import { stableHash } from "@/lib/build/compiler";
import type {
  AuditIssue,
  ColdStartBuildResult,
  EvidenceBinding,
  ProcessEdge,
  ProcessNode,
  ResearchTopic,
  SemanticBridge,
  SnapshotSection,
  SourceAsset,
  SourceSegment,
} from "@/lib/build/types";
import { rolePackageRuntime } from "@/lib/role-package/runtime";
import { createRolePackageManifest } from "@/lib/packages/role-package-manifest";
import type { EvidenceSummary, Lifecycle, WorkProcessEvidenceBinding } from "@/lib/role-package/types";

const COMPOSITE_VERSION = "1.2.0";

function lifecycle(value: Lifecycle) {
  return value === "accepted" ? "stable" as const : "candidate" as const;
}

function domainOf(locator?: string) {
  if (!locator) return undefined;
  try { return new URL(locator).hostname; }
  catch { return undefined; }
}

function sourceTier(kind: string, claimUse?: string): SourceAsset["sourceTier"] {
  if (kind === "official_doc") return "authoritative";
  if (claimUse === "primary") return "primary";
  if (kind === "job_posting") return "secondary";
  return "contextual";
}

function sourceKind(kind: string): SourceAsset["kind"] {
  return kind === "workspace_observation" ? "workspace_observation"
    : kind === "private_document" ? "private_document"
      : "public_document";
}

