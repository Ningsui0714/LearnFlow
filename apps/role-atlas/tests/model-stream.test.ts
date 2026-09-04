import assert from "node:assert/strict";
import test from "node:test";
import { createModelInvoker, parseOpenAICompatibleStream } from "@/lib/agent/model";

function sseBody(chunks: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

test("SSE 解析器分别保留 reasoning_content 与 content 的原始增量", async () => {
  const body = sseBody([
    "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"先分析\"}}]}\n\n",
    "data: {\"choices\":[{\"delta\":{\"content\":\"最终\"}}]}\r\n\r\n",
    "data: [DONE]\n\n",
  ]);
  const parts = [];
  for await (const part of parseOpenAICompatibleStream(body)) parts.push(part);
  assert.deepEqual(parts, [
    { type: "reasoning", delta: "先分析" },
    { type: "text", delta: "最终" },
  ]);
});

test("模型适配器固定启用思考并直连官方流式接口", async () => {
  let requestedBody: Record<string, unknown> | undefined;
  const fakeFetch: typeof fetch = async (_input, init) => {
    requestedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(sseBody([
      "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"理由\"}}]}\n\n",
      "data: {\"choices\":[{\"delta\":{\"content\":\"答案\"}}]}\n\n",
      "data: [DONE]\n\n",
    ]), { headers: { "content-type": "text/event-stream" } });
  };
  const invoke = createModelInvoker({
    provider: "mimo",
    model: "mimo-v2.5",
    apiKey: "test-key-long",
    thinking: false,
  }, fakeFetch);
  const parts = [];
  for await (const part of invoke({ system: "system", user: "user" })) parts.push(part);
  assert.deepEqual(requestedBody?.thinking, { type: "enabled" });
  assert.equal(requestedBody?.stream, true);
  assert.deepEqual(parts, [
    { type: "reasoning", delta: "理由" },
    { type: "text", delta: "答案" },
  ]);
});

test("模型流使用滑动空闲超时，持续输出不会被总时长误杀", async () => {
  const encoder = new TextEncoder();
  const fakeFetch: typeof fetch = async (_input, init) => {
    const signal = init?.signal;
    return new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        const timers = [
          setTimeout(() => controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"reasoning_content":"持续"}}]}\n\n')), 10),
          setTimeout(() => controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"输"}}]}\n\n')), 35),
          setTimeout(() => controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"出"}}]}\n\n')), 60),
          setTimeout(() => {
            controller.enqueue(encoder.encode("data: [DONE]\n\n"));
            controller.close();
          }, 85),
        ];
        signal?.addEventListener("abort", () => {
          timers.forEach(clearTimeout);
          controller.error(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      },
    }), { headers: { "content-type": "text/event-stream" } });
  };
  const invoke = createModelInvoker({
    provider: "mimo",
    model: "mimo-v2.5",
    apiKey: "test-key-long",
    thinking: true,
  }, fakeFetch);
  const parts = [];
  for await (const part of invoke({ system: "system", user: "user", timeoutMs: 40 })) parts.push(part);
  assert.deepEqual(parts, [
    { type: "reasoning", delta: "持续" },
    { type: "text", delta: "输" },
    { type: "text", delta: "出" },
  ]);
});
