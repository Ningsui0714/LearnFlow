import type { LearningEvent, LearningSkillId } from './learning'
import type {
  LearningPathPlan,
  LearningPathPlanProposal,
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

export type FormalLearningSkillRun = {
  id: number
  skill: { id: LearningSkillId; name: string; description?: string }
  goal: string
  status: string
  state: string
  stage_label: string
  step_index: number
  total_steps: number
  turn_count: number
  turn_budget: number
  support_count: number
  flow_note: string
  version: number
  next_prompt: string
  can_start_verification: boolean
  can_pause: boolean
  can_resume: boolean
  learning_task?: {
    id: number
    title: string
    status: string
    current_phase_id: string
    plan_version: number
    version: number
    path?: string | null
    management_path?: string | null
    artifact_path?: string | null
  } | null
  micro_learning_run?: {
    id: number
    goal: string
    status: string
    state: string
    version: number
  } | null
}

export type FormalTutorSession = {
  id: number
  title: string
  session_type: 'global' | 'project' | 'checkpoint'
  project_id?: number | null
  checkpoint_id?: number | null
  active_skill_run?: FormalLearningSkillRun | null
  learning_tasks: FormalLearningTask[]
}

export type FormalPathOverlay = {
  version: 1 | 2
  statuses: Record<string, { status?: LearnerPathStatus; node_title?: string } | LearnerPathStatus>
  personal_nodes: Array<Record<string, unknown>>
  plans?: Array<Record<string, unknown>>
  active_plan_id?: string | null
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

export type FormalLearnerProfilePatch = Partial<FormalLearnerSnapshot['profile']>

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

export async function updateFormalLearnerProfile(patch: FormalLearnerProfilePatch) {
  return jsonRequest<{ profile: FormalLearnerSnapshot['profile']; evidence_id: number }>('/api/profile', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
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
  const explicitScope = 'payload' in event && event.payload && typeof event.payload === 'object'
    ? event.payload as Record<string, unknown>
    : {}
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
      session_id: typeof explicitScope.session_id === 'number' ? explicitScope.session_id : undefined,
      project_id: typeof explicitScope.project_id === 'number' ? explicitScope.project_id : undefined,
      checkpoint_id: typeof explicitScope.checkpoint_id === 'number' ? explicitScope.checkpoint_id : undefined,
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

export async function commitFormalLearningPathPlan(proposal: LearningPathPlanProposal, clientEventId: string) {
  return jsonRequest<{ learning_path: FormalPathOverlay }>('/api/learner-state/learning-path/plans', {
    method: 'POST',
    body: JSON.stringify({
      plan_id: proposal.id,
      title: proposal.title,
      objective: proposal.objective,
      horizon: proposal.horizon,
      target_node_ids: proposal.targetNodeIds,
      route_node_ids: proposal.routeNodeIds,
      milestone_node_ids: proposal.milestoneNodeIds,
      rationale: proposal.rationale,
      evidence_quote: proposal.evidenceQuote,
      source_plan_id: proposal.sourcePlanId || '',
      client_event_id: clientEventId,
    }),
  })
}

export async function archiveFormalLearningPathPlan(planId: string, clientEventId: string) {
  const query = new URLSearchParams({ client_event_id: clientEventId })
  return jsonRequest<{ learning_path: FormalPathOverlay }>(`/api/learner-state/learning-path/plans/${encodeURIComponent(planId)}?${query}`, {
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

export async function createFormalTutorSession(createNew = true) {
  return jsonRequest<FormalTutorSession>('/api/agent/sessions', {
    method: 'POST',
    body: JSON.stringify({ session_type: 'global', create_new: createNew }),
  })
}

export async function loadFormalTutorSession(sessionId: number) {
  return jsonRequest<FormalTutorSession>(`/api/agent/sessions/${sessionId}`)
}

export async function startFormalLearningSkillRun(
  sessionId: number,
  skillId: LearningSkillId,
  goal: string,
  clientRequestId: string,
) {
  return jsonRequest<{
    session_id: number
    active_skill_run: FormalLearningSkillRun
    created: boolean
  }>(`/api/agent/sessions/${sessionId}/skill-runs`, {
    method: 'POST',
    body: JSON.stringify({
      skill_id: skillId,
      goal,
      client_request_id: clientRequestId,
    }),
  })
}

export async function advanceFormalLearningSkillTurn(
  sessionId: number,
  runId: number,
  message: string,
  expectedVersion: number,
  clientTurnId: string,
) {
  return jsonRequest<{
    session_id: number
    active_skill_run: FormalLearningSkillRun
    turn_plan?: { directive?: string; fallback?: string }
    created: boolean
  }>(`/api/agent/sessions/${sessionId}/skill-runs/${runId}/turns`, {
    method: 'POST',
    body: JSON.stringify({
      message,
      expected_version: expectedVersion,
      client_turn_id: clientTurnId,
    }),
  })
}

export async function actOnFormalLearningSkillRun(
  sessionId: number,
  run: Pick<FormalLearningSkillRun, 'id' | 'version'>,
  action: 'pause' | 'resume' | 'start_verification',
) {
  return jsonRequest<{
    session_id: number
    active_skill_run: FormalLearningSkillRun
    learning_run?: Record<string, unknown> | null
  }>(`/api/agent/sessions/${sessionId}/skill-runs/${run.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      expected_version: run.version,
      client_action_id: `vnext-skill-action:${run.id}:${action}:${Date.now()}`,
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
  for (const raw of overlay.plans || []) {
    const id = String(raw.id || '')
    const targetNodeIds = Array.isArray(raw.target_node_ids) ? raw.target_node_ids.map(String).slice(0, 8) : []
    const routeNodeIds = Array.isArray(raw.route_node_ids) ? raw.route_node_ids.map(String).slice(0, 40) : []
    if (!id || !targetNodeIds.length || !targetNodeIds.every(nodeId => routeNodeIds.includes(nodeId))) continue
    const plan: LearningPathPlan = {
      id,
      title: String(raw.title || raw.objective || id),
      objective: String(raw.objective || ''),
      horizon: String(raw.horizon || '长期'),
      targetNodeIds,
      routeNodeIds,
      milestoneNodeIds: Array.isArray(raw.milestone_node_ids) ? raw.milestone_node_ids.map(String).slice(0, 16) : [],
      rationale: String(raw.rationale || ''),
      evidenceQuote: String(raw.evidence_quote || ''),
      sourcePlanId: raw.source_plan_id ? String(raw.source_plan_id) : undefined,
      status: 'active',
      revision: Math.max(1, Number(raw.revision) || 1),
    }
    events.push({
      id: `formal-path-plan:${id}:${plan.revision}`,
      sequence: ++sequence,
      at: sequence,
      type: 'vnext_learning_path_plan_committed',
      detail: '从正式结构核恢复的长期学习路径',
      plan,
    })
  }
  return { version: 1, events }
}
