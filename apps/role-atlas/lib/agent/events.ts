import type { ToolCitation, ToolEnvelope } from "@/lib/role-package/types";

export type AgentEventKind =
  | "run.started"
  | "snapshot.pinned"
  | "plan.created"
  | "tool.started"
  | "tool.finished"
  | "tool.deduplicated"
  | "coverage.checked"
  | "context.assembled"
  | "generation.started"
  | "citation.registry"
  | "reasoning.delta"
  | "reasoning.completed"
  | "answer.delta"
  | "answer.completed"
  | "run.failed";

export type AgentEvent = {
  version: "1.1";
  runId: string;
  sessionId: string;
  seq: number;
  time: string;
  kind: AgentEventKind;
  payload: Record<string, unknown>;
};

export type AgentMessage = {
  role: "user" | "assistant";
  text: string;
};

export type AgentRequest = {
  runId: string;
  sessionId: string;
  message: string;
  references: Array<{
    packageId: string;
    packageVersion: string;
    snapshotId: string;
    targetId: string;
    fieldPath?: string;
    selectionHash?: string;
  }>;
  history: AgentMessage[];
};

export type AgentContextBundle = {
  toolResults: ToolEnvelope[];
  citations: ToolCitation[];
  context: string;
  coverageComplete: boolean;
};
