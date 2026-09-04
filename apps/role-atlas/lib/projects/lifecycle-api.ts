import { ensureAppSchema, getD1 } from "@/db";
import { resolveLearnFlowIdentity } from "@/lib/integrations/learnflow/auth";
import { mayManageProject, projectLifecycleStatements, type ProjectActor } from "./lifecycle";

export async function projectActor(request: Request): Promise<ProjectActor | Response> {
  const origin = request.headers.get("origin");
  const allowed = [new URL(request.url).origin];
  if (process.env.ROLE_ATLAS_PUBLIC_URL) allowed.push(new URL(process.env.ROLE_ATLAS_PUBLIC_URL).origin);
  if (origin && !allowed.includes(origin)) return Response.json({ error: "不允许跨站管理岗位项目。" }, { status: 403 });
  const baseUrl = process.env.LEARNFLOW_BASE_URL;
  if (!baseUrl) return Response.json({ error: "尚未配置身份服务，项目删除和恢复暂不可用。" }, { status: 503 });
  const identity = await resolveLearnFlowIdentity({ request, baseUrl });
  if (!identity) return Response.json({ error: "请先登录 LearnFlow 后管理岗位项目。" }, { status: 401 });
  return identity;
}

export async function manageProject(request: Request, projectId: string, action: "delete" | "restore") {
  try {
    const actor = await projectActor(request);
    if (actor instanceof Response) return actor;
    await ensureAppSchema();
    const d1 = getD1();
    const project = await d1.prepare("SELECT id, owner_subject_id FROM projects WHERE id=?").bind(projectId)
      .first<{ id: string; owner_subject_id: string | null }>();
    if (!project) return Response.json({ error: "项目不存在。" }, { status: 404 });
    if (!mayManageProject(project.owner_subject_id, actor)) return Response.json({ error: project.owner_subject_id
      ? "只有项目所有者或管理员可以执行此操作。" : "此历史项目尚未登记所有者，只有管理员可以删除或恢复。" }, { status: 403 });
    await d1.batch(projectLifecycleStatements(d1, { projectId, actor, action, now: new Date().toISOString() }));
    return Response.json({ projectId, status: action === "delete" ? "deleted" : "restored", recoverable: true }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "项目管理服务暂时不可用，请稍后重试。" }, { status: 503 });
  }
}
