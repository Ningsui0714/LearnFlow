export type LearningPlanKind = 'project_seed' | 'direction'
export type LearningPlanStatus = 'active' | 'closed'
export type ValueProposalDecision = 'proposed' | 'accepted' | 'rejected' | 'revision_requested'

export type ProjectPlanningField =
  | 'target_artifact'
  | 'baseline'
  | 'resources'
  | 'time_commitment'
  | 'practice_validation'
  | 'constraints'

export type DirectionPlanningField =
  | 'current_position'
  | 'candidate_directions'
  | 'decision_horizon'
  | 'decision_criteria'
  | 'exploration_evidence'
  | 'constraints'

export type PlanningField = ProjectPlanningField | DirectionPlanningField

export type PlanningSignal = {
  field: PlanningField
  value: string
}

export type ValueClaimProposal = {
  id: string
  currentClaim: string
  proposedClaim: string
  evidenceQuote: string
  rationale: string
  scope: 'long_term_direction_candidate'
  createdAt: number
}

// A planning dialogue collects requirements and proposals. A confirmed
// long-term route is a separate LearningPathPlan object.
export type PlanningDialogue = {
  id: string
  kind: LearningPlanKind
  objective: string
  createdAt: number
}

// Backward-compatible name for existing persisted vNext records.
export type LearningPlan = PlanningDialogue

export type PlanningEventType =
  | 'vnext_learning_plan_started'
  | 'vnext_learning_plan_note_captured'
  | 'vnext_project_seed_ready'
  | 'vnext_direction_plan_ready'
  | 'vnext_value_claim_proposed'
  | 'vnext_value_claim_proposal_accepted'
  | 'vnext_value_claim_proposal_rejected'
  | 'vnext_value_claim_proposal_revision_requested'
  | 'vnext_learning_plan_closed'

export type PlanningEvent = {
  id: string
  planId: string
  sequence: number
  type: PlanningEventType
  detail: string
  at: number
  signals?: PlanningSignal[]
  valueProposal?: ValueClaimProposal
  proposalId?: string
  formalWriteCompleted?: boolean
}

export type LearningPlanProjection = {
  plan: LearningPlan
  status: LearningPlanStatus
  signals: Partial<Record<PlanningField, string>>
  requirements: Array<{ id: PlanningField; label: string }>
  missingRequirements: Array<{ id: PlanningField; label: string }>
  noteCount: number
  eventCount: number
  valueProposal?: ValueClaimProposal & { decision: ValueProposalDecision; formalWriteCompleted: boolean }
}

export type LearningPlanTutorContext = {
  objectType: 'planning_dialogue'
  authority: 'browser_proposal_only'
  planId: string
  kind: LearningPlanKind
  kindLabel: string
  objective: string
  confirmedSignals: Array<{ label: string; value: string }>
  missingRequirements: string[]
  nextQuestion: string
  projectCreationAvailable: false
  valueProposal?: {
    currentClaim: string
    proposedClaim: string
    evidenceQuote: string
    decision: ValueProposalDecision
    formalWriteCompleted: boolean
  }
}

const PROJECT_REQUIREMENTS: LearningPlanProjection['requirements'] = [
  { id: 'target_artifact', label: '目标产物' },
  { id: 'baseline', label: '当前基础' },
  { id: 'resources', label: '来源与资源' },
  { id: 'time_commitment', label: '时间投入' },
  { id: 'practice_validation', label: '实践与验收' },
  { id: 'constraints', label: '现实约束' },
]

const DIRECTION_REQUIREMENTS: LearningPlanProjection['requirements'] = [
  { id: 'current_position', label: '当前位置' },
  { id: 'candidate_directions', label: '候选方向' },
  { id: 'decision_horizon', label: '决策时间' },
  { id: 'decision_criteria', label: '选择标准' },
  { id: 'exploration_evidence', label: '探索证据' },
  { id: 'constraints', label: '现实约束' },
]

const DIRECTION_PATTERN = /(?:未来|以后|职业|就业|工作方向|发展方向|科研方向|读研|升学|转行|从事什么|走什么方向|适合.*方向)/i
const COMPLEX_PLAN_PATTERN = /(?:系统(?:地)?学|完整(?:地)?学|学习规划|学习路线|路线图|从零.*(?:到|学)|几个月|半年|一年|长期学习|做一个.*(?:项目|系统|应用|作品)|构建.*(?:项目|系统|应用)|复现.*论文|围绕.*仓库.*学)/i
const EXPLICIT_VALUE_PATTERN = /(?:我(?:想|希望|打算|倾向|计划)|目标是|(?:未来|以后).*(?:做|从事|研究|方向)|准备(?:走|做|研究))/i

