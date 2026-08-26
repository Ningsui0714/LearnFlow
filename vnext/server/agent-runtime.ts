import type {
  AgentContextEnvelope,
  AgentKnowledgeDomain,
  AgentTaskQueueItem,
  AgentToolCall,
  AgentToolDefinition,
  AgentTrajectoryEvent,
  AgentTurnResponse,
} from '../src/agent-contracts.ts'
import type { TutorContextMessage, TutorMode } from '../src/tutor.ts'
import {
  buildTutorInstructions,
  endpointFor,
  ensureSearchCitations,
  isDisplayableTutorReply,
  textFromTutorProviderResponse,
} from '../src/tutor.ts'
import type { TutorToolChoice, TutorToolRun } from '../src/tooling.ts'
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

const MAX_MODEL_ROUNDS = 5
const MAX_TOOL_CALLS = 8
const MAX_WALL_TIME_MS = 90_000

type RuntimeMessage =
  | { role: 'user' | 'assistant'; content: string; toolCalls?: AgentToolCall[] }
  | { role: 'tool'; content: string; toolCallId: string; toolName: string }

type ProviderInvoke = (request: {
  endpoint: string
  body: unknown
  timeoutMs: number
}) => Promise<unknown>

export type TutorAgentRuntimeInput = {
  baseUrl: string
  model: string
  mode: TutorMode
  messages: TutorContextMessage[]
  toolChoice: TutorToolChoice
  selectionContext?: string
  learningTaskContext?: LearningTaskTutorContext
  learningPlanContext?: LearningPlanTutorContext
  learnerPathState?: LearnerPathState
  taskQueue?: AgentTaskQueueItem[]
  knowledgeDomains?: AgentKnowledgeDomain[]
  formalLearnerContext?: unknown
  formalWorkspaceContext?: unknown
  conversationId?: string
  sheetId?: string
  generate: TutorAgentToolRuntimeOptions['generate']
  searchConfiguration?: SearchProviderConfiguration
  invokeProvider: ProviderInvoke
  executeTool?: (
    name: string,
    args: Record<string, unknown>,
    options: TutorAgentToolRuntimeOptions,
    meta?: { callId?: string; sequence?: number; sourceUrls?: string[] },
  ) => Promise<TutorAgentToolExecution>
}

function turnId() {
  return `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`
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
    '读取工具可自主调用；当前没有向模型开放任何五核、路径、项目或文件写入工具。',
    '若学习者观察中存在 Claim 冲突，必须明确说明冲突并把纠正留给学习者确认；不得静默选择一边或声称已经改写画像。',
    '若工作区观察含 sourceConstraint，路线和讲解必须受当前项目来源覆盖范围约束；超出范围只能标为资料缺口，并在检索到新证据后补充。',
    '工作区中没有 Attempt 只表示当前作用域没有可见记录，不能推断学生第一次学习、从未练习或没有相关经历。',
    '工具失败时先依据错误类型决定重试、换工具或明确告知缺口。拿到足够证据后直接回答。',
  ].join('\n')
}

function availableTools(input: TutorAgentRuntimeInput) {
  return TUTOR_AGENT_TOOL_DEFINITIONS.filter(tool => (
    tool.name !== 'read_learning_path' || Boolean(input.learnerPathState)
  ))
}

