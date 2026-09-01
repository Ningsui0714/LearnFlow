import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { loadLearnFlowPluginRegistry } from './plugin-loader.ts'

const activation = { mode: 'simple_explain' as const, activePluginIds: ['role_capability_graph'] }
const executionContext = {
  ...activation,
  scope: { mode: 'simple_explain' as const, conversationId: 'test-conversation' },
  signal: AbortSignal.timeout(5_000),
}

async function registry() {
  return loadLearnFlowPluginRegistry(resolve(process.cwd(), 'plugins'))
}

test('role capability plugin is discovered declaratively with read and candidate-artifact tools', async () => {
  const loaded = await registry()
  const tools = loaded.toolDefinitions(activation)
  assert.deepEqual(tools.map(tool => tool.name), [
    'role_capability_graph__explore_role',
    'role_capability_graph__read_capability_radar',
    'role_capability_graph__read_role_objects',
    'role_capability_graph__search_role_knowledge',
    'role_capability_graph__query_role_graph',
    'role_capability_graph__trace_work_process',
    'role_capability_graph__inspect_role_evidence',
    'role_capability_graph__audit_role_package',
    'role_capability_graph__list_role_packages',
    'role_capability_graph__compare_role_packages',
    'role_capability_graph__start_role_cold_start',
    'role_capability_graph__draft_role_iteration',
  ])
  assert.equal(tools.filter(tool => tool.risk === 'read_only').length, 10)
  assert.equal(tools.filter(tool => tool.risk === 'artifact').length, 2)
  assert.match(loaded.skillInstructions(activation), /唯一岗位事实版本/)
  assert.match(loaded.skillInstructions(activation), /第一步调用 role_capability_graph__explore_role/)
  assert.match(loaded.skillInstructions(activation), /通用补充（非岗位快照）/)
  assert.match(loaded.skillInstructions(activation), /不能覆盖 LearnFlow 的教学状态/)
  assert.match(loaded.skillInstructions(activation), /任务屏障/)
  assert.match(loaded.skillInstructions(activation), /候选 patch/)
})

test('cold start produces an inspectable candidate contract without inventing a snapshot', async () => {
  const loaded = await registry()
  const waiting = await loaded.execute('role_capability_graph__start_role_cold_start', {
    roleTitle: '数据治理工程师', purpose: '研究岗位边界与课程输入', audiences: ['学习者'], sourceBriefs: [],
  }, executionContext)
  assert.equal(waiting.result.presentation?.renderer, 'role_capability_graph:role_build_candidate')
  const object = waiting.result.objects?.[0]
  assert.equal(object?.objectType, 'role_build_candidate')
  assert.equal((object?.value as any).status, 'waiting_sources')
  assert.match((object?.value as any).contentHash, /^[a-f0-9]{64}$/)
  assert.equal((object?.value as any).data.stages[2].id, 'task_barrier')
  assert.doesNotMatch(waiting.result.summary, /已创建.*快照/u)

  const ready = await loaded.execute('role_capability_graph__start_role_cold_start', {
    roleTitle: '数据治理工程师', purpose: '研究岗位边界与课程输入', sourceBriefs: ['某职业标准：职责与任务条款'],
  }, executionContext)
  assert.equal((ready.result.objects?.[0].value as any).status, 'ready_for_evidence_extraction')
  await assert.rejects(() => loaded.execute('role_capability_graph__start_role_cold_start', {
    roleTitle: '数据治理工程师', purpose: '边界测试', sourceBriefs: Array.from({ length: 13 }, (_, index) => `来源 ${index}`),
  }, executionContext), /exceeds maxItems/)
})

