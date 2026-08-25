import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import {
  LEARNING_PATH_SOURCES,
  PATH_EDGE_LABELS,
  PATH_STATUS_LABELS,
  buildPersonalNodeProposal,
  projectLearnerPath,
  readLearningPathGraph,
  type LearnerPathState,
  type LearnerPathStatus,
  type LearningPathNode,
  type PathEdgeKind,
  type PersonalPathNodeProposal,
} from './learning-path-graph'
import {
  KNOWLEDGE_CLUSTERS,
  NEBULA_HEIGHT,
  NEBULA_WIDTH,
  clusterLearningPathNode,
  knowledgeCluster,
  layoutLearningPathNebula,
  nebulaEdgePath,
  type KnowledgeClusterId,
} from './learning-path-nebula'

type Props = {
  state: LearnerPathState
  onStatusChange: (nodeId: string, status: LearnerPathStatus) => void
  onAddPersonalNode: (proposal: PersonalPathNodeProposal) => void
  onRemovePersonalNode: (nodeId: string) => void
}

const STATUS_ORDER: LearnerPathStatus[] = ['unmarked', 'exploring', 'self_reported_exposed', 'self_reported_mastered']

function compact(value: string) {
  return value.toLowerCase().replace(/[\s·（）()_\-/]+/g, '')
}

