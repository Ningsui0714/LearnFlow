import { readFile } from "node:fs/promises";
import path from "node:path";

import { SnapshotRoleRuntime } from "../lib/agent/snapshot-runtime";
import { reconstructBuildResult } from "../lib/packages/compiler";
import type { StaticRolePackageBundle } from "../lib/packages/types";
import { validateBuildResult, validatePackageBundle } from "../lib/packages/validator";

const root = path.resolve(import.meta.dirname, "..");
const packageRoot = path.join(root, "packages/golden/llm-app-engineer/1.0.0");
const evalRoot = path.join(root, "evals/golden/llm-app-engineer/frozen-v1");
const readJson = async (file: string) => JSON.parse(await readFile(file, "utf8"));
const unique = <T>(values: T[]) => [...new Set(values)];

const manifest = await readJson(path.join(packageRoot, "manifest.json"));
const componentEntries = await Promise.all(Object.values(manifest.entrypoints).map(async (relative) => [relative, await readFile(path.join(packageRoot, String(relative)), "utf8")] as const));
const bundle: StaticRolePackageBundle = { manifest, components: Object.fromEntries(componentEntries) };
const bundleValidation = await validatePackageBundle(bundle);
const result = reconstructBuildResult(bundle);
const buildValidation = validateBuildResult(result);
const structuralEval = await readJson(path.join(evalRoot, "structural-assertions.json"));

const semanticNodes = result.semantic.nodes;
const semanticEdges = result.semantic.edges;
const processObjects = [...result.process.scenarios, ...result.process.nodes];
const allEndpointIds = new Set([...semanticNodes, ...processObjects].map((item) => item.id));
const objectIds = [
  ...result.sources.assets.map((item) => item.id),
  ...result.sources.segments.map((item) => item.id),
  ...result.sources.evidenceBindings.map((item) => item.id),
  ...semanticNodes.map((item) => item.id),
  ...semanticEdges.map((item) => item.id),
  ...result.semantic.claims.map((item) => item.id),
  ...processObjects.map((item) => item.id),
  ...result.process.edges.map((item) => item.id),
  ...result.process.bridges.map((item) => item.id),
  ...result.snapshot.sections.map((item) => item.id),
];
const knownReferences = new Set(objectIds);
const sourceIds = new Set(result.sources.assets.map((item) => item.id));
const segmentIds = new Set(result.sources.segments.map((item) => item.id));
const targetIds = new Set([
  ...semanticNodes.map((item) => item.id),
  ...semanticEdges.map((item) => item.id),
  ...result.semantic.claims.map((item) => item.id),
  ...processObjects.map((item) => item.id),
  ...result.process.edges.map((item) => item.id),
  ...result.process.bridges.map((item) => item.id),
]);

