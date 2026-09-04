import { and, eq } from "drizzle-orm";
import { ensureAppSchema, getDb } from "@/db";
import { referenceMigrations, semanticDiffs } from "@/db/schema";
import type { ColdStartBuildResult } from "@/lib/build/types";
import { canonicalStringify, domainId } from "./canonical";
import { getProjectVersionRecord } from "./commit";
import type { FieldChange, ObjectChange, ReferenceMigration, SemanticDiff } from "./types";

const ALGORITHM_VERSION = "1.0.0" as const;

type IndexedObject = { id: string; label?: string; type?: string; [key: string]: unknown };

function objectIndex(result: ColdStartBuildResult) {
  const domains: Array<[ObjectChange["domain"], IndexedObject[]]> = [
    ["semantic_node", result.semantic.nodes as IndexedObject[]],
    ["semantic_edge", result.semantic.edges as IndexedObject[]],
    ["claim", result.semantic.claims as IndexedObject[]],
    ["process_scenario", result.process.scenarios.map((item) => ({ ...item, label: item.label })) as IndexedObject[]],
    ["process_node", result.process.nodes as IndexedObject[]],
    ["process_edge", result.process.edges as IndexedObject[]],
    ["process_bridge", result.process.bridges as IndexedObject[]],
    ["source", result.sources.assets as IndexedObject[]],
    ["evidence", result.sources.evidenceBindings as IndexedObject[]],
    ["snapshot_section", result.snapshot.sections as IndexedObject[]],
  ];
  return domains;
}

function fieldChanges(before: unknown, after: unknown, path = ""): FieldChange[] {
  if (canonicalStringify(before) === canonicalStringify(after)) return [];
  if (Array.isArray(before) || Array.isArray(after) || !before || !after || typeof before !== "object" || typeof after !== "object") {
    return [{ path: path || "$", before, after }];
  }
  const left = before as Record<string, unknown>;
  const right = after as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(left), ...Object.keys(right)])].sort();
  return keys.flatMap((key) => fieldChanges(left[key], right[key], path ? `${path}.${key}` : key));
}

function normalizeLabel(value: string) {
  return value.normalize("NFKC").toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
}

function aliases(item: IndexedObject) {
  const values = Array.isArray(item.aliases) ? item.aliases.filter((value): value is string => typeof value === "string") : [];
  return new Set([item.label, ...values].filter((value): value is string => Boolean(value)).map(normalizeLabel));
}

function identityScore(left: IndexedObject, right: IndexedObject) {
  if (left.type && right.type && left.type !== right.type) return 0;
  const leftAliases = aliases(left);
  const rightAliases = aliases(right);
  if ([...leftAliases].some((value) => rightAliases.has(value))) return 1;
  const a = normalizeLabel(left.label || "");
  const b = normalizeLabel(right.label || "");
  if (!a || !b) return 0;
  if (a.includes(b) || b.includes(a)) return 0.78;
  const aPairs = new Set(Array.from({ length: Math.max(0, a.length - 1) }, (_, index) => a.slice(index, index + 2)));
  const bPairs = new Set(Array.from({ length: Math.max(0, b.length - 1) }, (_, index) => b.slice(index, index + 2)));
  const shared = [...aPairs].filter((value) => bPairs.has(value)).length;
  return aPairs.size + bPairs.size > 0 ? 2 * shared / (aPairs.size + bPairs.size) : 0;
}

function discoverMigrations(input: {
  removed: IndexedObject[];
  added: IndexedObject[];
  fromSnapshotId: string;
  toSnapshotId: string;
}) {
  const result: ReferenceMigration[] = [];
  const candidates = input.removed.flatMap((from) => input.added
    .map((to) => ({ from, to, score: identityScore(from, to) }))
    .filter((item) => item.score >= 0.9));
  for (const removed of input.removed) {
    const matches = candidates.filter((item) => item.from.id === removed.id).sort((a, b) => b.score - a.score);
    if (matches.length === 1 && candidates.filter((item) => item.to.id === matches[0].to.id).length === 1) {
      result.push({
        fromSnapshotId: input.fromSnapshotId,
        toSnapshotId: input.toSnapshotId,
        fromTargetId: removed.id,
        toTargetIds: [matches[0].to.id],
        kind: "replacement",
        confidence: matches[0].score,
        reason: "类型一致且规范标签或别名匹配；保留为显式迁移，不静默替换旧引用。",
      });
    }
  }
  return result;
}

