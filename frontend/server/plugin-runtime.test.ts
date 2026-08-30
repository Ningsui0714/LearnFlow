import assert from 'node:assert/strict'
import test from 'node:test'

import {
  enableProjectPluginInstance,
  listProjectPluginInstances,
  loadProjectPluginReleaseCatalog,
  loadProjectPluginSurfaces,
  parsePluginSurfaceDocument,
  runProjectPluginWorkflow,
  updateProjectPluginInstance,
} from '../src/plugin-runtime.ts'

const workflows = [{ id: 'generate' }, { id: 'iterate' }]
const officialSurface = {
  protocol: 'learnflow.plugin-surface.v1',
  id: 'role_capability_project',
  slot: 'project.context.tabs',
  label: '岗位图谱',
  body: {
    type: 'section', title: '岗位能力图谱', children: [
      { type: 'status', source: 'instance.status', label: '插件状态' },
      { type: 'metric', source: 'snapshot.validation.stats.nodes', label: '对象' },
      {
        type: 'form', id: 'generate_role_package', workflow: 'generate', submit_label: '生成岗位包',
        children: [{ type: 'input', name: 'role_title', label: '目标岗位', required: true }],
      },
      { type: 'action', workflow: 'iterate', label: '迭代当前快照', requires_confirmation: true },
    ],
  },
}

test('official plugin surface is normalized to the safe v1 renderer contract', () => {
  const surface = parsePluginSurfaceDocument(officialSurface, workflows)
  assert.equal(surface.title, '岗位图谱')
  assert.equal(surface.body.length, 1)
  const section = surface.body[0]
  const form = section.children?.[2]
  assert.equal(form?.workflow_id, 'generate')
  assert.equal(form?.children?.[0].id, 'role_title')
  assert.equal(section.children?.[3].workflow_id, 'iterate')
})

test('plugin surface rejects executable fields and undeclared workflows', () => {
  assert.throws(() => parsePluginSurfaceDocument({
    ...officialSurface,
    body: { type: 'section', children: [{ type: 'text', html: '<b>unsafe</b>' }] },
  }, workflows), /不允许字段 html/)
  assert.throws(() => parsePluginSurfaceDocument({
    ...officialSurface,
    body: { type: 'action', workflow: 'delete_everything', label: '危险动作' },
  }, workflows), /未声明 workflow/)
  assert.throws(() => parsePluginSurfaceDocument({
    ...officialSurface,
    body: { type: 'citation', value: { url: 'https://example.test' } },
  }, workflows), /不允许字段 url/)
})

test('surface discovery and workflow execution use only generic plugin host APIs', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    if (String(url).includes('/plugin-surfaces')) {
      return new Response(JSON.stringify({
        schema_version: 'learnflow.plugin-surfaces.v1',
        surfaces: [{
          plugin_id: 'role_capability_graph', instance_id: 7, surface_id: 'role_capability_project',
          title: '岗位图谱', slot: 'project.context.tabs', schema: officialSurface, workflows,
          data: { instance: { status: 'enabled' }, snapshot: null },
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    return new Response(JSON.stringify({ run_id: 41, status: 'completed' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch
  try {
    const page = await loadProjectPluginSurfaces(12)
    assert.equal(page.surfaces[0].data?.instance && (page.surfaces[0].data?.instance as any).status, 'enabled')
    await runProjectPluginWorkflow(12, page.surfaces[0], 'generate', { role_title: 'Agent 工程师' })
    await runProjectPluginWorkflow(12, page.surfaces[0], 'iterate', {
      expected_snapshot_id: 9, objective: '补充线上质量任务',
    })
    assert.equal(calls[0].url, '/api/projects/12/plugin-surfaces?slot=project.context.tabs')
    assert.equal(calls[1].url, '/api/projects/12/plugin-instances/role_capability_graph/workflows/generate/runs')
    assert.equal(JSON.parse(String(calls[1].init?.body)).expected_snapshot_id, null)
    assert.equal(calls[2].url, '/api/projects/12/plugin-instances/role_capability_graph/workflows/iterate/runs')
    assert.deepEqual(JSON.parse(String(calls[2].init?.body)), {
      input: { objective: '补充线上质量任务' },
      idempotency_key: JSON.parse(String(calls[2].init?.body)).idempotency_key,
      expected_snapshot_id: 9,
    })
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('project owner can discover releases and explicitly manage a pinned plugin instance', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const release = {
    id: 14,
    plugin_id: 'role_capability_graph',
    version: '1.0.0',
    name: '岗位能力图谱',
    description: '项目岗位图谱插件',
    trust_state: 'trusted_signed',
    status: 'active',
    owner: 'learning_design_agent',
    host_ports: ['project.read.v1', 'source.read.v1'],
    config_schema: {
      type: 'object',
      properties: {
        max_tasks: { type: 'integer', minimum: 1, maximum: 40, default: 12 },
        include_process_view: { type: 'boolean', default: true },
      },
      additionalProperties: false,
    },
    workflows: [{ id: 'upgrade', mode: 'migration' }],
  }
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    if (String(url).endsWith('/plugin-releases')) {
      return new Response(JSON.stringify({ protocol: 'learnflow.plugin-catalog.v1', releases: [release] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    if (String(url).endsWith('/plugin-instances') && (!init?.method || init.method === 'GET')) {
      return new Response(JSON.stringify({ instances: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({
      instance: {
        id: 31, project_id: 8, plugin_id: release.plugin_id, release_id: release.id,
        release, status: 'enabled', current_snapshot_id: 90,
        configuration: { max_tasks: 20, include_process_view: true },
        granted_host_ports: release.host_ports,
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch

  try {
    const catalog = await loadProjectPluginReleaseCatalog(8)
    const instances = await listProjectPluginInstances(8)
    assert.equal(catalog.releases[0].config_schema?.properties?.max_tasks.default, 12)
    assert.deepEqual(catalog.releases[0].host_ports, ['project.read.v1', 'source.read.v1'])
    assert.deepEqual(instances.instances, [])

    await enableProjectPluginInstance(8, release.plugin_id, {
      release_id: release.id,
      configuration: { max_tasks: 20, include_process_view: true },
      granted_host_ports: release.host_ports,
    })
    await updateProjectPluginInstance(8, release.plugin_id, {
      release_id: 15,
      expected_snapshot_id: 90,
      upgrade_idempotency_key: 'plugin-upgrade:role_capability_graph:test-1',
      configuration: { max_tasks: 24, include_process_view: false },
      granted_host_ports: ['project.read.v1'],
    })
    await updateProjectPluginInstance(8, release.plugin_id, { status: 'disabled' })

    assert.equal(calls[0].url, '/api/projects/8/plugin-releases')
    assert.equal(calls[1].url, '/api/projects/8/plugin-instances')
    assert.equal(calls[2].init?.method, 'PUT')
    assert.deepEqual(JSON.parse(String(calls[2].init?.body)), {
      release_id: 14,
      configuration: { max_tasks: 20, include_process_view: true },
      granted_host_ports: ['project.read.v1', 'source.read.v1'],
    })
    assert.equal(calls[3].init?.method, 'PATCH')
    assert.deepEqual(JSON.parse(String(calls[3].init?.body)), {
      release_id: 15,
      expected_snapshot_id: 90,
      upgrade_idempotency_key: 'plugin-upgrade:role_capability_graph:test-1',
      configuration: { max_tasks: 24, include_process_view: false },
      granted_host_ports: ['project.read.v1'],
    })
    assert.deepEqual(JSON.parse(String(calls[4].init?.body)), { status: 'disabled' })
  } finally {
    globalThis.fetch = originalFetch
  }
})
