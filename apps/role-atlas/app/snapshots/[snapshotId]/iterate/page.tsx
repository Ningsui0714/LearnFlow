import type { Metadata } from "next";
import IterationWorkspace from "./IterationWorkspace";
import type { InitiativeProfile } from "@/lib/iteration/types";

export const metadata: Metadata = {
  title: "岗位快照迭代 · Role Atlas",
  description: "对任意岗位静态快照运行自动发现、定向研究、补证、扩展、修复与回归。",
};

const profiles = new Set<InitiativeProfile>(["autonomous", "co_guided", "user_directed"]);

export default async function SnapshotIterationPage({
  params,
  searchParams,
}: {
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<{ project?: string; version?: string; conversation?: string; profile?: string; prompt?: string; targets?: string }>;
}) {
  const [{ snapshotId }, query] = await Promise.all([params, searchParams]);
  let decodedSnapshotId = snapshotId;
  try { decodedSnapshotId = decodeURIComponent(snapshotId); }
  catch { /* Invalid encodings are handled by the snapshot resolver. */ }
  const initialProfile = profiles.has(query.profile as InitiativeProfile) ? query.profile as InitiativeProfile : "co_guided";
  return <IterationWorkspace snapshotId={decodedSnapshotId} projectId={query.project} versionId={query.version} conversationId={query.conversation} initialProfile={initialProfile} initialPrompt={query.prompt} initialTargetIds={query.targets} />;
}
