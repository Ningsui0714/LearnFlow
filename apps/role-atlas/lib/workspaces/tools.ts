import type { ColdStartBuildResult } from "@/lib/build/types";
import { alignWorkspaceToSnapshot } from "./align";
import { inspectWorkspaceInventory } from "./ingest";
import type { WorkspaceIngestionResult, WorkspacePackage } from "./types";

export function inspectWorkspacePackage(input: WorkspacePackage) {
  return {
    id: input.id,
    title: input.title,
    adapterId: input.adapterId,
    evidenceClass: input.evidenceClass,
    provenance: input.provenance,
    timeWindow: input.timeWindow,
    inventory: inspectWorkspaceInventory(input),
    caseIds: [...new Set(input.events.map((event) => event.caseId))],
  };
}

export function readWorkspaceResource(input: WorkspacePackage, resourceId: string) {
  const resource = input.resources.find((item) => item.id === resourceId);
  if (!resource) throw new Error(`WORKSPACE_RESOURCE_NOT_FOUND:${resourceId}`);
  const events = input.events.filter((event) => event.resourceIds.includes(resourceId));
  const objects = input.objects.filter((object) => object.resourceIds.includes(resourceId));
  return { resource, events, objects };
}

export function queryWorkspaceEvents(input: WorkspacePackage, query: {
  caseId?: string;
  actorRole?: string;
  type?: string;
  resourceId?: string;
  limit?: number;
}) {
  const limit = Math.max(1, Math.min(query.limit || 50, 200));
  return input.events.filter((event) => {
    if (query.caseId && event.caseId !== query.caseId) return false;
    if (query.actorRole && event.actorRole !== query.actorRole) return false;
    if (query.type && event.type !== query.type) return false;
    if (query.resourceId && !event.resourceIds.includes(query.resourceId)) return false;
    return true;
  }).sort((a, b) => (a.sequence ?? Number.MAX_SAFE_INTEGER) - (b.sequence ?? Number.MAX_SAFE_INTEGER)).slice(0, limit);
}

export function inspectWorkspaceObservation(input: WorkspaceIngestionResult, observationId: string) {
  const observation = input.observations.find((item) => item.id === observationId);
  if (!observation) throw new Error(`WORKSPACE_OBSERVATION_NOT_FOUND:${observationId}`);
  return {
    observation,
    resources: observation.resourceIds.map((id) => input.package.resources.find((resource) => resource.id === id)).filter(Boolean),
    events: observation.eventIds.map((id) => input.package.events.find((event) => event.id === id)).filter(Boolean),
  };
}

export function alignWorkspaceSnapshot(input: WorkspaceIngestionResult, base: ColdStartBuildResult) {
  return alignWorkspaceToSnapshot(input, base);
}
