import { createModelInvoker } from "@/lib/agent/model";
import { createColdStartSkill } from "@/lib/build/graph";
import type { ColdStartBuildResult, ColdStartRequest, SourceInput } from "@/lib/build/types";
import { PROVIDERS, type ProviderConfig } from "@/lib/providers";

type Fixture = { roleTitle: string; roleDescription: string; sources: SourceInput[] };

const fixtures: Record<string, Fixture> = {
  backend: {
    roleTitle: "后端开发工程师",
    roleDescription: "关注服务交付、质量验证和线上运行的完整责任，而非只罗列编程语言。",
    sources: [
      { title: "后端服务交付记录", kind: "private_document", content: "后端开发工程师接收业务需求后，澄清接口调用方、数据边界和验收标准，设计 API 与数据模型，完成代码、自动化测试和接口文档。变更通过代码评审和集成测试后发布，交付可观测、可回滚的服务版本。" },
      { title: "线上事件复盘", kind: "workspace_observation", content: "告警显示订单接口错误率上升。值班工程师先确认影响范围并检查日志和指标，再定位连接池耗尽问题，实施限流和配置回滚；服务恢复后补充回归测试、监控阈值和事故复盘，交付修复版本与复盘报告。" },
    ],
  },
  sre: {
    roleTitle: "站点可靠性工程师",
    roleDescription: "关注可靠性目标、变更、容量和故障处置之间的真实工作循环。",
    sources: [
      { title: "可靠性工作规范", kind: "private_document", content: "站点可靠性工程师与业务团队定义 SLI、SLO 和错误预算，建立监控、告警和容量模型。上线前审查变更风险和回滚方案，输出可靠性评审结论；运行期依据错误预算决定继续发布或暂停变更。" },
      { title: "故障处置事件", kind: "workspace_observation", content: "核心服务延迟越过 SLO 后，值班人员确认用户影响、关联近期变更并组织响应；通过流量切换和版本回滚恢复服务，随后完成时间线、根因、改进动作和演练验证，交付事故报告与修复验证记录。" },
    ],
  },
  llm_algorithm: {
    roleTitle: "大模型算法工程师",
    roleDescription: "区分算法研究、数据与训练实验、模型评价和工程交付，不把工具名直接当作能力。",
    sources: [
      { title: "模型研发职责说明", kind: "private_document", content: "大模型算法工程师围绕业务目标定义模型实验问题，构建和审查训练数据，选择基线并设计训练方案。工程师记录实验配置、数据版本和评测结果，比较模型质量、成本与风险，交付可复现的模型候选和实验报告。" },
      { title: "模型迭代工作事件", kind: "workspace_observation", content: "离线评测发现特定领域问答准确率下降。工程师抽样分析失败案例，定位数据覆盖和训练目标问题，补充数据并运行对照实验；候选模型通过安全、质量和性能评测后进入灰度验证，若线上指标退化则回滚，最终交付模型版本、评测报告与风险说明。" },
    ],
  },
};

function normalized(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
}

