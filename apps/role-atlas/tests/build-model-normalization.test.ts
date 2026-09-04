import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeProcessDraft,
  normalizeSemanticDraft,
  processDraftSchema,
  semanticDraftSchema,
} from "@/lib/build/model";
import { normalizeTaskBarrier, taskBarrierSchema } from "@/lib/build/workflow-model";
import type { ConceptMention } from "@/lib/build/types";
import { capabilityDerivationSchema, capabilityToSemanticDraft } from "@/lib/build/workflow-model";

test("结构化语义抽取只修复枚举别名并隔离无法识别的节点", () => {
  const parsed = semanticDraftSchema.parse(normalizeSemanticDraft({
    roleSummary: "岗位摘要",
    nodes: [
      { tempId: "n1", type: "role", label: "岗位", summary: "岗位边界", evidenceSegmentIds: ["seg:1"], confidence: 0.8 },
      { tempId: "n2", type: "skill", label: "故障诊断", summary: "可学习技能", evidenceSegmentIds: ["seg:2"], confidence: 0.7 },
      { tempId: "bad", type: "task|skill", label: "错误联合值", summary: "不能进入图谱" },
    ],
    edges: [],
  }));
  assert.deepEqual(parsed.nodes.map((node) => node.type), ["market_role", "knowledge_skill"]);
  assert.equal(parsed.nodes.some((node) => node.tempId === "bad"), false);
});

test("事理抽取把 null 可选值归一化，并依据关系补全对象所属场景", () => {
  const parsed = processDraftSchema.parse(normalizeProcessDraft({
    scenarios: [{ tempId: "s1", label: "故障处置", summary: "现场故障闭环", knowledgeState: "documented", evidenceSegmentIds: ["seg:1"] }],
    nodes: [
      { tempId: "e1", scenarioTempId: "s1", kind: "step", label: "确认告警", summary: "确认异常", sequenceHint: 1, evidenceSegmentIds: ["seg:1"] },
      { tempId: "a1", scenarioTempId: null, kind: "participant", label: "运维员", summary: "执行处置", sequenceHint: null, evidenceSegmentIds: ["seg:1"] },
    ],
    edges: [{ type: "performed_by", sourceTempId: "e1", targetTempId: "a1", evidenceSegmentIds: ["seg:1"] }],
    bridges: [],
  }));
  assert.equal(parsed.nodes[1].scenarioTempId, "s1");
  assert.equal(parsed.nodes[1].sequenceHint, undefined);
  assert.equal(parsed.nodes[1].kind, "actor");
  assert.equal(parsed.scenarios[0].knowledgeState, "documented_norm");
});

test("语义分层先限界再校验，模型超量输出不会让整张图回退为空", () => {
  const oversized = {
    roleSummary: "候选岗位摘要",
    nodes: Array.from({ length: 120 }, (_, index) => ({
      tempId: `t${index}`,
      type: "task",
      label: `交付模型能力模块 ${index}`,
      summary: "将需求实现为可验收的模型能力模块。",
      evidenceSegmentIds: ["seg:1"],
      confidence: 0.7,
    })),
    edges: Array.from({ length: 220 }, (_, index) => ({
      type: "related_to",
      sourceTempId: `t${index % 120}`,
      targetTempId: `t${(index + 1) % 120}`,
      evidenceSegmentIds: ["seg:1"],
      confidence: 0.6,
    })),
  };
  const parsed = semanticDraftSchema.parse(normalizeSemanticDraft(oversized, {
    allowedNodeTypes: ["task"],
    maxNodes: 24,
    maxEdges: 40,
  }));
  assert.equal(parsed.nodes.length, 24);
  assert.ok(parsed.edges.length <= 40);
  assert.ok(parsed.edges.every((edge) => parsed.nodes.some((node) => node.tempId === edge.sourceTempId) && parsed.nodes.some((node) => node.tempId === edge.targetTempId)));
});

