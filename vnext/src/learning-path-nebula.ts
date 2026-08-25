import type { LearningPathEdge, LearningPathNode } from './learning-path-graph'

export type KnowledgeClusterId =
  | 'mathematics'
  | 'foundations'
  | 'hardware'
  | 'security'
  | 'practice'
  | 'systems'
  | 'data'
  | 'ai'
  | 'software'

export type KnowledgeCluster = {
  id: KnowledgeClusterId
  label: string
  caption: string
  color: string
  rgb: string
  center: { x: number; y: number }
}

export type NebulaNodePosition = {
  nodeId: string
  clusterId: KnowledgeClusterId
  x: number
  y: number
  size: number
  degree: number
}

export const NEBULA_WIDTH = 1500
export const NEBULA_HEIGHT = 1120

export const KNOWLEDGE_CLUSTERS: KnowledgeCluster[] = [
  { id: 'mathematics', label: '数学与理论', caption: '抽象、证明与建模语言', color: '#7d78c9', rgb: '125,120,201', center: { x: 250, y: 205 } },
  { id: 'foundations', label: '专业基础', caption: '编程、算法与计算思维', color: '#2f9a72', rgb: '47,154,114', center: { x: 750, y: 190 } },
  { id: 'hardware', label: '硬件与嵌入式', caption: '从逻辑电路到真实设备', color: '#c28b45', rgb: '194,139,69', center: { x: 1250, y: 205 } },
  { id: 'security', label: '网络与安全', caption: '连接、攻防与可信边界', color: '#bd6267', rgb: '189,98,103', center: { x: 250, y: 550 } },
  { id: 'practice', label: '研究与实践', caption: '用产物和证据完成迁移', color: '#8a7257', rgb: '138,114,87', center: { x: 750, y: 535 } },
  { id: 'systems', label: '系统与云', caption: '资源、并发与大规模运行', color: '#4d83aa', rgb: '77,131,170', center: { x: 1250, y: 550 } },
  { id: 'data', label: '数据', caption: '组织、查询与数据工程', color: '#3b9290', rgb: '59,146,144', center: { x: 250, y: 900 } },
  { id: 'ai', label: 'AI 与智能体', caption: '学习、生成、决策与行动', color: '#8763b0', rgb: '135,99,176', center: { x: 750, y: 895 } },
  { id: 'software', label: '软件与交互', caption: '构造、架构与用户体验', color: '#5b8e5f', rgb: '91,142,95', center: { x: 1250, y: 900 } },
]

const clusterById = new Map(KNOWLEDGE_CLUSTERS.map(cluster => [cluster.id, cluster]))

const FOUNDATION_IDS = new Set([
  'digital-literacy', 'computer-introduction', 'computing-ethics', 'programming-foundations',
  'python-programming', 'c-programming', 'object-oriented-programming', 'data-structures', 'algorithms',
])
const PRACTICE_IDS = new Set(['research-methods', 'capstone-project', 'thesis-research'])
const HARDWARE_IDS = new Set(['digital-logic', 'computer-organization', 'embedded-systems'])

export function clusterLearningPathNode(node: LearningPathNode): KnowledgeClusterId {
  if (PRACTICE_IDS.has(node.id) || node.domains.includes('实践') || node.domains.includes('研究') && node.stage === 'research') return 'practice'
  if (FOUNDATION_IDS.has(node.id)) return 'foundations'
  if (HARDWARE_IDS.has(node.id) || node.domains.some(domain => ['硬件', '物联网'].includes(domain))) return 'hardware'
  if (node.domains.some(domain => ['安全', '网络'].includes(domain))) return 'security'
  if (node.domains.some(domain => ['数学', '理论', '算法'].includes(domain))) return 'mathematics'
  if (node.domains.some(domain => ['AI', '智能体', '机器人', '视觉', '语言', '决策'].includes(domain))) return 'ai'
  if (node.domains.some(domain => ['数据'].includes(domain))) return 'data'
  if (node.domains.some(domain => ['系统', '云', '运维', '计算'].includes(domain))) return 'systems'
  return 'software'
}

export function knowledgeCluster(clusterId: KnowledgeClusterId) {
  return clusterById.get(clusterId)!
}

export function layoutLearningPathNebula(nodes: LearningPathNode[], edges: LearningPathEdge[]) {
  const degree = new Map(nodes.map(node => [node.id, 0]))
  edges.forEach(edge => {
    degree.set(edge.from, (degree.get(edge.from) || 0) + 1)
    degree.set(edge.to, (degree.get(edge.to) || 0) + 1)
  })
  const positions = new Map<string, NebulaNodePosition>()
  KNOWLEDGE_CLUSTERS.forEach(cluster => {
    const clusterNodes = nodes.filter(node => clusterLearningPathNode(node) === cluster.id)
      .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0) || a.order - b.order || a.title.localeCompare(b.title))
    clusterNodes.forEach((node, index) => {
      const nodeDegree = degree.get(node.id) || 0
      const size = Math.max(52, Math.min(82, 52 + nodeDegree * 3))
      if (index === 0) {
        positions.set(node.id, { nodeId: node.id, clusterId: cluster.id, x: cluster.center.x - size / 2, y: cluster.center.y - size / 2, size, degree: nodeDegree })
        return
      }
      const firstRing = index <= 6
      const ringIndex = firstRing ? index - 1 : index - 7
      const ringCount = firstRing ? Math.min(6, Math.max(1, clusterNodes.length - 1)) : Math.max(1, clusterNodes.length - 7)
      const angle = -Math.PI / 2 + (Math.PI * 2 * ringIndex) / ringCount + (firstRing ? 0 : Math.PI / Math.max(5, ringCount))
      const radiusX = firstRing ? 102 : 184
      const radiusY = firstRing ? 78 : 125
      positions.set(node.id, {
        nodeId: node.id,
        clusterId: cluster.id,
        x: cluster.center.x + Math.cos(angle) * radiusX - size / 2,
        y: cluster.center.y + Math.sin(angle) * radiusY - size / 2,
        size,
        degree: nodeDegree,
      })
    })
  })
  return positions
}

export function nebulaEdgePath(from: NebulaNodePosition, to: NebulaNodePosition, edgeId: string) {
  const x1 = from.x + from.size / 2
  const y1 = from.y + from.size / 2
  const x2 = to.x + to.size / 2
  const y2 = to.y + to.size / 2
  let hash = 0
  for (let index = 0; index < edgeId.length; index += 1) hash = (hash * 31 + edgeId.charCodeAt(index)) | 0
  const bend = (Math.abs(hash) % 43) - 21
  const controlX = (x1 + x2) / 2 + (y2 - y1) * 0.035
  const controlY = (y1 + y2) / 2 + bend
  return `M ${x1} ${y1} Q ${controlX} ${controlY} ${x2} ${y2}`
}
