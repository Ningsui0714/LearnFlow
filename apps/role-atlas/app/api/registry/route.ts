import { z } from "zod/v4";
import { bootstrapBundledRegistryPackage } from "@/lib/registry/bootstrap";
import { listRegistryPackages, updateRegistryPackageStatus } from "@/lib/registry/repository";

export const runtime = "edge";

export async function GET(request: Request) {
  await bootstrapBundledRegistryPackage().catch(() => null);
  const params = new URL(request.url).searchParams;
  const packages = await listRegistryPackages({
    query: params.get("q") || undefined,
    visibility: params.get("visibility") || undefined,
    status: params.get("status") || undefined,
  });
  return Response.json({ packages, graphHubBaseUrl: process.env.GRAPH_HUB_PUBLIC_URL || "" });
}

const patchSchema = z.object({
  packageLineId: z.string().min(4),
  status: z.enum(["active", "disputed", "deprecated", "superseded"]),
  supersededByPackageLineId: z.string().min(4).nullable().optional(),
});

export async function PATCH(request: Request) {
  try {
    const input = patchSchema.parse(await request.json());
    return Response.json({ package: await updateRegistryPackageStatus(input) });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Registry 更新失败。" }, { status: 400 });
  }
}
