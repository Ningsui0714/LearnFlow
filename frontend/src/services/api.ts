import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 90000,
  withCredentials: true,
})

const DESKTOP_AUTH_STORAGE_KEY = 'learnflow.desktop.auth-token'

export function configureDesktopApi(baseURL: string, desktopToken: string) {
  api.defaults.baseURL = baseURL
  api.defaults.headers.common['X-LearnFlow-Desktop-Token'] = desktopToken
  const authToken = sessionStorage.getItem(DESKTOP_AUTH_STORAGE_KEY)
  if (authToken) api.defaults.headers.common.Authorization = `Bearer ${authToken}`
}

api.interceptors.response.use(
  response => {
    const desktopAuthToken = response?.data?.desktop_auth_token
    if (typeof desktopAuthToken === 'string' && desktopAuthToken) {
      sessionStorage.setItem(DESKTOP_AUTH_STORAGE_KEY, desktopAuthToken)
      api.defaults.headers.common.Authorization = `Bearer ${desktopAuthToken}`
    }
    return response
  },
  error => {
    if (error?.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('learnflow:unauthorized'))
    }
    return Promise.reject(error)
  },
)

export interface AuthUser {
  id: number
  username: string
  display_name: string
  learner_id: number
  is_legacy_demo: boolean
  is_dev_login: boolean
  dev_test_login_enabled: boolean
  desktop_auth_token?: string
  profile: {
    education_stage: string
    background: string
    focus_areas: string[]
    weekly_hours: number
    preferred_modes: string[]
    career_goal: string
    career_goal_status: 'exploring' | 'confirmed'
  }
}

export interface RegisterPayload {
  username: string
  password: string
  display_name: string
  education_stage: string
  background: string
  focus_areas: string[]
  weekly_hours: number
  preferred_modes: string[]
  career_goal?: string
  career_goal_status: 'exploring' | 'confirmed'
}

export const getCurrentUser = () => api.get('/auth/me').then(r => r.data as AuthUser)
export const loginUser = (username: string, password: string) =>
  api.post('/auth/login', { username, password }).then(r => r.data as AuthUser)
export const registerUser = (data: RegisterPayload) =>
  api.post('/auth/register', data).then(r => r.data as AuthUser)
export const logoutUser = () => api.post('/auth/logout').then(r => {
  sessionStorage.removeItem(DESKTOP_AUTH_STORAGE_KEY)
  delete api.defaults.headers.common.Authorization
  return r.data
})
export const listDevAccounts = () => api.get('/dev/accounts').then(r => r.data)
export const devLogin = (accountId: number) =>
  api.post(`/dev/accounts/${accountId}/login`).then(r => r.data as AuthUser)

export const getProfile = () => api.get('/profile').then(r => r.data)
export const getGrowth = () => api.get('/profile/growth').then(r => r.data)
export const updateProfile = (data: Record<string, any>) => api.patch('/profile', data).then(r => r.data)
export const getProfileMemories = () => api.get('/profile/memories').then(r => r.data)
export const archiveProfileMemory = (memoryId: string, reason = '') =>
  api.post(`/profile/memories/${encodeURIComponent(memoryId)}/archive`, { reason }).then(r => r.data)
export const restoreProfileMemory = (memoryId: string) =>
  api.post(`/profile/memories/${encodeURIComponent(memoryId)}/restore`).then(r => r.data)
export const getLearningJourney = () => api.get('/profile/journey').then(r => r.data)

export type MemoryKernel = 'structure' | 'knowledge' | 'human' | 'value' | 'practice'
export type MemoryNodeType = 'fact' | 'module' | 'claim'

export interface MemoryGraphNode {
  id: number
  type: MemoryNodeType
  kernel: MemoryKernel
  subject: string
  text: string
  payload: Record<string, any>
  confidence: number
  status: string
  valid_from?: string
  valid_to?: string
  occurred_at: string
  created_at: string
  fact?: {
    source_event_id: number
    source_mutation_id: number
    predicate: string
    value: any
    evidence_grade: string
    consumption_status: string
    consumed_by_module_id?: number
    project_id?: number
    checkpoint_id?: number
    session_id?: number
  }
  module?: {
    synthesis_run_id?: number
    module_type: string
    summary: string
    time_start: string
    time_end: string
    immutable: boolean
  }
  claim?: {
    module_id: number
    predicate: string
    value: any
    verification_status: string
  }
}

export interface MemoryGraphEdge {
  id: number
  source: number
  target: number
  relation: string
  origin: string
  confidence: number
  payload: Record<string, any>
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  page: { limit: number; has_more: boolean; next_after_id?: number }
}

export const getMemoryGraph = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/memory/graph', { params }).then(r => r.data as MemoryGraphResponse)

export const getMemoryNode = (nodeId: number) =>
  api.get(`/memory/nodes/${nodeId}`).then(r => r.data)

export const getMemoryConsolidations = (status?: string) =>
  api.get('/memory/consolidations', { params: { status } }).then(r => r.data)

export const submitMemoryClaimFeedback = (
  claimId: number,
  data: { action: 'confirm' | 'correct' | 'retract'; correction?: string; reason?: string },
) => api.post(`/memory/claims/${claimId}/feedback`, data).then(r => r.data)

// ── Project ──
export const createProject = (data: { name: string; description?: string; user_level?: string }) =>
  api.post('/projects', data).then(r => r.data)

