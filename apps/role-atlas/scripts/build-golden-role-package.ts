import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type {
  ColdStartBuildResult,
  EvidenceBinding,
  ProcessEdge,
  ProcessNode,
  ProcessScenario,
  SemanticBridge,
  SemanticClaim,
  SemanticEdge,
  SemanticNode,
  SourceAsset,
  SourceSegment,
} from "../lib/build/types";
import { compileStaticRolePackage } from "../lib/packages/compiler";
import { createRolePackageManifest } from "../lib/packages/role-package-manifest";

const root = path.resolve(import.meta.dirname, "..");
const researchRoot = path.join(root, "research/golden-role-packages/llm-app-engineer");
const outputRoot = path.join(root, "packages/golden/llm-app-engineer/1.0.0");
const snapshotId = "snapshot:role:llm-app-engineer@2026-08-24-gold-v1";
const packageId = "role-package:llm-app-engineer-golden";
const packageVersion = "1.0.0";

const readJson = async (relative: string) => JSON.parse(await readFile(path.join(researchRoot, relative), "utf8"));
const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");
const unique = <T>(values: T[]) => [...new Set(values)];
const strengthScore = (strength: string | undefined) => strength === "strong" ? 0.9 : strength === "moderate" ? 0.65 : 0.35;

const sourceRegister = await readJson("sources/source-register.json");
const evidenceSegments = await readJson("segments/evidence-segments.json");
const claimRegister = await readJson("claims/claims.json");
const taskBarrier = await readJson("task-barrier/task-barrier.json");
const capabilityModel = await readJson("task-barrier/capability-model.json");
const processForest = await readJson("task-barrier/process-forest.json");

const claimById = new Map<string, any>(claimRegister.claims.map((claim: any) => [claim.id, claim]));
const segmentById = new Map<string, any>(evidenceSegments.segments.map((segment: any) => [segment.id, segment]));

const sources: SourceAsset[] = sourceRegister.sources.map((source: any) => ({
  id: source.id,
  title: source.title,
  kind: "public_document",
  locator: source.locator,
  observedAt: source.fetchedAt,
  publisher: source.publisher,
  publishedAt: source.publishedAt,
  fetchedAt: source.fetchedAt,
  sourceTier: source.sourceTier,
  sourceType: source.sourceType,
  independenceGroup: source.independenceGroup,
  contentHash: sha256(JSON.stringify({ title: source.title, locator: source.locator, publishedAt: source.publishedAt, fetchedAt: source.fetchedAt })),
  visibility: "publishable_metadata",
  qualification: source.qualification,
  limitations: source.limitations || [],
}));

const segments: SourceSegment[] = evidenceSegments.segments.map((segment: any) => ({
  id: segment.id,
  sourceId: segment.sourceId,
  ordinal: segment.ordinal,
  text: segment.text,
  contentHash: sha256(segment.text),
  locator: segment.locator,
  page: segment.page,
  section: segment.section,
  paragraph: segment.paragraph,
  observedAt: segment.observedAt,
  excerptType: segment.excerptType,
}));

