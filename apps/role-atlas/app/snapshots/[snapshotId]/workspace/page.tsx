import type { Metadata } from "next";
import WorkspaceUpgradeWorkspace from "./WorkspaceUpgradeWorkspace";

export const metadata: Metadata = {
  title: "接入真实工作区 · Role Atlas",
  description: "把软件研发、运维、安全和 AI 协作工作资源蒸馏为可追溯岗位观察，并升级岗位快照与事理森林。",
};

export default async function WorkspaceUpgradePage({
  params,
  searchParams,
}: {
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<{ project?: string; version?: string; conversation?: string }>;
}) {
  const [{ snapshotId }, query] = await Promise.all([params, searchParams]);
  let decodedSnapshotId = snapshotId;
  try { decodedSnapshotId = decodeURIComponent(snapshotId); }
  catch { /* Resolver reports invalid references. */ }
  return <WorkspaceUpgradeWorkspace
    snapshotId={decodedSnapshotId}
    projectId={query.project}
    versionId={query.version}
    conversationId={query.conversation}
  />;
}
