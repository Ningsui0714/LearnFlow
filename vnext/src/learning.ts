export type LearningSkillId =
  | 'guided_explanation'
  | 'socratic_dialogue'
  | 'feynman_dialogue'
  | 'worked_example_fading'

export type LearningPhase = 'learn' | 'practice' | 'verify' | 'consolidate'
export type LearningTaskStatus = 'active' | 'paused' | 'completed'

export type LearningTask = {
  id: string
  objective: string
  createdAt: number
}

export type LearningEventType =
  | 'vnext_learning_task_created'
  | 'vnext_learning_task_started'
  | 'vnext_learning_task_phase_entered'
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
  phase?: LearningPhase
  skillId?: LearningSkillId
}

export type LearningTaskProjection = {
  task: LearningTask
  status: LearningTaskStatus
  phase: LearningPhase
  skillId: LearningSkillId
  phaseIndex: number
  eventCount: number
  learnerReplyCount: number
  supportCount: number
}

export type LearningTaskTutorContext = {
  taskId: string
  objective: string
  phase: LearningPhase
  phaseTitle: string
  phaseIndex: number
  phaseCount: number
  phaseInstruction: string
  skillId: LearningSkillId
  skillName: string
  skillInstruction: string
}

export const LEARNING_PHASES: ReadonlyArray<{
  id: LearningPhase
  title: string
  shortTitle: string
  purpose: string
}> = [
  {
    id: 'learn',
    title: '建立理解',
    shortTitle: '理解',
    purpose: '先给可用的知识起点，连接目标、机制与一个最小例子，再邀请学生做一个小动作。',
  },
  {
    id: 'practice',
    title: '主动练习',
    shortTitle: '练习',
    purpose: '让学生生成答案、步骤、代码或解释；每轮只处理一个可检查动作，并提供针对性反馈。',
  },
  {
    id: 'verify',
    title: '独立检查',
    shortTitle: '检查',
    purpose: '用一个未直接照搬示例的问题做无提示提取；需要提示时继续帮助，但不能算独立完成。',
  },
  {
    id: 'consolidate',
    title: '收束与复习',
    shortTitle: '收束',
    purpose: '整理关键关系、仍不确定之处和下一次复习建议；任务完成只是流程里程碑，不是掌握结论。',
  },
]

