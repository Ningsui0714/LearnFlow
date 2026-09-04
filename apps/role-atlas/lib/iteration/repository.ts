import { asc, desc, eq } from "drizzle-orm";
import { ensureAppSchema, getD1, getDb } from "@/db";
import { snapshotIterationEvents, snapshotIterationRuns } from "@/db/schema";
import type { IterationEvent, SnapshotIterationRequest, SnapshotIterationResult } from "./types";
import { commitStaticSnapshot } from "@/lib/versioning/commit";

export async function startSnapshotIteration(request: SnapshotIterationRequest) {
  await ensureAppSchema();
  const db = getDb();
  await db.insert(snapshotIterationRuns).values({
    id: request.runId,
    baseSnapshotId: request.snapshotRef.snapshotId,
    projectId: request.snapshotRef.projectId || request.projectId,
    projectVersionId: request.snapshotRef.versionId,
    status: "running",
    initiativeProfile: request.initiativeProfile,
    phase: "contract",
    inputJson: JSON.stringify(request),
  }).onConflictDoUpdate({
    target: snapshotIterationRuns.id,
    set: {
      status: "running",
      initiativeProfile: request.initiativeProfile,
      phase: "contract",
      inputJson: JSON.stringify(request),
      checkpointJson: null,
      resultJson: null,
      error: null,
      completedAt: null,
    },
  });
}

export async function appendIterationEvent(event: IterationEvent) {
  await ensureAppSchema();
  const db = getDb();
  await db.insert(snapshotIterationEvents).values({
    runId: event.runId,
    snapshotId: event.snapshotId,
    seq: event.seq,
    kind: event.kind,
    eventJson: JSON.stringify(event),
  }).onConflictDoNothing();
}

export async function saveIterationCheckpoint(runId: string, phase: string, checkpoint: unknown) {
  await ensureAppSchema();
  const db = getDb();
  await db.update(snapshotIterationRuns)
    .set({ phase, checkpointJson: JSON.stringify(checkpoint) })
    .where(eq(snapshotIterationRuns.id, runId));
}

/**
 * The run and its immutable snapshot version are committed together. A run
 * with findings but no meaningful change stays durable without cloning data.
 */
export async function completeSnapshotIteration(result: SnapshotIterationResult) {
  await ensureAppSchema();
  const d1 = getD1();
  const now = new Date().toISOString();
  if (result.createdSnapshot) result.candidateSnapshotId = result.candidate.snapshot.id;
  const statements = [
    d1.prepare(`UPDATE snapshot_iteration_runs
      SET status=?, phase='snapshot', candidate_snapshot_id=?, result_json=?, completed_at=? WHERE id=?`)
      .bind(
        result.createdSnapshot ? "completed" : result.status,
        result.createdSnapshot ? result.candidate.snapshot.id : null,
        JSON.stringify(result),
        now,
        result.runId,
      ),
  ];
  if (result.createdSnapshot) await commitStaticSnapshot({
    result: result.candidate,
    parentSnapshotId: result.baseSnapshotId,
    sourceRunId: result.runId,
  });
  await d1.batch(statements);
  return result.createdSnapshot ? result.candidate.snapshot.id : null;
}

export async function attachIterationProjectVersion(result: SnapshotIterationResult, projectVersionId: string) {
  await ensureAppSchema();
  result.projectVersionId = projectVersionId;
  const db = getDb();
  await db.update(snapshotIterationRuns).set({
    projectVersionId,
    resultJson: JSON.stringify(result),
  }).where(eq(snapshotIterationRuns.id, result.runId));
}

export async function failSnapshotIteration(runId: string, error: string, cancelled = false) {
  await ensureAppSchema();
  const db = getDb();
  await db.update(snapshotIterationRuns).set({
    status: cancelled ? "cancelled" : "failed",
    error,
    completedAt: new Date().toISOString(),
  }).where(eq(snapshotIterationRuns.id, runId));
}

export async function getLatestSnapshotIteration(snapshotId: string) {
  await ensureAppSchema();
  const db = getDb();
  const [run] = await db.select().from(snapshotIterationRuns)
    .where(eq(snapshotIterationRuns.baseSnapshotId, snapshotId))
    .orderBy(desc(snapshotIterationRuns.startedAt)).limit(1);
  if (!run) return null;
  const events = await db.select().from(snapshotIterationEvents)
    .where(eq(snapshotIterationEvents.runId, run.id))
    .orderBy(asc(snapshotIterationEvents.seq));
  return {
    ...run,
    result: run.resultJson ? JSON.parse(run.resultJson) as SnapshotIterationResult : null,
    events: events.flatMap((event) => {
      try { return [JSON.parse(event.eventJson) as IterationEvent]; }
      catch { return []; }
    }),
  };
}