const evidenceBindings: EvidenceBinding[] = [];
function evidenceFor(targetId: string, claimIds: string[], fieldPath = "*") {
  const bindingIds: string[] = [];
  const evidenceSegmentIds: string[] = [];
  const candidates: Array<{ claim: any; segment: any; segmentId: string }> = [];
  for (const claimId of unique(claimIds)) {
    const claim = claimById.get(claimId);
    if (!claim) throw new Error(`Unknown claim ${claimId} for ${targetId}`);
    for (const segmentId of claim.evidenceSegmentIds || []) {
      const segment = segmentById.get(segmentId);
      if (!segment) throw new Error(`Unknown segment ${segmentId} for ${targetId}`);
      candidates.push({ claim, segment, segmentId });
    }
  }
  const limit = fieldPath === "claim" ? Number.POSITIVE_INFINITY : fieldPath === "node" || fieldPath === "scenario" ? 8 : fieldPath === "event" ? 6 : 4;
  const distinctSources = unique(candidates.map((candidate) => candidate.segment.sourceId));
  const selected = [
    ...distinctSources.map((sourceId) => candidates.find((candidate) => candidate.segment.sourceId === sourceId)!),
    ...candidates,
  ].filter((candidate, index, values) => values.findIndex((value) => value.segmentId === candidate.segmentId) === index).slice(0, limit);
  for (const { claim, segment, segmentId } of selected) {
    const id = `eb:${targetId}:${segmentId}`;
    if (!evidenceBindings.some((binding) => binding.id === id)) {
      evidenceBindings.push({
        id,
        targetId,
        fieldPath,
        sourceId: segment.sourceId,
        segmentId,
        support: claim.assertionType === "direct_fact" ? "direct" : "inferred",
        method: "compiler",
        confidence: strengthScore(claim.strength),
        assertionType: claim.status === "disputed" ? "disputed" : claim.assertionType,
        supportRole: claim.status === "rejected" ? "contradicts" : claim.status === "disputed" ? "limits" : "supports",
        strength: claim.strength,
        limitations: unique([...(claim.limitations || []), ...(claim.status === "disputed" ? ["该结论在本版本中保持争议状态。"] : [])]),
        rationale: `兼容字段confidence仅由证据强度${claim.strength}映射为固定档位，不表示统计概率；断言状态见${claim.id}。`,
      });
    }
    bindingIds.push(id);
    evidenceSegmentIds.push(segmentId);
  }
  return { bindingIds: unique(bindingIds), segmentIds: unique(evidenceSegmentIds) };
}

const semanticNodes: SemanticNode[] = [];
function addSemanticNode(input: {
  id: string;
  type: SemanticNode["type"];
  label: string;
  summary: string;
  claimIds: string[];
  aliases?: string[];
  ring: number;
  lifecycle?: SemanticNode["lifecycle"];
  learningKind?: SemanticNode["learningKind"];
  applicability?: string;
  observableOutcome?: string;
}) {
  const evidence = evidenceFor(input.id, input.claimIds, "node");
  const weakestStatus = input.claimIds.map((id) => claimById.get(id)?.status);
  semanticNodes.push({
    id: input.id,
    type: input.type,
    label: input.label,
    summary: input.summary,
    aliases: input.aliases || [],
    lifecycle: input.lifecycle || (weakestStatus.some((status) => status === "disputed") ? "candidate" : "stable"),
    confidence: Math.min(...input.claimIds.map((id) => strengthScore(claimById.get(id)?.strength))),
    evidenceSegmentIds: evidence.segmentIds,
    evidenceBindingIds: evidence.bindingIds,
    ring: input.ring,
    learningKind: input.learningKind,
    applicability: input.applicability,
    observableOutcome: input.observableOutcome,
  });
}

addSemanticNode({
  id: "role:llm-app-engineer",
  type: "market_role",
  label: "大模型应用工程师",
  aliases: ["LLM应用工程师", "AI大模型应用开发工程师", "大模型应用开发工程师", "大模型应用后端工程师"],
  summary: "把业务需求与可用模型转化为可评价、可集成、可运行、可迭代应用系统的企业工程岗位实例。",
  claimIds: ["CLM-B06", "CLM-B08", "CLM-B09", "CLM-B10"],
  ring: 0,
});
addSemanticNode({ id: "chain:foundation-model", type: "industry_chain_node", label: "基础模型与模型服务层", summary: "提供通用或行业模型能力、接口及模型服务。", claimIds: ["CLM-B10", "CLM-T03"], ring: 1 });
addSemanticNode({ id: "chain:llm-application-engineering", type: "industry_chain_node", label: "大模型应用工程层", summary: "组合模型、知识、上下文、工具和软件工程能力，形成可运行应用。", claimIds: ["CLM-B10", "CLM-C02"], ring: 1 });
addSemanticNode({ id: "chain:industry-application", type: "industry_chain_node", label: "行业与业务应用层", summary: "在具体业务流程中使用应用系统并评价其结果与风险。", claimIds: ["CLM-B10", "CLM-T01"], ring: 1 });
addSemanticNode({ id: "family:ai-application-engineering", type: "job_family", label: "人工智能应用工程岗位群", summary: "围绕AI应用开发、系统集成、运行质量与工程交付形成的岗位群。", claimIds: ["CLM-B03", "CLM-B07", "CLM-B10"], ring: 1 });
addSemanticNode({ id: "occupation:CN:2-02-38-01", type: "occupation_standard", label: "人工智能工程技术人员", summary: "目标岗位的工程主锚；正式范围覆盖人工智能系统设计、集成、部署、运维与应用。", claimIds: ["CLM-B01", "CLM-B02", "CLM-B03", "CLM-B04"], ring: 1 });
addSemanticNode({ id: "occupation:CN:4-04-05-13", type: "occupation_standard", label: "生成式人工智能系统应用员", summary: "目标岗位的专项规范映射；覆盖生成式AI系统设计、调用、训练、优化、部署、更新和支持。", claimIds: ["CLM-B05", "CLM-B06"], ring: 1 });
addSemanticNode({ id: "related-role:llm-algorithm-engineer", type: "related_role", label: "大模型算法工程师", summary: "主要价值在模型或算法创新、后训练与深度模型优化。", claimIds: ["CLM-B11"], ring: 1 });
addSemanticNode({ id: "related-role:agent-engineer", type: "related_role", label: "AI Agent工程师", summary: "业务Agent是本岗位方向；通用Agent平台内核更接近AI Infra。", claimIds: ["CLM-B14", "CLM-D03"], ring: 1 });
addSemanticNode({ id: "related-role:backend-engineer", type: "related_role", label: "后端工程师", summary: "共享API、数据与服务能力，但不默认承担模型行为、知识链路和AI质量闭环。", claimIds: ["CLM-B13"], ring: 1 });
addSemanticNode({ id: "related-role:llmops-ai-infra", type: "related_role", label: "MLOps/LLMOps与AI Infra工程师", summary: "主要负责组织级模型、算力、部署和通用平台底座。", claimIds: ["CLM-B12", "CLM-D02"], ring: 1 });

