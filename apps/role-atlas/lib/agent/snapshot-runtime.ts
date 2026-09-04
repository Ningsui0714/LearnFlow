import { auditRoleSnapshot } from "@/lib/risk/audit";
import type {
  ColdStartBuildResult,
  EvidenceBinding,
  ProcessEdge,
  ProcessNode,
  ProcessScenario,
  SemanticBridge,
  SemanticEdge,
  SemanticNode,
  SourceAsset,
  SourceSegment,
} from "@/lib/build/types";
import type {
  Lifecycle,
  NodeReference,
  RoleToolCall,
  RoleToolName,
  ToolCitation,
  ToolCoverage,
  ToolEnvelope,
  ToolWarning,
} from "@/lib/role-package/types";
import { normalizeRolePackage } from "@/lib/packages/role-package-manifest";

export const CORE_ROLE_TOOL_NAMES = [
  "read_role_objects",
  "search_role_knowledge",
  "query_role_graph",
  "trace_work_process",
  "inspect_role_evidence",
  "audit_role_package",
] as const satisfies readonly RoleToolName[];

export type CoreRoleToolName = (typeof CORE_ROLE_TOOL_NAMES)[number];

export const CORE_TOOL_PURPOSES: Record<CoreRoleToolName, string> = {
  read_role_objects: "精确读取所选岗位对象及其一跳关系",
  search_role_knowledge: "在岗位语义、事理场景和证据片段中检索",
  query_role_graph: "沿统一岗位图查询邻域和跨层关系",
  trace_work_process: "读取任务对应的事理场景、事件、交付物、分支和返工",
  inspect_role_evidence: "查看对象绑定的原始来源、片段和证据强度",
  audit_role_package: "读取岗位快照概览、结构健康、缺口与研究主题",
};

type RuntimeObject = {
  id: string;
  type: string;
  label: string;
  summary: string;
  lifecycle: Lifecycle;
  confidence: number;
  evidenceBindingIds: string[];
  evidenceSegmentIds: string[];
  artifactKind: "role_semantic" | "work_process";
  knowledgeState?: ToolCitation["knowledgeState"];
  raw: SemanticNode | ProcessScenario | ProcessNode;
};

type RuntimeRelation = {
  id: string;
  type: string;
  source: string;
  target: string;
  artifactKind: "role_semantic" | "work_process";
  evidenceBindingIds: string[];
  evidenceSegmentIds: string[];
  raw: SemanticEdge | ProcessEdge | SemanticBridge | { scenarioId: string; nodeId: string };
};

type RuntimeIndexes = {
  objects: Map<string, RuntimeObject>;
  aliases: Map<string, string[]>;
  relations: RuntimeRelation[];
  outgoing: Map<string, RuntimeRelation[]>;
  incoming: Map<string, RuntimeRelation[]>;
  bindings: Map<string, EvidenceBinding>;
  bindingsByTarget: Map<string, EvidenceBinding[]>;
  segments: Map<string, SourceSegment>;
  sources: Map<string, SourceAsset>;
};

class SnapshotRuntimeError extends Error {
  constructor(
    readonly code: "INVALID_REFERENCE" | "SNAPSHOT_MISMATCH" | "OBJECT_NOT_FOUND" | "AMBIGUOUS_ALIAS" | "RESULT_LIMIT_EXCEEDED" | "INTERNAL_ERROR",
    message: string,
    readonly whoFixes: "system" | "agent" | "user" | "developer" = "agent",
    readonly retryable = false,
    readonly suggestedAction?: string,
  ) {
    super(message);
  }
}

const MAX_IDS = 25;
const MAX_TOP_K = 20;
const MAX_GRAPH_DEPTH = 2;
const MAX_PROCESS_DEPTH = 8;
const MAX_CONTEXT_CHARS = 14_000;

function unique<T>(values: T[]) {
  return [...new Set(values)];
}

function normalize(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
}

