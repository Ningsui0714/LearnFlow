export const ROLE_CAPABILITY_PLUGIN = {
  id: 'role_capability_graph',
  name: '岗位图谱',
  version: '1.0.0',
  description: '在 Tutor 对话中读取有版本和证据边界的岗位语义图、事理森林与岗位卡片。',
  icon: '岗',
} as const

export const ROLE_OBJECT_SCHEMA_VERSION = 'role-capability.object.v1' as const

export const ROLE_OBJECT_TYPES = [
  'role_object',
  'role_relation',
  'role_evidence',
  'role_audit',
  'role_snapshot',
] as const

export const ROLE_RENDERERS = {
  cards: 'role_cards',
  graph: 'role_graph',
  process: 'process_forest',
  evidence: 'evidence_panel',
  audit: 'audit_panel',
} as const
