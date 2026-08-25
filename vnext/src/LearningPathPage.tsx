import { useMemo, useState } from 'react'

import {
  LEARNING_PATH_SOURCES,
  PATH_EDGE_LABELS,
  PATH_STAGE_LABELS,
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

type Props = {
  state: LearnerPathState
  onStatusChange: (nodeId: string, status: LearnerPathStatus) => void
  onAddPersonalNode: (proposal: PersonalPathNodeProposal) => void
  onRemovePersonalNode: (nodeId: string) => void
}

const STAGES = ['foundation', 'core', 'domain', 'advanced', 'research'] as const
const STATUS_ORDER: LearnerPathStatus[] = ['unmarked', 'exploring', 'self_reported_exposed', 'self_reported_mastered']

function compact(value: string) {
  return value.toLowerCase().replace(/[\s·（）()_\-/]+/g, '')
}

export default function LearningPathPage({ state, onStatusChange, onAddPersonalNode, onRemovePersonalNode }: Props) {
  const projection = useMemo(() => projectLearnerPath(state), [state])
  const [query, setQuery] = useState('')
  const [domain, setDomain] = useState('全部')
  const [audience, setAudience] = useState('全部')
  const [selectedId, setSelectedId] = useState('agent-engineering')
  const [showSources, setShowSources] = useState(false)
  const [personalTitle, setPersonalTitle] = useState('')
  const [anchorId, setAnchorId] = useState('machine-learning')
  const [edgeKind, setEdgeKind] = useState<PathEdgeKind>('soft_prerequisite')

  const domains = useMemo(() => ['全部', ...new Set(projection.nodes.flatMap(node => node.domains))], [projection.nodes])
  const visibleNodes = useMemo(() => {
    const normalized = compact(query)
    return projection.nodes.filter(node => {
      const matchesQuery = !normalized || [node.title, ...node.aliases, ...node.domains].some(value => compact(value).includes(normalized))
      const matchesDomain = domain === '全部' || node.domains.includes(domain)
      const matchesAudience = audience === '全部' || node.audiences.includes(audience as LearningPathNode['audiences'][number])
      return matchesQuery && matchesDomain && matchesAudience
    })
  }, [projection.nodes, query, domain, audience])
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const selected = projection.nodes.find(node => node.id === selectedId) || visibleNodes[0]
  const nodeMap = new Map(projection.nodes.map(node => [node.id, node]))
  const stageRows = new Map(STAGES.map(stage => [stage, visibleNodes.filter(node => node.stage === stage).sort((a, b) => a.order - b.order || a.title.localeCompare(b.title))]))
  const positions = new Map<string, { x: number; y: number }>()
  STAGES.forEach((stage, stageIndex) => {
    stageRows.get(stage)?.forEach((node, rowIndex) => positions.set(node.id, { x: 42 + stageIndex * 226, y: 68 + rowIndex * 74 }))
  })
  const canvasHeight = Math.max(460, ...STAGES.map(stage => (stageRows.get(stage)?.length || 0) * 74 + 110))
  const selectedPrerequisites = selected
    ? projection.edges.filter(edge => edge.to === selected.id).map(edge => ({ edge, node: nodeMap.get(edge.from) })).filter(item => item.node)
    : []
  const selectedSuccessors = selected
    ? projection.edges.filter(edge => edge.from === selected.id).map(edge => ({ edge, node: nodeMap.get(edge.to) })).filter(item => item.node)
    : []

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
            <label><span>领域</span><select value={domain} onChange={event => setDomain(event.target.value)}>{domains.map(item => <option key={item}>{item}</option>)}</select></label>
            <label><span>学习阶段</span><select value={audience} onChange={event => setAudience(event.target.value)}><option>全部</option><option value="vocational">高职</option><option value="undergraduate">本科</option><option value="graduate">研究生</option><option value="self_directed">自主学习</option></select></label>
            <button type="button" onClick={() => setShowSources(value => !value)}>{showSources ? '收起来源' : '查看来源'}</button>
          </div>

          {showSources && (
            <div className="path-sources">
              {LEARNING_PATH_SOURCES.map(source => <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><span>{source.institution}</span><strong>{source.title}</strong></a>)}
            </div>
          )}

          <div className="path-canvas-scroll">
            <div className="path-canvas" style={{ height: canvasHeight }}>
              <div className="path-stage-headings">{STAGES.map(stage => <span key={stage}>{PATH_STAGE_LABELS[stage]}</span>)}</div>
              <svg className="path-edges" viewBox={`0 0 1160 ${canvasHeight}`} preserveAspectRatio="none" aria-hidden="true">
                <defs><marker id="path-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
                {projection.edges.filter(edge => visibleIds.has(edge.from) && visibleIds.has(edge.to)).map(edge => {
                  const from = positions.get(edge.from), to = positions.get(edge.to)
                  if (!from || !to) return null
                  return <line key={edge.id} className={`path-edge path-edge-${edge.kind}`} x1={from.x + 164} y1={from.y + 25} x2={to.x} y2={to.y + 25} markerEnd="url(#path-arrow)" />
                })}
              </svg>
              {visibleNodes.map(node => {
                const position = positions.get(node.id)!
                const status = projection.statuses[node.id] || 'unmarked'
                return (
                  <button
                    type="button"
                    key={node.id}
                    className={`path-node path-node-${status}${node.origin === 'personal' ? ' path-node-personal' : ''}${selected?.id === node.id ? ' path-node-selected' : ''}`}
                    style={{ left: position.x, top: position.y }}
                    onClick={() => setSelectedId(node.id)}
                  >
                    <span>{node.origin === 'personal' ? '个人' : node.domains[0]}</span>
                    <strong>{node.title}</strong>
                    <small>{PATH_STATUS_LABELS[status]}</small>
                  </button>
                )
              })}
              {visibleNodes.length === 0 && <div className="path-empty">没有匹配节点。你可以在右侧建立一个个人节点。</div>}
            </div>
          </div>
          <div className="path-legend">
            <span><i className="legend-hard" />硬前置</span><span><i className="legend-soft" />软前置</span><span><i className="legend-co" />建议共学</span>
          </div>
        </main>

        <aside className="path-inspector">
          {selected && (
            <>
              <span className="eyebrow">{selected.origin === 'personal' ? 'PERSONAL NODE' : 'COURSE NODE'}</span>
              <h2>{selected.title}</h2>
              <p>{selected.summary}</p>
              <div className="path-node-tags">{selected.domains.map(item => <span key={item}>{item}</span>)}</div>
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
