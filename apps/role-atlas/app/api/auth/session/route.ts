import { env } from "cloudflare:workers";
import { resolveLearnFlowIdentity } from "@/lib/integrations/learnflow/auth";

export const runtime = "edge";

type AuthBindings = { LEARNFLOW_BASE_URL?: string };

export async function GET(request: Request) {
  const baseUrl = String((env as unknown as AuthBindings).LEARNFLOW_BASE_URL || "").trim();
  if (!baseUrl) {
    return Response.json({
      authenticated: false,
      provider: "learnflow",
      error: "LEARNFLOW_AUTH_NOT_CONFIGURED",
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  try {
    const identity = await resolveLearnFlowIdentity({ request, baseUrl });
    return Response.json(identity
      ? { authenticated: true, provider: "learnflow", user: identity }
      : { authenticated: false, provider: "learnflow" }, {
      status: identity ? 200 : 401,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    return Response.json({
      authenticated: false,
      provider: "learnflow",
      error: error instanceof Error ? error.message : "LEARNFLOW_AUTH_UNAVAILABLE",
    }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
