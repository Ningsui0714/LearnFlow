import assert from 'node:assert/strict'
import test from 'node:test'

import { learnerPathStateFromFormal } from '../src/formal-runtime.ts'
import { projectLearnerPath } from '../src/learning-path-graph.ts'

test('formal learning-path overlay restores self-report and personal nodes without mastery inference', () => {
  const state = learnerPathStateFromFormal({
    version: 1,
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
    event_backed: true,
    knowledge_mastery_inference: false,
  })
  const projection = projectLearnerPath(state)
  assert.equal(projection.statuses.calculus, 'self_reported_mastered')
  assert.ok(projection.personalNodeIds.includes('personal-agent-eval'))
  assert.ok(projection.edges.some(edge => edge.to === 'personal-agent-eval'))
})
