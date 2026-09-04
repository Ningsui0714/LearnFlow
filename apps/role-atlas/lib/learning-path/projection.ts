import type {
  EvidenceBinding,
  LearningPathGraphInput,
  RoleLearningNodeProposal,
  RoleLearningPathBinding,
  RoleLearningProjection,
  SemanticNode,
  SourceAsset,
} from "@/lib/build/types";

function stableHash(value: string) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36).padStart(7, "0");
}

function normalize(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase()
    .replace(/人工智能代理/gu, "aiagent")
    .replace(/智能体开发/gu, "agent开发")
    .replace(/[^a-z0-9+#\u4e00-\u9fff]+/gu, "");
}

function grams(value: string) {
  if (value.length <= 2) return new Set(value ? [value] : []);
  return new Set(Array.from({ length: value.length - 1 }, (_, index) => value.slice(index, index + 2)));
}

function similarity(left: string, right: string) {
  const a = normalize(left), b = normalize(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.includes(b) || b.includes(a)) return Math.min(a.length, b.length) / Math.max(a.length, b.length) * 0.9;
  const ga = grams(a), gb = grams(b);
  let overlap = 0;
  ga.forEach((item) => { if (gb.has(item)) overlap += 1; });
  return 2 * overlap / Math.max(1, ga.size + gb.size);
}

function nodeScore(query: SemanticNode, candidate: LearningPathGraphInput["nodes"][number]) {
  const labels = [candidate.title, ...candidate.aliases];
  const lexical = Math.max(...labels.map((label) => similarity(query.label, label)));
  const topical = Math.max(0, ...candidate.domains.map((domain) => similarity(`${query.label}${query.summary}`, domain)));
  return Math.min(1, lexical * 0.82 + topical * 0.18);
}

function sourceEvidenceFor(
  node: SemanticNode,
  assets: SourceAsset[],
  bindings: EvidenceBinding[],
): RoleLearningNodeProposal["sourceEvidence"] {
  const sourceIds = new Set(bindings.filter((binding) => node.evidenceBindingIds.includes(binding.id)).map((binding) => binding.sourceId));
  return assets.flatMap((asset) => {
    if (!sourceIds.has(asset.id) || !asset.locator?.startsWith("https://")) return [];
    const roles = asset.qualification?.evidenceRoles || [];
    const quality = roles.includes("official_standard") ? "official" as const
      : roles.includes("work_practice") ? "repository" as const
        : "community" as const;
    return [{
      url: asset.locator,
      title: asset.title,
      source: asset.publisher || asset.locator,
      quality,
      relevance: 1,
      matchedTerms: [node.label],
    }];
  }).slice(0, 6);
}

export function buildRoleLearningProjection(input: {
  graph?: LearningPathGraphInput;
  snapshotId: string;
  semanticNodes: SemanticNode[];
  assets: SourceAsset[];
  evidenceBindings: EvidenceBinding[];
}): RoleLearningProjection | undefined {
  if (!input.graph) return undefined;
  const bindings: RoleLearningPathBinding[] = [];
  const proposals: RoleLearningNodeProposal[] = [];
  const targets = input.semanticNodes.filter((node) => node.type === "knowledge_skill" || node.type === "capability_unit");

  for (const target of targets) {
    const ranked = input.graph.nodes.map((node) => ({ node, score: nodeScore(target, node) }))
      .sort((left, right) => right.score - left.score || left.node.id.localeCompare(right.node.id));
    const exact = ranked.find(({ node }) => [node.id, node.title, ...node.aliases].some((label) => normalize(label) === normalize(target.label)));
    const top = ranked[0], second = ranked[1];
    const fuzzyResolved = !exact && top && top.score >= 0.76 && top.score - (second?.score || 0) >= 0.1;
    const ambiguous = !exact && !fuzzyResolved && top && top.score >= 0.48;
    const mode = exact ? "exact" as const : fuzzyResolved ? "fuzzy_resolved" as const : ambiguous ? "ambiguous" as const : "graph_gap" as const;
    const selected = exact?.node || (fuzzyResolved ? top.node : undefined);
    const candidates = ranked.filter((item) => item.score >= (ambiguous ? 0.38 : 0.24)).slice(0, 4);
    bindings.push({
      id: `learning-binding:${stableHash(`${target.id}:${selected?.id || mode}`)}`,
      semanticNodeId: target.id,
      learningPathNodeId: selected?.id,
      relation: target.type === "capability_unit" ? "practices" : "requires",
      mappingMode: mode,
      rationale: selected
        ? `“${target.label}”与学习路径节点“${selected.title}”${mode === "exact" ? "名称或别名一致" : "在名称和领域上形成唯一高分匹配"}。`
        : mode === "ambiguous" ? "存在多个相近节点，需要人工消歧后才能形成路线。" : "正式路径中没有可靠匹配，保留为图谱缺口。",
      candidateNodeIds: candidates.map((item) => item.node.id),
      evidenceBindingIds: target.evidenceBindingIds,
    });

    if (mode !== "graph_gap" || !candidates.length) continue;
    const sourceEvidence = sourceEvidenceFor(target, input.assets, input.evidenceBindings);
    if (!sourceEvidence.length) continue;
    const anchor = candidates[0].node;
    proposals.push({
      id: `path-proposal-${stableHash(`${input.snapshotId}:${target.id}`)}`,
      policyId: "vnext-personal-path-node-proposer-v3",
      generatedFromSnapshotId: input.snapshotId,
      semanticNodeId: target.id,
      title: target.label,
      summary: `${target.summary}；这是岗位要求映射形成的学习节点候选，关系仍需学习者检查。`.slice(0, 260),
      aliases: target.aliases.slice(0, 8),
      domains: [anchor.domains[0] || target.label].filter(Boolean),
      stage: anchor.stage === "research" ? "advanced" : anchor.stage,
      order: anchor.order + 1,
      sourceUrls: sourceEvidence.map((item) => item.url),
      sourceEvidence,
      connections: [{
        nodeId: anchor.id,
        kind: "co_learning",
        rationale: `它与“${anchor.title}”主题邻近，暂列为待确认共学关系；岗位映射不证明硬前置。`,
      }],
      requiresLearnerConfirmation: true,
      masteryUnchanged: true,
    });
  }

  return {
    protocolVersion: "learnflow-learning-path/v1",
    authority: "learnflow",
    retrievalPolicyId: "vnext-learning-path-retrieval-v3",
    generatedFromSnapshotId: input.snapshotId,
    bindings,
    proposals,
  };
}
