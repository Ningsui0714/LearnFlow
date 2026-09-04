import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import RoleCardView, { type RoleCardNode } from "@/app/components/RoleCardView";

const evidence = {
  binding_refs: ["binding:1"],
  source_refs: ["source:1"],
  max_confidence: 0.88,
  has_segment_evidence: true,
  temporal_status_counts: { current: 1 },
};

const nodes: RoleCardNode[] = [
  {
    id: "task:delivery",
    type: "task",
    label: "交付智能体应用",
    summary: "将需求转化为可验证、可发布的智能体应用。",
    ring: 2,
    lifecycle: "accepted",
    assertion_refs: ["assertion:1"],
    evidence_summary: evidence,
    data: { deliverable: "可运行应用与验收报告" },
    granularity: "kernel",
  },
  {
    id: "skill:retrieval",
    type: "knowledge_skill",
    label: "混合检索与融合排序",
    summary: "组合稀疏、稠密检索并进行结果融合。",
    ring: 5,
    lifecycle: "candidate",
    assertion_refs: ["assertion:2"],
    evidence_summary: evidence,
    data: { assessment: "构建可复现检索评测" },
    granularity: "detail",
  },
];

test("卡片总览按维度纵向组织，并提供横向浏览、展开和引用动作", () => {
  const html = renderToStaticMarkup(createElement(RoleCardView, {
    nodes,
    edges: [{ source: "task:delivery", target: "skill:retrieval" }],
    selectedId: "task:delivery",
    onSelect() {},
    onReference() {},
    onDragStart() {},
    onDragEnd() {},
  }));

  assert.match(html, /岗位卡片总览/);
  assert.match(html, /典型工作任务/);
  assert.match(html, /知识点与技能点/);
  assert.match(html, /向左浏览典型工作任务/);
  assert.match(html, /向右浏览知识点与技能点/);
  assert.match(html, /可运行应用与验收报告/);
  assert.match(html, /引用到对话/);
});