function tokens(value: string) {
  const normalized = value.normalize("NFKC").toLocaleLowerCase();
  const result = new Set<string>();
  for (const word of normalized.match(/[a-z0-9][a-z0-9._:+-]*/g) || []) result.add(word);
  for (const group of normalized.match(/[\u3400-\u9fff]+/g) || []) {
    if (group.length <= 5) result.add(group);
    for (const character of group) result.add(character);
    for (let index = 0; index < group.length - 1; index += 1) result.add(group.slice(index, index + 2));
  }
  return [...result];
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
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

function compact(value: unknown, depth = 0): unknown {
  if (value == null || typeof value === "boolean" || typeof value === "number") return value;
  if (typeof value === "string") return value.length > 900 ? `${value.slice(0, 897)}…` : value;
  if (Array.isArray(value)) return value.slice(0, depth === 0 ? 18 : 10).map((item) => compact(item, depth + 1));
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, 24).map(([key, item]) => [key, compact(item, depth + 1)]));
  }
  return String(value);
}

function makeContext(value: unknown) {
  const context = JSON.stringify(compact(value));
  return context.length <= MAX_CONTEXT_CHARS ? context : `${context.slice(0, MAX_CONTEXT_CHARS - 1)}…`;
}

function lifecycle(value: "candidate" | "stable" | "rejected"): Lifecycle {
  return value === "stable" ? "accepted" : value === "rejected" ? "deprecated" : "candidate";
}

function coverage(requested: number, returned: number, reason?: string): ToolCoverage {
  const omitted = Math.max(0, requested - returned);
  return { complete: omitted === 0, requested, returned, omitted, partial: omitted > 0, reason };
}

