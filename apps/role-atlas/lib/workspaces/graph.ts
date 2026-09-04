import { END, getWriter, ReducedValue, START, StateGraph, StateSchema } from "@langchain/langgraph";
import { z } from "zod/v4";
import type { ColdStartBuildResult } from "@/lib/build/types";
import { alignWorkspaceToSnapshot } from "./align";
import { normalizeWorkspaceConnection } from "./adapters";
import type { WorkspaceRunEvent, WorkspaceRunEventKind } from "./events";
import {
  extractArtifactObservations,
  extractEpisodeObservations,
  inspectWorkspaceInventory,
  mergeWorkspaceObservations,
  sanitizeWorkspacePackage,
} from "./ingest";
import type {
  WorkspaceAlignmentReport,
  WorkspaceIngestionRequest,
  WorkspaceIngestionResult,
  WorkspaceInventory,
  WorkspaceObservation,
  WorkspacePackage,
  WorkspaceSafetyFinding,
} from "./types";

const WorkspaceState = new StateSchema({
  request: z.custom<WorkspaceIngestionRequest>(),
  base: z.custom<ColdStartBuildResult>().optional(),
  normalized: z.custom<WorkspacePackage>().optional(),
  sanitized: z.custom<WorkspacePackage>().optional(),
  safetyFindings: z.custom<WorkspaceSafetyFinding[]>().default(() => []),
  quarantinedResourceIds: z.array(z.string()).default(() => []),
  inventory: z.custom<WorkspaceInventory>().optional(),
  observationLanes: new ReducedValue(z.custom<WorkspaceObservation[]>().default(() => []), {
    reducer: (current, update) => current.concat(update),
  }),
  observations: z.custom<WorkspaceObservation[]>().default(() => []),
  alignment: z.custom<WorkspaceAlignmentReport>().optional(),
  result: z.custom<WorkspaceIngestionResult>().optional(),
});

type WorkspaceStateType = typeof WorkspaceState.State;

