import { z } from "zod/v4";

export const buildEventKindSchema = z.enum([
  "build.run.started",
  "build.boundary.stabilized",
  "build.plan.created",
  "build.research.plan.created",
  "build.search.started",
  "build.search.retrying",
  "build.search.completed",
  "build.search.failed",
  "build.source.fetched",
  "build.source.deduplicated",
  "build.research.completed",
  "build.source.registered",
  "build.source.segmented",
  "build.source.qualified",
  "build.work_item.queued",
  "build.work_item.started",
  "build.work_item.completed",
  "build.work_item.failed",
  "build.task_barrier.completed",
  "build.fast_snapshot.completed",
  "build.kernel.completed",
  "build.enrichment.queued",
  "build.enrichment.started",
  "build.enrichment.semantic.completed",
  "build.enrichment.process.completed",
  "build.targeted_research.started",
  "build.targeted_research.completed",
  "build.evidence.bound",
  "build.lane.started",
  "build.lane.completed",
  "build.reasoning.delta",
  "build.semantic.patch",
  "build.process.patch",
  "build.audit.issue.created",
  "build.inspection.started",
  "build.inspection.finding.created",
  "build.inspection.completed",
  "build.snapshot.section.drafted",
  "build.package.compile.started",
  "build.package.compile.completed",
  "build.package.validation.completed",
  "build.run.completed",
  "build.followup.deep_research.started",
  "build.followup.deep_research.completed",
  "build.followup.deep_research.skipped",
  "build.followup.risk_repair.started",
  "build.followup.risk_repair.completed",
  "build.followup.failed",
  "build.run.failed",
]);

export type BuildEventKind = z.infer<typeof buildEventKindSchema>;

export type BuildEvent = {
  version: "2.0";
  runId: string;
  projectId: string;
  seq: number;
  time: string;
  kind: BuildEventKind;
  profile: "structural" | "semantic" | "evidence" | "temporal" | "process" | "system";
  payload: Record<string, unknown>;
};