export const listProjects = () =>
  api.get('/projects').then(r => r.data)

export const getProject = (id: number) =>
  api.get(`/projects/${id}`).then(r => r.data)

// ── Desktop project workspace ──
export type WorkspaceNodeKind =
  | 'managed_lecture'
  | 'managed_exercise'
  | 'workspace_text'
  | 'workspace_binary'
  | 'protected'

export interface WorkspaceNode {
  name: string
  path: string
  kind: WorkspaceNodeKind
  is_directory: boolean
  size?: number
  modified_at?: string
  protected_reason?: string
  children: WorkspaceNode[]
}

export interface WorkspaceTree {
  workspace_id: number
  project_id: number
  root_name: string
  nodes: WorkspaceNode[]
}

export interface WorkspaceFile {
  path: string
  kind: WorkspaceNodeKind
  content?: string
  sha256?: string
  size: number
  modified_at: string
  read_only: boolean
  mime_type?: string
  previewable: boolean
}

export interface WorkspaceOperation {
  id: number
  project_id: number
  actor: 'user' | 'agent'
  operation: 'create' | 'write' | 'mkdir' | 'rename' | 'move' | 'delete' | 'restore'
  status: string
  target_path: string
  destination_path?: string
  base_hash?: string
  result: Record<string, any>
  expires_at?: string
  created_at: string
  confirmed_at?: string
  applied_at?: string
}

const workspaceFileUrl = (projectId: number, path: string) =>
  `/projects/${projectId}/workspace/files/${path.split('/').map(encodeURIComponent).join('/')}`

export const linkProjectWorkspace = (
  projectId: number,
  data: { root_path: string; platform: string; create: boolean; client_request_id: string },
) => api.post(`/projects/${projectId}/workspace/link`, data).then(r => r.data)

export const getWorkspaceTree = (projectId: number) =>
  api.get(`/projects/${projectId}/workspace/tree`).then(r => r.data as WorkspaceTree)

export const getCheckpointWorkspaceArtifacts = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/workspace/artifacts`).then(r => r.data)

export const getWorkspaceFile = (projectId: number, path: string) =>
  api.get(workspaceFileUrl(projectId, path)).then(r => r.data as WorkspaceFile)

export const saveWorkspaceFile = (
  projectId: number,
  path: string,
  data: { content: string; base_hash?: string; idempotency_key: string },
) => api.put(workspaceFileUrl(projectId, path), data).then(r => r.data as WorkspaceOperation)

export const proposeWorkspaceOperation = (
  projectId: number,
  data: {
    actor: 'user' | 'agent'
    operation: WorkspaceOperation['operation']
    target_path: string
    destination_path?: string
    content?: string
    base_hash?: string
    checkpoint_id?: number
    session_id?: number
    source_operation_id?: number
    idempotency_key: string
  },
) => api.post(`/projects/${projectId}/workspace/operations/propose`, data)
  .then(r => r.data as WorkspaceOperation)

export const confirmWorkspaceOperation = (projectId: number, operationId: number) =>
  api.post(`/projects/${projectId}/workspace/operations/${operationId}/confirm`)
    .then(r => r.data as WorkspaceOperation)

export const listWorkspaceOperations = (
  projectId: number,
  params: { operation?: string; status?: string } = {},
) => api.get(`/projects/${projectId}/workspace/operations`, { params })
  .then(r => r.data.operations as WorkspaceOperation[])

export const revealWorkspaceItem = (projectId: number, path: string) =>
  api.post(`/projects/${projectId}/workspace/reveal`, { path }).then(r => r.data)

export const openWorkspaceItem = (projectId: number, path: string) =>
  api.post(`/projects/${projectId}/workspace/open`, { path }).then(r => r.data)

const workspacePreviewUrl = (projectId: number, path: string) =>
  `/projects/${projectId}/workspace/previews/${path.split('/').map(encodeURIComponent).join('/')}`

export const getWorkspacePreview = (projectId: number, path: string) =>
  api.get(workspacePreviewUrl(projectId, path), { responseType: 'blob' })
    .then(r => URL.createObjectURL(r.data))

// ── Source ──
export const addSource = (projectId: number, data: { type: string; url?: string }) =>
  api.post(`/projects/${projectId}/sources`, data).then(r => r.data)

export const uploadSource = (projectId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/projects/${projectId}/sources/upload`, form).then(r => r.data)
}

export const listSources = (projectId: number) =>
  api.get(`/projects/${projectId}/sources`).then(r => r.data)

export const processSource = (projectId: number, sourceId: number) =>
  api.post(`/projects/${projectId}/sources/${sourceId}/process`).then(r => r.data)

export const processAllSources = (projectId: number) =>
  api.post(`/projects/${projectId}/sources/process-all`).then(r => r.data)

export const startImageCaptioning = (projectId: number, sourceId: number, limit?: number, mode: 'free' | 'api' = 'free') =>
  api.post(`/projects/${projectId}/sources/${sourceId}/images/caption`, { limit, mode }).then(r => r.data)

export const setSourceRole = (projectId: number, sourceId: number, role: 'main' | 'auxiliary') =>
  api.put(`/projects/${projectId}/sources/${sourceId}/role`, { role }).then(r => r.data)

export const reconcileSources = (projectId: number) =>
  api.post(`/projects/${projectId}/reconcile`).then(r => r.data)

