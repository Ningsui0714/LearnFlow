import assert from 'node:assert/strict'
import test from 'node:test'

import { learnerPathStateFromFormal } from '../src/formal-runtime.ts'
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
