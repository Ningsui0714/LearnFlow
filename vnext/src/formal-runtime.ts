import type { LearningEvent, LearningSkillId, LearningTask as LocalLearningTask } from './learning'
import type {
  LearnerPathState,
  LearnerPathStatus,
  PersonalPathNodeProposal,
} from './learning-path-graph'
import type { PlanningEvent, ValueClaimProposal } from './planning'

export type KernelName = 'structure' | 'knowledge' | 'human' | 'value' | 'practice'
export type FormalRuntimeStatus = 'connecting' | 'connected' | 'offline' | 'auth_required'

export type FormalLearner = {
  id: number
  display_name: string
  education_stage: string
}

export type FormalKernelMemory = {
  memory_id: string
  title: string
  summary: string
  retention: 'long' | 'recent'
  retention_label: string
  source_kind: string
  source_label: string
  related_record_count: number
  updated_at?: string | null
  status: 'active' | 'archived'
}

export type FormalGrowthArea = {
  id: string
  title: string
  description?: string
  active_count: number
  memories: FormalKernelMemory[]
}

export type FormalClaim = {
  id: number
  text: string
  status: string
  confidence: number
  predicate: string
  verification_status: string
}

export type FormalMemoryModule = {
  id: number
  kernel: KernelName
  subject_key: string
  title: string
  summary: string
  version: number
  revision_kind: string
  evidence_fact_ids: number[]
  claims: FormalClaim[]
}

export type FormalLearningTask = {
  id: number
  title: string
  objective: string
  status: 'proposed' | 'queued' | 'active' | 'paused' | 'completed' | 'canceled'
  origin_kind: string
  priority: number
  queue_position: number
  estimated_minutes: number
  preferred_skills?: string[]
  source_refs: Array<Record<string, unknown>>
  success_criteria: string[]
  current_phase_id: string
  available_actions: string[]
  version: number
  created_at?: string | null
  updated_at?: string | null
}

export type FormalPathOverlay = {
  version: 1
  statuses: Record<string, { status?: LearnerPathStatus; node_title?: string } | LearnerPathStatus>
  personal_nodes: Array<Record<string, unknown>>
  event_backed: true
  knowledge_mastery_inference: false
}

export type FormalConceptTimelineEntry = {
  fact_id: number
  event_id: number
  occurred_at: string
  event_type: string
  observation_type: string
  statement: string
  evidence_grade: string
  verification: string
  source_tag: string
  raw_text: string
  question_ref: Record<string, unknown>
  mastery_inference: boolean | null
  correctable: boolean
}

export type FormalConceptEvidenceClaim = {
  claim_id: number
  statement: string
  predicate: string
  verification_status: string
  status: string
  confidence: number
  module_version: number
  evidence_fact_ids: number[]
}

export type FormalConceptNode = {
  concept_key: string
  name: string
  aliases: string[]
  origin: string
  official_node_id?: string | null
  knowledge_event_count: number
  structure_relation_count: number
  knowledge: {
    timeline: FormalConceptTimelineEntry[]
    latest_observation?: FormalConceptTimelineEntry | null
    evidence_grades: string[]
    verified_count: number
    self_reported_count: number
    claims: FormalConceptEvidenceClaim[]
    current_state: {
      status: string
      certain_claims: FormalConceptEvidenceClaim[]
      uncertain_observations: FormalConceptTimelineEntry[]
      conflicts: FormalConceptTimelineEntry[]
    }
    mastery_claim: FormalConceptEvidenceClaim | null
  }
}

export type FormalConceptEdge = {
  id: string
  source_key: string
  target_key: string
  relation_type: string
  label: string
  rationale: string
  evidence_event_id: number
  verification: string
  source_tag: string
  mastery_inference: false
}

export type FormalConceptGraph = {
  version: string
  authority: string
  nodes: FormalConceptNode[]
  edges: FormalConceptEdge[]
  manifest: {
    node_count: number
    edge_count: number
    knowledge_owns_node_history: true
    structure_owns_relations: true
    shared_identity_only: true
    official_course_graph_is_separate: true
    self_report_never_implies_mastery: true
    truncated_at_fact_count: number
  }
}