export const applyReconcile = (projectId: number, suggestion: any) =>
  api.post(`/projects/${projectId}/reconcile/apply`, suggestion).then(r => r.data)

// ── Chunk ──
export const listChunks = (projectId: number) =>
  api.get(`/projects/${projectId}/chunks`).then(r => r.data)

// ── Roadmap ──
export const getRoadmap = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap`).then(r => r.data)

// ── Agent ──
export const sendAgentMessage = (projectId: number, data: { message: string; history: any[] }) =>
  api.post(`/projects/${projectId}/roadmap/chat`, data).then(r => r.data)

export const getRoadmapHistory = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap/history`).then(r => r.data)

// ── Main Tutor ──
export interface LearningSkill {
  id: string
  name: string
  description: string
  best_for?: string[]
  avoid_when?: string[]
  atomic_task_capable?: boolean
}

export interface LearningSkillRecommendation {
  skill: LearningSkill
  goal?: string
  reason: string
  matched_signals: string[]
  requires_confirmation: boolean
  policy_version: string
}

export interface LearningSkillRun {
  id: number
  skill: LearningSkill
  runtime_version: string
  goal: string
  status: 'active' | 'paused' | 'verification' | 'completed' | 'canceled'
  state: string
  stage_label: string
  step_index: number
  total_steps: number
  turn_count: number
  turn_budget: number
  version: number
  next_prompt: string
  can_start_verification: boolean
  can_pause: boolean
  can_resume: boolean
  verification_required: boolean
  evidence_note: string
  learning_task?: {
    id: number
    title: string
    status: string
    current_phase_id: string
    plan_version: number
    version: number
    path: string
  } | null
  micro_learning_run?: {
    id: number
    goal: string
    status: string
    state: string
    version: number
    summary?: Record<string, any>
  } | null
  started_at?: string | null
  completed_at?: string | null
  updated_at?: string | null
}

export interface TutorSessionSummary {
  id: number
  title: string
  session_type: 'global' | 'project' | 'checkpoint'
  project_id?: number | null
  checkpoint_id?: number | null
  active_skill?: LearningSkill | null
  last_message?: string
  created_at?: string | null
  updated_at?: string | null
}

export const listTutorSessions = (sessionType?: 'global' | 'project' | 'checkpoint', limit = 30) =>
  api.get('/agent/sessions', { params: { session_type: sessionType, limit } }).then(r => r.data as TutorSessionSummary[])

export const listLearningSkills = () =>
  api.get('/agent/skills').then(r => r.data as LearningSkill[])

export const startLearningSkillRun = (
  sessionId: number,
  data: {
    skill_id: 'guided_explanation' | 'socratic_dialogue' | 'feynman_dialogue' | 'worked_example_fading'
    goal: string
    client_request_id: string
  },
) => api.post(`/agent/sessions/${sessionId}/skill-runs`, data).then(r => r.data)

export const updateLearningSkillRun = (
  sessionId: number,
  runId: number,
  data: {
    action: 'pause' | 'resume' | 'start_verification'
    expected_version: number
    client_action_id: string
  },
) => api.post(`/agent/sessions/${sessionId}/skill-runs/${runId}/actions`, data).then(r => r.data)

export const createTutorSession = (data: { session_type?: 'global' | 'project' | 'checkpoint'; project_id?: number; checkpoint_id?: number; create_new?: boolean }) =>
  api.post('/agent/sessions', data).then(r => r.data)

export const getTutorSession = (sessionId: number) =>
  api.get(`/agent/sessions/${sessionId}`).then(r => r.data)

export const sendTutorTurn = (sessionId: number, data: {
  message: string
  project_id?: number
  checkpoint_id?: number
  selected_action_id?: number
  selected_skill_id?: string
  client_turn_id?: string
  context?: Record<string, any>
}) => api.post(`/agent/sessions/${sessionId}/turns`, data).then(r => r.data)

export const confirmTutorAction = (actionId: number) =>
  api.post(`/agent/actions/${actionId}/confirm`).then(r => r.data)

export const cancelTutorAction = (actionId: number) =>
  api.post(`/agent/actions/${actionId}/cancel`).then(r => r.data)

export const getTutorAction = (actionId: number) =>
  api.get(`/agent/actions/${actionId}`).then(r => r.data)

export interface LocalAgentProfile {
  id: number
  name: string
  adapter: 'codex_cli' | 'deterministic_fake'
  executable_path?: string | null
  enabled: boolean
  priority: number
  task_types: string[]
  capabilities: string[]
  sandbox_policy: string
  network_policy: 'unmanaged' | 'managed_off' | 'managed_on'
  timeout_seconds: number
  last_probe: Record<string, any>
}

export interface LocalAgentRun {
  id: number
  project_id: number
  checkpoint_id: number
  session_id: number
  action_id: number
  profile_id: number
  task_type: string
  goal: string
  constraints: string[]
  required_capabilities: string[]
  status: 'queued' | 'running' | 'completed' | 'failed' | 'canceled' | 'stale' | 'applied'
  changed_files: Array<{
    operation: 'create' | 'write' | 'delete' | 'move'
    path: string
    destination_path?: string
    diff?: string
    requires_separate_confirmation?: boolean
  }>
  diff_text: string
  result: Record<string, any>
  error: Record<string, any>
}