for (const task of taskBarrier.tasks) addSemanticNode({
  id: task.id,
  type: "task",
  label: task.label,
  summary: `${task.action}；交付：${task.deliverables.join("、")}；完成边界：${task.completionBoundary}`,
  claimIds: task.claimIds,
  ring: 2,
});
for (const capability of capabilityModel.capabilities) addSemanticNode({
  id: capability.id,
  type: "capability",
  label: capability.label,
  summary: `${capability.summary} 表现：${capability.performance} 价值：${capability.value}`,
  claimIds: capability.claimIds,
  ring: 3,
  applicability: capability.applicableScenarios,
  observableOutcome: capability.performance,
});
for (const unit of capabilityModel.capabilityUnits) addSemanticNode({
  id: unit.id,
  type: "capability_unit",
  label: unit.label,
  summary: unit.observablePerformance,
  claimIds: unit.claimIds,
  ring: 4,
  applicability: `任务：${unit.taskIds.join("、")}`,
  observableOutcome: `测评证据：${unit.assessmentEvidence.join("、")}`,
});
for (const item of capabilityModel.knowledgeSkills) addSemanticNode({
  id: item.id,
  type: "knowledge_skill",
  label: item.label,
  summary: item.summary,
  claimIds: item.claimIds,
  ring: 5,
  learningKind: item.learningKind,
  applicability: item.applicability,
  observableOutcome: item.observableOutcome,
  lifecycle: item.id.includes("peft-lora") ? "candidate" : "stable",
});

