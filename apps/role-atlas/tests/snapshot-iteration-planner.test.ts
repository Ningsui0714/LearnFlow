import assert from "node:assert/strict";
import test from "node:test";
import { bundledRoleSnapshot } from "@/lib/snapshots/bundled-role-adapter";
import { inspectSnapshot } from "@/lib/iteration/inspector";
import { createIterationContract, discoverIterationOpportunities } from "@/lib/iteration/planner";
import type { IterationFinding, SnapshotIterationRequest } from "@/lib/iteration/types";
import { createColdStartDeepResearchRequest, createColdStartRiskRepairRequest } from "@/lib/iteration/automatic-followup";
import { buildEventKindSchema } from "@/lib/build/events";

function request(profile: SnapshotIterationRequest["initiativeProfile"], targetIds: string[] = []): SnapshotIterationRequest {
  const result = bundledRoleSnapshot();
  return {
    runId: `iteration-${profile}`,
    snapshotRef: { snapshotId: result.snapshot.id },
    initiativeProfile: profile,
    prompt: profile === "autonomous" ? "" : "重点研究指定任务",
    targetIds,
    supplementalSources: [],
    webResearch: true,
    maxRounds: 2,
    sourceLimit: 12,
    maxWorkItems: 10,
  };
}

test("三种发起方式共享契约但具有不同的自动发现边界", () => {
  const result = bundledRoleSnapshot();
  const inspection = inspectSnapshot(result, { now: `${result.snapshot.asOf}T12:00:00Z` });
  const target = result.semantic.nodes.find((node) => node.type === "task")!.id;
  const unrelated = result.semantic.nodes.find((node) => node.type === "knowledge_skill")!.id;
  const additions: IterationFinding[] = [
    { id: "finding:target", layer: "coverage", classification: "research", severity: "warning", code: "TARGET_GAP", title: "目标缺口", detail: "目标节点缺口", impact: "影响目标", targetIds: [target], evidenceBindingIds: [], confidence: 0.9, suggestedAction: "research", hardBlocker: false },
    { id: "finding:unrelated", layer: "coverage", classification: "research", severity: "warning", code: "OTHER_GAP", title: "其他缺口", detail: "其他节点缺口", impact: "影响其他", targetIds: [unrelated], evidenceBindingIds: [], confidence: 0.9, suggestedAction: "research", hardBlocker: false },
    { id: "finding:hard", layer: "protocol", classification: "invariant", severity: "error", code: "DANGLING_SEMANTIC_EDGE", title: "协议错误", detail: "必须处理", impact: "查询失败", targetIds: [unrelated], evidenceBindingIds: [], confidence: 1, suggestedAction: "automatic", hardBlocker: true },
  ];
  const enriched = { ...inspection, findings: [...inspection.findings, ...additions], hardBlockers: [...inspection.hardBlockers, additions[2]] };
  const directed = request("user_directed", [target]);
  const directedOps = discoverIterationOpportunities({ request: directed, contract: createIterationContract(directed, result), inspection: enriched });
  assert.ok(directedOps.some((item) => item.findingIds.includes("finding:target")));
  assert.equal(directedOps.some((item) => item.findingIds.includes("finding:unrelated")), false);
  assert.ok(directedOps.some((item) => item.findingIds.includes("finding:hard")), "协议不变量不因定向范围而被忽略");

  const promptOnly = request("user_directed");
  const promptOnlyOps = discoverIterationOpportunities({ request: promptOnly, contract: createIterationContract(promptOnly, result), inspection: enriched });
  assert.ok(promptOnlyOps.some((item) => item.origin === "user"));
  assert.equal(promptOnlyOps.some((item) => item.findingIds.includes("finding:unrelated")), false, "纯提示词定向不应偷偷扩成全局软性扫描");

  const autonomous = request("autonomous");
  const autoOps = discoverIterationOpportunities({ request: autonomous, contract: createIterationContract(autonomous, result), inspection: enriched });
  assert.ok(autoOps.some((item) => item.findingIds.includes("finding:unrelated")));

  const guided = request("co_guided", [target]);
  const contract = createIterationContract(guided, result);
  assert.equal(contract.budgets.graphRadius, 2);
  assert.match(contract.objective, /指定任务/u);
});

test("迭代功能类型将工作限定为时效、深研或风险修复", () => {
  const result = bundledRoleSnapshot();
  const freshness = { ...request("co_guided"), mode: "freshness" as const };
  const deep = { ...request("co_guided"), mode: "deep_research" as const };
  const repair = { ...request("co_guided"), mode: "risk_repair" as const };
  assert.deepEqual(createIterationContract(freshness, result).changeIntents, ["refresh", "verify"]);
  assert.deepEqual(createIterationContract(deep, result).changeIntents, ["expand", "verify"]);
  assert.deepEqual(createIterationContract(repair, result).changeIntents, ["repair", "verify"]);
});

test("冷启动后自动串联重要深研与全量风险修复", () => {
  const common = { runId: "cold-start-followup", snapshotId: "snapshot:full", projectId: "project:one", conversationId: "conversation:one" };
  const deep = createColdStartDeepResearchRequest(common);
  assert.equal(deep.mode, "deep_research");
  assert.equal(deep.initiativeProfile, "autonomous");
  assert.equal(deep.webResearch, true);
  assert.equal(deep.maxWorkItems, 5);
  assert.match(deep.prompt, /3—5 个/u);

  const repair = createColdStartRiskRepairRequest({ ...common, snapshotId: "snapshot:researched" });
  assert.equal(repair.snapshotRef.snapshotId, "snapshot:researched");
  assert.equal(repair.mode, "risk_repair");
  assert.equal(repair.webResearch, false);
  assert.equal(repair.maxWorkItems, 16);
  for (const kind of [
    "build.followup.deep_research.started",
    "build.followup.deep_research.completed",
    "build.followup.deep_research.skipped",
    "build.followup.risk_repair.started",
    "build.followup.risk_repair.completed",
    "build.followup.failed",
  ]) assert.equal(buildEventKindSchema.safeParse(kind).success, true);
});

test("风险修复模式不会把深度研究工作偷偷混入全量修复", () => {
  const result = bundledRoleSnapshot();
  const inspection = inspectSnapshot(result, { now: `${result.snapshot.asOf}T12:00:00Z` });
  const target = result.semantic.nodes.find(node => node.type === "task")!.id;
  const semanticResearch: IterationFinding = {
    id: "finding:semantic-research", layer: "semantic", classification: "research", severity: "warning",
    code: "BOUNDARY_RESEARCH", title: "边界研究", detail: "需要补研", impact: "影响边界", targetIds: [target],
    evidenceBindingIds: [], confidence: 0.8, suggestedAction: "research", hardBlocker: false,
  };
  const automaticRepair: IterationFinding = {
    id: "finding:automatic-repair", layer: "semantic", classification: "core_usability", severity: "error",
    code: "DUPLICATE", title: "重复修复", detail: "可确定修复", impact: "影响读取", targetIds: [target],
    evidenceBindingIds: [], confidence: 1, suggestedAction: "automatic", hardBlocker: false,
  };
  const repairRequest = { ...request("autonomous"), mode: "risk_repair" as const };
  const contract = createIterationContract(repairRequest, result);
  const opportunities = discoverIterationOpportunities({
    request: repairRequest,
    contract,
    inspection: { ...inspection, findings: [semanticResearch, automaticRepair] },
  });
  assert.ok(opportunities.some(item => item.findingIds.includes(automaticRepair.id)));
  assert.equal(opportunities.some(item => item.findingIds.includes(semanticResearch.id)), false);
});
