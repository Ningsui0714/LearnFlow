export type LearningSkillId =
  | 'guided_explanation'
  | 'socratic_dialogue'
  | 'feynman_dialogue'
  | 'worked_example_fading'

// Kept only to project browser events written by v0.5. New tasks do not use a universal phase model.
export type LegacyLearningPhase = 'learn' | 'practice' | 'verify' | 'consolidate'
export type LearningTaskStatus = 'active' | 'paused' | 'completed'
export type LearningSubstateId =
  | 'guidance'
  | 'demonstration'
  | 'inquiry'
  | 'teachback'
  | 'diagnosis'
  | 'revision'
  | 'practice'
  | 'transfer'
  | 'independent'
  | 'synthesis'
  | 'reflection'

export type LearningTask = {
  id: string
  objective: string
  createdAt: number
}

export type LearningSkillStep = {
  id: string
  title: string
  shortTitle: string
  substateId: LearningSubstateId
  substateLabel: string
  tutorInstruction: string
  nextAction: string
  canLoop?: boolean
  requiresLearnerReply?: boolean
  loopInstruction?: string
}

export type LearningSkillDefinition = {
  name: string
  description: string
  bestFor: string
  boundState: 'guided_learning'
  steps: readonly LearningSkillStep[]
}

export type LearningEventType =
  | 'vnext_learning_task_created'
  | 'vnext_learning_task_started'
  | 'vnext_learning_task_phase_entered'
  | 'vnext_learning_skill_step_entered'
  | 'vnext_learning_skill_looped'
  | 'vnext_learning_task_learner_replied'
  | 'vnext_learning_support_requested'
  | 'vnext_learning_skill_selected'
  | 'vnext_learning_task_paused'
  | 'vnext_learning_task_resumed'
  | 'vnext_learning_task_completed'

export type LearningEvent = {
  id: string
  sequence: number
  taskId: string
  type: LearningEventType
  at: number
  detail: string
  phase?: LegacyLearningPhase
  skillId?: LearningSkillId
  stepId?: string
}

export type LearningTaskProjection = {
  task: LearningTask
  status: LearningTaskStatus
  skillId: LearningSkillId
  stepId: string
  stepIndex: number
  eventCount: number
  learnerReplyCount: number
  learnerRepliesInStep: number
  supportCount: number
  loopCount: number
  totalLoopCount: number
}

export type LearningTaskTutorContext = {
  taskId: string
  objective: string
  skillId: LearningSkillId
  skillName: string
  substateId: LearningSubstateId
  substateLabel: string
  stepId: string
  stepTitle: string
  stepIndex: number
  stepCount: number
  stepInstruction: string
  nextAction: string
  loopCount: number
  loopInstruction: string
}

