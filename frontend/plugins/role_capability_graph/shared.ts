export const ROLE_CAPABILITY_PLUGIN = {
  id: 'role_capability_graph',
  name: '岗位图谱',
  version: '1.1.0',
  description: '在 Tutor 对话中一次读取岗位概览，并继续探索能力雷达、关系图、事理森林、证据与版本。',
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
