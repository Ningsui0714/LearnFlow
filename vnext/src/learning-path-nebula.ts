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

export const NEBULA_WIDTH = 1280
export const NEBULA_HEIGHT = 930

export const KNOWLEDGE_CLUSTERS: KnowledgeCluster[] = [
  { id: 'mathematics', label: '数学与理论', caption: '抽象、证明与建模语言', color: '#766fb8', rgb: '118,111,184', center: { x: 350, y: 175 } },
  { id: 'hardware', label: '硬件与嵌入式', caption: '从逻辑电路到真实设备', color: '#ac7d43', rgb: '172,125,67', center: { x: 755, y: 155 } },
  { id: 'systems', label: '系统与云', caption: '资源、并发与大规模运行', color: '#497b9d', rgb: '73,123,157', center: { x: 1030, y: 330 } },
  { id: 'security', label: '网络与安全', caption: '连接、攻防与可信边界', color: '#ad5c62', rgb: '173,92,98', center: { x: 1030, y: 655 } },
  { id: 'software', label: '软件与交互', caption: '构造、架构与用户体验', color: '#548259', rgb: '84,130,89', center: { x: 770, y: 770 } },
  { id: 'practice', label: '研究与实践', caption: '用产物和证据完成迁移', color: '#806d57', rgb: '128,109,87', center: { x: 485, y: 775 } },
  { id: 'data', label: '数据', caption: '组织、查询与数据工程', color: '#3c8583', rgb: '60,133,131', center: { x: 245, y: 620 } },
  { id: 'ai', label: 'AI 与智能体', caption: '学习、生成、决策与行动', color: '#7d5da1', rgb: '125,93,161', center: { x: 235, y: 360 } },
  { id: 'foundations', label: '专业基础', caption: '编程、算法与计算思维', color: '#2d8966', rgb: '45,137,102', center: { x: 625, y: 445 } },
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
      const ring = index <= 6 ? 1 : index <= 18 ? 2 : 3
      const ringStart = ring === 1 ? 1 : ring === 2 ? 7 : 19
      const ringCapacity = ring === 1 ? 6 : ring === 2 ? 12 : Math.max(1, clusterNodes.length - 19)
      const ringIndex = index - ringStart
      const ringCount = Math.min(ringCapacity, Math.max(1, clusterNodes.length - ringStart))
      const angle = -Math.PI / 2 + (Math.PI * 2 * ringIndex) / ringCount + (ring === 2 ? Math.PI / Math.max(6, ringCount) : 0)
      const radiusX = ring === 1 ? 92 : ring === 2 ? 148 : 188
      const radiusY = ring === 1 ? 68 : ring === 2 ? 108 : 142
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
  const fromCenterX = from.x + from.size / 2
  const fromCenterY = from.y + from.size / 2
  const toCenterX = to.x + to.size / 2
  const toCenterY = to.y + to.size / 2
  const deltaX = toCenterX - fromCenterX
  const deltaY = toCenterY - fromCenterY
  const length = Math.max(1, Math.hypot(deltaX, deltaY))
  const unitX = deltaX / length
  const unitY = deltaY / length
  const x1 = fromCenterX + unitX * (from.size / 2 + 3)
  const y1 = fromCenterY + unitY * (from.size / 2 + 3)
  const x2 = toCenterX - unitX * (to.size / 2 + 9)
  const y2 = toCenterY - unitY * (to.size / 2 + 9)
  let hash = 0
  for (let index = 0; index < edgeId.length; index += 1) hash = (hash * 31 + edgeId.charCodeAt(index)) | 0
  const bend = (Math.abs(hash) % 43) - 21
  const controlX = (x1 + x2) / 2 + (y2 - y1) * 0.035
  const controlY = (y1 + y2) / 2 + bend
  return `M ${x1} ${y1} Q ${controlX} ${controlY} ${x2} ${y2}`
}
