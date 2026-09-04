import type { Metadata } from "next";
import { bootstrapBundledRegistryPackage } from "@/lib/registry/bootstrap";
import { listPublicHubEntries } from "@/lib/hub/repository";
import GraphHubMarketplace from "./GraphHubMarketplace";

export const metadata: Metadata = { title: "图谱市场 · Graph Hub" };

export default async function GraphHubPage({ searchParams }: { searchParams: Promise<{ q?: string; category?: string }> }) {
  await bootstrapBundledRegistryPackage().catch(() => null);
  const params = await searchParams;
  const query = String(params.q || "");
  return <GraphHubMarketplace
    initialPackages={await listPublicHubEntries()}
    initialQuery={query}
    initialCategory={params.category || ""}
    roleAtlasBaseUrl={process.env.ROLE_ATLAS_PUBLIC_URL || ""}
  />;
}
