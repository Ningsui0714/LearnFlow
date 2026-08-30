import assert from 'node:assert/strict'
import test from 'node:test'
import {
  activateRoleCapabilityForTutor,
  planRoleCapabilityBootstrap,
} from '../src/role-capability-tutor.ts'

const schema = {
  protocol: 'learnflow.plugin-surface.v1',
  id: 'role_capability_project',
  title: '岗位图谱',
  slot: 'project.context.tabs',
  body: [{ type: 'section', title: '岗位图谱' }],
}

const emptySurface: any = {
  plugin_id: 'role_capability_graph', instance_id: 7, surface_id: 'role_capability_project',
  title: '岗位图谱', slot: 'project.context.tabs', schema, workflows: ['generate', 'iterate'],
  data: { snapshot: null },
}

test('project objective containing only a role is enough to build a generic bootstrap plan', () => {
  const plan = planRoleCapabilityBootstrap({
    projectName: '岗位分析',
    projectObjective: '研究一下大模型应用工程师',
  })
  assert.equal(plan?.roleTitle, '大模型应用工程师')
  assert.equal(plan?.origin, 'project_objective')
  assert.equal(plan?.taskSeeds.length, 3)
  assert.match(plan?.taskSeeds[0] || '', /真实工作场景/)
})

test('latest conversational role overrides a generic project objective', () => {
  const plan = planRoleCapabilityBootstrap({
    message: '我想研究数据产品经理',
    projectName: '岗位分析',
    projectObjective: '研究职业方向',
  })
  assert.equal(plan?.roleTitle, '数据产品经理')
  assert.equal(plan?.origin, 'message')
})

test('generic project names do not fabricate a role', () => {
  assert.equal(planRoleCapabilityBootstrap({ projectName: '岗位分析', projectObjective: '' }), undefined)
})

test('Tutor activation generates once and returns an in-message snapshot artifact', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    if (init?.method === 'POST') {
      return new Response(JSON.stringify({ run: { id: 41, status: 'completed' } }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({
      schema_version: 'learnflow.plugin-surfaces.v1',
      surfaces: [{
        ...emptySurface,
        data: { snapshot: {
          id: 35, version: 1, root_hash: 'a'.repeat(64), validation: { valid: true, errors: [], warnings: [] },
          components: {
            'semantic-graph': {
              nodes: [{ id: 'role:1', type: 'role', label: '大模型应用工程师' }, { id: 'task:1', type: 'task', label: '构建应用' }],
              edges: [{ id: 'edge:1', type: 'owns_task', source: 'role:1', target: 'task:1' }],
            },
            'process-forest': { scenarios: [], events: [], work_objects: [], bridges: [] },
          },
        } },
      }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  try {
    const result = await activateRoleCapabilityForTutor({
      projectId: 12,
      surface: emptySurface,
      project: { id: 12, name: '岗位分析', objective: '大模型应用工程师', expected_outcome: '', user_level: '' },
    })
    assert.equal(result.status, 'generated')
    assert.equal(result.context.snapshotId, 35)
    assert.equal(result.artifact?.title, '大模型应用工程师岗位图谱')
    const request = JSON.parse(String(calls[0].init?.body))
    assert.equal(request.input.role_title, '大模型应用工程师')
    assert.equal(request.input.task_seeds.length, 3)
    assert.match(request.idempotency_key, /^plugin:role_capability_graph:bootstrap:p12:i7:r[0-9a-f]{8}:v1$/)
  } finally {
    globalThis.fetch = originalFetch
  }
})
