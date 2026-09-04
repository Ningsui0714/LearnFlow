import { END, getWriter, START, StateGraph, StateSchema } from "@langchain/langgraph";
import { z } from "zod/v4";
import type { ModelInvoker } from "@/lib/agent/model";
import { stableHash } from "@/lib/build/compiler";
import { refreshRolePackageManifest } from "@/lib/packages/role-package-manifest";
import { createColdStartSkill } from "@/lib/build/graph";
import type { ColdStartBuildResult, SourceInput, WebResearchReport } from "@/lib/build/types";
import { researchRoleSources } from "@/lib/search/web-research";
import type { SearchProviderConfig } from "@/lib/search/providers";
import { auditRoleSnapshot, isAuditImproved } from "./audit";
import { applyGraphPatch, computeSemanticDiff, proposeSafePatch } from "./patch";
import { planRiskResearch, reconstructSourceInputs, requestForRiskResearch } from "./research";
import type { GraphPatch, RiskAuditReport, RiskEvent, RiskEventKind, RiskResearchPlan, RiskRunRequest, RiskRunResult } from "./types";

const RiskState = new StateSchema({
  request: z.custom<RiskRunRequest>(),
  baseVersionId: z.string(),
  base: z.custom<ColdStartBuildResult>(),
  candidate: z.custom<ColdStartBuildResult>(),
  iteration: z.number().int().default(1),
  auditBefore: z.custom<RiskAuditReport>().optional(),
  auditWorking: z.custom<RiskAuditReport>().optional(),
  auditAfter: z.custom<RiskAuditReport>().optional(),
  activePlan: z.custom<RiskResearchPlan>().optional(),
  researchPlans: z.custom<RiskResearchPlan[]>().default(() => []),
  researchReports: z.custom<WebResearchReport[]>().default(() => []),
  researchedSources: z.custom<SourceInput[]>().default(() => []),
  patches: z.custom<GraphPatch[]>().default(() => []),
  migrations: z.record(z.string(), z.string()).default(() => ({})),
  improved: z.boolean().default(false),
  result: z.custom<RiskRunResult>().optional(),
});

type RiskStateType = typeof RiskState.State;

