import type {
  AgentContextEnvelope,
  AgentDecisionSummary,
  AgentKnowledgeDomain,
  AgentTaskQueueItem,
  AgentToolCall,
  AgentToolDefinition,
  AgentTrajectoryEvent,
  AgentTurnResponse,
  AgentTurnStreamEvent,
} from '../src/agent-contracts.ts'
import type { TutorContextMessage, TutorMode } from '../src/tutor.ts'
import {
  auditSearchCitations,
  buildTutorInstructions,
  endpointFor,
  ensureSearchCitations,
  isDisplayableTutorReply,
  textFromTutorProviderResponse,
} from '../src/tutor.ts'
import type { SearchSource, TutorToolChoice, TutorToolRun } from '../src/tooling.ts'
import type { LearningTaskTutorContext } from '../src/learning.ts'
import type { LearningPlanTutorContext } from '../src/planning.ts'
import type { LearnerPathState } from '../src/learning-path-graph.ts'
import {
  executeTutorAgentTool,
  TUTOR_AGENT_TOOL_DEFINITIONS,
  type TutorAgentToolExecution,
  type TutorAgentToolRuntimeOptions,
} from './tool-runtime.ts'
import type { SearchProviderConfiguration } from './computer-knowledge-search.ts'
import type { LearningVideoCandidate } from './learning-video-harness.ts'
import type { AgentProjectContext } from '../src/project.ts'

export type TutorAgentBudget = {
  maxModelRounds: number
  maxToolCalls: number
  maxWallTimeMs: number
  finalizationAttempts: number
  finalizationGraceMs: number
}

export function tutorAgentBudget(mode: TutorMode): TutorAgentBudget {
  if (mode === 'guided_learning') {
    return {
      maxModelRounds: 9,
      maxToolCalls: 14,
      maxWallTimeMs: 180_000,
      finalizationAttempts: 2,
      finalizationGraceMs: 45_000,
    }
  }
  if (mode === 'learning_plan') {
    return {
      maxModelRounds: 7,
      maxToolCalls: 12,
      maxWallTimeMs: 150_000,
      finalizationAttempts: 2,
      finalizationGraceMs: 40_000,
    }
  }
  return {
    maxModelRounds: 5,
    maxToolCalls: 8,
    maxWallTimeMs: 90_000,
    finalizationAttempts: 1,
    finalizationGraceMs: 25_000,
  }
}

type RuntimeMessage =
  | { role: 'user' | 'assistant'; content: string; toolCalls?: AgentToolCall[] }
  | { role: 'tool'; content: string; toolCallId: string; toolName: string }

type ProviderInvoke = (request: {
  endpoint: string
  body: unknown
  timeoutMs: number
  onTextDelta?: (delta: string) => void
}) => Promise<unknown>

export type TutorAgentRuntimeInput = {
  baseUrl: string
  model: string
  mode: TutorMode
  messages: TutorContextMessage[]
  toolChoice: TutorToolChoice
  selectionContext?: string
  activeArtifactContext?: {
    kind: 'lecture' | 'practice' | 'source'
    ref: string
    title: string
    projectId?: number
  }
  learningTaskContext?: LearningTaskTutorContext
  learningPlanContext?: LearningPlanTutorContext
  learnerPathState?: LearnerPathState
  taskQueue?: AgentTaskQueueItem[]
  knowledgeDomains?: AgentKnowledgeDomain[]
  formalLearnerContext?: unknown
  formalWorkspaceContext?: unknown
  formalDomainKnowledgeContext?: unknown
  formalReviewContext?: unknown
  formalProjectContext?: AgentProjectContext
  conversationId?: string
  sheetId?: string
  backendBase?: string
  requestCookie?: string
  generate: TutorAgentToolRuntimeOptions['generate']
  searchConfiguration?: SearchProviderConfiguration
  invokeProvider: ProviderInvoke
  executeTool?: (
    name: string,
    args: Record<string, unknown>,
    options: TutorAgentToolRuntimeOptions,
    meta?: { callId?: string; sequence?: number; sourceUrls?: string[]; searchSources?: SearchSource[]; videoCandidates?: LearningVideoCandidate[] },
  ) => Promise<TutorAgentToolExecution>
  observe?: (event: AgentTurnStreamEvent) => void
}

