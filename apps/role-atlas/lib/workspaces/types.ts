import { z } from "zod/v4";
import type { ColdStartBuildResult, SourceInput } from "@/lib/build/types";

export const workspaceAdapterIdSchema = z.enum([
  "generic_package",
  "github_trace",
  "devgpt",
  "swebench",
  "bug_benchmark",
  "event_log",
  "telemetry_case",
  "soc_case",
]);

export const workspaceEvidenceClassSchema = z.enum([
  "real_work_activity",
  "curated_real_case",
  "production_trace",
  "controlled_experiment",
  "teaching_simulation",
  "synthetic_fixture",
]);

export const workspaceResourceKindSchema = z.enum([
  "task",
  "communication",
  "document",
  "code_snapshot",
  "patch",
  "review",
  "test",
  "ci_run",
  "release",
  "event_log",
  "metric",
  "log",
  "trace",
  "incident",
  "outcome",
]);

export const workspaceObjectTypeSchema = z.enum([
  "work_item",
  "artifact",
  "repository",
  "service",
  "system",
  "incident",
  "test_case",
  "release",
  "dataset_case",
]);

export const workspaceResourceSchema = z.object({
  id: z.string().min(1).max(180),
  kind: workspaceResourceKindSchema,
  title: z.string().min(1).max(240),
  summary: z.string().max(8_000).default(""),
  content: z.string().max(120_000).optional(),
  locator: z.string().max(700).optional(),
  mediaType: z.string().max(120).optional(),
  occurredAt: z.string().max(80).optional(),
  actorRole: z.string().max(120).optional(),
  caseId: z.string().max(180).optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const workspaceObjectSchema = z.object({
  id: z.string().min(1).max(180),
  type: workspaceObjectTypeSchema,
  label: z.string().min(1).max(240),
  summary: z.string().max(4_000).default(""),
  resourceIds: z.array(z.string().max(180)).max(80).default([]),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const workspaceEventSchema = z.object({
  id: z.string().min(1).max(180),
  caseId: z.string().min(1).max(180),
  type: z.string().min(1).max(120),
  label: z.string().min(1).max(240),
  summary: z.string().max(4_000).default(""),
  occurredAt: z.string().max(80).optional(),
  sequence: z.number().int().min(0).optional(),
  actorRole: z.string().max(120).optional(),
  objectIds: z.array(z.string().max(180)).max(80).default([]),
  resourceIds: z.array(z.string().max(180)).max(80).default([]),
  status: z.string().max(80).optional(),
  outcome: z.string().max(2_000).optional(),
});

export const workspaceLinkSchema = z.object({
  id: z.string().min(1).max(180),
  type: z.string().min(1).max(120),
  source: z.string().min(1).max(180),
  target: z.string().min(1).max(180),
  resourceIds: z.array(z.string().max(180)).max(80).default([]),
});

export const workspacePackageSchema = z.object({
  protocolVersion: z.literal("1.0"),
  id: z.string().min(1).max(180),
  title: z.string().min(1).max(240),
  adapterId: workspaceAdapterIdSchema,
  roleHint: z.string().max(160).optional(),
  description: z.string().max(8_000).default(""),
  evidenceClass: workspaceEvidenceClassSchema,
  visibility: z.enum(["project_private", "publishable_metadata"]),
  provenance: z.object({
    locator: z.string().url().max(700).optional(),
    publisher: z.string().max(240).optional(),
    license: z.string().max(120).optional(),
    capturedAt: z.string().max(80),
    sourceUpdatedAt: z.string().max(80).optional(),
    notes: z.array(z.string().max(500)).max(20).default([]),
  }),
  timeWindow: z.object({
    start: z.string().max(80).optional(),
    end: z.string().max(80).optional(),
    asOf: z.string().max(80).optional(),
  }).default({}),
  resources: z.array(workspaceResourceSchema).max(500),
  objects: z.array(workspaceObjectSchema).max(500).default([]),
  events: z.array(workspaceEventSchema).max(5_000).default([]),
  links: z.array(workspaceLinkSchema).max(5_000).default([]),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const workspaceConnectionSchema = z.object({
  adapterId: workspaceAdapterIdSchema,
  payload: z.unknown(),
  packageId: z.string().max(180).optional(),
  title: z.string().max(240).optional(),
  roleHint: z.string().max(160).optional(),
  visibility: z.enum(["project_private", "publishable_metadata"]).default("project_private"),
  evidenceClass: workspaceEvidenceClassSchema.optional(),
  provenance: z.object({
    locator: z.string().url().max(700).optional(),
    publisher: z.string().max(240).optional(),
    license: z.string().max(120).optional(),
    capturedAt: z.string().max(80).optional(),
  }).default({}),
});

export const workspaceIngestionRequestSchema = z.object({
  runId: z.string().min(4).max(100),
  projectId: z.string().min(4).max(100).optional(),
  connection: workspaceConnectionSchema,
  maxObservations: z.number().int().min(2).max(20).default(16),
  redactPersonalData: z.boolean().default(true),
});

export type WorkspaceAdapterId = z.infer<typeof workspaceAdapterIdSchema>;
export type WorkspaceEvidenceClass = z.infer<typeof workspaceEvidenceClassSchema>;
export type WorkspaceResourceKind = z.infer<typeof workspaceResourceKindSchema>;
export type WorkspaceResource = z.infer<typeof workspaceResourceSchema>;
export type WorkspaceObject = z.infer<typeof workspaceObjectSchema>;
export type WorkspaceEvent = z.infer<typeof workspaceEventSchema>;
export type WorkspaceLink = z.infer<typeof workspaceLinkSchema>;
export type WorkspacePackage = z.infer<typeof workspacePackageSchema>;
export type WorkspaceConnection = z.infer<typeof workspaceConnectionSchema>;
export type WorkspaceIngestionRequest = z.infer<typeof workspaceIngestionRequestSchema>;

export type WorkspaceSafetyFinding = {
  id: string;
  severity: "info" | "warning" | "error";
  code: "SECRET_LIKE_CONTENT" | "LOCAL_PATH" | "PERSONAL_DATA_REDACTED" | "EMPTY_RESOURCE" | "DUPLICATE_RESOURCE";
  title: string;
  resourceIds: string[];
  action: "redacted" | "quarantined" | "deduplicated" | "kept";
};

export type WorkspaceInventory = {
  resourceCount: number;
  acceptedResourceCount: number;
  quarantinedResourceCount: number;
  eventCount: number;
  objectCount: number;
  caseCount: number;
  kinds: Partial<Record<WorkspaceResourceKind, number>>;
};

export type WorkspaceObservation = {
  id: string;
  episodeId?: string;
  title: string;
  summary: string;
  resourceIds: string[];
  eventIds: string[];
  source: SourceInput;
};

export type WorkspaceTaskAlignment = {
  observationId: string;
  episodeId?: string;
  taskId?: string;
  taskLabel?: string;
  score: number;
  status: "aligned" | "candidate_task";
  evidenceResourceIds: string[];
};

export type WorkspaceAlignmentReport = {
  snapshotId: string;
  alignedCount: number;
  candidateTaskCount: number;
  uncoveredTaskIds: string[];
  alignments: WorkspaceTaskAlignment[];
};

export type WorkspaceIngestionResult = {
  runId: string;
  package: WorkspacePackage;
  inventory: WorkspaceInventory;
  safetyFindings: WorkspaceSafetyFinding[];
  observations: WorkspaceObservation[];
  quarantinedResourceIds: string[];
  warnings: string[];
};

export type WorkspaceUpgradePreparation = {
  ingestion: WorkspaceIngestionResult;
  alignment: WorkspaceAlignmentReport;
  supplementalSources: SourceInput[];
  base: ColdStartBuildResult;
};
