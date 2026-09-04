import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { exportStaticRolePackageFile } from "@/lib/packages/file-export";
import {
  exportRolePackageHubView,
  initializeRolePackageHub,
  publishRolePackageHubSubmission,
  reviewRolePackageHubSubmission,
  submitRolePackageToHub,
} from "@/lib/hub/file-hub";

async function setup() {
  const root = await mkdtemp(join(tmpdir(), "role-package-hub-"));
  const bundle = join(root, "role.role-package.json");
  await exportStaticRolePackageFile({ sourceDirectory: resolve("packages/golden/llm-app-engineer/1.0.0"), outputFile: bundle });
  const hub = join(root, "hub");
  await initializeRolePackageHub({
    hubRoot: hub,
    policy: { protocol: "role-package-hub-policy.v1", officialMaintainerSubjects: ["official:role-atlas"], reviewerSubjects: ["reviewer:one", "user:alice"] },
  });
  return { bundle, hub };
}

test("社区岗位包必须由独立审核者批准后才能进入公共目录", async () => {
  const { bundle, hub } = await setup();
  const submitted = await submitRolePackageToHub({ hubRoot: hub, packageFile: bundle, ownerSubjectId: "user:alice", maintainerName: "Alice", channel: "community", visibility: "public" });
  assert.equal(submitted.status, "submitted");
  await assert.rejects(publishRolePackageHubSubmission({ hubRoot: hub, submissionId: submitted.submissionId, actorSubjectId: "user:alice" }), /APPROVED_REVIEW_REQUIRED/u);
  await assert.rejects(reviewRolePackageHubSubmission({ hubRoot: hub, submissionId: submitted.submissionId, reviewerSubjectId: "user:alice", decision: "approve" }), /SELF_REVIEW_FORBIDDEN/u);
  const approved = await reviewRolePackageHubSubmission({ hubRoot: hub, submissionId: submitted.submissionId, reviewerSubjectId: "reviewer:one", decision: "approve" });
  assert.equal(approved.status, "approved");
  await publishRolePackageHubSubmission({ hubRoot: hub, submissionId: submitted.submissionId, actorSubjectId: "user:alice" });
  const catalog = JSON.parse(await readFile(join(hub, "catalog.json"), "utf8"));
  assert.equal(catalog.entries.length, 1);
  assert.equal(catalog.entries[0].review, "approved");
});

test("用户私有岗位包校验后直接进入仅所有者可见目录", async () => {
  const { bundle, hub } = await setup();
  const submission = await submitRolePackageToHub({ hubRoot: hub, packageFile: bundle, ownerSubjectId: "user:bob", maintainerName: "Bob", channel: "community", visibility: "private" });
  assert.equal(submission.status, "published");
  const catalog = JSON.parse(await readFile(join(hub, "catalog.json"), "utf8"));
  assert.equal(catalog.entries[0].visibility, "private");
  assert.equal(catalog.entries[0].ownerSubjectId, "user:bob");
  const publicView = join(hub, "..", "public-view");
  await exportRolePackageHubView({ hubRoot: hub, outputDirectory: publicView });
  assert.equal(JSON.parse(await readFile(join(publicView, "catalog.json"), "utf8")).entries.length, 0);
  const ownerView = join(hub, "..", "owner-view");
  await exportRolePackageHubView({ hubRoot: hub, outputDirectory: ownerView, actorSubjectId: "user:bob" });
  assert.equal(JSON.parse(await readFile(join(ownerView, "catalog.json"), "utf8")).entries.length, 1);
});
