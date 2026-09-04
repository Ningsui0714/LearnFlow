import { and, desc, eq } from "drizzle-orm";
import { ensureAppSchema, getD1, getDb } from "@/db";
import { projectTags, projectVersions } from "@/db/schema";
import { domainId } from "./canonical";

const TAG_PATTERN = /^[\p{L}\p{N}][\p{L}\p{N}._\- /]{0,79}$/u;

export async function listProjectTags(projectId: string) {
  await ensureAppSchema();
  return getDb().select().from(projectTags).where(eq(projectTags.projectId, projectId)).orderBy(desc(projectTags.createdAt));
}

export async function createProjectTag(input: {
  projectId: string;
  name: string;
  targetVersionId: string;
  description?: string;
  createdBy?: string;
}) {
  await ensureAppSchema();
  const name = input.name.trim();
  if (!TAG_PATTERN.test(name)) throw new Error("INVALID_TAG_NAME");
  const db = getDb();
  const [version] = await db.select({ id: projectVersions.id }).from(projectVersions).where(and(
    eq(projectVersions.projectId, input.projectId),
    eq(projectVersions.id, input.targetVersionId),
  )).limit(1);
  if (!version) throw new Error("VERSION_NOT_FOUND");
  const id = domainId("tag");
  const now = new Date().toISOString();
  const d1 = getD1();
  await d1.batch([
    d1.prepare(`INSERT INTO project_tags (id, project_id, name, target_version_id, description, created_by, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)`)
      .bind(id, input.projectId, name, input.targetVersionId, input.description || "", input.createdBy || "user", now),
    d1.prepare(`INSERT INTO project_version_events (project_id, version_id, action, actor_kind, detail_json, created_at)
      VALUES (?, ?, 'tag.created', ?, ?, ?)`)
      .bind(input.projectId, input.targetVersionId, input.createdBy || "user", JSON.stringify({ tagId: id, name }), now),
  ]);
  return { id, projectId: input.projectId, name, targetVersionId: input.targetVersionId, description: input.description || "", createdAt: now };
}

export async function deleteProjectTag(input: { projectId: string; tagId: string; actorKind?: string }) {
  await ensureAppSchema();
  const db = getDb();
  const [tag] = await db.select().from(projectTags).where(and(eq(projectTags.projectId, input.projectId), eq(projectTags.id, input.tagId))).limit(1);
  if (!tag) return false;
  const now = new Date().toISOString();
  const d1 = getD1();
  await d1.batch([
    d1.prepare("DELETE FROM project_tags WHERE id=? AND project_id=?").bind(input.tagId, input.projectId),
    d1.prepare(`INSERT INTO project_version_events (project_id, version_id, action, actor_kind, detail_json, created_at)
      VALUES (?, ?, 'tag.deleted', ?, ?, ?)`)
      .bind(input.projectId, tag.targetVersionId, input.actorKind || "user", JSON.stringify({ tagId: tag.id, name: tag.name }), now),
  ]);
  return true;
}