export function createWorkspaceIngestionSkill(options?: {
  onCheckpoint?: (phase: string, state: Record<string, unknown>) => Promise<void>;
}) {
  let seq = 0;
  const emit = (state: Pick<WorkspaceStateType, "request">, kind: WorkspaceRunEventKind, phase: WorkspaceRunEvent["phase"], payload: Record<string, unknown>) => {
    const event: WorkspaceRunEvent = {
      version: "1.0",
      runId: state.request.runId,
      projectId: state.request.projectId,
      seq: seq += 1,
      time: new Date().toISOString(),
      kind,
      phase,
      payload,
    };
    getWriter()?.(event);
  };
  const checkpoint = (phase: string, state: WorkspaceStateType, update: Record<string, unknown>) => options?.onCheckpoint?.(phase, {
    phase,
    packageId: state.normalized?.id,
    inventory: state.inventory,
    safetyFindings: state.safetyFindings,
    observationCount: state.observations.length,
    alignment: state.alignment,
    ...update,
  });

  const normalize = async (state: WorkspaceStateType) => {
    emit(state, "workspace.run.started", "system", {
      adapterId: state.request.connection.adapterId,
      roleHint: state.request.connection.roleHint,
      evidenceClass: state.request.connection.evidenceClass,
    });
    const normalized = normalizeWorkspaceConnection(state.request.connection);
    emit(state, "workspace.package.normalized", "register", {
      packageId: normalized.id,
      title: normalized.title,
      adapterId: normalized.adapterId,
      evidenceClass: normalized.evidenceClass,
      resources: normalized.resources.length,
      events: normalized.events.length,
      cases: new Set(normalized.events.map((event) => event.caseId)).size,
    });
    await checkpoint("register", state, { normalized });
    return { normalized };
  };

  const scan = async (state: WorkspaceStateType) => {
    emit(state, "workspace.scan.started", "scan", {
      packageId: state.normalized!.id,
      resourceCount: state.normalized!.resources.length,
      policy: "redact_secrets_and_personal_data_keep_usable_evidence",
    });
    const sanitized = sanitizeWorkspacePackage(state.normalized!, state.request.redactPersonalData);
    const inventory = inspectWorkspaceInventory(sanitized.package, sanitized.quarantinedResourceIds.length);
    const quarantined = new Set(sanitized.quarantinedResourceIds);
    for (const resource of state.normalized!.resources) {
      emit(state, quarantined.has(resource.id) ? "workspace.resource.quarantined" : "workspace.resource.accepted", "scan", {
        resourceId: resource.id,
        kind: resource.kind,
        title: resource.title,
        findings: sanitized.safetyFindings.filter((item) => item.resourceIds.includes(resource.id)),
      });
    }
    emit(state, "workspace.scan.completed", "scan", {
      inventory,
      findingCount: sanitized.safetyFindings.length,
      quarantinedResourceIds: sanitized.quarantinedResourceIds,
    });
    const update = {
      sanitized: sanitized.package,
      safetyFindings: sanitized.safetyFindings,
      quarantinedResourceIds: sanitized.quarantinedResourceIds,
      inventory,
    };
    await checkpoint("scan", state, update);
    return update;
  };

  const extractEpisodes = async (state: WorkspaceStateType) => {
    const observations = extractEpisodeObservations(state.sanitized!);
    for (const observation of observations) emit(state, "workspace.episode.extracted", "extract", {
      lane: "event_episode",
      observationId: observation.id,
      episodeId: observation.episodeId,
      title: observation.title,
      eventCount: observation.eventIds.length,
      resourceCount: observation.resourceIds.length,
    });
    return { observationLanes: observations };
  };

  const extractArtifacts = async (state: WorkspaceStateType) => {
    const observations = extractArtifactObservations(state.sanitized!);
    for (const observation of observations) emit(state, "workspace.episode.extracted", "extract", {
      lane: "standalone_artifact",
      observationId: observation.id,
      episodeId: observation.episodeId,
      title: observation.title,
      eventCount: 0,
      resourceCount: observation.resourceIds.length,
    });
    return { observationLanes: observations };
  };

  const merge = async (state: WorkspaceStateType) => {
    const observations = mergeWorkspaceObservations(state.observationLanes, state.request.maxObservations);
    await checkpoint("extract", state, { observations });
    return { observations };
  };

  const align = async (state: WorkspaceStateType) => {
    if (!state.base) return {};
    emit(state, "workspace.alignment.started", "align", {
      snapshotId: state.base.snapshot.id,
      observationCount: state.observations.length,
      taskCount: state.base.semantic.nodes.filter((node) => node.type === "task").length,
    });
    const ingestion: WorkspaceIngestionResult = {
      runId: state.request.runId,
      package: state.sanitized!,
      inventory: state.inventory!,
      safetyFindings: state.safetyFindings,
      observations: state.observations,
      quarantinedResourceIds: state.quarantinedResourceIds,
      warnings: [],
    };
    const alignment = alignWorkspaceToSnapshot(ingestion, state.base);
    emit(state, "workspace.alignment.completed", "align", {
      alignment,
      alignedCount: alignment.alignedCount,
      candidateTaskCount: alignment.candidateTaskCount,
      uncoveredTaskCount: alignment.uncoveredTaskIds.length,
    });
    await checkpoint("align", state, { alignment });
    return { alignment };
  };

  const complete = async (state: WorkspaceStateType) => {
    const warnings: string[] = [];
    if (!state.sanitized!.events.length) warnings.push("没有可排序事件；本轮只能从独立资源提取工作产物观察。" );
    if (!state.observations.length) warnings.push("没有形成可进入岗位快照的工作观察，请补充任务、事件或工作产物。" );
    if (state.observations.length === state.request.maxObservations) warnings.push(`观察达到本轮上限 ${state.request.maxObservations}，其余材料仍保留在工作区包中。`);
    const result: WorkspaceIngestionResult = {
      runId: state.request.runId,
      package: state.sanitized!,
      inventory: state.inventory!,
      safetyFindings: state.safetyFindings,
      observations: state.observations,
      quarantinedResourceIds: state.quarantinedResourceIds,
      warnings,
    };
    emit(state, "workspace.iteration.prepared", "iterate", {
      supplementalSourceCount: result.observations.length,
      alignedCount: state.alignment?.alignedCount || 0,
      candidateTaskCount: state.alignment?.candidateTaskCount || 0,
      intent: "instantiate",
    });
    emit(state, "workspace.run.completed", "system", { result, alignment: state.alignment });
    await checkpoint("complete", state, { result, alignment: state.alignment });
    return { result };
  };

  return new StateGraph(WorkspaceState)
    .addNode("normalize_package", normalize)
    .addNode("scan_resources", scan)
    .addNode("extract_event_episodes", extractEpisodes)
    .addNode("extract_standalone_artifacts", extractArtifacts)
    .addNode("merge_observations", merge)
    .addNode("align_snapshot", align)
    .addNode("prepare_iteration", complete)
    .addEdge(START, "normalize_package")
    .addEdge("normalize_package", "scan_resources")
    .addEdge("scan_resources", "extract_event_episodes")
    .addEdge("scan_resources", "extract_standalone_artifacts")
    .addEdge("extract_event_episodes", "merge_observations")
    .addEdge("extract_standalone_artifacts", "merge_observations")
    .addEdge("merge_observations", "align_snapshot")
    .addEdge("align_snapshot", "prepare_iteration")
    .addEdge("prepare_iteration", END)
    .compile({ checkpointer: false });
}
