export type Lifecycle = "accepted" | "candidate" | "deprecated";

export type EvidenceSummary = {
  binding_refs?: string[];
  source_refs?: string[];
  max_confidence?: number;
  has_segment_evidence?: boolean;
  temporal_status_counts?: Record<string, number>;
  capture_status_counts?: Record<string, number>;
  source_use_counts?: Record<string, number>;
  support_role_counts?: Record<string, number>;
  granularity_counts?: Record<string, number>;
  evidence_as_of?: string[];
};

export type RoleNode = {
  id: string;
  type: string;
  label: string;
  summary: string;
  ring: number;
  lifecycle: Lifecycle;
  assertion_refs?: string[];
  evidence_summary?: EvidenceSummary;
  data: Record<string, unknown>;
};

export type RoleEdge = {
  id: string;
  type: string;
  source: string;
  target: string;
  lifecycle: Lifecycle;
  attributes?: Record<string, unknown>;
  evidence_summary?: EvidenceSummary;
};

export type ObjectUnit = {
  id: string;
  target_id: string;
  object_type: string;
  lifecycle: Lifecycle;
  binding_refs: string[];
  field_states: Array<{
    field_path?: string;
    field_paths?: string[];
    state?: string;
    [key: string]: unknown;
  }>;
  related_ids: string[];
  payload: Record<string, unknown>;
  payload_sha256: string;
  snapshot_id: string;
};

export type RetrievalUnit = {
  id: string;
  target_id: string;
  unit_type: string;
  title: string;
  text: string;
  aliases: string[];
  lifecycle: Lifecycle;
  priority: number;
  facets: Record<string, unknown>;
  binding_refs: string[];
  source_refs: string[];
  evidence_profile: EvidenceSummary;
  snapshot_id: string;
};

export type SourceRecord = {
  id: string;
  kind: string;
  title: string;
  url?: string;
  as_of?: string;
  capture_status?: string;
  claim_use?: string;
  temporal_status?: string;
  segments?: Array<{
    id: string;
    locator?: string;
    kind?: string;
    text?: string;
  }>;
};

export type RolePackageData = {
  syncedAt: string;
  manifest: {
    package_protocol: string;
    protocol_version: string;
    package_id: string;
    package_version: string;
    status: string;
    snapshot_id: string;
    snapshot_as_of: string;
    hashes: Record<string, string>;
  };
  validation: {
    valid: boolean;
    publishable: boolean;
    errors: string[];
    warnings: string[];
    stats: Record<string, number | string>;
    validated_at: string;
  };
  graph: {
    metadata: Record<string, string>;
    nodes: RoleNode[];
    edges: RoleEdge[];
  };
  views: {
    default_view: string;
    views: Array<{
      id: string;
      label: string;
      purpose: string;
      included_types: string[];
      included_relations: string[];
    }>;
  };
  sources: { sources: SourceRecord[] };
  objectIndex: ObjectUnit[];
  retrieval: RetrievalUnit[];
  workProcessManifest: WorkProcessManifest;
  workProcessValidation: {
    valid: boolean;
    publishable: boolean;
    errors: string[];
    warnings: string[];
    stats: Record<string, number | string>;
    validated_at: string;
  };
  workProcess: WorkProcessPackageData;
};

export type KnowledgeState = "observed_pattern" | "documented_norm" | "inferred_pattern";

export type WorkProcessEvidenceBinding = {
  assertion_type: "observed" | "normative" | "synthesized" | "inferred";
  method: string;
  source_refs: string[];
  confidence: number;
  as_of: string;
  note?: string;
};

export type WorkProcessManifest = {
  package_protocol: "work-process-package";
  protocol_version: string;
  package_id: string;
  package_version: string;
  status: "candidate" | "published" | "deprecated";
  snapshot_id: string;
  snapshot_as_of: string;
  target_role_package: {
    package_id: string;
    package_version: string;
    snapshot_id: string;
  };
  entrypoints: Record<string, string>;
  hashes: Record<string, string>;
};

export type WorkProcessScenario = {
  id: string;
  title: string;
  summary: string;
  scenario_family: "delivery" | "operations" | "incident" | "governance" | "learning_improvement";
  goal: string;
  trigger: string;
  preconditions: string[];
  expected_outcomes: string[];
  root_event_refs: string[];
  event_refs: string[];
  task_refs: string[];
  capability_refs: string[];
  knowledge_skill_refs: string[];
  knowledge_state: KnowledgeState;
  lifecycle: Lifecycle;
  evidence_binding: WorkProcessEvidenceBinding;
};

