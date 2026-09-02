export const LEARNING_TASK_CONVERSION_PLUGIN = {
  id: 'learning_task_conversion',
  name: '学习型任务转化',
  version: '1.0.0',
  description: '把真实工作任务交给固定讯飞工作流，生成可审查、未提交的学习任务候选。',
  icon: '转',
} as const

export const LEARNING_TASK_OBJECT_SCHEMA_VERSION = 'role-learning-task-candidate.v1' as const

export const LEARNING_TASK_OBJECT_TYPES = [
  'learning_task_candidate',
  'learning_task_evidence',
  'learning_task_audit',
  'learning_task_handoff',
] as const

export const LEARNING_TASK_RENDERERS = {
  candidate: 'learning_task_candidate',
  evidence: 'learning_task_evidence',
  audit: 'learning_task_audit',
  handoff: 'learning_task_handoff',
} as const
