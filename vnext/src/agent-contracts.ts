import type { LearningPlanTutorContext } from './planning.ts'
import type { LearningTaskTutorContext } from './learning.ts'
import type { LearnerPathState } from './learning-path-graph.ts'
import type { TutorMode, TutorContextMessage } from './tutor.ts'
import type { TutorToolChoice, TutorToolRun } from './tooling.ts'

export type AgentToolClass =
  | 'perception'
  | 'execution'
  | 'collaboration'
  | 'event'
  | 'communication'

export type AgentToolRisk = 'read_only' | 'artifact' | 'proposal' | 'confirmation_required'

export type AgentToolDefinition = {
  name: string
  title: string
  description: string
  toolClass: AgentToolClass
  risk: AgentToolRisk
  inputSchema: {
    type: 'object'
    properties: Record<string, Record<string, unknown>>
    required?: string[]
    additionalProperties: false
  }
}

export type AgentToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export type AgentTrajectoryEvent = {
  sequence: number
  phase: 'observe' | 'decide' | 'act' | 'verify' | 'finalize' | 'error'
  detail: string
  at: number
  toolCallId?: string
  toolName?: string
  status?: 'started' | 'completed' | 'failed' | 'blocked' | 'retrying'
}

export type AgentContextEnvelope = {
  version: 'vnext-agent-context.v1'
  scope: {
    mode: TutorMode
    conversationId?: string
    sheetId?: string
  }
  current: {
    userMessage: string
    selection?: string
    learningTask?: LearningTaskTutorContext
    learningPlan?: LearningPlanTutorContext
  }
  observations: Array<{
    source: string
    authority: string
    answerFree: boolean
    data: unknown
  }>
  recentToolObservations: TutorToolRun[]
  budgets: {
    maxModelRounds: number
    maxToolCalls: number
    maxWallTimeMs: number
  }
}

export type AgentTurnTrace = {
  version: 'vnext-agent-trace.v1'
  turnId: string
  modelRounds: number
  toolCalls: number
  stopReason: 'final_answer' | 'tool_budget' | 'model_budget' | 'forced_finalize' | 'error'
  events: AgentTrajectoryEvent[]
}

export type AgentTaskQueueItem = {
  id: number
  objective: string
  status: string
  sourceType?: string
  sourceId?: string
  updatedAt?: string
}

export type AgentKnowledgeDomain = {
  id: string
  title: string
  summary?: string
  labels?: string[]
  sourceIds?: string[]
}

export type AgentFormalScope = {
  sessionId?: number
  projectId?: number
  checkpointId?: number
}

export type AgentTurnRequest = {
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
  formalScope?: AgentFormalScope
  conversationId?: string
  sheetId?: string
}

export type AgentTurnResponse = {
  reply: string
  toolRuns: TutorToolRun[]
  trace: AgentTurnTrace
}
