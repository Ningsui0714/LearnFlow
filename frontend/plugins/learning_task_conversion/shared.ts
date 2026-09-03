export const LEARNING_TASK_CONVERSION_PLUGIN = {
  id: 'learning_task_conversion',
  name: '学习型任务转化',
  version: '1.2.0',
  description: '先用可检查的准备单锁定真实工作任务，再交给固定讯飞工作流生成候选，并在用户明确确认后创建正式学习任务。',
  icon: '转',
} as const

export const LEARNING_TASK_OBJECT_SCHEMA_VERSION = 'role-learning-task-candidate.v1' as const
export const LEARNING_TASK_CONFIRMATION_SCHEMA_VERSION = 'learning-task-candidate-confirmation-result.v1' as const

export const LEARNING_TASK_OBJECT_TYPES = [
  'learning_task_intake',
  'learning_task_candidate',
  'learning_task_evidence',
  'learning_task_audit',
  'learning_task_handoff',
  'learning_task_confirmation',
] as const

export const LEARNING_TASK_RENDERERS = {
  intake: 'learning_task_intake',
  candidate: 'learning_task_candidate',
  evidence: 'learning_task_evidence',
  audit: 'learning_task_audit',
  handoff: 'learning_task_handoff',
  confirmation: 'learning_task_confirmation',
} as const