export default function LearningPathPage({ state, onStatusChange, onAddPersonalNode, onRemovePersonalNode }: Props) {
  const projection = useMemo(() => projectLearnerPath(state), [state])
  const canvasScrollRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [clusterFilter, setClusterFilter] = useState<'all' | KnowledgeClusterId>('all')
  const [audience, setAudience] = useState('全部')
  const [selectedId, setSelectedId] = useState('agent-engineering')
  const [hoveredId, setHoveredId] = useState<string>()
  const [showSources, setShowSources] = useState(false)
  const [personalTitle, setPersonalTitle] = useState('')
  const [anchorId, setAnchorId] = useState('machine-learning')
  const [edgeKind, setEdgeKind] = useState<PathEdgeKind>('soft_prerequisite')

  const nebulaPositions = useMemo(() => layoutLearningPathNebula(projection.nodes, projection.edges), [projection.nodes, projection.edges])
  const visibleNodes = useMemo(() => {
    const normalized = compact(query)
    return projection.nodes.filter(node => {
      const matchesQuery = !normalized || [node.title, ...node.aliases, ...node.domains].some(value => compact(value).includes(normalized))
      const matchesCluster = clusterFilter === 'all' || clusterLearningPathNode(node) === clusterFilter
      const matchesAudience = audience === '全部' || node.audiences.includes(audience as LearningPathNode['audiences'][number])
      return matchesQuery && matchesCluster && matchesAudience
    })
  }, [projection.nodes, query, clusterFilter, audience])
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const selected = projection.nodes.find(node => node.id === selectedId && visibleIds.has(node.id)) || visibleNodes[0]
  const nodeMap = new Map(projection.nodes.map(node => [node.id, node]))
  const emphasisId = hoveredId && visibleIds.has(hoveredId) ? hoveredId : selected?.id
  const emphasisEdgeIds = new Set(emphasisId
    ? projection.edges.filter(edge => edge.from === emphasisId || edge.to === emphasisId).map(edge => edge.id)
    : [])
  const hoverEdgeIds = new Set(hoveredId
    ? projection.edges.filter(edge => edge.from === hoveredId || edge.to === hoveredId).map(edge => edge.id)
    : [])
  const focusNodeIds = new Set(hoveredId ? [hoveredId] : [])
  projection.edges.forEach(edge => {
    if (!hoverEdgeIds.has(edge.id)) return
    focusNodeIds.add(edge.from)
    focusNodeIds.add(edge.to)
  })
  const visibleEdges = projection.edges.filter(edge => visibleIds.has(edge.from) && visibleIds.has(edge.to))
  const clusterCounts = useMemo(() => Object.fromEntries(KNOWLEDGE_CLUSTERS.map(cluster => [
    cluster.id,
    projection.nodes.filter(node => clusterLearningPathNode(node) === cluster.id).length,
  ])) as Record<KnowledgeClusterId, number>, [projection.nodes])
  const selectedPrerequisites = selected
    ? projection.edges.filter(edge => edge.to === selected.id).map(edge => ({ edge, node: nodeMap.get(edge.from) })).filter(item => item.node)
    : []
  const selectedSuccessors = selected
    ? projection.edges.filter(edge => edge.from === selected.id).map(edge => ({ edge, node: nodeMap.get(edge.to) })).filter(item => item.node)
    : []

  useEffect(() => {
    if (!selected || !canvasScrollRef.current) return
    const position = nebulaPositions.get(selected.id)
    if (!position) return
    const viewport = canvasScrollRef.current
    const left = Math.max(0, position.x + position.size / 2 - viewport.clientWidth / 2)
    const top = Math.max(0, position.y + position.size / 2 - viewport.clientHeight / 2)
    viewport.scrollTo({ left, top, behavior: 'smooth' })
  }, [selected?.id, nebulaPositions])

  const addManualNode = () => {
    const title = personalTitle.trim()
    const anchor = projection.nodes.find(node => node.id === anchorId)
    if (!title || !anchor) return
    const packet = readLearningPathGraph(`学习${title}`, state)
    const generated = buildPersonalNodeProposal({ ...packet, topicCandidate: title, needsExternalResearch: true, suggestedAnchorIds: [anchor.id] }, [])
    if (!generated) return
    onAddPersonalNode({
      ...generated,
      id: `manual-${Date.now()}`,
      connections: [{ nodeId: anchor.id, kind: edgeKind, rationale: `由学习者手动关联到“${anchor.title}”` }],
    })
    setPersonalTitle('')
  }

  return (
    <section className="path-page">
      <header className="path-heading">
        <div>
          <span className="eyebrow">STRUCTURE MAP · PERSONAL OVERLAY</span>
          <h1>学习路径</h1>
          <p>官方课程图提供共同坐标，个人节点补足真实目标；它帮助规划，不命令你按图学习。</p>
        </div>
        <div className="path-manifest">
          <strong>{projection.nodes.length}</strong><span>节点</span>
          <strong>{projection.edges.length}</strong><span>关系</span>
          <strong>{projection.personalNodeIds.length}</strong><span>个人节点</span>
        </div>
      </header>

      <div className="path-boundary-note">
        <span>证据边界</span>
        <p>“学过 / 掌握”是你的自报标记，只用于路线导航；正式 Knowledge 核掌握仍需练习、项目或迁移证据。</p>
      </div>

      <div className="path-layout">
        <main className="path-main">
          <div className="path-filters">
            <label><span>查找课程或技能</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="机器学习、网络安全、Agent…" /></label>
            <label><span>学习阶段</span><select value={audience} onChange={event => setAudience(event.target.value)}><option>全部</option><option value="vocational">高职</option><option value="undergraduate">本科</option><option value="graduate">研究生</option><option value="self_directed">自主学习</option></select></label>
            <button type="button" onClick={() => setShowSources(value => !value)}>{showSources ? '收起来源' : '查看来源'}</button>
          </div>

          <div className="nebula-cluster-filter" aria-label="知识星团筛选">
            <button type="button" className={clusterFilter === 'all' ? 'active' : ''} onClick={() => setClusterFilter('all')}><i />全部星团<span>{projection.nodes.length}</span></button>
            {KNOWLEDGE_CLUSTERS.map(cluster => (
              <button
                type="button"
                key={cluster.id}
                className={clusterFilter === cluster.id ? 'active' : ''}
                style={{ '--cluster-color': cluster.color, '--cluster-rgb': cluster.rgb } as CSSProperties}
                onClick={() => setClusterFilter(current => current === cluster.id ? 'all' : cluster.id)}
              ><i />{cluster.label}<span>{clusterCounts[cluster.id]}</span></button>
            ))}
          </div>

          {showSources && (
            <div className="path-sources">
              {LEARNING_PATH_SOURCES.map(source => <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><span>{source.institution}</span><strong>{source.title}</strong></a>)}
            </div>
          )}

          <div className="path-canvas-scroll" ref={canvasScrollRef}>
            <div className="path-canvas path-nebula" style={{ width: NEBULA_WIDTH, height: NEBULA_HEIGHT }}>
              <div className="nebula-field-label"><span>KNOWLEDGE NEBULA</span><strong>全图关系可见</strong><small>箭头指向后继；悬停星体聚焦一跳关系</small></div>
              {KNOWLEDGE_CLUSTERS.map(cluster => (
                <button
                  type="button"
                  key={cluster.id}
                  className={`nebula-cluster${clusterFilter === cluster.id ? ' nebula-cluster-active' : ''}${clusterFilter !== 'all' && clusterFilter !== cluster.id ? ' nebula-cluster-muted' : ''}`}
                  style={{ left: cluster.center.x - 180, top: cluster.center.y - 125, '--cluster-color': cluster.color, '--cluster-rgb': cluster.rgb } as CSSProperties}
                  onClick={() => setClusterFilter(current => current === cluster.id ? 'all' : cluster.id)}
                >
                  <span>{cluster.label}</span><small>{cluster.caption}</small><i>{clusterCounts[cluster.id]}</i>
                </button>
              ))}
              <svg className="path-edges" viewBox={`0 0 ${NEBULA_WIDTH} ${NEBULA_HEIGHT}`} aria-hidden="true">
                <defs>
                  <marker id="path-arrow-hard" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path className="path-arrow-hard" d="M 0 0 L 10 5 L 0 10 z" /></marker>
                  <marker id="path-arrow-soft" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path className="path-arrow-soft" d="M 0 0 L 10 5 L 0 10 z" /></marker>
                  <marker id="path-arrow-co" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path className="path-arrow-co" d="M 0 0 L 10 5 L 0 10 z" /></marker>
                </defs>
                {visibleEdges.map(edge => {
                  const from = nebulaPositions.get(edge.from), to = nebulaPositions.get(edge.to)
                  if (!from || !to) return null
                  const marker = edge.kind === 'hard_prerequisite' ? 'hard' : edge.kind === 'soft_prerequisite' ? 'soft' : 'co'
                  return <path
                    key={edge.id}
                    className={`path-edge path-edge-${edge.kind}${emphasisEdgeIds.has(edge.id) ? ' path-edge-focused' : ''}${hoveredId && !hoverEdgeIds.has(edge.id) ? ' path-edge-dimmed' : ''}`}
                    d={nebulaEdgePath(from, to, edge.id)}
                    markerEnd={`url(#path-arrow-${marker})`}
                  />
                })}
              </svg>
              {visibleNodes.map(node => {
                const position = nebulaPositions.get(node.id)!
                const cluster = knowledgeCluster(position.clusterId)
                const status = projection.statuses[node.id] || 'unmarked'
                return (
                  <button
                    type="button"
                    key={node.id}
                    className={`path-node path-node-${status}${node.origin === 'personal' ? ' path-node-personal' : ''}${selected?.id === node.id ? ' path-node-selected' : ''}${hoveredId && !focusNodeIds.has(node.id) ? ' path-node-muted' : ''}${hoveredId && focusNodeIds.has(node.id) ? ' path-node-related' : ''}${node.title.length > 10 ? ' path-node-long-title' : ''}`}
                    style={{ left: position.x, top: position.y, width: position.size, height: position.size, '--cluster-color': cluster.color, '--cluster-rgb': cluster.rgb } as CSSProperties}
                    onClick={() => setSelectedId(node.id)}
                    onMouseEnter={() => setHoveredId(node.id)}
                    onMouseLeave={() => setHoveredId(undefined)}
                    title={`${node.title} · ${cluster.label} · ${PATH_STATUS_LABELS[status]}`}
                  >
                    <strong>{node.title}</strong>
                    <small>{node.origin === 'personal' ? '个人节点' : PATH_STATUS_LABELS[status]}</small>
                  </button>
                )
              })}
              {visibleNodes.length === 0 && <div className="path-empty">没有匹配节点。你可以在右侧建立一个个人节点。</div>}
            </div>
          </div>
          <div className="path-legend">
            <span><i className="legend-hard" />硬前置</span><span><i className="legend-soft" />软前置</span><span><i className="legend-co" />建议共学</span><em>节点越大，连接越多；彩色实环表示正在学习或自报状态。</em>
          </div>
        </main>

        <aside className="path-inspector">
          {selected && (
            <>
              <span className="eyebrow">{selected.origin === 'personal' ? 'PERSONAL NODE' : 'COURSE NODE'}</span>
              <h2>{selected.title}</h2>
              <p>{selected.summary}</p>
              <div className="path-node-tags"><span className="path-cluster-tag" style={{ '--cluster-color': knowledgeCluster(clusterLearningPathNode(selected)).color, '--cluster-rgb': knowledgeCluster(clusterLearningPathNode(selected)).rgb } as CSSProperties}>{knowledgeCluster(clusterLearningPathNode(selected)).label}</span>{selected.domains.map(item => <span key={item}>{item}</span>)}</div>
              <div className="path-status-picker">
                <label>我的状态</label>
                <div>{STATUS_ORDER.map(status => <button type="button" key={status} className={(projection.statuses[selected.id] || 'unmarked') === status ? 'active' : ''} onClick={() => onStatusChange(selected.id, status)}>{PATH_STATUS_LABELS[status]}</button>)}</div>
              </div>
              <section className="path-relations"><h3>来到这里</h3>{selectedPrerequisites.length ? selectedPrerequisites.map(({ edge, node }) => <button type="button" key={edge.id} onClick={() => setSelectedId(node!.id)}><span>{PATH_EDGE_LABELS[edge.kind]}</span>{node!.title}</button>) : <p>没有显式前置。</p>}</section>
              <section className="path-relations"><h3>可以继续</h3>{selectedSuccessors.length ? selectedSuccessors.map(({ edge, node }) => <button type="button" key={edge.id} onClick={() => setSelectedId(node!.id)}><span>{PATH_EDGE_LABELS[edge.kind]}</span>{node!.title}</button>) : <p>当前没有直接后继。</p>}</section>
              {selected.origin === 'personal' && <button type="button" className="path-remove-node" onClick={() => { if (globalThis.confirm(`删除个人节点“${selected.title}”？`)) onRemovePersonalNode(selected.id) }}>删除个人节点</button>}
            </>
          )}

          <section className="personal-node-form">
            <span className="eyebrow">QUICK PERSONAL NODE</span>
            <h3>补一个个人节点</h3>
            <p>适合图中没有、但你确实想学的内容。规划态还会先联网研究并给你确认提案。</p>
            <label><span>节点名称</span><input value={personalTitle} onChange={event => setPersonalTitle(event.target.value)} placeholder="例如：量子机器学习" /></label>
            <label><span>连接到</span><select value={anchorId} onChange={event => setAnchorId(event.target.value)}>{projection.nodes.filter(node => node.origin === 'official').map(node => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>
            <label><span>关系</span><select value={edgeKind} onChange={event => setEdgeKind(event.target.value as PathEdgeKind)}><option value="hard_prerequisite">硬前置</option><option value="soft_prerequisite">软前置</option><option value="co_learning">建议共学</option></select></label>
            <button type="button" onClick={addManualNode} disabled={!personalTitle.trim()}>加入我的图</button>
          </section>
        </aside>
      </div>
    </section>
  )
}