type Assertion = Record<string, any>;
function relationExists(source: string, type: string, target: string) {
  return semanticEdges.some((edge) => edge.source === source && edge.type === type && edge.target === target);
}
function countType(type: string) {
  return semanticNodes.filter((node) => node.type === type).length;
}
function within(value: number, assertion: Assertion) {
  return value >= Number(assertion.min ?? value) && value <= Number(assertion.max ?? value);
}
function evaluate(assertion: Assertion) {
  switch (assertion.kind) {
    case "manifest_equals": return manifest[assertion.path] === assertion.expected;
    case "component_hashes_valid": return bundleValidation.hardErrors.every((error) => !error.includes("哈希") && !error.includes("组件不存在"));
    case "root_hash_valid": return bundleValidation.hardErrors.every((error) => !error.includes("root hash"));
    case "global_ids_unique": return new Set(objectIds).size === objectIds.length;
    case "semantic_node_type_count": return within(countType(assertion.nodeType), assertion);
    case "process_scenario_count": return within(result.process.scenarios.length, assertion);
    case "required_node": return semanticNodes.some((node) => node.id === assertion.id);
    case "required_relation": return relationExists(assertion.source, assertion.type, assertion.target);
    case "all_semantic_edges_have_valid_endpoints": return semanticEdges.every((edge) => allEndpointIds.has(edge.source) && allEndpointIds.has(edge.target));
    case "all_process_edges_have_valid_endpoints": return result.process.edges.every((edge) => allEndpointIds.has(edge.source) && allEndpointIds.has(edge.target));
    case "all_bridges_have_valid_endpoints": return result.process.bridges.every((bridge) => allEndpointIds.has(bridge.processNodeId) && allEndpointIds.has(bridge.semanticNodeId));
    case "no_isolated_semantic_nodes": {
      const excluded = new Set(assertion.excludeTypes || []);
      return semanticNodes.filter((node) => !excluded.has(node.type)).every((node) => semanticEdges.some((edge) => edge.source === node.id || edge.target === node.id));
    }
    case "all_tasks_have_capability_mapping": return semanticNodes.filter((node) => node.type === "task").every((task) => semanticEdges.filter((edge) => edge.type === "transfers_across" && edge.target === task.id && semanticNodes.find((node) => node.id === edge.source)?.type === "capability").length >= assertion.min);
    case "all_tasks_have_unit_mapping": return semanticNodes.filter((node) => node.type === "task").every((task) => semanticEdges.filter((edge) => edge.type === "demonstrated_in" && edge.target === task.id).length >= assertion.min);
    case "all_tasks_have_learning_elements": return semanticNodes.filter((node) => node.type === "task").every((task) => semanticEdges.filter((edge) => edge.type === "supports_task" && edge.target === task.id).length >= assertion.min);
    case "all_tasks_have_process_bridge": return semanticNodes.filter((node) => node.type === "task").every((task) => result.process.bridges.filter((bridge) => bridge.type === "realizes_task" && bridge.semanticNodeId === task.id).length >= assertion.min);
    case "capabilities_transfer_across_tasks": return semanticNodes.filter((node) => node.type === "capability").every((capability) => new Set(semanticEdges.filter((edge) => edge.type === "transfers_across" && edge.source === capability.id).map((edge) => edge.target)).size >= assertion.minTasks);
    case "all_units_have_capability_parent": return semanticNodes.filter((node) => node.type === "capability_unit").every((unit) => within(semanticEdges.filter((edge) => edge.type === "decomposes_into" && edge.target === unit.id).length, assertion));
    case "all_units_have_task_mapping": return semanticNodes.filter((node) => node.type === "capability_unit").every((unit) => semanticEdges.filter((edge) => edge.type === "demonstrated_in" && edge.source === unit.id).length >= assertion.min);
    case "all_learning_elements_have_kind": return semanticNodes.filter((node) => node.type === "knowledge_skill").every((item) => assertion.allowed.includes(item.learningKind));
    case "all_learning_elements_have_task_mapping": return semanticNodes.filter((node) => node.type === "knowledge_skill").every((item) => semanticEdges.filter((edge) => edge.type === "supports_task" && edge.source === item.id).length >= assertion.min);
    case "all_accepted_semantic_nodes_have_evidence": return semanticNodes.filter((node) => node.lifecycle === "stable").every((node) => node.evidenceBindingIds.length >= assertion.minBindings);
    case "all_accepted_semantic_edges_have_evidence": return semanticEdges.filter((edge) => edge.lifecycle === "stable").every((edge) => edge.evidenceBindingIds.length >= assertion.minBindings);
    case "all_process_objects_have_evidence": return processObjects.every((item) => item.evidenceBindingIds.length >= assertion.minBindings);
    case "all_process_relations_have_evidence": return result.process.edges.every((edge) => edge.evidenceBindingIds.length >= assertion.minBindings);
    case "all_bridges_have_evidence": return result.process.bridges.every((bridge) => (bridge.evidenceBindingIds || []).length >= assertion.minBindings);
    case "all_segments_have_source_and_locator": return result.sources.segments.every((segment) => sourceIds.has(segment.sourceId) && Boolean(segment.locator));
    case "all_bindings_resolve": return result.sources.evidenceBindings.every((binding) => sourceIds.has(binding.sourceId) && segmentIds.has(binding.segmentId) && targetIds.has(binding.targetId));
    case "all_claims_have_status": return result.semantic.claims.every((claim) => assertion.allowed.includes(claim.status));
    case "all_claims_have_evidence": return result.semantic.claims.every((claim) => claim.evidenceSegmentIds.length >= assertion.minSegments);
    case "accepted_claim_count": return result.semantic.claims.filter((claim) => claim.status === "accepted").length >= assertion.min;
    case "disputed_claim_count": return result.semantic.claims.filter((claim) => claim.status === "disputed").length >= assertion.min;
    case "rejected_claim_count": return result.semantic.claims.filter((claim) => claim.status === "rejected").length >= assertion.min;
    case "source_count": return result.sources.assets.length >= assertion.min;
    case "independent_enterprise_source_count": return new Set(result.sources.assets.filter((source) => source.sourceType === "job_posting").map((source) => source.publisher || source.id)).size >= assertion.min;
    case "all_scenarios_have_trigger_outcome_acceptance": return result.process.scenarios.every((scenario) => Boolean(scenario.trigger && scenario.outcome && scenario.acceptanceCriteria?.length));
    case "all_scenarios_have_actor_input_output": return result.process.scenarios.every((scenario) => Boolean(scenario.actorRefs?.length && scenario.inputRefs?.length && scenario.outputRefs?.length));
    case "process_forest_contains_flow_type": return result.process.edges.filter((edge) => edge.type === assertion.flowType).length >= assertion.min;
    case "process_forest_contains_event_type": return result.process.nodes.filter((node) => node.eventType === assertion.eventType).length >= assertion.min;
    default: throw new Error(`Unknown assertion kind: ${assertion.kind}`);
  }
}

const assertionResults: Array<{ id: string; passed: boolean }> = structuralEval.assertions.map((assertion: Assertion) => ({ id: assertion.id, passed: Boolean(evaluate(assertion)) }));
const forbiddenResults: Array<{ id: string; passed: boolean; matches: string[] }> = structuralEval.forbiddenRelations.map((forbidden: Assertion, index: number) => {
  const matches = semanticEdges.filter((edge) => {
    const sourceType = semanticNodes.find((node) => node.id === edge.source)?.type;
    const targetType = semanticNodes.find((node) => node.id === edge.target)?.type;
    return sourceType === forbidden.sourceType && edge.type === forbidden.type && targetType === forbidden.targetType;
  });
  return { id: `FORBID-${String(index + 1).padStart(3, "0")}`, passed: matches.length === 0, matches: matches.map((edge) => edge.id) };
});