function buildIndexes(snapshot: ColdStartBuildResult): RuntimeIndexes {
  const bindings = new Map(snapshot.sources.evidenceBindings.map((binding) => [binding.id, binding]));
  const bindingsByTarget = new Map<string, EvidenceBinding[]>();
  for (const binding of snapshot.sources.evidenceBindings) {
    bindingsByTarget.set(binding.targetId, [...(bindingsByTarget.get(binding.targetId) || []), binding]);
  }
  const segments = new Map(snapshot.sources.segments.map((segment) => [segment.id, segment]));
  const sources = new Map(snapshot.sources.assets.map((source) => [source.id, source]));
  const objects = new Map<string, RuntimeObject>();
  for (const node of snapshot.semantic.nodes) {
    objects.set(node.id, {
      id: node.id,
      type: node.type,
      label: node.label,
      summary: node.summary,
      lifecycle: lifecycle(node.lifecycle),
      confidence: node.confidence,
      evidenceBindingIds: node.evidenceBindingIds,
      evidenceSegmentIds: node.evidenceSegmentIds,
      artifactKind: "role_semantic",
      raw: node,
    });
  }
  for (const scenario of snapshot.process.scenarios) {
    objects.set(scenario.id, {
      id: scenario.id,
      type: "scenario",
      label: scenario.label,
      summary: scenario.summary,
      lifecycle: lifecycle(scenario.lifecycle),
      confidence: Math.max(0, ...scenario.evidenceBindingIds.map((id) => bindings.get(id)?.confidence || 0)),
      evidenceBindingIds: scenario.evidenceBindingIds,
      evidenceSegmentIds: scenario.evidenceSegmentIds,
      artifactKind: "work_process",
      knowledgeState: scenario.knowledgeState,
      raw: scenario,
    });
  }
  for (const node of snapshot.process.nodes) {
    objects.set(node.id, {
      id: node.id,
      type: node.kind,
      label: node.label,
      summary: node.summary,
      lifecycle: lifecycle(node.lifecycle),
      confidence: Math.max(0, ...node.evidenceBindingIds.map((id) => bindings.get(id)?.confidence || 0)),
      evidenceBindingIds: node.evidenceBindingIds,
      evidenceSegmentIds: node.evidenceSegmentIds,
      artifactKind: "work_process",
      knowledgeState: node.knowledgeState,
      raw: node,
    });
  }

  const relations: RuntimeRelation[] = [
    ...snapshot.semantic.edges.map((edge): RuntimeRelation => ({
      id: edge.id,
      type: edge.type,
      source: edge.source,
      target: edge.target,
      artifactKind: "role_semantic",
      evidenceBindingIds: edge.evidenceBindingIds,
      evidenceSegmentIds: edge.evidenceSegmentIds,
      raw: edge,
    })),
    ...snapshot.process.edges.map((edge): RuntimeRelation => ({
      id: edge.id,
      type: edge.type,
      source: edge.source,
      target: edge.target,
      artifactKind: "work_process",
      evidenceBindingIds: edge.evidenceBindingIds,
      evidenceSegmentIds: edge.evidenceSegmentIds,
      raw: edge,
    })),
    ...snapshot.process.bridges.map((bridge): RuntimeRelation => ({
      id: bridge.id,
      type: bridge.type,
      source: bridge.processNodeId,
      target: bridge.semanticNodeId,
      artifactKind: "work_process",
      evidenceBindingIds: bridge.evidenceBindingIds || [],
      evidenceSegmentIds: bridge.evidenceSegmentIds || [],
      raw: bridge,
    })),
    ...snapshot.process.nodes.map((node): RuntimeRelation => ({
      id: `runtime:scenario_contains:${node.scenarioId}:${node.id}`,
      type: "contains_event",
      source: node.scenarioId,
      target: node.id,
      artifactKind: "work_process",
      evidenceBindingIds: [],
      evidenceSegmentIds: [],
      raw: { scenarioId: node.scenarioId, nodeId: node.id },
    })),
  ];
  const outgoing = new Map<string, RuntimeRelation[]>();
  const incoming = new Map<string, RuntimeRelation[]>();
  for (const relation of relations) {
    outgoing.set(relation.source, [...(outgoing.get(relation.source) || []), relation]);
    incoming.set(relation.target, [...(incoming.get(relation.target) || []), relation]);
  }
  const aliases = new Map<string, string[]>();
  for (const object of objects.values()) {
    const values = [object.id, object.label, ...("aliases" in object.raw && Array.isArray(object.raw.aliases) ? object.raw.aliases : [])];
    for (const value of values) {
      const key = normalize(String(value));
      aliases.set(key, unique([...(aliases.get(key) || []), object.id]));
    }
  }
  return { objects, aliases, relations, outgoing, incoming, bindings, bindingsByTarget, segments, sources };
}

export class SnapshotRoleRuntime {
  readonly snapshot: ColdStartBuildResult;
  private readonly indexes: RuntimeIndexes;
  private readonly runCache = new Map<string, ToolEnvelope>();

  constructor(snapshot: ColdStartBuildResult) {
    this.snapshot = normalizeRolePackage(snapshot);
    this.indexes = buildIndexes(this.snapshot);
  }

  get descriptor() {
    return {
      packageId: this.snapshot.packages.rolePackage.packageId,
      packageVersion: this.snapshot.packages.rolePackage.packageVersion,
      snapshotId: this.snapshot.snapshot.id,
      snapshotAsOf: this.snapshot.snapshot.asOf,
      status: this.snapshot.snapshot.status,
      publishable: this.snapshot.validation.publishable,
      workProcess: {
        packageId: this.snapshot.packages.rolePackage.packageId,
        packageVersion: this.snapshot.packages.rolePackage.packageVersion,
        snapshotId: this.snapshot.packages.rolePackage.snapshotId,
        status: this.snapshot.packages.rolePackage.status,
        namespaceId: this.snapshot.packages.rolePackage.namespaces.process.id,
      },
    };
  }