const semanticEdges: SemanticEdge[] = [];
function addSemanticEdge(source: string, type: string, target: string, claimIds: string[], lifecycle: SemanticEdge["lifecycle"] = "stable") {
  const id = `rel:${source}:${type}:${target}`;
  const evidence = evidenceFor(id, claimIds, "relation");
  semanticEdges.push({ id, type, source, target, lifecycle, confidence: Math.min(...claimIds.map((claimId) => strengthScore(claimById.get(claimId)?.strength))), evidenceSegmentIds: evidence.segmentIds, evidenceBindingIds: evidence.bindingIds });
}
addSemanticEdge("chain:foundation-model", "feeds", "chain:llm-application-engineering", ["CLM-B10", "CLM-T03"]);
addSemanticEdge("chain:llm-application-engineering", "serves", "chain:industry-application", ["CLM-B10", "CLM-T01"]);
addSemanticEdge("chain:llm-application-engineering", "contains_job_family", "family:ai-application-engineering", ["CLM-B03", "CLM-B07"]);
addSemanticEdge("family:ai-application-engineering", "includes_role", "role:llm-app-engineer", ["CLM-B07", "CLM-B10"]);
addSemanticEdge("role:llm-app-engineer", "primary_engineering_anchor", "occupation:CN:2-02-38-01", ["CLM-B01", "CLM-B04", "CLM-B06"]);
addSemanticEdge("role:llm-app-engineer", "specialized_normative_mapping", "occupation:CN:4-04-05-13", ["CLM-B05", "CLM-B06"]);
for (const related of ["related-role:llm-algorithm-engineer", "related-role:agent-engineer", "related-role:backend-engineer", "related-role:llmops-ai-infra"]) {
  const claimId = related.includes("algorithm") ? "CLM-B11" : related.includes("agent") ? "CLM-B14" : related.includes("backend") ? "CLM-B13" : "CLM-B12";
  addSemanticEdge("role:llm-app-engineer", "adjacent_to", related, [claimId]);
}
for (const task of taskBarrier.tasks) addSemanticEdge("role:llm-app-engineer", "has_typical_task", task.id, task.claimIds);
for (const capability of capabilityModel.capabilities) {
  addSemanticEdge("role:llm-app-engineer", "requires_capability", capability.id, capability.claimIds);
  for (const taskId of capability.taskIds) addSemanticEdge(capability.id, "transfers_across", taskId, capability.claimIds);
}
for (const unit of capabilityModel.capabilityUnits) {
  addSemanticEdge(unit.capabilityId, "decomposes_into", unit.id, unit.claimIds);
  for (const taskId of unit.taskIds) addSemanticEdge(unit.id, "demonstrated_in", taskId, unit.claimIds);
}
for (const item of capabilityModel.knowledgeSkills) {
  const lifecycle = item.id.includes("peft-lora") ? "candidate" : "stable";
  for (const unitId of item.unitIds) addSemanticEdge(unitId, "requires_learning_element", item.id, item.claimIds, lifecycle);
  for (const taskId of item.taskIds) addSemanticEdge(item.id, "supports_task", taskId, item.claimIds, lifecycle);
}
for (const prerequisite of capabilityModel.prerequisites) {
  const item = capabilityModel.knowledgeSkills.find((candidate: any) => candidate.id === prerequisite.source);
  addSemanticEdge(prerequisite.source, "prerequisite_of", prerequisite.target, item.claimIds, prerequisite.source.includes("peft-lora") || prerequisite.target.includes("peft-lora") ? "candidate" : "stable");
}

