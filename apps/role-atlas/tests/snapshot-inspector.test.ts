import assert from "node:assert/strict";
import test from "node:test";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { inspectSnapshot } from "@/lib/iteration/inspector";

test("结构检查只把协议不变量标为硬阻断", () => {
  const snapshot = structuredClone(bundledRoleSnapshot());
  snapshot.semantic.edges.push({
    id: "edge:test-dangling",
    type: "requires_skill",
    source: snapshot.semantic.nodes.find((node) => node.type === "task")!.id,
    target: "skill:does-not-exist",
    lifecycle: "candidate",
    confidence: 0.4,
    evidenceSegmentIds: [],
    evidenceBindingIds: [],
  });
  const inspection = inspectSnapshot(snapshot, { now: `${snapshot.snapshot.asOf}T12:00:00Z` });
  assert.equal(inspection.protocolValid, false);
  assert.ok(inspection.hardBlockers.some((finding) => finding.code === "DANGLING_SEMANTIC_EDGE"));
  assert.ok(inspection.findings.some((finding) => !finding.hardBlocker));
});

test("任务知识技能不足形成研究发现而不是数量门禁", () => {
  const snapshot = structuredClone(bundledRoleSnapshot());
  const taskIds = new Set(snapshot.semantic.nodes.filter((node) => node.type === "task").map((node) => node.id));
  const skillIds = new Set(snapshot.semantic.nodes.filter((node) => node.type === "knowledge_skill").map((node) => node.id));
  snapshot.semantic.edges = snapshot.semantic.edges.filter((edge) => !(taskIds.has(edge.source) && skillIds.has(edge.target)));
  const inspection = inspectSnapshot(snapshot, { now: `${snapshot.snapshot.asOf}T12:00:00Z` });
  assert.ok(inspection.coverage.tasksWithoutSkills > 0);
  assert.ok(inspection.findings.some((finding) => finding.code === "TASK_SKILL_GAP" && finding.classification === "research" && !finding.hardBlocker));
  assert.ok(inspection.agentProbes.some((probe) => probe.id === "probe:evidence-resolution"));
});

test("无法解析的证据绑定属于协议不变量，而不是可忽略的质量分", () => {
  const snapshot = structuredClone(bundledRoleSnapshot());
  snapshot.sources.evidenceBindings[0].segmentId = "segment:missing";
  const inspection = inspectSnapshot(snapshot, { now: `${snapshot.snapshot.asOf}T12:00:00Z` });
  assert.equal(inspection.protocolValid, false);
  assert.ok(inspection.hardBlockers.some((finding) => finding.code === "AGENT_EVIDENCE_RESOLUTION"));
});

test("只有岗位根节点的空壳快照不会再得到满分结构、语义与 Agent 可用性", () => {
  const snapshot = structuredClone(bundledRoleSnapshot());
  const role = snapshot.semantic.nodes.find((node) => node.type === "market_role")!;
  snapshot.semantic.nodes = [role];
  snapshot.semantic.edges = [];
  snapshot.semantic.claims = [];
  snapshot.process.scenarios = [];
  snapshot.process.nodes = [];
  snapshot.process.edges = [];
  snapshot.process.bridges = [];
  for (const section of snapshot.snapshot.sections) {
    if (["tasks", "capabilities", "knowledge-skills", "work-process"].includes(section.id)) section.itemIds = [];
  }
  const inspection = inspectSnapshot(snapshot, { now: `${snapshot.snapshot.asOf}T12:00:00Z` });
  assert.ok(inspection.axes.structuralValidity < 50);
  assert.equal(inspection.axes.semanticClarity, 0);
  assert.ok(inspection.axes.agentUsability < 70);
  assert.equal(inspection.agentProbes.find((probe) => probe.id === "probe:graph-traversal")?.status, "failed");
  assert.equal(inspection.agentProbes.find((probe) => probe.id === "probe:snapshot-context")?.status, "failed");
});
