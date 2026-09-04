import { roleAtlasHref } from "@/lib/public-links";

export async function GET(request: Request) {
  try {
    const path = new URL(request.url).searchParams.get("path") || "/";
    const target = roleAtlasHref(process.env.ROLE_ATLAS_PUBLIC_URL, path);
    if (target.startsWith("/")) return Response.json({
      error: "ROLE_ATLAS_PUBLIC_URL_NOT_CONFIGURED",
      message: "Role Atlas 入口尚未配置，请管理员设置 ROLE_ATLAS_PUBLIC_URL 后重新启动服务。",
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
    return Response.redirect(target, 307);
  } catch {
    return Response.json({ error: "PUBLIC_LINK_PATH_INVALID" }, { status: 400 });
  }
}