function explicitToolCall(choice: TutorToolChoice, message: string): AgentToolCall | undefined {
  if (choice === 'auto') return undefined
  if (choice === 'search') return { id: `explicit-search-${Date.now()}`, name: 'search_computer_knowledge', arguments: { query: message } }
  return {
    id: `explicit-visual-${Date.now()}`,
    name: 'generate_learning_visual',
    arguments: { query: message, kind: choice },
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
  const hasUncommittedProposal = options.toolRuns.some(run => run.pathProposal || run.pathPlanProposal)
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
  if (searched && !options.toolRuns.some(run => run.kind === 'search' && run.sources?.some(source => reply.includes(source.url)))) {
    violations.push('missing_search_citation')
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
  const deadline = startedAt + MAX_WALL_TIME_MS
  const latestMessage = [...input.messages].reverse().find(message => message.role === 'user')?.content || ''
  const trajectory: AgentTrajectoryEvent[] = []
  const runs: TutorToolRun[] = []
  const runtimeMessages: RuntimeMessage[] = input.messages.slice(-18).map(message => ({ role: message.role, content: message.content }))
  const observations: AgentContextEnvelope['observations'] = []
  const signatures = new Set<string>()
  let modelRounds = 0
  let toolCalls = 0
  let sequence = 0
  let stopReason: AgentTurnResponse['trace']['stopReason'] = 'error'
  let fallbackReply = ''
  let pathGapPending = false

  const record = (event: Omit<AgentTrajectoryEvent, 'sequence' | 'at'>) => {
    trajectory.push({ ...event, sequence: ++sequence, at: Date.now() })
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
  }

  const execute = async (call: AgentToolCall, sourceUrls: string[] = []) => {
    const signature = `${call.name}:${JSON.stringify(call.arguments)}`
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
    if (toolCalls >= MAX_TOOL_CALLS) {
      record({ phase: 'act', detail: '达到工具调用预算', toolCallId: call.id, toolName: call.name, status: 'blocked' })
      return [] as string[]
    }
    signatures.add(signature)
    toolCalls += 1
    record({ phase: 'act', detail: `调用 ${call.name}`, toolCallId: call.id, toolName: call.name, status: 'started' })
    runtimeMessages.push({ role: 'assistant', content: '', toolCalls: [call] })
    const result = await (input.executeTool || executeTutorAgentTool)(call.name, call.arguments, toolOptions, {
      callId: call.id,
      sequence: toolCalls,
      sourceUrls,
    })
    runs.push(result.run)
    if (call.name === 'read_learning_path') {
      pathGapPending = Boolean((result.observation as any)?.needsExternalResearch)
        && !(result.observation as any)?.personalNodeProposal
    }
    observations.push({
      source: call.name,
      authority: String((result.observation as any)?.authority || 'tool_observation'),
      answerFree: call.name === 'read_learner_context'
        || call.name === 'read_learning_workspace'
        || call.name === 'read_learning_path',
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
    return result.searchSourceUrls || []
  }

  const refreshPathAfterSearch = async (urls: string[]) => {
    if (!pathGapPending || !urls.length || !input.learnerPathState) return
    await execute({
      id: `path-evidence-refresh-${id}-${toolCalls + 1}`,
      name: 'read_learning_path',
      arguments: { query: latestMessage, evidence_refresh: true },
    }, urls)
  }

  record({ phase: 'observe', detail: '开始组装本轮观察空间', status: 'started' })
  await execute({ id: `observe-memory-${id}`, name: 'read_learner_context', arguments: { query: latestMessage } })
  if (input.mode === 'guided_learning' || input.mode === 'learning_plan') {
    await execute({ id: `observe-workspace-${id}`, name: 'read_learning_workspace', arguments: { query: latestMessage } })
  }
  if (input.mode === 'learning_plan' && input.learnerPathState) {
    await execute({ id: `observe-path-${id}`, name: 'read_learning_path', arguments: { query: latestMessage } })
  }
  const explicit = explicitToolCall(input.toolChoice, latestMessage)
  if (explicit) {
    const urls = await execute(explicit)
    if (explicit.name === 'search_computer_knowledge') await refreshPathAfterSearch(urls)
  }
  record({ phase: 'observe', detail: `观察空间已就绪：${observations.length} 个结构化观察`, status: 'completed' })

  const envelope: AgentContextEnvelope = {
    version: 'vnext-agent-context.v1',
    scope: { mode: input.mode, conversationId: input.conversationId, sheetId: input.sheetId },
    current: {
      userMessage: latestMessage,
      selection: input.selectionContext,
      learningTask: input.learningTaskContext,
      learningPlan: input.learningPlanContext,
    },
    observations: observations.map(item => ({ ...item, data: undefined })),
    recentToolObservations: compactPriorRuns(input.messages),
    budgets: { maxModelRounds: MAX_MODEL_ROUNDS, maxToolCalls: MAX_TOOL_CALLS, maxWallTimeMs: MAX_WALL_TIME_MS },
  }
  const tools = availableTools(input)
  const instructions = buildTutorInstructions({
    mode: input.mode,
    selectionContext: input.selectionContext,
    learningTaskContext: input.learningTaskContext,
    learningPlanContext: input.learningPlanContext,
    toolContext: envelopePrompt(envelope),
  })

  let reply = ''
  let sourceUrls: string[] = runs.flatMap(run => run.sources || []).map(source => source.url)
  const invokeModel = async (request: ReturnType<typeof buildAgentProviderRequest>) => {
    let lastError: unknown
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await input.invokeProvider({
          ...request,
          timeoutMs: Math.max(1_000, Math.min(40_000, deadline - Date.now())),
        })
      } catch (error) {
        lastError = error
        const message = error instanceof Error ? error.message : String(error || '')
        const transient = /timeout|超时|429|rate|network|fetch|ECONN|temporar|503|502/i.test(message)
        if (!transient || attempt > 0 || Date.now() >= deadline - 1_000) throw error
        record({ phase: 'decide', detail: '模型请求遇到暂时故障，使用剩余预算重试一次', status: 'retrying' })
      }
    }
    throw lastError
  }
  try {
    for (let round = 0; round < MAX_MODEL_ROUNDS && Date.now() < deadline; round += 1) {
      modelRounds += 1
      record({ phase: 'decide', detail: `模型决策第 ${modelRounds} 轮`, status: 'started' })
      const request = buildAgentProviderRequest({
        baseUrl: input.baseUrl,
        model: input.model,
        instructions,
        messages: runtimeMessages,
        tools,
        includeTools: toolCalls < MAX_TOOL_CALLS,
      })
      const payload = await invokeModel(request)
      const calls = toolCallsFromProviderResponse(payload)
      const text = textFromTutorProviderResponse(payload)
      if (calls.length) {
        record({ phase: 'decide', detail: `模型选择 ${calls.length} 个工具`, status: 'completed' })
        for (const call of calls.slice(0, MAX_TOOL_CALLS - toolCalls)) {
          const urls = await execute(call, sourceUrls)
          if (urls.length) sourceUrls = [...new Set([...sourceUrls, ...urls])]
          if (call.name === 'search_computer_knowledge') await refreshPathAfterSearch(urls)
        }
        continue
      }
      const candidate = ensureSearchCitations(text, runs)
      const verification = verifyTutorTurnOutcome({
        reply: candidate,
        mode: input.mode,
        toolRuns: runs,
        learningTaskContext: input.learningTaskContext,
        observations,
      })
      if (verification.valid) {
        reply = candidate
        stopReason = 'final_answer'
        record({ phase: 'verify', detail: '最终回复通过展示协议校验', status: 'completed' })
        break
      }
      runtimeMessages.push({ role: 'assistant', content: text })
      runtimeMessages.push({
        role: 'user',
        content: `上一次输出未通过终态校验（${verification.violations.join('、')}）。请只输出自然的中文教学正文；不得冒充已写入状态、不得无证据宣布掌握，工具失败要透明说明；观察到记忆冲突时必须把冲突和确认权告诉学习者；没有可见 Attempt 只能说暂无记录，不能推断学生第一次学习或从未练习。`,
      })
      record({ phase: 'verify', detail: `回复未通过终态校验：${verification.violations.join('、')}`, status: 'failed' })
    }

    if (!reply) {
      stopReason = Date.now() >= deadline ? 'model_budget' : toolCalls >= MAX_TOOL_CALLS ? 'tool_budget' : 'forced_finalize'
      record({ phase: 'finalize', detail: '进入无工具最终收束', status: 'started' })
      runtimeMessages.push({
        role: 'user',
        content: '工具阶段已经结束。请基于已有观察直接给出完整、自然的中文教学回复；明确资料缺口，不再调用工具。',
      })
      const request = buildAgentProviderRequest({
        baseUrl: input.baseUrl,
        model: input.model,
        instructions,
        messages: runtimeMessages.slice(-24),
        tools,
        includeTools: false,
      })
      if (Date.now() < deadline) {
        const payload = await invokeModel(request)
        const text = textFromTutorProviderResponse(payload)
        const candidate = ensureSearchCitations(text, runs)
        if (verifyTutorTurnOutcome({
          reply: candidate,
          mode: input.mode,
          toolRuns: runs,
          learningTaskContext: input.learningTaskContext,
          observations,
        }).valid) reply = candidate
      }
      if (!reply && fallbackReply) reply = fallbackReply
      if (!reply) throw new Error('模型在本轮预算内没有返回可显示的教学内容')
      record({ phase: 'finalize', detail: '最终回复已收束', status: 'completed' })
    }
  } catch (error) {
    record({ phase: 'error', detail: error instanceof Error ? error.message.slice(0, 240) : 'Agent Runtime 失败', status: 'failed' })
    stopReason = 'error'
    if (!reply && fallbackReply) reply = fallbackReply
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
    },
  }
}