export const LEARNING_SKILLS: Record<LearningSkillId, LearningSkillDefinition> = {
  guided_explanation: {
    name: '清晰讲解',
    description: '先建立模型，再用例子和迁移检查把解释变成理解。',
    bestFor: '陌生概念、需要先获得可靠知识起点',
    boundState: 'guided_learning',
    steps: [
      {
        id: 'anchor_model', title: '建立最小模型', shortTitle: '模型', substateId: 'guidance', substateLabel: '引导态', nextAction: '看最小例子', canLoop: true,
        tutorInstruction: '先直接解释目标最核心的对象、关系和作用，只讲一个清晰层次；不能用空泛追问代替知识起点。结尾邀请学生指出其中一个关键关系。',
        loopInstruction: '换一种表征重讲同一个核心关系：可用类比、反例或更小的组成，不增加新的知识层次。',
      },
      {
        id: 'inspect_example', title: '检查最小例子', shortTitle: '例子', substateId: 'demonstration', substateLabel: '示范态', nextAction: '让我解释', canLoop: true,
        tutorInstruction: '给一个足够小、能逐项映射到核心模型的例子，明确例子中每个部分对应什么，然后只让学生判断一个关键步骤。',
        loopInstruction: '保留同一知识关系，换一个更具体或更小的例子，并把待判断范围缩小。',
      },
      {
        id: 'learner_explain', title: '学生解释关键关系', shortTitle: '复述', substateId: 'teachback', substateLabel: '复述态', nextAction: '换情境检查', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '请学生用自己的话解释一个指定关系。反馈时先指出说清的一点，再指出一个仍模糊的连接，并邀请立即修订；复述不作为掌握证据。',
        loopInstruction: '把复述目标缩成一句因果关系或一个输入到输出的变化，再让学生修订同一处。',
      },
      {
        id: 'transfer_check', title: '换情境检查', shortTitle: '迁移', substateId: 'transfer', substateLabel: '迁移态', nextAction: '完成本轮', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '给一个没有照搬原例子的轻量新情境，让学生独立做一个判断并说明理由。只提供反馈，不评分、不宣称掌握。',
        loopInstruction: '换一个难度相近但表面不同的情境继续检查；如需提示，明确它是支架而非独立完成。',
      },
    ],
  },
  socratic_dialogue: {
    name: '苏格拉底追问',
    description: '从可回答的起点出发，用假设、理由和边界逐步推进推理。',
    bestFor: '因果推理、证明、不变量、已有部分直觉',
    boundState: 'guided_learning',
    steps: [
      {
        id: 'ground_context', title: '提供可回答起点', shortTitle: '起点', substateId: 'guidance', substateLabel: '引导态', nextAction: '提出判断', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '给出理解当前问题所必需的最小事实和一个具体情境，然后问一个无需猜测术语即可回答的问题。不能让完全陌生的学生从空白猜关键关系。',
        loopInstruction: '补一个更具体的事实、二选一或可观察现象，继续停留在同一问题附近。',
      },
      {
        id: 'hypothesis', title: '提出一个判断', shortTitle: '假设', substateId: 'inquiry', substateLabel: '探究态', nextAction: '追问理由', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '邀请学生对具体情境提出一个可检验判断；一次只问一个问题，不提前给完整答案。',
        loopInstruction: '缩小判断范围，给出两个候选方向或固定一个变量，让学生只选择并解释一项。',
      },
      {
        id: 'probe_reason', title: '追问判断理由', shortTitle: '理由', substateId: 'inquiry', substateLabel: '探究态', nextAction: '检验边界', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '围绕学生刚才的判断只追问一个“为什么成立”的关键连接；先回应已有推理，不要机械重复问题。',
        loopInstruction: '把理由拆成前提到结论之间缺失的一步，提供句子开头或局部事实后再问。',
      },
      {
        id: 'test_boundary', title: '用边界检验假设', shortTitle: '边界', substateId: 'transfer', substateLabel: '检验态', nextAction: '收束推理', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '给一个反例、极端值或改变单一条件的情境，请学生判断原假设是否仍成立以及为什么。',
        loopInstruction: '降低反例复杂度，只改变一个条件，并明确其余条件保持不变。',
      },
      {
        id: 'synthesize_reasoning', title: '学生收束推理', shortTitle: '收束', substateId: 'synthesis', substateLabel: '收束态', nextAction: '完成本轮', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '请学生用“条件—机制—结论”收束刚才的推理；反馈只修正一个关键连接，不宣布掌握。',
        loopInstruction: '给出三段式句架，让学生只补全缺失的一段后再完整说一遍。',
      },
    ],
  },
  feynman_dialogue: {
    name: '费曼复述',
    description: '先有知识起点，再通过复述、诊断和修订暴露跳步。',
    bestFor: '查漏补缺、组织概念关系、已有接触后的理解检查',
    boundState: 'guided_learning',
    steps: [
      {
        id: 'knowledge_anchor', title: '补齐必要起点', shortTitle: '起点', substateId: 'guidance', substateLabel: '引导态', nextAction: '开始复述', canLoop: true,
        tutorInstruction: '用很短的说明确认学生已经拥有复述所需的对象和关系；若尚未接触主题，先给最小讲解，不能直接要求复述未知内容。',
        loopInstruction: '换成一个更直观的最小模型或例子，只补足复述必需的知识。',
      },
      {
        id: 'first_teachback', title: '第一次用自己的话讲', shortTitle: '初讲', substateId: 'teachback', substateLabel: '复述态', nextAction: '定位跳步', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '指定听众和范围，请学生不用术语堆砌地讲清一个机制。收到回答后先指出讲清的一点，不把流畅复述当作掌握。',
        loopInstruction: '把复述目标缩小到一个关系，并给出“它先……所以……”的句架。',
      },
      {
        id: 'diagnose_gap', title: '定位一个关键跳步', shortTitle: '诊断', substateId: 'diagnosis', substateLabel: '诊断态', nextAction: '修订复述', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '只指出复述中最关键的一个模糊处、遗漏前提或术语替代解释，并问一个能暴露该连接的问题。',
        loopInstruction: '把跳步拆成更小的前提问题；如仍不会，直接补足该前提，再保留修订机会。',
      },
      {
        id: 'revised_teachback', title: '带着修正再讲一遍', shortTitle: '修订', substateId: 'revision', substateLabel: '修订态', nextAction: '补例子与边界', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '请学生只修订刚才的关键跳步，再把它放回完整解释。对比前后变化，但不做掌握判断。',
        loopInstruction: '继续围绕同一跳步缩小复述范围；必要时给半成品解释让学生改错。',
      },
      {
        id: 'example_or_boundary', title: '补一个例子或边界', shortTitle: '边界', substateId: 'transfer', substateLabel: '迁移态', nextAction: '完成本轮', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '请学生给一个能体现机制的例子，或指出概念不适用的边界；反馈例子是否真的映射到所讲关系。',
        loopInstruction: '给出一个候选例子，让学生只判断它是否成立并修正不合适之处。',
      },
    ],
  },
  worked_example_fading: {
    name: '示例渐隐',
    description: '从完整示范逐步撤掉答案，直到独立处理一个变式。',
    bestFor: '代码、算法、配置和程序性问题求解',
    boundState: 'guided_learning',
    steps: [
      {
        id: 'worked_example', title: '观看带子目标的示范', shortTitle: '示范', substateId: 'demonstration', substateLabel: '示范态', nextAction: '补最后一步', canLoop: true,
        tutorInstruction: '给一个小而完整、按子目标标注的示例，解释每一步为什么服务于目标；不要一次塞入多个变体。',
        loopInstruction: '换一个更小的输入或补充逐行标注，仍展示完整过程。',
      },
      {
        id: 'complete_last_step', title: '补全最后一步', shortTitle: '末步', substateId: 'practice', substateLabel: '练习态', nextAction: '补中间步骤', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '保留前面过程，只撤掉最后一个可检查步骤，让学生补全并说明该步骤如何得到。',
        loopInstruction: '给最后一步的输入、输出形状或一个局部提示，仍由学生完成该步。',
      },
      {
        id: 'complete_middle_step', title: '补全中间步骤', shortTitle: '渐隐', substateId: 'practice', substateLabel: '练习态', nextAction: '独立做变式', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '撤掉一个中间步骤及其后续结果，让学生补全当前步骤；每轮只处理一个缺口。',
        loopInstruction: '恢复一个相邻步骤或给出待用规则，降低一次需要保持的信息量。',
      },
      {
        id: 'independent_problem', title: '独立完成近迁移变式', shortTitle: '变式', substateId: 'independent', substateLabel: '独立态', nextAction: '解释策略', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '给一个表面不同但使用同一策略的小变式，先不提供步骤。若学生请求提示，明确记录支架并留在本步，不能视为独立完成。',
        loopInstruction: '再给一个难度相近的变式；若上一轮用了提示，先换题再尝试无提示完成。',
      },
      {
        id: 'reflect_strategy', title: '说出策略选择依据', shortTitle: '策略', substateId: 'reflection', substateLabel: '反思态', nextAction: '完成本轮', canLoop: true, requiresLearnerReply: true,
        tutorInstruction: '请学生说明何时使用这套步骤、关键判断点和一个常见错误；只反馈策略表达，不宣布掌握。',
        loopInstruction: '给一个相邻但不适用的情境，让学生比较为什么不能照搬。',
      },
    ],
  },
}

