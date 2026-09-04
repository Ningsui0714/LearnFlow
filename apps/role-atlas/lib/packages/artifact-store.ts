import { eq } from "drizzle-orm";
import { ensureAppSchema, getDb } from "@/db";
import { packageArtifacts } from "@/db/schema";
import { bundleFromJson, bundleToJson } from "./archive";
import type { StaticRolePackageBundle } from "./types";

export async function putPackageArtifact(bundle: StaticRolePackageBundle) {
  await ensureAppSchema();
  const content = bundleToJson(bundle);
  const db = getDb();
  const [existing] = await db.select().from(packageArtifacts).where(eq(packageArtifacts.rootHash, bundle.manifest.rootHash)).limit(1);
  if (existing) {
    if (existing.content !== content) throw new Error("ARTIFACT_HASH_CONFLICT");
    return existing;
  }
  const value = {
    rootHash: bundle.manifest.rootHash,
    artifactKind: "static-role-package",
    mediaType: "application/vnd.role-atlas.package+json",
    byteSize: new TextEncoder().encode(content).byteLength,
    content,
  };
  await db.insert(packageArtifacts).values(value);
  return value;
}

export async function getPackageArtifact(rootHash: string) {
  await ensureAppSchema();
  const [row] = await getDb().select().from(packageArtifacts).where(eq(packageArtifacts.rootHash, rootHash)).limit(1);
  if (!row?.content) return null;
  return { row, bundle: bundleFromJson(row.content) };
}
