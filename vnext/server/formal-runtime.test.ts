import assert from 'node:assert/strict'
import test from 'node:test'

import {
  advanceFormalLearningSkillTurn,
  createFormalTutorSession,
  learnerPathStateFromFormal,
  startFormalLearningSkillRun,
} from '../src/formal-runtime.ts'
import { projectLearnerPath } from '../src/learning-path-graph.ts'

test('formal learning-path overlay restores self-report and personal nodes without mastery inference', () => {
  const state = learnerPathStateFromFormal({
    version: 2,
    statuses: {
      calculus: { status: 'self_reported_mastered', node_title: '微积分' },
    },
    personal_nodes: [{
      id: 'personal-agent-eval',
      title: 'Agent 评测工程',
      summary: '围绕可复现评测构建个人节点',
      aliases: ['Agent Evals'],
      domains: ['AI', '工程'],
      stage: 'advanced',
      order: 6,
      sourceRefs: ['https://example.com/source'],
      edges: [{ id: 'edge-1', from: 'machine-learning', to: 'personal-agent-eval', kind: 'soft_prerequisite', rationale: '需要基础', origin: 'personal' }],
    }],
    plans: [{
      id: 'path-plan-agent',
      title: '通向 Agent 工程的长期路径',
      objective: '半年内系统学习 Agent 工程',
      horizon: '6 个月',
      target_node_ids: ['agent-engineering'],
      route_node_ids: ['python-programming', 'machine-learning', 'agent-engineering'],
      milestone_node_ids: ['python-programming', 'machine-learning', 'agent-engineering'],
      rationale: '按前置关系形成路线',
      evidence_quote: '我想系统学习 Agent 工程',
      status: 'active',
      revision: 1,
    }],
    active_plan_id: 'path-plan-agent',
    event_backed: true,
    knowledge_mastery_inference: false,
  })
  const projection = projectLearnerPath(state)
  assert.equal(projection.statuses.calculus, 'self_reported_mastered')
  assert.ok(projection.personalNodeIds.includes('personal-agent-eval'))
  assert.ok(projection.edges.some(edge => edge.to === 'personal-agent-eval'))
  assert.equal(projection.activePlan?.id, 'path-plan-agent')
  assert.ok(projection.activePlan?.targetNodeIds.includes('agent-engineering'))
})

test('vNext formal skill binding uses a session, a SkillRun and a deterministic turn endpoint', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; body: any }> = []
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    const target = String(url)
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url: target, body })
    if (target === '/api/agent/sessions') return new Response(JSON.stringify({
      id: 41, title: 'vNext', session_type: 'global', learning_tasks: [],
    }), { status: 200 })
    const run = {
      id: 71, skill: { id: 'guided_explanation', name: '清晰讲解' }, goal: '哈希表',
      status: 'active', state: 'presenting_core_model', stage_label: '建立核心模型',
      step_index: 1, total_steps: 4, turn_count: body?.message ? 1 : 0, turn_budget: 4,
      support_count: 0, flow_note: '每次一步', version: body?.message ? 2 : 1,
      next_prompt: '给一个最小例子', can_start_verification: false, can_pause: true, can_resume: false,
      learning_task: { id: 88, title: '哈希表', status: 'active', current_phase_id: 'learn', plan_version: 1, version: 1 },
    }
    return new Response(JSON.stringify({ session_id: 41, active_skill_run: run, created: true }), { status: 200 })
  }) as typeof fetch
  try {
    const session = await createFormalTutorSession(true)
    const started = await startFormalLearningSkillRun(41, 'guided_explanation', '哈希表', 'vnext-skill:test')
    const advanced = await advanceFormalLearningSkillTurn(41, 71, '我觉得它把键映射到数组位置', 1, 'vnext-turn:test')
    assert.equal(session.id, 41)
    assert.equal(started.active_skill_run.learning_task?.id, 88)
    assert.equal(advanced.active_skill_run.version, 2)
    assert.deepEqual(calls.map(call => call.url), [
      '/api/agent/sessions',
      '/api/agent/sessions/41/skill-runs',
      '/api/agent/sessions/41/skill-runs/71/turns',
    ])
    assert.equal(calls[2].body.expected_version, 1)
    assert.equal(calls[2].body.client_turn_id, 'vnext-turn:test')
  } finally {
    globalThis.fetch = originalFetch
  }
})
