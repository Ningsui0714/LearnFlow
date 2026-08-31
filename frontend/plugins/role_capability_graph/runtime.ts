import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  LEARNFLOW_PLUGIN_OBJECT_VERSION,
  type LearnFlowPluginObject,
  type PluginJson,
  type PluginToolResult,
} from '../../src/plugin-api.ts'
import {
  ROLE_CAPABILITY_PLUGIN,
  ROLE_OBJECT_SCHEMA_VERSION,
  ROLE_RENDERERS,
} from './shared.ts'

type JsonObject = Record<string, PluginJson>

type StaticPackageManifest = {
  packageProtocol: string
  protocolVersion: string
  packageId: string
  packageVersion: string
  snapshotId: string
  snapshotAsOf: string
  roleTitle: string
  visibility: string
  evidencePolicy: string
  entrypoints: Record<string, string>
  hashes: Record<string, string>
  rootHash: string
}

type RoleNode = JsonObject & {
  id: string
  type: string
  label: string
  summary: string
  aliases?: string[]
  lifecycle?: string
  confidence?: number
  evidenceBindingIds?: string[]
  evidenceSegmentIds?: string[]
  ring?: number
}

type RoleRelation = JsonObject & {
  id: string
  type: string
  source?: string
  target?: string
  processNodeId?: string
  semanticNodeId?: string
  confidence?: number
  evidenceBindingIds?: string[]
  evidenceSegmentIds?: string[]
}

type ProcessScenario = JsonObject & {
  id: string
  label: string
  summary: string
  lifecycle?: string
  knowledgeState?: string
  taskRefs?: string[]
  evidenceBindingIds?: string[]
  evidenceSegmentIds?: string[]
}

type ProcessNode = RoleNode & {
  scenarioId: string
  kind: string
  knowledgeState?: string
  sequenceHint?: number
  taskRefs?: string[]
}

type SourceAsset = JsonObject & { id: string; title: string; publisher?: string; locator?: string }
type SourceSegment = JsonObject & { id: string; sourceId: string; text: string; locator?: string }
type EvidenceBinding = JsonObject & {
  id: string
  targetId: string
  sourceId: string
  segmentId: string
  confidence?: number
  strength?: string
  support?: string
  assertionType?: string
  limitations?: string[]
}

type LoadedRolePackage = {
  manifest: StaticPackageManifest
  semantic: { nodes: RoleNode[]; edges: RoleRelation[]; claims: JsonObject[] }
  process: { scenarios: ProcessScenario[]; nodes: ProcessNode[]; edges: RoleRelation[]; bridges: RoleRelation[] }
  sources: { assets: SourceAsset[]; segments: SourceSegment[]; evidenceBindings: EvidenceBinding[] }
  validation: JsonObject
  objects: Map<string, RoleNode | ProcessScenario | ProcessNode>
  relations: RoleRelation[]
  outgoing: Map<string, RoleRelation[]>
  incoming: Map<string, RoleRelation[]>
  assets: Map<string, SourceAsset>
  segments: Map<string, SourceSegment>
  bindingsByTarget: Map<string, EvidenceBinding[]>
}

export type PackageSelector = {
  packageId?: string
  packageVersion?: string
  snapshotId?: string
}

const PACKAGE_ROOT = fileURLToPath(new URL('./data/packages', import.meta.url))
const MAX_OBJECT_IDS = 25
const MAX_SEARCH_RESULTS = 12
const MAX_GRAPH_NODES = 28
const MAX_PROCESS_NODES = 36
const MAX_EVIDENCE_TARGETS = 8

function asObject(value: unknown, label: string): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`role_package_invalid:${label}`)
  return value as JsonObject
}

function readJson(path: string) {
  const raw = readFileSync(path, 'utf8')
  return { raw, value: JSON.parse(raw) as unknown }
}

function sha256(value: string) {
  return createHash('sha256').update(value).digest('hex')
}

function discoverManifests(root: string) {
  const manifests: string[] = []
  for (const packageDirectory of readdirSync(root, { withFileTypes: true }).filter(item => item.isDirectory())) {
    const packagePath = join(root, packageDirectory.name)
    for (const versionDirectory of readdirSync(packagePath, { withFileTypes: true }).filter(item => item.isDirectory())) {
      manifests.push(join(packagePath, versionDirectory.name, 'manifest.json'))
    }
  }
  return manifests.sort()
}

