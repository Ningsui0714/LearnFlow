import { and, desc, eq, inArray } from "drizzle-orm";
import { ensureAppSchema, getDb } from "@/db";
import { packageLines, packageReleases } from "@/db/schema";
import { getPackageArtifact } from "@/lib/packages/artifact-store";
import { reconstructBuildResult } from "@/lib/packages/compiler";

export async function getReleaseWithArtifact(releaseId: string) {
  await ensureAppSchema();
  const db = getDb();
  const [release] = await db.select().from(packageReleases).where(eq(packageReleases.id, releaseId)).limit(1);
  if (!release?.artifactRootHash) return null;
  const artifact = await getPackageArtifact(release.artifactRootHash);
  if (!artifact) return null;
  const [line] = await db.select().from(packageLines).where(eq(packageLines.id, release.packageLineId)).limit(1);
  return { release, line, ...artifact, result: reconstructBuildResult(artifact.bundle) };
}

export async function findReleaseBySnapshot(input: { snapshotId: string; packageVersion?: string }) {
  await ensureAppSchema();
  const db = getDb();
  const usable = inArray(packageReleases.status, ["ready", "published", "deprecated"]);
  const rows = input.packageVersion
    ? await db.select().from(packageReleases).where(and(eq(packageReleases.snapshotId, input.snapshotId), eq(packageReleases.packageVersion, input.packageVersion), usable)).orderBy(desc(packageReleases.publishedAt), desc(packageReleases.createdAt)).limit(1)
    : await db.select().from(packageReleases).where(and(eq(packageReleases.snapshotId, input.snapshotId), usable)).orderBy(desc(packageReleases.publishedAt), desc(packageReleases.createdAt)).limit(1);
  return rows[0] ? getReleaseWithArtifact(rows[0].id) : null;
}
