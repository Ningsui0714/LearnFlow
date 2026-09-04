import assert from "node:assert/strict";
import test from "node:test";
import { prepareBuildInput, selectExtractionSegments } from "@/lib/build/compiler";
import type { ColdStartRequest, WebSearchCategory } from "@/lib/build/types";

test("模型选段保持来源覆盖与字符上限，完整来源索引不被裁掉", () => {
  const categories: WebSearchCategory[] = [
    "official_standard",
    "job_market",
    "work_practice",
    "technology",
    "education",
    "future_signal",
  ];
  const request: ColdStartRequest = {
    runId: "run-source-context",
    projectId: "project-source-context",
    roleTitle: "工业机器人系统运维员",
    roleDescription: "关注现场任务、证据与教学转化。",
    market: "中国大陆",
    audience: ["高职学生", "教师"],
    snapshotAsOf: "2026-08-21",
    sources: categories.map((category, index) => ({
      title: `${category} 来源`,
      kind: "public_document" as const,
      content: `${"工业机器人系统运维员的任务、流程、交付物与技能要求。".repeat(45)}\n\n${"补充细节与案例。".repeat(130)}\n\n${"学习评价与安全规范。".repeat(110)}`,
      locator: `https://source-${index}.example.com/page`,
      sourceTier: category === "official_standard" ? "authoritative" as const : "secondary" as const,
      searchCategories: [category],
      retrievalScore: 0.7,
    })),
  };
  const prepared = prepareBuildInput(request);
  const selected = selectExtractionSegments({ ...prepared, request, maxSegments: 8, maxChars: 12_000 });
  const representedSourceIds = new Set(selected.map((segment) => segment.sourceId));

  assert.ok(prepared.segments.length > selected.length, "完整来源层应保留更多片段");
  assert.ok(selected.length <= 8);
  assert.ok(selected.reduce((total, segment) => total + segment.text.length, 0) <= 12_000);
  assert.equal(new Set(selected.map((segment) => segment.id)).size, selected.length);
  assert.ok(prepared.assets.every((asset) => representedSourceIds.has(asset.id)), "预算允许时每个来源至少保留一个代表片段");
  assert.ok(selected.every((segment) => prepared.segments.some((candidate) => candidate.id === segment.id)));
});
