import assert from "node:assert/strict";
import test from "node:test";
import { compileProcessDraft } from "@/lib/build/compiler";
import type { ProcessDraft } from "@/lib/build/model";
import type { SemanticNode, SourceAsset, SourceSegment } from "@/lib/build/types";

const source: SourceAsset = {
  id: "src:standard",
  title: "职业标准",
  kind: "public_document",
  contentHash: "hash",
  visibility: "publishable_metadata",
};

const segment: SourceSegment = {
  id: "seg:maintenance",
  sourceId: source.id,
  ordinal: 0,
  text: "对机械系统和电气系统进行常规检查诊断，开展维护保养、数据监测、故障诊断与维修并编制报告。",
  contentHash: "segment-hash",
};

function task(id: string, label: string): SemanticNode {
  return {
    id,
    type: "task",
    label,
    summary: label,
    aliases: [],
    lifecycle: "stable",
    confidence: 0.75,
    evidenceSegmentIds: [segment.id],
    evidenceBindingIds: [],
    ring: 2,
  };
}

test("并行抽取未返回 bridges 时，Barrier 后按强标签相似度和共享证据保守对齐任务与事件", () => {
  const draft: ProcessDraft = {
    scenarios: [{
      tempId: "s1",
      label: "现场运维",
      summary: "完成检查、维护与故障处置。",
      trigger: "计划保养或发生故障",
      outcome: "恢复运行并留存报告",
      knowledgeState: "documented_norm",
      evidenceSegmentIds: [segment.id],
    }],
    nodes: [
      { tempId: "e1", scenarioTempId: "s1", kind: "event", label: "常规检查与诊断", summary: "检查设备状态。", sequenceHint: 1, knowledgeState: "documented_norm", evidenceSegmentIds: [segment.id] },
      { tempId: "e2", scenarioTempId: "s1", kind: "event", label: "预防性维护与保养", summary: "执行保养。", sequenceHint: 2, knowledgeState: "documented_norm", evidenceSegmentIds: [segment.id] },
      { tempId: "e3", scenarioTempId: "s1", kind: "event", label: "数据采集与监测", summary: "采集运行数据。", sequenceHint: 3, knowledgeState: "documented_norm", evidenceSegmentIds: [segment.id] },
      { tempId: "e4", scenarioTempId: "s1", kind: "event", label: "编制运维报告", summary: "形成记录。", sequenceHint: 4, knowledgeState: "documented_norm", evidenceSegmentIds: [segment.id] },
    ],
    edges: [],
    bridges: [],
  };
  const semanticNodes = [
    task("task:mechanical", "机械系统常规性检查与诊断"),
    task("task:maintenance", "执行维护保养"),
    task("task:monitoring", "运行数据采集与监测"),
    task("task:report", "编制运维与维修报告"),
    task("task:programming", "程序编写与调试"),
  ];

  const result = compileProcessDraft({ draft, segments: [segment], assets: [source], semanticNodes });
  const bridgedTaskIds = new Set(result.bridges.filter((bridge) => bridge.type === "realizes_task").map((bridge) => bridge.semanticNodeId));

  assert.deepEqual(
    [...bridgedTaskIds].sort(),
    ["task:maintenance", "task:mechanical", "task:monitoring", "task:report"].sort(),
  );
  assert.equal(bridgedTaskIds.has("task:programming"), false, "弱相关任务必须保留为研究缺口");
});