const LEARNING_INTENT = /(?:带我(?:学|学习|弄懂|理解|练习|做|写|实现|完成)|教我(?:学会|理解|弄懂)|陪我(?:学|练)|让我练习|(?:开始|创建|建立|加入)(?:一个)?学习任务|练习并(?:检查|验证)|从头学会)/
const SUPPORT_REQUEST = /(?:不会|不知道|没懂|不明白|想不出来|给个提示|提示一下|举个例子|直接讲|跳过)/
const PROCEDURAL_GOAL = /(?:代码|编程|算法|配置|命令|调试|实现|写一个|手写|步骤|操作|SQL|指针)/i
const REASONING_GOAL = /(?:为什么|证明|推导|不变量|因果|判断)/

function eventId() {
  return `learning-event-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function taskId() {
  return `learning-task-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

export function hasExplicitLearningIntent(input: string) {
  return LEARNING_INTENT.test(input.replace(/\s+/g, ''))
}

export function isSupportRequest(input: string) {
  return SUPPORT_REQUEST.test(input.replace(/\s+/g, ''))
}

export function learningObjectiveFromInput(input: string) {
  const cleaned = input
    .replace(/^(?:请|可以|能不能|你能)?\s*带我(?=(?:写|实现|完成))/i, '')
    .replace(/^(?:请|可以|能不能|你能)?\s*(?:带我(?:学|学习|弄懂|理解|练习|做)|教我(?:学会|理解|弄懂)|陪我(?:学|练)|让我练习)\s*/i, '')
    .replace(/[。！？!?]+$/g, '')
    .trim()
  return (cleaned || input.trim() || '完成当前学习目标').slice(0, 180)
}

export function recommendedLearningSkill(objective: string): LearningSkillId {
  if (PROCEDURAL_GOAL.test(objective)) return 'worked_example_fading'
  if (REASONING_GOAL.test(objective)) return 'socratic_dialogue'
  return 'guided_explanation'
}

export function createLearningTask(objective: string, now = Date.now(), existingEvents: LearningEvent[] = [], preferredSkillId?: LearningSkillId) {
  const task: LearningTask = { id: taskId(), objective: learningObjectiveFromInput(objective), createdAt: now }
  const skillId = preferredSkillId || recommendedLearningSkill(task.objective)
  const firstStep = LEARNING_SKILLS[skillId].steps[0]
  const events = appendLearningEvents(existingEvents, task.id, [
    { type: 'vnext_learning_task_created', detail: `建立任务：${task.objective}`, skillId },
    { type: 'vnext_learning_task_started', detail: '开始在当前对话中学习' },
    { type: 'vnext_learning_skill_selected', detail: `使用${LEARNING_SKILLS[skillId].name}`, skillId },
    { type: 'vnext_learning_skill_step_entered', detail: `进入${firstStep.substateLabel}：${firstStep.title}`, skillId, stepId: firstStep.id },
  ], now)
  return { task, events }
}

export function appendLearningEvents(
  existing: LearningEvent[],
  targetTaskId: string,
  additions: Array<Omit<LearningEvent, 'id' | 'sequence' | 'taskId' | 'at'>>,
  now = Date.now(),
) {
  let sequence = existing.reduce((highest, item) => Math.max(highest, item.sequence || 0), 0)
  return [
    ...existing,
    ...additions.map((addition, index) => ({
      ...addition,
      id: eventId(),
      sequence: ++sequence,
      taskId: targetTaskId,
      at: now + index,
    })),
  ]
}

function legacyStepIndex(phase: LegacyLearningPhase, stepCount: number) {
  if (phase === 'learn') return 0
  if (phase === 'practice') return Math.min(1, stepCount - 1)
  if (phase === 'verify') return Math.max(0, stepCount - 2)
  return Math.max(0, stepCount - 1)
}

export function projectLearningTask(task: LearningTask, events: LearningEvent[]): LearningTaskProjection {
  const taskEvents = events.filter(event => event.taskId === task.id).sort((left, right) => left.sequence - right.sequence)
  let status: LearningTaskStatus = 'active'
  let skillId: LearningSkillId = recommendedLearningSkill(task.objective)
  let stepId = LEARNING_SKILLS[skillId].steps[0].id
  let legacyPhase: LegacyLearningPhase = 'learn'
  let hasSkillStep = false
  let learnerReplyCount = 0
  let learnerRepliesInStep = 0
  let supportCount = 0
  let loopCount = 0
  let totalLoopCount = 0

  taskEvents.forEach(event => {
    if (event.type === 'vnext_learning_task_paused') status = 'paused'
    if (event.type === 'vnext_learning_task_resumed' || event.type === 'vnext_learning_task_started') status = 'active'
    if (event.type === 'vnext_learning_task_completed') status = 'completed'
    if (event.type === 'vnext_learning_task_phase_entered' && event.phase) legacyPhase = event.phase
    if (event.type === 'vnext_learning_skill_selected' && event.skillId) {
      skillId = event.skillId
      stepId = LEARNING_SKILLS[skillId].steps[0].id
      loopCount = 0
      learnerRepliesInStep = 0
    }
    if (event.type === 'vnext_learning_skill_step_entered' && event.stepId) {
      const eventSkillId = event.skillId || skillId
      if (isLearningSkillId(eventSkillId) && LEARNING_SKILLS[eventSkillId].steps.some(step => step.id === event.stepId)) {
        skillId = eventSkillId
        stepId = event.stepId
        hasSkillStep = true
        loopCount = 0
        learnerRepliesInStep = 0
      }
    }
    if (event.type === 'vnext_learning_skill_looped') {
      loopCount += 1
      totalLoopCount += 1
      learnerRepliesInStep = 0
    }
    if (event.type === 'vnext_learning_task_learner_replied') {
      learnerReplyCount += 1
      learnerRepliesInStep += 1
    }
    if (event.type === 'vnext_learning_support_requested') supportCount += 1
  })

  const steps = LEARNING_SKILLS[skillId].steps
  if (!hasSkillStep) stepId = steps[legacyStepIndex(legacyPhase, steps.length)].id
  const stepIndex = Math.max(0, steps.findIndex(step => step.id === stepId))
  return { task, status, skillId, stepId, stepIndex, eventCount: taskEvents.length, learnerReplyCount, learnerRepliesInStep, supportCount, loopCount, totalLoopCount }
}

export function latestLearningTaskProjection(tasks: LearningTask[], events: LearningEvent[]) {
  const task = [...tasks].sort((left, right) => right.createdAt - left.createdAt)[0]
  return task ? projectLearningTask(task, events) : undefined
}

export function activeLearningTaskProjection(tasks: LearningTask[], events: LearningEvent[]) {
  return [...tasks]
    .sort((left, right) => right.createdAt - left.createdAt)
    .map(task => projectLearningTask(task, events))
    .find(item => item.status === 'active')
}

export function currentLearningSkillStep(projection: LearningTaskProjection) {
  return LEARNING_SKILLS[projection.skillId].steps[projection.stepIndex]
}

export function nextLearningSkillStep(projection: LearningTaskProjection) {
  return LEARNING_SKILLS[projection.skillId].steps[projection.stepIndex + 1]
}

export function canAdvanceLearningSkillStep(projection: LearningTaskProjection) {
  const step = currentLearningSkillStep(projection)
  return !step.requiresLearnerReply || projection.learnerRepliesInStep > 0
}

export function advanceLearningSkillStep(events: LearningEvent[], projection: LearningTaskProjection, now = Date.now()) {
  const next = nextLearningSkillStep(projection)
  if (!next) return events
  return appendLearningEvents(events, projection.task.id, [{
    type: 'vnext_learning_skill_step_entered',
    detail: `进入${next.substateLabel}：${next.title}；不表示上一动作通过`,
    skillId: projection.skillId,
    stepId: next.id,
  }], now)
}

export function loopLearningSkillStep(events: LearningEvent[], projection: LearningTaskProjection, reason = '重复当前教学动作', now = Date.now()) {
  const step = currentLearningSkillStep(projection)
  return appendLearningEvents(events, projection.task.id, [{
    type: 'vnext_learning_skill_looped', detail: `${reason}：${step.title}`, skillId: projection.skillId, stepId: step.id,
  }], now)
}

export function switchLearningSkill(events: LearningEvent[], projection: LearningTaskProjection, skillId: LearningSkillId, now = Date.now()) {
  const firstStep = LEARNING_SKILLS[skillId].steps[0]
  return appendLearningEvents(events, projection.task.id, [
    { type: 'vnext_learning_skill_selected', detail: `切换为${LEARNING_SKILLS[skillId].name}`, skillId },
    { type: 'vnext_learning_skill_step_entered', detail: `进入${firstStep.substateLabel}：从${firstStep.title}开始`, skillId, stepId: firstStep.id },
  ], now)
}

export function learningTaskTutorContext(projection: LearningTaskProjection): LearningTaskTutorContext {
  const skill = LEARNING_SKILLS[projection.skillId]
  const step = skill.steps[projection.stepIndex]
  return {
    taskId: projection.task.id,
    objective: projection.task.objective,
    skillId: projection.skillId,
    skillName: skill.name,
    substateId: step.substateId,
    substateLabel: step.substateLabel,
    stepId: step.id,
    stepTitle: step.title,
    stepIndex: projection.stepIndex,
    stepCount: skill.steps.length,
    stepInstruction: step.tutorInstruction,
    nextAction: step.nextAction,
    loopCount: projection.loopCount,
    loopInstruction: step.loopInstruction || '继续当前动作并缩小问题范围。',
  }
}

export function isLearningSkillId(value: unknown): value is LearningSkillId {
  return typeof value === 'string' && value in LEARNING_SKILLS
}

export function sanitizeLearningTaskTutorContext(value: unknown): LearningTaskTutorContext | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  if (
    typeof item.taskId !== 'string'
    || typeof item.objective !== 'string'
    || !isLearningSkillId(item.skillId)
    || typeof item.skillName !== 'string'
    || typeof item.substateId !== 'string'
    || typeof item.substateLabel !== 'string'
    || typeof item.stepId !== 'string'
    || typeof item.stepTitle !== 'string'
    || typeof item.stepIndex !== 'number'
    || typeof item.stepCount !== 'number'
    || typeof item.stepInstruction !== 'string'
    || typeof item.nextAction !== 'string'
    || typeof item.loopCount !== 'number'
    || typeof item.loopInstruction !== 'string'
  ) return undefined
  const maxStepIndex = Math.max(0, LEARNING_SKILLS[item.skillId].steps.length - 1)
  return {
    taskId: item.taskId.slice(0, 120),
    objective: item.objective.slice(0, 500),
    skillId: item.skillId,
    skillName: item.skillName.slice(0, 80),
    substateId: LEARNING_SKILLS[item.skillId].steps.some(step => step.substateId === item.substateId)
      ? item.substateId as LearningSubstateId
      : LEARNING_SKILLS[item.skillId].steps[0].substateId,
    substateLabel: item.substateLabel.slice(0, 40),
    stepId: item.stepId.slice(0, 80),
    stepTitle: item.stepTitle.slice(0, 100),
    stepIndex: Math.max(0, Math.min(Math.floor(item.stepIndex), maxStepIndex)),
    stepCount: LEARNING_SKILLS[item.skillId].steps.length,
    stepInstruction: item.stepInstruction.slice(0, 1400),
    nextAction: item.nextAction.slice(0, 100),
    loopCount: Math.max(0, Math.min(Math.floor(item.loopCount), 99)),
    loopInstruction: item.loopInstruction.slice(0, 1000),
  }
}
