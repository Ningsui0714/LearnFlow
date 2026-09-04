import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { mayManageProject, projectLifecycleStatements } from "@/lib/projects/lifecycle";

test("删除归属来自服务端身份；无主历史项目仅允许管理员", () => {
  assert.equal(mayManageProject("learner:1", { subjectId: "learner:1", role: "user" }), true);
  assert.equal(mayManageProject("learner:1", { subjectId: "learner:2", role: "user" }), false);
  assert.equal(mayManageProject(null, { subjectId: "learner:1", role: "user" }), false);
  assert.equal(mayManageProject(null, { subjectId: "admin", role: "admin" }), true);
});

test("软删除、停止运行与审计原子执行；恢复保留历史但不自动重启取消任务", () => {
  const db = new DatabaseSync(":memory:");
  try {
    db.exec(`CREATE TABLE projects(id TEXT PRIMARY KEY, owner_subject_id TEXT, deleted_at TEXT, deleted_by TEXT, updated_at TEXT);
      CREATE TABLE project_version_events(project_id TEXT, version_id TEXT, action TEXT, actor_kind TEXT, detail_json TEXT, created_at TEXT);
      CREATE TABLE role_jobs(project_id TEXT, status TEXT, lease_owner TEXT, lease_expires_at TEXT, error TEXT, completed_at TEXT, updated_at TEXT);
      CREATE TABLE package_releases(project_id TEXT, root_hash TEXT);
      INSERT INTO projects(id, owner_subject_id) VALUES('p1', 'learner:1'), ('p2','learner:2');
      INSERT INTO role_jobs(project_id,status,lease_owner) VALUES('p1','running','worker'), ('p2','running','other');
      INSERT INTO package_releases VALUES('p1','immutable-hash');`);
    for (const table of ["build_runs", "risk_runs", "snapshot_risk_runs", "snapshot_iteration_runs", "workspace_ingestion_runs"]) {
      db.exec(`CREATE TABLE ${table}(project_id TEXT, status TEXT, error TEXT, completed_at TEXT); INSERT INTO ${table} VALUES('p1','running',NULL,NULL);`);
    }
    const binding = { prepare: (sql: string) => ({ bind: (...values: (string | null)[]) => ({ sql, values }) }) } as unknown as D1Database;
    const change = (subjectId: string, action: "delete" | "restore") => {
      db.exec("BEGIN");
      try {
        for (const raw of projectLifecycleStatements(binding, { projectId: "p1", actor: { subjectId, role: "user" }, action, now: "2026-09-04T12:00:00Z" })) {
          const statement = raw as unknown as { sql: string; values: (string | null)[] };
          db.prepare(statement.sql).run(...statement.values);
        }
        db.exec("COMMIT");
      } catch (error) { db.exec("ROLLBACK"); throw error; }
    };
    change("learner:2", "delete");
    assert.equal(db.prepare("SELECT deleted_at FROM projects WHERE id='p1'").get()?.deleted_at, null);
    assert.equal(db.prepare("SELECT status FROM role_jobs WHERE project_id='p1'").get()?.status, "running");
    change("learner:1", "delete");
    change("learner:1", "delete");
    assert.equal(db.prepare("SELECT count(*) AS n FROM project_version_events").get()?.n, 1);
    assert.equal(db.prepare("SELECT status FROM build_runs WHERE project_id='p1'").get()?.status, "cancelled");
    assert.equal(db.prepare("SELECT lease_owner FROM role_jobs WHERE project_id='p1'").get()?.lease_owner, null);
    assert.equal(db.prepare("SELECT status FROM role_jobs WHERE project_id='p2'").get()?.status, "running");
    assert.equal(db.prepare("SELECT root_hash FROM package_releases").get()?.root_hash, "immutable-hash");
    change("learner:1", "restore");
    assert.equal(db.prepare("SELECT deleted_at FROM projects WHERE id='p1'").get()?.deleted_at, null);
    assert.equal(db.prepare("SELECT status FROM role_jobs WHERE project_id='p1'").get()?.status, "cancelled");
    assert.equal(db.prepare("SELECT count(*) AS n FROM project_version_events").get()?.n, 2);
  } finally { db.close(); }
});
