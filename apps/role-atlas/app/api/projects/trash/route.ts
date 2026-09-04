import { ensureAppSchema, getD1 } from "@/db";
import { projectActor } from "@/lib/projects/lifecycle-api";

export async function GET(request: Request) {
  try {
    const actor = await projectActor(request);
    if (actor instanceof Response) return actor;
    await ensureAppSchema();
    const rows = await getD1().prepare(`SELECT id, title, deleted_at AS deletedAt FROM projects
      WHERE deleted_at IS NOT NULL AND (owner_subject_id=? OR ?='admin') ORDER BY deleted_at DESC`)
      .bind(actor.subjectId, actor.role).all();
    return Response.json({ projects: rows.results }, { headers: { "Cache-Control": "no-store" } });
  } catch { return Response.json({ error: "回收站读取失败。" }, { status: 503 }); }
}
