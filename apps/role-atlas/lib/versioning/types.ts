import type { ColdStartBuildResult } from "@/lib/build/types";

export type ProjectVersionSourceKind = "cold_start" | "iteration" | "workspace" | "restore" | "import" | "legacy";

export type ProjectVersionRecord = {
  id: string;
  projectId: string;
  parentVersionId: string | null;
  sourceRunId: string | null;
  sourceKind: ProjectVersionSourceKind;
  version: string;
  snapshotId: string;
  status: "candidate" | "ready" | "published";
  rootHash: string;
  message: string;
  authorKind: "user" | "agent" | "system";
  createdAt: string;
  result: ColdStartBuildResult;
};

export type DiffKind = "added" | "removed" | "modified" | "renamed";

export type FieldChange = {
  path: string;
  before?: unknown;
  after?: unknown;
};

export type ObjectChange = {
  domain: "semantic_node" | "semantic_edge" | "claim" | "process_scenario" | "process_node" | "process_edge" | "process_bridge" | "source" | "evidence" | "snapshot_section";
  kind: DiffKind;
  id: string;
  label?: string;
  changes: FieldChange[];
};

export type ReferenceMigration = {
  fromSnapshotId: string;
  toSnapshotId: string;
  fromTargetId: string;
  toTargetIds: string[];
  kind: "rename" | "merge" | "split" | "replacement" | "removed";
  confidence: number;
  reason: string;
};

export type SemanticDiff = {
  id: string;
  algorithmVersion: "1.0.0";
  projectId?: string;
  from: { versionId: string; snapshotId: string; rootHash: string };
  to: { versionId: string; snapshotId: string; rootHash: string };
  changes: ObjectChange[];
  migrations: ReferenceMigration[];
  impacts: string[];
  summary: {
    added: number;
    removed: number;
    modified: number;
    renamed: number;
    total: number;
  };
  recommendedBump: "none" | "patch" | "minor" | "major";
  createdAt: string;
};
