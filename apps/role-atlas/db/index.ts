import { env } from "cloudflare:workers";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";
import { applyRuntimeMigrations } from "./migrations";

type DatabaseBindings = { DB?: D1Database };

export function getD1() {
  const bindings = env as unknown as DatabaseBindings;
  if (!bindings.DB) {
    throw new Error("Cloudflare D1 binding `DB` is unavailable.");
  }
  return bindings.DB;
}

export function getDb() {
  return drizzle(getD1(), { schema });
}

let schemaReady: Promise<void> | null = null;

export function ensureAppSchema() {
  if (schemaReady) return schemaReady;
  const d1 = getD1();
  schemaReady = d1.batch([
    d1.prepare(`CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY NOT NULL,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      market TEXT NOT NULL DEFAULT '中国大陆',
      status TEXT NOT NULL DEFAULT 'draft',
      active_version_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      snapshot_id TEXT,
      version_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY NOT NULL,
      conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      text TEXT NOT NULL DEFAULT '',
      reasoning TEXT NOT NULL DEFAULT '',
      references_json TEXT NOT NULL DEFAULT '[]',
      activities_json TEXT NOT NULL DEFAULT '[]',
      citations_json TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'done',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS build_runs (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'running',
      input_json TEXT NOT NULL,
      result_json TEXT,
      error TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS build_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
      run_id TEXT NOT NULL REFERENCES build_runs(id) ON DELETE CASCADE,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      seq INTEGER NOT NULL,
      kind TEXT NOT NULL,
      event_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS project_versions (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      build_run_id TEXT NOT NULL REFERENCES build_runs(id) ON DELETE CASCADE,
      version TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'candidate',
      package_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS risk_runs (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      base_version_id TEXT NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
      candidate_version_id TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      mode TEXT NOT NULL,
      phase TEXT NOT NULL DEFAULT 'baseline',
      input_json TEXT NOT NULL,
      checkpoint_json TEXT,
      result_json TEXT,
      error TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS risk_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
      run_id TEXT NOT NULL REFERENCES risk_runs(id) ON DELETE CASCADE,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      seq INTEGER NOT NULL,
      kind TEXT NOT NULL,
      event_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS risk_issues (
      id TEXT NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      run_id TEXT NOT NULL REFERENCES risk_runs(id) ON DELETE CASCADE,
      fingerprint TEXT NOT NULL,
      profile TEXT NOT NULL,
      severity TEXT NOT NULL,
      status TEXT NOT NULL,
      issue_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS risk_patches (
      id TEXT NOT NULL,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      run_id TEXT NOT NULL REFERENCES risk_runs(id) ON DELETE CASCADE,
      iteration INTEGER NOT NULL,
      status TEXT NOT NULL,
      patch_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS snapshot_versions (
      snapshot_id TEXT PRIMARY KEY NOT NULL,
      parent_snapshot_id TEXT,
      package_id TEXT NOT NULL,
      package_version TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'candidate',
      package_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS snapshot_risk_runs (
      id TEXT PRIMARY KEY NOT NULL,
      base_snapshot_id TEXT NOT NULL,
      candidate_snapshot_id TEXT,
      project_id TEXT,
      project_version_id TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      mode TEXT NOT NULL,
      phase TEXT NOT NULL DEFAULT 'snapshot',
      input_json TEXT NOT NULL,
      checkpoint_json TEXT,
      result_json TEXT,
      error TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS snapshot_risk_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
      run_id TEXT NOT NULL REFERENCES snapshot_risk_runs(id) ON DELETE CASCADE,
      snapshot_id TEXT NOT NULL,
      seq INTEGER NOT NULL,
      kind TEXT NOT NULL,
      event_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS snapshot_iteration_runs (
      id TEXT PRIMARY KEY NOT NULL,
      base_snapshot_id TEXT NOT NULL,
      candidate_snapshot_id TEXT,
      project_id TEXT,
      project_version_id TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      initiative_profile TEXT NOT NULL,
      phase TEXT NOT NULL DEFAULT 'contract',
      input_json TEXT NOT NULL,
      checkpoint_json TEXT,
      result_json TEXT,
      error TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS snapshot_iteration_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
      run_id TEXT NOT NULL REFERENCES snapshot_iteration_runs(id) ON DELETE CASCADE,
      snapshot_id TEXT NOT NULL,
      seq INTEGER NOT NULL,
      kind TEXT NOT NULL,
      event_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS workspace_ingestion_runs (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT,
      base_snapshot_id TEXT,
      iteration_run_id TEXT,
      adapter_id TEXT NOT NULL,
      package_id TEXT,
      status TEXT NOT NULL DEFAULT 'running',
      phase TEXT NOT NULL DEFAULT 'register',
      input_json TEXT NOT NULL,
      checkpoint_json TEXT,
      result_json TEXT,
      alignment_json TEXT,
      error TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    )`),
    d1.prepare(`CREATE TABLE IF NOT EXISTS workspace_ingestion_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
      run_id TEXT NOT NULL REFERENCES workspace_ingestion_runs(id) ON DELETE CASCADE,
      seq INTEGER NOT NULL,
      kind TEXT NOT NULL,
      event_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_conversations_project_updated ON conversations(project_id, updated_at DESC)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at ASC)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_build_runs_project_started ON build_runs(project_id, started_at DESC)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_build_events_run_seq ON build_events(run_id, seq)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_project_versions_project_version ON project_versions(project_id, version)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_risk_runs_project_started ON risk_runs(project_id, started_at DESC)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_events_run_seq ON risk_events(run_id, seq)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_issues_run_id ON risk_issues(run_id, id)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_risk_issues_project_fingerprint ON risk_issues(project_id, fingerprint)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_patches_run_id ON risk_patches(run_id, id)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_snapshot_risk_runs_base_started ON snapshot_risk_runs(base_snapshot_id, started_at DESC)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_risk_events_run_seq ON snapshot_risk_events(run_id, seq)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_snapshot_iteration_runs_base_started ON snapshot_iteration_runs(base_snapshot_id, started_at DESC)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_iteration_events_run_seq ON snapshot_iteration_events(run_id, seq)"),
    d1.prepare("CREATE INDEX IF NOT EXISTS idx_workspace_ingestion_runs_project_started ON workspace_ingestion_runs(project_id, started_at DESC)"),
    d1.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_ingestion_events_run_seq ON workspace_ingestion_events(run_id, seq)"),
  ]).then(async () => {
    // Existing development databases predate exact package-version pinning.
    // SQLite has no portable ADD COLUMN IF NOT EXISTS, so inspect first.
    const info = await d1.prepare("PRAGMA table_info(conversations)").all<{ name: string }>();
    if (!info.results.some((column) => column.name === "version_id")) {
      await d1.prepare("ALTER TABLE conversations ADD COLUMN version_id TEXT").run();
    }
    await applyRuntimeMigrations(d1);
  }).catch((error) => {
    schemaReady = null;
    throw error;
  });
  return schemaReady;
}
