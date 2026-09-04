import assert from "node:assert/strict";
import test from "node:test";
import { signRolePackageLaunch, verifyRolePackageLaunch } from "@/lib/integrations/learnflow/launch-token";

const secret = "launch-secret-with-at-least-thirty-two-bytes";
const packageRef = { packageId: "role.network", packageVersion: "1.2.0", snapshotId: "snapshot:network", rootHash: "a".repeat(64) };

test("岗位包交接令牌固定主体和不可变制品身份", () => {
  const token = signRolePackageLaunch({ secret, subject: "learnflow:learner:7", source: "graph_hub", roleTitle: "网络运维工程师", packageRef, now: 1_000, launchId: "launch-1" });
  const payload = verifyRolePackageLaunch(token, secret, 1_010);
  assert.equal(payload.subject, "learnflow:learner:7");
  assert.deepEqual(payload.packageRef, packageRef);
  assert.equal(payload.launchId, "launch-1");
});

test("岗位包交接令牌拒绝篡改与过期重放", () => {
  const token = signRolePackageLaunch({ secret, subject: "learnflow:learner:7", source: "role_atlas", roleTitle: "网络运维工程师", packageRef, now: 1_000, ttlSeconds: 60 });
  assert.throws(() => verifyRolePackageLaunch(`${token.slice(0, -1)}x`, secret, 1_010), /TOKEN_INVALID/u);
  assert.throws(() => verifyRolePackageLaunch(token, secret, 1_061), /TOKEN_INVALID/u);
});