export const listLocalAgentProfiles = () =>
  api.get('/desktop/agent-profiles').then(r => r.data as LocalAgentProfile[])

export const createLocalAgentProfile = (data: {
  name: string
  adapter?: 'codex_cli'
  executable_path?: string | null
  enabled?: boolean
  priority?: number
  task_types?: string[]
  capabilities?: string[]
  sandbox_policy?: 'workspace_write'
  network_policy?: 'unmanaged'
  timeout_seconds?: number
}) => api.post('/desktop/agent-profiles', data).then(r => r.data as LocalAgentProfile)

export const updateLocalAgentProfile = (profileId: number, data: Record<string, any>) =>
  api.patch(`/desktop/agent-profiles/${profileId}`, data).then(r => r.data as LocalAgentProfile)

export const deleteLocalAgentProfile = (profileId: number) =>
  api.delete(`/desktop/agent-profiles/${profileId}`).then(r => r.data)

export const getLocalAgentRun = (runId: number) =>
  api.get(`/local-agent/runs/${runId}`).then(r => r.data as LocalAgentRun)

export const getLocalAgentRunEvents = (runId: number, after = 0) =>
  api.get(`/local-agent/runs/${runId}/events`, { params: { after } }).then(r => r.data)

export const cancelLocalAgentRun = (runId: number) =>
  api.post(`/local-agent/runs/${runId}/cancel`).then(r => r.data as LocalAgentRun)

export const applyLocalAgentRun = (
  runId: number,
  data: { confirm_apply: boolean; confirmed_deletions: string[]; confirmed_moves: string[]; idempotency_key: string },
) => api.post(`/local-agent/runs/${runId}/apply`, data).then(r => r.data as LocalAgentRun)

export interface ProjectProposalMilestone {
  id: string
  title: string
  purpose?: string
  estimated_effort?: string
}

export interface ProjectProposalSource {
  title: string
  url: string
  type: 'github' | 'url'
  description?: string
  stars?: number
  forks?: number
  language?: string
  license?: string
  pushed_at?: string
  rank_score?: number
  quality?: 'excellent' | 'strong' | 'relevant'
  match_reasons?: string[]
  reason?: string
}

export interface ProjectProposal {
  id: number
  proposal_key: string
  proposal_type: 'build' | 'mastery' | 'exam' | 'research'
  status: string
  action_type: 'create' | 'enter_existing'
  target_project_id?: number
  accepted_project_id?: number
  artifact: {
    title: string
    learning_goal: string
    practice_goal: string
    learner_start: string[]
    estimated_effort: string
    milestones: ProjectProposalMilestone[]
    acceptance_criteria: string[]
    risks: string[]
    assumptions?: string[]
    details?: Record<string, any>
    candidate_sources?: ProjectProposalSource[]
    source_search_generation?: number
    source_search_requested_at?: string
    source_search_refreshed_at?: string
    source_search_discovered_count?: number
    source_search_partial_failures?: number
    source_search_result_changed?: boolean
    source_search_last_error?: string
  }
  revision: number
  locked_fields: string[]
  last_change_summary: string
  source_status: 'idle' | 'queued' | 'searching' | 'completed' | 'failed'
  source_task_id?: number
  updated_at?: string
}

export const getProjectProposal = (proposalId: number) =>
  api.get(`/agent/project-proposals/${proposalId}`).then(r => r.data as ProjectProposal)

export const getAcceptedProjectProposal = (projectId: number) =>
  api.get(`/agent/projects/${projectId}/accepted-proposal`).then(r => r.data as ProjectProposal | null)

export const updateProjectProposal = (proposalId: number, data: {
  patch?: Record<string, any>
  lock_fields?: string[]
  unlock_fields?: string[]
  client_event_id?: string
}) => api.patch(`/agent/project-proposals/${proposalId}`, data).then(r => r.data as ProjectProposal)

export const acceptProjectProposal = (proposalId: number, clientEventId: string) =>
  api.post(`/agent/project-proposals/${proposalId}/accept`, { client_event_id: clientEventId }).then(r => r.data)

export const dismissProjectProposal = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/dismiss`).then(r => r.data as ProjectProposal)

export const reopenProjectProposal = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/reopen`).then(r => r.data as ProjectProposal)

