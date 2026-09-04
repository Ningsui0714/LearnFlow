import type { Metadata } from "next";
import RoleWorkspace from "@/app/RoleWorkspace";

export const metadata: Metadata = {
  title: "岗位项目 · Role Atlas",
  description: "查看版本化岗位快照、语义图谱、事理森林与项目会话。",
};

export default async function ProjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ conversation?: string }>;
}) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  return <RoleWorkspace projectId={projectId} initialConversationId={query.conversation} />;
}
