export type ProjectActor = { subjectId: string; role: "user" | "admin" };

export function mayManageProject(ownerSubjectId: string | null, actor: ProjectActor) {
  return actor.role === "admin" || Boolean(ownerSubjectId && ownerSubjectId === actor.subjectId);
}

export function projectLifecycleStatements(d1: D1Database, input: { projectId: string; actor: ProjectActor; action: "delete" | "restore"; now: string }) {
  const { projectId, actor, action, now } = input;
  const restoring = action === "restore";
  const statements = [
    d1.prepare(`UPDATE projects SET deleted_at=?, deleted_by=?, updated_at=?
      WHERE id=? AND (owner_subject_id=? OR ?='admin') AND deleted_at IS ${restoring ? "NOT " : ""}NULL`)
      .bind(restoring ? null : now, restoring ? null : actor.subjectId, now, projectId, actor.subjectId, actor.role),
    d1.prepare(`INSERT INTO project_version_events(project_id, version_id, action, actor_kind, detail_json, created_at)
      SELECT ?, NULL, ?, 'user', ?, ? WHERE changes()>0`)
      .bind(projectId, restoring ? "project.restored" : "project.deleted", JSON.stringify({ subjectId: actor.subjectId, recoverable: true }), now),
  ];
  if (!restoring) {
    // Cancel work and revoke leases in the same transaction. Artifacts/releases/history are untouched.
    for (const table of ["build_runs", "risk_runs", "snapshot_risk_runs", "snapshot_iteration_runs", "workspace_ingestion_runs"]) {
      statements.push(d1.prepare(`UPDATE ${table} SET status='cancelled', error='PROJECT_DELETED', completed_at=?
        WHERE project_id=? AND status='running' AND EXISTS (SELECT 1 FROM projects WHERE id=? AND deleted_at IS NOT NULL AND (owner_subject_id=? OR ?='admin'))`)
        .bind(now, projectId, projectId, actor.subjectId, actor.role));
    }
    statements.push(d1.prepare(`UPDATE role_jobs SET status='cancelled', lease_owner=NULL, lease_expires_at=NULL,
      error='PROJECT_DELETED', completed_at=?, updated_at=? WHERE project_id=? AND status IN ('queued','running','waiting_user')
      AND EXISTS (SELECT 1 FROM projects WHERE id=? AND deleted_at IS NOT NULL AND (owner_subject_id=? OR ?='admin'))`)
      .bind(now, now, projectId, projectId, actor.subjectId, actor.role));
  }
  return statements;
}
