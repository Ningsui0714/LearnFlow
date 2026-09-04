import type { WorkspaceAlignmentReport, WorkspaceIngestionResult } from "./types";

export type WorkspaceEventPhase = "register" | "scan" | "extract" | "align" | "iterate" | "system";

export type WorkspaceRunEventKind =
  | "workspace.run.started"
  | "workspace.package.normalized"
  | "workspace.scan.started"
  | "workspace.resource.accepted"
  | "workspace.resource.quarantined"
  | "workspace.scan.completed"
  | "workspace.episode.extracted"
  | "workspace.alignment.started"
  | "workspace.alignment.completed"
  | "workspace.iteration.prepared"
  | "workspace.run.completed"
  | "workspace.run.failed";

export type WorkspaceRunEvent = {
  version: "1.0";
  runId: string;
  projectId?: string;
  seq: number;
  time: string;
  kind: WorkspaceRunEventKind;
  phase: WorkspaceEventPhase;
  payload: Record<string, unknown> & {
    result?: WorkspaceIngestionResult;
    alignment?: WorkspaceAlignmentReport;
  };
};
