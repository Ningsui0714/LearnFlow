import type { ProjectPluginSurface } from './plugin-runtime.ts'

export const PLUGIN_CHAT_PROTOCOL = 'learnflow.plugin-chat-artifact.v1' as const

export type PluginChatContext = {
  pluginId: string
  title: string
  surfaceId: string
  instanceId: number
  snapshotId?: number
  snapshotVersion?: number
  snapshotRootHash?: string
  productSkillId?: string
}

export type RoleCapabilityNode = {
  id: string
  type: string
  label: string
  summary?: string
  lifecycle?: string
  evidenceCount: number
}

export type RoleCapabilityEdge = {
  id: string
  type: string
  source: string
  target: string
  label?: string
}

export type RoleProcessScenario = {
  id: string
  label: string
  eventIds: string[]
}

export type RoleProcessEvent = {
  id: string
  label: string
  order: number
  taskId?: string
  workObjectId?: string
  lifecycle?: string
}

export type RoleCapabilityChatArtifact = {
  protocol: typeof PLUGIN_CHAT_PROTOCOL
  pluginId: 'role_capability_graph'
  title: string
  snapshot?: { id?: number; version?: number; rootHash?: string }
  nodes: RoleCapabilityNode[]
  edges: RoleCapabilityEdge[]
  scenarios: RoleProcessScenario[]
  events: RoleProcessEvent[]
  workObjects: RoleCapabilityNode[]
  bridges: Array<{ id: string; label: string; semanticObjectId?: string; processEventId?: string }>
  citations: Array<{ title: string; locator?: string }>
  explanation?: string
  validation?: { valid?: boolean; errors: string[]; warnings: string[] }
}