export const LEARNING_SKILLS: Record<LearningSkillId, {
  name: string
  description: string
  instruction: string
}> = {
  guided_explanation: {
    name: '清晰讲解',
    description: '核心模型 → 最小例子 → 小检查',
    instruction: '先直接讲清一个层次，再给最小例子，最后邀请学生做一个很小的解释或判断；不要用空泛追问代替起点。',
  },
  socratic_dialogue: {
    name: '苏格拉底追问',
    description: '给起点后，一次追一个关键判断',
    instruction: '先给足以作答的最小支架和具体情境，再一次只问一个能推进推理的问题；学生说不会时补支架并停留在当前动作。',
  },
  feynman_dialogue: {
    name: '费曼复述',
    description: '自己讲一遍，再定位一个模糊处',
    instruction: '在已有起点后请学生用自己的话复述；先指出讲清的一点，再只定位一个关键跳步，并邀请修订。',
  },
  worked_example_fading: {
    name: '示例渐隐',
    description: '完整示范 → 补最后一步 → 独立完成',
    instruction: '先给按子目标标注的小型完整示例，再从最后一步开始撤去答案；每轮只要求补一个可检查步骤。',
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

export function createLearningTask(objective: string, now = Date.now(), existingEvents: LearningEvent[] = []) {
  const task: LearningTask = {
    id: taskId(),
    objective: learningObjectiveFromInput(objective),
    createdAt: now,
  }
  const skillId = recommendedLearningSkill(task.objective)
  const events = appendLearningEvents(existingEvents, task.id, [
    { type: 'vnext_learning_task_created', detail: `建立任务：${task.objective}`, skillId },
    { type: 'vnext_learning_task_started', detail: '开始在当前对话中学习' },
    { type: 'vnext_learning_task_phase_entered', detail: '进入建立理解', phase: 'learn' },
    { type: 'vnext_learning_skill_selected', detail: `使用${LEARNING_SKILLS[skillId].name}`, skillId },
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

export function projectLearningTask(task: LearningTask, events: LearningEvent[]): LearningTaskProjection {
  const taskEvents = events
    .filter(event => event.taskId === task.id)
    .sort((left, right) => left.sequence - right.sequence)
  let status: LearningTaskStatus = 'active'
  let phase: LearningPhase = 'learn'
  let skillId: LearningSkillId = recommendedLearningSkill(task.objective)
  let learnerReplyCount = 0
  let supportCount = 0

  taskEvents.forEach(event => {
    if (event.type === 'vnext_learning_task_paused') status = 'paused'
    if (event.type === 'vnext_learning_task_resumed' || event.type === 'vnext_learning_task_started') status = 'active'
    if (event.type === 'vnext_learning_task_completed') status = 'completed'
    if (event.type === 'vnext_learning_task_phase_entered' && event.phase) phase = event.phase
    if (event.type === 'vnext_learning_skill_selected' && event.skillId) skillId = event.skillId
    if (event.type === 'vnext_learning_task_learner_replied') learnerReplyCount += 1
    if (event.type === 'vnext_learning_support_requested') supportCount += 1
  })

  return {
    task,
    status,
    phase,
    skillId,
    phaseIndex: Math.max(0, LEARNING_PHASES.findIndex(item => item.id === phase)),
    eventCount: taskEvents.length,
    learnerReplyCount,
    supportCount,
  }
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

export function nextLearningPhase(phase: LearningPhase) {
  const index = LEARNING_PHASES.findIndex(item => item.id === phase)
  return index >= 0 && index < LEARNING_PHASES.length - 1 ? LEARNING_PHASES[index + 1].id : undefined
}

export function advanceLearningPhase(events: LearningEvent[], projection: LearningTaskProjection, now = Date.now()) {
  const next = nextLearningPhase(projection.phase)
  if (!next) return events
  const nextSpec = LEARNING_PHASES.find(item => item.id === next)!
  return appendLearningEvents(events, projection.task.id, [
    { type: 'vnext_learning_task_phase_entered', detail: `学生切换到${nextSpec.title}；不表示上一环节通过`, phase: next },
  ], now)
}

export function learningTaskTutorContext(projection: LearningTaskProjection): LearningTaskTutorContext {
  const phase = LEARNING_PHASES[projection.phaseIndex]
  const skill = LEARNING_SKILLS[projection.skillId]
  return {
    taskId: projection.task.id,
    objective: projection.task.objective,
    phase: projection.phase,
    phaseTitle: phase.title,
    phaseIndex: projection.phaseIndex,
    phaseCount: LEARNING_PHASES.length,
    phaseInstruction: phase.purpose,
    skillId: projection.skillId,
    skillName: skill.name,
    skillInstruction: skill.instruction,
  }
}

export function isLearningSkillId(value: unknown): value is LearningSkillId {
  return typeof value === 'string' && value in LEARNING_SKILLS
}

export function isLearningPhase(value: unknown): value is LearningPhase {
  return LEARNING_PHASES.some(item => item.id === value)
}

export function sanitizeLearningTaskTutorContext(value: unknown): LearningTaskTutorContext | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  if (
    typeof item.taskId !== 'string'
    || typeof item.objective !== 'string'
    || !isLearningPhase(item.phase)
    || typeof item.phaseTitle !== 'string'
    || typeof item.phaseIndex !== 'number'
    || typeof item.phaseCount !== 'number'
    || typeof item.phaseInstruction !== 'string'
    || !isLearningSkillId(item.skillId)
    || typeof item.skillName !== 'string'
    || typeof item.skillInstruction !== 'string'
  ) return undefined
  return {
    taskId: item.taskId.slice(0, 120),
    objective: item.objective.slice(0, 500),
    phase: item.phase,
    phaseTitle: item.phaseTitle.slice(0, 80),
    phaseIndex: Math.max(0, Math.min(Math.floor(item.phaseIndex), LEARNING_PHASES.length - 1)),
    phaseCount: LEARNING_PHASES.length,
    phaseInstruction: item.phaseInstruction.slice(0, 800),
    skillId: item.skillId,
    skillName: item.skillName.slice(0, 80),
    skillInstruction: item.skillInstruction.slice(0, 1000),
  }
}
