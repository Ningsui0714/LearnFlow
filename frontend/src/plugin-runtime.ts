import { runtimeFetch } from './runtime-client.ts'

export const PLUGIN_SURFACE_PROTOCOL = 'learnflow.plugin-surface.v1' as const
export const PLUGIN_SURFACES_PROTOCOL = 'learnflow.plugin-surfaces.v1' as const

export const PLUGIN_SURFACE_NODE_TYPES = [
  'section', 'text', 'metric', 'list', 'table', 'graph', 'form', 'input',
  'citation', 'status', 'action',
] as const

export type PluginSurfaceNodeType = typeof PLUGIN_SURFACE_NODE_TYPES[number]

export type PluginSurfaceNode = {
  type: PluginSurfaceNodeType
  id?: string
  label?: string
  text?: string
  value?: unknown
  items?: unknown[]
  columns?: unknown[]
  rows?: unknown[]
  children?: PluginSurfaceNode[]
  fields?: PluginSurfaceNode[]
  workflow_id?: string
  input?: Record<string, unknown>
  // Compatibility fields used by the official v1 declarative surface. They
  // remain data-only and are normalized by PluginSurfaceHost.
  title?: string
  source?: string
  nodes?: unknown
  edges?: unknown
  workflow?: string
  submit_label?: string
  name?: string
  required?: boolean
  multiple?: boolean
  requires_confirmation?: boolean
}

export type PluginSurfaceDocument = {
  protocol: typeof PLUGIN_SURFACE_PROTOCOL
  id: string
  title: string
  slot: string
  body: PluginSurfaceNode[]
}

export type PluginWorkflowDescriptor = string | {
  id: string
  title?: string
  description?: string
  risk?: string
  mode?: string
}

export type ProjectPluginSurface = {
  plugin_id: string
  instance_id: number
  surface_id: string
  title: string
  slot: string
  schema: PluginSurfaceDocument
  workflows: PluginWorkflowDescriptor[]
  data?: Record<string, unknown>
}

export type ProjectPluginSurfacePage = {
  schema_version: typeof PLUGIN_SURFACES_PROTOCOL
  surfaces: ProjectPluginSurface[]
}

export type PluginWorkflowRun = {
  id?: number
  run_id?: number
  status?: string
  result?: unknown
  run?: { id?: number; status?: string; result?: unknown; [key: string]: unknown }
  [key: string]: unknown
}

export type PluginInstanceView = {
  id: number
  plugin_id: string
  project_id: number
  release_id: number
  status: 'enabled' | 'disabled'
  current_snapshot_id?: number | null
  configuration?: Record<string, unknown>
  granted_host_ports?: string[]
  release?: PluginReleaseView | null
  [key: string]: unknown
}

export type PluginConfigurationProperty = {
  type?: 'string' | 'integer' | 'number' | 'boolean' | 'array'
  title?: string
  description?: string
  default?: unknown
  minimum?: number
  maximum?: number
  enum?: unknown[]
  items?: { type?: string }
}

export type PluginConfigurationSchema = {
  type?: 'object'
  properties?: Record<string, PluginConfigurationProperty>
  required?: string[]
  additionalProperties?: boolean
}

export type PluginReleaseView = {
  id: number
  plugin_id: string
  version: string
  name: string
  description?: string
  trust_state: 'trusted_signed' | 'untrusted_development' | 'built_in' | string
  status: 'active' | 'deprecated' | 'revoked' | string
  owner?: 'tutor_agent' | 'learning_design_agent' | 'practice_agent' | string
  host_ports: string[]
  config_schema?: PluginConfigurationSchema
  workflows?: PluginWorkflowDescriptor[]
}

export type ProjectPluginReleaseCatalog = {
  protocol?: string
  releases: PluginReleaseView[]
}

export type PluginSnapshotView = {
  id: number
  instance_id: number
  version: number
  schema_version: string
  root_hash: string
  parent_snapshot_id?: number | null
  [key: string]: unknown
}

export type PluginObjectRef = {
  protocol: 'learnflow.plugin-object-ref.v1'
  plugin_id: string
  instance_id: number
  snapshot_id: number
  snapshot_root_hash: string
  object_type: string
  object_id: string
  schema_version: string
  content_hash: string
}