export type FormalLearnerSnapshot = {
  authority: string
  learner: FormalLearner
  profile: {
    background: string
    focus_areas: string[]
    weekly_hours: number
    preferred_modes: string[]
    career_goal: string
    career_goal_status: string
  }
  kernels: Record<KernelName, { short_term: Record<string, unknown>; long_term: Record<string, unknown>; confidence: number; evidence_refs: unknown[] }>
  growth: {
    overview: Record<string, unknown>
    stats: Record<string, number>
    areas: FormalGrowthArea[]
    evidence: Array<Record<string, unknown>>
  }
  modules: FormalMemoryModule[]
  concept_graph: FormalConceptGraph
  learning_path: FormalPathOverlay
  learning_tasks: FormalLearningTask[]
}

export type FormalRuntimeConnection = {
  status: FormalRuntimeStatus
  detail: string
  learner?: FormalLearner
}

type DevAccount = {
  id: number
  display_name: string
  username: string
  last_login_at?: string | null
  is_legacy_demo?: boolean
}

function errorText(payload: unknown, fallback: string) {
  if (payload && typeof payload === 'object') {
    const detail = (payload as Record<string, unknown>).detail || (payload as Record<string, unknown>).error
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

async function jsonRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers || {}),
    },
  })
  const text = await response.text()
  let payload: unknown = null
  try { payload = text ? JSON.parse(text) : null } catch { payload = text }
  if (!response.ok) throw new Error(errorText(payload, `请求失败（${response.status}）`))
  return payload as T
}

export async function listFormalDevAccounts() {
  return jsonRequest<DevAccount[]>('/api/dev/accounts')
}

export async function loginFormalDevAccount(accountId: number) {
  return jsonRequest<Record<string, unknown>>(`/api/dev/accounts/${accountId}/login`, { method: 'POST' })
}

async function ensureFormalIdentity() {
  try {
    return await jsonRequest<Record<string, unknown>>('/api/auth/me')
  } catch (error) {
    const message = error instanceof Error ? error.message : ''
    if (!/登录|401|认证|凭据/.test(message)) throw error
  }
  const accounts = await listFormalDevAccounts()
  const candidates = [...accounts].sort((left, right) => {
    if (Boolean(left.is_legacy_demo) !== Boolean(right.is_legacy_demo)) return left.is_legacy_demo ? 1 : -1
    return String(right.last_login_at || '').localeCompare(String(left.last_login_at || ''))
  })
  if (!candidates[0]) throw new Error('正式后端还没有可用学习者，请先注册或启用开发账号')
  await loginFormalDevAccount(candidates[0].id)
  return jsonRequest<Record<string, unknown>>('/api/auth/me')
}

export async function loadFormalLearnerSnapshot(includeTerminalTasks = false): Promise<FormalLearnerSnapshot> {
  await ensureFormalIdentity()
  return jsonRequest<FormalLearnerSnapshot>(`/api/learner-state/snapshot?include_terminal_tasks=${includeTerminalTasks ? 'true' : 'false'}`)
}

