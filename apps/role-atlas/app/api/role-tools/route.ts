import { rolePackageRuntime } from "@/lib/role-package/runtime";
import { SnapshotRoleRuntime } from "@/lib/agent/snapshot-runtime";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { ROLE_TOOL_NAMES, type RoleToolCall, type RoleToolName } from "@/lib/role-package/types";

export const runtime = "edge";

const allowedTools = new Set<RoleToolName>(ROLE_TOOL_NAMES);

export async function GET() {
  return Response.json({ ok: true, data: new SnapshotRoleRuntime(bundledRoleSnapshot()).descriptor });
}

export async function POST(request: Request) {
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > 32_768) return Response.json({ ok: false, error: { code: "RESULT_LIMIT_EXCEEDED", message: "请求体过大。" } }, { status: 413 });

  try {
    const body = await request.json() as { name?: RoleToolName; args?: Record<string, unknown>; runId?: string };
    if (!body.name || !allowedTools.has(body.name)) return Response.json({ ok: false, error: { code: "INVALID_REFERENCE", message: "工具名称无效。" } }, { status: 400 });
    const call: RoleToolCall = { name: body.name, args: body.args || {} };
    const result = await rolePackageRuntime.execute(call, typeof body.runId === "string" ? body.runId.slice(0, 80) : "http-tool");
    return Response.json(result, { status: result.ok ? 200 : 400 });
  } catch {
    return Response.json({ ok: false, error: { code: "INVALID_REFERENCE", message: "请求格式无效。" } }, { status: 400 });
  }
}