const NODE_TYPES = new Set<string>(PLUGIN_SURFACE_NODE_TYPES)
const NODE_FIELDS = new Set([
  'type', 'id', 'label', 'text', 'value', 'items', 'columns', 'rows', 'children',
  'fields', 'workflow_id', 'input',
  'title', 'source', 'nodes', 'edges', 'workflow', 'submit_label', 'name',
  'required', 'multiple', 'requires_confirmation',
])
const FORBIDDEN_KEYS = new Set([
  'html', 'dangerouslysetinnerhtml', 'script', 'style', 'url', 'href', 'src',
])

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function safeIdentifier(value: unknown, field: string) {
  const normalized = String(value || '').trim()
  if (!normalized || normalized.length > 160 || !/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(normalized)) {
    throw new Error(`插件 Surface 的 ${field} 无效`)
  }
  return normalized
}

function safeText(value: unknown, field: string, limit = 4_000) {
  if (typeof value !== 'string') throw new Error(`插件 Surface 的 ${field} 必须是文本`)
  const normalized = value.trim().slice(0, limit)
  if (/<\/?(?:script|style|iframe|object|embed)\b/i.test(normalized)) {
    throw new Error(`插件 Surface 的 ${field} 含不允许的标记`)
  }
  return normalized
}

function assertNoExecutableFields(value: unknown, depth = 0): void {
  if (depth > 12) throw new Error('插件 Surface 嵌套过深')
  if (Array.isArray(value)) {
    if (value.length > 500) throw new Error('插件 Surface 集合超出上限')
    value.forEach(item => assertNoExecutableFields(item, depth + 1))
    return
  }
  const source = record(value)
  if (!source) return
  for (const [key, item] of Object.entries(source)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) throw new Error(`插件 Surface 不允许字段 ${key}`)
    assertNoExecutableFields(item, depth + 1)
  }
}

function parseNode(value: unknown, workflowIds: Set<string>, depth: number): PluginSurfaceNode {
  if (depth > 8) throw new Error('插件 Surface 节点嵌套过深')
  const source = record(value)
  if (!source || !NODE_TYPES.has(String(source.type || ''))) throw new Error('插件 Surface 含未知节点类型')
  for (const key of Object.keys(source)) {
    if (!NODE_FIELDS.has(key)) throw new Error(`插件 Surface 节点不允许字段 ${key}`)
  }
  assertNoExecutableFields(source)

  const type = String(source.type) as PluginSurfaceNodeType
  const node: PluginSurfaceNode = { type }
  if (source.id !== undefined) node.id = safeIdentifier(source.id, 'node.id')
  if (source.label !== undefined) node.label = safeText(source.label, 'node.label', 240)
  if (source.text !== undefined) node.text = safeText(source.text, 'node.text')
  if (source.title !== undefined) node.title = safeText(source.title, 'node.title', 240)
  if (source.source !== undefined) node.source = safeIdentifier(source.source, 'node.source')
  if (source.value !== undefined) node.value = source.value
  for (const field of ['items', 'columns', 'rows'] as const) {
    if (source[field] !== undefined) {
      if (!Array.isArray(source[field])) throw new Error(`插件 Surface 的 node.${field} 必须是数组`)
      node[field] = source[field].slice(0, 200)
    }
  }
  for (const field of ['children', 'fields'] as const) {
    if (source[field] !== undefined) {
      if (!Array.isArray(source[field])) throw new Error(`插件 Surface 的 node.${field} 必须是数组`)
      node[field] = source[field].map(item => parseNode(item, workflowIds, depth + 1))
    }
  }
  if (source.input !== undefined) {
    const input = record(source.input)
    if (!input) throw new Error('插件 Surface 的 node.input 必须是对象')
    assertNoExecutableFields(input)
    node.input = input
  }
  if (source.nodes !== undefined) node.nodes = source.nodes
  if (source.edges !== undefined) node.edges = source.edges
  if (source.submit_label !== undefined) node.submit_label = safeText(source.submit_label, 'node.submit_label', 160)
  if (source.name !== undefined) node.name = safeIdentifier(source.name, 'node.name')
  for (const field of ['required', 'multiple', 'requires_confirmation'] as const) {
    if (source[field] !== undefined) {
      if (typeof source[field] !== 'boolean') throw new Error(`插件 Surface 的 node.${field} 必须是布尔值`)
      node[field] = source[field]
    }
  }
  const declaredWorkflow = source.workflow_id ?? source.workflow
  if (declaredWorkflow !== undefined) {
    node.workflow_id = safeIdentifier(declaredWorkflow, 'node.workflow_id')
    node.workflow = node.workflow_id
    if (!workflowIds.has(node.workflow_id)) throw new Error(`插件 Surface 引用了未声明 workflow：${node.workflow_id}`)
  }
  if (type === 'action' && !node.workflow_id) throw new Error('插件 Surface action 缺少 workflow_id')
  if (type === 'input') {
    node.id ||= node.name
    if (!node.id) throw new Error('插件 Surface input 缺少稳定 id 或 name')
  }
  return node
}