export const refreshProjectProposalSources = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/refresh-sources`).then(r => r.data as ProjectProposal)

export const recordLearningEvent = (data: {
  client_event_id: string
  event_type: string
  project_id?: number
  checkpoint_id?: number
  session_id?: number
  payload?: Record<string, any>
}) => api.post('/learning-events', data).then(r => r.data)

// ── Focused micro-learning ──
export interface MicroLearningQuestion {
  id: number
  question: string
  options: string[]
  q_type: 'single' | 'multi' | 'judge'
  difficulty: string
  order: number
  learning_target: string
  evidence_claim: string
}

export type LearningTaskSurfaceKind = 'conversation' | 'checkpoint' | 'focused_learning' | 'task'

export interface LearningTaskNavigation {
  kind: LearningTaskSurfaceKind
  path: string
}

export interface MicroLearningRun {
  id: number
  goal: string
  source_type: 'topic' | 'provided_text'
  source_excerpt: string
  status: 'active' | 'paused' | 'completed'
  state: 'learning_card' | 'teach_back' | 'teach_back_feedback' | 'verification' | 'remediation' | 'paused' | 'completed'
  version: number
  project_id: number
  checkpoint_id: number
  session_id?: number
  skill_plan: Record<string, any>
  learning_card: {
    title?: string
    objective?: string
    key_points?: string[]
    target_concepts?: string[]
    example?: string
    common_confusion?: string
    success_criteria?: string
    generation_mode?: 'model_enhanced' | 'deterministic_fallback' | 'unknown'
    generation_reason?: string
    generation_source?: string
  }
  teach_back: Record<string, any>
  verification: Record<string, any>
  summary: Record<string, any>
  questions: MicroLearningQuestion[]
  current_question: MicroLearningQuestion | null
  remediation?: any
  progress: {
    current: number
    total: number
    completed_questions: number
    total_questions: number
  }
  learning_task?: {
    id: number
    title: string
    status: LearningTaskStatus
    current_phase_id: string
    path: string
    navigation: LearningTaskNavigation
    origin_navigation: LearningTaskNavigation
    management_navigation: LearningTaskNavigation
    artifact_refs: Array<Record<string, any>>
  } | null
  started_at?: string
  completed_at?: string
  updated_at?: string
}

export const createMicroLearningRun = (data: {
  goal: string
  source_text?: string
  client_request_id: string
}) => api.post('/micro-learning/runs', data).then(r => r.data as MicroLearningRun)

export const listMicroLearningRuns = (limit = 8) =>
  api.get('/micro-learning/runs', { params: { limit } })
    .then(r => r.data.items as MicroLearningRun[])

export const getMicroLearningRun = (runId: number) =>
  api.get(`/micro-learning/runs/${runId}`).then(r => r.data as MicroLearningRun)

export const advanceMicroLearningRun = (
  runId: number,
  data: {
    action: 'complete_card' | 'continue_after_feedback' | 'pause' | 'resume'
    expected_version: number
    client_action_id: string
  },
) => api.post(`/micro-learning/runs/${runId}/advance`, data)
  .then(r => r.data as MicroLearningRun)

export const regenerateMicroLearningRun = (
  runId: number,
  data: { expected_version: number; client_request_id: string },
) => api.post(`/micro-learning/runs/${runId}/regenerate`, data)
  .then(r => r.data as MicroLearningRun)

export const submitMicroLearningTeachBack = (
  runId: number,
  data: { response: string; expected_version: number; client_submission_id: string },
) => api.post(`/micro-learning/runs/${runId}/teach-back`, data)
  .then(r => r.data as MicroLearningRun)

export const syncMicroLearningRun = (
  runId: number,
  data: { expected_version?: number; client_action_id: string },
) => api.post(`/micro-learning/runs/${runId}/sync`, data)
  .then(r => r.data as MicroLearningRun)

// ── Lecture (Phase 2) ──
export const getLecture = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture`).then(r => r.data)

// ── Process animations (process-animator) ──
export interface AnimationStep {
  title: string
  text: string
  bars?: { values: number[]; highlight?: number[]; pivot?: number[]; sorted?: number[]; done?: number[] }
  svg?: string
}
export interface ProcessAnimation {
  id?: number
  checkpoint_id?: number
  section_index?: number
  source?: string
  kind?: 'animation' | 'static'
  title?: string
  subtitle?: string
  legend?: [string, string][]
  steps: AnimationStep[]
}
export const generateAnimation = (text: string) =>
  api.post('/animations/generate', { text }).then(r => r.data)
export const getAnimation = (id: number) =>
  api.get(`/animations/${id}`).then(r => r.data)

export const generateConceptGraph = (checkpointId: number) =>
  api.post(`/checkpoints/${checkpointId}/concept-graph/generate`).then(r => r.data)

