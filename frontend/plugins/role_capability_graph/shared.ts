export const ROLE_CAPABILITY_PLUGIN = {
  id: 'role_capability_graph',
  name: '岗位图谱',
  version: '1.4.0',
  description: '在 Tutor 对话中交互阅读岗位快照，并围绕固定节点研究证据、关系与风险以支持解释。',
  icon: '岗',
} as const

export const ROLE_OBJECT_SCHEMA_VERSION = 'role-capability.object.v1' as const

export const ROLE_OBJECT_TYPES = [
  'role_object',
  'role_relation',
  'role_evidence',
  'role_audit',
  'role_snapshot',
  'role_node_risk',
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
  nodeRisk: 'role_node_risk_research',
} as const