export type WorkProcessNode = {
  id: string;
  scenario_id: string;
  kind: "event" | "work_object" | "artifact" | "actor" | "tool_system" | "quality_criterion" | "exception_risk";
  event_type?: "activity" | "decision" | "handoff" | "exception" | "outcome";
  label: string;
  summary: string;
  lane?: string;
  sequence_hint?: number;
  task_refs?: string[];
  capability_refs?: string[];
  knowledge_skill_refs?: string[];
  object_refs?: string[];
  artifact_refs?: string[];
  actor_refs?: string[];
  tool_refs?: string[];
  lifecycle: Lifecycle;
  evidence_binding: WorkProcessEvidenceBinding;
};

export type WorkProcessRelation = {
  id: string;
  type: string;
  source: string;
  target: string;
  qualifiers?: Record<string, unknown>;
  lifecycle: Lifecycle;
  evidence_binding: WorkProcessEvidenceBinding;
};

export type WorkProcessAlignment = {
  semantic_target_id: string;
  scenario_refs: string[];
  status: "covered" | "partial" | "gap" | "organization_specific";
  note: string;
};

export type WorkProcessPackageData = {
  metadata: {
    package_id: string;
    package_version: string;
    snapshot_id: string;
    snapshot_as_of: string;
    status: "candidate" | "published" | "deprecated";
    target_role_package: {
      package_id: string;
      package_version: string;
      snapshot_id: string;
    };
  };
  scenarios: WorkProcessScenario[];
  nodes: WorkProcessNode[];
  relations: WorkProcessRelation[];
  alignment: WorkProcessAlignment[];
};

export type NodeReference = {
  packageId: string;
  packageVersion: string;
  snapshotId: string;
  targetId: string;
  fieldPath?: string;
  selectionHash?: string;
};

export type ToolCitation = {
  handle?: string;
  artifactKind?: "role_semantic" | "work_process";
  packageId: string;
  packageVersion: string;
  snapshotId: string;
  targetId: string;
  label: string;
  fieldPath?: string;
  bindingId?: string;
  segmentId?: string;
  sourceIds: string[];
  sourceTitles: string[];
  confidence: number;
  lifecycle: Lifecycle;
  temporalStatus: string;
  knowledgeState?: KnowledgeState;
};

export type ToolCoverage = {
  complete: boolean;
  requested: number;
  returned: number;
  omitted: number;
  partial: boolean;
  nextCursor?: string;
  reason?: string;
};

export type ToolWarning = {
  code: string;
  message: string;
  targetId?: string;
};

export type ToolDiagnostics = {
  callFingerprint: string;
  deduplicated: boolean;
  durationMs: number;
  packageVersion: string;
  snapshotId: string;
  cache: "miss" | "run" | "package";
  companionVersions?: Record<string, string>;
};

export type ToolEnvelope<T = unknown> = {
  ok: boolean;
  tool: RoleToolName;
  data: T;
  context: string;
  citations: ToolCitation[];
  coverage: ToolCoverage;
  warnings: ToolWarning[];
  diagnostics: ToolDiagnostics;
  error?: {
    code: RoleToolErrorCode;
    message: string;
    retryable: boolean;
    whoFixes: "system" | "agent" | "user" | "developer";
    suggestedAction?: string;
  };
};

export const ROLE_TOOL_NAMES = [
  "get_role_overview",
  "get_role_package_status",
  "read_role_objects",
  "resolve_role_targets",
  "search_role_knowledge",
  "query_role_graph",
  "trace_role_paths",
  "read_task_bundle",
  "project_role_view",
  "compare_role_objects",
  "inspect_role_evidence",
  "read_work_scenarios",
  "trace_work_process",
  "inspect_role_process_alignment",
  "audit_role_package",
] as const;

export type RoleToolName = (typeof ROLE_TOOL_NAMES)[number];

export type RoleToolErrorCode =
  | "INVALID_REFERENCE"
  | "SNAPSHOT_MISMATCH"
  | "PACKAGE_NOT_PUBLISHABLE"
  | "HASH_MISMATCH"
  | "OBJECT_NOT_FOUND"
  | "AMBIGUOUS_ALIAS"
  | "RESULT_LIMIT_EXCEEDED"
  | "GRAPH_CYCLE_DETECTED"
  | "EVIDENCE_UNAVAILABLE"
  | "TEMPORAL_POLICY_BLOCKED"
  | "DUPLICATE_CALL"
  | "TOOL_TIMEOUT"
  | "CANCELLED"
  | "INTERNAL_ERROR";

export type RoleToolCall = {
  name: RoleToolName;
  args: Record<string, unknown>;
};