test('iteration fixes an exact base snapshot and returns only a candidate patch contract', async () => {
  const loaded = await registry()
  const overview = await loaded.execute('role_capability_graph__explore_role', { query: '大模型应用工程师' }, executionContext)
  const payload = overview.result.payload as any
  const targetId = payload.sections.tasks[0]
  const iteration = await loaded.execute('role_capability_graph__draft_role_iteration', {
    snapshotId: payload.snapshot.snapshotId,
    prompt: '补充这个任务的证据并核验过程覆盖',
    targetIds: [targetId], proposedChanges: ['补充一条有来源绑定的验收活动'], initiativeProfile: 'co_guided',
  }, executionContext)
  assert.equal(iteration.result.presentation?.renderer, 'role_capability_graph:role_iteration_candidate')
  const candidate = iteration.result.objects?.[0]
  assert.equal(candidate?.objectType, 'role_iteration_candidate')
  assert.equal((candidate?.value as any).baseSnapshotId, payload.snapshot.snapshotId)
  assert.equal((candidate?.value as any).expectedRootHash, payload.snapshot.rootHash)
  assert.equal((candidate?.value as any).data.proposedChanges[0].status, 'proposed')
  assert.match((candidate?.value as any).data.stopConditions.join(' '), /保持当前快照/)
})

test('one overview call returns grounded role, task, capability and scenario sections', async () => {
  const loaded = await registry()
  const execution = await loaded.execute('role_capability_graph__explore_role', {
    query: '介绍一下大模型应用工程师',
  }, executionContext)
  assert.equal(execution.result.presentation?.renderer, 'role_capability_graph:role_overview')
  const payload = execution.result.payload as any
  assert.equal(payload.kind, 'role_overview')
  assert.ok(payload.sections.tasks.length >= 4)
  assert.ok(payload.sections.capabilities.length >= 4)
  assert.ok(payload.sections.scenarios.length >= 3)
  assert.equal(payload.grounding.policy, 'snapshot_facts_only')
  assert.ok(payload.grounding.facts.every((fact: any) => fact.objectId && fact.statement))
  assert.equal((execution.result.presentation?.state as any).snapshotId, payload.snapshot.snapshotId)
  assert.ok((execution.result.presentation?.state as any).focusObjectIds.includes(payload.rootId))
})

test('capability radar expands semantic rings around the role and package catalog is version-addressable', async () => {
  const loaded = await registry()
  const radar = await loaded.execute('role_capability_graph__read_capability_radar', { query: '' }, executionContext)
  assert.equal(radar.result.presentation?.renderer, 'role_capability_graph:capability_radar')
  const radarPayload = radar.result.payload as any
  assert.equal(radarPayload.kind, 'role_dimension_radar')
  assert.ok(radarPayload.rings.length >= 5)
  assert.equal(radarPayload.rings[0].ring, 0)
  assert.ok(radarPayload.rings.some((ring: any) => ring.label === '知识技能'))
  assert.ok(radar.result.objects?.some(object => object.objectType === 'role_relation'))
  assert.match(radarPayload.boundary, /不是学习者能力评分/)

  const catalog = await loaded.execute('role_capability_graph__list_role_packages', {}, executionContext)
  assert.equal(catalog.result.presentation?.renderer, 'role_capability_graph:role_package_catalog')
  const snapshots = (catalog.result.payload as any).packages
  assert.ok(snapshots.length >= 1)
  const comparison = await loaded.execute('role_capability_graph__compare_role_packages', {
    baseSnapshotId: snapshots[0].snapshotId,
    targetSnapshotId: snapshots[0].snapshotId,
  }, executionContext)
  assert.equal(comparison.result.presentation?.renderer, 'role_capability_graph:role_package_comparison')
  assert.deepEqual((comparison.result.payload as any).added, [])
  assert.deepEqual((comparison.result.payload as any).removed, [])
  assert.deepEqual((comparison.result.payload as any).changed, [])
})

