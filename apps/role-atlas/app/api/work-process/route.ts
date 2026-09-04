import { projectWorkProcessPayload } from "@/lib/projects/presentation";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";

export const runtime = "edge";

export async function GET() {
  return Response.json(projectWorkProcessPayload(bundledRoleSnapshot()));
}
