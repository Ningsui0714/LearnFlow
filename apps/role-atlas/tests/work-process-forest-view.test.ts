import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import WorkProcessForestView, { type WorkProcessPayload } from "@/app/components/WorkProcessForestView";
import type { RoleCardNode } from "@/app/components/RoleCardView";
import generated from "@/lib/role-package/generated-data.json";

test("事理森林并列展示场景树、事件分支、返工与引用动作", () => {
  const payload: WorkProcessPayload = {
    manifest: generated.workProcessManifest as WorkProcessPayload["manifest"],
    validation: generated.workProcessValidation as WorkProcessPayload["validation"],
    workProcess: generated.workProcess as WorkProcessPayload["workProcess"],
  };
  const html = renderToStaticMarkup(createElement(WorkProcessForestView, {
    payload,
    query: "",
    selectedId: "event:SC-01:01",
    onSelect() {},
    onReference() {},
    onDragStart() {},
    onDragEnd() {},
  }));
  assert.equal((html.match(/forest-index/g) || []).length, 1);
  assert.match(html, /工作场景森林/);
  assert.match(html, /从模糊需求到可发布 Agent 应用/);
  assert.match(html, /条件分支|分支/);
  assert.match(html, /返工/);
  assert.match(html, /引用场景/);
  assert.match(html, /候选工作模式/);
});

test("任务事理视角只列出相关场景，并把知识技能附着到工作事件", () => {
  const payload: WorkProcessPayload = {
    manifest: generated.workProcessManifest as WorkProcessPayload["manifest"],
    validation: generated.workProcessValidation as WorkProcessPayload["validation"],
    workProcess: generated.workProcess as WorkProcessPayload["workProcess"],
  };
  const html = renderToStaticMarkup(createElement(WorkProcessForestView, {
    payload,
    query: "",
    taskId: "task:T-03",
    semanticNodes: generated.graph.nodes as RoleCardNode[],
    embedded: true,
    selectedId: "event:SC-01:04",
    onSelect() {},
    onReference() {},
    onDragStart() {},
    onDragEnd() {},
  }));
  assert.match(html, /任务事理场景/);
  assert.match(html, /此步使用/);
  assert.match(html, /Agent 编排范式/);
  assert.doesNotMatch(html, /新模型、框架或协议的采用评估/);
});

test("旧岗位包只有任务知识关系时也会在明确匹配的事件上显示技能", () => {
  const payload: WorkProcessPayload = {
    manifest: generated.workProcessManifest as WorkProcessPayload["manifest"],
    validation: generated.workProcessValidation as WorkProcessPayload["validation"],
    workProcess: {
      ...generated.workProcess as WorkProcessPayload["workProcess"],
      nodes: (generated.workProcess.nodes as WorkProcessPayload["workProcess"]["nodes"]).map((node) => ({ ...node, knowledge_skill_refs: [] })),
    },
  };
  const fallbackSkill = (generated.graph.nodes as RoleCardNode[]).find((node) => node.label.includes("Agent 编排范式"));
  assert.ok(fallbackSkill);
  const html = renderToStaticMarkup(createElement(WorkProcessForestView, {
    payload,
    query: "",
    taskId: "task:T-03",
    semanticNodes: generated.graph.nodes as RoleCardNode[],
    taskKnowledgeSkills: [fallbackSkill],
    embedded: true,
    selectedId: "event:SC-01:04",
    onSelect() {},
    onReference() {},
    onDragStart() {},
    onDragEnd() {},
  }));
  assert.match(html, /此步使用/);
  assert.match(html, /Agent 编排范式/);
});