export async function bootstrapFormalRuntime(): Promise<{ connection: FormalRuntimeConnection; snapshot?: FormalLearnerSnapshot }> {
  try {
    const snapshot = await loadFormalLearnerSnapshot()
    return {
      connection: { status: 'connected', detail: snapshot.authority, learner: snapshot.learner },
      snapshot,
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : '正式后端暂不可用'
    return {
      connection: {
        status: /学习者|登录|认证/.test(detail) ? 'auth_required' : 'offline',
        detail,
      },
    }
  }
}

export async function syncFormalEvent(event: LearningEvent | PlanningEvent | {
  id: string
  type: 'chat_mode_entered' | 'learning_action_segment_completed'
  at: number
  detail: string
  payload?: Record<string, unknown>
}) {
  const payload: Record<string, unknown> = {
    detail: event.detail,
    ...('taskId' in event ? { local_task_id: event.taskId } : {}),
    ...('planId' in event ? { local_plan_id: event.planId } : {}),
    ...('skillId' in event && event.skillId ? { skill_id: event.skillId } : {}),
    ...('stepId' in event && event.stepId ? { step_id: event.stepId } : {}),
    ...('signals' in event && event.signals ? { signals: event.signals } : {}),
    ...('valueProposal' in event && event.valueProposal ? { value_proposal: event.valueProposal } : {}),
    ...('payload' in event && event.payload ? event.payload : {}),
  }
  return jsonRequest<{ event_id: number; learner_seq: number }>('/api/learner-state/events', {
    method: 'POST',
    body: JSON.stringify({
      event_type: event.type,
      client_event_id: event.id,
      occurred_at: new Date(event.at).toISOString(),
      payload,
    }),
  })
}

export async function syncFormalEvents(events: Array<LearningEvent | PlanningEvent>) {
  const results = await Promise.allSettled(events.map(syncFormalEvent))
  const failed = results.find(result => result.status === 'rejected')
  if (failed?.status === 'rejected') throw failed.reason
}

export async function setFormalPathStatus(nodeId: string, nodeTitle: string, status: LearnerPathStatus, clientEventId: string) {
  return jsonRequest<{ learning_path: FormalPathOverlay }>('/api/learner-state/learning-path/status', {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, node_title: nodeTitle, status, client_event_id: clientEventId }),
  })
}

export async function addFormalPersonalPathNode(proposal: PersonalPathNodeProposal, clientEventId: string) {
  const node = {
    id: proposal.id,
    title: proposal.title,
    summary: proposal.summary,
    aliases: proposal.aliases,
    domains: proposal.domains,
    stage: proposal.stage,
    order: proposal.order,
    origin: 'personal',
    sourceRefs: proposal.sourceUrls,
  }
  const edges = proposal.connections.map((connection, index) => ({
    id: `personal-edge:${proposal.id}:${connection.nodeId}:${index}`,
    from: connection.kind === 'co_learning' ? proposal.id : connection.nodeId,
    to: connection.kind === 'co_learning' ? connection.nodeId : proposal.id,
    kind: connection.kind,
    rationale: connection.rationale,
    origin: 'personal',
  }))
  return jsonRequest<{ learning_path: FormalPathOverlay }>('/api/learner-state/learning-path/personal-nodes', {
    method: 'POST',
    body: JSON.stringify({ node, edges, reason: '学习者确认加入个人学习路径', client_event_id: clientEventId }),
  })
}

export async function removeFormalPersonalPathNode(nodeId: string, nodeTitle: string, clientEventId: string) {
  const query = new URLSearchParams({ client_event_id: clientEventId, node_title: nodeTitle })
  return jsonRequest<{ learning_path: FormalPathOverlay }>(`/api/learner-state/learning-path/personal-nodes/${encodeURIComponent(nodeId)}?${query}`, {
    method: 'DELETE',
  })
}

export async function confirmFormalValueClaim(proposal: ValueClaimProposal, clientEventId: string) {
  return jsonRequest<{ event_id: number; status: string }>('/api/learner-state/value-claims/confirm', {
    method: 'POST',
    body: JSON.stringify({
      proposal_id: proposal.id,
      current_claim: proposal.currentClaim,
      proposed_claim: proposal.proposedClaim,
      evidence_quote: proposal.evidenceQuote,
      scope: proposal.scope,
      client_event_id: clientEventId,
    }),
  })
}

export async function recordFormalConceptStatement(rawText: string, clientEventId: string) {
  return jsonRequest<{
    statement_event_id: number
    knowledge_event_ids: number[]
    structure_event_ids: number[]
    extracted: { concepts: Array<Record<string, unknown>>; relations: Array<Record<string, unknown>> }
    concept_graph: FormalConceptGraph
  }>('/api/learner-state/concept-graph/statements', {
    method: 'POST',
    body: JSON.stringify({
      raw_text: rawText,
      source_tag: 'user_self_input',
      client_event_id: clientEventId,
    }),
  })
}

