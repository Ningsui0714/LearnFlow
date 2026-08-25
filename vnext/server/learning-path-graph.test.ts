import assert from 'node:assert/strict'
import test from 'node:test'

import {
  OFFICIAL_PATH_EDGES,
  OFFICIAL_PATH_NODES,
  addPersonalPathNode,
  buildPersonalNodeProposal,
  createInitialLearnerPathState,
  projectLearnerPath,
  readLearningPathGraph,
  removePersonalPathNode,
  setLearnerPathStatus,
  validateOfficialLearningPathGraph,
} from '../src/learning-path-graph.ts'
import { runTutorTools } from './tool-runtime.ts'
import {
  KNOWLEDGE_CLUSTERS,
  NEBULA_HEIGHT,
  NEBULA_WIDTH,
  clusterLearningPathNode,
  layoutLearningPathNebula,
} from '../src/learning-path-nebula.ts'

test('official graph is sourced, broad, and acyclic', () => {
  const validation = validateOfficialLearningPathGraph()
  assert.equal(validation.valid, true, validation.errors.join('\n'))
  assert.ok(OFFICIAL_PATH_NODES.length >= 60)
  assert.ok(OFFICIAL_PATH_EDGES.length >= 80)
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.audiences.includes('vocational')))
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.audiences.includes('graduate')))
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.id === 'agent-engineering'))
  assert.ok(OFFICIAL_PATH_NODES.every((node) => node.sourceRefs.length > 0))
})

test('reader returns a planning packet around a known course', () => {
  const packet = readLearningPathGraph('我想系统学习 Agent 开发', createInitialLearnerPathState())
  assert.equal(packet.matchKind, 'official_match')
  assert.ok(packet.matchedNodeIds.includes('agent-engineering'))
  assert.equal(packet.needsExternalResearch, false)
  assert.equal(packet.manifest.noKnowledgeMasteryInference, true)
})

test('a graph gap becomes a confirmable personal node and remains removable', () => {
  const initial = createInitialLearnerPathState()
  const packet = readLearningPathGraph('我想学习量子机器学习', initial)
  assert.equal(packet.matchKind, 'graph_gap')
  assert.equal(packet.needsExternalResearch, true)

  const proposal = buildPersonalNodeProposal(packet, [
    'https://example.edu/quantum-machine-learning',
  ])
  assert.ok(proposal)
  const added = addPersonalPathNode(initial, proposal!)
  const projection = projectLearnerPath(added)
  const personal = projection.nodes.find((node) => node.sourceProposalId === proposal!.id)
  assert.ok(personal)
  assert.ok(projection.edges.some((edge) => edge.to === personal!.id))

  const removed = removePersonalPathNode(added, personal!.id)
  assert.equal(projectLearnerPath(removed).nodes.some((node) => node.id === personal!.id), false)
})

test('course status remains explicitly self reported', () => {
  const state = setLearnerPathStatus(
    createInitialLearnerPathState(),
    'machine-learning',
    'self_reported_mastered',
  )
  const packet = readLearningPathGraph('机器学习', state)
  assert.equal(packet.nodes.find((node) => node.id === 'machine-learning')?.status, 'self_reported_mastered')
  assert.equal(packet.manifest.noKnowledgeMasteryInference, true)
})

test('planning mode invokes the path reader without asking the model to decide structure', async () => {
  const result = await runTutorTools({
    message: '我想规划 Agent 开发的学习路线',
    choice: 'auto',
    mode: 'learning_plan',
    learnerPathState: createInitialLearnerPathState(),
    generate: async () => { throw new Error('known-node path read should not need generation') },
  })
  const pathRun = result.runs.find(run => run.kind === 'path')
  assert.equal(pathRun?.status, 'completed')
  assert.match(pathRun?.detail || '', /智能体工程/)
  assert.match(result.context, /结构核参考投影/)
  assert.match(result.context, /不能替代题目、项目或迁移证据/)
})

test('knowledge nebula gives every course one bounded thematic position', () => {
  const positions = layoutLearningPathNebula(OFFICIAL_PATH_NODES, OFFICIAL_PATH_EDGES)
  assert.equal(positions.size, OFFICIAL_PATH_NODES.length)
  assert.equal(new Set(OFFICIAL_PATH_NODES.map(clusterLearningPathNode)).size, KNOWLEDGE_CLUSTERS.length)
  positions.forEach(position => {
    assert.ok(position.x >= 0 && position.x + position.size <= NEBULA_WIDTH)
    assert.ok(position.y >= 0 && position.y + position.size <= NEBULA_HEIGHT)
  })
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'linear-algebra')!), 'mathematics')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'operating-systems')!), 'systems')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'agent-engineering')!), 'ai')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'computer-security')!), 'security')
})
