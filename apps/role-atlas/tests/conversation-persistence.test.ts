import assert from "node:assert/strict";
import test from "node:test";
import type { AgentEvent } from "@/lib/agent/events";
import { assistantMessageFromEvents } from "@/lib/projects/message-persistence";

function event(seq: number, kind: AgentEvent["kind"], payload: Record<string, unknown>): AgentEvent {
  return { version: "1.1", runId: "run-message", sessionId: "conversation-message", seq, time: "2026-08-21T00:00:00.000Z", kind, payload };
}

test("Agent 事件流稳定编译为可持久化的正文、思考、工具活动与引用", () => {
  const references = [{ targetId: "task:maintenance" }];
  const message = assistantMessageFromEvents({
    references,
    events: [
      event(1, "run.started", {}),
      event(2, "snapshot.pinned", { snapshotId: "snapshot:one" }),
      event(3, "tool.started", { name: "read_task_bundle" }),
      event(4, "tool.finished", { name: "read_task_bundle", returned: 4, ok: true }),
      event(5, "citation.registry", { citations: [{ handle: "C1", targetId: "task:maintenance" }] }),
      event(6, "reasoning.delta", { delta: "先检查任务证据。" }),
      event(7, "answer.delta", { delta: "维护保养" }),
      event(8, "answer.delta", { delta: "需要形成记录。" }),
      event(9, "answer.completed", {}),
    ],
  });

  assert.equal(message.text, "维护保养需要形成记录。");
  assert.equal(message.reasoning, "先检查任务证据。");
  assert.deepEqual(message.references, references);
  assert.equal(message.status, "done");
  assert.ok(message.activities.some((activity) => activity.id === "tool:read_task_bundle" && activity.status === "done"));
  assert.deepEqual(message.citations, [{ handle: "C1", targetId: "task:maintenance" }]);
});

test("失败和取消事件不会伪装成成功消息", () => {
  const failed = assistantMessageFromEvents({ references: [], events: [event(1, "run.failed", { message: "模型供应商拒绝凭据" })] });
  const cancelled = assistantMessageFromEvents({ references: [], events: [event(1, "run.failed", { message: "运行已取消。" })] });
  assert.equal(failed.status, "failed");
  assert.equal(failed.text, "模型供应商拒绝凭据");
  assert.equal(cancelled.status, "cancelled");
});