function loadPackage(manifestPath: string): LoadedRolePackage {
  const manifest = asObject(readJson(manifestPath).value, 'manifest') as unknown as StaticPackageManifest
  if (manifest.packageProtocol !== 'static-role-package' || !manifest.packageId || !manifest.snapshotId || !manifest.rootHash) {
    throw new Error(`role_package_invalid:${manifestPath}`)
  }
  const directory = dirname(manifestPath)
  function component(entrypoint: string, label: string) {
    const filename = manifest.entrypoints[entrypoint]
    if (!filename || filename.includes('..') || filename.startsWith('/')) throw new Error(`role_package_invalid:${label}_entrypoint`)
    const loaded = readJson(join(directory, filename))
    if (manifest.hashes[filename] !== sha256(loaded.raw)) throw new Error(`role_package_hash_mismatch:${filename}`)
    return asObject(loaded.value, label)
  }
  const semantic = component('semanticGraph', 'semantic') as unknown as LoadedRolePackage['semantic']
  const process = component('workProcessForest', 'process') as unknown as LoadedRolePackage['process']
  const sources = component('sources', 'sources') as unknown as LoadedRolePackage['sources']
  const validation = component('validation', 'validation')
  if (!Array.isArray(semantic.nodes) || !Array.isArray(semantic.edges)
    || !Array.isArray(process.scenarios) || !Array.isArray(process.nodes) || !Array.isArray(process.edges)
    || !Array.isArray(sources.assets) || !Array.isArray(sources.segments) || !Array.isArray(sources.evidenceBindings)) {
    throw new Error(`role_package_invalid:${manifest.packageId}`)
  }
  const objects = new Map<string, RoleNode | ProcessScenario | ProcessNode>()
  ;[...semantic.nodes, ...process.scenarios, ...process.nodes].forEach(object => {
    if (!object.id || objects.has(object.id)) throw new Error(`role_package_duplicate_object:${object.id}`)
    objects.set(object.id, object)
  })
  const relations = [...semantic.edges, ...process.edges, ...process.bridges]
  const outgoing = new Map<string, RoleRelation[]>()
  const incoming = new Map<string, RoleRelation[]>()
  relations.forEach(relation => {
    const source = relation.source || relation.processNodeId
    const target = relation.target || relation.semanticNodeId
    if (!source || !target || !objects.has(source) || !objects.has(target)) throw new Error(`role_package_relation_invalid:${relation.id}`)
    outgoing.set(source, [...(outgoing.get(source) || []), relation])
    incoming.set(target, [...(incoming.get(target) || []), relation])
  })
  const assets = new Map(sources.assets.map(asset => [asset.id, asset]))
  const segments = new Map(sources.segments.map(segment => [segment.id, segment]))
  const bindingsByTarget = new Map<string, EvidenceBinding[]>()
  sources.evidenceBindings.forEach(binding => bindingsByTarget.set(binding.targetId, [
    ...(bindingsByTarget.get(binding.targetId) || []), binding,
  ]))
  return { manifest, semantic, process, sources, validation, objects, relations, outgoing, incoming, assets, segments, bindingsByTarget }
}

function normalize(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase().replace(/[\s\p{P}\p{S}]+/gu, '')
}

function tokens(value: string) {
  const text = normalize(value)
  const result = new Set<string>()
  for (const word of value.toLocaleLowerCase().match(/[a-z0-9][a-z0-9._:+-]*/g) || []) result.add(word)
  for (const character of text) result.add(character)
  for (let index = 0; index < text.length - 1; index += 1) result.add(text.slice(index, index + 2))
  return [...result]
}

function relationEndpoints(relation: RoleRelation) {
  return {
    source: relation.source || relation.processNodeId || '',
    target: relation.target || relation.semanticNodeId || '',
  }
}

function objectKind(object: RoleNode | ProcessScenario | ProcessNode) {
  if ('kind' in object && typeof object.kind === 'string') return object.kind
  if ('scenarioId' in object && typeof object.scenarioId === 'string') return 'scenario'
  return typeof object.type === 'string' ? object.type : 'object'
}

