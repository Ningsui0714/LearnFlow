/** Kept independent of the Worker binding so the exact transaction is testable with SQLite. */
export type VersionCommit = {
  id: string;
  projectId: string;
  sourceRunId: string;
  sourceKind: string;
  sourceInput: string;
  parentVersionId: string | null;
  expectedHeadId: string | null;
  version: string;
  snapshotId: string;
  rootHash: string;
  status: string;
  message: string;
  authorKind: string;
  packageJson: string;
  now: string;
  conversationId?: string | null;
};

export function versionCommitStatements(d1: D1Database, input: VersionCommit) {
  const statements = [
    d1.prepare(`INSERT INTO build_runs (id, project_id, status, input_json, result_json, started_at, completed_at)
      SELECT ?, ?, 'completed', ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM projects WHERE id=? AND deleted_at IS NULL)
      ON CONFLICT(id) DO UPDATE SET status='completed', result_json=excluded.result_json, error=NULL, completed_at=excluded.completed_at
      WHERE build_runs.project_id=excluded.project_id AND build_runs.status!='cancelled'`)
      .bind(input.sourceRunId, input.projectId, input.sourceInput, input.packageJson, input.now, input.now, input.projectId),
    // INSERT SELECT binds the run to its owning project. A conflicting run from another project cannot be reused.
    d1.prepare(`INSERT INTO project_versions
      (id, project_id, build_run_id, parent_version_id, source_run_id, source_kind, version, snapshot_id, status, root_hash, message, author_kind, package_json, created_at)
      SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
      WHERE EXISTS (SELECT 1 FROM build_runs WHERE id=? AND project_id=? AND status!='cancelled')
        AND EXISTS (SELECT 1 FROM projects WHERE id=? AND deleted_at IS NULL)`)
      .bind(input.id, input.projectId, input.sourceRunId, input.parentVersionId, input.sourceRunId, input.sourceKind,
        input.version, input.snapshotId, input.status, input.rootHash, input.message, input.authorKind, input.packageJson, input.now,
        input.sourceRunId, input.projectId, input.projectId),
    // Concurrent work based on an older head is retained as a branch, not allowed to silently replace the newer head.
    d1.prepare(`UPDATE projects SET head_version_id=?, active_version_id=?, status=?, updated_at=?
      WHERE id=? AND COALESCE(head_version_id, active_version_id) IS ?
        AND EXISTS (SELECT 1 FROM project_versions WHERE id=? AND project_id=?)`)
      .bind(input.id, input.id, input.status === "ready" ? "ready" : "draft", input.now, input.projectId,
        input.expectedHeadId, input.id, input.projectId),
    d1.prepare(`INSERT INTO project_version_events (project_id, version_id, action, actor_kind, detail_json, created_at)
      SELECT ?, ?, 'version.created', ?, ?, ? WHERE EXISTS (SELECT 1 FROM project_versions WHERE id=? AND project_id=?)`)
      .bind(input.projectId, input.id, input.authorKind,
        JSON.stringify({ sourceKind: input.sourceKind, sourceRunId: input.sourceRunId, snapshotId: input.snapshotId, rootHash: input.rootHash }),
        input.now, input.id, input.projectId),
  ];
  if (input.conversationId) statements.push(d1.prepare(`UPDATE conversations SET snapshot_id=?, version_id=?, updated_at=?
    WHERE id=? AND project_id=? AND EXISTS (SELECT 1 FROM projects WHERE id=? AND head_version_id=?)`)
    .bind(input.snapshotId, input.id, input.now, input.conversationId, input.projectId, input.projectId, input.id));
  return statements;
}
