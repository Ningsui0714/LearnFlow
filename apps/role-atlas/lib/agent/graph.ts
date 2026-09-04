import { END, getWriter, START, StateGraph, StateSchema } from "@langchain/langgraph";
import { z } from "zod/v4";
import { assignCitationHandles } from "@/lib/role-package/runtime";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import type { RoleToolCall, ToolCitation, ToolEnvelope } from "@/lib/role-package/types";
import type { AgentContextBundle, AgentEvent, AgentEventKind, AgentRequest } from "./events";
import { buildGroundedPrompt, bundleToolResults } from "./grounding";
import type { ModelInvoker } from "./model";
import { planRoleTools, TOOL_PURPOSES } from "./planner";
import { SnapshotRoleRuntime, type CoreRoleToolName } from "./snapshot-runtime";

const AgentState = new StateSchema({
  request: z.custom<AgentRequest>(),
  plan: z.array(z.custom<RoleToolCall>()).default(() => []),
  toolResults: z.array(z.custom<ToolEnvelope>()).default(() => []),
  citations: z.array(z.custom<ToolCitation>()).default(() => []),
  bundle: z.custom<AgentContextBundle>().optional(),
  reasoning: z.string().default(""),
  finalAnswer: z.string().default(""),
});

export function createRoleAgent(
  modelInvoker: ModelInvoker,
  runtime = new SnapshotRoleRuntime(bundledRoleSnapshot()),
) {
  let seq = 0;

  function emit(request: AgentRequest, kind: AgentEventKind, payload: Record<string, unknown>) {
    const writer = getWriter();
    const event: AgentEvent = {
      version: "1.1",
      runId: request.runId,
      sessionId: request.sessionId,
      seq: seq += 1,
      time: new Date().toISOString(),
      kind,
      payload,
    };
    writer?.(event);
  }

  const validate = async (state: typeof AgentState.State) => {
    emit(state.request, "run.started", { messageLength: state.request.message.length, referenceCount: state.request.references.length });
    runtime.validateReferences(state.request.references);
    const status = runtime.descriptor;
    emit(state.request, "snapshot.pinned", {
      ...status,
    });
    return { plan: [], toolResults: [], citations: [], bundle: undefined, reasoning: "", finalAnswer: "" };
  };

  const plan = async (state: typeof AgentState.State) => {
    const calls = planRoleTools(state.request);
    emit(state.request, "plan.created", {
      calls: calls.map((call) => ({ name: call.name, purpose: TOOL_PURPOSES[call.name as CoreRoleToolName] })),
      callCount: calls.length,
    });
    return { plan: calls };
  };

  const executeTools = async (state: typeof AgentState.State) => {
    for (const call of state.plan) emit(state.request, "tool.started", { name: call.name, args: call.args });
    const results = await Promise.all(state.plan.map(async (call) => {
      const result = await runtime.execute(call, state.request.runId);
      emit(state.request, result.diagnostics.deduplicated ? "tool.deduplicated" : "tool.finished", {
        name: call.name,
        ok: result.ok,
        returned: result.coverage.returned,
        coverageComplete: result.coverage.complete,
        warningCount: result.warnings.length,
        durationMs: result.diagnostics.durationMs,
        error: result.error,
      });
      return result;
    }));
    return { toolResults: results };
  };

  const checkCoverage = async (state: typeof AgentState.State) => {
    let results = state.toolResults;
    let citations = assignCitationHandles(results.flatMap((result) => result.citations));
    let supplemented = false;
    if (citations.length === 0) {
      supplemented = true;
      const supplementCall: RoleToolCall = {
        name: "search_role_knowledge",
        args: { query: state.request.message || "大模型应用工程师 核心任务 能力 知识技能", topK: 8, includeCandidate: true },
      };
      emit(state.request, "tool.started", { name: supplementCall.name, args: supplementCall.args, supplement: true });
      const supplement = await runtime.execute(supplementCall, `${state.request.runId}:supplement`);
      emit(state.request, "tool.finished", {
        name: supplementCall.name,
        ok: supplement.ok,
        returned: supplement.coverage.returned,
        coverageComplete: supplement.coverage.complete,
        warningCount: supplement.warnings.length,
        durationMs: supplement.diagnostics.durationMs,
        supplement: true,
      });
      results = [...results, supplement];
      citations = assignCitationHandles(results.flatMap((result) => result.citations));
    }
    const bundle = bundleToolResults(results, citations);
    emit(state.request, "coverage.checked", {
      complete: bundle.coverageComplete,
      citationCount: citations.length,
      successfulTools: results.filter((result) => result.ok).length,
      failedTools: results.filter((result) => !result.ok).length,
      supplemented,
    });
    emit(state.request, "context.assembled", {
      chars: bundle.context.length,
      semanticCitations: citations.filter((citation) => citation.artifactKind !== "work_process").length,
      processCitations: citations.filter((citation) => citation.artifactKind === "work_process").length,
      includedTools: results.filter((result) => result.ok && result.context).map((result) => result.tool),
    });
    return { toolResults: results, citations, bundle };
  };

  const synthesize = async (state: typeof AgentState.State, config: { signal?: AbortSignal }) => {
    const bundle = state.bundle!;
    emit(state.request, "citation.registry", {
      citations: bundle.citations.map((citation) => ({
        handle: citation.handle,
        targetId: citation.targetId,
        label: citation.label,
        lifecycle: citation.lifecycle,
        confidence: citation.confidence,
        sourceIds: citation.sourceIds,
        sourceTitles: citation.sourceTitles,
        temporalStatus: citation.temporalStatus,
        artifactKind: citation.artifactKind,
        knowledgeState: citation.knowledgeState,
      })),
    });
    emit(state.request, "generation.started", { contextChars: bundle.context.length, citationCount: bundle.citations.length });
    const prompt = buildGroundedPrompt(state.request.message, state.request.history, bundle);
    let reasoning = "";
    let answer = "";
    for await (const part of modelInvoker({ ...prompt, signal: config.signal })) {
      if (part.type === "reasoning") {
        reasoning += part.delta;
        emit(state.request, "reasoning.delta", { delta: part.delta });
      } else {
        answer += part.delta;
        emit(state.request, "answer.delta", { delta: part.delta });
      }
    }
    emit(state.request, "reasoning.completed", { chars: reasoning.length });
    emit(state.request, "answer.completed", {
      answer,
      reasoning,
      outputMode: "provider_raw",
    });
    return { reasoning, finalAnswer: answer };
  };

  return new StateGraph(AgentState)
    .addNode("validate", validate)
    .addNode("plan_tools", plan)
    .addNode("execute_tools", executeTools)
    .addNode("check_coverage", checkCoverage)
    .addNode("synthesize_answer", synthesize)
    .addEdge(START, "validate")
    .addEdge("validate", "plan_tools")
    .addEdge("plan_tools", "execute_tools")
    .addEdge("execute_tools", "check_coverage")
    .addEdge("check_coverage", "synthesize_answer")
    .addEdge("synthesize_answer", END)
    .compile({ checkpointer: false });
}