function record(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function list(value: unknown, limit = 200): any[] {
  return Array.isArray(value) ? value.slice(0, limit) : []
}

function text(value: unknown, fallback = '', limit = 500) {
  const normalized = String(value ?? fallback).replace(/\s+/g, ' ').trim()
  return normalized.slice(0, limit)
}

function node(value: unknown): RoleCapabilityNode | undefined {
  const item = record(value)
  const id = text(item.id, '', 180)
  if (!id) return undefined
  return {
    id,
    type: text(item.type || item.object_type, 'object', 80),
    label: text(item.label || item.title || id, id, 240),
    ...(text(item.summary || item.statement, '', 700) ? { summary: text(item.summary || item.statement, '', 700) } : {}),
    ...(text(item.lifecycle, '', 60) ? { lifecycle: text(item.lifecycle, '', 60) } : {}),
    evidenceCount: list(item.evidence_refs, 50).length,
  }
}

function snapshotProjection(value: unknown) {
  const source = record(value)
  const snapshot = record(source.snapshot || source.snapshot_ref)
  return {
    id: Number(snapshot.id || snapshot.snapshot_id) || undefined,
    version: Number(snapshot.version) || undefined,
    rootHash: text(snapshot.root_hash || snapshot.snapshot_root_hash, '', 128) || undefined,
  }
}

export function roleCapabilityArtifactFromSnapshot(value: unknown, title = '岗位能力图谱'): RoleCapabilityChatArtifact | undefined {
  const source = record(value)
  const snapshot = record(source.snapshot || source)
  const components = record(snapshot.components)
  const graph = record(components['semantic-graph'] || source.graph || source['semantic-graph'])
  const forest = record(components['process-forest'] || source.process_forest || source['process-forest'])
  const semanticNodes = list(graph.nodes).map(node).filter(Boolean) as RoleCapabilityNode[]
  const processNodes = list(forest.work_objects).map(node).filter(Boolean) as RoleCapabilityNode[]
  if (!semanticNodes.length && !processNodes.length && !list(forest.events).length) return undefined
  const validation = record(snapshot.validation || components['validation-report'] || source.validation)
  return {
    protocol: PLUGIN_CHAT_PROTOCOL,
    pluginId: 'role_capability_graph',
    title,
    snapshot: snapshotProjection({ snapshot }),
    nodes: semanticNodes,
    edges: list(graph.edges).flatMap((raw, index) => {
      const item = record(raw)
      const sourceId = text(item.source || item.source_id, '', 180)
      const targetId = text(item.target || item.target_id, '', 180)
      if (!sourceId || !targetId) return []
      return [{
        id: text(item.id, `edge:${index}`, 180), type: text(item.type || item.relation, 'related_to', 80),
        source: sourceId, target: targetId, label: text(item.label, '', 160) || undefined,
      }]
    }),
    scenarios: list(forest.scenarios).flatMap(raw => {
      const item = record(raw)
      const id = text(item.id, '', 180)
      return id ? [{ id, label: text(item.label || id, id, 240), eventIds: list(item.event_ids, 80).map(value => text(value, '', 180)).filter(Boolean) }] : []
    }),
    events: list(forest.events).flatMap(raw => {
      const item = record(raw)
      const id = text(item.id, '', 180)
      return id ? [{
        id, label: text(item.label || id, id, 240), order: Number(item.order) || 0,
        taskId: text(item.task_id, '', 180) || undefined,
        workObjectId: text(item.work_object_id, '', 180) || undefined,
        lifecycle: text(item.lifecycle, '', 60) || undefined,
      }] : []
    }).sort((left, right) => left.order - right.order),
    workObjects: processNodes,
    bridges: list(forest.bridges).flatMap(raw => {
      const item = record(raw)
      const id = text(item.id, '', 180)
      return id ? [{
        id, label: text(item.label || id, id, 240),
        semanticObjectId: text(item.semantic_object_id, '', 180) || undefined,
        processEventId: text(item.process_event_id, '', 180) || undefined,
      }] : []
    }),
    citations: [],
    validation: {
      valid: typeof validation.valid === 'boolean' ? validation.valid : undefined,
      errors: list(validation.errors, 30).map(value => text(value, '', 300)).filter(Boolean),
      warnings: list(validation.warnings, 30).map(value => text(value, '', 300)).filter(Boolean),
    },
  }
}

export function roleCapabilityArtifactFromToolObservation(value: unknown): RoleCapabilityChatArtifact | undefined {
  const observation = record(value)
  const result = record(observation.result || observation)
  const direct = roleCapabilityArtifactFromSnapshot({
    snapshot: {
      ...record(observation.snapshot_ref || result.snapshot_ref),
      components: result.components || (result.graph ? { 'semantic-graph': result.graph, 'process-forest': result.process_forest } : undefined),
      validation: result.validation,
    },
  }, text(result.title, '岗位图谱工具结果', 200))
  if (direct) {
    direct.explanation = text(result.answer || result.explanation, '', 4_000) || undefined
    direct.citations = list(result.citations, 40).map(raw => {
      const item = record(raw)
      return { title: text(item.title || item.label || item.source || '来源', '来源', 240), locator: text(item.locator || item.ref, '', 300) || undefined }
    })
    return direct
  }
  const objects = list(result.objects).map(raw => node(record(raw).object || raw)).filter(Boolean) as RoleCapabilityNode[]
  if (!objects.length && !text(result.answer || result.explanation)) return undefined
  return {
    protocol: PLUGIN_CHAT_PROTOCOL, pluginId: 'role_capability_graph', title: '岗位图谱解释',
    snapshot: snapshotProjection(observation), nodes: objects,
    edges: list(result.relations).flatMap((raw, index) => {
      const item = record(raw)
      const source = text(item.source || item.source_id, '', 180)
      const target = text(item.target || item.target_id, '', 180)
      return source && target ? [{ id: text(item.id, `relation:${index}`, 180), type: text(item.type || item.relation, 'related_to', 80), source, target }] : []
    }),
    scenarios: [], events: [], workObjects: [], bridges: [],
    citations: list(result.citations, 40).map(raw => ({ title: text(record(raw).title || record(raw).source || '来源', '来源', 240), locator: text(record(raw).locator || record(raw).ref, '', 300) || undefined })),
    explanation: text(result.answer || result.explanation, '', 4_000) || undefined,
    validation: { errors: [], warnings: [] },
  }
}

export function pluginChatContext(surface: ProjectPluginSurface): PluginChatContext {
  const snapshot = record(surface.data?.snapshot)
  return {
    pluginId: surface.plugin_id,
    title: surface.title,
    surfaceId: surface.surface_id,
    instanceId: surface.instance_id,
    snapshotId: Number(snapshot.id) || undefined,
    snapshotVersion: Number(snapshot.version) || undefined,
    snapshotRootHash: text(snapshot.root_hash, '', 128) || undefined,
    productSkillId: surface.plugin_id === 'role_capability_graph' ? 'role_capability_graphing' : undefined,
  }
}

export function pluginChatGlyph(pluginId: string) {
  return pluginId === 'role_capability_graph' ? '岗' : '插'
}

export function roleCapabilityChatState(surface?: ProjectPluginSurface, busyWorkflow?: string) {
  if (busyWorkflow === 'generate') return { id: 'generating', label: '正在生成候选岗位包' }
  if (busyWorkflow === 'iterate') return { id: 'iterating', label: '正在验证后继快照' }
  if (busyWorkflow === 'explain') return { id: 'explaining', label: '正在固定快照并解释' }
  const snapshot = record(surface?.data?.snapshot)
  if (!surface) return { id: 'unavailable', label: '插件未启用' }
  if (!snapshot.id) return { id: 'needs_snapshot', label: '等待生成首个快照' }
  return { id: 'ready', label: `快照 v${Number(snapshot.version) || 1} 可对话` }
}
