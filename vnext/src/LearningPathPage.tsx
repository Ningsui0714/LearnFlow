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
  KNOWLEDGE_STAGE_COLUMNS,
  NEBULA_WIDTH,
  clusterLearningPathNode,
  knowledgeCluster,
  layoutKnowledgeClusters,
  layoutLearningPathNebula,
  nebulaHeight,
  nebulaEdgePath,
  traceLearningPath,
  type KnowledgeClusterId,
} from './learning-path-nebula'

type Props = {
  state: LearnerPathState
  onStatusChange: (nodeId: string, status: LearnerPathStatus) => void
  onAddPersonalNode: (proposal: PersonalPathNodeProposal) => void
  onRemovePersonalNode: (nodeId: string) => void
  onArchivePlan: (planId: string) => void
}

const STATUS_ORDER: LearnerPathStatus[] = ['unmarked', 'exploring', 'self_reported_exposed', 'self_reported_mastered']

function compact(value: string) {
  return value.toLowerCase().replace(/[\s·（）()_\-/]+/g, '')
}

export default function LearningPathPage({ state, onStatusChange, onAddPersonalNode, onRemovePersonalNode, onArchivePlan }: Props) {
  const projection = useMemo(() => projectLearnerPath(state), [state])
  const canvasScrollRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [clusterFilter, setClusterFilter] = useState<'all' | KnowledgeClusterId>('all')
  const [audience, setAudience] = useState('全部')
  const [selectedId, setSelectedId] = useState('agent-engineering')
  const [hoveredId, setHoveredId] = useState<string>()
  const [focusPinned, setFocusPinned] = useState(false)
  const [showSources, setShowSources] = useState(false)
  const [personalTitle, setPersonalTitle] = useState('')
  const [anchorId, setAnchorId] = useState('machine-learning')
  const [edgeKind, setEdgeKind] = useState<PathEdgeKind>('soft_prerequisite')

  const nebulaPositions = useMemo(() => layoutLearningPathNebula(projection.nodes, projection.edges), [projection.nodes, projection.edges])
  const clusterBounds = useMemo(() => layoutKnowledgeClusters(projection.nodes), [projection.nodes])
  const nebulaCanvasHeight = useMemo(() => nebulaHeight(projection.nodes), [projection.nodes])
  const visibleNodes = useMemo(() => {
    const normalized = compact(query)
    return projection.nodes.filter(node => {
      const matchesQuery = !normalized || [node.title, ...node.aliases, ...node.domains].some(value => compact(value).includes(normalized))
      const matchesCluster = clusterFilter === 'all' || clusterLearningPathNode(node) === clusterFilter
      const matchesAudience = audience === '全部' || node.audiences.includes(audience as LearningPathNode['audiences'][number])
      return matchesQuery && matchesCluster && matchesAudience
    })
  }, [projection.nodes, query, clusterFilter, audience])
  const visibleIds = useMemo(() => new Set(visibleNodes.map(node => node.id)), [visibleNodes])
  const selected = projection.nodes.find(node => node.id === selectedId && visibleIds.has(node.id)) || visibleNodes[0]
  const nodeMap = useMemo(() => new Map(projection.nodes.map(node => [node.id, node])), [projection.nodes])
  const visibleEdges = useMemo(
    () => projection.edges.filter(edge => visibleIds.has(edge.from) && visibleIds.has(edge.to)),
    [projection.edges, visibleIds],
  )
  const focusId = hoveredId && visibleIds.has(hoveredId) ? hoveredId : focusPinned ? selected?.id : undefined
  const focusTrace = useMemo(
    () => focusId ? traceLearningPath(visibleEdges, focusId, !hoveredId && focusPinned) : undefined,
    [focusId, focusPinned, hoveredId, visibleEdges],
  )
  const selectedEdgeIds = useMemo(() => new Set(selected
    ? visibleEdges.filter(edge => edge.from === selected.id || edge.to === selected.id).map(edge => edge.id)
    : []), [selected, visibleEdges])
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
  const activePlan = projection.activePlan
  const planRouteNodeIds = useMemo(() => new Set(activePlan?.routeNodeIds || []), [activePlan])
  const planMilestoneNodeIds = useMemo(() => new Set(activePlan?.milestoneNodeIds || []), [activePlan])
  const planTargetNodeIds = useMemo(() => new Set(activePlan?.targetNodeIds || []), [activePlan])
  const planEdgeIds = useMemo(() => new Set(activePlan
    ? projection.edges.filter(edge => planRouteNodeIds.has(edge.from) && planRouteNodeIds.has(edge.to)).map(edge => edge.id)
    : []), [activePlan, planRouteNodeIds, projection.edges])
  const planTargetTitles = activePlan?.targetNodeIds.map(nodeId => nodeMap.get(nodeId)?.title || nodeId) || []

  useEffect(() => {
    if (!selected || !canvasScrollRef.current) return
    const position = nebulaPositions.get(selected.id)
    if (!position) return
    const viewport = canvasScrollRef.current
    const left = Math.max(0, position.x + position.width / 2 - viewport.clientWidth / 2)
    const top = Math.max(0, position.y + position.height / 2 - viewport.clientHeight / 2)
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

  const selectAndFocus = (nodeId: string) => {
    setSelectedId(nodeId)
    setFocusPinned(true)
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

      {activePlan && (
        <section className="path-active-plan" aria-label="当前长期学习路径">
          <div>
            <span>ACTIVE LEARNING PLAN · v{activePlan.revision}</span>
            <strong>{activePlan.title}</strong>
            <p>{activePlan.objective}</p>
          </div>
          <dl>
            <div><dt>周期</dt><dd>{activePlan.horizon}</dd></div>
            <div><dt>目标</dt><dd>{planTargetTitles.join('、')}</dd></div>
            <div><dt>路线</dt><dd>{activePlan.routeNodeIds.length} 节点 · {activePlan.milestoneNodeIds.length} 里程碑</dd></div>
          </dl>
          <button type="button" onClick={() => { if (globalThis.confirm(`归档长期路径“${activePlan.title}”？历史记录会保留。`)) onArchivePlan(activePlan.id) }}>归档这条路径</button>
        </section>
      )}

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

          <div className="path-canvas-toolbar">
            <div><strong>学习星图</strong><span>从左到右：基础 → 核心 → 方向 → 高阶 → 产出</span></div>
            <div><button type="button" className={!focusPinned ? 'active' : ''} onClick={() => setFocusPinned(false)}>全图</button><button type="button" className={focusPinned ? 'active' : ''} disabled={!selected} onClick={() => setFocusPinned(true)}>聚焦路径</button></div>
          </div>
          <div className="path-canvas-scroll" ref={canvasScrollRef}>
            <div className="path-canvas path-nebula" style={{ width: NEBULA_WIDTH, height: nebulaCanvasHeight }}>
              <div className="nebula-field-label"><span>LEARNING CONSTELLATION</span><strong>语义成团，阶段成路</strong><small>悬停看一跳 · 点击固定完整前置与后继链</small></div>
              {KNOWLEDGE_STAGE_COLUMNS.map(stage => (
                <div className="nebula-stage-column" key={stage.id} style={{ left: stage.x - 12, height: nebulaCanvasHeight - 18 }}>
                  <span>{stage.label}</span><small>{stage.caption}</small>
                </div>
              ))}
              {KNOWLEDGE_CLUSTERS.map(cluster => (
                <button
                  type="button"
                  key={cluster.id}
                  className={`nebula-cluster${clusterFilter === cluster.id ? ' nebula-cluster-active' : ''}${clusterFilter !== 'all' && clusterFilter !== cluster.id ? ' nebula-cluster-muted' : ''}`}
                  style={{ left: clusterBounds.get(cluster.id)!.x, top: clusterBounds.get(cluster.id)!.y, width: clusterBounds.get(cluster.id)!.width, height: clusterBounds.get(cluster.id)!.height, '--cluster-color': cluster.color, '--cluster-rgb': cluster.rgb } as CSSProperties}
                  onClick={() => { setClusterFilter(current => current === cluster.id ? 'all' : cluster.id); setFocusPinned(false) }}
                >
                  <span>{cluster.label}</span><small>{cluster.caption}</small><i>{clusterCounts[cluster.id]}</i>
                </button>
              ))}
              <svg className="path-edges" viewBox={`0 0 ${NEBULA_WIDTH} ${nebulaCanvasHeight}`} aria-hidden="true">
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
                    className={`path-edge path-edge-${edge.kind}${planEdgeIds.has(edge.id) ? ' path-edge-plan' : ''}${(focusTrace?.edgeIds.has(edge.id) || !focusId && selectedEdgeIds.has(edge.id)) ? ' path-edge-focused' : ''}${focusId && !focusTrace?.edgeIds.has(edge.id) && !planEdgeIds.has(edge.id) ? ' path-edge-dimmed' : ''}`}
                    d={nebulaEdgePath(from, to, edge.id)}
                    markerEnd={`url(#path-arrow-${marker})`}
                  />
                })}
              </svg>
              {visibleNodes.map(node => {
                const position = nebulaPositions.get(node.id)!
                const cluster = knowledgeCluster(position.clusterId)
                const status = projection.statuses[node.id] || 'unmarked'
                const planRole = planTargetNodeIds.has(node.id) ? 'target' : planMilestoneNodeIds.has(node.id) ? 'milestone' : planRouteNodeIds.has(node.id) ? 'route' : ''
                return (
                  <button
                    type="button"
                    key={node.id}
                    className={`path-node path-node-${status}${node.origin === 'personal' ? ' path-node-personal' : ''}${planRole ? ` path-node-plan-${planRole}` : ''}${selected?.id === node.id ? ' path-node-selected' : ''}${focusId && !focusTrace?.nodes.has(node.id) && !planRole ? ' path-node-muted' : ''}${focusTrace?.upstream.has(node.id) && node.id !== focusId ? ' path-node-upstream' : ''}${focusTrace?.downstream.has(node.id) && node.id !== focusId ? ' path-node-downstream' : ''}${node.title.length > 10 ? ' path-node-long-title' : ''}`}
                    style={{ left: position.x, top: position.y, width: position.width, height: position.height, '--cluster-color': cluster.color, '--cluster-rgb': cluster.rgb } as CSSProperties}
                    onClick={() => selectAndFocus(node.id)}
                    onMouseEnter={() => setHoveredId(node.id)}
                    onMouseLeave={() => setHoveredId(undefined)}
                    title={`${node.title} · ${cluster.label} · ${planRole === 'target' ? '规划目标' : planRole === 'milestone' ? '路线里程碑' : planRole === 'route' ? '规划路线' : PATH_STATUS_LABELS[status]}`}
                  >
                    <strong>{node.title}</strong>
                    <small>{planRole === 'target' ? '◎ 规划目标' : planRole === 'milestone' ? '◆ 路线里程碑' : planRole === 'route' ? '· 规划路线' : node.origin === 'personal' ? '个人节点' : PATH_STATUS_LABELS[status]}</small>
                  </button>
                )
              })}
              {visibleNodes.length === 0 && <div className="path-empty">没有匹配节点。你可以在右侧建立一个个人节点。</div>}
            </div>
          </div>
          <div className="path-legend">
            <span><i className="legend-hard" />硬前置</span><span><i className="legend-soft" />软前置</span><span><i className="legend-co" />建议共学</span><span><i className="legend-plan" />我的长期路线</span><em>聚焦时：蓝色是来到这里的前置，绿色是从这里继续的后继。</em>
          </div>
        </main>

        <aside className="path-inspector">
          {selected && (
            <>
              <span className="eyebrow">{selected.origin === 'personal' ? 'PERSONAL NODE' : 'COURSE NODE'}</span>
              <h2>{selected.title}</h2>
              <p>{selected.summary}</p>
              <div className="path-node-tags"><span className="path-cluster-tag" style={{ '--cluster-color': knowledgeCluster(clusterLearningPathNode(selected)).color, '--cluster-rgb': knowledgeCluster(clusterLearningPathNode(selected)).rgb } as CSSProperties}>{knowledgeCluster(clusterLearningPathNode(selected)).label}</span>{selected.domains.map(item => <span key={item}>{item}</span>)}</div>
              {activePlan && planRouteNodeIds.has(selected.id) && (
                <div className={`path-plan-role path-plan-role-${planTargetNodeIds.has(selected.id) ? 'target' : planMilestoneNodeIds.has(selected.id) ? 'milestone' : 'route'}`}>
                  <span>{planTargetNodeIds.has(selected.id) ? '长期规划目标' : planMilestoneNodeIds.has(selected.id) ? '长期路线里程碑' : '长期规划路线节点'}</span>
                  <p>属于“{activePlan.title}”。路线是规划导航，不代表已经掌握。</p>
                </div>
              )}
              <div className="path-status-picker">
                <label>我的状态</label>
                <div>{STATUS_ORDER.map(status => <button type="button" key={status} className={(projection.statuses[selected.id] || 'unmarked') === status ? 'active' : ''} onClick={() => onStatusChange(selected.id, status)}>{PATH_STATUS_LABELS[status]}</button>)}</div>
              </div>
              <button type="button" className="path-focus-action" onClick={() => setFocusPinned(value => !value)}>{focusPinned ? '返回完整星图' : '在星图中聚焦完整路径'}</button>
              <section className="path-relations"><h3>来到这里</h3>{selectedPrerequisites.length ? selectedPrerequisites.map(({ edge, node }) => <button type="button" key={edge.id} onClick={() => selectAndFocus(node!.id)}><span>{PATH_EDGE_LABELS[edge.kind]}</span>{node!.title}</button>) : <p>没有显式前置。</p>}</section>
              <section className="path-relations"><h3>可以继续</h3>{selectedSuccessors.length ? selectedSuccessors.map(({ edge, node }) => <button type="button" key={edge.id} onClick={() => selectAndFocus(node!.id)}><span>{PATH_EDGE_LABELS[edge.kind]}</span>{node!.title}</button>) : <p>当前没有直接后继。</p>}</section>
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
