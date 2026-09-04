import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { buildRoleLearningProjection } from "@/lib/learning-path/projection";
import { learningPathGraphInputSchema, type SemanticNode } from "@/lib/build/types";

function semanticNode(id: string, type: SemanticNode["type"], label: string, summary = ""): SemanticNode {
  return {
    id, type, label, summary, aliases: [], lifecycle: "candidate", confidence: 0.7,
    evidenceSegmentIds: ["seg:1"], evidenceBindingIds: ["binding:1"], ring: type === "capability_unit" ? 4 : 5,
  };
}

const graph = {
  protocolVersion: "learnflow-learning-path/v1" as const,
  nodes: [
    { id: "agent-engineering", title: "Agent 工程", summary: "智能体系统工程", aliases: ["智能体工程"], domains: ["AI 与智能体"], audiences: ["vocational" as const], stage: "advanced" as const, order: 7, origin: "official" as const, sourceRefs: ["source:course"] },
    { id: "software-testing", title: "软件测试", summary: "测试设计与执行", aliases: [], domains: ["软件工程"], audiences: ["vocational" as const], stage: "core" as const, order: 4, origin: "official" as const, sourceRefs: ["source:standard"] },
  ],
  edges: [{ id: "edge:1", from: "software-testing", to: "agent-engineering", kind: "soft_prerequisite" as const, rationale: "先建立测试基础", origin: "official" as const }],
};

test("同步制品符合 LearnFlow 共享学习路径协议", () => {
  const synced = learningPathGraphInputSchema.parse(JSON.parse(readFileSync("public/data/learnflow-learning-path.json", "utf8")));
  assert.ok(synced);
  assert.ok(synced!.nodes.length >= 90);
  assert.ok(synced!.edges.length >= 140);
});

test("岗位知识技能按 LearnFlow 协议形成精确、歧义或缺口映射而不写个人状态", () => {
  const projection = buildRoleLearningProjection({
    graph,
    snapshotId: "snapshot:role@2026-09-02",
    semanticNodes: [
      semanticNode("skill:agent", "knowledge_skill", "智能体工程"),
      semanticNode("unit:trace", "capability_unit", "分析 Agent 失败 trace", "定位智能体执行失败"),
    ],
    assets: [{
      id: "source:1", title: "岗位实践", kind: "public_document", locator: "https://example.com/practice",
      contentHash: "hash", visibility: "publishable_metadata", qualification: { status: "accepted", evidenceRoles: ["work_practice"], reasons: [] },
    }],
    evidenceBindings: [{ id: "binding:1", targetId: "skill:agent", fieldPath: "summary", sourceId: "source:1", segmentId: "seg:1", support: "direct", method: "model_extraction", confidence: 0.8 }],
  });
  assert.ok(projection);
  assert.equal(projection!.authority, "learnflow");
  assert.equal(projection!.bindings[0].mappingMode, "exact");
  assert.equal(projection!.bindings[0].learningPathNodeId, "agent-engineering");
  assert.equal(projection!.bindings[1].relation, "practices");
  assert.ok(projection!.bindings.every(binding => !("learnerStatus" in binding)), "岗位投影不得写学习者状态");
});