const taskClaimSubject: Record<string, string> = {
  "01": "task:llmapp:define-scenario", "02": "task:llmapp:define-scenario",
  "03": "task:llmapp:design-solution", "04": "task:llmapp:design-solution",
  "05": "task:llmapp:build-rag", "06": "task:llmapp:build-rag",
  "07": "task:llmapp:build-agent-integration", "08": "task:llmapp:build-agent-integration", "16": "task:llmapp:build-agent-integration",
  "09": "task:llmapp:control-model-behavior", "10": "task:llmapp:control-model-behavior",
  "11": "task:llmapp:evaluate-quality-safety", "12": "task:llmapp:evaluate-quality-safety",
  "13": "task:llmapp:release-service", "17": "task:llmapp:release-service",
  "14": "task:llmapp:operate-improve", "15": "task:llmapp:operate-improve",
};
const boundaryClaimSubject: Record<string, string> = {
  "01": "occupation:CN:2-02-38-01", "02": "occupation:CN:2-02-38-01", "03": "occupation:CN:2-02-38-01", "04": "occupation:CN:2-02-38-01",
  "05": "occupation:CN:4-04-05-13", "06": "role:llm-app-engineer", "07": "role:llm-app-engineer", "08": "role:llm-app-engineer", "09": "role:llm-app-engineer", "10": "role:llm-app-engineer",
  "11": "related-role:llm-algorithm-engineer", "12": "related-role:llmops-ai-infra", "13": "related-role:backend-engineer", "14": "related-role:agent-engineer",
};
const capabilityClaimSubject: Record<string, string> = Object.fromEntries(capabilityModel.capabilities.map((item: any, index: number) => [String(index + 1).padStart(2, "0"), item.id]));
const unitClaimSubject: Record<string, string> = {
  "01": "unit:llmapp:model-work-scenario", "02": "unit:llmapp:compare-solution-paths", "03": "unit:llmapp:evaluate-components-e2e", "04": "unit:llmapp:implement-agent-tools", "05": "unit:llmapp:diagnose-regress",
};
function subjectForClaim(claim: any) {
  const [, prefix, suffix] = claim.id.match(/^CLM-([A-Z]+)(\d+)$/) || [];
  if (prefix === "B") return boundaryClaimSubject[suffix] || "role:llm-app-engineer";
  if (prefix === "T") return taskClaimSubject[suffix] || "role:llm-app-engineer";
  if (prefix === "C") return capabilityClaimSubject[suffix] || "role:llm-app-engineer";
  if (prefix === "CU") return unitClaimSubject[suffix] || "role:llm-app-engineer";
  if (prefix === "D" && suffix === "02") return "related-role:llmops-ai-infra";
  if (prefix === "D" && (suffix === "03" || suffix === "08")) return "related-role:agent-engineer";
  if (prefix === "D" && suffix === "01") return "knowledge:llmapp:peft-lora-conditional";
  return "role:llm-app-engineer";
}
const semanticClaims: SemanticClaim[] = claimRegister.claims.map((claim: any) => {
  const evidence = evidenceFor(claim.id, claim.evidenceSegmentIds?.length ? [claim.id] : [], "claim");
  return {
    id: claim.id,
    subjectId: subjectForClaim(claim),
    predicate: claim.assertionType,
    value: claim.statement,
    status: claim.status,
    evidenceSegmentIds: evidence.segmentIds,
    evidenceBindingIds: evidence.bindingIds,
    confidence: strengthScore(claim.strength),
    assertionType: claim.assertionType,
    limitations: unique([...(claim.limitations || []), ...(claim.status === "disputed" ? ["争议结论不得在Agent回答中表述为岗位稳定内核。"] : []), ...(claim.status === "rejected" ? ["本版本明确拒绝该结论。"] : [])]),
    conflictRefs: claim.conflictRefs || [],
  };
});