export async function createFormalLearningTask(task: LocalLearningTask, skillId: LearningSkillId, conversationId: string) {
  return jsonRequest<FormalLearningTask>('/api/learning-tasks', {
    method: 'POST',
    body: JSON.stringify({
      title: task.objective.slice(0, 255),
      objective: task.objective,
      estimated_minutes: 25,
      preferred_skills: [skillId],
      source_refs: [{ kind: 'vnext_conversation', conversation_id: conversationId, local_task_id: task.id }],
      success_criteria: ['完成当前 Skill 的必要学习动作', '至少完成一次无答案泄露的迁移或独立检查'],
      client_request_id: `vnext-task:${task.id}`,
    }),
  })
}

export async function actOnFormalLearningTask(task: FormalLearningTask, action: 'start' | 'pause' | 'resume' | 'cancel' | 'reopen') {
  return jsonRequest<FormalLearningTask>(`/api/learning-tasks/${task.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      expected_version: task.version,
      client_action_id: `vnext-task-action:${task.id}:${action}:${Date.now()}`,
      evidence_refs: [],
    }),
  })
}

export async function submitFormalClaimFeedback(claimId: number, action: 'confirm' | 'correct' | 'retract', correction = '', reason = '') {
  return jsonRequest<Record<string, unknown>>(`/api/memory/claims/${claimId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ action, correction, reason }),
  })
}

export async function setFormalMemoryArchived(memoryId: string, archived: boolean) {
  return jsonRequest<Record<string, unknown>>(`/api/profile/memories/${encodeURIComponent(memoryId)}/${archived ? 'archive' : 'restore'}`, {
    method: 'POST',
    body: archived ? JSON.stringify({ reason: '学习者在五核画像页选择不再提供给 Agent 参考' }) : undefined,
  })
}

function statusValue(value: FormalPathOverlay['statuses'][string]): LearnerPathStatus {
  if (typeof value === 'string') return value
  return value?.status || 'unmarked'
}

export function learnerPathStateFromFormal(overlay: FormalPathOverlay): LearnerPathState {
  let sequence = 0
  const events: LearnerPathState['events'] = []
  Object.entries(overlay.statuses || {}).forEach(([nodeId, value]) => {
    const status = statusValue(value)
    if (status === 'unmarked') return
    events.push({
      id: `formal-path-status:${nodeId}`,
      sequence: ++sequence,
      at: sequence,
      type: 'vnext_learning_path_node_status_set',
      detail: '从正式结构核恢复的学习者自报节点状态',
      nodeId,
      status,
    })
  })
  for (const raw of overlay.personal_nodes || []) {
    const id = String(raw.id || '')
    const title = String(raw.title || '')
    if (!id || !title) continue
    const sourceRefs = Array.isArray(raw.sourceRefs) ? raw.sourceRefs.map(String) : []
    const edges = Array.isArray(raw.edges) ? raw.edges.filter(item => item && typeof item === 'object').map(item => item as any) : []
    events.push({
      id: `formal-personal-node:${id}`,
      sequence: ++sequence,
      at: sequence,
      type: 'vnext_personal_path_node_added',
      detail: '从正式结构核恢复的个人节点',
      node: {
        id,
        title,
        summary: String(raw.summary || ''),
        aliases: Array.isArray(raw.aliases) ? raw.aliases.map(String) : [],
        domains: Array.isArray(raw.domains) ? raw.domains.map(String) : [],
        audiences: ['self_directed'],
        stage: ['foundation', 'core', 'domain', 'advanced', 'research'].includes(String(raw.stage)) ? raw.stage as any : 'advanced',
        order: Number(raw.order || 6),
        origin: 'personal',
        sourceRefs,
      },
      edges,
    })
  }
  return { version: 1, events }
}
