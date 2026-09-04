import type { IterationEvent, IterationEventPhase } from "./types";

export type IterationActivityStatus = "running" | "completed" | "failed";

export type IterationActivity = {
  id: string;
  kind: "message" | "tool" | "milestone";
  phase: IterationEventPhase;
  status: IterationActivityStatus;
  title: string;
  summary: string;
  toolName?: string;
  startedAt: string;
  endedAt?: string;
  elapsedMs: number;
  details: Array<{ label: string; value: string }>;
  seq: number;
};

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function objectList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is UnknownRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function elapsed(startedAt: string, endedAt: string | undefined, now: number) {
  const start = Date.parse(startedAt);
  const end = endedAt ? Date.parse(endedAt) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return Math.max(0, end - start);
}

function eventByKind(events: IterationEvent[], kind: IterationEvent["kind"]) {
  return events.find((event) => event.kind === kind);
}

function searchEnd(events: IterationEvent[], queryId: string) {
  return events.find((event) => (
    event.kind === "iteration.search.completed" || event.kind === "iteration.search.failed"
  ) && stringValue(event.payload.queryId) === queryId);
}

function detail(label: string, value: unknown) {
  const text = typeof value === "number" ? String(value) : stringValue(value);
  return text ? { label, value: text } : null;
}

function compactDetails(items: Array<{ label: string; value: string } | null>) {
  return items.filter((item): item is { label: string; value: string } => Boolean(item));
}

