import assert from "node:assert/strict";
import test from "node:test";
import { resolveLearnFlowIdentity } from "@/lib/integrations/learnflow/auth";

test("Role Atlas 复用 LearnFlow 会话并映射为稳定主体，不保存或解析密码", async () => {
  let forwardedCookie = "";
  const identity = await resolveLearnFlowIdentity({
    request: new Request("https://role.example/api/auth/session", { headers: { cookie: "learnflow_session=opaque" } }),
    baseUrl: "https://learnflow.example",
    fetchImpl: async (_url, init) => {
      forwardedCookie = new Headers(init?.headers).get("cookie") || "";
      return Response.json({ id: 11, learner_id: 23, username: "alice", display_name: "Alice", role: "user" });
    },
  });
  assert.equal(forwardedCookie, "learnflow_session=opaque");
  assert.deepEqual(identity, {
    issuer: "learnflow",
    subjectId: "learnflow:learner:23",
    accountId: 11,
    learnerId: 23,
    username: "alice",
    displayName: "Alice",
    role: "user",
  });
});

test("无 LearnFlow 会话时保持匿名，认证服务异常与未登录严格区分", async () => {
  const anonymous = await resolveLearnFlowIdentity({
    request: new Request("https://role.example/api/auth/session"),
    baseUrl: "https://learnflow.example",
    fetchImpl: async () => { throw new Error("不应调用"); },
  });
  assert.equal(anonymous, null);

  const signedOut = await resolveLearnFlowIdentity({
    request: new Request("https://role.example/api/auth/session", { headers: { cookie: "learnflow_session=expired" } }),
    baseUrl: "https://learnflow.example",
    fetchImpl: async () => new Response(null, { status: 401 }),
  });
  assert.equal(signedOut, null);

  await assert.rejects(resolveLearnFlowIdentity({
    request: new Request("https://role.example/api/auth/session", { headers: { cookie: "learnflow_session=opaque" } }),
    baseUrl: "https://learnflow.example",
    fetchImpl: async () => new Response(null, { status: 503 }),
  }), /LEARNFLOW_AUTH_UNAVAILABLE:503/u);
});
