import assert from "node:assert/strict";
import test from "node:test";
import { createRoleAgent } from "@/lib/agent/graph";
import type { AgentRequest } from "@/lib/agent/events";
import { buildGroundedPrompt, bundleToolResults } from "@/lib/agent/grounding";
import { planRoleTools } from "@/lib/agent/planner";
import { createNodeReference, rolePackageRuntime } from "@/lib/role-package/runtime";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";

function unifiedReference(targetId: string) {
  const result = bundledRoleSnapshot();
  return {
    packageId: result.packages.rolePackage.packageId,
    packageVersion: result.packages.rolePackage.packageVersion,
    snapshotId: result.snapshot.id,
    targetId,
  };
}

test("规划器优先精确读取所选节点，调用数始终有界", () => {
  const request: AgentRequest = {
    runId: "run-plan",
    sessionId: "session-plan",
    message: "比较这两个任务的证据、关系、学习路径与语义风险",
    references: [createNodeReference("task:T-02"), createNodeReference("task:T-03")],
    history: [],
  };
  const plan = planRoleTools(request);
  assert.equal(plan[0].name, "read_role_objects");
  assert.ok(plan.some((call) => call.name === "query_role_graph"));
  assert.ok(plan.some((call) => call.name === "inspect_role_evidence"));
  assert.ok(plan.some((call) => call.name === "audit_role_package"));
  assert.ok(plan.length <= 4);
});

test("事理问题会读取任务包与候选事件链，并保持调用有界", () => {
  const request: AgentRequest = {
    runId: "run-process-plan",
    sessionId: "session-process-plan",
    message: "这个任务在真实工作中一般怎么做，有哪些交接、分支、返工和交付物？",
    references: [createNodeReference("task:T-03")],
    history: [],
  };
  const plan = planRoleTools(request);
  assert.ok(plan.some((call) => call.name === "read_role_objects"));
  assert.ok(plan.some((call) => call.name === "trace_work_process"));
  assert.ok(plan.length <= 4);
});

test("提示词把岗位上下文和引用注册表交给模型，但不设置输出门禁", async () => {
  const toolResult = await rolePackageRuntime.execute({ name: "read_role_objects", args: { targets: ["task:T-02"] } }, crypto.randomUUID());
  toolResult.citations[0].handle = "C1";
  const bundle = bundleToolResults([toolResult], toolResult.citations);
  const prompt = buildGroundedPrompt("RAG 调优的重点是什么？", [], bundle);
  assert.match(prompt.user, /"handle":"C1"/);
  assert.match(prompt.user, /系统会原样展示你的输出/);
  assert.doesNotMatch(prompt.system, /不要展示内部思维过程/);
});

test("LangGraph 原样、实时转发模型的思考与正文，不再发送门禁事件", async () => {
  const request: AgentRequest = {
    runId: crypto.randomUUID(),
    sessionId: crypto.randomUUID(),
    message: "RAG 系统构建与调优的重点是什么？",
    references: [unifiedReference("task:T-02")],
    history: [],
  };
  const rawReasoning = "先检查上下文，再回答。";
  const rawAnswer = "<script>保持原样</script> 未注册引用也不拦截。[C999]";
  const agent = createRoleAgent(async function* () {
    yield { type: "reasoning" as const, delta: rawReasoning.slice(0, 6) };
    yield { type: "reasoning" as const, delta: rawReasoning.slice(6) };
    yield { type: "text" as const, delta: rawAnswer.slice(0, 12) };
    yield { type: "text" as const, delta: rawAnswer.slice(12) };
  });
  const events: Array<{ kind: string; payload: Record<string, unknown> }> = [];
  for await (const event of await agent.stream(
    { request },
    { configurable: { thread_id: crypto.randomUUID() }, streamMode: "custom" },
  )) events.push(event as { kind: string; payload: Record<string, unknown> });

  const kinds = events.map((event) => event.kind);
  assert.ok(kinds.includes("snapshot.pinned"));
  assert.ok(kinds.includes("tool.finished"));
  assert.ok(kinds.includes("coverage.checked"));
  assert.ok(kinds.includes("citation.registry"));
  assert.ok(kinds.includes("reasoning.delta"));
  assert.ok(kinds.includes("reasoning.completed"));
  assert.ok(kinds.includes("answer.completed"));
  assert.equal(kinds.includes("citation.gate"), false);
  assert.ok(kinds.indexOf("reasoning.delta") < kinds.indexOf("answer.delta"));
  assert.equal(events.filter((event) => event.kind === "reasoning.delta").map((event) => event.payload.delta).join(""), rawReasoning);
  assert.equal(events.filter((event) => event.kind === "answer.delta").map((event) => event.payload.delta).join(""), rawAnswer);
  assert.equal(events.find((event) => event.kind === "answer.completed")?.payload.answer, rawAnswer);
});
