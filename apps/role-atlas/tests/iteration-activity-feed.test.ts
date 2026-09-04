import assert from "node:assert/strict";
import test from "node:test";
import {
  buildIterationActivityFeed,
  currentIterationThinking,
  formatIterationElapsed,
  iterationRunElapsed,
} from "@/lib/iteration/activity-feed";
import type { IterationEvent, IterationEventKind, IterationEventPhase } from "@/lib/iteration/types";

function event(seq: number, kind: IterationEventKind, phase: IterationEventPhase, payload: Record<string, unknown> = {}, seconds = seq): IterationEvent {
  return {
    version: "1.0",
    runId: "activity-feed-test",
    snapshotId: "snapshot:test@2026-08-22:base",
    seq,
    time: new Date(Date.UTC(2026, 7, 22, 0, 0, seconds)).toISOString(),
    kind,
    phase,
    payload,
  };
}

test("运行事件被聚合成对话消息与有耗时的工具卡，而不是逐条暴露结构发现", () => {
  const events: IterationEvent[] = [
    event(1, "iteration.run.started", "system", { searchProvider: "tavily", model: "mimo/mimo-v2.5" }),
    event(2, "iteration.snapshot.resolved", "contract", { snapshotId: "snapshot:test", version: "1.0.0", asOf: "2026-08-22" }),
    event(3, "iteration.contract.created", "contract", { contract: { objective: "研究 Agent 工具调用能力", changeIntents: ["expand", "verify"], budgets: { graphRadius: 2 }, targetAsOf: "2026-08-22" } }),
    event(4, "iteration.inspection.started", "inspect", { scope: 2 }),
    event(5, "iteration.finding.discovered", "inspect", { finding: { title: "发现一" } }),
    event(6, "iteration.finding.discovered", "inspect", { finding: { title: "发现二" } }),
    event(7, "iteration.inspection.completed", "inspect", { findingCount: 2, hardBlockerCount: 0 }),
    event(8, "iteration.work.plan.created", "plan", { workItems: [{ title: "研究工具调用" }] }),
    event(9, "iteration.research.plan.created", "research", { plan: { queries: [{ id: "q1" }] } }),
    event(10, "iteration.search.started", "research", { queryId: "q1", category: "technology", query: "Agent tool calling official docs" }),
    event(11, "iteration.search.completed", "research", { queryId: "q1", resultCount: 5, responseTimeMs: 1_240 }),
  ];
  const activities = buildIterationActivityFeed(events, Date.UTC(2026, 7, 22, 0, 0, 12));
  assert.equal(activities.filter((activity) => activity.id === "inspect-snapshot").length, 1);
  assert.equal(activities.some((activity) => activity.summary.includes("发现一")), false, "单条发现不应淹没主对话流");
  const search = activities.find((activity) => activity.id === "search:q1")!;
  assert.equal(search.toolName, "tavily.search");
  assert.equal(search.status, "completed");
  assert.equal(search.elapsedMs, 1_240);
  assert.match(search.summary, /Agent tool calling/u);
});

test("模型重建、回归评估和快照写入都有准确的运行中状态与配对耗时", () => {
  const events: IterationEvent[] = [
    event(1, "iteration.run.started", "system"),
    event(2, "iteration.candidate.rebuild.started", "rebuild", { model: "mimo/mimo-v2.5", sourceCount: 18 }),
    event(8, "iteration.candidate.rebuilt", "rebuild", { nodes: 54, edges: 105, scenarios: 3, sources: 18 }),
    event(9, "iteration.consolidation.started", "consolidate"),
    event(10, "iteration.patch.proposed", "consolidate", { patch: { operations: [] } }),
    event(11, "iteration.evaluation.started", "evaluate"),
    event(13, "iteration.evaluation.completed", "evaluate", { evaluation: { protocolValid: true, meaningful: true, coreRegression: false, informationGain: { score: 42 } } }),
    event(14, "iteration.snapshot.write.started", "snapshot"),
  ];
  const now = Date.UTC(2026, 7, 22, 0, 0, 20);
  const activities = buildIterationActivityFeed(events, now);
  assert.equal(activities.find((activity) => activity.id === "rebuild-candidate")?.elapsedMs, 6_000);
  assert.equal(activities.find((activity) => activity.id === "evaluate-candidate")?.elapsedMs, 2_000);
  assert.equal(activities.find((activity) => activity.id === "write-snapshot")?.status, "running");
  assert.equal(activities.find((activity) => activity.id === "write-snapshot")?.elapsedMs, 6_000);
  assert.match(currentIterationThinking(events), /不可变静态快照/u);
});

test("总耗时在完成后固定，格式适合直接展示", () => {
  const events = [
    event(1, "iteration.run.started", "system", {}, 1),
    event(66, "iteration.run.completed", "system", {}, 66),
  ];
  const elapsed = iterationRunElapsed(events, Date.UTC(2026, 7, 22, 0, 5, 0));
  assert.equal(elapsed, 65_000);
  assert.equal(formatIterationElapsed(elapsed), "1 分 5 秒");
});
