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
  NEBULA_WIDTH,
  clusterLearningPathNode,
  learningStageIndex,
  layoutLearningPathNebula,
  nebulaHeight,
  traceLearningPath,
} from '../src/learning-path-nebula.ts'

test('official graph is sourced, broad, and acyclic', () => {
  const validation = validateOfficialLearningPathGraph()
  assert.equal(validation.valid, true, validation.errors.join('\n'))
  assert.ok(OFFICIAL_PATH_NODES.length >= 90)
  assert.ok(OFFICIAL_PATH_EDGES.length >= 140)
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.audiences.includes('vocational')))
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.audiences.includes('graduate')))
  assert.ok(OFFICIAL_PATH_NODES.some((node) => node.id === 'agent-engineering'))
  assert.ok(OFFICIAL_PATH_NODES.every((node) => node.sourceRefs.length > 0))
})

test('vocational computer and information technology pathways expose job-facing core courses', () => {
  const expectedVocationalNodes = [
    'computer-maintenance', 'windows-server-administration', 'network-cabling',
    'software-modeling-design', 'enterprise-application-development', 'software-testing',
    'wireless-networking', 'network-automation', 'network-systems-integration',
    'virtualization-technology', 'cloud-platform-operations', 'container-cloud-operations',
    'data-acquisition-technology', 'data-preprocessing-etl', 'data-analysis-applications',
    'data-visualization-applications', 'big-data-platform-operations',
    'operating-system-security', 'security-product-configuration', 'storage-disaster-recovery',
    'digital-forensics', 'security-risk-assessment', 'mobile-cross-platform', 'mini-program-development',
  ]
  expectedVocationalNodes.forEach(nodeId => {
    const node = OFFICIAL_PATH_NODES.find(item => item.id === nodeId)
    assert.ok(node, `missing vocational node: ${nodeId}`)
    assert.ok(node!.audiences.includes('vocational'), `${nodeId} must support vocational learners`)
    assert.ok(node!.sourceRefs.some(source => source.startsWith('moe-')), `${nodeId} must cite an MOE standard`)
  })
  assert.ok(OFFICIAL_PATH_EDGES.some(edge => edge.from === 'network-routing-switching' && edge.to === 'network-systems-integration'))
  assert.ok(OFFICIAL_PATH_EDGES.some(edge => edge.from === 'cloud-platform-operations' && edge.to === 'container-cloud-operations'))
  assert.ok(OFFICIAL_PATH_EDGES.some(edge => edge.from === 'data-preprocessing-etl' && edge.to === 'data-analysis-applications'))
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
  const canvasHeight = nebulaHeight(OFFICIAL_PATH_NODES)
  assert.equal(positions.size, OFFICIAL_PATH_NODES.length)
  assert.equal(new Set(OFFICIAL_PATH_NODES.map(clusterLearningPathNode)).size, KNOWLEDGE_CLUSTERS.length)
  positions.forEach(position => {
    assert.ok(position.x >= 0 && position.x + position.width <= NEBULA_WIDTH)
    assert.ok(position.y >= 0 && position.y + position.height <= canvasHeight)
  })
  assert.ok(learningStageIndex(OFFICIAL_PATH_NODES.find(node => node.id === 'python-programming')!.stage)
    < learningStageIndex(OFFICIAL_PATH_NODES.find(node => node.id === 'agent-engineering')!.stage))
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'linear-algebra')!), 'mathematics')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'operating-systems')!), 'systems')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'agent-engineering')!), 'ai')
  assert.equal(clusterLearningPathNode(OFFICIAL_PATH_NODES.find(node => node.id === 'computer-security')!), 'security')
})

test('knowledge nebula distinguishes one-hop hover from pinned prerequisite paths', () => {
  const oneHop = traceLearningPath(OFFICIAL_PATH_EDGES, 'machine-learning', false)
  const fullPath = traceLearningPath(OFFICIAL_PATH_EDGES, 'machine-learning', true)
  assert.ok(oneHop.nodes.has('machine-learning'))
  assert.ok(fullPath.nodes.size >= oneHop.nodes.size)
  assert.ok(fullPath.upstream.has('linear-algebra'))
  assert.ok(fullPath.edgeIds.size > 0)
})