function mergeSources(current: SourceInput[], incoming: SourceInput[], limit: number) {
  const seen = new Set<string>();
  const ordered = [
    ...incoming,
    ...current.filter((source) => source.kind === "workspace_observation" || source.kind === "private_document"),
    ...current.filter((source) => source.sourceTier === "authoritative" || source.sourceTier === "primary"),
    ...current,
  ];
  return ordered.filter((source) => {
    const key = source.locator ? `url:${source.locator}` : `content:${stableHash(`${source.title}:${source.content}`)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, Math.max(4, Math.min(limit, 20)));
}

function stampCandidate(candidate: ColdStartBuildResult, request: RiskRunRequest, improved: boolean) {
  const result = structuredClone(candidate);
  const revision = stableHash(`${request.runId}:${JSON.stringify(result.semantic.nodes)}:${JSON.stringify(result.process.scenarios)}`);
  const asOf = request.targetAsOf || result.snapshot.asOf;
  const roleSlug = stableHash(result.brief.roleTitle);
  const snapshotId = `snapshot:${roleSlug}@${asOf}:${revision}`;
  const currentVersion = candidate.packages.rolePackage.packageVersion.match(/^(\d+)\.(\d+)\.(\d+)/u)?.slice(1).map(Number) || [0, 1, 0];
  const [major, minor, patch] = currentVersion;
  const baseVersion = request.targetAsOf && request.targetAsOf !== candidate.snapshot.asOf
    ? `${major}.${minor + 1}.0`
    : `${major}.${minor}.${patch + 1}`;
  const packageVersion = `${baseVersion}-candidate.${revision}`;
  result.runId = request.runId;
  result.snapshot.id = snapshotId;
  result.snapshot.asOf = asOf;
  result.snapshot.status = "candidate";
  if (!improved) result.validation.publishable = false;
  return refreshRolePackageManifest(result, { packageVersion, status: "candidate" });
}

export function createRiskResearchRepairSkill(input: {
  model: ModelInvoker;
  searchConfig?: SearchProviderConfig;
  onCheckpoint?: (phase: string, state: Record<string, unknown>) => Promise<void>;
}) {
  let seq = 0;
  const emit = (state: Pick<RiskStateType, "request">, kind: RiskEventKind, phase: RiskEvent["phase"], payload: Record<string, unknown>) => {
    const event: RiskEvent = {
      version: "1.0",
      runId: state.request.runId,
      snapshotId: state.request.snapshotRef.snapshotId,
      projectId: state.request.projectId,
      seq: seq += 1,
      time: new Date().toISOString(),
      kind,
      phase,
      payload,
    };
    getWriter()?.(event);
  };
  const checkpoint = async (phase: string, state: RiskStateType, update: Record<string, unknown>) => {
    await input.onCheckpoint?.(phase, {
      iteration: state.iteration,
      phase,
      auditBefore: state.auditBefore,
      auditAfter: state.auditAfter,
      researchPlans: state.researchPlans,
      researchReports: state.researchReports,
      patches: state.patches,
      ...update,
    });
  };

  const auditBaseline = async (state: RiskStateType) => {
    emit(state, "risk.run.started", "system", { mode: state.request.mode, maxIterations: state.request.maxIterations });
    emit(state, "risk.baseline.pinned", "baseline", { versionId: state.baseVersionId, snapshotId: state.base.snapshot.id, asOf: state.base.snapshot.asOf });
    emit(state, "risk.audit.started", "audit", { profiles: state.request.scope.profiles, targetIds: state.request.scope.targetIds });
    const audit = auditRoleSnapshot(state.base, {
      profiles: state.request.scope.profiles,
      targetIds: state.request.scope.targetIds,
    });
    for (const issue of audit.issues) emit(state, "risk.audit.issue.found", "audit", { issue });
    emit(state, "risk.audit.clustered", "audit", { clusters: audit.clusters, metrics: audit.metrics });
    const update = { auditBefore: audit, auditWorking: audit, auditAfter: audit, candidate: state.base };
    await checkpoint("audit", state, update);
    return update;
  };

  const planResearch = async (state: RiskStateType) => {
    const enabled = state.request.webResearch && Boolean(input.searchConfig)
      && !["scan", "verify"].includes(state.request.mode);
    const plan = enabled
      ? planRiskResearch({ result: state.candidate, audit: state.auditWorking!, request: state.request, iteration: state.iteration })
      : { id: `risk-plan:${state.request.runId}:${state.iteration}`, iteration: state.iteration, clusterIds: [], queries: [], rationale: [], stopConditions: [] };
    emit(state, "risk.research.plan.created", "research", {
      planId: plan.id,
      iteration: state.iteration,
      queryCount: plan.queries.length,
      clusterIds: plan.clusterIds,
      rationale: plan.rationale,
      skippedReason: enabled ? undefined : input.searchConfig ? "当前模式只审计" : "未配置搜索供应商",
    });
    const update = { activePlan: plan, researchPlans: [...state.researchPlans, plan] };
    await checkpoint("research-plan", state, update);
    return update;
  };

  const research = async (state: RiskStateType, config: { signal?: AbortSignal }) => {
    const plan = state.activePlan!;
    if (!plan.queries.length || !input.searchConfig) return { researchedSources: [] };
    const researchRequest = requestForRiskResearch({ result: state.candidate, request: state.request, sources: [], iteration: state.iteration });
    const researched = await researchRoleSources({
      request: researchRequest,
      config: input.searchConfig,
      queries: plan.queries,
      planStrategy: "deterministic",
      sourceLimit: state.request.sourceLimit,
      signal: config.signal,
      onProgress: (progress) => {
        if (progress.kind === "search-started") emit(state, "risk.search.started", "research", progress.payload);
        if (progress.kind === "search-completed") emit(state, "risk.search.completed", "research", progress.payload);
        if (progress.kind === "search-failed") emit(state, "risk.search.failed", "research", progress.payload);
      },
    });
    emit(state, "risk.research.completed", "research", {
      iteration: state.iteration,
      selectedSourceCount: researched.sources.length,
      candidateCount: researched.report.candidateCount,
      failures: researched.report.failures,
      categoryCoverage: researched.report.categoryCoverage,
    });
    const update = {
      researchedSources: researched.sources,
      researchReports: [...state.researchReports, researched.report],
    };
    await checkpoint("research", state, update);
    return update;
  };

  const rebuild = async (state: RiskStateType, config: { signal?: AbortSignal }) => {
    if (!state.researchedSources.length) return { candidate: state.candidate };
    const currentSources = reconstructSourceInputs(state.candidate);
    const sources = mergeSources(currentSources, state.researchedSources, 20);
    const request = requestForRiskResearch({ result: state.candidate, request: state.request, sources, iteration: state.iteration });
    const skill = createColdStartSkill(input.model, {
      existingResearchReport: state.researchReports.at(-1),
      emitEvents: false,
    });
    const built = await skill.invoke(
      { request, laneFailures: [] },
      { configurable: { thread_id: `${state.request.snapshotRef.snapshotId}:${state.request.runId}:risk:${state.iteration}` }, signal: config.signal },
    );
    const candidate = built.result || state.candidate;
    emit(state, "risk.candidate.rebuilt", "repair", {
      iteration: state.iteration,
      nodes: candidate.semantic.nodes.length,
      edges: candidate.semantic.edges.length,
      scenarios: candidate.process.scenarios.length,
      sources: candidate.sources.assets.length,
    });
    await checkpoint("rebuild", state, { candidate });
    return { candidate };
  };

  const repair = async (state: RiskStateType) => {
    const candidateAudit = auditRoleSnapshot(state.candidate, {
      profiles: state.request.scope.profiles,
      targetIds: state.request.scope.targetIds,
    });
    if (["scan", "verify"].includes(state.request.mode)) {
      const proposed: GraphPatch = {
        id: `risk-patch:${stableHash(`${state.request.runId}:${state.iteration}:readonly`)}`,
        baseSnapshotId: state.candidate.snapshot.id,
        status: "proposed",
        iteration: state.iteration,
        operations: [],
        targetIds: [],
        issueIds: [],
        summary: "只读模式不生成或应用修复操作。",
        createdAt: new Date().toISOString(),
      };
      const patches = [...state.patches, proposed];
      emit(state, "risk.patch.proposed", "repair", { patch: proposed, readonly: true });
      await checkpoint("repair", state, { auditWorking: candidateAudit, patches });
      return { auditWorking: candidateAudit, patches };
    }
    const proposed = proposeSafePatch({ result: state.candidate, audit: candidateAudit, iteration: state.iteration });
    emit(state, "risk.patch.proposed", "repair", { patch: proposed });
    if (!proposed.operations.length) {
      const patches = [...state.patches, proposed];
      await checkpoint("repair", state, { auditWorking: candidateAudit, patches });
      return { auditWorking: candidateAudit, patches };
    }
    const applied = applyGraphPatch(state.candidate, proposed);
    emit(state, "risk.patch.applied", "repair", { patch: applied.patch, referenceMigration: applied.referenceMigration });
    const migrations = { ...state.migrations, ...applied.referenceMigration };
    const patches = [...state.patches, applied.patch];
    await checkpoint("repair", state, { candidate: applied.result, patches, migrations });
    return { candidate: applied.result, patches, migrations };
  };

  const validate = async (state: RiskStateType) => {
    const auditAfter = auditRoleSnapshot(state.candidate, {
      profiles: state.request.scope.profiles,
      targetIds: state.request.scope.targetIds,
    });
    const improved = isAuditImproved(state.auditBefore!, auditAfter);
    emit(state, "risk.validation.completed", "validate", {
      iteration: state.iteration,
      improved,
      before: state.auditBefore!.metrics,
      after: auditAfter.metrics,
      introduced: auditAfter.issues.filter((issue) => !state.auditBefore!.issues.some((before) => before.fingerprint === issue.fingerprint)).map((issue) => issue.id),
    });
    emit(state, "risk.iteration.completed", "validate", { iteration: state.iteration, improved, remainingClusters: auditAfter.clusters.length });
    const update = { auditAfter, auditWorking: auditAfter, improved };
    await checkpoint("validate", state, update);
    return update;
  };

  const routeAfterValidation = (state: RiskStateType) => {
    const hasResearchable = state.auditAfter?.clusters.some((cluster) => cluster.repairability.includes("research"));
    if (!state.improved && hasResearchable && state.request.webResearch && input.searchConfig && state.iteration < state.request.maxIterations) return "retry";
    return "finish";
  };

  const nextIteration = async (state: RiskStateType) => {
    const iteration = state.iteration + 1;
    await checkpoint("iteration", state, { iteration, researchedSources: [] });
    return { iteration, researchedSources: [] };
  };

  const finalize = async (state: RiskStateType) => {
    const candidate = stampCandidate(state.candidate, state.request, state.improved);
    const diff = computeSemanticDiff({
      base: state.base,
      candidate,
      patches: state.patches,
      auditBefore: state.auditBefore!,
      auditAfter: state.auditAfter!,
      migrations: state.migrations,
    });
    const before = state.auditBefore!.metrics;
    const after = state.auditAfter!.metrics;
    const improvementSummary = [
      `健康分 ${before.score.toFixed(1)} → ${after.score.toFixed(1)}`,
      `错误 ${before.errors} → ${after.errors}，风险权重 ${before.issueWeight} → ${after.issueWeight}`,
      `直接证据覆盖 ${(before.directEvidenceCoverage * 100).toFixed(0)}% → ${(after.directEvidenceCoverage * 100).toFixed(0)}%`,
      `任务—事理覆盖 ${(before.processCoverage * 100).toFixed(0)}% → ${(after.processCoverage * 100).toFixed(0)}%`,
    ];
    const result: RiskRunResult = {
      runId: state.request.runId,
      snapshotRef: state.request.snapshotRef,
      projectId: state.request.projectId,
      baseVersionId: state.baseVersionId,
      baseSnapshotId: state.base.snapshot.id,
      mode: state.request.mode,
      status: state.improved ? "completed" : "no_improvement",
      auditBefore: state.auditBefore!,
      auditAfter: state.auditAfter!,
      researchPlans: state.researchPlans,
      researchReports: state.researchReports,
      patches: state.patches,
      diff,
      candidate,
      improved: state.improved,
      improvementSummary,
      knownGaps: state.auditAfter!.issues.filter((issue) => issue.repairability !== "automatic"),
    };
    emit(state, "risk.run.completed", "system", { result, improved: state.improved, diff });
    await checkpoint("completed", state, { result });
    return { result, candidate };
  };

  return new StateGraph(RiskState)
    .addNode("audit_baseline", auditBaseline)
    .addNode("plan_research", planResearch)
    .addNode("targeted_research", research, { retryPolicy: { maxAttempts: 2, initialInterval: 1 } })
    .addNode("rebuild_candidate", rebuild)
    .addNode("apply_safe_patch", repair)
    .addNode("validate_candidate", validate)
    .addNode("next_iteration", nextIteration)
    .addNode("finalize", finalize)
    .addEdge(START, "audit_baseline")
    .addEdge("audit_baseline", "plan_research")
    .addEdge("plan_research", "targeted_research")
    .addEdge("targeted_research", "rebuild_candidate")
    .addEdge("rebuild_candidate", "apply_safe_patch")
    .addEdge("apply_safe_patch", "validate_candidate")
    .addConditionalEdges("validate_candidate", routeAfterValidation, { retry: "next_iteration", finish: "finalize" })
    .addEdge("next_iteration", "plan_research")
    .addEdge("finalize", END)
    .compile({ checkpointer: false });
}
