import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { versionCommitStatements, type VersionCommit } from "@/lib/versioning/commit-transaction";
import { projectVersionLabel } from "@/lib/versioning/canonical";

function database() {
  const db = new DatabaseSync(":memory:");
  db.exec(`CREATE TABLE projects(id TEXT PRIMARY KEY, head_version_id TEXT, active_version_id TEXT, status TEXT, updated_at TEXT, deleted_at TEXT);
    CREATE TABLE build_runs(id TEXT PRIMARY KEY, project_id TEXT, status TEXT, input_json TEXT, result_json TEXT, error TEXT, started_at TEXT, completed_at TEXT);
    CREATE TABLE project_versions(id TEXT PRIMARY KEY, project_id TEXT, build_run_id TEXT, parent_version_id TEXT, source_run_id TEXT, source_kind TEXT, version TEXT,
      snapshot_id TEXT, status TEXT, root_hash TEXT, message TEXT, author_kind TEXT, package_json TEXT, created_at TEXT,
      UNIQUE(project_id, version), UNIQUE(project_id, source_run_id));
    CREATE TABLE project_version_events(project_id TEXT, version_id TEXT, action TEXT, actor_kind TEXT, detail_json TEXT, created_at TEXT);
    CREATE TABLE conversations(id TEXT PRIMARY KEY, project_id TEXT, snapshot_id TEXT, version_id TEXT, updated_at TEXT);
    INSERT INTO projects(id) VALUES ('project:1'), ('project:other');
    INSERT INTO conversations(id, project_id) VALUES ('conversation:1', 'project:1');`);
  const binding = { prepare: (sql: string) => ({ bind: (...values: (string | number | null)[]) => ({ sql, values }) }) } as unknown as D1Database;
  const commit = (input: VersionCommit) => {
    db.exec("BEGIN");
    try {
      const changes = versionCommitStatements(binding, input).map(value => {
        const statement = value as unknown as { sql: string; values: (string | number | null)[] };
        return db.prepare(statement.sql).run(...statement.values).changes;
      });
      db.exec("COMMIT");
      return changes;
    } catch (error) { db.exec("ROLLBACK"); throw error; }
  };
  return { db, commit };
}

function input(run: string, patch: Partial<VersionCommit> = {}): VersionCommit {
  return { id: `pv:${run}`, projectId: "project:1", sourceRunId: run, sourceKind: "iteration", sourceInput: "{}", parentVersionId: null, expectedHeadId: null,
    version: projectVersionLabel("2026-09-04T12:00:00.000Z", "a".repeat(64), run), snapshotId: "same-snapshot", rootHash: "a".repeat(64), status: "ready",
    message: "测试提交", authorKind: "agent", packageJson: "{}", now: "2026-09-04T12:00:00.000Z", conversationId: "conversation:1", ...patch };
}

test("同秒同快照的不同操作拥有不同版本标签，保留并发分支而不覆盖新 head", () => {
  const { db, commit } = database();
  try {
    commit(input("run:1"));
    commit(input("run:2"));
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_versions").get()?.n, 2);
    assert.equal(db.prepare("SELECT head_version_id FROM projects WHERE id='project:1'").get()?.head_version_id, "pv:run:1");
    assert.equal(db.prepare("SELECT version_id FROM conversations WHERE id='conversation:1'").get()?.version_id, "pv:run:1");
    commit(input("run:3", { parentVersionId: "pv:run:1", expectedHeadId: "pv:run:1" }));
    assert.equal(db.prepare("SELECT head_version_id FROM projects WHERE id='project:1'").get()?.head_version_id, "pv:run:3");
  } finally { db.close(); }
});

test("重复 source run 被数据库拒绝且整个批次回滚，原版本、结果和审计不变", () => {
  const { db, commit } = database();
  try {
    commit(input("run:1"));
    assert.throws(() => commit(input("run:1", { id: "pv:duplicate", packageJson: '{"changed":true}' })), /UNIQUE/);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_versions").get()?.n, 1);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_version_events").get()?.n, 1);
    assert.equal(db.prepare("SELECT result_json FROM build_runs").get()?.result_json, "{}");
  } finally { db.close(); }
});

test("不可借用其他项目的运行身份提交版本", () => {
  const { db, commit } = database();
  try {
    db.prepare("INSERT INTO build_runs(id,project_id) VALUES (?,?)").run("foreign-run", "project:other");
    const changes = commit(input("foreign-run"));
    assert.equal(Number(changes[1]), 0);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_versions").get()?.n, 0);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_version_events").get()?.n, 0);
  } finally { db.close(); }
});

test("删除项目和取消运行阻止迟到的后台写入，即使项目随后恢复", () => {
  const { db, commit } = database();
  try {
    db.exec("UPDATE projects SET deleted_at='deleted' WHERE id='project:1'");
    assert.equal(Number(commit(input("late-run"))[1]), 0);
    db.exec("UPDATE projects SET deleted_at=NULL WHERE id='project:1'; INSERT INTO build_runs(id,project_id,status) VALUES('cancelled-run','project:1','cancelled')");
    assert.equal(Number(commit(input("cancelled-run"))[1]), 0);
    assert.equal(db.prepare("SELECT COUNT(*) AS n FROM project_versions").get()?.n, 0);
  } finally { db.close(); }
});