function jsonRecord(value: unknown): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject
}

export class RolePackageRuntime {
  readonly packages: readonly LoadedRolePackage[]

  constructor(root = PACKAGE_ROOT) {
    this.packages = discoverManifests(root).map(loadPackage)
    if (!this.packages.length) throw new Error('role_package_unavailable:no static packages were found')
  }

  resolve(selector: PackageSelector) {
    const matches = this.packages.filter(item => (
      (!selector.packageId || item.manifest.packageId === selector.packageId)
      && (!selector.packageVersion || item.manifest.packageVersion === selector.packageVersion)
      && (!selector.snapshotId || item.manifest.snapshotId === selector.snapshotId)
    ))
    if (matches.length !== 1) {
      throw new Error(matches.length
        ? 'role_package_ambiguous:provide packageId, packageVersion or snapshotId'
        : 'role_package_not_found:the requested immutable package is not installed')
    }
    return matches[0]
  }

  descriptor(pkg: LoadedRolePackage) {
    return {
      packageId: pkg.manifest.packageId,
      packageVersion: pkg.manifest.packageVersion,
      snapshotId: pkg.manifest.snapshotId,
      snapshotAsOf: pkg.manifest.snapshotAsOf,
      rootHash: pkg.manifest.rootHash,
      roleTitle: pkg.manifest.roleTitle,
      evidencePolicy: pkg.manifest.evidencePolicy,
    }
  }

  private pluginObject(pkg: LoadedRolePackage, objectType: string, objectId: string, label: string, category: string, data: unknown): LearnFlowPluginObject {
    return {
      protocol: LEARNFLOW_PLUGIN_OBJECT_VERSION,
      pluginId: ROLE_CAPABILITY_PLUGIN.id,
      objectType,
      objectId,
      schemaVersion: ROLE_OBJECT_SCHEMA_VERSION,
      label,
      value: {
        ...this.descriptor(pkg),
        category,
        data: jsonRecord(data),
      },
    }
  }

  private nodeObject(pkg: LoadedRolePackage, object: RoleNode | ProcessScenario | ProcessNode) {
    return this.pluginObject(pkg, 'role_object', object.id, object.label, objectKind(object), object)
  }

  private relationObject(pkg: LoadedRolePackage, relation: RoleRelation) {
    return this.pluginObject(pkg, 'role_relation', relation.id, relation.type, relation.type, {
      ...relation,
      ...relationEndpoints(relation),
    })
  }

  private result(pkg: LoadedRolePackage, summary: string, renderer: string, objects: LearnFlowPluginObject[], payload: JsonObject): PluginToolResult {
    return {
      summary,
      objects,
      payload: { snapshot: this.descriptor(pkg), ...payload },
      presentation: { renderer, state: { snapshotId: pkg.manifest.snapshotId } },
    }
  }

  readObjects(selector: PackageSelector, objectIds: string[], includeRelations: boolean) {
    const pkg = this.resolve(selector)
    const ids = [...new Set(objectIds)].slice(0, MAX_OBJECT_IDS)
    const objects = ids.map(id => pkg.objects.get(id)).filter((item): item is RoleNode | ProcessScenario | ProcessNode => Boolean(item))
    const relations = includeRelations
      ? [...new Map(objects.flatMap(object => [...(pkg.outgoing.get(object.id) || []), ...(pkg.incoming.get(object.id) || [])]).map(item => [item.id, item])).values()].slice(0, 36)
      : []
    return this.result(pkg, `读取 ${objects.length}/${ids.length} 个岗位对象${relations.length ? `及 ${relations.length} 条一跳关系` : ''}。`, ROLE_RENDERERS.cards, [
      ...objects.map(object => this.nodeObject(pkg, object)),
      ...relations.map(relation => this.relationObject(pkg, relation)),
    ], {
      kind: 'role_objects', requested: ids.length, returned: objects.length,
      omittedIds: ids.filter(id => !pkg.objects.has(id)), truncated: objectIds.length > MAX_OBJECT_IDS,
    })
  }