  private isSemanticReference(reference: NodeReference) {
    const rolePackage = this.snapshot.packages.rolePackage;
    return reference.packageId === rolePackage.packageId
      && reference.packageVersion === rolePackage.packageVersion
      && reference.snapshotId === rolePackage.snapshotId;
  }

  private isProcessReference(reference: NodeReference) {
    return this.isSemanticReference(reference);
  }

  resolveTarget(input: string | NodeReference) {
    if (typeof input !== "string") {
      if (!input?.targetId) throw new SnapshotRuntimeError("INVALID_REFERENCE", "节点引用缺少 targetId。", "user");
      const object = this.indexes.objects.get(input.targetId);
      if (!object) throw new SnapshotRuntimeError("OBJECT_NOT_FOUND", `对象不存在：${input.targetId}`, "user");
      const packageMatches = object.artifactKind === "work_process" ? this.isProcessReference(input) : this.isSemanticReference(input);
      if (!packageMatches) throw new SnapshotRuntimeError("SNAPSHOT_MISMATCH", "节点引用不属于当前固定岗位快照。", "user", false, "请从当前图谱重新选择节点。");
      return input.targetId;
    }
    if (this.indexes.objects.has(input)) return input;
    const matches = this.indexes.aliases.get(normalize(input)) || [];
    if (!matches.length) throw new SnapshotRuntimeError("OBJECT_NOT_FOUND", `对象或别名不存在：${input}`, "agent");
    if (matches.length > 1) throw new SnapshotRuntimeError("AMBIGUOUS_ALIAS", `别名对应多个对象：${matches.join("、")}`, "agent", false, "请使用精确节点 ID。");
    return matches[0];
  }

  validateReferences(references: NodeReference[]) {
    return references.map((reference) => this.resolveTarget(reference));
  }

  private citationFor(targetId: string, fieldPath?: string): ToolCitation {
    const object = this.indexes.objects.get(targetId);
    if (!object) throw new SnapshotRuntimeError("OBJECT_NOT_FOUND", `对象不存在：${targetId}`);
    const targetBindings = object.evidenceBindingIds.map((id) => this.indexes.bindings.get(id)).filter((binding): binding is EvidenceBinding => Boolean(binding));
    const sourceIds = unique(targetBindings.map((binding) => binding.sourceId));
    const future = sourceIds.some((sourceId) => {
      const source = this.indexes.sources.get(sourceId);
      const date = source?.publishedAt || source?.observedAt;
      return Boolean(date && date > this.snapshot.snapshot.asOf);
    });
    const packageInfo = this.snapshot.packages.rolePackage;
    return {
      artifactKind: object.artifactKind,
      packageId: packageInfo.packageId,
      packageVersion: packageInfo.packageVersion,
      snapshotId: packageInfo.snapshotId,
      targetId,
      label: object.label,
      fieldPath,
      bindingId: targetBindings[0]?.id,
      segmentId: targetBindings[0]?.segmentId || object.evidenceSegmentIds[0],
      sourceIds,
      sourceTitles: sourceIds.map((sourceId) => this.indexes.sources.get(sourceId)?.title || sourceId),
      confidence: Math.max(object.confidence, ...targetBindings.map((binding) => binding.confidence), 0),
      lifecycle: object.lifecycle,
      temporalStatus: future ? "mixed_or_future" : "within_snapshot",
      knowledgeState: object.knowledgeState,
    };
  }

  private warningsFor(citations: ToolCitation[]): ToolWarning[] {
    return citations.flatMap((citation) => [
      ...(citation.lifecycle !== "accepted" ? [{ code: "CANDIDATE_CONTENT", message: "该对象仍是候选知识。", targetId: citation.targetId }] : []),
      ...(citation.sourceIds.length === 0 ? [{ code: "NO_DIRECT_SOURCE", message: "该对象没有可下钻的直接来源。", targetId: citation.targetId }] : []),
      ...(citation.temporalStatus !== "within_snapshot" ? [{ code: "TEMPORAL_SCOPE", message: "证据含快照时点之后的材料。", targetId: citation.targetId }] : []),
      ...(citation.knowledgeState === "inferred_pattern" ? [{ code: "INFERRED_PROCESS", message: "该事理对象是归纳工作模式，不是真实工作日志。", targetId: citation.targetId }] : []),
    ]);
  }

