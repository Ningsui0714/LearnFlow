import { and, eq } from "drizzle-orm";
import { ensureAppSchema, getDb } from "@/db";
import { packageLines, packageReleases } from "@/db/schema";
import { putPackageArtifact } from "@/lib/packages/artifact-store";
import { compileStaticRolePackage } from "@/lib/packages/compiler";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { canonicalStringify, domainId, sha256Hex } from "@/lib/versioning/canonical";
import { commitStaticSnapshot } from "@/lib/versioning/commit";
import { ensureRegistryPackageLine } from "./repository";

export async function bootstrapBundledRegistryPackage() {
  await ensureAppSchema();
  const result = bundledRoleSnapshot();
  await commitStaticSnapshot({ result, sourceRunId: "bundled:llm-app-engineer" });
  const line = await ensureRegistryPackageLine({
    result,
    metadata: {
      maintainerName: "Role Atlas",
      maintainerKind: "role_atlas",
      maintenanceKind: "role_atlas",
      hostingKind: "bundled",
      visibility: "public",
      evidencePolicy: "metadata",
      license: "research-and-education",
      maintenancePolicy: { reviewCadence: "每季度或重要变化触发", updateTriggers: ["岗位标准变化", "主流技术迁移", "教学验证反馈"] },
      scope: { market: result.brief.market, audiences: result.brief.audience, industries: ["计算机与人工智能"] },
    },
  });
  const version = result.packages.rolePackage.packageVersion.match(/^\d+\.\d+\.\d+/u)?.[0] || "1.0.0";
  const db = getDb();
  const [existing] = await db.select().from(packageReleases).where(and(
    eq(packageReleases.packageLineId, line.id),
    eq(packageReleases.packageVersion, version),
  )).limit(1);
  if (existing) return { line, release: existing };
  const compiled = await compileStaticRolePackage({
    result,
    packageId: line.packageId,
    packageVersion: version,
    sourceRootHash: "bundled",
    visibility: "public",
    evidencePolicy: "metadata",
  });
  const artifact = await putPackageArtifact(compiled.bundle);
  const validationReportHash = await sha256Hex(canonicalStringify(compiled.validation));
  const releaseId = domainId("release");
  await db.insert(packageReleases).values({
    id: releaseId,
    packageLineId: line.id,
    snapshotId: result.snapshot.id,
    snapshotAsOf: result.snapshot.asOf,
    packageVersion: version,
    protocolVersion: "3.0.0",
    status: compiled.validation.valid ? "published" : "failed",
    artifactRootHash: artifact.rootHash,
    validationReportHash,
    error: compiled.validation.valid ? null : compiled.validation.hardErrors.join("\n"),
    publishedAt: compiled.validation.valid ? new Date().toISOString() : null,
  });
  if (compiled.validation.valid) {
    await db.update(packageLines).set({ recommendedReleaseId: releaseId, registryVersion: 1 }).where(eq(packageLines.id, line.id));
  }
  const [release] = await db.select().from(packageReleases).where(eq(packageReleases.id, releaseId)).limit(1);
  return { line, release };
}