export const getConceptGraphTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concept-graph/task`).then(r => r.data)

export interface TaskEventSubscription {
  close: () => void
}

function streamingHeaders() {
  const headers = new Headers()
  for (const [name, value] of Object.entries(api.defaults.headers.common)) {
    if (typeof value === 'string') headers.set(name, value)
  }
  return headers
}

function apiUrl(path: string) {
  return api.getUri({ url: path })
}

async function consumeSSE(response: Response, onData: (data: any) => void, signal: AbortSignal) {
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`服务器错误 (${response.status})${detail ? `: ${detail.slice(0, 200)}` : ''}`)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('响应无数据流')

  const decoder = new TextDecoder()
  let buffer = ''
  const deliver = (frame: string) => {
    const payload = frame.split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
      .join('\n')
    if (!payload) return
    try { onData(JSON.parse(payload)) } catch { /* Ignore malformed SSE frames. */ }
  }

  while (!signal.aborted) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    frames.forEach(deliver)
  }
  buffer += decoder.decode()
  if (buffer.trim()) deliver(buffer)
}

/**
 * Subscribe to a task snapshot stream with the current API base URL and auth
 * headers. Native EventSource cannot attach the desktop sidecar token, so it
 * would silently fail in Tauri after a task was successfully created.
 */
export function subscribeTaskEvents(
  taskId: number,
  onSnapshot: (snapshot: any) => void,
  onError: (message: string) => void,
): TaskEventSubscription {
  const controller = new AbortController()
  let polling = false

  const sleep = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

  // The sidecar can briefly restart or the WebView can lose an SSE stream.
  // Keep observing the persisted task instead of turning a still-running job
  // into a false UI failure.  The task API is the same source of truth used by
  // the SSE endpoint, so reconnecting is safe and idempotent.
  const pollUntilTerminal = async () => {
    if (polling || controller.signal.aborted) return
    polling = true
    let failures = 0
    try {
      while (!controller.signal.aborted && failures < 12) {
        try {
          const snapshot = (await api.get(`/tasks/${taskId}`)).data
          failures = 0
          onSnapshot(snapshot)
          if (['completed', 'failed', 'canceled'].includes(snapshot.status)) return
        } catch (error: any) {
          failures += 1
          if (failures >= 12) {
            onError(error instanceof Error ? error.message : '任务状态同步失败')
            return
          }
        }
        await sleep(1000)
      }
    } finally {
      polling = false
    }
  }

  void fetch(apiUrl(`/tasks/${taskId}/events`), {
    headers: streamingHeaders(),
    credentials: 'include',
    signal: controller.signal,
  })
    .then(response => consumeSSE(response, onSnapshot, controller.signal))
    .catch((error: unknown) => {
      if (!controller.signal.aborted) {
        void pollUntilTerminal().catch(() => {
          if (!controller.signal.aborted) onError(error instanceof Error ? error.message : '网络错误')
        })
      }
    })

  return { close: () => controller.abort() }
}

// Legacy direct-lecture stream kept for compatibility with older callers.
export function subscribeLectureSSE(
  checkpointId: number,
  onSection: (data: any) => void,
  onDone: (data: any) => void,
  onError: (msg: string) => void,
  onStatus?: (msg: string) => void,
) {
  let aborted = false
  const controller = new AbortController()
  let firstData = false

  // Timeout: if no data within 90s, report error
  const timeoutId = setTimeout(() => {
    if (!firstData && !aborted) {
      aborted = true
      onError('生成超时（90s）：AI 模型响应较慢，请稍后重试。如果持续出现，检查 API Key 和网络连接。')
    }
  }, 90000)

  const abort = () => {
    aborted = true
    controller.abort()
    clearTimeout(timeoutId)
  }

  const doFetch = async () => {
    try {
      const resp = await fetch(apiUrl(`/checkpoints/${checkpointId}/lecture/generate`), {
        headers: streamingHeaders(),
        credentials: 'include',
        signal: controller.signal,
      })

      if (!resp.ok) {
        clearTimeout(timeoutId)
        const body = await resp.text().catch(() => '')
        onError(`服务器错误 (${resp.status}): ${body.slice(0, 200)}`)
        return
      }

      firstData = true
      clearTimeout(timeoutId)

      const reader = resp.body?.getReader()
      if (!reader) {
        onError('响应无数据流')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (!aborted) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const event of events) {
          for (const line of event.split('\n')) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === 'section') {
                  onSection(data)
                } else if (data.type === 'status') {
                  if (onStatus) onStatus(data.message || '')
                } else if (data.type === 'done') {
                  onDone(data)
                  return
                } else if (data.type === 'error') {
                  onError(data.message || '未知错误')
                  return
                }
              } catch { /* skip parse errors */ }
            }
          }
        }
      }
    } catch (e: any) {
      if (!aborted) {
        onError(`连接失败: ${e.message || '网络错误'}`)
      }
    }
  }

  doFetch()

  return { close: abort }
}

export const saveLecture = (
  checkpointId: number, sections: any[], baseVersion: number, idempotencyKey: string,
) => api.put(`/checkpoints/${checkpointId}/lecture`, {
  sections, base_version: baseVersion, idempotency_key: idempotencyKey,
}).then(r => r.data)

// ── Tasks (T1: background jobs) ──
export const createLectureTask = (checkpointId: number, mode: 'fresh' | 'resume' = 'fresh', feedback?: string) =>
  api.post(`/checkpoints/${checkpointId}/lecture/generate`, { mode, feedback: feedback || '' }).then(r => r.data)

export const getActiveLectureTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/task`).then(r => r.data)

export const listLectureVersions = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/versions`).then(r => r.data)

export const rollbackLecture = (checkpointId: number, versionId: number) =>
  api.post(`/checkpoints/${checkpointId}/lecture/rollback`, { version_id: versionId }).then(r => r.data)

export const getTaskStatus = (taskId: number) =>
  api.get(`/tasks/${taskId}`).then(r => r.data)

export const cancelTask = (taskId: number) =>
  api.post(`/tasks/${taskId}/cancel`).then(r => r.data)

export const askQuestion = (checkpointId: number, data: { selection: string; question: string; history: any[]; action?: string }) =>
  api.post(`/checkpoints/${checkpointId}/ask`, data).then(r => r.data)

// ── T9: anchored notes ──
export const listNotes = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/notes`).then(r => r.data)

export const createNote = (checkpointId: number, data: { section_index: number; selection: string; note: string }) =>
  api.post(`/checkpoints/${checkpointId}/notes`, data).then(r => r.data)

export const updateNote = (noteId: number, note: string) =>
  api.put(`/notes/${noteId}`, { note }).then(r => r.data)

export const deleteNote = (noteId: number) =>
  api.delete(`/notes/${noteId}`).then(r => r.data)