const CURRENT_VALUE_CLAIM = '希望深入机器学习、智能体工程与强化学习；未来可能走智能体相关工作或广义机器学习科研。'

function id(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function compact(value: string, limit = 180) {
  return value.replace(/\s+/g, ' ').trim().slice(0, limit)
}

export function hasPlanningIntent(input: string) {
  const text = compact(input, 500)
  return DIRECTION_PATTERN.test(text) || COMPLEX_PLAN_PATTERN.test(text)
}

export function classifyLearningPlan(input: string): LearningPlanKind {
  return DIRECTION_PATTERN.test(input) ? 'direction' : 'project_seed'
}

export function planningKindLabel(kind: LearningPlanKind) {
  return kind === 'direction' ? '发展方向规划' : '项目雏形规划'
}

function requirementsFor(kind: LearningPlanKind) {
  return kind === 'direction' ? DIRECTION_REQUIREMENTS : PROJECT_REQUIREMENTS
}

function extractSignals(kind: LearningPlanKind, input: string): PlanningSignal[] {
  const text = compact(input)
  const values: PlanningSignal[] = []
  const add = (field: PlanningField, pattern: RegExp) => {
    if (pattern.test(text)) values.push({ field, value: text })
  }
  if (kind === 'project_seed') {
    add('target_artifact', /(?:做|构建|实现|开发|完成|复现|产出|作品|项目|系统|应用)/i)
    add('baseline', /(?:学过|会用|熟悉|基础|目前|现在|专业|大[一二三四]|零基础)/i)
    add('resources', /(?:仓库|repo|github|教材|书|课程|文档|论文|视频|资料)/i)
    add('time_commitment', /(?:每天|每周|周末|小时|天|周|月|半年|一年|学期)/i)
    add('practice_validation', /(?:测试|验证|部署|演示|答辩|作品集|开源|复现|指标|验收|实践)/i)
  } else {
    add('current_position', /(?:目前|现在|专业|大[一二三四]|学过|会用|基础|工作)/i)
    add('candidate_directions', /(?:机器学习|深度学习|强化学习|智能体|agent|算法|工程|科研|读研|就业|方向)/i)
    add('decision_horizon', /(?:今年|明年|毕业|大[一二三四]|学期|月|半年|一年|几年)/i)
    add('decision_criteria', /(?:喜欢|兴趣|擅长|就业|收入|稳定|科研|论文|工程|成长|价值)/i)
    add('exploration_evidence', /(?:项目|实习|科研|比赛|论文|复现|开源|尝试|体验)/i)
  }
  add('constraints', /(?:限制|只能|不能|预算|设备|显卡|时间不多|课程|考试|压力|地点)/i)
  return [...new Map(values.map(signal => [signal.field, signal])).values()]
}

function valueClaimProposal(input: string, now: number): ValueClaimProposal | undefined {
  const quote = compact(input, 140)
  if (!EXPLICIT_VALUE_PATTERN.test(quote)) return undefined
  const claimText = quote
    .replace(/[，,；;]?(?:你|请)?(?:建议|帮我|告诉我).*(?:怎么|如何)?(?:规划|选择|发展).*$/i, '')
    .replace(/[。！？!?]+$/, '')
    .trim()
  return {
    id: id('value-proposal'),
    currentClaim: CURRENT_VALUE_CLAIM,
    proposedClaim: `当前方向候选：${claimText || quote.replace(/[。！？!?]+$/, '')}。`,
    evidenceQuote: quote,
    rationale: '只根据你在本轮明确表达的方向生成候选，不从一次选择推断固定职业、人格或能力。',
    scope: 'long_term_direction_candidate',
    createdAt: now,
  }
}

export function appendPlanningEvents(
  events: PlanningEvent[],
  planId: string,
  additions: Array<Omit<PlanningEvent, 'id' | 'planId' | 'sequence' | 'at'>>,
  now = Date.now(),
) {
  let sequence = events.filter(event => event.planId === planId).reduce((max, event) => Math.max(max, event.sequence), 0)
  return [...events, ...additions.map((event, index) => ({
    ...event,
    id: id('plan-event'),
    planId,
    sequence: ++sequence,
    at: now + index,
  }))]
}

export function createLearningPlan(input: string, now = Date.now(), existingEvents: PlanningEvent[] = []) {
  const kind = classifyLearningPlan(input)
  const objective = compact(input.replace(/^(?:请|帮我|我想|我希望|给我)?\s*(?:规划|制定)?\s*/i, ''), 160) || '新的学习规划'
  const plan: LearningPlan = { id: id('plan'), kind, objective, createdAt: now }
  const signals = extractSignals(kind, input)
  const proposal = kind === 'direction' ? valueClaimProposal(input, now) : undefined
  const additions: Array<Omit<PlanningEvent, 'id' | 'planId' | 'sequence' | 'at'>> = [
    { type: 'vnext_learning_plan_started', detail: `开始${planningKindLabel(kind)}：${objective}` },
    { type: 'vnext_learning_plan_note_captured', detail: `记录本轮明确规划信息：${signals.length} 项`, signals },
  ]
  if (proposal) additions.push({ type: 'vnext_value_claim_proposed', detail: '提出 Value Claim 修改候选；等待学生决定', valueProposal: proposal })
  return { plan, events: appendPlanningEvents(existingEvents, plan.id, additions, now) }
}

export function projectLearningPlan(plan: LearningPlan, events: PlanningEvent[]): LearningPlanProjection {
  const relevant = events.filter(event => event.planId === plan.id).sort((a, b) => a.sequence - b.sequence)
  const signals: Partial<Record<PlanningField, string>> = {}
  let status: LearningPlanStatus = 'active'
  let proposal: LearningPlanProjection['valueProposal']
  relevant.forEach(event => {
    event.signals?.forEach(signal => { signals[signal.field] = signal.value })
    if (event.type === 'vnext_value_claim_proposed' && event.valueProposal) {
      proposal = { ...event.valueProposal, decision: 'proposed', formalWriteCompleted: false }
    }
    if (proposal && event.proposalId === proposal.id) {
      if (event.type === 'vnext_value_claim_proposal_accepted') {
        proposal.decision = 'accepted'
        proposal.formalWriteCompleted = Boolean(event.formalWriteCompleted)
      }
      if (event.type === 'vnext_value_claim_proposal_rejected') proposal.decision = 'rejected'
      if (event.type === 'vnext_value_claim_proposal_revision_requested') proposal.decision = 'revision_requested'
    }
    if (event.type === 'vnext_learning_plan_closed') status = 'closed'
  })
  const requirements = requirementsFor(plan.kind)
  return {
    plan,
    status,
    signals,
    requirements,
    missingRequirements: requirements.filter(requirement => !signals[requirement.id]),
    noteCount: relevant.filter(event => event.type === 'vnext_learning_plan_note_captured').length,
    eventCount: relevant.length,
    valueProposal: proposal,
  }
}

export function activeLearningPlanProjection(plans: LearningPlan[], events: PlanningEvent[]) {
  return [...plans].reverse().map(plan => projectLearningPlan(plan, events)).find(projection => projection.status === 'active')
}

export function updateLearningPlan(events: PlanningEvent[], projection: LearningPlanProjection, input: string, now = Date.now()) {
  const signals = extractSignals(projection.plan.kind, input)
  const proposal = projection.plan.kind === 'direction' ? valueClaimProposal(input, now) : undefined
  const additions: Array<Omit<PlanningEvent, 'id' | 'planId' | 'sequence' | 'at'>> = [
    { type: 'vnext_learning_plan_note_captured', detail: `记录本轮明确规划信息：${signals.length} 项`, signals },
  ]
  if (proposal) additions.push({ type: 'vnext_value_claim_proposed', detail: '更新 Value Claim 修改候选；等待学生决定', valueProposal: proposal })
  const nextEvents = appendPlanningEvents(events, projection.plan.id, additions, now)
  const next = projectLearningPlan(projection.plan, nextEvents)
  const readinessThreshold = projection.plan.kind === 'project_seed' ? 4 : 4
  const confirmedCount = next.requirements.length - next.missingRequirements.length
  const readyEventType = projection.plan.kind === 'project_seed' ? 'vnext_project_seed_ready' : 'vnext_direction_plan_ready'
  if (confirmedCount >= readinessThreshold && !nextEvents.some(event => event.planId === projection.plan.id && event.type === readyEventType)) {
    return appendPlanningEvents(nextEvents, projection.plan.id, [{
      type: readyEventType,
      detail: projection.plan.kind === 'project_seed' ? '项目启动信息已形成可检查雏形；项目创建尚未接入' : '发展方向信息已形成可比较雏形',
    }], now + 2)
  }
  return nextEvents
}

export function decideValueClaimProposal(
  events: PlanningEvent[], projection: LearningPlanProjection,
  decision: Exclude<ValueProposalDecision, 'proposed'>, now = Date.now(), formalWriteCompleted = false,
) {
  const proposal = projection.valueProposal
  if (!proposal || proposal.decision !== 'proposed') return events
  const type = decision === 'accepted'
    ? 'vnext_value_claim_proposal_accepted'
    : decision === 'rejected'
      ? 'vnext_value_claim_proposal_rejected'
      : 'vnext_value_claim_proposal_revision_requested'
  const detail = decision === 'accepted'
    ? formalWriteCompleted
      ? '学生确认 Value Claim 候选；已通过正式事件入口写入价值核'
      : '学生确认 Value Claim 候选；正式后端不可用，本地保留待同步状态'
    : decision === 'rejected'
      ? '学生拒绝 Value Claim 候选；不写入'
      : '学生要求修改 Value Claim 候选；不写入'
  return appendPlanningEvents(events, projection.plan.id, [{ type, detail, proposalId: proposal.id, formalWriteCompleted }], now)
}

export function closeLearningPlan(events: PlanningEvent[], projection: LearningPlanProjection, now = Date.now()) {
  return appendPlanningEvents(events, projection.plan.id, [{ type: 'vnext_learning_plan_closed', detail: '结束本段规划；未自动创建项目或改写五核' }], now)
}

export function learningPlanTutorContext(projection: LearningPlanProjection): LearningPlanTutorContext {
  const labels = new Map(projection.requirements.map(requirement => [requirement.id, requirement.label]))
  return {
    objectType: 'planning_dialogue',
    authority: 'browser_proposal_only',
    planId: projection.plan.id,
    kind: projection.plan.kind,
    kindLabel: planningKindLabel(projection.plan.kind),
    objective: projection.plan.objective,
    confirmedSignals: Object.entries(projection.signals).map(([field, value]) => ({
      label: labels.get(field as PlanningField) || field,
      value,
    })),
    missingRequirements: projection.missingRequirements.map(requirement => requirement.label),
    nextQuestion: projection.missingRequirements[0]?.label || '请学生检查当前草案并指出要修订之处',
    projectCreationAvailable: false,
    valueProposal: projection.valueProposal ? {
      currentClaim: projection.valueProposal.currentClaim,
      proposedClaim: projection.valueProposal.proposedClaim,
      evidenceQuote: projection.valueProposal.evidenceQuote,
      decision: projection.valueProposal.decision,
      formalWriteCompleted: projection.valueProposal.formalWriteCompleted,
    } : undefined,
  }
}

export function sanitizeLearningPlanTutorContext(value: unknown): LearningPlanTutorContext | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  if (
    typeof item.planId !== 'string'
    || (item.kind !== 'project_seed' && item.kind !== 'direction')
    || typeof item.kindLabel !== 'string'
    || typeof item.objective !== 'string'
    || !Array.isArray(item.confirmedSignals)
    || !Array.isArray(item.missingRequirements)
  ) return undefined
  const confirmedSignals = item.confirmedSignals.filter(signal => {
    if (!signal || typeof signal !== 'object') return false
    const candidate = signal as Record<string, unknown>
    return typeof candidate.label === 'string' && typeof candidate.value === 'string'
  }).slice(0, 8).map(signal => {
    const candidate = signal as Record<string, unknown>
    return { label: String(candidate.label).slice(0, 40), value: String(candidate.value).slice(0, 220) }
  })
  const rawProposal = item.valueProposal && typeof item.valueProposal === 'object'
    ? item.valueProposal as Record<string, unknown>
    : undefined
  const valueProposal = rawProposal
    && typeof rawProposal.currentClaim === 'string'
    && typeof rawProposal.proposedClaim === 'string'
    && typeof rawProposal.evidenceQuote === 'string'
    && ['proposed', 'accepted', 'rejected', 'revision_requested'].includes(String(rawProposal.decision))
    ? {
        currentClaim: rawProposal.currentClaim.slice(0, 300),
        proposedClaim: rawProposal.proposedClaim.slice(0, 300),
        evidenceQuote: rawProposal.evidenceQuote.slice(0, 180),
        decision: rawProposal.decision as ValueProposalDecision,
        formalWriteCompleted: rawProposal.formalWriteCompleted === true,
      }
    : undefined
  return {
    objectType: 'planning_dialogue',
    authority: 'browser_proposal_only',
    planId: item.planId.slice(0, 100),
    kind: item.kind,
    kindLabel: item.kindLabel.slice(0, 60),
    objective: item.objective.slice(0, 300),
    confirmedSignals,
    missingRequirements: item.missingRequirements.filter(entry => typeof entry === 'string').slice(0, 8).map(entry => String(entry).slice(0, 50)),
    nextQuestion: typeof item.nextQuestion === 'string' ? item.nextQuestion.slice(0, 100) : '',
    projectCreationAvailable: false,
    valueProposal,
  }
}
