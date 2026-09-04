import assert from "node:assert/strict";
import test from "node:test";
import { carryKernelPresentation } from "@/lib/build/kernel";
import type { ColdStartBuildResult, SemanticNode } from "@/lib/build/types";

function node(id: string, type: SemanticNode["type"], label: string, confidence = 0.8): SemanticNode {
  return {
    id,
    type,
    label,
    summary: `能够完成${label}。`,
    aliases: [],
    lifecycle: "candidate",
    confidence,
    evidenceSegmentIds: ["seg:test"],
    evidenceBindingIds: ["binding:test"],
    ring: type === "market_role" ? 0 : 1,
  };
}

test("后台知识增量只把技能簇代表放入默认雷达，近义节点仍保留为 facet", () => {
  const role = { ...node("role:test", "market_role", "DevOps 平台工程师", 0.9), defaultVisibility: true };
  const base = { semantic: { nodes: [role], edges: [], claims: [] } } as unknown as ColdStartBuildResult;
  const nodes = [
    role,
    node("skill:k8s-ops", "knowledge_skill", "Kubernetes 容器平台管理与运维", 0.9),
    node("skill:k8s-deploy", "knowledge_skill", "基于 Kubernetes 的容器化应用部署与管理", 0.86),
    node("skill:jenkins-build", "knowledge_skill", "Jenkins CI/CD 流水线构建与自动化操作", 0.88),
    node("skill:jenkins-run", "knowledge_skill", "基于 Jenkins 的 CI/CD 流水线构建与执行", 0.84),
    node("skill:ansible", "knowledge_skill", "使用 Ansible 实现基础设施自动化配置", 0.82),
    node("skill:diagnosis", "knowledge_skill", "生产环境应用问题诊断与排查", 0.8),
    node("skill:scripting", "knowledge_skill", "Shell 与 Python 运维脚本编写", 0.78),
  ];

  const projected = carryKernelPresentation(nodes, base, "semantic");
  const visibleSkills = projected.filter((item) => item.type === "knowledge_skill" && item.defaultVisibility !== false);
  assert.ok(visibleSkills.length <= 5);
  assert.equal(visibleSkills.filter((item) => item.label.toLowerCase().includes("kubernetes")).length, 1);
  assert.equal(visibleSkills.filter((item) => item.label.toLowerCase().includes("jenkins")).length, 1);
  assert.equal(projected.filter((item) => item.type === "knowledge_skill").length, 7, "事实层不得因投影去重而丢节点");
  const hiddenNearDuplicates = projected.filter((item) => item.type === "knowledge_skill" && item.defaultVisibility === false && item.parentKernelId);
  assert.ok(hiddenNearDuplicates.length >= 2, "被折叠的同技术细项必须能回到代表节点");
});