const processScenarios: ProcessScenario[] = [];
const processNodes: ProcessNode[] = [];
const processEdges: ProcessEdge[] = [];
const processBridges: SemanticBridge[] = [];
for (const authoredScenario of processForest.scenarios) {
  const scenarioEvidence = evidenceFor(authoredScenario.id, authoredScenario.claimIds, "scenario");
  const nodeIdsByKind = (kind: string) => authoredScenario.nodes.filter((node: any) => node.kind === kind).map((node: any) => node.id);
  processScenarios.push({
    id: authoredScenario.id,
    label: authoredScenario.label,
    summary: authoredScenario.summary,
    trigger: authoredScenario.trigger,
    outcome: authoredScenario.outcome,
    knowledgeState: authoredScenario.knowledgeState,
    lifecycle: "stable",
    evidenceSegmentIds: scenarioEvidence.segmentIds,
    evidenceBindingIds: scenarioEvidence.bindingIds,
    taskRefs: authoredScenario.taskRefs,
    actorRefs: nodeIdsByKind("actor"),
    inputRefs: nodeIdsByKind("work_object"),
    outputRefs: nodeIdsByKind("artifact"),
    acceptanceCriteria: authoredScenario.acceptanceCriteria,
  });
  for (const authoredNode of authoredScenario.nodes) {
    const nodeEvidence = evidenceFor(authoredNode.id, authoredNode.claimIds, authoredNode.kind === "event" ? "event" : authoredNode.kind);
    processNodes.push({
      id: authoredNode.id,
      scenarioId: authoredScenario.id,
      kind: authoredNode.kind,
      label: authoredNode.label,
      summary: authoredNode.summary,
      sequenceHint: authoredNode.sequenceHint,
      knowledgeState: authoredScenario.knowledgeState,
      lifecycle: "stable",
      eventType: authoredNode.eventType,
      lane: authoredNode.lane,
      taskRefs: authoredNode.taskRefs,
      actorRefs: authoredNode.actorRefs,
      objectRefs: authoredNode.objectRefs,
      artifactRefs: authoredNode.artifactRefs,
      toolRefs: authoredNode.toolRefs,
      qualityCriterionRefs: authoredNode.qualityCriterionRefs,
      evidenceSegmentIds: nodeEvidence.segmentIds,
      evidenceBindingIds: nodeEvidence.bindingIds,
    });
    if (authoredNode.kind === "event") {
      const derived: Array<[string, string]> = [
        ...((authoredNode.actorRefs || []).map((target: string) => ["involves_actor", target] as [string, string])),
        ...((authoredNode.objectRefs || []).map((target: string) => ["acts_on", target] as [string, string])),
        ...((authoredNode.artifactRefs || []).map((target: string) => ["uses_or_updates_artifact", target] as [string, string])),
        ...((authoredNode.toolRefs || []).map((target: string) => ["uses_tool_system", target] as [string, string])),
        ...((authoredNode.qualityCriterionRefs || []).map((target: string) => ["checked_against", target] as [string, string])),
      ];
      for (const [type, target] of derived) {
        const id = `process-rel:${authoredNode.id}:${type}:${target}`;
        const edgeEvidence = evidenceFor(id, authoredNode.claimIds, "process_relation");
        processEdges.push({ id, type, source: authoredNode.id, target, evidenceSegmentIds: edgeEvidence.segmentIds, evidenceBindingIds: edgeEvidence.bindingIds, lifecycle: "stable", knowledgeState: authoredScenario.knowledgeState });
      }
      for (const taskId of authoredNode.taskRefs || []) {
        const id = `bridge:${authoredNode.id}:realizes:${taskId}`;
        const bridgeEvidence = evidenceFor(id, authoredNode.claimIds, "semantic_bridge");
        processBridges.push({
          id,
          processNodeId: authoredNode.id,
          semanticNodeId: taskId,
          type: "realizes_task",
          confidence: Math.min(...authoredNode.claimIds.map((claimId: string) => strengthScore(claimById.get(claimId)?.strength))),
          evidenceSegmentIds: bridgeEvidence.segmentIds,
          evidenceBindingIds: bridgeEvidence.bindingIds,
          assertionType: "research_inference",
          limitations: ["桥接表示经人工审视的任务—事件对应，不表示来源逐字给出稳定ID。"],
        });
      }
    }
  }
  for (const [index, flow] of authoredScenario.flows.entries()) {
    const id = `flow:${authoredScenario.id}:${String(index + 1).padStart(2, "0")}`;
    const flowEvidence = evidenceFor(id, flow.claimIds, "process_relation");
    processEdges.push({ id, type: flow.type, source: flow.source, target: flow.target, evidenceSegmentIds: flowEvidence.segmentIds, evidenceBindingIds: flowEvidence.bindingIds, lifecycle: "stable", knowledgeState: authoredScenario.knowledgeState, qualifiers: flow.qualifiers });
  }
}

const sections = [
  { id: "section:identity-boundary", title: "岗位身份与边界", summary: "企业岗位实例、正式职业锚点、产业位置与相邻岗位。", itemIds: semanticNodes.filter((node) => node.ring <= 1).map((node) => node.id) },
  { id: "section:task-barrier", title: "典型工作任务", summary: "以工作对象、动作、交付物和完成边界冻结的八项任务。", itemIds: semanticNodes.filter((node) => node.type === "task").map((node) => node.id) },
  { id: "section:capabilities", title: "岗位能力与能力单元", summary: "跨任务迁移能力及其可观察、可测评表现。", itemIds: semanticNodes.filter((node) => node.type === "capability" || node.type === "capability_unit").map((node) => node.id) },
  { id: "section:knowledge-skills", title: "核心知识与技能", summary: "区分概念原理与可操作行为，并标注应用位置和验收结果。", itemIds: semanticNodes.filter((node) => node.type === "knowledge_skill").map((node) => node.id) },
  { id: "section:process-forest", title: "事理森林", summary: "四个代表性工作情境及其参与者、资源、分支、异常、返工和验收。", itemIds: processScenarios.map((scenario) => scenario.id) },
].map((section) => ({
  ...section,
  status: "stable" as const,
  evidenceBindingIds: unique(section.itemIds.flatMap((id) => semanticNodes.find((node) => node.id === id)?.evidenceBindingIds || processScenarios.find((scenario) => scenario.id === id)?.evidenceBindingIds || [])),
}));

