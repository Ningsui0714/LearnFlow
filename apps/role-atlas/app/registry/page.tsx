import type { Metadata } from "next";
import { bootstrapBundledRegistryPackage } from "@/lib/registry/bootstrap";
import { listRegistryPackages } from "@/lib/registry/repository";
import RegistryCatalog from "./RegistryCatalog";

export const metadata: Metadata = { title: "岗位包中心 · Role Atlas" };

export default async function RegistryPage() {
  await bootstrapBundledRegistryPackage().catch(() => null);
  return <RegistryCatalog
    initialPackages={await listRegistryPackages()}
    roleAtlasBaseUrl={process.env.ROLE_ATLAS_PUBLIC_URL || ""}
    graphHubBaseUrl={process.env.GRAPH_HUB_PUBLIC_URL || ""}
  />;
}