export function formatIterationElapsed(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1_000));
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分钟`;
}

export function iterationRunElapsed(events: IterationEvent[], now = Date.now()) {
  if (!events.length) return 0;
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const startedAt = Date.parse(ordered[0].time);
  const terminal = ordered.findLast((event) => event.kind === "iteration.run.completed" || event.kind === "iteration.run.failed");
  const endedAt = terminal ? Date.parse(terminal.time) : now;
  if (!Number.isFinite(startedAt) || !Number.isFinite(endedAt)) return 0;
  return Math.max(0, endedAt - startedAt);
}

export function currentIterationThinking(events: IterationEvent[]) {
  const last = [...events].sort((a, b) => a.seq - b.seq).at(-1);
  if (!last) return "正在准备迭代运行环境";
  if (last.kind === "iteration.run.failed") return "运行已停止，正在保留诊断记录";
  if (last.kind === "iteration.run.completed") return "本轮迭代已经完成";
  if (last.kind === "iteration.snapshot.created") return "正在保存完成记录并准备新快照入口";
  if (last.kind === "iteration.snapshot.write.started") return "正在写入新的不可变静态快照";
  if (last.kind === "iteration.evaluation.started" || last.kind === "iteration.evaluation.completed" || last.kind === "iteration.round.completed") return "正在回归检查，并判断本轮增量是否值得生成新版本";
  if (last.kind === "iteration.consolidation.started" || last.kind === "iteration.patch.proposed" || last.kind === "iteration.patch.applied") return "正在聚类重复概念，并应用可追踪的安全修复";
  if (last.kind === "iteration.candidate.rebuild.started" || last.kind === "iteration.candidate.rebuilt") return "正在重建语义图、事理森林、证据层和快照正文";
  if (last.kind === "iteration.search.started" || last.kind === "iteration.search.completed" || last.kind === "iteration.search.failed" || last.kind === "iteration.research.completed") return "正在并行检索、比较来源并过滤低价值信息";
  if (last.kind === "iteration.research.plan.created" || last.kind === "iteration.work.item.started" || last.kind === "iteration.work.item.completed") return "正在把研究目标拆成有边界的工具任务";
  if (last.kind === "iteration.opportunities.created" || last.kind === "iteration.work.plan.created") return "正在选择信息增益最高、风险可控的工作组合";
  if (last.kind === "iteration.inspection.started" || last.kind === "iteration.finding.discovered" || last.kind === "iteration.inspection.completed") return "正在检查节点语义、关系覆盖、证据绑定和事理完整性";
  if (last.kind === "iteration.contract.created") return "正在理解目标，并决定本轮要检查哪些范围";
  return "正在固定当前快照和迭代边界";
}

export function buildIterationActivityFeed(events: IterationEvent[], now = Date.now()): IterationActivity[] {
  if (!events.length) return [];
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const activities: IterationActivity[] = [];
  const runStarted = eventByKind(ordered, "iteration.run.started") || ordered[0];
  const searchProvider = stringValue(runStarted.payload.searchProvider, "web");
  const snapshotResolved = eventByKind(ordered, "iteration.snapshot.resolved");
  if (snapshotResolved) {
    activities.push({
      id: "read-snapshot",
      kind: "tool",
      phase: "contract",
      status: "completed",
      title: "读取并固定当前岗位快照",
      summary: "后续研究都以这份不可变快照为基准，旧版本不会被原地覆盖。",
      toolName: "snapshot.read",
      startedAt: runStarted.time,
      endedAt: snapshotResolved.time,
      elapsedMs: elapsed(runStarted.time, snapshotResolved.time, now),
      details: compactDetails([
        detail("快照", snapshotResolved.payload.snapshotId),
        detail("版本", snapshotResolved.payload.version),
        detail("时点", snapshotResolved.payload.asOf),
      ]),
      seq: snapshotResolved.seq,
    });
  }

  const contractEvent = eventByKind(ordered, "iteration.contract.created");
  if (contractEvent) {
    const contract = record(contractEvent.payload.contract);
    const intents = stringList(contract.changeIntents);
    activities.push({
      id: "contract",
      kind: "message",
      phase: "contract",
      status: "completed",
      title: "我先明确本轮要解决什么",
      summary: stringValue(contract.objective, "已建立本轮目标、研究边界和停止条件。"),
      startedAt: snapshotResolved?.time || runStarted.time,
      endedAt: contractEvent.time,
      elapsedMs: elapsed(snapshotResolved?.time || runStarted.time, contractEvent.time, now),
      details: compactDetails([
        detail("功能类型", contract.mode === "freshness" ? "时效迭代" : contract.mode === "risk_repair" ? "风险修复" : contract.mode === "deep_research" ? "深度研究" : "自动判定"),
        detail("处理意图", intents.join("、")),
        detail("范围", contract.budgets && record(contract.budgets).graphRadius === "global" ? "全局快照" : `目标节点附近 ${numberValue(record(contract.budgets).graphRadius)} 层`),
        detail("目标时点", contract.targetAsOf),
      ]),
      seq: contractEvent.seq,
    });
  }

  const inspectionStarted = eventByKind(ordered, "iteration.inspection.started");
  const inspectionCompleted = eventByKind(ordered, "iteration.inspection.completed");
  if (inspectionStarted) {
    const payload = inspectionCompleted?.payload || {};
    const findingCount = numberValue(payload.findingCount);
    const hardBlockers = numberValue(payload.hardBlockerCount);
    activities.push({
      id: "inspect-snapshot",
      kind: "tool",
      phase: "inspect",
      status: inspectionCompleted ? "completed" : "running",
      title: "检查快照结构与可用性",
      summary: inspectionCompleted
        ? `完成语义、覆盖、证据、时点、事理和 Agent 可用性检查；发现 ${findingCount} 个可跟进问题，${hardBlockers} 个协议阻断。`
        : "正在检查同维度语义重合、任务—技能覆盖、证据绑定、事理过程和协议完整性。",
      toolName: "snapshot.inspect",
      startedAt: inspectionStarted.time,
      endedAt: inspectionCompleted?.time,
      elapsedMs: elapsed(inspectionStarted.time, inspectionCompleted?.time, now),
      details: compactDetails([
        detail("检查范围", inspectionStarted.payload.scope === "global" ? "全局快照" : `${numberValue(inspectionStarted.payload.scope)} 层邻域`),
        inspectionCompleted ? detail("结构发现", `${findingCount} 项`) : null,
        inspectionCompleted ? detail("协议状态", hardBlockers ? `${hardBlockers} 个阻断` : "有效") : null,
      ]),
      seq: inspectionStarted.seq,
    });
  }

  const workPlan = eventByKind(ordered, "iteration.work.plan.created");
  if (workPlan) {
    const items = objectList(workPlan.payload.workItems);
    const titles = items.slice(0, 4).map((item) => stringValue(item.title)).filter(Boolean);
    activities.push({
      id: "plan-work",
      kind: "tool",
      phase: "plan",
      status: "completed",
      title: "形成有界工作计划",
      summary: `已选择 ${items.length} 个本轮值得处理的工作项，按信息价值、依赖关系和研究成本安排顺序。`,
      toolName: "iteration.plan",
      startedAt: inspectionCompleted?.time || workPlan.time,
      endedAt: workPlan.time,
      elapsedMs: elapsed(inspectionCompleted?.time || workPlan.time, workPlan.time, now),
      details: compactDetails([
        detail("优先工作", titles.join("；")),
        detail("工作项数", items.length),
      ]),
      seq: workPlan.seq,
    });
  }

  const researchPlan = eventByKind(ordered, "iteration.research.plan.created");
  if (researchPlan) {
    const plan = record(researchPlan.payload.plan);
    const queries = objectList(plan.queries);
    const skippedReason = stringValue(researchPlan.payload.skippedReason);
    activities.push({
      id: "plan-research",
      kind: "tool",
      phase: "research",
      status: "completed",
      title: queries.length ? "规划并行检索问题" : "判断本轮是否需要联网检索",
      summary: skippedReason || `已生成 ${queries.length} 个互补查询，将并行覆盖标准、招聘、实际工作、技术与教学资料。`,
      toolName: "research.plan",
      startedAt: workPlan?.time || researchPlan.time,
      endedAt: researchPlan.time,
      elapsedMs: elapsed(workPlan?.time || researchPlan.time, researchPlan.time, now),
      details: compactDetails([
        detail("查询数", queries.length),
        detail("策略", queries.length ? "最多 4 路并行，检索后去重和定向抽取" : "使用现有证据与结构检查结果"),
      ]),
      seq: researchPlan.seq,
    });
  }

  for (const searchStarted of ordered.filter((event) => event.kind === "iteration.search.started")) {
    const queryId = stringValue(searchStarted.payload.queryId, `seq-${searchStarted.seq}`);
    const end = searchEnd(ordered, queryId);
    const failed = end?.kind === "iteration.search.failed";
    const providerElapsed = end?.kind === "iteration.search.completed" ? numberValue(end.payload.responseTimeMs, -1) : -1;
    activities.push({
      id: `search:${queryId}`,
      kind: "tool",
      phase: "research",
      status: failed ? "failed" : end ? "completed" : "running",
      title: "检索外部岗位证据",
      summary: stringValue(searchStarted.payload.query, "正在执行定向搜索。"),
      toolName: `${searchProvider}.search`,
      startedAt: searchStarted.time,
      endedAt: end?.time,
      elapsedMs: providerElapsed >= 0 ? providerElapsed : elapsed(searchStarted.time, end?.time, now),
      details: compactDetails([
        detail("类别", searchStarted.payload.category),
        end?.kind === "iteration.search.completed" ? detail("返回", `${numberValue(end.payload.resultCount)} 条候选`) : null,
        failed ? detail("失败原因", end?.payload.message) : null,
        end?.kind === "iteration.search.completed" ? detail("请求 ID", end.payload.requestId) : null,
      ]),
      seq: searchStarted.seq,
    });
  }

  const researchCompleted = eventByKind(ordered, "iteration.research.completed");
  if (researchCompleted) {
    activities.push({
      id: "research-completed",
      kind: "milestone",
      phase: "research",
      status: "completed",
      title: "完成来源筛选与归集",
      summary: `从 ${numberValue(researchCompleted.payload.candidateCount)} 个候选中保留 ${numberValue(researchCompleted.payload.selectedSourceCount)} 个本轮可用来源。`,
      startedAt: researchPlan?.time || researchCompleted.time,
      endedAt: researchCompleted.time,
      elapsedMs: elapsed(researchPlan?.time || researchCompleted.time, researchCompleted.time, now),
      details: compactDetails([
        detail("选中来源", researchCompleted.payload.selectedSourceCount),
        detail("失败分支", Array.isArray(researchCompleted.payload.failures) ? researchCompleted.payload.failures.length : 0),
      ]),
      seq: researchCompleted.seq,
    });
  }

  const rebuildStarted = eventByKind(ordered, "iteration.candidate.rebuild.started");
  const rebuilt = eventByKind(ordered, "iteration.candidate.rebuilt");
  if (rebuildStarted) {
    activities.push({
      id: "rebuild-candidate",
      kind: "tool",
      phase: "rebuild",
      status: rebuilt ? "completed" : "running",
      title: "重建完整岗位候选包",
      summary: rebuilt
        ? `模型已同步重建语义图、事理森林、证据层与快照正文：${numberValue(rebuilt.payload.nodes)} 个节点、${numberValue(rebuilt.payload.scenarios)} 个工作场景。`
        : "正在让模型基于原快照和新增证据重建完整候选，而不是只追加零散节点。",
      toolName: stringValue(rebuildStarted.payload.tool, "snapshot.rebuild"),
      startedAt: rebuildStarted.time,
      endedAt: rebuilt?.time,
      elapsedMs: elapsed(rebuildStarted.time, rebuilt?.time, now),
      details: compactDetails([
        detail("模型", rebuildStarted.payload.model),
        detail("输入来源", rebuildStarted.payload.sourceCount),
        rebuilt ? detail("语义关系", rebuilt.payload.edges) : null,
        rebuilt ? detail("证据来源", rebuilt.payload.sources) : null,
      ]),
      seq: rebuildStarted.seq,
    });
  }

  const consolidationStarted = eventByKind(ordered, "iteration.consolidation.started");
  const patchProposed = eventByKind(ordered, "iteration.patch.proposed");
  const patchApplied = eventByKind(ordered, "iteration.patch.applied");
  if (consolidationStarted) {
    const patch = record((patchApplied || patchProposed)?.payload.patch);
    const operations = Array.isArray(patch.operations) ? patch.operations.length : 0;
    const end = patchApplied || patchProposed;
    activities.push({
      id: "consolidate-candidate",
      kind: "tool",
      phase: "consolidate",
      status: end ? "completed" : "running",
      title: "聚类概念并应用结构修复",
      summary: end
        ? operations ? `已应用 ${operations} 个确定性修复，并同步迁移相关引用。` : "没有发现需要自动改写的协议级结构问题；软性问题保留为后续研究议程。"
        : "正在检查重复节点、悬空关系、非法环和证据引用，修复不会覆盖原始快照。",
      toolName: "graph.consolidate",
      startedAt: consolidationStarted.time,
      endedAt: end?.time,
      elapsedMs: elapsed(consolidationStarted.time, end?.time, now),
      details: compactDetails([
        detail("修复操作", operations),
        detail("策略", "确定性修复 + 引用迁移 + 保留软性发现"),
      ]),
      seq: consolidationStarted.seq,
    });
  }

  const evaluationStarted = eventByKind(ordered, "iteration.evaluation.started");
  const evaluationCompleted = eventByKind(ordered, "iteration.evaluation.completed");
  if (evaluationStarted) {
    const evaluation = record(evaluationCompleted?.payload.evaluation);
    const gain = record(evaluation.informationGain);
    activities.push({
      id: "evaluate-candidate",
      kind: "tool",
      phase: "evaluate",
      status: evaluationCompleted ? "completed" : "running",
      title: "回归检查并评估信息增量",
      summary: evaluationCompleted
        ? `候选协议${evaluation.protocolValid ? "有效" : "存在阻断"}，信息增量 ${numberValue(gain.score).toFixed(1)}，${evaluation.meaningful ? "值得形成新快照" : "暂不生成新版本"}。`
        : "正在比较迭代前后结构、证据、事理覆盖和 Agent 可用性，并检查是否出现退化。",
      toolName: "snapshot.evaluate",
      startedAt: evaluationStarted.time,
      endedAt: evaluationCompleted?.time,
      elapsedMs: elapsed(evaluationStarted.time, evaluationCompleted?.time, now),
      details: compactDetails([
        evaluationCompleted ? detail("信息增量", numberValue(gain.score).toFixed(1)) : null,
        evaluationCompleted ? detail("核心回归", evaluation.coreRegression ? "发现" : "没有") : null,
        evaluationCompleted ? detail("版本决策", evaluation.meaningful ? "生成新快照" : "保留研究记录") : null,
      ]),
      seq: evaluationStarted.seq,
    });
  }

  const snapshotWrite = eventByKind(ordered, "iteration.snapshot.write.started");
  const snapshotCreated = eventByKind(ordered, "iteration.snapshot.created");
  if (snapshotWrite) {
    activities.push({
      id: "write-snapshot",
      kind: "tool",
      phase: "snapshot",
      status: snapshotCreated ? "completed" : "running",
      title: "写入新的不可变静态快照",
      summary: snapshotCreated ? "新版本、父快照关系和项目版本引用已经保存。" : "正在保存候选快照、运行记录和版本关系；当前快照不会被原地修改。",
      toolName: "snapshot.write",
      startedAt: snapshotWrite.time,
      endedAt: snapshotCreated?.time,
      elapsedMs: elapsed(snapshotWrite.time, snapshotCreated?.time, now),
      details: compactDetails([
        snapshotCreated ? detail("新快照", snapshotCreated.payload.candidateSnapshotId) : null,
        snapshotCreated ? detail("父快照", snapshotCreated.payload.parentSnapshotId) : null,
      ]),
      seq: snapshotWrite.seq,
    });
  }

  const failed = eventByKind(ordered, "iteration.run.failed");
  if (failed) {
    activities.push({
      id: "run-failed",
      kind: "message",
      phase: "system",
      status: "failed",
      title: "本轮运行没有完成",
      summary: stringValue(failed.payload.message, "运行失败，当前静态快照没有改变。"),
      startedAt: failed.time,
      endedAt: failed.time,
      elapsedMs: 0,
      details: [],
      seq: failed.seq,
    });
  }

  return activities.sort((a, b) => a.seq - b.seq);
}
