import { getRegistryPackage } from "@/lib/registry/repository";

export const runtime = "edge";

export async function GET(_: Request, context: { params: Promise<{ packageLineId: string }> }) {
  const { packageLineId } = await context.params;
  const item = await getRegistryPackage(packageLineId);
  return item ? Response.json({ package: item }) : Response.json({ error: "岗位包线不存在。" }, { status: 404 });
}