  search(selector: PackageSelector, query: string, topK: number, includeCandidate: boolean) {
    const pkg = this.resolve(selector)
    const queryTokens = tokens(query)
    const scored = [...pkg.objects.values()].filter(object => includeCandidate || object.lifecycle !== 'candidate').map(object => {
      const text = [object.id, object.label, object.summary, objectKind(object), ...(('aliases' in object && Array.isArray(object.aliases)) ? object.aliases : [])].join(' ')
      const targetTokens = new Set(tokens(text))
      const overlap = queryTokens.filter(token => targetTokens.has(token)).length
      const exact = normalize(text).includes(normalize(query)) ? Math.max(3, queryTokens.length) : 0
      return { object, score: overlap + exact }
    }).filter(item => item.score > 0).sort((left, right) => right.score - left.score || left.object.id.localeCompare(right.object.id))
    const selected = scored.slice(0, Math.min(Math.max(1, topK), MAX_SEARCH_RESULTS))
    return this.result(pkg, `在固定快照中找到 ${selected.length} 个与“${query.slice(0, 80)}”相关的对象。`, ROLE_RENDERERS.cards,
      selected.map(item => this.nodeObject(pkg, item.object)), {
        kind: 'search_results', query, coverage: {
          complete: scored.length <= selected.length,
          returned: selected.length,
          omitted: Math.max(0, scored.length - selected.length),
        },
        scores: selected.map(item => ({ objectId: item.object.id, score: item.score })),
      })
  }

  queryGraph(selector: PackageSelector, objectId: string, depth: number, direction: 'outgoing' | 'incoming' | 'both', maxNodes: number) {
    const pkg = this.resolve(selector)
    if (!pkg.objects.has(objectId)) throw new Error(`role_object_not_found:${objectId}`)
    const limit = Math.min(Math.max(2, maxNodes), MAX_GRAPH_NODES)
    const nodeIds = new Set([objectId])
    const relations = new Map<string, RoleRelation>()
    let frontier = [objectId]
    for (let level = 0; level < Math.min(Math.max(1, depth), 2) && frontier.length && nodeIds.size < limit; level += 1) {
      const next: string[] = []
      for (const current of frontier) {
        const candidates = [
          ...(direction !== 'incoming' ? pkg.outgoing.get(current) || [] : []),
          ...(direction !== 'outgoing' ? pkg.incoming.get(current) || [] : []),
        ]
        for (const relation of candidates) {
          const endpoints = relationEndpoints(relation)
          const adjacent = endpoints.source === current ? endpoints.target : endpoints.source
          if (!pkg.objects.has(adjacent)) continue
          relations.set(relation.id, relation)
          if (!nodeIds.has(adjacent) && nodeIds.size < limit) {
            nodeIds.add(adjacent)
            next.push(adjacent)
          }
        }
      }
      frontier = next
    }
    const nodes = [...nodeIds].map(id => pkg.objects.get(id)!)
    const boundedRelations = [...relations.values()].filter(relation => {
      const endpoints = relationEndpoints(relation)
      return nodeIds.has(endpoints.source) && nodeIds.has(endpoints.target)
    }).slice(0, 48)
    return this.result(pkg, `从“${pkg.objects.get(objectId)!.label}”读取 ${nodes.length} 个节点和 ${boundedRelations.length} 条关系。`, ROLE_RENDERERS.graph, [
      ...nodes.map(object => this.nodeObject(pkg, object)),
      ...boundedRelations.map(relation => this.relationObject(pkg, relation)),
    ], { kind: 'role_graph', rootId: objectId, depth: Math.min(Math.max(1, depth), 2), direction, truncated: nodeIds.size >= limit })
  }