  async execute(call: RoleToolCall, runId: string): Promise<ToolEnvelope> {
    const startedAt = performance.now();
    const callFingerprint = fingerprint({ call, snapshotId: this.snapshot.snapshot.id });
    const cacheKey = `${runId}:${callFingerprint}`;
    const cached = this.runCache.get(cacheKey);
    if (cached) {
      return {
        ...cached,
        warnings: [...cached.warnings, { code: "DUPLICATE_CALL", message: "同一运行中的相同工具调用已复用。" }],
        diagnostics: { ...cached.diagnostics, deduplicated: true, durationMs: Math.max(0, performance.now() - startedAt), cache: "run" },
      };
    }
    try {
      if (!CORE_ROLE_TOOL_NAMES.includes(call.name as CoreRoleToolName)) {
        throw new SnapshotRuntimeError("INTERNAL_ERROR", `主 Agent 不暴露旧工具：${call.name}`, "developer");
      }
      const raw = this.dispatch(call.name as CoreRoleToolName, call.args);
      const result: ToolEnvelope = {
        ok: true,
        tool: call.name,
        ...raw,
        diagnostics: {
          callFingerprint,
          deduplicated: false,
          durationMs: Math.max(0, performance.now() - startedAt),
          packageVersion: this.snapshot.packages.rolePackage.packageVersion,
          snapshotId: this.snapshot.snapshot.id,
          cache: "miss",
          companionVersions: { workProcess: this.snapshot.packages.rolePackage.packageVersion },
        },
      };
      this.runCache.set(cacheKey, result);
      return result;
    } catch (error) {
      const known = error instanceof SnapshotRuntimeError ? error : new SnapshotRuntimeError("INTERNAL_ERROR", "工具执行失败。", "developer", false);
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
          durationMs: Math.max(0, performance.now() - startedAt),
          packageVersion: this.snapshot.packages.rolePackage.packageVersion,
          snapshotId: this.snapshot.snapshot.id,
          cache: "miss",
          companionVersions: { workProcess: this.snapshot.packages.rolePackage.packageVersion },
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

  private dispatch(name: CoreRoleToolName, args: Record<string, unknown>) {
    switch (name) {
      case "read_role_objects": return this.readObjects(args);
      case "search_role_knowledge": return this.searchKnowledge(args);
      case "query_role_graph": return this.queryGraph(args);
      case "trace_work_process": return this.traceProcess(args);
      case "inspect_role_evidence": return this.inspectEvidence(args);
      case "audit_role_package": return this.inspectSnapshot(args);
    }
  }

  private objectView(object: RuntimeObject) {
    return {
      id: object.id,
      type: object.type,
      label: object.label,
      summary: object.summary,
      lifecycle: object.lifecycle,
      confidence: object.confidence,
      artifactKind: object.artifactKind,
      knowledgeState: object.knowledgeState,
      data: object.raw,
    };
  }

  private evidencePreview(targetId: string) {
    return (this.indexes.bindingsByTarget.get(targetId) || []).slice(0, 3).map((binding) => {
      const segment = this.indexes.segments.get(binding.segmentId);
      const source = this.indexes.sources.get(binding.sourceId);
      return {
        bindingId: binding.id,
        support: binding.support,
        confidence: binding.confidence,
        sourceId: source?.id || binding.sourceId,
        sourceTitle: source?.title,
        locator: source?.locator,
        segmentId: segment?.id || binding.segmentId,
        excerpt: segment?.text.slice(0, 700),
      };
    });
  }

  private relationView(relation: RuntimeRelation) {
    return {
      id: relation.id,
      type: relation.type,
      source: relation.source,
      sourceLabel: this.indexes.objects.get(relation.source)?.label || relation.source,
      target: relation.target,
      targetLabel: this.indexes.objects.get(relation.target)?.label || relation.target,
      artifactKind: relation.artifactKind,
    };
  }

  private requestedTargets(args: Record<string, unknown>) {
    const raw = Array.isArray(args.targets) ? args.targets : args.target != null ? [args.target] : [];
    if (raw.length > MAX_IDS) throw new SnapshotRuntimeError("RESULT_LIMIT_EXCEEDED", `一次最多读取 ${MAX_IDS} 个对象。`, "agent");
    return raw as Array<string | NodeReference>;
  }

  private readObjects(args: Record<string, unknown>) {
    const requested = this.requestedTargets(args);
    const objects: Array<ReturnType<SnapshotRoleRuntime["objectView"]> & { evidence: ReturnType<SnapshotRoleRuntime["evidencePreview"]> }> = [];
    const missing: string[] = [];
    const ids: string[] = [];
    for (const target of requested) {
      try {
        const id = this.resolveTarget(target);
        const object = this.indexes.objects.get(id)!;
        ids.push(id);
        objects.push({ ...this.objectView(object), evidence: this.evidencePreview(id) });
      } catch {
        missing.push(typeof target === "string" ? target : target.targetId);
      }
    }
    const relations = unique(ids.flatMap((id) => [...(this.indexes.outgoing.get(id) || []), ...(this.indexes.incoming.get(id) || [])]))
      .slice(0, 60)
      .map((relation) => this.relationView(relation));
    const citations = ids.map((id) => this.citationFor(id));
    const result = { objects, relations, missing };
    return {
      data: result,
      context: makeContext(result),
      citations,
      coverage: coverage(requested.length, objects.length, missing.length ? "partial_batch_success" : undefined),
      warnings: [...this.warningsFor(citations), ...missing.map((targetId) => ({ code: "OBJECT_NOT_FOUND", message: "对象不存在或不属于当前快照。", targetId }))],
    };
  }

  private searchKnowledge(args: Record<string, unknown>) {
    const query = String(args.query || "").trim();
    const topK = Math.max(1, Math.min(Number(args.topK || 8), MAX_TOP_K));
    const selectedIds = new Set(Array.isArray(args.selectedIds) ? args.selectedIds.filter((id): id is string => typeof id === "string") : []);
    const queryTokens = tokens(query);
    const candidates = [...this.indexes.objects.values()].map((object) => {
      const evidence = object.evidenceSegmentIds.map((id) => this.indexes.segments.get(id)?.text || "").join(" ").slice(0, 4_000);
      const haystack = `${object.label} ${object.summary} ${evidence}`.toLocaleLowerCase();
      const overlap = queryTokens.reduce((score, token) => score + (haystack.includes(token) ? token.length > 1 ? 2 : 0.15 : 0), 0);
      const exact = normalize(object.label) === normalize(query) ? 25 : normalize(object.label).includes(normalize(query)) && normalize(query) ? 8 : 0;
      return { object, score: overlap + exact + (selectedIds.has(object.id) ? 30 : 0) };
    }).filter((candidate) => candidate.score > 0)
      .sort((left, right) => right.score - left.score || right.object.confidence - left.object.confidence)
      .slice(0, topK);
    const results = candidates.map(({ object, score }) => ({ ...this.objectView(object), score: Number(score.toFixed(3)) }));
    const citations = candidates.map(({ object }) => this.citationFor(object.id));
    return {
      data: { query, results, searched: this.indexes.objects.size },
      context: makeContext({ query, results }),
      citations,
      coverage: coverage(this.indexes.objects.size, results.length, results.length === topK ? "top_k" : undefined),
      warnings: results.length ? this.warningsFor(citations) : [{ code: "ZERO_RESULTS", message: "当前岗位快照中没有匹配对象。" }],
    };
  }

  private queryGraph(args: Record<string, unknown>) {
    const start = this.resolveTarget(args.start as string | NodeReference);
    const depth = Math.max(1, Math.min(Number(args.depth || 1), MAX_GRAPH_DEPTH));
    const direction = args.direction === "out" || args.direction === "in" ? args.direction : "both";
    const visited = new Set([start]);
    const relationMap = new Map<string, RuntimeRelation>();
    let frontier = [start];
    for (let level = 0; level < depth && frontier.length; level += 1) {
      const next: string[] = [];
      for (const id of frontier) {
        const relations = direction === "out" ? this.indexes.outgoing.get(id) || []
          : direction === "in" ? this.indexes.incoming.get(id) || []
            : [...(this.indexes.outgoing.get(id) || []), ...(this.indexes.incoming.get(id) || [])];
        for (const relation of relations) {
          relationMap.set(relation.id, relation);
          for (const endpoint of [relation.source, relation.target]) {
            if (!visited.has(endpoint) && this.indexes.objects.has(endpoint)) {
              visited.add(endpoint);
              next.push(endpoint);
            }
          }
        }
      }
      frontier = next;
    }
    const ids = [...visited].slice(0, MAX_IDS);
    const nodes = ids.map((id) => this.objectView(this.indexes.objects.get(id)!));
    const relations = [...relationMap.values()].filter((relation) => visited.has(relation.source) && visited.has(relation.target)).slice(0, 80).map((relation) => this.relationView(relation));
    const citations = ids.map((id) => this.citationFor(id));
    const result = { start, depth, direction, nodes, relations };
    return { data: result, context: makeContext(result), citations, coverage: coverage(visited.size, nodes.length, visited.size > MAX_IDS ? "citation_limit" : undefined), warnings: this.warningsFor(citations) };
  }

  private traceProcess(args: Record<string, unknown>) {
    const query = String(args.query || "").trim();
    const rawStart = args.start || args.target;
    const start = rawStart ? this.resolveTarget(rawStart as string | NodeReference) : undefined;
    const scenarioIds = new Set<string>();
    if (start) {
      const object = this.indexes.objects.get(start)!;
      if (object.type === "scenario") scenarioIds.add(start);
      else if (object.artifactKind === "work_process" && "scenarioId" in object.raw) scenarioIds.add(object.raw.scenarioId);
      else {
        for (const bridge of this.snapshot.process.bridges.filter((item) => item.semanticNodeId === start)) {
          const processNode = this.snapshot.process.nodes.find((node) => node.id === bridge.processNodeId);
          if (processNode) scenarioIds.add(processNode.scenarioId);
        }
      }
    }
    if (!scenarioIds.size && query) {
      const queryTokens = tokens(query);
      const ranked = this.snapshot.process.scenarios.map((scenario) => ({
        id: scenario.id,
        score: queryTokens.reduce((score, token) => score + (`${scenario.label}${scenario.summary}`.toLocaleLowerCase().includes(token) ? 1 : 0), 0),
      })).filter((item) => item.score > 0).sort((left, right) => right.score - left.score).slice(0, 4);
      ranked.forEach((item) => scenarioIds.add(item.id));
    }
    const scenarios = this.snapshot.process.scenarios.filter((scenario) => scenarioIds.has(scenario.id));
    const nodeIds = new Set(this.snapshot.process.nodes.filter((node) => scenarioIds.has(node.scenarioId)).map((node) => node.id));
    const nodes = [...nodeIds].map((id) => this.objectView(this.indexes.objects.get(id)!));
    const edges = this.snapshot.process.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)).map((edge) => this.relationView(this.indexes.relations.find((relation) => relation.id === edge.id)!));
    const bridges = this.snapshot.process.bridges.filter((bridge) => nodeIds.has(bridge.processNodeId)).map((bridge) => this.relationView(this.indexes.relations.find((relation) => relation.id === bridge.id)!));
    const ids = [...scenarios.map((scenario) => scenario.id), ...nodeIds].slice(0, MAX_IDS);
    const citations = ids.map((id) => this.citationFor(id));
    const result = { start, query, depth: Math.max(1, Math.min(Number(args.depth || 6), MAX_PROCESS_DEPTH)), scenarios, nodes, edges, bridges };
    return {
      data: result,
      context: makeContext(result),
      citations,
      coverage: coverage(this.snapshot.process.scenarios.length, scenarios.length, scenarios.length < this.snapshot.process.scenarios.length ? "filtered" : undefined),
      warnings: scenarios.length ? this.warningsFor(citations) : [{ code: "ZERO_RESULTS", message: "没有找到对应的事理场景。", targetId: start }],
    };
  }