export interface ArtifactAnnotation {
  id: number
  checkpoint_id: number
  artifact_type: 'lecture' | 'exercise'
  artifact_id: number
  artifact_version: number
  section_index: number
  surface: string
  selection: string
  anchor: Record<string, any>
  note: string
  status: 'anchored' | 'orphaned'
}

export const listArtifactAnnotations = (artifactType: 'lecture' | 'exercise', artifactId: number) =>
  api.get(`/artifacts/${artifactType}/${artifactId}/annotations`)
    .then(r => r.data as ArtifactAnnotation[])

export const createArtifactAnnotation = (
  artifactType: 'lecture' | 'exercise', artifactId: number,
  data: { anchor: Record<string, any>; body: string; idempotency_key: string },
) => api.post(`/artifacts/${artifactType}/${artifactId}/annotations`, data)
  .then(r => r.data as ArtifactAnnotation)

export const updateArtifactAnnotation = (annotationId: number, body: string) =>
  api.put(`/artifact-annotations/${annotationId}`, { body }).then(r => r.data as ArtifactAnnotation)

export const deleteArtifactAnnotation = (annotationId: number) =>
  api.delete(`/artifact-annotations/${annotationId}`).then(r => r.data)

// ── Phase 3: Exercises & Code ──
export const listExercises = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/exercises`).then(r => r.data)

export const getExercise = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}`).then(r => r.data)

export const getExerciseDraft = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}/draft`).then(r => r.data)

export const saveExerciseDraft = (exerciseId: number, code: string, files: any[]) =>
  api.put(`/exercises/${exerciseId}/draft`, { code, files }).then(r => r.data)

export const runCode = (code: string, exerciseId?: number) => {
  const url = exerciseId ? `/exercises/${exerciseId}/run` : '/exercises/run'
  return api.post(url, { code }).then(r => r.data)
}

// ── Project-mode exercises (multi-file, pilot) ──
export const runProject = (exerciseId: number, files: any[]) =>
  api.post(`/exercises/${exerciseId}/run`, { code: '', files }).then(r => r.data)

export const getExerciseEnv = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}/env`).then(r => r.data)

export const submitProject = (
  exerciseId: number,
  files: any[],
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
  clientSubmissionId?: string,
) => api.post(`/exercises/${exerciseId}/submit`, {
  code: '', files, assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId, attempt_role: attemptRole,
  client_submission_id: clientSubmissionId,
}).then(r => r.data)

export const reviewCode = (exerciseId: number, code: string, selection?: string) =>
  api.post(`/exercises/${exerciseId}/review`, { code, selection }).then(r => r.data)

export const askCodeQuestion = (data: { code: string; selection: string; question: string; context?: string }) =>
  api.post('/code/ask', data).then(r => r.data)

// ── T7: Concept questions ──
export const listConcepts = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concepts`).then(r => r.data)

export const generateConcepts = (checkpointId: number) =>
  api.post(`/checkpoints/${checkpointId}/concepts/generate`).then(r => r.data)

export const getConceptTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concepts/task`).then(r => r.data)

export const explainConcept = (checkpointId: number, questionId: number, userAnswerIndexes: number[]) =>
  api.post(`/checkpoints/${checkpointId}/concepts/${questionId}/explain`, { user_answer_indexes: userAnswerIndexes }).then(r => r.data)

export const submitConcept = (
  checkpointId: number,
  questionId: number,
  answerIndexes: number[],
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
  clientSubmissionId?: string,
) => api.post(`/checkpoints/${checkpointId}/concepts/${questionId}/submit`, {
  answer_indexes: answerIndexes,
  assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId,
  attempt_role: attemptRole,
  client_submission_id: clientSubmissionId,
}).then(r => r.data)

// ── T8: exercise submit ──
export const submitExercise = (
  exerciseId: number,
  code: string,
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
  clientSubmissionId?: string,
) => api.post(`/exercises/${exerciseId}/submit`, {
  code,
  assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId,
  attempt_role: attemptRole,
  client_submission_id: clientSubmissionId,
}).then(r => r.data)

// ── Explicit remediation loop ──
export const getRemediationCase = (caseId: number) =>
  api.get(`/remediation/${caseId}`).then(r => r.data)