test('search pins one immutable package and returns typed objects with explicit coverage', async () => {
  const loaded = await registry()
  const execution = await loaded.execute('role_capability_graph__search_role_knowledge', {
    query: 'RAG 评测与知识库', topK: 5, includeCandidate: true,
  }, executionContext)
  assert.equal(execution.result.presentation?.renderer, 'role_capability_graph:role_cards')
  assert.ok(execution.result.objects?.length)
  const snapshotIds = new Set(execution.result.objects?.map(object => (object.value as any).snapshotId))
  const rootHashes = new Set(execution.result.objects?.map(object => (object.value as any).rootHash))
  assert.equal(snapshotIds.size, 1)
  assert.equal(rootHashes.size, 1)
  assert.match([...rootHashes][0], /^[a-f0-9]{64}$/)
  assert.equal((execution.result.payload as any).kind, 'search_results')
  assert.equal(typeof (execution.result.payload as any).coverage.complete, 'boolean')
})

test('graph, process, evidence and audit tools preserve package identity and renderer contracts', async () => {
  const loaded = await registry()
  const search = await loaded.execute('role_capability_graph__search_role_knowledge', { query: '构建 RAG', topK: 1 }, executionContext)
  const objectId = search.result.objects![0].objectId
  const graph = await loaded.execute('role_capability_graph__query_role_graph', { objectId, depth: 1, direction: 'both', maxNodes: 12 }, executionContext)
  assert.equal(graph.result.presentation?.renderer, 'role_capability_graph:role_graph')
  assert.ok(graph.result.objects?.some(object => object.objectType === 'role_relation'))
  assert.equal(graph.result.objects?.filter(object => object.objectType === 'role_object').length, (graph.result.payload as any).truncated ? 12 : graph.result.objects?.filter(object => object.objectType === 'role_object').length)
  const graphPayload = graph.result.payload as any
  assert.equal(graphPayload.grounding.relationFacts.length, graph.result.objects?.filter(object => object.objectType === 'role_relation').length)
  assert.ok(graphPayload.grounding.relationFacts.every((fact: any) => fact.relationId && fact.sourceId && fact.targetId && fact.type))
  assert.match(graphPayload.grounding.requiredDisclosure, /不得改名、反向或补造/)

  const task = await loaded.execute('role_capability_graph__search_role_knowledge', { query: '发布应用', topK: 8 }, executionContext)
  const processAnchor = task.result.objects!.find(object => ['task', 'scenario', 'event'].includes(String((object.value as any).category)))
  assert.ok(processAnchor)
  const process = await loaded.execute('role_capability_graph__trace_work_process', { objectId: processAnchor!.objectId, maxNodes: 20 }, executionContext)
  assert.equal(process.result.presentation?.renderer, 'role_capability_graph:process_forest')
  assert.match(String((process.result.payload as any).boundary), /不是企业真实事件日志/)

  const evidence = await loaded.execute('role_capability_graph__inspect_role_evidence', { objectIds: [objectId] }, executionContext)
  assert.equal(evidence.result.presentation?.renderer, 'role_capability_graph:evidence_panel')
  assert.ok(evidence.result.objects?.every(object => object.objectType === 'role_evidence'))

  const audit = await loaded.execute('role_capability_graph__audit_role_package', {}, executionContext)
  assert.equal(audit.result.presentation?.renderer, 'role_capability_graph:audit_panel')
  assert.equal((audit.result.payload as any).validation.valid, true)
})

test('package selectors fail closed instead of silently switching snapshots', async () => {
  const loaded = await registry()
  await assert.rejects(() => loaded.execute('role_capability_graph__audit_role_package', {
    snapshotId: 'snapshot:not-installed',
  }, executionContext), /role_package_not_found/)
})

test('role plugin implementation stays inside its package and host files contain no role-specific branches', () => {
  const hostSource = [
    resolve(process.cwd(), 'src/plugin-api.ts'),
    resolve(process.cwd(), 'src/PluginToolResultView.tsx'),
    resolve(process.cwd(), 'server/agent-runtime.ts'),
  ].map(path => readFileSync(path, 'utf8')).join('\n')
  assert.doesNotMatch(hostSource, /role_capability_graph|llm-app-engineer|process_forest/)
})