const result: ColdStartBuildResult = {
  runId: "golden:llm-app-engineer:1.0.0",
  projectId: "golden-role-package:llm-app-engineer",
  brief: {
    projectId: "golden-role-package:llm-app-engineer",
    roleTitle: "大模型应用工程师",
    roleDescription: "面向中国大陆职业教育与企业岗位理解的研究型黄金岗位包。",
    market: "中国大陆",
    audience: ["高职学生", "教师", "企业人员", "Role Atlas Agent"],
    snapshotAsOf: "2026-08-24",
    assumptions: [
      "岗位名是企业岗位实例名，不冒充国家职业分类名称。",
      "人工智能工程技术人员2-02-38-01为工程主锚，生成式人工智能系统应用员4-04-05-13为专项规范映射。",
      "PEFT、自托管推理平台、前端全栈和通用Agent平台属于条件性或相邻职责。",
      "confidence字段仅为三档证据强度的兼容投影，不是统计概率。",
    ],
  },
  sources: { assets: sources, segments, evidenceBindings },
  semantic: { nodes: semanticNodes, edges: semanticEdges, claims: semanticClaims },
  process: { scenarios: processScenarios, nodes: processNodes, edges: processEdges, bridges: processBridges },
  snapshot: { id: snapshotId, asOf: "2026-08-24", status: "ready", sections },
  audit: {
    issues: [
      { id: "audit:no-private-observed-episode", code: "NO_PRIVATE_OBSERVED_EPISODE", severity: "warning", title: "缺少企业内部完整工作事件", detail: "事理森林由正式标准、技术规范、企业岗位样本和公开Issue交叉归纳；不得声称为单一企业流程实录。", targetIds: processScenarios.map((scenario) => scenario.id), repair: "organization_specific" },
      { id: "audit:market-sample-scope", code: "MARKET_SAMPLE_SCOPE", severity: "warning", title: "企业样本代表性有限", detail: "样本覆盖大型互联网、软件、研究教育和国企岗位，但不能代表所有地区、规模、行业与资历层级。", targetIds: ["role:llm-app-engineer"], repair: "research" },
      { id: "audit:regulation-scope", code: "REGULATION_SCOPE", severity: "info", title: "法规适用需逐场景判断", detail: "面向境内公众提供生成式AI服务与企业内部研发应用的监管适用范围不同，Agent回答不得一概而论。", targetIds: ["knowledge:llmapp:safety-privacy-compliance"], repair: "organization_specific" },
    ],
    researchTopics: [
      { id: "research:private-episodes", title: "补充企业内部工作事件", question: "能否获得脱敏的需求、设计、评测、发布和事故闭环材料？", reason: "用于把部分inferred_pattern升级为observed_pattern。", targetIds: processScenarios.map((scenario) => scenario.id) },
      { id: "research:small-company-roles", title: "补充小型企业岗位组合样本", question: "小团队中前端、后端、模型适配和运维组合职责的稳定边界是什么？", reason: "当前企业样本仍偏正式组织和较大团队。", targetIds: ["role:llm-app-engineer"] },
    ],
  },
  packages: {
    rolePackage: {
      protocolVersion: "3.0.0",
      packageId,
      packageVersion,
      snapshotId,
      snapshotAsOf: "2026-08-24",
      status: "ready",
      namespaces: {
        evidence: { id: "evidence", schemaVersion: "2.0.0", objectCount: 0, fingerprint: "pending" },
        semantic: { id: "semantic", schemaVersion: "2.0.0", objectCount: 0, fingerprint: "pending" },
        process: { id: "process", schemaVersion: "2.0.0", objectCount: 0, fingerprint: "pending" },
      },
    },
  },
  validation: {
    publishable: true,
    structural: { passed: true, issues: [] },
    semantic: { passed: true, issues: [] },
    evidence: { passed: true, coverage: 1, issues: ["直接事实、跨来源归纳、研究推断、争议和拒绝结论已分类；数值confidence仅为三档兼容投影。"] },
    temporal: { passed: true, issues: [] },
    process: { passed: true, coverage: 1, issues: ["缺少企业内部完整工作事件，事理树不得表述为单一企业流程实录。"] },
  },
};
result.packages.rolePackage = createRolePackageManifest({ result, packageId, packageVersion, status: "ready" });