export async function createSemanticDiff(input: {
  projectId: string;
  fromVersionId: string;
  toVersionId: string;
  persist?: boolean;
}): Promise<SemanticDiff> {
  await ensureAppSchema();
  const db = getDb();
  const [cached] = await db.select().from(semanticDiffs).where(and(
    eq(semanticDiffs.fromVersionId, input.fromVersionId),
    eq(semanticDiffs.toVersionId, input.toVersionId),
    eq(semanticDiffs.algorithmVersion, ALGORITHM_VERSION),
  )).limit(1);
  if (cached) return JSON.parse(cached.diffJson) as SemanticDiff;

  const [from, to] = await Promise.all([
    getProjectVersionRecord(input.projectId, input.fromVersionId),
    getProjectVersionRecord(input.projectId, input.toVersionId),
  ]);
  if (!from || !to) throw new Error("VERSION_NOT_FOUND");

  const changes: ObjectChange[] = [];
  const removedSemantic: IndexedObject[] = [];
  const addedSemantic: IndexedObject[] = [];
  const fromDomains = new Map(objectIndex(from.result));
  for (const [domain, toItems] of objectIndex(to.result)) {
    const fromItems = fromDomains.get(domain) || [];
    const left = new Map(fromItems.map((item) => [item.id, item]));
    const right = new Map(toItems.map((item) => [item.id, item]));
    for (const item of fromItems) {
      const next = right.get(item.id);
      if (!next) {
        changes.push({ domain, kind: "removed", id: item.id, label: item.label, changes: [{ path: "$", before: item }] });
        if (domain === "semantic_node") removedSemantic.push(item);
        continue;
      }
      const fields = fieldChanges(item, next);
      if (fields.length === 0) continue;
      const renamed = item.label !== next.label && fields.every((change) => change.path === "label" || change.path === "aliases");
      changes.push({ domain, kind: renamed ? "renamed" : "modified", id: item.id, label: next.label || item.label, changes: fields });
    }
    for (const item of toItems) {
      if (left.has(item.id)) continue;
      changes.push({ domain, kind: "added", id: item.id, label: item.label, changes: [{ path: "$", after: item }] });
      if (domain === "semantic_node") addedSemantic.push(item);
    }
  }

  const migrations = discoverMigrations({
    removed: removedSemantic,
    added: addedSemantic,
    fromSnapshotId: from.snapshotId,
    toSnapshotId: to.snapshotId,
  });
  for (const change of changes.filter((item) => item.kind === "renamed")) {
    migrations.push({
      fromSnapshotId: from.snapshotId,
      toSnapshotId: to.snapshotId,
      fromTargetId: change.id,
      toTargetIds: [change.id],
      kind: "rename",
      confidence: 1,
      reason: "稳定 ID 未变化，仅标签或别名发生变化。",
    });
  }

  const counts = (kind: ObjectChange["kind"]) => changes.filter((item) => item.kind === kind).length;
  const structural = changes.some((item) => ["semantic_node", "semantic_edge", "process_scenario", "process_node", "process_edge", "process_bridge"].includes(item.domain) && ["added", "removed"].includes(item.kind));
  const roleRemoved = changes.some((item) => item.domain === "semantic_node" && item.kind === "removed" && String((item.changes[0]?.before as IndexedObject | undefined)?.type) === "market_role");
  const recommendedBump = changes.length === 0 ? "none" : roleRemoved ? "major" : structural ? "minor" : "patch";
  const impacts = [
    changes.some((item) => ["semantic_node", "semantic_edge", "claim"].includes(item.domain)) ? "岗位语义图谱" : "",
    changes.some((item) => item.domain.startsWith("process_")) ? "事理森林" : "",
    changes.some((item) => ["source", "evidence"].includes(item.domain)) ? "证据与来源" : "",
    changes.some((item) => item.domain === "snapshot_section") ? "岗位快照投影" : "",
  ].filter(Boolean);
  const diff: SemanticDiff = {
    id: domainId("diff"),
    algorithmVersion: ALGORITHM_VERSION,
    projectId: input.projectId,
    from: { versionId: from.id, snapshotId: from.snapshotId, rootHash: from.rootHash },
    to: { versionId: to.id, snapshotId: to.snapshotId, rootHash: to.rootHash },
    changes,
    migrations,
    impacts,
    summary: { added: counts("added"), removed: counts("removed"), modified: counts("modified"), renamed: counts("renamed"), total: changes.length },
    recommendedBump,
    createdAt: new Date().toISOString(),
  };
  if (input.persist !== false) {
    await db.insert(semanticDiffs).values({
      id: diff.id,
      projectId: input.projectId,
      fromVersionId: input.fromVersionId,
      toVersionId: input.toVersionId,
      algorithmVersion: ALGORITHM_VERSION,
      diffJson: canonicalStringify(diff),
    }).onConflictDoNothing();
    for (const migration of migrations) {
      await db.insert(referenceMigrations).values({
        id: domainId("migration"),
        fromSnapshotId: migration.fromSnapshotId,
        toSnapshotId: migration.toSnapshotId,
        fromTargetId: migration.fromTargetId,
        toTargetIdsJson: JSON.stringify(migration.toTargetIds),
        kind: migration.kind,
        confidence: Math.round(migration.confidence * 1000),
        reason: migration.reason,
      }).onConflictDoNothing();
    }
  }
  return diff;
}

export async function resolveReferenceMigration(input: { fromSnapshotId: string; toSnapshotId: string; targetId: string }) {
  await ensureAppSchema();
  const db = getDb();
  const [row] = await db.select().from(referenceMigrations).where(and(
    eq(referenceMigrations.fromSnapshotId, input.fromSnapshotId),
    eq(referenceMigrations.toSnapshotId, input.toSnapshotId),
    eq(referenceMigrations.fromTargetId, input.targetId),
  )).limit(1);
  if (!row) return null;
  return { ...row, toTargetIds: JSON.parse(row.toTargetIdsJson) as string[], confidence: row.confidence / 1000 };
}
