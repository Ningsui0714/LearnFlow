import { ensureAppSchema, getD1 } from "@/db";
import type { RoleJobCheckpoint, RoleJobDescriptor, RoleJobKind, RoleJobStatus } from "./runtime";

type RoleJobRow = {
  id: string;
  kind: RoleJobKind;
  thread_id: string;
  project_id: string | null;
  base_snapshot_id: string | null;
  status: RoleJobStatus;
  phase: string;
  attempt: number;
  input_json: string;
  checkpoint_json: string | null;
  result_json: string | null;
  lease_owner: string | null;
  lease_expires_at: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

function isoAfter(milliseconds: number) {
  return new Date(Date.now() + milliseconds).toISOString();
}

function descriptor(row: RoleJobRow): RoleJobDescriptor {
  return {
    id: row.id,
    kind: row.kind,
    threadId: row.thread_id,
    projectId: row.project_id || undefined,
    baseSnapshotId: row.base_snapshot_id || undefined,
    status: row.status,
    phase: row.phase,
    attempt: row.attempt,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function parseJson<T>(value: string | null): T | undefined {
  if (!value) return undefined;
  try { return JSON.parse(value) as T; }
  catch { return undefined; }
}

export async function claimRoleJob(input: {
  id: string;
  kind: RoleJobKind;
  threadId: string;
  owner: string;
  projectId?: string;
  baseSnapshotId?: string;
  phase: string;
  payload?: unknown;
  leaseMs?: number;
}) {
  await ensureAppSchema();
  const d1 = getD1();
  const now = new Date().toISOString();
  const expiresAt = isoAfter(input.leaseMs || 45_000);
  await d1.batch([
    d1.prepare(`INSERT OR IGNORE INTO role_jobs
      (id, kind, thread_id, project_id, base_snapshot_id, status, phase, attempt, input_json, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?)`)
      .bind(input.id, input.kind, input.threadId, input.projectId || null, input.baseSnapshotId || null, input.phase, JSON.stringify(input.payload || {}), now, now),
    d1.prepare(`UPDATE role_jobs SET
        kind=?, thread_id=?, project_id=COALESCE(?, project_id), base_snapshot_id=COALESCE(?, base_snapshot_id),
        status='running', attempt=attempt+1, input_json=?, lease_owner=?, lease_expires_at=?,
        error=NULL, completed_at=NULL, updated_at=?
      WHERE id=?
        AND status NOT IN ('completed', 'cancelled')
        AND (lease_owner IS NULL OR lease_owner=? OR lease_expires_at IS NULL OR lease_expires_at<=?)`)
      .bind(input.kind, input.threadId, input.projectId || null, input.baseSnapshotId || null, JSON.stringify(input.payload || {}), input.owner, expiresAt, now, input.id, input.owner, now),
  ]);
  const row = await d1.prepare("SELECT * FROM role_jobs WHERE id=?").bind(input.id).first<RoleJobRow>();
  const claimed = Boolean(row && row.status === "running" && row.lease_owner === input.owner);
  return {
    claimed,
    job: row ? descriptor(row) : undefined,
    checkpoint: row ? parseJson<RoleJobCheckpoint>(row.checkpoint_json) : undefined,
    leaseExpiresAt: row?.lease_expires_at || undefined,
  };
}

export async function renewRoleJobLease(jobId: string, owner: string, leaseMs = 45_000) {
  await ensureAppSchema();
  const now = new Date().toISOString();
  const expiresAt = isoAfter(leaseMs);
  await getD1().prepare(`UPDATE role_jobs SET lease_expires_at=?, updated_at=?
    WHERE id=? AND lease_owner=? AND status='running'`).bind(expiresAt, now, jobId, owner).run();
  const row = await getD1().prepare("SELECT lease_owner, status FROM role_jobs WHERE id=?").bind(jobId).first<{ lease_owner: string | null; status: RoleJobStatus }>();
  return Boolean(row?.lease_owner === owner && row.status === "running");
}

export async function checkpointRoleJob(input: {
  jobId: string;
  owner: string;
  kind: RoleJobKind;
  phase: string;
  state: unknown;
  leaseMs?: number;
}) {
  await ensureAppSchema();
  const row = await getD1().prepare("SELECT attempt FROM role_jobs WHERE id=? AND lease_owner=? AND status='running'")
    .bind(input.jobId, input.owner).first<{ attempt: number }>();
  if (!row) return false;
  const savedAt = new Date().toISOString();
  const checkpoint: RoleJobCheckpoint = {
    jobId: input.jobId,
    kind: input.kind,
    phase: input.phase,
    attempt: row.attempt,
    state: input.state,
    savedAt,
  };
  await getD1().prepare(`UPDATE role_jobs SET phase=?, checkpoint_json=?, lease_expires_at=?, updated_at=?
    WHERE id=? AND lease_owner=? AND status='running'`)
    .bind(input.phase, JSON.stringify(checkpoint), isoAfter(input.leaseMs || 45_000), savedAt, input.jobId, input.owner).run();
  return true;
}

export async function completeRoleJob(input: { jobId: string; owner: string; phase: string; result?: unknown }) {
  await ensureAppSchema();
  const now = new Date().toISOString();
  await getD1().prepare(`UPDATE role_jobs SET status='completed', phase=?, result_json=?, lease_owner=NULL,
    lease_expires_at=NULL, error=NULL, completed_at=?, updated_at=?
    WHERE id=? AND lease_owner=? AND status='running'`)
    .bind(input.phase, JSON.stringify(input.result || {}), now, now, input.jobId, input.owner).run();
}

export async function failRoleJob(input: { jobId: string; owner: string; error: string; retryable: boolean }) {
  await ensureAppSchema();
  const now = new Date().toISOString();
  await getD1().prepare(`UPDATE role_jobs SET status=?, lease_owner=NULL, lease_expires_at=NULL, error=?,
    completed_at=?, updated_at=? WHERE id=? AND lease_owner=? AND status='running'`)
    .bind(input.retryable ? "queued" : "failed", input.error, input.retryable ? null : now, now, input.jobId, input.owner).run();
}

export async function getRoleJob(jobId: string) {
  await ensureAppSchema();
  const row = await getD1().prepare("SELECT * FROM role_jobs WHERE id=?").bind(jobId).first<RoleJobRow>();
  if (!row) return null;
  return {
    ...descriptor(row),
    checkpoint: parseJson<RoleJobCheckpoint>(row.checkpoint_json),
    result: parseJson<unknown>(row.result_json),
    leaseExpiresAt: row.lease_expires_at || undefined,
    error: row.error || undefined,
    completedAt: row.completed_at || undefined,
  };
}