function turnId() {
  return `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function compactDecisionText(value: unknown, fallback: string, limit = 220) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return (text || fallback).slice(0, limit)
}

function toolDecisionReason(call: AgentToolCall) {
  const reasons: Record<string, string> = {
    read_learner_context: '先确认与当前问题相关的基础、目标和已记录学习线索，避免使用不合适的讲法',
    read_learning_workspace: '先确认当前任务、练习、错题和复习位置，避免脱离正在进行的学习现场',
    read_project_workspace: '先读取当前项目目标、关卡和来源范围，保证回答只服务于这个项目',
    read_project_roadmap: '先核对项目关卡图与当前位置，再决定是否调整尚未学习的部分',
    read_project_sources: '先核对项目已接入的来源，避免重复搜索或引用项目外材料',
    read_active_learning_file: '先读取当前纸张中的讲义或练习锚点，让回答延续正在看的内容',
    read_domain_knowledge: '先从本对话资料中取得带来源的上下文，再判断是否仍需联网',
    read_review_context: '先读取复习与错题状态，再安排本轮回忆或纠错动作',
    lookup_learning_path_node: '先精确匹配正式学习路径节点，避免把相近课程误当成目标',
    search_learning_path_graph: '精确匹配不足，转为模糊读取学习路径候选与关系',
    search_computer_knowledge: '现有上下文不足以支撑可靠讲解，补充计算机领域的高质量来源',
    read_web_evidence: '搜索摘要不足以直接支撑结论，继续读取候选页面中的相关原文',
    search_learning_videos: '当前目标适合演示或分步讲解，先取得可用的视频候选',
    inspect_learning_video: '标题和热度不能证明内容适合学习，继续用字幕与时间点核验覆盖',
    generate_dynamic_practice: '当前学习动作需要可作答的检测，因此生成受任务约束的练习文件',
    generate_similar_practice: '需要检查迁移而不是重复原题，因此生成同构但不相同的练习',
    inspect_practice_quality: '题目投入学习前先检查结构、答案确定性和目标覆盖',
    generate_learning_lecture: '当前概念需要一份可留存、可作为纸张展开的讲义',
    generate_learning_diagram: '文字不足以同时表达当前对象与关系，因此补充一张可检查的结构图解',
    generate_learning_animation: '当前机制包含不可交换的状态变化，因此用可暂停的逐帧动画呈现',
  }
  const definition = TUTOR_AGENT_TOOL_DEFINITIONS.find(tool => tool.name === call.name)
  return compactDecisionText(reasons[call.name], `为完成当前学习动作，调用“${definition?.title || call.name}”取得结构化观察`)
}

function toolDecisionNextAction(run: TutorToolRun) {
  if (run.status === 'failed') return '保留失败原因，调整工具路线；最终回答必须透明说明仍存在的缺口'
  if (run.kind === 'file' || run.learningFile) return '把文件作为当前对话的学习对象，并继续决定阅读、练习或验证动作'
  if (run.kind === 'search') return '把来源与证据覆盖回灌给 Tutor，再判断是否需要读取原文或形成讲解'
  return '把这条结构化观察回灌给 Tutor，继续选择下一个学习动作或形成回答'
}

function deterministicTutorFallback(input: TutorAgentRuntimeInput, runs: TutorToolRun[]) {
  const failedRuns = runs.filter(run => run.status === 'failed')
  const failureNote = failedRuns.length
    ? `\n\n本轮有 ${failedRuns.length} 个工具没有成功（${failedRuns.map(run => run.title).join('、')}），我不会用猜测补齐这些缺口。`
    : ''
  if (input.mode === 'guided_learning' && input.learningTaskContext) {
    const task = input.learningTaskContext
    const formalPrompt = task.authority === 'formal_learning_task' && task.stepInstruction.trim()
      ? task.stepInstruction.trim()
      : ''
    const nextPrompt = formalPrompt || `当前来到“${task.stepTitle}”。请先说出你已经能确认的一点，或者直接指出卡住的位置；我会从你的回答继续推进，而不要求你手动切换步骤。`
    return `我们保留当前学习进度，继续完成「${task.objective}」。\n\n${nextPrompt}${failureNote}`
  }
  if (input.mode === 'learning_plan') {
    return `这轮模型正文没有稳定返回，但已经取得的观察会保留。请先确认你最想达成的产物或方向，我会从该目标继续收紧路线。${failureNote}`
  }
  return `这轮模型正文没有稳定返回，已保留工具观察和上下文。你可以直接继续追问，我会从当前位置重试。${failureNote}`
}

export function repairTutorDraftForObservedGaps(reply: string, runs: TutorToolRun[]) {
  let repaired = ensureSearchCitations(reply, runs).trim()
  if (!repaired) return repaired

  const unresolvedFailures = runs.filter(run => (
    run.status === 'failed'
    && !runs.some(candidate => candidate.kind === run.kind && candidate.status === 'completed')
  ))
  if (
    unresolvedFailures.length
    && !/(?:失败|暂时|无法|未能|没有拿到|资料缺口|证据不足|连接问题)/i.test(repaired)
  ) {
    const titles = [...new Set(unresolvedFailures.map(run => run.title))].slice(0, 3).join('、')
    repaired += `\n\n说明：本轮“${titles}”暂时未能成功，因此我先用已经取得的可靠观察完成这一教学动作，不把缺失产物冒充为已生成。`
  }

  const searched = runs.some(run => run.kind === 'search' && run.status === 'completed' && run.sources?.length)
  if (searched) {
    const citationAudit = auditSearchCitations(repaired, runs)
    if (citationAudit.evidenceGap && !citationAudit.acknowledgesGap) {
      repaired += '\n\n检索说明：本轮资料覆盖仍有缺口，以上只采用已经读取到的来源支撑核心辨析，不把未覆盖内容当作检索结论。'
    }
  }

  return repaired
}

function structurallyCompact(value: unknown, depth = 0, tight = false): unknown {
  if (typeof value === 'string') {
    const max = tight ? 320 : 1600
    return value.length > max ? `${value.slice(0, max - 1)}…` : value
  }
  if (value === null || typeof value !== 'object') return value
  if (depth >= (tight ? 4 : 7)) return { omitted: true, reason: 'depth_budget' }
  if (Array.isArray(value)) {
    const max = tight ? 8 : 24
    const items = value.slice(0, max).map(item => structurallyCompact(item, depth + 1, tight))
    return value.length > max ? [...items, { omittedItems: value.length - max }] : items
  }
  const entries = Object.entries(value as Record<string, unknown>)
  const max = tight ? 24 : 60
  const result = Object.fromEntries(entries.slice(0, max).map(([key, item]) => [
    key,
    structurallyCompact(item, depth + 1, tight),
  ]))
  if (entries.length > max) result.__omittedFields = entries.length - max
  return result
}

function safeJson(value: unknown, limit = 18_000) {
  const normal = JSON.stringify(structurallyCompact(value))
  if (normal.length <= limit) return normal
  const tight = JSON.stringify(structurallyCompact(value, 0, true))
  if (tight.length <= limit) return tight
  return JSON.stringify({
    truncated: true,
    reason: 'context_budget',
    topLevelKeys: value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).slice(0, 80) : [],
  })
}

function parseArguments(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value !== 'string' || !value.trim()) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return { __invalid_arguments: value.slice(0, 600) }
  }
}

export function toolCallsFromProviderResponse(payload: unknown): AgentToolCall[] {
  if (!payload || typeof payload !== 'object') return []
  const root = payload as Record<string, any>
  const result: AgentToolCall[] = []
  const choice = Array.isArray(root.choices) ? root.choices[0] : undefined
  const message = choice?.message && typeof choice.message === 'object' ? choice.message : undefined
  for (const raw of Array.isArray(message?.tool_calls) ? message.tool_calls : []) {
    const fn = raw?.function && typeof raw.function === 'object' ? raw.function : {}
    if (!fn.name) continue
    result.push({
      id: String(raw.id || `call-${result.length + 1}`),
      name: String(fn.name),
      arguments: parseArguments(fn.arguments),
    })
  }
  for (const raw of Array.isArray(root.output) ? root.output : []) {
    if (!raw || typeof raw !== 'object' || raw.type !== 'function_call' || !raw.name) continue
    result.push({
      id: String(raw.call_id || raw.id || `call-${result.length + 1}`),
      name: String(raw.name),
      arguments: parseArguments(raw.arguments),
    })
  }
  return result
}

function chatToolDefinitions(tools: AgentToolDefinition[]) {
  return tools.map(tool => ({
    type: 'function',
    function: {
      name: tool.name,
      description: `${tool.description} [${tool.toolClass}; ${tool.risk}]`,
      parameters: tool.inputSchema,
    },
  }))
}

function responsesToolDefinitions(tools: AgentToolDefinition[]) {
  return tools.map(tool => ({
    type: 'function',
    name: tool.name,
    description: `${tool.description} [${tool.toolClass}; ${tool.risk}]`,
    parameters: tool.inputSchema,
  }))
}

function providerInput(messages: RuntimeMessage[]) {
  const input: Array<Record<string, unknown>> = []
  for (const message of messages) {
    if (message.role === 'tool') {
      input.push({ type: 'function_call_output', call_id: message.toolCallId, output: message.content })
      continue
    }
    if (message.toolCalls?.length) {
      for (const call of message.toolCalls) {
        input.push({
          type: 'function_call',
          call_id: call.id,
          name: call.name,
          arguments: JSON.stringify(call.arguments),
        })
      }
      if (message.content.trim()) input.push({ role: 'assistant', content: message.content })
      continue
    }
    input.push({ role: message.role, content: message.content })
  }
  return input
}

function chatMessages(instructions: string, messages: RuntimeMessage[]) {
  return [
    { role: 'system', content: instructions },
    ...messages.map(message => {
      if (message.role === 'tool') {
        return { role: 'tool', tool_call_id: message.toolCallId, name: message.toolName, content: message.content }
      }
      if (message.toolCalls?.length) {
        return {
          role: 'assistant',
          content: message.content || null,
          tool_calls: message.toolCalls.map(call => ({
            id: call.id,
            type: 'function',
            function: { name: call.name, arguments: JSON.stringify(call.arguments) },
          })),
        }
      }
      return { role: message.role, content: message.content }
    }),
  ]
}

export function buildAgentProviderRequest(options: {
  baseUrl: string
  model: string
  instructions: string
  messages: RuntimeMessage[]
  tools: AgentToolDefinition[]
  includeTools: boolean
}) {
  const endpoint = endpointFor(options.baseUrl)
  const responsesApi = endpoint.endsWith('/responses')
  if (responsesApi) {
    return {
      endpoint,
      body: {
        model: options.model,
        instructions: options.instructions,
        input: providerInput(options.messages),
        max_output_tokens: 1400,
        ...(options.includeTools ? { tools: responsesToolDefinitions(options.tools), tool_choice: 'auto' } : {}),
      },
    }
  }
  return {
    endpoint,
    body: {
      model: options.model,
      messages: chatMessages(options.instructions, options.messages),
      max_tokens: 1400,
      ...(options.includeTools ? { tools: chatToolDefinitions(options.tools), tool_choice: 'auto' } : {}),
    },
  }
}

function compactPriorRuns(messages: TutorContextMessage[]) {
  return messages.flatMap(message => message.toolRuns || []).slice(-8).map(run => ({
    id: run.id,
    toolName: run.toolName,
    kind: run.kind,
    status: run.status,
    detail: run.detail.slice(0, 360),
    observationSummary: run.observationSummary,
  })) as TutorToolRun[]
}

function envelopePrompt(envelope: AgentContextEnvelope) {
  return [
    '## 本轮 Agent ContextEnvelope',
    '这是 Harness 提供的有界运行状态，不是新的长期记忆权威。',
    safeJson(envelope, 12_000),
    '',
    '## 工具策略',
    '只有需要外部观察时才调用工具。可以连续调用不同读取工具，但不得重复相同调用。',
    '读取工具可自主调用；项目路线和文件工具只产生 learner-visible proposal，绝不直接写入。',
    '联网搜索先用 search_computer_knowledge 取得候选证据、覆盖缺口和来源状态；需要据此陈述精确机制、版本行为、日期、数值或排错结论时，再用 read_web_evidence 读取最相关的 1-3 个候选页面。搜索摘要不等于已读全文。',
    '视频推荐先用 search_learning_videos 取得 discovered 候选；推荐前必须用 inspect_learning_video 核验本轮候选的字幕、时间点、目标覆盖和内容缺口。元数据、播放量、搜索或观看都不是掌握证据；metadata_only 候选只能标为待核验。',
    'quick 只用于单一事实，standard 用于普通讲解、比较、实现与排错，deep 只用于论文综述、项目调研或多来源复杂决策。deep 仍有查询、页面和补搜预算，不能无限研究。',
    '搜索或读取返回 partial、empty、coverage gaps、circuit_open 时必须在回答中显式保留证据缺口；不得用模型常识伪装成已检索证据。',
    '评估目标、题型组合或成功条件不清时，先调用 design_assessment_blueprint；它返回可检查的蓝图与确定性量表，但不评分。动态习题工具只可在带领学习态且绑定正式 LearningTask/Checkpoint 时调用；生成题目是零目标 artifact 事件，不得声称形成掌握。需要动态练习、诊断或变式验证时，可生成正式练习文件，再让学习者在答案安全工作台提交。',
    '处于项目 scope 时，所有规划、来源选择、讲义与练习都必须锚定 envelope.scope.projectId 对应的项目主题；不得偷换为通用课程规划。',
    '若学习者观察中存在 Claim 冲突，必须明确说明冲突并把纠正留给学习者确认；不得静默选择一边或声称已经改写画像。',
    '若工作区观察含 sourceConstraint，路线和讲解必须受当前项目来源覆盖范围约束；超出范围只能标为资料缺口，并在检索到新证据后补充。',
    '工作区中没有 Attempt 只表示当前作用域没有可见记录，不能推断学生第一次学习、从未练习或没有相关经历。',
    '学习路径必须先调用 lookup_learning_path_node 做精确读取；只有它未命中、存在错别字/近义表达或候选歧义时才调用 search_learning_path_graph。模糊结果为 ambiguous 时应呈现候选让学习者选择，不能直接形成路线。只有模糊检索明确返回 graph_gap 且联网来源已取得后，才可调用 propose_personal_path_node；提案绝不等于已写入。',
    '工具失败时先依据错误类型决定重试、换工具或明确告知缺口。拿到足够证据后直接回答。',
  ].join('\n')
}

function availableTools(input: TutorAgentRuntimeInput) {
  const projectTutor = input.formalProjectContext?.tool_policy?.roadmap_tool_access === 'project_tutor'
  return TUTOR_AGENT_TOOL_DEFINITIONS.filter(tool => (
    (!['lookup_learning_path_node', 'search_learning_path_graph', 'propose_personal_path_node'].includes(tool.name) || Boolean(input.learnerPathState))
    && (tool.name !== 'read_domain_knowledge' || Boolean(input.formalDomainKnowledgeContext))
    && (tool.name !== 'read_review_context' || Boolean(input.formalReviewContext))
    && (tool.name !== 'read_active_learning_file' || Boolean(input.activeArtifactContext))
    && (!tool.name.startsWith('read_project_') || Boolean(input.formalProjectContext))
    && (tool.name !== 'read_project_roadmap' || projectTutor)
    && (tool.name !== 'propose_project_roadmap' || projectTutor && input.mode === 'learning_plan')
    && (tool.name !== 'propose_project_learning_files' || Boolean(input.formalProjectContext) && input.mode === 'guided_learning')
    && (!['design_assessment_blueprint', 'generate_dynamic_practice', 'generate_similar_practice'].includes(tool.name)
      || Boolean(input.formalProjectContext?.checkpoint_id) && input.mode === 'guided_learning' && Boolean(input.learningTaskContext))
    && (tool.name !== 'inspect_practice_quality' || Boolean(input.formalProjectContext) && input.mode === 'guided_learning')
  ))
}

function explicitToolCall(choice: TutorToolChoice, message: string, projectScoped = false): AgentToolCall | undefined {
  if (choice === 'auto') return undefined
  if (choice === 'domain') return {
    id: `explicit-domain-${Date.now()}`,
    name: projectScoped ? 'read_project_sources' : 'read_domain_knowledge',
    arguments: { query: message },
  }
  if (choice === 'search') return {
    id: `explicit-search-${Date.now()}`,
    name: /视频|课程视频|b站|bilibili|youtube/i.test(message) ? 'search_learning_videos' : 'search_computer_knowledge',
    arguments: /视频|课程视频|b站|bilibili|youtube/i.test(message)
      ? { target: message, platforms: /b站|bilibili/i.test(message) ? ['bilibili'] : /youtube/i.test(message) ? ['youtube'] : ['bilibili', 'youtube'], max_results: 6 }
      : { query: message, depth: /深度研究|系统调研|文献综述|研究综述|多来源|全面研究|deep research/i.test(message) ? 'deep' : 'standard' },
  }
  return {
    id: `explicit-visual-${Date.now()}`,
    name: choice === 'animation' ? 'generate_learning_animation' : 'generate_learning_diagram',
    arguments: { query: message },
  }
}

export function verifyTutorTurnOutcome(options: {
  reply: string
  mode: TutorMode
  toolRuns: TutorToolRun[]
  learningTaskContext?: LearningTaskTutorContext
  observations?: AgentContextEnvelope['observations']
}) {
  const violations: string[] = []
  const reply = options.reply.trim()
  if (!isDisplayableTutorReply(reply)) violations.push('display_protocol')
  const hasUncommittedProposal = options.toolRuns.some(run => run.pathProposal || run.pathPlanProposal || run.projectRoadmapProposal || run.projectLearningFileProposal)
  if (
    hasUncommittedProposal
    && /(?:已经|已)[^。！!？?\n]{0,24}(?:保存|加入|写入|更新|创建)(?:了)?[^。！!？?\n]{0,20}(?:路径|节点|规划)/i.test(reply)
    && !/(?:尚未|没有|并未|等待|需要|只有.*确认)/i.test(reply)
  ) violations.push('unconfirmed_path_write_claim')
  const masteryClaim = /(?:你|这说明你)[^。！!？?\n]{0,18}(?:已经|已)?(?:完全|稳定|真正)?掌握/i.test(reply)
    && !/(?:尚未|还没|没有|未能|并未)[^。！!？?\n]{0,10}掌握/i.test(reply)
  if (
    (options.mode === 'guided_learning' || Boolean(options.learningTaskContext))
    && masteryClaim
  ) violations.push('unsupported_mastery_claim')
  const failedKinds = new Set(options.toolRuns.filter(run => run.status === 'failed').map(run => run.kind))
  const unresolvedFailure = [...failedKinds].some(kind => !options.toolRuns.some(run => run.kind === kind && run.status === 'completed'))
  if (unresolvedFailure && !/(?:失败|暂时|无法|未能|没有拿到|资料缺口|证据不足|连接问题)/i.test(reply)) {
    violations.push('hidden_tool_failure')
  }
  const searched = options.toolRuns.some(run => run.kind === 'search' && run.status === 'completed' && run.sources?.length)
  if (searched) {
    const citationAudit = auditSearchCitations(reply, options.toolRuns)
    const hasNonSearchSourceObservation = options.toolRuns.some(run => (
      run.status === 'completed'
      && run.kind !== 'search'
      && ['domain', 'project', 'file'].includes(run.kind)
    ))
    if (!citationAudit.citedAllowedUrls.length) violations.push('missing_search_citation')
    if (citationAudit.citationLikeUnknownUrls.length && !hasNonSearchSourceObservation) violations.push('unverified_search_citation')
    if (citationAudit.evidenceGap && !citationAudit.acknowledgesGap) violations.push('hidden_search_coverage_gap')
  }
  const learnerContext = options.observations?.find(observation => observation.source === 'read_learner_context')?.data
  const learnerConflicts = learnerContext && typeof learnerContext === 'object'
    ? (learnerContext as Record<string, unknown>).conflicts
    : undefined
  const hasLearnerConflict = Array.isArray(learnerConflicts) && learnerConflicts.length > 0
  const acknowledgesConflict = /(?:冲突|不一致|相互矛盾|需要你确认|请你确认|保留原记录|不会静默覆盖|纠正候选)/i.test(reply)
  if (hasLearnerConflict && !acknowledgesConflict) violations.push('silent_memory_conflict')
  const workspaceContext = options.observations?.find(observation => observation.source === 'read_learning_workspace')?.data
  const evidenceManifest = workspaceContext && typeof workspaceContext === 'object'
    ? ((workspaceContext as Record<string, any>).learningEvidence?.manifest || {})
    : {}
  const noScopedAttempts = evidenceManifest && Number(evidenceManifest.attempt_count) === 0
  const unsupportedHistoryInference = /(?:说明|所以|因此|可见)?[^。！!？?\n]{0,18}(?:你(?:是|这)?[^。！!？?\n]{0,8})?(?:第一次(?:正式)?学|从未(?:学|练习)|没有(?:学过|练习过))/i.test(reply)
    && !/(?:记录|数据|当前作用域|这里)[^。！!？?\n]{0,18}(?:没有|暂无|未找到|不可见)/i.test(reply)
  if (noScopedAttempts && unsupportedHistoryInference) violations.push('unsupported_learning_history_claim')
  return { valid: violations.length === 0, violations }
}

export async function runTutorAgentTurn(input: TutorAgentRuntimeInput): Promise<AgentTurnResponse> {
  const id = turnId()
  const startedAt = Date.now()
  const budget = tutorAgentBudget(input.mode)
  const deadline = startedAt + budget.maxWallTimeMs
  const latestMessage = [...input.messages].reverse().find(message => message.role === 'user')?.content || ''
  const trajectory: AgentTrajectoryEvent[] = []
  const decisionSummaries: AgentDecisionSummary[] = []
  const runs: TutorToolRun[] = []
  const runtimeMessages: RuntimeMessage[] = input.messages.slice(-18).map(message => ({ role: message.role, content: message.content }))
  const observations: AgentContextEnvelope['observations'] = []
  const signatures = new Set<string>()
  let modelRounds = 0
  let toolCalls = 0
  let sequence = 0
  let stopReason: AgentTurnResponse['trace']['stopReason'] = 'error'
  let fallbackReply = ''
  let visibleDraft = ''
  let firstTextDeltaAt: number | undefined
  let pathGapPending = false
  let pathFuzzyPending = false
  let pathResolution: 'unknown' | 'resolved' | 'ambiguous' | 'not_found' | 'overview' = 'unknown'
  let currentVideoCandidates: LearningVideoCandidate[] = []
  const explicitlyRequestsExternalResources = input.toolChoice !== 'auto'
    || /(?:联网|搜索|查找|检索|资料|资源|教材|课程推荐|来源|论文|文档|仓库|官网|最新)/i.test(latestMessage)

  const record = (event: Omit<AgentTrajectoryEvent, 'sequence' | 'at'>) => {
    const recorded = { ...event, sequence: ++sequence, at: Date.now() }
    trajectory.push(recorded)
    input.observe?.({ type: 'trajectory', event: recorded })
  }
  const emitTextDelta = (delta: string) => {
    if (!delta) return
    if (!firstTextDeltaAt) firstTextDeltaAt = Date.now()
    visibleDraft += delta
    input.observe?.({ type: 'text_delta', delta })
  }
  const resetVisibleDraft = (reason: 'tool_call' | 'retry' | 'verification' | 'reconcile') => {
    if (!visibleDraft) return
    visibleDraft = ''
    input.observe?.({ type: 'text_reset', reason })
  }
  const reconcileVisibleDraft = (candidate: string) => {
    if (!input.observe) return
    if (candidate.startsWith(visibleDraft)) {
      emitTextDelta(candidate.slice(visibleDraft.length))
      return
    }
    resetVisibleDraft('reconcile')
    emitTextDelta(candidate)
  }
  const toolOptions: TutorAgentToolRuntimeOptions = {
    message: latestMessage,
    generate: input.generate,
    searchConfiguration: input.searchConfiguration,
    mode: input.mode,
    learningTaskContext: input.learningTaskContext,
    learningPlanContext: input.learningPlanContext,
    taskQueue: input.taskQueue,
    knowledgeDomains: input.knowledgeDomains,
    learnerPathState: input.learnerPathState,
    formalLearnerContext: input.formalLearnerContext,
    formalWorkspaceContext: input.formalWorkspaceContext,
    formalDomainKnowledgeContext: input.formalDomainKnowledgeContext,
    formalReviewContext: input.formalReviewContext,
    formalProjectContext: input.formalProjectContext,
    activeArtifactContext: input.activeArtifactContext,
    backendBase: input.backendBase,
    requestCookie: input.requestCookie,
  }

  const execute = async (call: AgentToolCall, searchSources: SearchSource[] = []) => {
    // Artifact generators are expensive and have side effects. Treat a second
    // request for the same formal task as a duplicate even when the model only
    // changes a title or difficulty after a failure. Recovery must use the
    // existing observation or end transparently, not burn the whole turn on
    // near-identical generation attempts.
    const practiceGenerationKey = ['generate_dynamic_practice', 'generate_similar_practice'].includes(call.name)
      ? `${call.name}:learning-task:${String(call.arguments.learning_task_id || '')}`
      : ''
    const signature = practiceGenerationKey || `${call.name}:${JSON.stringify(call.arguments)}`
    if (signatures.has(signature)) {
      const duplicate = {
        error: 'duplicate_tool_call',
        guidance: '相同工具和参数本轮已经执行；请使用已有观察、修改参数或结束回答。',
      }
      runtimeMessages.push({ role: 'assistant', content: '', toolCalls: [call] })
      runtimeMessages.push({ role: 'tool', toolCallId: call.id, toolName: call.name, content: safeJson(duplicate) })
      record({ phase: 'act', detail: '阻止重复工具调用', toolCallId: call.id, toolName: call.name, status: 'blocked' })
      return [] as string[]
    }
    if (toolCalls >= budget.maxToolCalls) {
      record({ phase: 'act', detail: '达到工具调用预算', toolCallId: call.id, toolName: call.name, status: 'blocked' })
      return [] as string[]
    }
    signatures.add(signature)
    toolCalls += 1
    input.observe?.({
      type: 'tool_started', toolCallId: call.id, toolName: call.name,
      title: TUTOR_AGENT_TOOL_DEFINITIONS.find(tool => tool.name === call.name)?.title || call.name,
      startedAt: Date.now(),
    })
    record({ phase: 'act', detail: `调用 ${call.name}`, toolCallId: call.id, toolName: call.name, status: 'started' })
    runtimeMessages.push({ role: 'assistant', content: '', toolCalls: [call] })
    const result = await (input.executeTool || executeTutorAgentTool)(call.name, call.arguments, toolOptions, {
      callId: call.id,
      sequence: toolCalls,
      sourceUrls: searchSources.map(source => source.url),
      searchSources,
      videoCandidates: currentVideoCandidates,
    })
    if (result.videoCandidates) currentVideoCandidates = result.videoCandidates
    runs.push(result.run)
    input.observe?.({ type: 'tool_completed', run: result.run })
    const decisionSummary: AgentDecisionSummary = {
      id: `decision-${id}-${toolCalls}`,
      sequence: toolCalls,
      round: modelRounds,
      at: Date.now(),
      toolCallId: call.id,
      toolName: call.name,
      reason: toolDecisionReason(call),
      observation: compactDecisionText(
        result.run.observationSummary || result.run.detail,
        result.run.status === 'completed' ? '工具返回了结构化观察' : '工具没有返回可用观察',
      ),
      nextAction: toolDecisionNextAction(result.run),
    }
    decisionSummaries.push(decisionSummary)
    input.observe?.({ type: 'decision_summary', summary: decisionSummary })
    if (call.name === 'lookup_learning_path_node') {
      pathFuzzyPending = Boolean((result.observation as any)?.needsFuzzySearch)
      pathResolution = ((result.observation as any)?.retrieval?.resolution || pathResolution) as typeof pathResolution
    }
    if (call.name === 'search_learning_path_graph') {
      pathFuzzyPending = false
      pathGapPending = Boolean((result.observation as any)?.needsExternalResearch)
      pathResolution = ((result.observation as any)?.retrieval?.resolution || pathResolution) as typeof pathResolution
    }
    if (call.name === 'propose_personal_path_node' && result.run.status === 'completed') {
      pathGapPending = false
    }
    observations.push({
      source: call.name,
      authority: String((result.observation as any)?.authority || 'tool_observation'),
      answerFree: call.name === 'read_learner_context'
        || call.name === 'read_learning_workspace'
        || call.name === 'read_domain_knowledge'
        || call.name === 'lookup_learning_path_node'
        || call.name === 'search_learning_path_graph'
        || call.name === 'read_review_context'
        || call.name === 'read_project_workspace'
        || call.name === 'read_project_roadmap'
        || call.name === 'read_project_sources'
        || call.name === 'read_project_learning_file'
        || call.name === 'read_active_learning_file'
        || call.name === 'search_learning_videos'
        || call.name === 'inspect_learning_video',
      data: result.observation,
    })
    runtimeMessages.push({
      role: 'tool',
      toolCallId: call.id,
      toolName: call.name,
      content: safeJson(result.observation),
    })
    if (result.directReply) fallbackReply = result.directReply
    record({
      phase: 'act',
      detail: result.run.status === 'completed' ? `${call.name} 返回观察` : `${call.name} 执行失败`,
      toolCallId: call.id,
      toolName: call.name,
      status: result.run.status,
    })
    return result.searchSources || []
  }

  const refreshPathAfterSearch = async (sources: SearchSource[]) => {
    if (!pathGapPending || !sources.length || !input.learnerPathState) return
    await execute({
      id: `path-evidence-refresh-${id}-${toolCalls + 1}`,
      name: 'propose_personal_path_node',
      arguments: { query: latestMessage, source_urls: sources.map(source => source.url) },
    }, sources)
  }

  record({ phase: 'observe', detail: '开始组装本轮观察空间', status: 'started' })
  const needsLearnerContext = input.mode === 'guided_learning'
    || input.mode === 'learning_plan'
    || /(?:根据我|适合我|我的基础|我的情况|我之前|我学过|我不会|我总是|记得我|偏好|目标|熟练度|掌握度|薄弱|错题)/i.test(latestMessage)
  if (needsLearnerContext) {
    await execute({ id: `observe-memory-${id}`, name: 'read_learner_context', arguments: { query: latestMessage } })
  }
  if (input.formalProjectContext) {
    await execute({ id: `observe-project-${id}`, name: 'read_project_workspace', arguments: { query: latestMessage } })
    if (input.formalProjectContext.tool_policy?.roadmap_tool_access === 'project_tutor' && input.mode === 'learning_plan') {
      await execute({ id: `observe-roadmap-${id}`, name: 'read_project_roadmap', arguments: { query: latestMessage } })
    }
  }
  if (input.mode === 'guided_learning' || input.mode === 'learning_plan') {
    await execute({ id: `observe-workspace-${id}`, name: 'read_learning_workspace', arguments: { query: latestMessage } })
  }
  if (input.activeArtifactContext) {
    await execute({ id: `observe-active-file-${id}`, name: 'read_active_learning_file', arguments: {} })
  }
  if (input.formalDomainKnowledgeContext && input.mode === 'learning_plan' && input.toolChoice === 'auto') {
    await execute({ id: `observe-domain-${id}`, name: 'read_domain_knowledge', arguments: { query: latestMessage } })
  }
  if (input.mode === 'learning_plan' && input.learnerPathState) {
    await execute({ id: `observe-path-exact-${id}`, name: 'lookup_learning_path_node', arguments: { query: latestMessage } })
    if (pathFuzzyPending) {
      await execute({ id: `observe-path-fuzzy-${id}`, name: 'search_learning_path_graph', arguments: { query: latestMessage, limit: 6 } })
    }
  }
  if (input.formalReviewContext && /复习|错题|遗忘|记不住|熟练度|掌握度|记忆曲线|间隔|回忆|薄弱/i.test(latestMessage)) {
    await execute({ id: `observe-review-${id}`, name: 'read_review_context', arguments: { query: latestMessage } })
  }
  const explicit = explicitToolCall(input.toolChoice, latestMessage, Boolean(input.formalProjectContext))
  if (explicit) {
    const sources = await execute(explicit)
    if (explicit.name === 'search_computer_knowledge') await refreshPathAfterSearch(sources)
  }
  record({ phase: 'observe', detail: `观察空间已就绪：${observations.length} 个结构化观察`, status: 'completed' })

  const envelope: AgentContextEnvelope = {
    version: 'vnext-agent-context.v1',
    scope: {
      mode: input.mode, conversationId: input.conversationId, sheetId: input.sheetId,
      projectId: input.formalProjectContext?.project?.id,
      checkpointId: input.formalProjectContext?.checkpoint_id || undefined,
    },
    current: {
      userMessage: latestMessage,
      selection: input.selectionContext,
      activeArtifact: input.activeArtifactContext,
      learningTask: input.learningTaskContext,
      learningPlan: input.learningPlanContext,
    },
    observations: observations.map(item => ({ ...item, data: undefined })),
    recentToolObservations: compactPriorRuns(input.messages),
    budgets: {
      maxModelRounds: budget.maxModelRounds,
      maxToolCalls: budget.maxToolCalls,
      maxWallTimeMs: budget.maxWallTimeMs,
    },
  }
  const tools = availableTools(input)
  const modelVisibleToolNames = new Set(tools.map(tool => tool.name))
  const instructions = buildTutorInstructions({
    mode: input.mode,
    selectionContext: input.selectionContext,
    activeArtifactContext: input.activeArtifactContext,
    learningTaskContext: input.learningTaskContext,
    learningPlanContext: input.learningPlanContext,
    toolContext: envelopePrompt(envelope),
  })

  let reply = ''
  let searchSources: SearchSource[] = runs.flatMap(run => run.sources || [])
  const invokeModel = async (
    request: ReturnType<typeof buildAgentProviderRequest>,
    requestDeadline = deadline,
  ) => {
    let lastError: unknown
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const payload = await input.invokeProvider({
          ...request,
          timeoutMs: Math.max(1_000, Math.min(45_000, requestDeadline - Date.now())),
          onTextDelta: emitTextDelta,
        })
        return payload
      } catch (error) {
        lastError = error
        resetVisibleDraft('retry')
        const message = error instanceof Error ? error.message : String(error || '')
        const transient = /timeout|超时|429|rate|network|fetch|ECONN|temporar|503|502/i.test(message)
        if (!transient || attempt > 0 || Date.now() >= requestDeadline - 1_000) throw error
        record({ phase: 'decide', detail: '模型请求遇到暂时故障，使用剩余预算重试一次', status: 'retrying' })
      }
    }
    throw lastError
  }
  try {
    for (let round = 0; round < budget.maxModelRounds && Date.now() < deadline; round += 1) {
      modelRounds += 1
      record({ phase: 'decide', detail: `模型决策第 ${modelRounds} 轮`, status: 'started' })
      const request = buildAgentProviderRequest({
        baseUrl: input.baseUrl,
        model: input.model,
        instructions,
        messages: runtimeMessages,
        tools,
        includeTools: toolCalls < budget.maxToolCalls,
      })
      const payload = await invokeModel(request)
      const calls = toolCallsFromProviderResponse(payload)
      const text = textFromTutorProviderResponse(payload)
      if (calls.length) {
        resetVisibleDraft('tool_call')
        record({ phase: 'decide', detail: `模型选择 ${calls.length} 个工具`, status: 'completed' })
        for (const call of calls.slice(0, budget.maxToolCalls - toolCalls)) {
          if (!modelVisibleToolNames.has(call.name)) {
            const observation = {
              error: 'tool_not_available',
              requestedTool: call.name,
              guidance: '该工具没有向当前状态或作用域开放。请只使用本轮 tools 列表中的工具。',
            }
            runtimeMessages.push({ role: 'assistant', content: '', toolCalls: [call] })
            runtimeMessages.push({
              role: 'tool', toolCallId: call.id, toolName: call.name, content: safeJson(observation),
            })
            record({
              phase: 'act', detail: `阻止未开放工具 ${call.name}`,
              toolCallId: call.id, toolName: call.name, status: 'blocked',
            })
            continue
          }
          if (
            call.name === 'search_computer_knowledge'
            && input.mode === 'learning_plan'
            && input.toolChoice === 'auto'
            && !explicitlyRequestsExternalResources
            && (pathResolution === 'resolved' || pathResolution === 'ambiguous')
          ) {
            const observation = {
              error: 'path_retrieval_already_sufficient',
              pathResolution,
              guidance: pathResolution === 'resolved'
                ? '学习路径目标已经由正式图谱可靠定位。请直接基于已有图谱回答，不要为补充一般背景重复联网。'
                : '当前目标存在多个正式图谱候选。请先让学习者消歧，不要用联网结果替学习者选择方向。',
            }
            runtimeMessages.push({ role: 'assistant', content: '', toolCalls: [call] })
            runtimeMessages.push({
              role: 'tool', toolCallId: call.id, toolName: call.name, content: safeJson(observation),
            })
            record({
              phase: 'act', detail: `阻止路径已${pathResolution === 'resolved' ? '定位' : '进入消歧'}后的冗余联网`,
              toolCallId: call.id, toolName: call.name, status: 'blocked',
            })
            continue
          }
          const sources = await execute(call, searchSources)
          if (sources.length) {
            const byUrl = new Map([...searchSources, ...sources].map(source => [source.url, source]))
            searchSources = [...byUrl.values()]
          }
          if (call.name === 'search_computer_knowledge') await refreshPathAfterSearch(sources)
        }
        continue
      }
      const candidate = repairTutorDraftForObservedGaps(text, runs)
      const verification = verifyTutorTurnOutcome({
        reply: candidate,
        mode: input.mode,
        toolRuns: runs,
        learningTaskContext: input.learningTaskContext,
        observations,
      })
      if (verification.valid) {
        reply = candidate
        reconcileVisibleDraft(candidate)
        stopReason = 'final_answer'
        record({ phase: 'verify', detail: '最终回复通过展示协议校验', status: 'completed' })
        break
      }
      runtimeMessages.push({ role: 'assistant', content: text })
      resetVisibleDraft('verification')
      runtimeMessages.push({
        role: 'user',
        content: `上一次输出未通过终态校验（${verification.violations.join('、')}）。请只输出自然的中文教学正文；不得冒充已写入状态、不得无证据宣布掌握，工具失败和搜索覆盖缺口要透明说明；联网事实只能引用本轮工具返回的精确 URL，不得补写链接；观察到记忆冲突时必须把冲突和确认权告诉学习者；没有可见 Attempt 只能说暂无记录，不能推断学生第一次学习或从未练习。`,
      })
      record({ phase: 'verify', detail: `回复未通过终态校验：${verification.violations.join('、')}`, status: 'failed' })
    }

    if (!reply) {
      stopReason = Date.now() >= deadline ? 'model_budget' : toolCalls >= budget.maxToolCalls ? 'tool_budget' : 'forced_finalize'
      record({ phase: 'finalize', detail: '进入无工具最终收束', status: 'started' })
      const finalizationDeadline = Math.max(Date.now(), deadline) + budget.finalizationGraceMs
      for (let attempt = 0; attempt < budget.finalizationAttempts && Date.now() < finalizationDeadline && !reply; attempt += 1) {
        modelRounds += 1
        runtimeMessages.push({
          role: 'user',
          content: attempt === 0
            ? '工具阶段已经结束。请基于已有观察直接给出完整、自然的中文教学回复；明确资料缺口，不再调用工具。'
            : '上一轮仍没有形成可展示正文。现在只完成当前 SkillRun 要求的一个教学动作：先自然回应，再给最小必要解释或问题；不要调用工具，不要输出协议文本。',
        })
        const request = buildAgentProviderRequest({
          baseUrl: input.baseUrl,
          model: input.model,
          instructions,
          messages: runtimeMessages.slice(-24),
          tools,
          includeTools: false,
        })
        const payload = await invokeModel(request, finalizationDeadline)
        const text = textFromTutorProviderResponse(payload)
        const candidate = repairTutorDraftForObservedGaps(text, runs)
        if (verifyTutorTurnOutcome({
          reply: candidate,
          mode: input.mode,
          toolRuns: runs,
          learningTaskContext: input.learningTaskContext,
          observations,
        }).valid) {
          reply = candidate
          reconcileVisibleDraft(candidate)
        } else {
          resetVisibleDraft('verification')
          record({ phase: 'verify', detail: `第 ${attempt + 1} 次最终收束未形成可展示正文`, status: 'failed' })
        }
      }
      if (!reply && fallbackReply) reply = fallbackReply
      if (!reply) {
        reply = deterministicTutorFallback(input, runs)
        reconcileVisibleDraft(reply)
        record({ phase: 'finalize', detail: '模型正文缺失，使用确定性教学续接保护学习现场', status: 'completed' })
      }
      record({ phase: 'finalize', detail: '最终回复已收束', status: 'completed' })
    }
  } catch (error) {
    record({ phase: 'error', detail: error instanceof Error ? error.message.slice(0, 240) : 'Agent Runtime 失败', status: 'failed' })
    stopReason = 'error'
    if (!reply && fallbackReply) reply = fallbackReply
    if (!reply && input.mode === 'guided_learning') {
      reply = deterministicTutorFallback(input, runs)
      stopReason = 'forced_finalize'
      reconcileVisibleDraft(reply)
      record({ phase: 'finalize', detail: '模型或工具异常，使用确定性教学续接保护学习现场', status: 'completed' })
    }
    if (!reply) throw error
  }

  reply = ensureSearchCitations(reply, runs)
  const finalVerification = verifyTutorTurnOutcome({
    reply,
    mode: input.mode,
    toolRuns: runs,
    learningTaskContext: input.learningTaskContext,
    observations,
  })
  if (!finalVerification.valid) {
    record({ phase: 'error', detail: `终态校验失败：${finalVerification.violations.join('、')}`, status: 'failed' })
    throw new Error(`模型回复未通过终态安全校验：${finalVerification.violations.join('、')}`)
  }
  reconcileVisibleDraft(reply)
  return {
    reply,
    toolRuns: runs,
    trace: {
      version: 'vnext-agent-trace.v1',
      turnId: id,
      modelRounds,
      toolCalls,
      stopReason,
      events: trajectory,
      decisionSummaries,
      timings: {
        ...(firstTextDeltaAt ? { firstTextDeltaMs: firstTextDeltaAt - startedAt } : {}),
        totalMs: Date.now() - startedAt,
      },
    },
  }
}
