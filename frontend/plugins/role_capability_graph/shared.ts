export const ROLE_CAPABILITY_PLUGIN = {
  id: 'role_capability_graph',
  name: '岗位图谱',
  version: '1.2.0',
  description: '在 Tutor 对话中交互阅读岗位快照，切换全景、能力雷达与卡片，并继续探索关系、事理、证据与版本。',
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
  overview: 'role_overview',
  cards: 'role_cards',
  radar: 'capability_radar',
  graph: 'role_graph',
  process: 'process_forest',
  evidence: 'evidence_panel',
  audit: 'audit_panel',
  catalog: 'role_package_catalog',
  comparison: 'role_package_comparison',
} as const
