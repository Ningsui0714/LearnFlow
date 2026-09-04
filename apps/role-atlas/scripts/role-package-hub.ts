import { resolve } from "node:path";
import {
  exportRolePackageHubView,
  initializeRolePackageHub,
  publishRolePackageHubSubmission,
  reviewRolePackageHubSubmission,
  submitRolePackageToHub,
} from "../lib/hub/file-hub";

function argument(name: string) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const command = process.argv[2];
const hubRoot = argument("--hub");
if (!command || !hubRoot) throw new Error("用法：npx tsx scripts/role-package-hub.ts <init|submit|review|publish|export-view> --hub <目录> ...");

let result: unknown;
if (command === "init") {
  result = await initializeRolePackageHub({
    hubRoot: resolve(hubRoot),
    policy: {
      protocol: "role-package-hub-policy.v1",
      officialMaintainerSubjects: (argument("--official") || "").split(",").filter(Boolean),
      reviewerSubjects: (argument("--reviewers") || "").split(",").filter(Boolean),
    },
  });
} else if (command === "submit") {
  const file = argument("--file");
  const owner = argument("--owner");
  if (!file || !owner) throw new Error("submit 需要 --file 与 --owner");
  result = await submitRolePackageToHub({
    hubRoot: resolve(hubRoot),
    packageFile: resolve(file),
    ownerSubjectId: owner,
    maintainerName: argument("--maintainer") || owner,
    channel: argument("--channel") === "official" ? "official" : "community",
    visibility: argument("--visibility") === "public" ? "public" : "private",
  });
} else if (command === "review") {
  const submissionId = argument("--submission");
  const reviewer = argument("--reviewer");
  if (!submissionId || !reviewer) throw new Error("review 需要 --submission 与 --reviewer");
  result = await reviewRolePackageHubSubmission({
    hubRoot: resolve(hubRoot),
    submissionId,
    reviewerSubjectId: reviewer,
    decision: argument("--decision") === "reject" ? "reject" : "approve",
    notes: argument("--notes"),
  });
} else if (command === "publish") {
  const submissionId = argument("--submission");
  const actor = argument("--actor");
  if (!submissionId || !actor) throw new Error("publish 需要 --submission 与 --actor");
  result = await publishRolePackageHubSubmission({ hubRoot: resolve(hubRoot), submissionId, actorSubjectId: actor });
} else if (command === "export-view") {
  const out = argument("--out");
  if (!out) throw new Error("export-view 需要 --out");
  result = await exportRolePackageHubView({ hubRoot: resolve(hubRoot), outputDirectory: resolve(out), actorSubjectId: argument("--actor") });
} else {
  throw new Error(`未知命令：${command}`);
}
console.log(JSON.stringify(result, null, 2));
