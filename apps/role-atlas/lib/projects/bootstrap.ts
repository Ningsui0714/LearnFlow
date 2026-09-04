import type { ColdStartBuildResult } from "@/lib/build/types";
import agentDeveloperPackage from "@/packages/projects/cn-agent-dev/0.1.0-candidate/cold-start-package.json";
import { commitProjectVersion } from "@/lib/versioning/commit";
import { createConversation, createProject, getProjectWorkspace } from "./repository";
import { ensureAppSchema, getD1 } from "@/db";

const PROJECT_ID = "ra-cn-agent-dev-coldstart-20260827";
const CONVERSATION_ID = "conversation:cn-agent-dev:review";
const SOURCE_RUN_ID = "bundled:cn-agent-dev:0.1.0-candidate";

/** Seed the reviewed Agent developer package as a normal, editable local project. */
export async function bootstrapAgentDeveloperProject() {
  await ensureAppSchema();
  const tombstone = await getD1().prepare("SELECT deleted_at FROM projects WHERE id=?").bind(PROJECT_ID).first<{ deleted_at: string | null }>();
  if (tombstone?.deleted_at) return null;
  const result = structuredClone(agentDeveloperPackage) as unknown as ColdStartBuildResult;
  let workspace = await getProjectWorkspace(PROJECT_ID);

  if (!workspace) {
    try {
      await createProject({
        id: PROJECT_ID,
        title: result.brief.roleTitle,
        description: result.brief.roleDescription,
        market: result.brief.market,
        conversationId: CONVERSATION_ID,
        conversationTitle: "岗位包审阅与迭代",
      });
    } catch (error) {
      if (!(error instanceof Error) || !/UNIQUE|constraint/i.test(error.message)) throw error;
    }
    workspace = await getProjectWorkspace(PROJECT_ID);
  }

  if (!workspace) throw new Error("BUNDLED_AGENT_DEVELOPER_PROJECT_CREATE_FAILED");

  let conversationId = workspace.conversations.find((item) => item.id === CONVERSATION_ID)?.id;
  if (!conversationId) {
    const created = await createConversation({
      id: CONVERSATION_ID,
      projectId: PROJECT_ID,
      title: "岗位包审阅与迭代",
      pinToActive: false,
    });
    conversationId = created?.id;
  }

  if (!workspace.version) {
    await commitProjectVersion({
      projectId: PROJECT_ID,
      result,
      sourceRunId: SOURCE_RUN_ID,
      sourceKind: "cold_start",
      sourceInput: { kind: "bundled_candidate_import", origin: "DeepSeek Harness" },
      conversationId: conversationId || null,
      message: "导入经协议校验的 Agent 开发工程师候选岗位包",
      authorKind: "system",
    });
    workspace = await getProjectWorkspace(PROJECT_ID);
  }

  return {
    projectId: PROJECT_ID,
    conversationId: conversationId || CONVERSATION_ID,
    snapshotId: workspace?.result?.snapshot.id || result.snapshot.id,
  };
}
