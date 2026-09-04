import generatedData from "./generated-data.json";
import { RoleToolError } from "./errors";
import type {
  EvidenceSummary,
  NodeReference,
  ObjectUnit,
  RoleEdge,
  RoleNode,
  RolePackageData,
  RoleToolCall,
  RoleToolName,
  SourceRecord,
  ToolCitation,
  ToolCoverage,
  ToolEnvelope,
  ToolWarning,
  WorkProcessNode,
  WorkProcessRelation,
  WorkProcessScenario,
} from "./types";

const data = generatedData as unknown as RolePackageData;
const MAX_IDS = 25;
const MAX_TOP_K = 20;
const MAX_GRAPH_DEPTH = 2;
const MAX_PATH_DEPTH = 4;
const MAX_CONTEXT_CHARS = 12_000;

type RuntimeIndexes = {
  objects: Map<string, ObjectUnit>;
  nodes: Map<string, RoleNode>;
  edges: Map<string, RoleEdge>;
  sources: Map<string, SourceRecord>;
  aliases: Map<string, string[]>;
  outgoing: Map<string, RoleEdge[]>;
  incoming: Map<string, RoleEdge[]>;
  processScenarios: Map<string, WorkProcessScenario>;
  processNodes: Map<string, WorkProcessNode>;
  processRelations: Map<string, WorkProcessRelation>;
  processOutgoing: Map<string, WorkProcessRelation[]>;
  processIncoming: Map<string, WorkProcessRelation[]>;
  taskScenarios: Map<string, string[]>;
  processAliases: Map<string, string[]>;
};

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function fingerprint(value: unknown) {
  const input = stable(value);
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `call_${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function normalize(text: string) {
  return text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
}

function tokenize(text: string) {
  const normalized = normalize(text);
  const tokens = new Set<string>();
  for (const word of normalized.match(/[a-z0-9][a-z0-9._:+-]*/g) || []) {
    tokens.add(word);
  }
  for (const sequence of normalized.match(/[\u3400-\u9fff]+/g) || []) {
    if (sequence.length <= 4) tokens.add(sequence);
    for (const char of sequence) tokens.add(char);
    for (let index = 0; index < sequence.length - 1; index += 1) tokens.add(sequence.slice(index, index + 2));
  }
  return [...tokens];
}

function compact(value: unknown, depth = 0): unknown {
  if (value == null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") return value.length > 720 ? `${value.slice(0, 717)}…` : value;
  if (Array.isArray(value)) return value.slice(0, depth === 0 ? 8 : 5).map((item) => compact(item, depth + 1));
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, 18).map(([key, item]) => [key, compact(item, depth + 1)]));
  }
  return String(value);
}

function getPath(payload: Record<string, unknown>, path: string): unknown {
  const normalizedPath = path.replace(/^\$\.?/, "").replace(/^payload\.?/, "");
  if (!normalizedPath) return payload;
  return normalizedPath.split(".").reduce<unknown>((current, key) => {
    if (current && typeof current === "object" && key in (current as Record<string, unknown>)) {
      return (current as Record<string, unknown>)[key];
    }
    return undefined;
  }, payload);
}

function evidenceOf(targetId: string, indexes: RuntimeIndexes): EvidenceSummary {
  return indexes.nodes.get(targetId)?.evidence_summary
    || indexes.edges.get(targetId)?.evidence_summary
    || data.retrieval.find((unit) => unit.target_id === targetId)?.evidence_profile
    || {};
}

function isProcessTarget(targetId: string, indexes: RuntimeIndexes) {
  return indexes.processScenarios.has(targetId) || indexes.processNodes.has(targetId) || indexes.processRelations.has(targetId);
}

function labelOf(targetId: string, indexes: RuntimeIndexes) {
  const object = indexes.objects.get(targetId);
  return indexes.nodes.get(targetId)?.label
    || indexes.edges.get(targetId)?.type
    || indexes.processScenarios.get(targetId)?.title
    || indexes.processNodes.get(targetId)?.label
    || indexes.processRelations.get(targetId)?.type
    || String(object?.payload.title || object?.payload.label || object?.payload.name || targetId);
}

function temporalStatus(summary: EvidenceSummary) {
  const future = summary.temporal_status_counts?.future_of_snapshot || 0;
  return future > 0 ? "mixed_or_future" : "within_snapshot";
}

function citationFor(targetId: string, indexes: RuntimeIndexes, fieldPath?: string): ToolCitation {
  if (isProcessTarget(targetId, indexes)) {
    const scenario = indexes.processScenarios.get(targetId);
    const node = indexes.processNodes.get(targetId);
    const relation = indexes.processRelations.get(targetId);
    const scenarioForNode = node ? indexes.processScenarios.get(node.scenario_id) : undefined;
    const binding = scenario?.evidence_binding || node?.evidence_binding || relation?.evidence_binding;
    const sourceIds = [...new Set(binding?.source_refs || [])];
    return {
      artifactKind: "work_process",
      packageId: data.workProcessManifest.package_id,
      packageVersion: data.workProcessManifest.package_version,
      snapshotId: data.workProcessManifest.snapshot_id,
      targetId,
      label: labelOf(targetId, indexes),
      fieldPath,
      sourceIds,
      sourceTitles: sourceIds.map((id) => indexes.sources.get(id)?.title || id),
      confidence: binding?.confidence || 0,
      lifecycle: scenario?.lifecycle || node?.lifecycle || relation?.lifecycle || "candidate",
      temporalStatus: binding?.as_of && binding.as_of > data.workProcessManifest.snapshot_as_of ? "mixed_or_future" : "within_snapshot",
      knowledgeState: scenario?.knowledge_state || scenarioForNode?.knowledge_state,
    };
  }
  const object = indexes.objects.get(targetId);
  const summary = evidenceOf(targetId, indexes);
  const sourceIds = [...new Set([
    ...(summary.source_refs || []),
    ...(object?.related_ids || []).filter((id) => id.startsWith("SRC-")),
  ])];
  const segmentId = (object?.related_ids || []).find((id) => id.startsWith("segment:"));
  return {
    artifactKind: "role_semantic",
    packageId: data.manifest.package_id,
    packageVersion: data.manifest.package_version,
    snapshotId: data.manifest.snapshot_id,
    targetId,
    label: labelOf(targetId, indexes),
    fieldPath,
    bindingId: object?.binding_refs?.[0] || summary.binding_refs?.[0],
    segmentId,
    sourceIds,
    sourceTitles: sourceIds.map((id) => indexes.sources.get(id)?.title || id),
    confidence: summary.max_confidence || 0,
    lifecycle: object?.lifecycle || indexes.nodes.get(targetId)?.lifecycle || indexes.edges.get(targetId)?.lifecycle || "candidate",
    temporalStatus: temporalStatus(summary),
  };
}

function coverage(requested: number, returned: number, reason?: string): ToolCoverage {
  const omitted = Math.max(0, requested - returned);
  return { complete: omitted === 0, requested, returned, omitted, partial: omitted > 0, reason };
}

function makeContext(value: unknown) {
  const text = JSON.stringify(compact(value));
  return text.length <= MAX_CONTEXT_CHARS ? text : `${text.slice(0, MAX_CONTEXT_CHARS - 1)}…`;
}

function warningsFor(citations: ToolCitation[]): ToolWarning[] {
  const warnings: ToolWarning[] = [];
  for (const citation of citations) {
    if (citation.lifecycle !== "accepted") warnings.push({ code: "CANDIDATE_CONTENT", message: "该对象尚未进入 accepted 生命周期。", targetId: citation.targetId });
    if (citation.temporalStatus !== "within_snapshot") warnings.push({ code: "TEMPORAL_SCOPE", message: "证据含快照时点之后的材料，回答必须单列。", targetId: citation.targetId });
    if (citation.sourceIds.length === 0) warnings.push({ code: "NO_DIRECT_SOURCE", message: "该对象没有可下钻的直接来源。", targetId: citation.targetId });
    if (citation.knowledgeState === "inferred_pattern") warnings.push({ code: "INFERRED_PROCESS", message: "该事理节点是归纳工作模式，不得表述为真实工作记录。", targetId: citation.targetId });
  }
  return warnings;
}

function buildIndexes(): RuntimeIndexes {
  const objects = new Map(data.objectIndex.map((item) => [item.target_id, item]));
  const nodes = new Map(data.graph.nodes.map((item) => [item.id, item]));
  const edges = new Map(data.graph.edges.map((item) => [item.id, item]));
  const sources = new Map(data.sources.sources.map((item) => [item.id, item]));
  const outgoing = new Map<string, RoleEdge[]>();
  const incoming = new Map<string, RoleEdge[]>();
  for (const edge of data.graph.edges) {
    outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge]);
    incoming.set(edge.target, [...(incoming.get(edge.target) || []), edge]);
  }
  const aliases = new Map<string, string[]>();
  for (const node of data.graph.nodes) {
    const values = [node.id, node.label, ...((node.data.aliases as string[] | undefined) || [])];
    for (const value of values) aliases.set(normalize(value), [...new Set([...(aliases.get(normalize(value)) || []), node.id])]);
  }
  for (const unit of data.retrieval) {
    for (const value of [unit.target_id, unit.title, ...(unit.aliases || [])]) {
      aliases.set(normalize(value), [...new Set([...(aliases.get(normalize(value)) || []), unit.target_id])]);
    }
  }
  const processScenarios = new Map(data.workProcess.scenarios.map((item) => [item.id, item]));
  const processNodes = new Map(data.workProcess.nodes.map((item) => [item.id, item]));
  const processRelations = new Map(data.workProcess.relations.map((item) => [item.id, item]));
  const processOutgoing = new Map<string, WorkProcessRelation[]>();
  const processIncoming = new Map<string, WorkProcessRelation[]>();
  for (const relation of data.workProcess.relations) {
    processOutgoing.set(relation.source, [...(processOutgoing.get(relation.source) || []), relation]);
    processIncoming.set(relation.target, [...(processIncoming.get(relation.target) || []), relation]);
  }
  const taskScenarios = new Map<string, string[]>();
  const processAliases = new Map<string, string[]>();
  for (const scenario of data.workProcess.scenarios) {
    for (const taskId of scenario.task_refs) taskScenarios.set(taskId, [...new Set([...(taskScenarios.get(taskId) || []), scenario.id])]);
    for (const value of [scenario.id, scenario.title]) processAliases.set(normalize(value), [...new Set([...(processAliases.get(normalize(value)) || []), scenario.id])]);
  }
  for (const node of data.workProcess.nodes) {
    for (const value of [node.id, node.label]) processAliases.set(normalize(value), [...new Set([...(processAliases.get(normalize(value)) || []), node.id])]);
  }
  return { objects, nodes, edges, sources, aliases, outgoing, incoming, processScenarios, processNodes, processRelations, processOutgoing, processIncoming, taskScenarios, processAliases };
}

export class RolePackageRuntime {
  readonly package = data;
  private readonly indexes = buildIndexes();
  private readonly runCache = new Map<string, ToolEnvelope>();

  constructor() {
    if (!data.validation.valid || !data.validation.publishable) {
      throw new RoleToolError("PACKAGE_NOT_PUBLISHABLE", "岗位包未通过发布校验。", "运行协议校验器并修复所有错误。 ");
    }
    if (data.graph.metadata.snapshot_id !== data.manifest.snapshot_id) {
      throw new RoleToolError("SNAPSHOT_MISMATCH", "图谱与清单的 snapshot_id 不一致。 ");
    }
  }

  get referenceBase(): Omit<NodeReference, "targetId"> {
    return {
      packageId: data.manifest.package_id,
      packageVersion: data.manifest.package_version,
      snapshotId: data.manifest.snapshot_id,
    };
  }

  get processReferenceBase(): Omit<NodeReference, "targetId"> {
    return {
      packageId: data.workProcessManifest.package_id,
      packageVersion: data.workProcessManifest.package_version,
      snapshotId: data.workProcessManifest.snapshot_id,
    };
  }

  private assertReference(reference: NodeReference) {
    if (!reference || typeof reference.targetId !== "string") throw new RoleToolError("INVALID_REFERENCE", "节点引用缺少 targetId。 ");
    const semanticMatch = reference.packageId === data.manifest.package_id && reference.packageVersion === data.manifest.package_version && reference.snapshotId === data.manifest.snapshot_id;
    const processMatch = reference.packageId === data.workProcessManifest.package_id && reference.packageVersion === data.workProcessManifest.package_version && reference.snapshotId === data.workProcessManifest.snapshot_id;
    if (!semanticMatch && !processMatch) {
      throw new RoleToolError("SNAPSHOT_MISMATCH", "节点引用不属于当前固定岗位快照。", "重新从当前图谱选择节点。 ");
    }
    if (semanticMatch && isProcessTarget(reference.targetId, this.indexes)) throw new RoleToolError("SNAPSHOT_MISMATCH", "事理节点使用了语义岗位包引用。 ");
    if (processMatch && !isProcessTarget(reference.targetId, this.indexes)) throw new RoleToolError("SNAPSHOT_MISMATCH", "语义节点使用了事理过程包引用。 ");
  }

  resolveTarget(input: string | NodeReference): string {
    if (typeof input !== "string") {
      this.assertReference(input);
      if (!this.indexes.objects.has(input.targetId) && !isProcessTarget(input.targetId, this.indexes)) throw new RoleToolError("OBJECT_NOT_FOUND", `对象不存在：${input.targetId}`);
      return input.targetId;
    }
    if (this.indexes.objects.has(input) || isProcessTarget(input, this.indexes)) return input;
    const matches = [...new Set([...(this.indexes.aliases.get(normalize(input)) || []), ...(this.indexes.processAliases.get(normalize(input)) || [])])];
    if (matches.length === 0) throw new RoleToolError("OBJECT_NOT_FOUND", `对象或别名不存在：${input}`);
    if (matches.length > 1) throw new RoleToolError("AMBIGUOUS_ALIAS", `别名对应多个对象：${matches.join("、")}`, "改用精确 target_id。 ");
    return matches[0];
  }

  async execute(call: RoleToolCall, runId = "standalone"): Promise<ToolEnvelope> {
    const startedAt = Date.now();
    const callFingerprint = fingerprint({ name: call.name, args: call.args, packageVersion: data.manifest.package_version, snapshotId: data.manifest.snapshot_id });
    const cacheKey = `${runId}:${callFingerprint}`;
    const cached = this.runCache.get(cacheKey);
    if (cached) {
      return {
        ...cached,
        diagnostics: { ...cached.diagnostics, deduplicated: true, durationMs: Date.now() - startedAt, cache: "run" },
        warnings: [...cached.warnings, { code: "DUPLICATE_CALL", message: "同一运行中的相同工具调用已复用先前结果。" }],
      };
    }

    try {
      const raw = await this.dispatch(call.name, call.args);
      const result: ToolEnvelope = {
        ok: true,
        tool: call.name,
        ...raw,
        diagnostics: {
          callFingerprint,
          deduplicated: false,
          durationMs: Date.now() - startedAt,
          packageVersion: data.manifest.package_version,
          snapshotId: data.manifest.snapshot_id,
          cache: "miss",
          companionVersions: { workProcess: data.workProcessManifest.package_version },
        },
      };
      this.runCache.set(cacheKey, result);
      return result;
    } catch (error) {
      const known = error instanceof RoleToolError ? error : new RoleToolError("INTERNAL_ERROR", "工具执行失败。 ");
      return {
        ok: false,
        tool: call.name,
        data: null,
        context: "",
        citations: [],
        coverage: coverage(1, 0, known.code),
        warnings: [],
        diagnostics: {
          callFingerprint,
          deduplicated: false,
          durationMs: Date.now() - startedAt,
          packageVersion: data.manifest.package_version,
          snapshotId: data.manifest.snapshot_id,
          cache: "miss",
          companionVersions: { workProcess: data.workProcessManifest.package_version },
        },
        error: {
          code: known.code,
          message: known.message,
          retryable: known.retryable,
          whoFixes: known.whoFixes,
          suggestedAction: known.suggestedAction,
        },
      };
    }
  }

  private async dispatch(name: RoleToolName, args: Record<string, unknown>) {
    switch (name) {
      case "get_role_overview": return this.roleOverview();
      case "get_role_package_status": return this.packageStatus();
      case "read_role_objects": return this.readObjects(args);
      case "resolve_role_targets": return this.resolveTargets(args);
      case "search_role_knowledge": return this.searchKnowledge(args);
      case "query_role_graph": return this.queryGraph(args);
      case "trace_role_paths": return this.traceRolePaths(args);
      case "read_task_bundle": return this.readTaskBundle(args);
      case "project_role_view": return this.projectView(args);
      case "compare_role_objects": return this.compareObjects(args);
      case "inspect_role_evidence": return this.inspectEvidence(args);
      case "read_work_scenarios": return this.readWorkScenarios(args);
      case "trace_work_process": return this.traceWorkProcess(args);
      case "inspect_role_process_alignment": return this.inspectRoleProcessAlignment(args);
      case "audit_role_package": return this.auditPackage(args);
      default: throw new RoleToolError("INVALID_REFERENCE", `未知工具：${name}`);
    }
  }

  private roleOverview() {
    const byType = Object.fromEntries([...new Set(data.graph.nodes.map((node) => node.type))].sort().map((type) => [type, data.graph.nodes.filter((node) => node.type === type).length]));
    const semanticNodes = (types: string[], limit: number) => data.graph.nodes
      .filter((node) => types.includes(node.type))
      .slice(0, limit)
      .map((node) => ({ id: node.id, type: node.type, label: node.label, summary: node.summary, lifecycle: node.lifecycle }));
    const processCoverage = data.workProcess.alignment.reduce<Record<string, number>>((counts, item) => {
      counts[item.status] = (counts[item.status] || 0) + 1;
      return counts;
    }, {});
    const result = {
      role: semanticNodes(["market_role"], 1)[0],
      snapshot: {
        compositeVersion: "1.2.0",
        semantic: { packageId: data.manifest.package_id, version: data.manifest.package_version, asOf: data.manifest.snapshot_as_of },
        workProcess: { packageId: data.workProcessManifest.package_id, version: data.workProcessManifest.package_version, asOf: data.workProcessManifest.snapshot_as_of, status: data.workProcessManifest.status },
      },
      semanticCounts: byType,
      coreTasks: semanticNodes(["task"], 12),
      capabilities: semanticNodes(["capability"], 8),
      knowledgeSkills: semanticNodes(["knowledge_skill"], 16),
      workScenarios: data.workProcess.scenarios.map((scenario) => ({
        id: scenario.id,
        title: scenario.title,
        summary: scenario.summary,
        family: scenario.scenario_family,
        taskRefs: scenario.task_refs,
        knowledgeState: scenario.knowledge_state,
        lifecycle: scenario.lifecycle,
      })),
      processCoverage,
      interpretation: "语义图谱回答岗位包含什么；事理森林回答工作如何沿事件、交接、分支和产物展开。事理包当前是候选归纳模式，不是真实工作日志。",
    };
    const targetIds = [...semanticNodes(["market_role", "task", "capability"], 20).map((node) => node.id), ...data.workProcess.scenarios.map((scenario) => scenario.id)];
    const citations = targetIds.slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(targetIds.length, citations.length, targetIds.length > MAX_IDS ? "citation_limit" : undefined), warnings: warningsFor(citations) };
  }

  private packageStatus() {
    const result = {
      packageId: data.manifest.package_id,
      packageVersion: data.manifest.package_version,
      protocolVersion: data.manifest.protocol_version,
      snapshotId: data.manifest.snapshot_id,
      snapshotAsOf: data.manifest.snapshot_as_of,
      manifestStatus: data.manifest.status,
      valid: data.validation.valid,
      publishable: data.validation.publishable,
      validatedAt: data.validation.validated_at,
      stats: data.validation.stats,
      pinnedHashes: {
        graph: data.manifest.hashes["graph.json"],
        objectIndex: data.manifest.hashes["object-index.jsonl"],
        retrieval: data.manifest.hashes["retrieval.jsonl"],
      },
      workProcess: {
        packageId: data.workProcessManifest.package_id,
        packageVersion: data.workProcessManifest.package_version,
        protocolVersion: data.workProcessManifest.protocol_version,
        snapshotId: data.workProcessManifest.snapshot_id,
        snapshotAsOf: data.workProcessManifest.snapshot_as_of,
        status: data.workProcessManifest.status,
        valid: data.workProcessValidation.valid,
        publishable: data.workProcessValidation.publishable,
        stats: data.workProcessValidation.stats,
        pinnedHashes: data.workProcessManifest.hashes,
      },
      compositeSnapshotVersion: "1.2.0",
    };
    const validationWarnings = [...data.validation.warnings, ...data.workProcessValidation.warnings];
    return { data: result, context: makeContext(result), citations: [], coverage: coverage(2, 2), warnings: validationWarnings.map((message) => ({ code: "VALIDATION_WARNING", message })) };
  }

  private resolveTargets(args: Record<string, unknown>) {
    const query = typeof args.query === "string" ? args.query.trim() : "";
    if (!query) throw new RoleToolError("INVALID_REFERENCE", "resolve_role_targets 的 query 不能为空。 ");
    const limit = Math.min(12, Math.max(1, Number(args.limit) || 6));
    const requestedKinds = new Set(Array.isArray(args.kinds) ? args.kinds.filter((value): value is string => typeof value === "string") : []);
    const queryTokens = tokenize(query);
    const candidates = [
      ...data.graph.nodes.map((node) => ({ id: node.id, label: node.label, summary: node.summary, kind: node.type, artifactKind: "role_semantic" as const, lifecycle: node.lifecycle })),
      ...data.workProcess.scenarios.map((scenario) => ({ id: scenario.id, label: scenario.title, summary: scenario.summary, kind: "scenario", artifactKind: "work_process" as const, lifecycle: scenario.lifecycle })),
      ...data.workProcess.nodes.map((node) => ({ id: node.id, label: node.label, summary: node.summary, kind: node.kind, artifactKind: "work_process" as const, lifecycle: node.lifecycle })),
    ].filter((item) => requestedKinds.size === 0 || requestedKinds.has(item.kind));
    const normalizedQuery = normalize(query);
    const matches = candidates.map((item) => {
      const text = normalize(`${item.id} ${item.label} ${item.summary}`);
      let score = queryTokens.reduce((sum, token) => sum + (text.includes(token) ? (token.length > 1 ? 2 : 0.25) : 0), 0);
      if (normalize(item.id) === normalizedQuery || normalize(item.label) === normalizedQuery) score += 20;
      else if (normalize(item.label).includes(normalizedQuery)) score += 7;
      return { ...item, score: Number(score.toFixed(2)) };
    }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score || a.label.localeCompare(b.label)).slice(0, limit);
    const citations = matches.map((item) => citationFor(item.id, this.indexes));
    const result = { query, matches, ambiguous: matches.length > 1 && matches[0].score - matches[1].score < 2, guidance: matches.length ? "将精确 id 交给读取或路径工具；若 ambiguous=true，先依据类型和摘要消歧。" : "没有候选；改用 search_role_knowledge 做全文检索。" };
    return { data: result, context: makeContext(result), citations, coverage: coverage(candidates.length, matches.length, matches.length === limit ? "top_k" : undefined), warnings: matches.length ? warningsFor(citations) : [{ code: "ZERO_RESULTS", message: "未解析到候选对象。" }] };
  }

  private readObjects(args: Record<string, unknown>) {
    const requested = Array.isArray(args.targets) ? args.targets : [];
    if (requested.length === 0) throw new RoleToolError("INVALID_REFERENCE", "read_role_objects 至少需要一个 target。 ");
    if (requested.length > MAX_IDS) throw new RoleToolError("RESULT_LIMIT_EXCEEDED", `单次最多读取 ${MAX_IDS} 个对象。`);
    const fields = Array.isArray(args.fields) ? args.fields.filter((item): item is string => typeof item === "string").slice(0, 20) : [];
    const oneHop = Boolean(args.oneHop);
    const targetIds: string[] = [];
    const missing: string[] = [];
    for (const input of requested) {
      try {
        targetIds.push(this.resolveTarget(input as string | NodeReference));
      } catch (error) {
        if (error instanceof RoleToolError && error.code === "OBJECT_NOT_FOUND") missing.push(typeof input === "string" ? input : (input as NodeReference).targetId);
        else throw error;
      }
    }
    if (oneHop) {
      for (const targetId of [...targetIds]) {
        const processRelated = [
          ...(this.indexes.processOutgoing.get(targetId) || []).flatMap((relation) => [relation.id, relation.target]),
          ...(this.indexes.processIncoming.get(targetId) || []).flatMap((relation) => [relation.id, relation.source]),
          ...(this.indexes.processScenarios.get(targetId)?.event_refs || []),
        ];
        for (const relatedId of [...(this.indexes.objects.get(targetId)?.related_ids || []), ...processRelated]) {
          if ((this.indexes.objects.has(relatedId) || isProcessTarget(relatedId, this.indexes)) && targetIds.length < MAX_IDS && !targetIds.includes(relatedId)) targetIds.push(relatedId);
        }
      }
    }
    const objects = targetIds.map((targetId) => {
      const object = this.indexes.objects.get(targetId);
      if (!object) {
        const scenario = this.indexes.processScenarios.get(targetId);
        const node = this.indexes.processNodes.get(targetId);
        const relation = this.indexes.processRelations.get(targetId);
        const payload = (scenario || node || relation) as unknown as Record<string, unknown>;
        const selectedPayload = fields.length > 0
          ? Object.fromEntries(fields.map((field) => [field, getPath(payload, field)]).filter(([, value]) => value !== undefined))
          : payload;
        const relatedIds = [
          ...(scenario?.event_refs || []),
          ...(node ? [node.scenario_id, ...(node.task_refs || []), ...(node.artifact_refs || []), ...(node.actor_refs || [])] : []),
          ...(relation ? [relation.source, relation.target] : []),
        ];
        return {
          targetId,
          objectType: scenario ? "work_process_scenario" : node ? `work_process_${node.kind}` : "work_process_relation",
          lifecycle: scenario?.lifecycle || node?.lifecycle || relation?.lifecycle || "candidate",
          payload: compact(selectedPayload),
          fieldStates: [{ field_path: "$", state: scenario?.knowledge_state || "inferred_pattern" }],
          relatedIds: [...new Set(relatedIds)].slice(0, 30),
        };
      }
      const selectedPayload = fields.length > 0
        ? Object.fromEntries(fields.map((field) => [field, getPath(object.payload, field)]).filter(([, value]) => value !== undefined))
        : object.payload;
      return {
        targetId,
        objectType: object.object_type,
        lifecycle: object.lifecycle,
        payload: compact(selectedPayload),
        fieldStates: fields.length > 0
          ? object.field_states.filter((state) => {
            const statePaths = state.field_paths || (state.field_path ? [state.field_path] : []);
            return fields.some((field) => statePaths.some((statePath) => statePath.includes(field)));
          })
          : object.field_states,
        relatedIds: object.related_ids.slice(0, 30),
      };
    });
    const citations = targetIds.map((targetId) => citationFor(targetId, this.indexes, fields[0]));
    const warnings = [...warningsFor(citations), ...missing.map((targetId) => ({ code: "OBJECT_NOT_FOUND", message: "批量读取中有对象未找到。", targetId }))];
    return { data: { objects, missing }, context: makeContext(objects), citations, coverage: coverage(requested.length, requested.length - missing.length, missing.length ? "partial_batch_success" : undefined), warnings };
  }

  private searchKnowledge(args: Record<string, unknown>) {
    const query = typeof args.query === "string" ? args.query.trim() : "";
    if (!query) throw new RoleToolError("INVALID_REFERENCE", "搜索 query 不能为空。 ");
    const topK = Math.min(MAX_TOP_K, Math.max(1, Number(args.topK) || 8));
    const includeCandidate = args.includeCandidate !== false;
    const unitTypes = new Set(Array.isArray(args.unitTypes) ? args.unitTypes.filter((item): item is string => typeof item === "string") : []);
    const contexts = new Set(Array.isArray(args.contexts) ? args.contexts.filter((item): item is string => typeof item === "string") : []);
    const selectedIds = Array.isArray(args.selectedIds) ? args.selectedIds.filter((item): item is string => typeof item === "string").slice(0, 8) : [];
    const queryTokens = tokenize(query);
    const requiredIdentifiers = queryTokens.filter((token) => /^[a-z0-9][a-z0-9._:+-]{3,}$/.test(token));
    const documents = data.retrieval.filter((unit) => {
      if (!includeCandidate && unit.lifecycle !== "accepted") return false;
      if (unitTypes.size > 0 && !unitTypes.has(unit.unit_type)) return false;
      if (contexts.size > 0 && !contexts.has(String(unit.facets.context || ""))) return false;
      return true;
    });
    const docTokens = documents.map((unit) => {
      const corpus = [
        unit.target_id,
        unit.title,
        unit.text,
        ...(unit.aliases || []),
        JSON.stringify(unit.facets),
      ].join(" ");
      return tokenize(corpus);
    });
    const dfs = new Map<string, number>();
    for (const tokens of docTokens) for (const token of new Set(tokens)) dfs.set(token, (dfs.get(token) || 0) + 1);
    const averageLength = docTokens.reduce((sum, tokens) => sum + tokens.length, 0) / Math.max(1, docTokens.length);
    const normalizedQuery = normalize(query);
    const scored = documents.map((unit, index) => {
      const tokens = docTokens[index];
      const tf = new Map<string, number>();
      for (const token of tokens) tf.set(token, (tf.get(token) || 0) + 1);
      if (requiredIdentifiers.length > 0 && !requiredIdentifiers.some((token) => tf.has(token))) return { unit, score: 0 };
      let score = 0;
      for (const token of queryTokens) {
        const frequency = tf.get(token) || 0;
        if (!frequency) continue;
        const df = dfs.get(token) || 0;
        const idf = Math.log(1 + (documents.length - df + 0.5) / (df + 0.5));
        const denominator = frequency + 1.2 * (0.25 + 0.75 * tokens.length / Math.max(1, averageLength));
        score += idf * ((frequency * 2.2) / denominator);
      }
      const exactValues = [unit.target_id, unit.title, ...(unit.aliases || [])].map(normalize);
      if (exactValues.includes(normalizedQuery)) score += 18;
      if (normalize(unit.text).includes(normalizedQuery)) score += 5;
      if (selectedIds.some((id) => unit.target_id === id || this.indexes.objects.get(id)?.related_ids.includes(unit.target_id))) score += 2.5;
      score += (unit.priority || 0) / 100;
      score += (unit.evidence_profile.max_confidence || 0) * 1.5;
      if (unit.lifecycle === "candidate") score *= 0.86;
      return { unit, score };
    }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score || b.unit.priority - a.unit.priority);
    const selected = scored.slice(0, topK).map(({ unit, score }) => ({
      targetId: unit.target_id,
      unitType: unit.unit_type,
      title: unit.title,
      text: unit.text,
      lifecycle: unit.lifecycle,
      score: Number(score.toFixed(4)),
      facets: unit.facets,
      evidence: unit.evidence_profile,
    }));
    const citations = selected.map((item) => citationFor(item.targetId, this.indexes));
    const filteredCount = data.retrieval.length - documents.length;
    const warnings = warningsFor(citations);
    if (selected.length === 0) warnings.push({ code: "ZERO_RESULTS", message: "已完整搜索索引，但没有达到相关性阈值的结果。" });
    return {
      data: { query, results: selected, searched: documents.length, filtered: filteredCount },
      context: makeContext(selected),
      citations,
      coverage: { complete: true, requested: documents.length, returned: selected.length, omitted: Math.max(0, scored.length - selected.length), partial: scored.length > selected.length, reason: scored.length > selected.length ? "top_k" : undefined },
      warnings,
    };
  }

  private queryGraph(args: Record<string, unknown>) {
    const startInput = args.start as string | NodeReference;
    const start = this.resolveTarget(startInput);
    const mode = args.mode === "path" ? "path" : "neighbors";
    const depth = Math.min(MAX_GRAPH_DEPTH, Math.max(1, Number(args.depth) || 1));
    const direction = args.direction === "in" || args.direction === "out" ? args.direction : "both";
    const relationTypes = new Set(Array.isArray(args.relationTypes) ? args.relationTypes.filter((item): item is string => typeof item === "string") : []);
    const target = typeof args.target === "string" ? this.resolveTarget(args.target) : undefined;
    const edgeAllowed = (edge: RoleEdge) => relationTypes.size === 0 || relationTypes.has(edge.type);
    const queue: Array<{ id: string; level: number; path: string[]; edges: string[] }> = [{ id: start, level: 0, path: [start], edges: [] }];
    const visited = new Set([start]);
    const paths: Array<{ nodes: string[]; edges: string[] }> = [];
    const foundEdges = new Map<string, RoleEdge>();
    while (queue.length) {
      const current = queue.shift()!;
      if (current.level >= depth) continue;
      const candidates = [
        ...(direction !== "in" ? (this.indexes.outgoing.get(current.id) || []).map((edge) => ({ edge, next: edge.target })) : []),
        ...(direction !== "out" ? (this.indexes.incoming.get(current.id) || []).map((edge) => ({ edge, next: edge.source })) : []),
      ].filter(({ edge }) => edgeAllowed(edge));
      for (const { edge, next } of candidates) {
        foundEdges.set(edge.id, edge);
        const nextPath = [...current.path, next];
        const nextEdges = [...current.edges, edge.id];
        if (target && next === target) paths.push({ nodes: nextPath, edges: nextEdges });
        if (!visited.has(next)) {
          visited.add(next);
          queue.push({ id: next, level: current.level + 1, path: nextPath, edges: nextEdges });
        }
      }
    }
    if (mode === "path" && target && paths.length === 0) {
      return { data: { start, target, paths: [] }, context: "[]", citations: [], coverage: coverage(1, 0, `no_path_within_depth_${depth}`), warnings: [{ code: "NO_PATH", message: `在深度 ${depth} 内未找到路径。` }] };
    }
    const nodes = [...visited].map((id) => this.indexes.nodes.get(id)).filter((node): node is RoleNode => Boolean(node));
    const edges = [...foundEdges.values()];
    const citations = [...new Set([...nodes.map((node) => node.id), ...edges.map((edge) => edge.id)])].map((id) => citationFor(id, this.indexes));
    const result = mode === "path" ? { start, target, paths } : { start, depth, direction, nodes: nodes.map(compact), edges: edges.map(compact) };
    return { data: result, context: makeContext(result), citations, coverage: coverage(1, 1), warnings: warningsFor(citations) };
  }

  private traceRolePaths(args: Record<string, unknown>) {
    const start = this.resolveTarget(args.start as string | NodeReference);
    if (isProcessTarget(start, this.indexes)) throw new RoleToolError("INVALID_REFERENCE", "语义路径工具不接受事理节点，请使用 trace_work_process。 ");
    const end = args.end ? this.resolveTarget(args.end as string | NodeReference) : undefined;
    if (end && isProcessTarget(end, this.indexes)) throw new RoleToolError("INVALID_REFERENCE", "跨包关系请从任务包或事理过程工具读取。 ");
    const targetTypes = new Set(Array.isArray(args.targetTypes) ? args.targetTypes.filter((value): value is string => typeof value === "string") : []);
    const relationTypes = new Set(Array.isArray(args.relationTypes) ? args.relationTypes.filter((value): value is string => typeof value === "string") : []);
    const maxDepth = Math.min(MAX_PATH_DEPTH, Math.max(1, Number(args.maxDepth) || 3));
    const maxPaths = Math.min(12, Math.max(1, Number(args.maxPaths) || 6));
    const queue: Array<{ id: string; nodes: string[]; edges: string[] }> = [{ id: start, nodes: [start], edges: [] }];
    const paths: Array<{ nodes: string[]; edges: string[]; labels: string[] }> = [];
    while (queue.length && paths.length < maxPaths) {
      const current = queue.shift()!;
      if (current.edges.length >= maxDepth) continue;
      const adjacent = [
        ...(this.indexes.outgoing.get(current.id) || []).map((edge) => ({ edge, next: edge.target })),
        ...(this.indexes.incoming.get(current.id) || []).map((edge) => ({ edge, next: edge.source })),
      ].filter(({ edge }) => relationTypes.size === 0 || relationTypes.has(edge.type));
      for (const { edge, next } of adjacent) {
        if (current.nodes.includes(next)) continue;
        const nextNodes = [...current.nodes, next];
        const nextEdges = [...current.edges, edge.id];
        const nextNode = this.indexes.nodes.get(next);
        const reached = end ? next === end : Boolean(nextNode && targetTypes.size > 0 && targetTypes.has(nextNode.type));
        if (reached) paths.push({ nodes: nextNodes, edges: nextEdges, labels: nextNodes.map((id) => labelOf(id, this.indexes)) });
        if (!end || next !== end) queue.push({ id: next, nodes: nextNodes, edges: nextEdges });
        if (paths.length >= maxPaths) break;
      }
    }
    const ids = [...new Set(paths.flatMap((path) => [...path.nodes, ...path.edges]))];
    const citations = ids.slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    const result = { start, end, targetTypes: [...targetTypes], maxDepth, paths };
    return { data: result, context: makeContext(result), citations, coverage: coverage(1, paths.length > 0 ? 1 : 0, paths.length ? undefined : `no_path_within_depth_${maxDepth}`), warnings: paths.length ? warningsFor(citations) : [{ code: "NO_PATH", message: `在深度 ${maxDepth} 内未找到满足条件的语义路径。` }] };
  }

  private readTaskBundle(args: Record<string, unknown>) {
    const taskId = this.resolveTarget((args.task || args.target) as string | NodeReference);
    const taskNode = this.indexes.nodes.get(taskId);
    if (!taskNode || taskNode.type !== "task") throw new RoleToolError("INVALID_REFERENCE", "read_task_bundle 需要 task 节点。 ");
    const incidentEdges = [...(this.indexes.outgoing.get(taskId) || []), ...(this.indexes.incoming.get(taskId) || [])];
    const relatedIds = [...new Set(incidentEdges.map((edge) => edge.source === taskId ? edge.target : edge.source))];
    const related = relatedIds.map((id) => this.indexes.nodes.get(id)).filter((node): node is RoleNode => Boolean(node));
    const grouped = related.reduce<Record<string, Array<Record<string, unknown>>>>((groups, node) => {
      groups[node.type] = [...(groups[node.type] || []), { id: node.id, label: node.label, summary: node.summary, lifecycle: node.lifecycle }];
      return groups;
    }, {});
    const scenarioIds = this.indexes.taskScenarios.get(taskId) || [];
    const scenarios = scenarioIds.map((id) => this.indexes.processScenarios.get(id)).filter((item): item is WorkProcessScenario => Boolean(item));
    const events = data.workProcess.nodes.filter((node) => node.kind === "event" && node.task_refs?.includes(taskId)).map((node) => ({
      id: node.id,
      scenarioId: node.scenario_id,
      label: node.label,
      summary: node.summary,
      eventType: node.event_type,
      lane: node.lane,
      sequence: node.sequence_hint,
      artifactRefs: node.artifact_refs || [],
      knowledgeSkillRefs: node.knowledge_skill_refs || [],
      lifecycle: node.lifecycle,
    }));
    const alignment = data.workProcess.alignment.find((item) => item.semantic_target_id === taskId) || { semantic_target_id: taskId, scenario_refs: [], status: "gap", note: "事理包尚未登记该任务。" };
    const object = this.indexes.objects.get(taskId)!;
    const result = {
      task: { id: taskId, label: taskNode.label, summary: taskNode.summary, lifecycle: taskNode.lifecycle, payload: compact(object.payload) },
      semanticRelations: incidentEdges.map((edge) => ({ id: edge.id, type: edge.type, source: edge.source, target: edge.target })),
      relatedByType: grouped,
      processAlignment: alignment,
      scenarios: scenarios.map((scenario) => ({ id: scenario.id, title: scenario.title, summary: scenario.summary, knowledgeState: scenario.knowledge_state, lifecycle: scenario.lifecycle })),
      workEvents: events,
      interpretation: "任务是稳定语义单元；事件是任务在具体候选工作场景中的实例化位置，两者不可互相替代。",
    };
    const ids = [taskId, ...relatedIds, ...incidentEdges.map((edge) => edge.id), ...scenarioIds, ...events.map((event) => event.id)];
    const citations = [...new Set(ids)].slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(ids.length, citations.length, ids.length > MAX_IDS ? "citation_limit" : undefined), warnings: warningsFor(citations) };
  }

  private projectView(args: Record<string, unknown>) {
    const viewId = typeof args.viewId === "string" ? args.viewId : data.views.default_view;
    const view = data.views.views.find((item) => item.id === viewId);
    if (!view) throw new RoleToolError("OBJECT_NOT_FOUND", `视图不存在：${viewId}`);
    const focusId = typeof args.focusId === "string" ? this.resolveTarget(args.focusId) : undefined;
    let nodes = data.graph.nodes.filter((node) => view.included_types.includes(node.type));
    let edges = data.graph.edges.filter((edge) => view.included_relations.includes(edge.type));
    if (focusId) {
      const focusIds = new Set([focusId]);
      for (const edge of edges) if (edge.source === focusId || edge.target === focusId) { focusIds.add(edge.source); focusIds.add(edge.target); }
      nodes = nodes.filter((node) => focusIds.has(node.id));
      edges = edges.filter((edge) => focusIds.has(edge.source) && focusIds.has(edge.target));
    }
    const nodeIds = new Set(nodes.map((node) => node.id));
    edges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
    const result = { view: { id: view.id, label: view.label, purpose: view.purpose }, nodes: nodes.map(compact), edges: edges.map(compact) };
    const citations = nodes.slice(0, MAX_IDS).map((node) => citationFor(node.id, this.indexes));
    return { data: result, context: makeContext({ view: result.view, nodes: nodes.map((node) => ({ id: node.id, label: node.label, type: node.type, lifecycle: node.lifecycle })), edges: edges.map((edge) => ({ id: edge.id, type: edge.type, source: edge.source, target: edge.target })) }), citations, coverage: coverage(nodes.length, citations.length, nodes.length > MAX_IDS ? "citation_limit" : undefined), warnings: warningsFor(citations) };
  }

  private compareObjects(args: Record<string, unknown>) {
    const inputs = Array.isArray(args.targets) ? args.targets : [];
    if (inputs.length < 2 || inputs.length > 6) throw new RoleToolError("INVALID_REFERENCE", "比较需要 2—6 个对象。 ");
    const targetIds = inputs.map((input) => this.resolveTarget(input as string | NodeReference));
    const dimensions = Array.isArray(args.dimensions) ? args.dimensions.filter((item): item is string => typeof item === "string").slice(0, 12) : [];
    const defaultDimensions = ["summary", "responsibilities", "deliverables", "capability_refs", "knowledge_refs", "lifecycle", "evidence"];
    const selectedDimensions = dimensions.length ? dimensions : defaultDimensions;
    const rows = targetIds.map((targetId) => {
      const object = this.indexes.objects.get(targetId)!;
      const node = this.indexes.nodes.get(targetId);
      return {
        targetId,
        label: labelOf(targetId, this.indexes),
        objectType: object.object_type,
        values: Object.fromEntries(selectedDimensions.map((dimension) => {
          if (dimension === "summary") return [dimension, node?.summary || object.payload.summary || object.payload.description || ""];
          if (dimension === "lifecycle") return [dimension, object.lifecycle];
          if (dimension === "evidence") return [dimension, evidenceOf(targetId, this.indexes)];
          return [dimension, getPath(object.payload, dimension) ?? object.related_ids.filter((id) => id.toLowerCase().includes(dimension.replace(/_refs?$/, ""))).slice(0, 12)];
        })),
      };
    });
    const result = { dimensions: selectedDimensions, rows };
    const citations = targetIds.map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(inputs.length, rows.length), warnings: warningsFor(citations) };
  }

  private inspectEvidence(args: Record<string, unknown>) {
    const targetId = this.resolveTarget(args.target as string | NodeReference);
    const mode = args.mode === "sufficiency" || args.mode === "tension" ? args.mode : "trace";
    if (isProcessTarget(targetId, this.indexes)) {
      const scenario = this.indexes.processScenarios.get(targetId);
      const node = this.indexes.processNodes.get(targetId);
      const relation = this.indexes.processRelations.get(targetId);
      const binding = scenario?.evidence_binding || node?.evidence_binding || relation?.evidence_binding;
      if (!binding) throw new RoleToolError("EVIDENCE_UNAVAILABLE", `事理对象没有证据绑定：${targetId}`);
      const sources = binding.source_refs.map((id) => this.indexes.sources.get(id)).filter((item): item is SourceRecord => Boolean(item));
      const result = {
        targetId,
        artifactKind: "work_process",
        knowledgeState: scenario?.knowledge_state || (node ? this.indexes.processScenarios.get(node.scenario_id)?.knowledge_state : undefined),
        evidenceBinding: binding,
        sources: sources.map((source) => compact(source)),
        sufficientForRealEpisodeClaim: false,
        interpretation: "这些来源支持归纳岗位工作模式；没有 episode_id、发生时间和真实工作对象，因此不能证明某个组织实际按此流程工作。",
      };
      const citation = citationFor(targetId, this.indexes);
      return { data: result, context: makeContext(result), citations: [citation], coverage: coverage(binding.source_refs.length, sources.length, sources.length < binding.source_refs.length ? "missing_source_records" : undefined), warnings: warningsFor([citation]) };
    }
    const object = this.indexes.objects.get(targetId)!;
    const summary = evidenceOf(targetId, this.indexes);
    const sourceIds = [...new Set([...(summary.source_refs || []), ...object.related_ids.filter((id) => id.startsWith("SRC-"))])];
    const sources = sourceIds.map((id) => this.indexes.sources.get(id)).filter((item): item is SourceRecord => Boolean(item));
    const segments = sources.flatMap((source) => (source.segments || []).map((segment) => ({ ...segment, sourceId: source.id, sourceTitle: source.title })));
    if (sourceIds.length === 0) throw new RoleToolError("EVIDENCE_UNAVAILABLE", `对象没有直接证据：${targetId}`);
    let result: Record<string, unknown>;
    if (mode === "sufficiency") {
      result = {
        targetId,
        sourceCount: sources.length,
        capturedCount: sources.filter((source) => source.capture_status === "captured").length,
        segmentCount: segments.length,
        maxConfidence: summary.max_confidence || 0,
        lifecycle: object.lifecycle,
        sufficientForDirectClaim: sources.some((source) => source.claim_use === "primary" && source.capture_status === "captured"),
        weaknesses: [
          ...(segments.length === 0 ? ["缺少片段级证据"] : []),
          ...(sources.some((source) => source.capture_status === "failed" || source.capture_status === "thin") ? ["存在抓取失败或薄证据来源"] : []),
          ...(object.lifecycle !== "accepted" ? ["对象仍处于候选生命周期"] : []),
        ],
      };
    } else if (mode === "tension") {
      result = {
        targetId,
        supportRoles: summary.support_role_counts || {},
        contradictions: summary.support_role_counts?.contradicts || 0,
        futureEvidence: summary.temporal_status_counts?.future_of_snapshot || 0,
        quarantinedSources: summary.source_use_counts?.quarantined || 0,
        interpretation: "contradictions、futureEvidence 或 quarantinedSources 大于 0 时，回答必须显式分栏，不能合并为同一事实。",
      };
    } else {
      result = {
        targetId,
        fieldStates: object.field_states,
        bindingRefs: [...new Set([...(object.binding_refs || []), ...(summary.binding_refs || [])])],
        sources: sources.map((source) => compact(source)),
        segments: segments.map((segment) => compact(segment)),
        evidenceProfile: summary,
      };
    }
    const citation = citationFor(targetId, this.indexes);
    return { data: result, context: makeContext(result), citations: [citation], coverage: coverage(sourceIds.length, sources.length, sources.length < sourceIds.length ? "missing_source_records" : undefined), warnings: warningsFor([citation]) };
  }

  private readWorkScenarios(args: Record<string, unknown>) {
    const requestedIds = Array.isArray(args.scenarioIds) ? args.scenarioIds.filter((item): item is string => typeof item === "string") : [];
    const taskId = typeof args.taskId === "string" ? this.resolveTarget(args.taskId) : undefined;
    const query = typeof args.query === "string" ? normalize(args.query) : "";
    let scenarios = data.workProcess.scenarios;
    if (requestedIds.length) {
      const resolved = requestedIds.map((id) => this.resolveTarget(id));
      scenarios = scenarios.filter((scenario) => resolved.includes(scenario.id));
    }
    if (taskId) scenarios = scenarios.filter((scenario) => scenario.task_refs.includes(taskId));
    if (query) scenarios = scenarios.filter((scenario) => normalize(`${scenario.title} ${scenario.summary} ${scenario.goal} ${scenario.trigger}`).includes(query) || tokenize(query).some((token) => normalize(`${scenario.title} ${scenario.summary}`).includes(token)));
    const scenarioIds = new Set(scenarios.map((scenario) => scenario.id));
    const nodes = data.workProcess.nodes.filter((node) => scenarioIds.has(node.scenario_id));
    const nodeIds = new Set(nodes.map((node) => node.id));
    const relations = data.workProcess.relations.filter((relation) => nodeIds.has(relation.source) || nodeIds.has(relation.target));
    const result = {
      package: { id: data.workProcessManifest.package_id, version: data.workProcessManifest.package_version, snapshotId: data.workProcessManifest.snapshot_id, status: data.workProcessManifest.status },
      interpretation: "以下是候选事理模板森林，用于解释可能的工作展开方式；它不是企业真实 episode，也不表示唯一标准流程。",
      scenarios: scenarios.map((scenario) => ({
        ...scenario,
        nodes: nodes.filter((node) => node.scenario_id === scenario.id).sort((a, b) => (a.sequence_hint || 999) - (b.sequence_hint || 999)),
        relations: relations.filter((relation) => scenario.event_refs.includes(relation.source) || scenario.event_refs.includes(relation.target)),
      })),
    };
    const ids = [...scenarios.map((scenario) => scenario.id), ...nodes.map((node) => node.id), ...relations.map((relation) => relation.id)];
    const citations = [...new Set(ids)].slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(data.workProcess.scenarios.length, scenarios.length, scenarios.length < data.workProcess.scenarios.length ? "filtered" : undefined), warnings: scenarios.length ? warningsFor(citations) : [{ code: "ZERO_RESULTS", message: "没有匹配的工作场景。" }] };
  }

  private traceWorkProcess(args: Record<string, unknown>) {
    const start = this.resolveTarget(args.start as string | NodeReference);
    if (!isProcessTarget(start, this.indexes)) {
      const taskScenarios = this.indexes.taskScenarios.get(start) || [];
      if (taskScenarios.length === 0) throw new RoleToolError("OBJECT_NOT_FOUND", `语义节点没有已登记的事理映射：${start}`);
      return this.readWorkScenarios({ scenarioIds: taskScenarios, taskId: start });
    }
    const scenario = this.indexes.processScenarios.get(start);
    const roots = scenario?.root_event_refs || [start];
    const depth = Math.min(10, Math.max(1, Number(args.depth) || 6));
    const relationTypes = new Set(Array.isArray(args.relationTypes) ? args.relationTypes.filter((value): value is string => typeof value === "string") : ["directly_follows", "branches_to", "loops_to", "produces", "realizes_task"]);
    const queue = roots.map((id) => ({ id, level: 0 }));
    const visited = new Set(roots);
    const foundRelations = new Map<string, WorkProcessRelation>();
    while (queue.length) {
      const current = queue.shift()!;
      if (current.level >= depth) continue;
      const adjacent = [...(this.indexes.processOutgoing.get(current.id) || []), ...(this.indexes.processIncoming.get(current.id) || [])]
        .filter((relation) => relationTypes.size === 0 || relationTypes.has(relation.type));
      for (const relation of adjacent) {
        foundRelations.set(relation.id, relation);
        const next = relation.source === current.id ? relation.target : relation.source;
        if (!visited.has(next)) {
          visited.add(next);
          if (isProcessTarget(next, this.indexes)) queue.push({ id: next, level: current.level + 1 });
        }
      }
    }
    const processNodes = [...visited].map((id) => this.indexes.processNodes.get(id)).filter((item): item is WorkProcessNode => Boolean(item));
    const semanticBridges = [...visited].map((id) => this.indexes.nodes.get(id)).filter((item): item is RoleNode => Boolean(item));
    const scenarioIds = [...new Set(processNodes.map((node) => node.scenario_id))];
    const result = {
      start,
      depth,
      knowledgeState: scenario?.knowledge_state || scenarioIds.map((id) => this.indexes.processScenarios.get(id)?.knowledge_state),
      nodes: processNodes.sort((a, b) => (a.sequence_hint || 999) - (b.sequence_hint || 999)),
      relations: [...foundRelations.values()],
      semanticBridges: semanticBridges.map((node) => ({ id: node.id, type: node.type, label: node.label, summary: node.summary })),
      interpretation: "branches_to 表示条件分支，loops_to 表示返工或回归，不应压平成单一路径。",
    };
    const ids = [...scenarioIds, ...visited, ...foundRelations.keys()];
    const citations = [...new Set(ids)].slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(ids.length, citations.length, ids.length > MAX_IDS ? "citation_limit" : undefined), warnings: warningsFor(citations) };
  }

  private inspectRoleProcessAlignment(args: Record<string, unknown>) {
    const statusFilter = new Set(Array.isArray(args.statuses) ? args.statuses.filter((value): value is string => typeof value === "string") : []);
    const targetId = args.target ? this.resolveTarget(args.target as string | NodeReference) : undefined;
    let records = data.workProcess.alignment;
    if (targetId) records = records.filter((record) => record.semantic_target_id === targetId || record.scenario_refs.includes(targetId));
    if (statusFilter.size) records = records.filter((record) => statusFilter.has(record.status));
    const scenarioIds = new Set(data.workProcess.scenarios.map((scenario) => scenario.id));
    const invalidScenarioRefs = data.workProcess.alignment.flatMap((record) => record.scenario_refs.filter((id) => !scenarioIds.has(id)).map((id) => ({ targetId: record.semantic_target_id, scenarioId: id })));
    const alignedTasks = new Set(data.workProcess.alignment.map((record) => record.semantic_target_id));
    const unregisteredTasks = data.graph.nodes.filter((node) => node.type === "task" && !alignedTasks.has(node.id)).map((node) => node.id);
    const orphanEvents = data.workProcess.nodes.filter((node) => node.kind === "event" && (!node.task_refs || node.task_refs.length === 0)).map((node) => node.id);
    const result = {
      summary: {
        totalSemanticTasks: data.graph.nodes.filter((node) => node.type === "task").length,
        alignmentRecords: data.workProcess.alignment.length,
        covered: data.workProcess.alignment.filter((item) => item.status === "covered").length,
        partial: data.workProcess.alignment.filter((item) => item.status === "partial").length,
        gaps: data.workProcess.alignment.filter((item) => item.status === "gap").length,
      },
      records: records.map((record) => ({ ...record, semanticLabel: labelOf(record.semantic_target_id, this.indexes), scenarios: record.scenario_refs.map((id) => ({ id, title: labelOf(id, this.indexes) })) })),
      structuralIssues: { invalidScenarioRefs, unregisteredTasks, orphanEvents },
      researchPriorities: data.workProcess.alignment.filter((item) => item.status === "gap" || item.status === "partial").map((item) => ({ targetId: item.semantic_target_id, label: labelOf(item.semantic_target_id, this.indexes), status: item.status, question: `真实工作材料中，${labelOf(item.semantic_target_id, this.indexes)} 如何进入事件链、产生什么交付物、与谁交接？` })),
    };
    const ids = [...new Set(records.flatMap((record) => [record.semantic_target_id, ...record.scenario_refs]))];
    const citations = ids.slice(0, MAX_IDS).map((id) => citationFor(id, this.indexes));
    return { data: result, context: makeContext(result), citations, coverage: coverage(data.workProcess.alignment.length, records.length, records.length < data.workProcess.alignment.length ? "filtered" : undefined), warnings: warningsFor(citations) };
  }

  private auditPackage(args: Record<string, unknown>) {
    const profile = typeof args.profile === "string" ? args.profile : "integrity";
    const missingEndpoints = data.graph.edges.filter((edge) => !this.indexes.nodes.has(edge.source) || !this.indexes.nodes.has(edge.target));
    const duplicateLabels = new Map<string, string[]>();
    for (const node of data.graph.nodes) duplicateLabels.set(normalize(node.label), [...(duplicateLabels.get(normalize(node.label)) || []), node.id]);
    const ambiguousLabels = [...duplicateLabels.entries()].filter(([, ids]) => ids.length > 1).map(([label, ids]) => ({ label, ids }));
    const futureSources = data.sources.sources.filter((source) => source.temporal_status === "future_of_snapshot");
    const failedSources = data.sources.sources.filter((source) => source.capture_status === "failed" || source.capture_status === "thin");
    const candidateNodes = data.graph.nodes.filter((node) => node.lifecycle === "candidate");
    const processEndpointIds = new Set([...data.workProcess.nodes.map((node) => node.id), ...data.graph.nodes.map((node) => node.id)]);
    const missingProcessEndpoints = data.workProcess.relations.filter((relation) => !processEndpointIds.has(relation.source) || !processEndpointIds.has(relation.target));
    const processAlignmentGaps = data.workProcess.alignment.filter((item) => item.status === "gap");
    const findings = [
      ...missingEndpoints.map((edge) => ({ severity: "error", code: "MISSING_ENDPOINT", targetId: edge.id, message: "关系端点不存在。" })),
      ...ambiguousLabels.map((item) => ({ severity: "warning", code: "DUPLICATE_LABEL", targetId: item.ids.join(","), message: `标签重复：${item.label}` })),
      ...futureSources.map((source) => ({ severity: "warning", code: "FUTURE_SOURCE", targetId: source.id, message: "来源晚于快照时点。" })),
      ...failedSources.map((source) => ({ severity: "warning", code: "THIN_SOURCE", targetId: source.id, message: "来源抓取失败或内容过薄。" })),
      ...missingProcessEndpoints.map((relation) => ({ severity: "error", code: "MISSING_PROCESS_ENDPOINT", targetId: relation.id, message: "事理关系端点不存在。" })),
      ...processAlignmentGaps.map((item) => ({ severity: "research", code: "PROCESS_ALIGNMENT_GAP", targetId: item.semantic_target_id, message: item.note })),
    ];
    const result = {
      profile,
      valid: data.validation.valid && data.workProcessValidation.valid && missingEndpoints.length === 0 && missingProcessEndpoints.length === 0,
      publishable: data.validation.publishable && data.workProcessValidation.publishable && missingEndpoints.length === 0 && missingProcessEndpoints.length === 0,
      validationStats: data.validation.stats,
      metrics: {
        missingEndpoints: missingEndpoints.length,
        ambiguousLabels: ambiguousLabels.length,
        candidateNodes: candidateNodes.length,
        futureSources: futureSources.length,
        failedOrThinSources: failedSources.length,
        processScenarios: data.workProcess.scenarios.length,
        processNodes: data.workProcess.nodes.length,
        missingProcessEndpoints: missingProcessEndpoints.length,
        processAlignmentGaps: processAlignmentGaps.length,
      },
      findings,
      patchProposals: findings.map((finding) => ({ targetId: finding.targetId, action: "review", reason: finding.message })),
    };
    const citationTargets = [...new Set(findings.map((finding) => finding.targetId).filter((id) => this.indexes.objects.has(id)))].slice(0, MAX_IDS);
    const citations = citationTargets.map((id) => citationFor(id, this.indexes));
    const auditedCount = data.graph.edges.length + data.graph.nodes.length + data.sources.sources.length + data.workProcess.nodes.length + data.workProcess.relations.length;
    return { data: result, context: makeContext(result), citations, coverage: coverage(auditedCount, auditedCount), warnings: warningsFor(citations) };
  }
}

export const rolePackageRuntime = new RolePackageRuntime();

export function createNodeReference(targetId: string): NodeReference {
  const isProcess = rolePackageRuntime.package.workProcess.scenarios.some((item) => item.id === targetId)
    || rolePackageRuntime.package.workProcess.nodes.some((item) => item.id === targetId)
    || rolePackageRuntime.package.workProcess.relations.some((item) => item.id === targetId);
  return { ...(isProcess ? rolePackageRuntime.processReferenceBase : rolePackageRuntime.referenceBase), targetId };
}

export function assignCitationHandles(citations: ToolCitation[]) {
  const deduplicated = new Map<string, ToolCitation>();
  for (const citation of citations) {
    const key = `${citation.packageId}:${citation.packageVersion}:${citation.snapshotId}:${citation.targetId}:${citation.fieldPath || ""}:${citation.bindingId || ""}:${citation.segmentId || ""}`;
    if (!deduplicated.has(key)) deduplicated.set(key, citation);
  }
  return [...deduplicated.values()].map((citation, index) => ({ ...citation, handle: `C${index + 1}` }));
}