function workflowId(value: PluginWorkflowDescriptor) {
  return typeof value === 'string' ? value : value.id
}

export function parsePluginSurfaceDocument(value: unknown, workflows: PluginWorkflowDescriptor[] = []): PluginSurfaceDocument {
  const source = record(value)
  if (!source) throw new Error('插件 Surface 必须是对象')
  const allowedRoot = new Set(['protocol', 'id', 'title', 'label', 'slot', 'body'])
  for (const key of Object.keys(source)) {
    if (!allowedRoot.has(key)) throw new Error(`插件 Surface 根节点不允许字段 ${key}`)
  }
  if (source.protocol !== PLUGIN_SURFACE_PROTOCOL) throw new Error('插件 Surface 协议版本不受支持')
  const body = Array.isArray(source.body) ? source.body : source.body ? [source.body] : []
  if (!body.length) throw new Error('插件 Surface body 必须包含节点')
  const workflowIds = new Set(workflows.map(workflowId).map(value => safeIdentifier(value, 'workflow.id')))
  return {
    protocol: PLUGIN_SURFACE_PROTOCOL,
    id: safeIdentifier(source.id, 'id'),
    title: safeText(source.title || source.label, 'title', 240),
    slot: safeIdentifier(source.slot, 'slot'),
    body: body.map(item => parseNode(item, workflowIds, 0)),
  }
}

function parseSurface(value: unknown): ProjectPluginSurface {
  const source = record(value)
  if (!source) throw new Error('插件 Surface 条目必须是对象')
  const workflows = Array.isArray(source.workflows) ? source.workflows as PluginWorkflowDescriptor[] : []
  const schema = parsePluginSurfaceDocument(source.schema, workflows)
  const surfaceId = safeIdentifier(source.surface_id || schema.id, 'surface_id')
  const slot = safeIdentifier(source.slot || schema.slot, 'slot')
  if (surfaceId !== schema.id || slot !== schema.slot) throw new Error('插件 Surface envelope 与 schema 不一致')
  const instanceId = Number(source.instance_id)
  if (!Number.isInteger(instanceId) || instanceId <= 0) throw new Error('插件 Surface instance_id 无效')
  return {
    plugin_id: safeIdentifier(source.plugin_id, 'plugin_id'),
    instance_id: instanceId,
    surface_id: surfaceId,
    title: safeText(source.title || schema.title, 'title', 240),
    slot,
    schema,
    workflows,
    ...(record(source.data) ? { data: source.data as Record<string, unknown> } : {}),
  }
}

function parseConfigurationSchema(value: unknown): PluginConfigurationSchema | undefined {
  const source = record(value)
  if (!source) return undefined
  const rawProperties = record(source.properties) || {}
  const properties: Record<string, PluginConfigurationProperty> = {}
  for (const [name, rawProperty] of Object.entries(rawProperties)) {
    const property = record(rawProperty)
    if (!property) continue
    properties[name] = {
      ...(typeof property.type === 'string' ? { type: property.type as PluginConfigurationProperty['type'] } : {}),
      ...(typeof property.title === 'string' ? { title: property.title.slice(0, 240) } : {}),
      ...(typeof property.description === 'string' ? { description: property.description.slice(0, 1_000) } : {}),
      ...(property.default !== undefined ? { default: property.default } : {}),
      ...(typeof property.minimum === 'number' ? { minimum: property.minimum } : {}),
      ...(typeof property.maximum === 'number' ? { maximum: property.maximum } : {}),
      ...(Array.isArray(property.enum) ? { enum: property.enum.slice(0, 100) } : {}),
      ...(record(property.items) && typeof record(property.items)?.type === 'string'
        ? { items: { type: String(record(property.items)?.type) } }
        : {}),
    }
  }
  return {
    ...(source.type === 'object' ? { type: 'object' as const } : {}),
    properties,
    required: Array.isArray(source.required) ? source.required.filter(item => typeof item === 'string').slice(0, 100) : [],
    ...(typeof source.additionalProperties === 'boolean' ? { additionalProperties: source.additionalProperties } : {}),
  }
}