  private inspectEvidence(args: Record<string, unknown>) {
    const requested = this.requestedTargets(args);
    const ids = requested.map((target) => this.resolveTarget(target));
    const records = ids.map((targetId) => {
      const targetBindings = this.indexes.bindingsByTarget.get(targetId) || [];
      return {
        targetId,
        label: this.indexes.objects.get(targetId)?.label || targetId,
        bindings: targetBindings.map((binding) => {
          const segment = this.indexes.segments.get(binding.segmentId);
          const source = this.indexes.sources.get(binding.sourceId);
          return {
            id: binding.id,
            support: binding.support,
            method: binding.method,
            confidence: binding.confidence,
            fieldPath: binding.fieldPath,
            evidenceSpan: binding.evidenceSpan,
            segment: segment ? { id: segment.id, text: segment.text } : undefined,
            source: source ? {
              id: source.id,
              title: source.title,
              kind: source.kind,
              locator: source.locator,
              publisher: source.publisher,
              publishedAt: source.publishedAt,
              observedAt: source.observedAt,
              sourceTier: source.sourceTier,
              qualification: source.qualification,
            } : undefined,
          };
        }),
      };
    });
    const citations = ids.map((id) => this.citationFor(id));
    return { data: { records }, context: makeContext({ records }), citations, coverage: coverage(ids.length, records.filter((record) => record.bindings.length).length, "evidence_coverage"), warnings: this.warningsFor(citations) };
  }

