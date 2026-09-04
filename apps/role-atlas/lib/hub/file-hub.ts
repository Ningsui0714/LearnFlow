import { constants } from "node:fs";
import { access, copyFile, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { bundleFromJson } from "@/lib/packages/archive";
import { validatePackageBundle } from "@/lib/packages/validator";
import { canonicalStringify, sha256Hex } from "@/lib/versioning/canonical";
import type {
  HubChannel,
  HubVisibility,
  RolePackageHubCatalog,
  RolePackageHubCatalogEntry,
  RolePackageHubPolicy,
  RolePackageHubSubmission,
} from "./types";

const POLICY_FILE = "hub-policy.json";
const CATALOG_FILE = "catalog.json";

function assertSubject(value: string, label: string) {
  if (!/^[0-9A-Za-z][0-9A-Za-z._:@/-]{2,159}$/u.test(value)) throw new Error(`INVALID_${label}`);
}

async function writeExclusive(path: string, value: string) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, value, { encoding: "utf8", flag: "wx" });
}

async function writeAtomic(path: string, value: string) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, value, { encoding: "utf8", flag: "wx" });
  await rename(temporary, path);
}

async function readPolicy(hubRoot: string) {
  const policy = JSON.parse(await readFile(join(hubRoot, POLICY_FILE), "utf8")) as RolePackageHubPolicy;
  if (policy.protocol !== "role-package-hub-policy.v1") throw new Error("UNSUPPORTED_HUB_POLICY");
  return policy;
}