function parsePluginRelease(value: unknown): PluginReleaseView {
  const source = record(value)
  if (!source) throw new Error('插件 release 条目必须是对象')
  const id = Number(source.id)
  if (!Number.isInteger(id) || id <= 0) throw new Error('插件 release id 无效')
  const hostPorts = Array.isArray(source.host_ports)
    ? [...new Set(source.host_ports.map(port => safeIdentifier(port, 'host_port')))].slice(0, 32)
    : []
  const workflows = Array.isArray(source.workflows) ? source.workflows as PluginWorkflowDescriptor[] : []
  const configSchema = parseConfigurationSchema(source.config_schema)
  return {
    id,
    plugin_id: safeIdentifier(source.plugin_id, 'plugin_id'),
    version: safeText(source.version, 'version', 80),
    name: safeText(source.name || source.plugin_id, 'name', 240),
    ...(typeof source.description === 'string' ? { description: safeText(source.description, 'description', 2_000) } : {}),
    trust_state: safeIdentifier(source.trust_state, 'trust_state'),
    status: safeIdentifier(source.status, 'status'),
    ...(typeof source.owner === 'string' ? { owner: safeIdentifier(source.owner, 'owner') } : {}),
    host_ports: hostPorts,
    ...(configSchema ? { config_schema: configSchema } : {}),
    workflows,
  }
}

async function jsonRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await runtimeFetch(path, {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers || {}),
    },
  })
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>
  if (!response.ok) {
    const detail = typeof payload.detail === 'string'
      ? payload.detail
      : record(payload.detail)?.message || payload.error
    throw new Error(String(detail || `插件宿主返回 ${response.status}`))
  }
  return payload as T
}

export async function loadProjectPluginSurfaces(projectId: number, slot = 'project.context.tabs'): Promise<ProjectPluginSurfacePage> {
  const payload = await jsonRequest<Record<string, unknown>>(
    `/api/projects/${projectId}/plugin-surfaces?slot=${encodeURIComponent(slot)}`,
  )
  if (payload.schema_version !== PLUGIN_SURFACES_PROTOCOL || !Array.isArray(payload.surfaces)) {
    throw new Error('插件宿主返回了不受支持的 Surface 列表')
  }
  return {
    schema_version: PLUGIN_SURFACES_PROTOCOL,
    surfaces: payload.surfaces.map(parseSurface),
  }
}

function requestKey(pluginId: string, workflowId: string) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `plugin:${pluginId}:${workflowId}:${suffix}`
}

export async function runProjectPluginWorkflow(projectId: number, surface: ProjectPluginSurface, workflowId: string, input: Record<string, unknown> = {}) {
  const declared = new Set(surface.workflows.map(workflowId => typeof workflowId === 'string' ? workflowId : workflowId.id))
  if (!declared.has(workflowId)) throw new Error(`插件未声明 workflow：${workflowId}`)
  const snapshot = record(surface.data?.snapshot)
  const expected = Number(input.expected_snapshot_id || snapshot?.id)
  const workflowInput = { ...input }
  delete workflowInput.expected_snapshot_id
  return jsonRequest<PluginWorkflowRun>(
    `/api/projects/${projectId}/plugin-instances/${encodeURIComponent(surface.plugin_id)}/workflows/${encodeURIComponent(workflowId)}/runs`,
    {
      method: 'POST',
      body: JSON.stringify({
        input: workflowInput,
        idempotency_key: requestKey(surface.plugin_id, workflowId),
        expected_snapshot_id: Number.isInteger(expected) && expected > 0 ? expected : null,
      }),
    },
  )
}

