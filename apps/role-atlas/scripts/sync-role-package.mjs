import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageRoot = resolve(projectRoot, "../role-snapshot/packages/llm-app-engineer-v1.1");
const processPackageRoot = resolve(projectRoot, "../role-snapshot/packages/llm-app-engineer-process-v0.1");
const outputFile = resolve(projectRoot, "lib/role-package/generated-data.json");

function read(path) {
  return readFileSync(resolve(packageRoot, path), "utf8");
}

function readProcess(path) {
  return readFileSync(resolve(processPackageRoot, path), "utf8");
}

function parseJsonLines(path) {
  return read(path).split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

const manifest = parse(read("manifest.yaml"));
const workProcessManifest = parse(readProcess("manifest.yaml"));
const mismatches = [];
for (const [path, expected] of Object.entries(manifest.hashes || {})) {
  const actual = sha256(read(path));
  if (actual !== expected) mismatches.push({ path, expected, actual });
}
for (const [path, expected] of Object.entries(workProcessManifest.hashes || {})) {
  const actual = sha256(readProcess(path));
  if (actual !== expected) mismatches.push({ package: "work-process", path, expected, actual });
}

if (mismatches.length > 0) {
  throw new Error(`Role package hash mismatch: ${JSON.stringify(mismatches)}`);
}

if (
  workProcessManifest.target_role_package.package_id !== manifest.package_id
  || workProcessManifest.target_role_package.package_version !== manifest.package_version
  || workProcessManifest.target_role_package.snapshot_id !== manifest.snapshot_id
) {
  throw new Error("Work process package targets a different role package snapshot.");
}

const payload = {
  syncedAt: new Date().toISOString(),
  manifest,
  validation: JSON.parse(read("validation-report.json")),
  graph: JSON.parse(read("graph.json")),
  views: parse(read("views.yaml")),
  sources: parse(read("sources.yaml")),
  objectIndex: parseJsonLines("object-index.jsonl"),
  retrieval: parseJsonLines("retrieval.jsonl"),
  workProcessManifest,
  workProcessValidation: JSON.parse(readProcess("validation-report.json")),
  workProcess: JSON.parse(readProcess("work-process.json")),
};

mkdirSync(dirname(outputFile), { recursive: true });
writeFileSync(outputFile, `${JSON.stringify(payload)}\n`);

const publicData = resolve(projectRoot, "public/data");
mkdirSync(publicData, { recursive: true });
writeFileSync(resolve(publicData, "graph.json"), read("graph.json"));
writeFileSync(resolve(publicData, "object-index.jsonl"), read("object-index.jsonl"));
writeFileSync(resolve(publicData, "validation-report.json"), read("validation-report.json"));
writeFileSync(resolve(publicData, "work-process.json"), readProcess("work-process.json"));
writeFileSync(resolve(publicData, "work-process-validation-report.json"), readProcess("validation-report.json"));

console.log(JSON.stringify({
  ok: true,
  packageId: manifest.package_id,
  packageVersion: manifest.package_version,
  snapshotId: manifest.snapshot_id,
  objects: payload.objectIndex.length,
  retrievalUnits: payload.retrieval.length,
  processPackageVersion: workProcessManifest.package_version,
  processScenarios: payload.workProcess.scenarios.length,
  processNodes: payload.workProcess.nodes.length,
}));