  traceProcess(selector: PackageSelector, objectId: string, maxNodes: number) {
    const pkg = this.resolve(selector)
    const scenarioIds = new Set<string>()
    if (pkg.process.scenarios.some(item => item.id === objectId)) scenarioIds.add(objectId)
    pkg.process.scenarios.filter(item => item.taskRefs?.includes(objectId)).forEach(item => scenarioIds.add(item.id))
    const processObject = pkg.process.nodes.find(item => item.id === objectId)
    if (processObject) scenarioIds.add(processObject.scenarioId)
    pkg.process.bridges.filter(item => item.semanticNodeId === objectId).forEach(bridge => {
      const node = pkg.process.nodes.find(item => item.id === bridge.processNodeId)
      if (node) scenarioIds.add(node.scenarioId)
    })
    if (!scenarioIds.size) throw new Error(`role_process_not_found:${objectId}`)
    const limit = Math.min(Math.max(4, maxNodes), MAX_PROCESS_NODES)
    const scenarios = pkg.process.scenarios.filter(item => scenarioIds.has(item.id)).slice(0, 4)
    const nodes = pkg.process.nodes.filter(item => scenarioIds.has(item.scenarioId)).sort((left, right) => (left.sequenceHint || 999) - (right.sequenceHint || 999) || left.id.localeCompare(right.id)).slice(0, limit)
    const nodeIds = new Set([...scenarios.map(item => item.id), ...nodes.map(item => item.id)])
    const relations = [...pkg.process.edges, ...pkg.process.bridges].filter(relation => {
      const endpoints = relationEndpoints(relation)
      return nodeIds.has(endpoints.source) && (nodeIds.has(endpoints.target) || pkg.objects.has(endpoints.target))
    }).slice(0, 64)
    return this.result(pkg, `读取 ${scenarios.length} 个工作场景、${nodes.length} 个事理对象和 ${relations.length} 条关系。`, ROLE_RENDERERS.process, [
      ...scenarios.map(object => this.nodeObject(pkg, object)),
      ...nodes.map(object => this.nodeObject(pkg, object)),
      ...relations.map(relation => this.relationObject(pkg, relation)),
    ], {
      kind: 'process_forest', anchorId: objectId, scenarioIds: scenarios.map(item => item.id),
      boundary: '事理森林表示有证据边界的工作模式；除 observed_pattern 外，不是企业真实事件日志。',
      truncated: pkg.process.nodes.filter(item => scenarioIds.has(item.scenarioId)).length > nodes.length,
    })
  }

  inspectEvidence(selector: PackageSelector, objectIds: string[]) {
    const pkg = this.resolve(selector)
    const ids = [...new Set(objectIds)].slice(0, MAX_EVIDENCE_TARGETS)
    const evidence = ids.flatMap(targetId => (pkg.bindingsByTarget.get(targetId) || []).slice(0, 6).map(binding => {
      const segment = pkg.segments.get(binding.segmentId)
      const source = pkg.assets.get(binding.sourceId)
      return { targetId, binding, segment: segment ? { ...segment, text: segment.text.slice(0, 900) } : undefined, source }
    }))
    const objects = evidence.map(item => this.pluginObject(pkg, 'role_evidence', item.binding.id,
      item.source?.title || item.binding.id, item.binding.assertionType || 'evidence_binding', item))
    return this.result(pkg, `为 ${ids.length} 个对象解析 ${evidence.length} 条证据绑定。`, ROLE_RENDERERS.evidence, objects, {
      kind: 'role_evidence', targetIds: ids,
      coverage: ids.map(targetId => ({ targetId, bindingCount: (pkg.bindingsByTarget.get(targetId) || []).length })),
      truncated: objectIds.length > MAX_EVIDENCE_TARGETS,
    })
  }

  audit(selector: PackageSelector) {
    const pkg = this.resolve(selector)
    const validation = pkg.validation
    const descriptor = this.descriptor(pkg)
    return this.result(pkg, `岗位包“${descriptor.roleTitle}”协议${validation.valid === true ? '有效' : '无效'}；读取结构统计、警告和研究缺口。`, ROLE_RENDERERS.audit, [
      this.pluginObject(pkg, 'role_snapshot', pkg.manifest.snapshotId, descriptor.roleTitle, 'snapshot', descriptor),
      this.pluginObject(pkg, 'role_audit', `${pkg.manifest.snapshotId}:validation`, '岗位包结构审计', 'validation', validation),
    ], { kind: 'role_audit', validation })
  }
}

export function packageSelector(input: Record<string, PluginJson>): PackageSelector {
  return {
    packageId: typeof input.packageId === 'string' && input.packageId ? input.packageId : undefined,
    packageVersion: typeof input.packageVersion === 'string' && input.packageVersion ? input.packageVersion : undefined,
    snapshotId: typeof input.snapshotId === 'string' && input.snapshotId ? input.snapshotId : undefined,
  }
}

export const rolePackageRuntime = new RolePackageRuntime()
