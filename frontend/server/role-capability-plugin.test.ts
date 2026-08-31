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

test('role capability plugin is discovered declaratively with six bounded read tools and one Skill', async () => {
  const loaded = await registry()
  const tools = loaded.toolDefinitions(activation)
  assert.deepEqual(tools.map(tool => tool.name), [
    'role_capability_graph__read_role_objects',
    'role_capability_graph__search_role_knowledge',
    'role_capability_graph__query_role_graph',
    'role_capability_graph__trace_work_process',
    'role_capability_graph__inspect_role_evidence',
    'role_capability_graph__audit_role_package',
  ])
  assert.ok(tools.every(tool => tool.risk === 'read_only'))
  assert.match(loaded.skillInstructions(activation), /唯一岗位事实版本/)
  assert.match(loaded.skillInstructions(activation), /不能覆盖 LearnFlow 的教学状态/)
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