test("非招聘教学岗位的事理森林会隔离面试、课程和学习路径伪场景", () => {
  const parsed = processDraftSchema.parse(normalizeProcessDraft({
    scenarios: [
      { tempId: "bad", label: "面试与学习路径", summary: "整理面经并观看课程。", trigger: "准备求职", outcome: "完成面试", evidenceSegmentIds: ["seg:1"] },
      { tempId: "good", label: "模型训练与验收", summary: "从数据准备到评测交付。", trigger: "收到训练需求", outcome: "形成评测报告", evidenceSegmentIds: ["seg:2"] },
    ],
    nodes: [
      { tempId: "bad-e", scenarioTempId: "bad", kind: "event", label: "整理面经", summary: "准备应聘。", evidenceSegmentIds: ["seg:1"] },
      { tempId: "good-e", scenarioTempId: "good", kind: "event", label: "运行训练与评测", summary: "形成模型和评测结果。", evidenceSegmentIds: ["seg:2"] },
    ],
    edges: [],
    bridges: [],
  }, { roleTitle: "大模型算法工程师", rejectOffScope: true }));
  assert.deepEqual(parsed.scenarios.map((scenario) => scenario.tempId), ["good"]);
  assert.deepEqual(parsed.nodes.map((node) => node.tempId), ["good-e"]);
});

test("任务屏障按行动主体隔离产品用户和相邻岗位，不删除原子证据", () => {
  const mentions: ConceptMention[] = [
    {
      id: "mention:target",
      runId: "run",
      createdByWorkItem: "work",
      kind: "work_event",
      surfaceForm: "构建自助服务模板",
      normalizedForm: "构建自助服务模板",
      definitionHint: "平台团队构建可复用模板。",
      attributes: { actor: "平台工程团队", actorRelation: "target_team", deliverable: "服务模板" },
      sourceSegmentId: "seg:1",
      confidence: 0.8,
    },
    {
      id: "mention:user",
      runId: "run",
      createdByWorkItem: "work",
      kind: "work_event",
      surfaceForm: "一键发布应用",
      normalizedForm: "一键发布应用",
      definitionHint: "开发人员通过平台发布应用。",
      attributes: { actor: "开发人员", actorRelation: "external_user", deliverable: "已发布应用" },
      sourceSegmentId: "seg:2",
      confidence: 0.8,
    },
  ];
  const parsed = taskBarrierSchema.parse(normalizeTaskBarrier({
    roleSummary: "平台工程岗位",
    tasks: [
      { tempId: "target", label: "构建自助服务模板", summary: "形成模板。", mentionIds: ["mention:target"], confidence: 0.8 },
      { tempId: "user", label: "执行应用一键发布", summary: "发布应用。", mentionIds: ["mention:user"], confidence: 0.8 },
    ],
    roleContexts: [],
  }, mentions));
  assert.deepEqual(parsed.tasks.map((task) => task.tempId), ["target"]);
  assert.equal(mentions.length, 2, "外部用户事件仍保留在 Mention 证据层");
});

test("能力单元携带可日常落实的完整培养契约", () => {
  const draft = capabilityDerivationSchema.parse({ capabilities: [{
    tempId: "cap:diagnosis", label: "系统诊断能力", summary: "定位跨组件故障", situations: "系统运行异常",
    observableBehaviors: ["根据 trace 缩小故障范围"], qualityStandard: "结论可复查",
    taskTempIds: ["task:one", "task:two"], mentionIds: [], confidence: 0.7,
    units: [{
      tempId: "unit:trace", label: "分析失败 trace", summary: "从执行记录定位失败位置",
      observableBehavior: "标注输入、决策、调用和返回中的异常",
      practiceSituation: "每周故障案例复盘", microPractice: "分析一条失败 trace 并提出修复假设",
      practiceFrequency: "每周一次", feedbackSignal: "定位是否准确且能被日志复核",
      evidenceArtifact: "故障定位表和回归测试", progression: "从标注示例到独立诊断陌生链路",
      independenceCriterion: "能独立定位并通过回归验证修复",
    }],
  }] });
  const result = capabilityToSemanticDraft({
    draft,
    tasks: [
      { tempId: "task:one", type: "task", label: "任务一", summary: "", aliases: [], evidenceSegmentIds: ["seg:1"], confidence: 0.7 },
      { tempId: "task:two", type: "task", label: "任务二", summary: "", aliases: [], evidenceSegmentIds: ["seg:2"], confidence: 0.7 },
    ],
    mentions: [],
  });
  const unit = result.nodes.find(node => node.type === "capability_unit");
  assert.equal(unit?.cultivation?.practiceFrequency, "每周一次");
  assert.match(unit?.cultivation?.evidenceArtifact || "", /回归测试/u);
});