const referenceMigrations = [
  { oldId: "task:T-01", newIds: ["task:llmapp:define-scenario", "task:llmapp:design-solution"], disposition: "split", reason: "旧节点混合需求界定与方案决策两个不同交付边界。", claimIds: ["CLM-T01", "CLM-T02", "CLM-T03"] },
  { oldId: "task:T-02", newIds: ["task:llmapp:build-rag"], disposition: "renamed", reason: "保留RAG工作对象，补充知识版本、权限、维护与检索评价边界。", claimIds: ["CLM-T05", "CLM-T06"] },
  { oldId: "task:T-03", newIds: ["task:llmapp:build-agent-integration"], disposition: "renamed", reason: "保留Agent与工具集成，去除把多Agent当作普遍核心的暗示。", claimIds: ["CLM-T07", "CLM-T08", "CLM-D03"] },
  { oldId: "task:T-04", newIds: ["task:llmapp:control-model-behavior"], disposition: "broadened", reason: "从Prompt扩展到上下文、结构化输出、模型路由和行为测试。", claimIds: ["CLM-T09", "CLM-T10"] },
  { oldId: "task:T-05", newIds: ["knowledge:llmapp:peft-lora-conditional", "skill:llmapp:apply-peft-lora-conditional"], disposition: "demoted_to_conditional_learning", reason: "微调有正式和部分岗位支持，但不是跨企业普遍核心任务。", claimIds: ["CLM-D01"] },
  { oldId: "task:T-06", newIds: ["task:llmapp:evaluate-quality-safety"], disposition: "renamed", reason: "保留独立评测任务，补齐安全、分层评价、回归与发布判断。", claimIds: ["CLM-T11", "CLM-T12"] },
  { oldId: "task:T-07", newIds: ["task:llmapp:release-service", "task:llmapp:operate-improve"], disposition: "split_and_narrowed", reason: "应用服务发布属于核心；组织级推理平台与深度框架优化归入条件职责或相邻岗位。", claimIds: ["CLM-T13", "CLM-T14", "CLM-D02"] },
  { oldId: "task:T-08", newIds: ["task:llmapp:operate-improve"], disposition: "renamed", reason: "以坏例、根因、修复、回归和发布/回滚定义完整完成边界。", claimIds: ["CLM-T14", "CLM-T15"] },
  { oldId: "task:T-09", newIds: ["task:llmapp:design-solution", "task:llmapp:operate-improve"], disposition: "embedded_activity", reason: "技术跟踪没有独立稳定交付边界，只有进入方案或改进决策时才形成岗位价值。", claimIds: ["CLM-D04"] },
  { oldId: "task:T-10", newIds: ["task:llmapp:release-service", "task:llmapp:operate-improve", "skill:llmapp:write-runbooks-decisions"], disposition: "embedded_lifecycle_activity", reason: "文档、培训与支持附着于交付、运行和知识转移，不独立定义岗位任务。", claimIds: ["CLM-T17", "CLM-D05"] },
];

const compiled = await compileStaticRolePackage({ result, packageId, packageVersion, visibility: "public", evidencePolicy: "full", sourceProjectVersionId: "legacy:role-package:llm-app-engineer@1.1.0", referenceMigrations });
if (!compiled.validation.valid) throw new Error(`Golden package validation failed:\n${compiled.validation.hardErrors.join("\n")}`);

const expectedFiles = new Map<string, string>([["manifest.json", JSON.stringify(compiled.bundle.manifest)], ...Object.entries(compiled.bundle.components)]);
if (process.argv.includes("--check")) {
  const mismatches: string[] = [];
  for (const [relative, expected] of expectedFiles) {
    const actual = await readFile(path.join(outputRoot, relative), "utf8").catch(() => "");
    if (actual !== expected) mismatches.push(relative);
  }
  if (mismatches.length) throw new Error(`Generated package differs: ${mismatches.join(", ")}`);
  console.log(JSON.stringify({ ok: true, mode: "check", rootHash: compiled.bundle.manifest.rootHash, stats: compiled.validation.stats }, null, 2));
} else {
  await mkdir(outputRoot, { recursive: true });
  for (const [relative, content] of expectedFiles) {
    const target = path.join(outputRoot, relative);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, content, "utf8");
  }
  console.log(JSON.stringify({ ok: true, outputRoot, rootHash: compiled.bundle.manifest.rootHash, stats: compiled.validation.stats }, null, 2));
}