async function readSubmissions(hubRoot: string) {
  const directory = join(hubRoot, "submissions");
  let files: string[] = [];
  try { files = (await readdir(directory)).filter((file) => file.endsWith(".json")); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  return Promise.all(files.sort().map(async (file) => JSON.parse(await readFile(join(directory, file), "utf8")) as RolePackageHubSubmission));
}

async function catalogRootHash(catalog: Omit<RolePackageHubCatalog, "rootHash">) {
  return sha256Hex(canonicalStringify({ ...catalog, generatedAt: "", rootHash: "" }));
}

export async function rebuildRolePackageHubCatalog(hubRootInput: string) {
  const hubRoot = resolve(hubRootInput);
  const submissions = await readSubmissions(hubRoot);
  const entries: RolePackageHubCatalogEntry[] = submissions
    .filter((item) => item.status === "published")
    .map((item): RolePackageHubCatalogEntry => ({
      packageId: item.packageId,
      packageVersion: item.packageVersion,
      snapshotId: item.snapshotId,
      rootHash: item.rootHash,
      roleTitle: item.roleTitle,
      ownerSubjectId: item.ownerSubjectId,
      maintainerName: item.maintainerName,
      channel: item.channel,
      visibility: item.visibility,
      review: item.visibility === "private" ? "not_required_private" : "approved",
      objectPath: item.objectPath,
      publishedAt: item.publishedAt!,
    }))
    .sort((left, right) => `${left.packageId}@${left.packageVersion}`.localeCompare(`${right.packageId}@${right.packageVersion}`));
  const releaseKeys = new Set<string>();
  for (const entry of entries) {
    const key = `${entry.packageId}@${entry.packageVersion}`;
    if (releaseKeys.has(key)) throw new Error(`HUB_RELEASE_CONFLICT:${key}`);
    releaseKeys.add(key);
  }
  const core = { protocol: "role-package-hub-catalog.v1" as const, generatedAt: new Date().toISOString(), entries };
  const catalog: RolePackageHubCatalog = { ...core, rootHash: await catalogRootHash(core) };
  await writeAtomic(join(hubRoot, CATALOG_FILE), `${canonicalStringify(catalog)}\n`);
  return catalog;
}

export async function initializeRolePackageHub(input: { hubRoot: string; policy: RolePackageHubPolicy }) {
  const hubRoot = resolve(input.hubRoot);
  if (input.policy.protocol !== "role-package-hub-policy.v1") throw new Error("UNSUPPORTED_HUB_POLICY");
  input.policy.officialMaintainerSubjects.forEach((item) => assertSubject(item, "OFFICIAL_SUBJECT"));
  input.policy.reviewerSubjects.forEach((item) => assertSubject(item, "REVIEWER_SUBJECT"));
  await mkdir(join(hubRoot, "objects", "sha256"), { recursive: true });
  await mkdir(join(hubRoot, "submissions"), { recursive: true });
  try { await access(join(hubRoot, POLICY_FILE), constants.F_OK); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    await writeExclusive(join(hubRoot, POLICY_FILE), `${canonicalStringify(input.policy)}\n`);
  }
  try { await access(join(hubRoot, CATALOG_FILE), constants.F_OK); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    await rebuildRolePackageHubCatalog(hubRoot);
  }
  return { protocol: "role-package-hub-init.v1", hubRoot };
}

export async function submitRolePackageToHub(input: {
  hubRoot: string;
  packageFile: string;
  ownerSubjectId: string;
  maintainerName: string;
  channel: HubChannel;
  visibility: HubVisibility;
}) {
  assertSubject(input.ownerSubjectId, "OWNER_SUBJECT");
  const hubRoot = resolve(input.hubRoot);
  const policy = await readPolicy(hubRoot);
  if (input.channel === "official" && !policy.officialMaintainerSubjects.includes(input.ownerSubjectId)) {
    throw new Error("OFFICIAL_MAINTAINER_REQUIRED");
  }
  const packageFile = resolve(input.packageFile);
  const raw = await readFile(packageFile, "utf8");
  const bundle = bundleFromJson(raw);
  const validation = await validatePackageBundle(bundle);
  if (!validation.valid) throw new Error(`PACKAGE_INVALID:${validation.hardErrors.join("|")}`);
  const objectPath = `objects/sha256/${bundle.manifest.rootHash}.role-package.json`;
  const objectFile = join(hubRoot, objectPath);
  try { await copyFile(packageFile, objectFile, constants.COPYFILE_EXCL); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    if ((await readFile(objectFile, "utf8")) !== raw) throw new Error("HUB_OBJECT_HASH_COLLISION");
  }
  const submissionId = `submission-${(await sha256Hex(`${input.ownerSubjectId}\0${bundle.manifest.packageId}\0${bundle.manifest.packageVersion}\0${bundle.manifest.rootHash}`)).slice(0, 24)}`;
  const submissionFile = join(hubRoot, "submissions", `${submissionId}.json`);
  const now = new Date().toISOString();
  const submission: RolePackageHubSubmission = {
    protocol: "role-package-hub-submission.v1",
    submissionId,
    packageId: bundle.manifest.packageId,
    packageVersion: bundle.manifest.packageVersion,
    snapshotId: bundle.manifest.snapshotId,
    rootHash: bundle.manifest.rootHash,
    roleTitle: bundle.manifest.roleTitle,
    ownerSubjectId: input.ownerSubjectId,
    maintainerName: input.maintainerName,
    channel: input.channel,
    visibility: input.visibility,
    objectPath,
    status: input.visibility === "private" ? "published" : "submitted",
    submittedAt: now,
    ...(input.visibility === "private" ? { publishedAt: now } : {}),
  };
  try { await writeExclusive(submissionFile, `${canonicalStringify(submission)}\n`); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    const existing = JSON.parse(await readFile(submissionFile, "utf8")) as RolePackageHubSubmission;
    if (
      existing.rootHash !== submission.rootHash
      || existing.ownerSubjectId !== submission.ownerSubjectId
      || existing.channel !== submission.channel
      || existing.visibility !== submission.visibility
      || existing.maintainerName !== submission.maintainerName
    ) throw new Error("HUB_SUBMISSION_CONFLICT");
    return existing;
  }
  if (submission.status === "published") await rebuildRolePackageHubCatalog(hubRoot);
  return submission;
}

async function readSubmission(hubRoot: string, submissionId: string) {
  if (!/^submission-[0-9a-f]{24}$/u.test(submissionId)) throw new Error("INVALID_SUBMISSION_ID");
  try { return JSON.parse(await readFile(join(hubRoot, "submissions", `${submissionId}.json`), "utf8")) as RolePackageHubSubmission; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") throw new Error("SUBMISSION_NOT_FOUND");
    throw error;
  }
}

async function replaceSubmission(hubRoot: string, submission: RolePackageHubSubmission) {
  const target = join(hubRoot, "submissions", `${submission.submissionId}.json`);
  await writeAtomic(target, `${canonicalStringify(submission)}\n`);
  return submission;
}

export async function reviewRolePackageHubSubmission(input: {
  hubRoot: string;
  submissionId: string;
  reviewerSubjectId: string;
  decision: "approve" | "reject";
  notes?: string;
}) {
  const hubRoot = resolve(input.hubRoot);
  const policy = await readPolicy(hubRoot);
  if (!policy.reviewerSubjects.includes(input.reviewerSubjectId)) throw new Error("HUB_REVIEWER_REQUIRED");
  const submission = await readSubmission(hubRoot, input.submissionId);
  if (submission.ownerSubjectId === input.reviewerSubjectId) throw new Error("SELF_REVIEW_FORBIDDEN");
  if (submission.visibility !== "public" || submission.status !== "submitted") throw new Error("SUBMISSION_NOT_REVIEWABLE");
  return replaceSubmission(hubRoot, {
    ...submission,
    status: input.decision === "approve" ? "approved" : "rejected",
    reviewedAt: new Date().toISOString(),
    reviewerSubjectId: input.reviewerSubjectId,
    reviewNotes: input.notes || "",
  });
}

export async function publishRolePackageHubSubmission(input: { hubRoot: string; submissionId: string; actorSubjectId: string }) {
  const hubRoot = resolve(input.hubRoot);
  const submission = await readSubmission(hubRoot, input.submissionId);
  if (submission.ownerSubjectId !== input.actorSubjectId) throw new Error("SUBMISSION_OWNER_REQUIRED");
  if (submission.status === "published") return submission;
  if (submission.status !== "approved" || !submission.reviewerSubjectId) throw new Error("APPROVED_REVIEW_REQUIRED");
  const published = await replaceSubmission(hubRoot, { ...submission, status: "published", publishedAt: new Date().toISOString() });
  await rebuildRolePackageHubCatalog(hubRoot);
  return published;
}

export async function exportRolePackageHubView(input: { hubRoot: string; outputDirectory: string; actorSubjectId?: string }) {
  const hubRoot = resolve(input.hubRoot);
  const outputDirectory = resolve(input.outputDirectory);
  try {
    await access(outputDirectory, constants.F_OK);
    throw new Error("HUB_VIEW_OUTPUT_EXISTS");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  const catalog = JSON.parse(await readFile(join(hubRoot, CATALOG_FILE), "utf8")) as RolePackageHubCatalog;
  const entries = catalog.entries.filter((entry) => entry.visibility === "public" || entry.ownerSubjectId === input.actorSubjectId);
  await mkdir(dirname(outputDirectory), { recursive: true });
  const stagingDirectory = await mkdtemp(join(dirname(outputDirectory), ".role-hub-view-"));
  try {
    for (const entry of entries) {
      const source = resolve(hubRoot, entry.objectPath);
      const destination = resolve(stagingDirectory, entry.objectPath);
      if (!source.startsWith(`${hubRoot}${sep}`) || !destination.startsWith(`${stagingDirectory}${sep}`)) throw new Error("UNSAFE_HUB_OBJECT_PATH");
      await mkdir(dirname(destination), { recursive: true });
      await copyFile(source, destination, constants.COPYFILE_EXCL);
    }
    const core = { protocol: "role-package-hub-catalog.v1" as const, generatedAt: new Date().toISOString(), entries };
    const view: RolePackageHubCatalog = { ...core, rootHash: await catalogRootHash(core) };
    await writeExclusive(join(stagingDirectory, CATALOG_FILE), `${canonicalStringify(view)}\n`);
    await rename(stagingDirectory, outputDirectory);
    return { protocol: "role-package-hub-view.v1", outputDirectory, entries: entries.length, rootHash: view.rootHash };
  } catch (error) {
    await rm(stagingDirectory, { recursive: true, force: true });
    throw error;
  }
}