  private inspectSnapshot(args: Record<string, unknown>) {
    const targetIds = Array.isArray(args.targetIds) ? args.targetIds.filter((id): id is string => typeof id === "string" && this.indexes.objects.has(id)) : [];
    const audit = auditRoleSnapshot(this.snapshot, { targetIds });
    const role = this.snapshot.semantic.nodes.find((node) => node.type === "market_role");
    const counts = Object.fromEntries(unique(this.snapshot.semantic.nodes.map((node) => node.type)).sort().map((type) => [type, this.snapshot.semantic.nodes.filter((node) => node.type === type).length]));
    const result = {
      mode: typeof args.profile === "string" ? args.profile : "overview",
      role: role ? this.objectView(this.indexes.objects.get(role.id)!) : { label: this.snapshot.brief.roleTitle, summary: this.snapshot.brief.roleDescription },
      snapshot: this.descriptor,
      counts: { semantic: counts, scenarios: this.snapshot.process.scenarios.length, processNodes: this.snapshot.process.nodes.length, sources: this.snapshot.sources.assets.length },
      sections: this.snapshot.snapshot.sections,
      validation: this.snapshot.validation,
      health: audit.metrics,
      clusters: audit.clusters.slice(0, 12),
      issues: audit.issues.slice(0, 30),
      researchTopics: this.snapshot.audit.researchTopics.slice(0, 20),
    };
    const citationIds = unique([...(role ? [role.id] : []), ...targetIds]).slice(0, MAX_IDS);
    const citations = citationIds.map((id) => this.citationFor(id));
    return { data: result, context: makeContext(result), citations, coverage: coverage(1, 1), warnings: this.warningsFor(citations) };
  }
}