function score(result: ColdStartBuildResult, elapsedMs: number) {
  const tasks = result.semantic.nodes.filter((node) => node.type === "task");
  const skills = result.semantic.nodes.filter((node) => node.type === "knowledge_skill");
  const capabilities = result.semantic.nodes.filter((node) => node.type === "capability");
  const labels = result.semantic.nodes.map((node) => `${node.type}:${normalized(node.label)}`);
  const duplicates = labels.length - new Set(labels).size;
  const taskSkillSources = new Set(result.semantic.edges.filter((edge) => edge.type === "requires_skill").map((edge) => edge.source));
  const taskProcessSources = new Set(result.process.bridges.filter((bridge) => bridge.type === "realizes_task").map((bridge) => bridge.semanticNodeId));
  const capabilityCoverage = capabilities.map((node) => result.semantic.edges.filter((edge) => edge.type === "requires_capability" && edge.target === node.id).length);
  const mentions = result.sources.mentions || [];
  return {
    elapsedMs,
    firstTaskSkeletonMs: result.build?.metrics.firstTaskSkeletonMs,
    sources: result.sources.assets.length,
    mentions: mentions.length,
    exactSpanCoverage: mentions.length ? mentions.filter((mention) => mention.evidenceSpan).length / mentions.length : 0,
    tasks: tasks.length,
    taskShapeCoverage: tasks.length ? tasks.filter((task) => /对象：|交付：|完成标准：/u.test(task.summary)).length / tasks.length : 0,
    skills: skills.length,
    taskSkillCoverage: tasks.length ? tasks.filter((task) => taskSkillSources.has(task.id)).length / tasks.length : 0,
    capabilities: capabilities.length,
    crossTaskCapabilities: capabilityCoverage.filter((count) => count >= 2).length,
    processScenarios: result.process.scenarios.length,
    taskProcessCoverage: tasks.length ? tasks.filter((task) => taskProcessSources.has(task.id)).length / tasks.length : 0,
    duplicateLabels: duplicates,
    offScopeScenarios: result.process.scenarios.filter((scenario) => /招聘|面试|课程|学习路径|求职/u.test(`${scenario.label}${scenario.summary}`)).length,
    failedWorkItems: result.build?.metrics.failedWorkItems || 0,
    workItems: result.build?.workItems.length || 0,
    largestEstimatedInput: Math.max(0, ...(result.build?.workItems.map((item) => item.estimatedInputTokens) || [])),
    largestOutputBudget: Math.max(0, ...(result.build?.workItems.map((item) => item.maxOutputTokens) || [])),
    publishable: result.validation.publishable,
    protocolValid: result.audit.inspection?.protocolValid,
    issueCodes: [...new Set(result.audit.issues.map((issue) => issue.code))],
  };
}

async function evaluate(name: string, fixture: Fixture, modelConfig: ProviderConfig) {
  const request: ColdStartRequest = {
    runId: `eval-v3-${name}-${Date.now()}`,
    projectId: `eval-v3-${name}`,
    roleTitle: fixture.roleTitle,
    roleDescription: fixture.roleDescription,
    market: "中国大陆",
    audience: ["高职学生", "教师"],
    snapshotAsOf: new Date().toISOString().slice(0, 10),
    sources: fixture.sources,
  };
  const startedAt = Date.now();
  const graph = createColdStartSkill(createModelInvoker(modelConfig), { emitEvents: false });
  const state = await graph.invoke({ request, laneFailures: [] }, { configurable: { thread_id: request.runId } });
  if (!state.result) throw new Error(`${name} did not produce a result`);
  return {
    fixture: name,
    roleTitle: fixture.roleTitle,
    score: score(state.result, Date.now() - startedAt),
    taskLabels: state.result.semantic.nodes.filter((node) => node.type === "task").map((node) => node.label),
    skillLabels: state.result.semantic.nodes.filter((node) => node.type === "knowledge_skill").map((node) => node.label),
    capabilityLabels: state.result.semantic.nodes.filter((node) => node.type === "capability").map((node) => node.label),
    scenarioLabels: state.result.process.scenarios.map((scenario) => scenario.label),
    failedLanes: state.result.build?.workItems.filter((item) => item.status === "failed").map((item) => ({ lane: item.lane, error: item.error })) || [],
  };
}

const apiKey = process.env.MIMO_API_KEY;
if (!apiKey) throw new Error("MIMO_API_KEY is required");
const provider = "mimo" as const;
const model = process.env.ROLE_ATLAS_MODEL && PROVIDERS[provider].models.some((item) => item.id === process.env.ROLE_ATLAS_MODEL)
  ? process.env.ROLE_ATLAS_MODEL
  : PROVIDERS[provider].defaultModel;
const requested = process.argv.slice(2).filter((value) => fixtures[value]);
const selected = requested.length ? requested : Object.keys(fixtures);
const modelConfig: ProviderConfig = { provider, model, apiKey, thinking: true };
const results = [];
for (const name of selected) results.push(await evaluate(name, fixtures[name], modelConfig));
process.stdout.write(`${JSON.stringify({ workflowVersion: "3.3", provider, model, results }, null, 2)}\n`);
