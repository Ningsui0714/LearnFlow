import { redirect } from "next/navigation";

/** Compatibility route for bookmarks created before the two skills were merged. */
export default async function LegacySnapshotRiskPage({
  params,
  searchParams,
}: {
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<{ project?: string; version?: string; conversation?: string; mode?: string }>;
}) {
  const [{ snapshotId }, query] = await Promise.all([params, searchParams]);
  const paramsOut = new URLSearchParams({
    profile: query.mode === "scan" || query.mode === "verify" ? "autonomous" : "co_guided",
  });
  if (query.project) paramsOut.set("project", query.project);
  if (query.version) paramsOut.set("version", query.version);
  if (query.conversation) paramsOut.set("conversation", query.conversation);
  let decodedSnapshotId = snapshotId;
  try { decodedSnapshotId = decodeURIComponent(snapshotId); }
  catch { /* The destination resolver handles malformed identifiers. */ }
  redirect(`/snapshots/${encodeURIComponent(decodedSnapshotId)}/iterate?${paramsOut.toString()}`);
}