function confidenceOf(summary?: EvidenceSummary) {
  return Math.max(0, Math.min(1, summary?.max_confidence ?? 0.65));
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function section(
  id: string,
  title: string,
  summary: string,
  itemIds: string[],
  bindingsByTarget: Map<string, string[]>,
): SnapshotSection {
  return {
    id,
    title,
    status: "stable",
    summary,
    itemIds,
    evidenceBindingIds: unique(itemIds.flatMap((itemId) => bindingsByTarget.get(itemId) || [])),
  };
}

/**
 * Projects the checked-in role package into the same build-result contract
 * consumed by research/repair skills. No facts are regenerated here.
 */
export function bundledRoleSnapshot(): ColdStartBuildResult {
  const data = rolePackageRuntime.package;
  const segments: SourceSegment[] = [];
  const realSegmentIds = new Set<string>();
  const firstSegmentBySource = new Map<string, string>();
  const assets: SourceAsset[] = data.sources.sources.map((source) => {
    const sourceSegments = source.segments || [];
    if (sourceSegments.length) {
      sourceSegments.forEach((segment, ordinal) => {
        const text = segment.text?.trim() || `来源定位：${segment.locator || source.title}`;
        segments.push({ id: segment.id, sourceId: source.id, ordinal, text, contentHash: stableHash(text) });
        realSegmentIds.add(segment.id);
        if (!firstSegmentBySource.has(source.id)) firstSegmentBySource.set(source.id, segment.id);
      });
    } else {
      const text = `来源元数据：${source.title}${source.url ? `\n${source.url}` : ""}`;
      const id = `segment:${source.id}:metadata`;
      segments.push({ id, sourceId: source.id, ordinal: 0, text, contentHash: stableHash(text) });
      firstSegmentBySource.set(source.id, id);
    }
    return {
      id: source.id,
      title: source.title,
      kind: sourceKind(source.kind),
      locator: source.url,
      observedAt: source.as_of,
      publishedAt: source.as_of,
      domain: domainOf(source.url),
      sourceTier: sourceTier(source.kind, source.claim_use),
      searchCategories: source.kind === "official_doc" ? ["official_standard"]
        : source.kind === "job_posting" ? ["job_market"] : ["work_practice"],
      contentHash: stableHash(`${source.id}:${source.title}:${source.url || ""}:${source.as_of || ""}`),
      visibility: "publishable_metadata",
    };
  });

  const bindings: EvidenceBinding[] = [];
  const bindingsByTarget = new Map<string, string[]>();
  const addBindings = (targetId: string, evidence: EvidenceSummary | WorkProcessEvidenceBinding | undefined, fieldPath = "summary") => {
    const sourceRefs = "source_refs" in (evidence || {}) ? (evidence as { source_refs?: string[] }).source_refs || [] : [];
    const evidenceConfidence = "confidence" in (evidence || {})
      ? Number((evidence as WorkProcessEvidenceBinding).confidence || 0.65)
      : confidenceOf(evidence as EvidenceSummary | undefined);
    const hasSegmentEvidence = "has_segment_evidence" in (evidence || {})
      ? Boolean((evidence as EvidenceSummary).has_segment_evidence)
      : (evidence as WorkProcessEvidenceBinding | undefined)?.assertion_type === "observed"
        || (evidence as WorkProcessEvidenceBinding | undefined)?.assertion_type === "normative";
    for (const sourceId of sourceRefs) {
      const segmentId = firstSegmentBySource.get(sourceId);
      if (!segmentId) continue;
      const id = `binding:${stableHash(`${targetId}:${fieldPath}:${sourceId}:${segmentId}`)}`;
      bindings.push({
        id,
        targetId,
        fieldPath,
        sourceId,
        segmentId,
        support: hasSegmentEvidence && realSegmentIds.has(segmentId) ? "direct" : "inferred",
        method: "compiler",
        confidence: Math.max(0, Math.min(1, evidenceConfidence)),
      });
      bindingsByTarget.set(targetId, [...(bindingsByTarget.get(targetId) || []), id]);
    }
  };

  data.graph.nodes.forEach((node) => addBindings(node.id, node.evidence_summary));
  data.graph.edges.forEach((edge) => addBindings(edge.id, edge.evidence_summary, "relationship"));
  data.workProcess.scenarios.forEach((scenario) => addBindings(scenario.id, scenario.evidence_binding));
  data.workProcess.nodes.forEach((node) => addBindings(node.id, node.evidence_binding));
  data.workProcess.relations.forEach((relation) => addBindings(relation.id, relation.evidence_binding, "relationship"));

  const segmentIdsFor = (targetId: string) => unique((bindingsByTarget.get(targetId) || [])
    .map((id) => bindings.find((binding) => binding.id === id)?.segmentId || ""));

  const semanticNodes = data.graph.nodes.map((node) => ({
    id: node.id,
    type: node.type as ColdStartBuildResult["semantic"]["nodes"][number]["type"],
    label: node.label,
    summary: node.summary,
    aliases: Array.isArray(node.data.aliases) ? node.data.aliases.filter((value): value is string => typeof value === "string") : [],
    lifecycle: lifecycle(node.lifecycle),
    confidence: confidenceOf(node.evidence_summary),
    evidenceSegmentIds: segmentIdsFor(node.id),
    evidenceBindingIds: bindingsByTarget.get(node.id) || [],
    ring: node.ring,
  }));
  const semanticEdges = data.graph.edges.map((edge) => ({
    id: edge.id,
    type: edge.type,
    source: edge.source,
    target: edge.target,
    lifecycle: lifecycle(edge.lifecycle),
    confidence: confidenceOf(edge.evidence_summary),
    evidenceSegmentIds: segmentIdsFor(edge.id),
    evidenceBindingIds: bindingsByTarget.get(edge.id) || [],
  }));

  const scenarios = data.workProcess.scenarios.map((scenario) => ({
    id: scenario.id,
    label: scenario.title,
    summary: scenario.summary,
    trigger: scenario.trigger,
    outcome: scenario.expected_outcomes.join("；") || scenario.goal,
    knowledgeState: scenario.knowledge_state,
    lifecycle: lifecycle(scenario.lifecycle),
    evidenceSegmentIds: segmentIdsFor(scenario.id),
    evidenceBindingIds: bindingsByTarget.get(scenario.id) || [],
  }));
  const processNodes: ProcessNode[] = data.workProcess.nodes.map((node) => ({
    id: node.id,
    scenarioId: node.scenario_id,
    kind: node.kind === "event" || node.kind === "artifact" || node.kind === "actor" ? node.kind : "work_object",
    label: node.label,
    summary: node.summary,
    sequenceHint: node.sequence_hint,
    knowledgeState: data.workProcess.scenarios.find((scenario) => scenario.id === node.scenario_id)?.knowledge_state || "inferred_pattern",
    lifecycle: lifecycle(node.lifecycle),
    evidenceSegmentIds: segmentIdsFor(node.id),
    evidenceBindingIds: bindingsByTarget.get(node.id) || [],
  }));
  const bridgeTypes = new Set(["realizes_task", "uses_skill", "produces_deliverable"]);
  const semanticIds = new Set(semanticNodes.map((node) => node.id));
  const bridges: SemanticBridge[] = [];
  const bridgeKeys = new Set<string>();
  const appendBridge = (bridge: SemanticBridge) => {
    const key = `${bridge.processNodeId}:${bridge.type}:${bridge.semanticNodeId}`;
    if (bridgeKeys.has(key)) return;
    bridgeKeys.add(key);
    bridges.push(bridge);
  };
  const processEdges: ProcessEdge[] = [];
  for (const relation of data.workProcess.relations) {
    const processSide = semanticIds.has(relation.source) ? relation.target : relation.source;
    const semanticSide = semanticIds.has(relation.source) ? relation.source : relation.target;
    if (bridgeTypes.has(relation.type) && semanticIds.has(semanticSide)) {
      appendBridge({
        id: relation.id,
        processNodeId: processSide,
        semanticNodeId: semanticSide,
        type: relation.type as SemanticBridge["type"],
        confidence: relation.evidence_binding.confidence,
      });
    } else {
      processEdges.push({
        id: relation.id,
        type: relation.type,
        source: relation.source,
        target: relation.target,
        evidenceSegmentIds: segmentIdsFor(relation.id),
        evidenceBindingIds: bindingsByTarget.get(relation.id) || [],
      });
    }
  }
  // The historical work-process package also stores semantic references on
  // scenarios and events. Preserve those references as bridges so conversion
  // into the unified role package does not silently lose task or skill links.
  for (const scenario of data.workProcess.scenarios) {
    for (const taskId of scenario.task_refs || []) {
      if (!semanticIds.has(taskId)) continue;
      appendBridge({
        id: `bridge:${stableHash(`${scenario.id}:realizes_task:${taskId}`)}`,
        processNodeId: scenario.id,
        semanticNodeId: taskId,
        type: "realizes_task",
        confidence: scenario.evidence_binding.confidence,
      });
    }
  }
  for (const node of data.workProcess.nodes) {
    for (const taskId of node.task_refs || []) {
      if (!semanticIds.has(taskId)) continue;
      appendBridge({
        id: `bridge:${stableHash(`${node.id}:realizes_task:${taskId}`)}`,
        processNodeId: node.id,
        semanticNodeId: taskId,
        type: "realizes_task",
        confidence: node.evidence_binding.confidence,
      });
    }
    for (const skillId of node.knowledge_skill_refs || []) {
      if (!semanticIds.has(skillId)) continue;
      appendBridge({
        id: `bridge:${stableHash(`${node.id}:uses_skill:${skillId}`)}`,
        processNodeId: node.id,
        semanticNodeId: skillId,
        type: "uses_skill",
        confidence: node.evidence_binding.confidence,
      });
    }
  }

  const role = semanticNodes.find((node) => node.type === "market_role");
  const tasks = semanticNodes.filter((node) => node.type === "task");
  const capabilities = semanticNodes.filter((node) => node.type === "capability" || node.type === "capability_unit");
  const skills = semanticNodes.filter((node) => node.type === "knowledge_skill");
  const researchTopics: ResearchTopic[] = data.workProcess.alignment
    .filter((item) => item.status === "gap" || item.status === "partial")
    .map((item) => ({
      id: `research:${stableHash(`${item.semantic_target_id}:${item.status}`)}`,
      title: `补充工作过程证据：${semanticNodes.find((node) => node.id === item.semantic_target_id)?.label || item.semantic_target_id}`,
      question: `需要哪些真实工作资料或规范，才能确认该对象如何进入岗位工作过程？`,
      reason: item.note,
      targetIds: [item.semantic_target_id],
    }));
  const auditIssues: AuditIssue[] = [];
  const snapshotSections = [
    section("overview", "岗位概览", "岗位定位、边界、产业位置与相邻岗位的结构化概览。", role ? [role.id] : [], bindingsByTarget),
    section("tasks", "典型工作任务", "以可独立交付和验收为边界组织岗位承担的典型工作任务。", tasks.map((node) => node.id), bindingsByTarget),
    section("capabilities", "工作能力", "跨场景迁移的能力及其可观察表现，和具体工具技能分层表达。", capabilities.map((node) => node.id), bindingsByTarget),
    section("knowledge-skills", "知识技能", "支撑任务实施、面试判断、课程学习和项目实践的具体知识技能。", skills.map((node) => node.id), bindingsByTarget),
    section("work-process", "工作过程", "用事理森林呈现触发、事件、参与者、交付物、分支与回路。", scenarios.map((scenario) => scenario.id), bindingsByTarget),
    section("evidence-risks", "证据与风险", "记录每项认识的来源、证据粒度、时间边界与仍需研究的缺口。", researchTopics.flatMap((topic) => topic.targetIds), bindingsByTarget),
  ];
  const evidenceCoverageTargets = [...semanticNodes, ...semanticEdges, ...scenarios, ...processNodes, ...processEdges];
  const evidenceCoverage = evidenceCoverageTargets.length
    ? evidenceCoverageTargets.filter((target) => (bindingsByTarget.get(target.id) || []).length > 0).length / evidenceCoverageTargets.length
    : 0;
  const processTaskCoverage = tasks.length
    ? tasks.filter((task) => bridges.some((bridge) => bridge.type === "realizes_task" && bridge.semanticNodeId === task.id)).length / tasks.length
    : 0;

  const result: ColdStartBuildResult = {
    runId: `adapt:${stableHash(data.manifest.snapshot_id)}`,
    projectId: data.manifest.package_id,
    brief: {
      projectId: data.manifest.package_id,
      roleTitle: role?.label || "岗位快照",
      roleDescription: role?.summary || "",
      market: "中国大陆",
      audience: ["高职学生", "教师", "企业"],
      snapshotAsOf: data.manifest.snapshot_as_of,
      assumptions: [],
    },
    sources: { assets, segments, evidenceBindings: bindings },
    semantic: {
      nodes: semanticNodes,
      edges: semanticEdges,
      claims: data.graph.nodes.flatMap((node) => (node.assertion_refs || []).map((assertionId) => ({
        id: assertionId,
        subjectId: node.id,
        predicate: "asserted",
        value: node.summary,
        status: node.lifecycle === "accepted" ? "accepted" as const : "candidate" as const,
        evidenceSegmentIds: segmentIdsFor(node.id),
        evidenceBindingIds: bindingsByTarget.get(node.id) || [],
        confidence: confidenceOf(node.evidence_summary),
      }))),
    },
    process: { scenarios, nodes: processNodes, edges: processEdges, bridges },
    snapshot: { id: data.manifest.snapshot_id, asOf: data.manifest.snapshot_as_of, status: "ready", sections: snapshotSections },
    audit: { issues: auditIssues, researchTopics },
    packages: {
      rolePackage: undefined as never,
    },
    validation: {
      publishable: data.validation.publishable && data.workProcessValidation.publishable,
      structural: { passed: data.validation.valid, issues: data.validation.errors },
      semantic: { passed: data.validation.valid, issues: data.validation.warnings },
      evidence: { passed: evidenceCoverage > 0.5, coverage: Number(evidenceCoverage.toFixed(4)), issues: [] },
      temporal: { passed: true, issues: [] },
      process: { passed: data.workProcessValidation.valid, coverage: Number(processTaskCoverage.toFixed(4)), issues: data.workProcessValidation.errors },
    },
  };
  result.packages.rolePackage = createRolePackageManifest({
    result,
    packageId: data.manifest.package_id,
    packageVersion: COMPOSITE_VERSION,
    status: "ready",
  });
  return result;
}
