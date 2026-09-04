import assert from "node:assert/strict";
import test from "node:test";
import type { ModelInvoker } from "@/lib/agent/model";
import { createRoleAgent } from "@/lib/agent/graph";
import { SnapshotRoleRuntime } from "@/lib/agent/snapshot-runtime";
import type { AgentEvent, AgentRequest } from "@/lib/agent/events";
import { compileProcessDraft, compileRolePackage, compileSemanticDraft, prepareBuildInput } from "@/lib/build/compiler";
import type { ColdStartRequest } from "@/lib/build/types";

function candidatePackage() {
  const request: ColdStartRequest = {
    runId: "run-candidate-agent",
    projectId: "project-candidate-agent",
    roleTitle: "大模型应用工程师",
    roleDescription: "研究任务、技能与实际工作过程。",
    market: "中国大陆",
    audience: ["高职学生", "教师"],
    snapshotAsOf: "2026-08-21",
    sources: [{
      title: "岗位实践资料",
      kind: "public_document",
      locator: "https://example.com/role-practice",
      content: "大模型应用工程师需要构建 RAG 系统，进行检索质量评测，并交付可运行的 RAG 服务。工作过程包括构建检索链路和形成服务。",
      sourceTier: "primary",
    }],
  };
  const prepared = prepareBuildInput(request);
  const evidenceId = prepared.segments.find((segment) => prepared.assets.find((asset) => asset.id === segment.sourceId)?.kind === "public_document")!.id;
  const semantic = compileSemanticDraft({
    request,
    assets: prepared.assets,
    segments: prepared.segments,
    draft: {
      roleSummary: "把大模型能力转化为可运行应用。",
      nodes: [
        { tempId: "task", type: "task", label: "RAG 系统构建", summary: "交付可运行的检索增强生成服务。", aliases: [], evidenceSegmentIds: [evidenceId], confidence: 0.86 },
        { tempId: "skill", type: "knowledge_skill", label: "检索质量评测", summary: "用数据与指标检查检索效果。", aliases: [], evidenceSegmentIds: [evidenceId], confidence: 0.8 },
      ],
      edges: [{ type: "requires_skill", sourceTempId: "task", targetTempId: "skill", evidenceSegmentIds: [evidenceId], confidence: 0.78 }],
    },
  });
  const process = compileProcessDraft({
    assets: prepared.assets,
    segments: prepared.segments,
    semanticNodes: semantic.nodes,
    draft: {
      scenarios: [{ tempId: "scenario", label: "交付 RAG 应用", summary: "从构建到形成服务。", trigger: "提出知识问答需求", outcome: "可运行服务", knowledgeState: "inferred_pattern", evidenceSegmentIds: [evidenceId] }],
      nodes: [
        { tempId: "event", scenarioTempId: "scenario", kind: "event", label: "构建 RAG 链路", summary: "实现检索与生成。", sequenceHint: 1, knowledgeState: "inferred_pattern", evidenceSegmentIds: [evidenceId] },
        { tempId: "artifact", scenarioTempId: "scenario", kind: "artifact", label: "RAG 服务", summary: "可运行的交付物。", sequenceHint: 2, knowledgeState: "inferred_pattern", evidenceSegmentIds: [evidenceId] },
      ],
      edges: [{ type: "produces", sourceTempId: "event", targetTempId: "artifact", evidenceSegmentIds: [evidenceId] }],
      bridges: [{ processTempId: "event", semanticLabel: "RAG 系统构建", type: "realizes_task", confidence: 0.8 }],
    },
  });
  return compileRolePackage({ request, brief: prepared.brief, assets: prepared.assets, segments: prepared.segments, semantic, process, laneFailures: [] });
}

test("项目 Agent 精确读取节点后组装任务关系、事理场景与来源，引用句柄只加一次括号", async () => {
  const result = candidatePackage();
  const task = result.semantic.nodes.find((node) => node.type === "task")!;
  let prompt = "";
  const model: ModelInvoker = async function* (input) {
    prompt = `${input.system}\n${input.user}`;
    yield { type: "reasoning", delta: "先核对任务和场景。" };
    yield { type: "text", delta: "该任务需要检索质量评测，并形成候选工作过程。[C1]" };
  };
  const graph = createRoleAgent(model, new SnapshotRoleRuntime(result));
  const request: AgentRequest = {
    runId: "run-candidate-answer",
    sessionId: "conversation-candidate-answer",
    message: "这个任务需要什么技能，实际流程和交付物是什么？",
    history: [],
    references: [{
      packageId: result.packages.rolePackage.packageId,
      packageVersion: result.packages.rolePackage.packageVersion,
      snapshotId: result.snapshot.id,
      targetId: task.id,
    }],
  };
  const events: AgentEvent[] = [];
  const stream = await graph.stream({ request }, { configurable: { thread_id: "candidate-project-agent" }, streamMode: "custom" });
  for await (const item of stream) events.push(item as AgentEvent);

  const plan = events.find((event) => event.kind === "plan.created")!;
  const calls = (plan.payload.calls as Array<{ name: string }>).map((call) => call.name);
  assert.ok(calls.includes("read_role_objects"));
  assert.ok(calls.includes("trace_work_process"));
  const registry = events.find((event) => event.kind === "citation.registry")!.payload.citations as Array<{ handle: string; sourceIds: string[] }>;
  assert.equal(registry[0].handle, "C1");
  assert.ok(registry.some((citation) => citation.sourceIds.length > 0));
  assert.match(prompt, /requires_skill/);
  assert.match(prompt, /交付 RAG 应用/);
  assert.match(prompt, /https:\/\/example\.com\/role-practice/);
  assert.ok(events.some((event) => event.kind === "answer.completed"));
});

test("项目 Agent 遇到风险问题时调用完整岗位健康审计并把风险簇交给模型", async () => {
  const result = candidatePackage();
  let prompt = "";
  const model: ModelInvoker = async function* (input) {
    prompt = input.user;
    yield { type: "text", delta: "当前岗位包存在事理证据边界风险。" };
  };
  const request: AgentRequest = {
    runId: "run-candidate-risk",
    sessionId: "conversation-candidate-risk",
    message: "检查这个岗位快照有哪些风险、证据缺口和语义重合",
    history: [],
    references: [],
  };
  const events: AgentEvent[] = [];
  const stream = await createRoleAgent(model, new SnapshotRoleRuntime(result)).stream(
    { request },
    { configurable: { thread_id: "candidate-risk-audit" }, streamMode: "custom" },
  );
  for await (const event of stream) events.push(event as AgentEvent);
  assert.ok(events.some((event) => event.kind === "tool.started" && event.payload.name === "audit_role_package"));
  assert.ok(events.some((event) => event.kind === "tool.finished" && event.payload.name === "audit_role_package"));
  assert.match(prompt, /health/);
  assert.match(prompt, /clusters/);
});