async function readJsonl(name: string) {
  const content = await readFile(path.join(evalRoot, name), "utf8");
  return content.split(/\r?\n/u).filter(Boolean).map((line, index) => {
    try { return JSON.parse(line); } catch (error) { throw new Error(`${name}:${index + 1}: ${String(error)}`); }
  });
}
const semanticCases = await readJsonl("semantic-cases.jsonl");
const evidenceCases = await readJsonl("evidence-cases.jsonl");
const agentQa = await readJsonl("agent-qa.jsonl");
const evalCases = [...semanticCases, ...evidenceCases, ...agentQa];
const evalCaseIds = evalCases.map((item) => item.id);
const evalReferenceErrors: string[] = [];
function inspectReference(value: unknown, trail: string[]) {
  if (typeof value === "string" && /^(?:(?:role|occupation|chain|family|related-role|task|cap|unit|knowledge|skill|scenario|event|actor|object|artifact|tool|quality|risk):|(?:CLM|SRC|SEG)-)/u.test(value)) {
    if (!knownReferences.has(value)) evalReferenceErrors.push(`${trail.join(".")}: ${value}`);
    return;
  }
  if (Array.isArray(value)) value.forEach((item, index) => inspectReference(item, [...trail, String(index)]));
  else if (value && typeof value === "object") Object.entries(value).forEach(([key, item]) => inspectReference(item, [...trail, key]));
}
evalCases.forEach((item) => inspectReference(item, [item.id]));

const runtime = new SnapshotRoleRuntime(result);
const trace = await runtime.execute({ name: "trace_work_process", args: { start: "task:llmapp:build-agent-integration", depth: 8 } }, "golden-validation-trace");
const evidence = await runtime.execute({ name: "inspect_role_evidence", args: { target: "task:llmapp:build-rag" } }, "golden-validation-evidence");
const graph = await runtime.execute({ name: "query_role_graph", args: { start: "role:llm-app-engineer", depth: 2, direction: "outgoing" } }, "golden-validation-graph");
const runtimeChecks = [
  { id: "RUNTIME-001", passed: trace.ok && (trace.data as any).scenarios.length >= 1, detail: "task to process trace" },
  { id: "RUNTIME-002", passed: trace.ok && trace.citations.some((citation) => citation.artifactKind === "work_process"), detail: "process citations" },
  { id: "RUNTIME-003", passed: evidence.ok && (evidence.data as any).records[0].bindings.length >= 1, detail: "evidence drill-down" },
  { id: "RUNTIME-004", passed: graph.ok && (graph.data as any).relations.length >= 1, detail: "semantic graph query" },
];

const failures = [
  ...bundleValidation.hardErrors.map((detail) => ({ id: "BUNDLE", detail })),
  ...buildValidation.hardErrors.map((detail) => ({ id: "BUILD", detail })),
  ...assertionResults.filter((item) => !item.passed).map((item) => ({ id: item.id, detail: "structural assertion failed" })),
  ...forbiddenResults.filter((item) => !item.passed).map((item) => ({ id: item.id, detail: item.matches.join(", ") })),
  ...(new Set(evalCaseIds).size === evalCaseIds.length ? [] : [{ id: "EVAL-IDS", detail: "duplicate eval case IDs" }]),
  ...evalReferenceErrors.map((detail) => ({ id: "EVAL-REF", detail })),
  ...runtimeChecks.filter((item) => !item.passed).map((item) => ({ id: item.id, detail: item.detail })),
];
const report = {
  valid: failures.length === 0,
  package: { packageId: manifest.packageId, packageVersion: manifest.packageVersion, snapshotId: manifest.snapshotId, rootHash: manifest.rootHash },
  protocol: { bundleValid: bundleValidation.valid, buildHardErrors: buildValidation.hardErrors.length },
  structural: { passed: assertionResults.filter((item) => item.passed).length, total: assertionResults.length, forbiddenPassed: forbiddenResults.filter((item) => item.passed).length, forbiddenTotal: forbiddenResults.length },
  frozenEval: { semanticCases: semanticCases.length, evidenceCases: evidenceCases.length, agentQaCases: agentQa.length, uniqueIds: new Set(evalCaseIds).size === evalCaseIds.length, referenceErrors: evalReferenceErrors.length },
  runtime: runtimeChecks,
  counts: { semanticNodes: semanticNodes.length, semanticEdges: semanticEdges.length, processScenarios: result.process.scenarios.length, processNodes: result.process.nodes.length, processEdges: result.process.edges.length, sources: result.sources.assets.length, segments: result.sources.segments.length, claims: result.semantic.claims.length, evidenceBindings: result.sources.evidenceBindings.length },
  failures,
};
console.log(JSON.stringify(report, null, 2));
if (!report.valid) process.exitCode = 1;
