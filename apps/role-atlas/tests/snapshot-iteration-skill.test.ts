import assert from "node:assert/strict";
import test from "node:test";
import type { ModelInvoker } from "@/lib/agent/model";
import { createSnapshotIterationSkill, mergeIterationSources } from "@/lib/iteration/graph";
import type { IterationEvent, SnapshotIterationRequest, SnapshotIterationResult } from "@/lib/iteration/types";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { reconstructSourceInputs } from "@/lib/risk/research";

const modelMustNotRun: ModelInvoker = async function* () {
  yield* [];
  throw new Error("关闭联网且没有附加资料时不应调用模型");
};

test("成熟快照迭代不会被冷启动的 20 项输入上限截断来源历史", () => {
  const base = bundledRoleSnapshot();
  const current = reconstructSourceInputs(base);
  assert.ok(current.length > 20);
  const incoming = { title: "新增研究来源", content: "用于补充本轮研究。", kind: "public_document" as const, locator: "https://example.com/new" };
  const merged = mergeIterationSources(current, [incoming], current.length + 1);
  assert.equal(merged.length, current.length + 1);
  assert.ok(merged.some((source) => source.locator === incoming.locator));
});

test("统一迭代 Skill 可自动发现并确定性修复协议错误，随后创建不可变快照", async () => {
  const base = structuredClone(bundledRoleSnapshot());
  base.semantic.edges.push({
    id: "edge:iteration-dangling",
    type: "requires_skill",
    source: base.semantic.nodes.find((node) => node.type === "task")!.id,
    target: "skill:iteration-missing",
    lifecycle: "candidate",
    confidence: 0.4,
    evidenceSegmentIds: [],
    evidenceBindingIds: [],
  });
  const request: SnapshotIterationRequest = {
    runId: "iteration-skill-test",
    snapshotRef: { snapshotId: base.snapshot.id },
    initiativeProfile: "autonomous",
    prompt: "",
    targetIds: [],
    supplementalSources: [],
    webResearch: false,
    maxRounds: 2,
    sourceLimit: 12,
    maxWorkItems: 10,
  };
  const graph = createSnapshotIterationSkill({ model: modelMustNotRun });
  const events: IterationEvent[] = [];
  const stream = await graph.stream({
    request,
    base,
    candidate: base,
    round: 1,
    opportunities: [],
    workItems: [],
    researchPlans: [],
    researchReports: [],
    researchedSources: [],
    patches: [],
    migrations: {},
  }, { configurable: { thread_id: "iteration-skill-test" }, streamMode: "custom" });
  for await (const event of stream) events.push(event as IterationEvent);
  const completed = events.findLast((event) => event.kind === "iteration.run.completed")!;
  const result = completed.payload.result as SnapshotIterationResult;
  assert.equal(result.createdSnapshot, true);
  assert.notEqual(result.candidate.snapshot.id, base.snapshot.id);
  assert.equal(result.candidate.semantic.edges.some((edge) => edge.id === "edge:iteration-dangling"), false);
  assert.equal(result.inspectionAfter.protocolValid, true);
  assert.ok(result.workItems.some((item) => item.status === "completed"), "评估应回写已被候选修复的工作项状态");
  assert.equal(result.candidate.audit.inspection?.protocolValid, true);
  assert.match(result.candidate.snapshot.sections.find((section) => section.id === "evidence-risks")!.summary, /任务缺少工作场景|节点简介信息不足/u);
  const kinds = new Set(events.map((event) => event.kind));
  for (const kind of ["iteration.contract.created", "iteration.inspection.completed", "iteration.work.plan.created", "iteration.consolidation.started", "iteration.patch.applied", "iteration.evaluation.started", "iteration.evaluation.completed", "iteration.run.completed"] as const) assert.ok(kinds.has(kind), `缺少 ${kind}`);
});

test("阶段检查点恢复会从下一节点继续，不重复契约和结构扫描", async () => {
  const base = bundledRoleSnapshot();
  const request: SnapshotIterationRequest = {
    runId: "iteration-resume-test",
    snapshotRef: { snapshotId: base.snapshot.id },
    initiativeProfile: "autonomous",
    prompt: "",
    targetIds: [],
    supplementalSources: [],
    webResearch: false,
    maxRounds: 1,
    sourceLimit: 8,
    maxWorkItems: 8,
  };
  let discovery: Record<string, unknown> | undefined;
  const first = createSnapshotIterationSkill({
    model: modelMustNotRun,
    onCheckpoint: async (phase, state) => { if (phase === "discovery") discovery = state; },
  });
  await first.invoke({
    request,
    base,
    candidate: base,
    round: 1,
    opportunities: [],
    workItems: [],
    researchPlans: [],
    researchReports: [],
    researchedSources: [],
    patches: [],
    migrations: {},
  }, { configurable: { thread_id: "iteration-resume-seed" } });
  assert.ok(discovery);

  const resumed = createSnapshotIterationSkill({ model: modelMustNotRun });
  const events: IterationEvent[] = [];
  const stream = await resumed.stream({
    round: 1,
    opportunities: [],
    workItems: [],
    researchPlans: [],
    researchReports: [],
    researchedSources: [],
    patches: [],
    migrations: {},
    ...discovery,
    request,
    base,
    candidate: base,
    resumeFrom: "discovery",
  }, { configurable: { thread_id: "iteration-resume-run" }, streamMode: "custom" });
  for await (const event of stream) events.push(event as IterationEvent);
  const kinds = new Set(events.map((event) => event.kind));
  assert.equal(kinds.has("iteration.contract.created"), false);
  assert.equal(kinds.has("iteration.inspection.started"), false);
  assert.equal(kinds.has("iteration.research.plan.created"), true);
  assert.equal(kinds.has("iteration.run.completed"), true);
});