export async function listProjectPluginInstances(projectId: number) {
  const payload = await jsonRequest<{ instances: PluginInstanceView[] }>(`/api/projects/${projectId}/plugin-instances`)
  if (!Array.isArray(payload.instances)) throw new Error('插件宿主返回了无效的实例列表')
  return {
    instances: payload.instances.map(instance => ({
      ...instance,
      ...(instance.release ? { release: parsePluginRelease(instance.release) } : {}),
      configuration: record(instance.configuration) || {},
      granted_host_ports: Array.isArray(instance.granted_host_ports) ? instance.granted_host_ports.map(String) : [],
    })),
  }
}

export async function loadProjectPluginReleaseCatalog(projectId: number): Promise<ProjectPluginReleaseCatalog> {
  const payload = await jsonRequest<Record<string, unknown>>(`/api/projects/${projectId}/plugin-releases`)
  const releases = Array.isArray(payload.releases)
    ? payload.releases
    : Array.isArray(payload.available_releases) ? payload.available_releases : null
  if (!releases) throw new Error('插件宿主返回了无效的 release 目录')
  return {
    ...(typeof payload.protocol === 'string' ? { protocol: payload.protocol } : {}),
    releases: releases.map(parsePluginRelease),
  }
}

export function enableProjectPluginInstance(projectId: number, pluginId: string, input: {
  release_id: number
  configuration?: Record<string, unknown>
  granted_host_ports?: string[]
}) {
  return jsonRequest<{ instance: PluginInstanceView; existing_instance: boolean }>(
    `/api/projects/${projectId}/plugin-instances/${encodeURIComponent(pluginId)}`,
    { method: 'PUT', body: JSON.stringify(input) },
  )
}

export function updateProjectPluginInstance(projectId: number, pluginId: string, input: {
  status?: 'enabled' | 'disabled'
  configuration?: Record<string, unknown>
  granted_host_ports?: string[]
  release_id?: number
  expected_snapshot_id?: number | null
  upgrade_idempotency_key?: string
}) {
  return jsonRequest<{ instance: PluginInstanceView; upgrade_run?: PluginWorkflowRun }>(
    `/api/projects/${projectId}/plugin-instances/${encodeURIComponent(pluginId)}`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
}

export function loadPluginRun(runId: number) {
  return jsonRequest<{ run: PluginWorkflowRun }>(`/api/plugin-runs/${runId}`)
}

export function listProjectPluginSnapshots(projectId: number, pluginId: string) {
  return jsonRequest<{ current_snapshot_id: number | null; snapshots: PluginSnapshotView[] }>(
    `/api/projects/${projectId}/plugin-instances/${encodeURIComponent(pluginId)}/snapshots`,
  )
}

export function listProjectPluginObjects(projectId: number, pluginId: string, options: {
  snapshot_id?: number
  object_type?: string
  offset?: number
  limit?: number
} = {}) {
  const query = new URLSearchParams()
  if (options.snapshot_id) query.set('snapshot_id', String(options.snapshot_id))
  if (options.object_type) query.set('object_type', options.object_type)
  if (options.offset !== undefined) query.set('offset', String(options.offset))
  if (options.limit !== undefined) query.set('limit', String(options.limit))
  const suffix = query.size ? `?${query}` : ''
  return jsonRequest<{
    snapshot: PluginSnapshotView
    objects: Array<{ ref: PluginObjectRef; label?: string; lifecycle?: string; [key: string]: unknown }>
    page: { offset: number; limit: number; has_more: boolean }
  }>(`/api/projects/${projectId}/plugin-instances/${encodeURIComponent(pluginId)}/objects${suffix}`)
}

export function loadProjectPluginObject(projectId: number, pluginId: string, objectId: string, snapshotId?: number) {
  const suffix = snapshotId ? `?snapshot_id=${snapshotId}` : ''
  return jsonRequest<{
    snapshot: PluginSnapshotView
    index: { ref: PluginObjectRef; [key: string]: unknown }
    object: unknown
  }>(`/api/projects/${projectId}/plugin-instances/${encodeURIComponent(pluginId)}/objects/${encodeURIComponent(objectId)}${suffix}`)
}
