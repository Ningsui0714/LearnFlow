import assert from "node:assert/strict";
import test from "node:test";
import { auditRoleSnapshot } from "@/lib/risk/audit";
import { rolePackageRuntime } from "@/lib/role-package/runtime";
import { projectWorkProcessPayload } from "@/lib/projects/presentation";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";

test("内置岗位包无生成地适配为完整快照 Skill 输入", () => {
  const source = rolePackageRuntime.package;
  const result = bundledRoleSnapshot();
  assert.equal(result.snapshot.id, source.manifest.snapshot_id);
  assert.equal(result.semantic.nodes.length, source.graph.nodes.length);
  assert.equal(result.semantic.edges.length, source.graph.edges.length);
  assert.equal(result.process.scenarios.length, source.workProcess.scenarios.length);
  assert.equal(result.process.nodes.length, source.workProcess.nodes.length);
  assert.equal(result.snapshot.sections.length, 6);
  assert.deepEqual(result.snapshot.sections.map((section) => section.id), [
    "overview", "tasks", "capabilities", "knowledge-skills", "work-process", "evidence-risks",
  ]);
  assert.ok(result.sources.evidenceBindings.length > 0);
  assert.ok(result.semantic.nodes.some((node) => node.type === "occupation_standard"));
  assert.ok(result.process.bridges.some((bridge) => bridge.processNodeId === "event:SC-01:03" && bridge.semanticNodeId === "ks:K-09" && bridge.type === "uses_skill"));
  const projection = projectWorkProcessPayload(result);
  assert.ok(projection.workProcess.scenarios.find((scenario) => scenario.id === "scenario:SC-01")?.task_refs.includes("task:T-01"));
  assert.ok(projection.workProcess.nodes.find((node) => node.id === "event:SC-01:03")?.knowledge_skill_refs?.includes("ks:K-09"));
});

test("内置静态快照可直接进入风险审计并保留证据与事理覆盖", () => {
  const result = bundledRoleSnapshot();
  const audit = auditRoleSnapshot(result);
  assert.equal(audit.snapshotId, result.snapshot.id);
  assert.ok(audit.metrics.evidenceCoverage > 0.5);
  assert.ok(audit.metrics.processCoverage > 0);
  assert.ok(audit.clusters.length > 0);
});