export const listRemediationCases = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/remediation-cases`).then(r => r.data)

export const changeRemediationExplanation = (
  caseId: number, action: 'switch' | 'steps' | 'example',
) => api.post(`/remediation/${caseId}/explanations`, { action }).then(r => r.data)

export const createRemediationVariant = (caseId: number) =>
  api.post(`/remediation/${caseId}/variant`).then(r => r.data)

export const submitRemediationVariant = (
  caseId: number, data: { answer_indexes?: number[]; answer_text?: string },
) => api.post(`/remediation/${caseId}/variant/submit`, data).then(r => r.data)

// ── Learner-visible learning task runtime ──
export type LearningTaskStatus = 'proposed' | 'queued' | 'active' | 'paused' | 'completed' | 'canceled'

export interface LearningTaskPhase {
  id: string
  kind: 'learn' | 'practice' | 'verify' | 'consolidate'
  title: string
  purpose: string
  methods: string[]
  required: boolean
  status: 'pending' | 'completed'
  completion_rule: string
  artifact_outputs: string[]
  completed_at?: string
}

export interface LearningTask {
  id: number
  title: string
  objective: string
  status: LearningTaskStatus
  origin_kind: string
  created_by: string
  session_id?: number
  project_id?: number
  checkpoint_id?: number
  micro_learning_run_id?: number
  priority: number
  queue_position: number
  estimated_minutes: number
  due_at?: string
  success_criteria: string[]
  plan: {
    schema_version: string
    summary: string
    estimated_minutes: number
    phases: LearningTaskPhase[]
    adaptation_triggers: string[]
  }
  current_phase_id: string
  plan_version: number
  execution_state: Record<string, any>
  artifact_refs: Array<{
    type: string
    id?: number
    ids?: number[]
    logical_filename?: string
    path?: string
  }>
  review_handoff: Record<string, any>
  navigation: LearningTaskNavigation
  origin_navigation: LearningTaskNavigation
  management_navigation: LearningTaskNavigation
  runtime: {
    runtime_version: string
    current_phase: Partial<LearningTaskPhase>
    next_action: { id: string; label: string; path?: string }
    materials: {
      status: 'not_prepared' | 'partial' | 'ready'
      lecture?: Record<string, any> | null
      question_set?: Record<string, any> | null
      exercises: Array<Record<string, any>>
    }
    evidence: {
      learning_events: number
      practice_attempts: number
      successful_verifications: number
      review_items: number
    }
    state_boundary: Record<string, string>
    learning_flow: {
      kind: LearningTaskSurfaceKind
      state: string
      active_state: string
      status: string
      completed_items: number
      total_items: number
    }
  }
  available_actions: string[]
  version: number
  plan_history: Array<{ id: number; version: number; source: string; reason: string; created_at?: string }>
  evidence_notice: string
}

export const getLearningTaskSummary = () =>
  api.get('/learning-tasks/summary').then(r => r.data)

export const listLearningTasks = (params: Record<string, string | number | boolean | undefined> = {}) =>
  api.get('/learning-tasks', { params }).then(r => r.data as { items: LearningTask[] })

export const getLearningTask = (taskId: number) =>
  api.get(`/learning-tasks/${taskId}`).then(r => r.data as LearningTask)

export const createLearningTask = (data: {
  title: string
  objective: string
  session_id?: number
  project_id?: number
  checkpoint_id?: number
  priority?: number
  estimated_minutes?: number
  preferred_skills?: string[]
  success_criteria?: string[]
  client_request_id: string
}) => api.post('/learning-tasks', data).then(r => r.data as LearningTask)

export const updateLearningTask = (
  taskId: number,
  data: Partial<Pick<LearningTask, 'title' | 'objective' | 'priority' | 'estimated_minutes' | 'due_at' | 'success_criteria'>> & { expected_version: number },
) => api.patch(`/learning-tasks/${taskId}`, data).then(r => r.data as LearningTask)

export const actOnLearningTask = (taskId: number, data: {
  action: 'accept' | 'start' | 'pause' | 'resume' | 'cancel' | 'reopen' | 'complete_phase' | 'complete_task'
  expected_version: number
  client_action_id: string
  phase_id?: string
  evidence_refs?: Array<Record<string, any>>
}) => api.post(`/learning-tasks/${taskId}/actions`, data).then(r => r.data as LearningTask)

export const replanLearningTask = (taskId: number, data: {
  reason: string
  learner_direction?: string
  preferred_skills?: string[]
  expected_version: number
  client_request_id: string
}) => api.post(`/learning-tasks/${taskId}/replan`, data).then(r => r.data as LearningTask)

export const materializeLearningTask = (taskId: number, data: {
  source_text?: string
  expected_version: number
  client_request_id: string
}) => api.post(`/learning-tasks/${taskId}/materialize`, data).then(r => r.data as LearningTask)

export const reorderLearningTasks = (taskIds: number[], clientRequestId: string) =>
  api.post('/learning-tasks/reorder', {
    task_ids: taskIds,
    client_request_id: clientRequestId,
  }).then(r => r.data as { items: LearningTask[] })

// ── Global spaced review workbench ──
export const getReviewSummary = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/review/summary', { params }).then(r => r.data)

export const listReviewItems = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/review/items', { params }).then(r => r.data)

export const getReviewItem = (scheduleId: number) =>
  api.get(`/review/items/${scheduleId}`).then(r => r.data)

export const getReviewHistory = (scheduleId: number) =>
  api.get(`/review/items/${scheduleId}/history`).then(r => r.data)

export const submitReviewItem = (scheduleId: number, data: {
  expected_version: number
  client_submission_id: string
  response_status: 'answered' | 'unknown' | 'skipped'
  answer_indexes?: number[]
  answer_text?: string
  code?: string
  files?: Array<Record<string, any>>
  assistance_level?: 'none' | 'hint' | 'guided'
  presentation_version: string
}) => api.post(`/review/items/${scheduleId}/submit`, data).then(r => r.data)

export const manageReviewItem = (
  scheduleId: number,
  action: 'defer' | 'suspend' | 'resume',
  data: { expected_version: number; client_event_id: string },
) => api.post(`/review/items/${scheduleId}/${action}`, data).then(r => r.data)

export const getCompetitionDemoStatus = () =>
  api.get('/demo/status').then(r => r.data)

export const competitionDemoLogin = () =>
  api.post('/demo/login').then(r => r.data)

export const getCompetitionDemoManifest = () =>
  api.get('/demo/manifest').then(r => r.data)

export const getExerciseTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/exercises/task`).then(r => r.data)

export default api
