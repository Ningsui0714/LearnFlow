import { useState, type CSSProperties } from 'react'
import {
  defineLearnFlowPluginClient,
  pluginObjectDragProps,
  type PluginToolRendererProps,
} from '../../src/PluginToolResultView.tsx'
import { ROLE_CAPABILITY_PLUGIN, ROLE_RENDERERS } from './shared.ts'
import './plugin.css'

type RecordValue = Record<string, any>

function dataOf(object: PluginToolRendererProps['objects'][number]) {
  const value = object.value as RecordValue
  return (value.data || {}) as RecordValue
}

function categoryOf(object: PluginToolRendererProps['objects'][number]) {
  const value = object.value as RecordValue
  return String(value.category || dataOf(object).type || dataOf(object).kind || 'object')
}

function semanticRingOf(object: PluginToolRendererProps['objects'][number]) {
  const explicit = Number(dataOf(object).ring)
  if (Number.isInteger(explicit) && explicit >= 0) return explicit
  const category = categoryOf(object)
  if (category === 'market_role') return 0
  if (['industry_chain_node', 'job_family', 'occupation_standard', 'related_role'].includes(category)) return 1
  if (category === 'task') return 2
  if (category === 'capability') return 3
  if (category === 'capability_unit') return 4
  if (category === 'knowledge_skill') return 5
  return null
}

function snapshotOf(result: PluginToolRendererProps['result']) {
  const payload = (result.payload || {}) as RecordValue
  return (payload.snapshot || {}) as RecordValue
}

const palette: Record<string, string> = {
  market_role: '#315947', industry_chain_node: '#4f7280', job_family: '#4f7280', occupation_standard: '#4f7280', related_role: '#4f7280',
  task: '#b96649', capability: '#806692', capability_unit: '#9a82aa', knowledge_skill: '#4d8060',
  scenario: '#9b684e', event: '#ba744f', actor: '#55758a', work_object: '#887656', artifact: '#4c796e',
  tool_system: '#687493', quality_criterion: '#64804f', exception_risk: '#a25b56', risk: '#a25b56', decision: '#8d7040',
}

function colorFor(category: string) {
  return palette[category] || '#68766f'
}

function SnapshotBadge({ result }: { result: PluginToolRendererProps['result'] }) {
  const snapshot = snapshotOf(result)
  return (
    <div className="role-plugin-snapshot">
      <span>固定快照</span>
      <strong>{String(snapshot.roleTitle || '岗位包')}</strong>
      <small>v{String(snapshot.packageVersion || '—')} · {String(snapshot.snapshotAsOf || '—')}</small>
    </div>
  )
}

function SnapshotViewTabs<T extends string>({ active, views, onChange }: {
  active: T
  views: Array<{ id: T; label: string }>
  onChange: (view: T) => void
}) {
  return <nav className="role-plugin-view-tabs" aria-label="切换岗位快照展示">
    {views.map(view => <button
      key={view.id}
      type="button"
      aria-pressed={active === view.id}
      onClick={() => onChange(view.id)}
    >{view.label}</button>)}
  </nav>
}

function interactiveObjectProps(props: PluginToolRendererProps, object: PluginToolRendererProps['objects'][number]) {
  return {
    ...pluginObjectDragProps(object),
    onDoubleClick: () => props.onReference?.(object),
  }
}

function FollowActions({ props, objectId, label }: { props: PluginToolRendererProps; objectId: string; label: string }) {
  const object = props.objects.find(item => item.objectId === objectId)
  if (!props.onPrompt && !props.onReference) return null
  const snapshot = snapshotOf(props.result)
  const suffix = `（固定快照 ${String(snapshot.snapshotId || '')}，对象 ${objectId}）`
  return <div className="role-plugin-actions">
    {props.onReference && object && <button type="button" onClick={() => props.onReference?.(object)}>引用到输入框</button>}
    {props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`详细解释“${label}”${suffix}`)}>继续解释</button>}
    {props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`展示“${label}”与其他岗位对象的关系${suffix}`)}>查看关系</button>}
    {props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`核对“${label}”的证据和适用边界${suffix}`)}>查看证据</button>}
  </div>
}

function ObjectCardGrid({ props, objects = props.objects.filter(object => object.objectType === 'role_object') }: {
  props: PluginToolRendererProps
  objects?: readonly PluginToolRendererProps['objects'][number][]
}) {
  return <div className="role-plugin-card-grid">
    {objects.map(object => {
      const data = dataOf(object)
      const category = categoryOf(object)
      return <article
        key={object.objectId}
        style={{ '--role-accent': colorFor(category) } as CSSProperties}
        {...interactiveObjectProps(props, object)}
      >
        <header><span>{category}</span><small>{String(data.lifecycle || data.knowledgeState || 'snapshot')}</small></header>
        <strong>{object.label}</strong>
        <p>{String(data.summary || '')}</p>
        <footer><code>{object.objectId}</code>{typeof data.confidence === 'number' && <b>{Math.round(data.confidence * 100)}%</b>}</footer>
        <FollowActions props={props} objectId={object.objectId} label={object.label} />
      </article>
    })}
  </div>
}

type RadarRing = { ring: number; label: string; objectIds: string[]; total?: number }

function RoleDimensionRadar({ props, radar }: { props: PluginToolRendererProps; radar: RecordValue }) {
  const [selectedId, setSelectedId] = useState(String(radar.rootId || ''))
  const objects = new Map(props.objects.filter(object => object.objectType === 'role_object').map(object => [object.objectId, object]))
  const relations = props.objects.filter(object => object.objectType === 'role_relation')
  const rings = ((radar.rings || []) as RadarRing[]).filter(ring => ring.objectIds.some(id => objects.has(id)))
  const rootId = String(radar.rootId || rings.find(ring => ring.ring === 0)?.objectIds[0] || '')
  const width = 820
  const height = 580
  const center = { x: width / 2, y: height / 2 }
  const maxRadius = 242
  const positions = new Map<string, { x: number; y: number; ring: number }>()
  rings.forEach(ring => {
    const visibleIds = ring.objectIds.filter(id => objects.has(id))
    visibleIds.forEach((objectId, index) => {
      if (ring.ring === 0) positions.set(objectId, { ...center, ring: 0 })
      else {
        const radius = maxRadius * (.28 + ring.ring * .14)
        const angle = -Math.PI / 2 + Math.PI * 2 * index / Math.max(visibleIds.length, 1) + (ring.ring % 2 ? .08 : 0)
        positions.set(objectId, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius, ring: ring.ring })
      }
    })
  })
  const visibleIds = new Set(positions.keys())
  const selected = objects.get(selectedId) || objects.get(rootId)
  return <div className="role-plugin-dimension-radar">
    <header><strong>岗位中心语义雷达</strong><span>{Math.max(0, rings.length - 1)} 个维度 · {Math.max(0, visibleIds.size - 1)} 个外围节点</span></header>
    <div className="role-plugin-radar-stage" role="img" aria-label={`以${objects.get(rootId)?.label || '岗位'}为中心，按岗位边界、任务、能力、能力单元和知识技能向外展开`}>
      <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {rings.filter(ring => ring.ring > 0).map(ring => {
          const radius = maxRadius * (.28 + ring.ring * .14)
          return <circle key={ring.ring} cx={center.x} cy={center.y} r={radius} className={`ring ring-${ring.ring}`} />
        })}
        <g className="role-plugin-radar-edges">{relations.map(relationObject => {
          const relation = dataOf(relationObject)
          const source = positions.get(String(relation.source || ''))
          const target = positions.get(String(relation.target || ''))
          if (!source || !target) return null
          return <line key={relationObject.objectId} x1={source.x} y1={source.y} x2={target.x} y2={target.y}><title>{String(relation.type || '')}</title></line>
        })}</g>
      </svg>
      {rings.filter(ring => ring.ring > 0).map(ring => <span key={ring.ring} className={`role-plugin-ring-label ring-${ring.ring}`}>{ring.label}<small>{ring.objectIds.filter(id => objects.has(id)).length}{ring.total && ring.total > ring.objectIds.length ? ` / ${ring.total}` : ''}</small></span>)}
      {[...positions].map(([objectId, position]) => {
        const object = objects.get(objectId)
        if (!object) return null
        const category = categoryOf(object)
        return <button
          key={objectId}
          type="button"
          className={`role-plugin-radar-node ${position.ring === 0 ? 'root' : ''} ${selected?.objectId === objectId ? 'selected' : ''}`}
          style={{ left: `${position.x / width * 100}%`, top: `${position.y / height * 100}%`, '--role-accent': colorFor(category) } as CSSProperties}
          aria-label={`${object.label}，${category}`}
          {...interactiveObjectProps(props, object)}
          onClick={() => setSelectedId(objectId)}
        ><i /><span>{object.label}</span></button>
      })}
    </div>
    {selected && <article className="role-plugin-radar-selection" style={{ '--role-accent': colorFor(categoryOf(selected)) } as CSSProperties} {...interactiveObjectProps(props, selected)}>
      <span>{categoryOf(selected)} · 第 {semanticRingOf(selected) ?? '—'} 环</span><strong>{selected.label}</strong><p>{String(dataOf(selected).summary || '')}</p>
      <FollowActions props={props} objectId={selected.objectId} label={selected.label} />
    </article>}
    <footer>节点可点击查看、双击引用，也可直接拖入下方输入框。环表示岗位语义维度，不表示分数高低。</footer>
  </div>
}

function RoleOverview(props: PluginToolRendererProps) {
  const [view, setView] = useState<'overview' | 'radar' | 'cards'>('overview')
  const payload = (props.result.payload || {}) as RecordValue
  const sections = payload.sections || {}
  const nodes = new Map(props.objects.filter(object => object.objectType === 'role_object').map(object => [object.objectId, object]))
  const root = nodes.get(String(payload.rootId || ''))
  const inferredRings = [...nodes.values()].reduce<Map<number, string[]>>((groups, object) => {
    const ring = semanticRingOf(object)
    if (ring === null) return groups
    groups.set(ring, [...(groups.get(ring) || []), object.objectId])
    return groups
  }, new Map())
  const radar = (payload.radar || {
    rootId: payload.rootId,
    rings: [...inferredRings].sort(([left], [right]) => left - right).map(([ring, objectIds]) => ({
      ring,
      objectIds,
      label: ({ 0: '岗位中心', 1: '岗位身份与边界', 2: '典型任务', 3: '抽象能力', 4: '能力单元', 5: '知识技能' } as Record<number, string>)[ring] || `第 ${ring} 层`,
    })),
  }) as RecordValue
  const renderSection = (title: string, ids: string[], empty: string) => <section className="role-plugin-overview-section">
    <header><strong>{title}</strong><small>{ids.length}</small></header>
    <div>{ids.map(id => nodes.get(id)).filter(Boolean).map(object => {
      const data = dataOf(object!)
      return <article key={object!.objectId} style={{ '--role-accent': colorFor(categoryOf(object!)) } as CSSProperties} {...interactiveObjectProps(props, object!)}>
        <span>{categoryOf(object!)}</span><strong>{object!.label}</strong><p>{String(data.summary || '')}</p>
        <FollowActions props={props} objectId={object!.objectId} label={object!.label} />
      </article>
    })}</div>
    {!ids.length && <p>{empty}</p>}
  </section>
  return <section className="role-plugin-view role-plugin-overview" aria-label="岗位全景">
    <SnapshotBadge result={props.result} />
    <SnapshotViewTabs active={view} views={[{ id: 'overview', label: '岗位全景' }, { id: 'radar', label: '能力雷达' }, { id: 'cards', label: '对象卡片' }]} onChange={setView} />
    {view === 'overview' && <>
      {root && <article className="role-plugin-identity" {...interactiveObjectProps(props, root)}><span>岗位定位</span><strong>{root.label}</strong><p>{String(dataOf(root).summary || '')}</p><FollowActions props={props} objectId={root.objectId} label={root.label} /></article>}
      <div className="role-plugin-overview-grid">
        {renderSection('典型任务', sections.tasks || [], '当前视图没有任务对象。')}
        {renderSection('核心能力', sections.capabilities || [], '当前视图没有能力对象。')}
        {renderSection('工作场景', sections.scenarios || [], '当前视图没有场景对象。')}
        {renderSection('相邻岗位', sections.relatedRoles || [], '当前视图没有相邻岗位。')}
      </div>
    </>}
    {view === 'radar' && <RoleDimensionRadar props={props} radar={radar} />}
    {view === 'cards' && <ObjectCardGrid props={props} />}
    <p className="role-plugin-boundary">{String(payload.grounding?.requiredDisclosure || '')}</p>
  </section>
}

function CapabilityRadar(props: PluginToolRendererProps) {
  const [view, setView] = useState<'radar' | 'cards'>('radar')
  const payload = (props.result.payload || {}) as RecordValue
  return <section className="role-plugin-view role-plugin-radar" aria-label="岗位能力雷达">
    <SnapshotBadge result={props.result} />
    <SnapshotViewTabs active={view} views={[{ id: 'radar', label: '能力雷达' }, { id: 'cards', label: '能力卡片' }]} onChange={setView} />
    {view === 'radar' ? <RoleDimensionRadar props={props} radar={payload} /> : <ObjectCardGrid props={props} />}
    <p className="role-plugin-boundary">{String(payload.boundary || '')}</p>
  </section>
}

function RoleCards(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  return (
    <section className="role-plugin-view role-plugin-cards" aria-label="岗位对象卡片">
      <SnapshotBadge result={props.result} />
      <ObjectCardGrid props={props} />
      {payload.omittedIds?.length ? <p className="role-plugin-warning">未找到：{payload.omittedIds.join('、')}</p> : null}
      {payload.coverage?.omitted ? <p className="role-plugin-boundary">结果有界：另有 {payload.coverage.omitted} 个匹配对象未展示。</p> : null}
    </section>
  )
}

function RoleGraph(props: PluginToolRendererProps) {
  const [expanded, setExpanded] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const allNodes = props.objects.filter(object => object.objectType === 'role_object')
  const relationObjects = props.objects.filter(object => object.objectType === 'role_relation')
  const payload = (props.result.payload || {}) as RecordValue
  const rootId = String(payload.rootId || allNodes[0]?.objectId || '')
  const nodeLimit = expanded ? allNodes.length : Math.min(16, allNodes.length)
  const nodeObjects = [allNodes.find(object => object.objectId === rootId), ...allNodes.filter(object => object.objectId !== rootId)].filter(Boolean).slice(0, nodeLimit) as typeof allNodes
  const visibleIds = new Set(nodeObjects.map(object => object.objectId))
  const visibleRelations = relationObjects.filter(object => {
    const relation = dataOf(object)
    return visibleIds.has(String(relation.source)) && visibleIds.has(String(relation.target))
  }).slice(0, expanded ? relationObjects.length : 28)
  const width = 760
  const height = expanded ? 560 : 430
  const center = { x: width / 2, y: height / 2 }
  const positions = new Map<string, { x: number; y: number }>()
  const ordered = [...nodeObjects].sort((left, right) => left.objectId === rootId ? -1 : right.objectId === rootId ? 1 : left.objectId.localeCompare(right.objectId))
  ordered.forEach((object, index) => {
    if (object.objectId === rootId) positions.set(object.objectId, center)
    else {
      const ringIndex = index - (ordered[0]?.objectId === rootId ? 1 : 0)
      const count = Math.max(1, ordered.length - 1)
      const angle = (Math.PI * 2 * ringIndex) / count - Math.PI / 2
      const band = ringIndex < 8 ? 0 : ringIndex < 18 ? 1 : 2
      const radius = expanded ? [118, 190, 252][band] : (ringIndex < 8 ? 112 : 176)
      positions.set(object.objectId, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius })
    }
  })
  const selected = allNodes.find(object => object.objectId === (selectedId || rootId))
  const selectedRelations = relationObjects.filter(object => {
    const relation = dataOf(object)
    return String(relation.source) === selected?.objectId || String(relation.target) === selected?.objectId
  })
  return (
    <section className="role-plugin-view role-plugin-graph" aria-label="岗位关系图">
      <SnapshotBadge result={props.result} />
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${nodeObjects.length} 个岗位对象的关系图`}>
        <g className="role-plugin-graph-edges">
          {visibleRelations.map(object => {
            const relation = dataOf(object)
            const source = positions.get(String(relation.source))
            const target = positions.get(String(relation.target))
            if (!source || !target) return null
            return <line key={object.objectId} x1={source.x} y1={source.y} x2={target.x} y2={target.y}><title>{String(relation.type || '')}</title></line>
          })}
        </g>
        <g className="role-plugin-graph-nodes">
          {ordered.map(object => {
            const position = positions.get(object.objectId)!
            const category = categoryOf(object)
            const root = object.objectId === rootId
            return <g key={object.objectId} transform={`translate(${position.x} ${position.y})`}><circle r={root ? 34 : 23} fill={colorFor(category)} /><text y={root ? 49 : 37}>{object.label.length > 14 ? `${object.label.slice(0, 13)}…` : object.label}</text><title>{object.label} · {object.objectId}</title></g>
          })}
        </g>
      </svg>
      <div className="role-plugin-graph-toolbar"><span>显示 {nodeObjects.length}/{allNodes.length} 个节点 · {visibleRelations.length}/{relationObjects.length} 条关系</span>{allNodes.length > 16 && <button type="button" onClick={() => setExpanded(value => !value)}>{expanded ? '收起图谱' : `展示全部 ${allNodes.length} 个节点`}</button>}</div>
      <div className="role-plugin-graph-focus">{ordered.map(object => <button
        key={object.objectId}
        type="button"
        {...interactiveObjectProps(props, object)}
        aria-pressed={selected?.objectId === object.objectId}
        onClick={() => setSelectedId(object.objectId)}
      >{object.label}</button>)}</div>
      {selected && <article className="role-plugin-graph-inspector" {...interactiveObjectProps(props, selected)}>
        <header><span>{categoryOf(selected)}</span><strong>{selected.label}</strong><small>{selectedRelations.length} 条直接关系</small></header>
        <p>{String(dataOf(selected).summary || '')}</p>
        <div>{selectedRelations.map(object => {
          const relation = dataOf(object)
          const outgoing = String(relation.source) === selected.objectId
          const otherId = String(outgoing ? relation.target : relation.source)
          const other = allNodes.find(node => node.objectId === otherId)
          return <button key={object.objectId} type="button" onClick={() => other && setSelectedId(other.objectId)}>
            <small>{outgoing ? '→' : '←'} {String(relation.type || 'relation')}</small><strong>{other?.label || otherId}</strong>
          </button>
        })}</div>
        <FollowActions props={props} objectId={selected.objectId} label={selected.label} />
      </article>}
      <p className="role-plugin-legend">关系类型：{[...new Set(visibleRelations.map(object => String(dataOf(object).type || 'relation')))].join(' · ')}</p>
      {payload.truncated && <p className="role-plugin-boundary">子图达到本次节点上限；这是有界投影，不是完整岗位包。</p>}
    </section>
  )
}

function CandidateHeader({ value }: { value: RecordValue }) {
  return <header className="role-plugin-candidate-header"><span>{String(value.status || 'candidate')}</span><strong>{String(value.roleTitle || '岗位候选')}</strong><code>{String(value.artifactId || '')}</code></header>
}

function ColdStartCandidate(props: PluginToolRendererProps) {
  const object = props.objects.find(item => item.objectType === 'role_build_candidate')
  const value = (object?.value || {}) as RecordValue
  const data = (value.data || {}) as RecordValue
  const stages = (data.stages || []) as RecordValue[]
  return <section className="role-plugin-view role-plugin-candidate" aria-label="岗位冷启动候选">
    <CandidateHeader value={value} />
    <div className="role-plugin-candidate-summary"><span>用途</span><strong>{String(data.purpose || '—')}</strong><span>市场 / 受众</span><strong>{String(data.market || '—')} · {(data.audiences || []).join('、') || '待确认'}</strong><span>来源输入</span><strong>{(data.sourceBriefs || []).length} 条</strong></div>
    <ol className="role-plugin-workflow-stages">{stages.map((stage, index) => <li key={String(stage.id)} data-status={String(stage.status)}><i>{index + 1}</i><span><strong>{String(stage.title)}</strong><small>{String(stage.output)}</small></span><b>{String(stage.status)}</b></li>)}</ol>
    {!(data.sourceBriefs || []).length && <p className="role-plugin-warning">当前没有真实来源，只建立了构建合同。继续提供 JD、职业标准、技术文档或脱敏工作证据后，才能进入证据抽取。</p>}
    <details><summary>任务屏障与发布门槛</summary><div className="role-plugin-gates">{Object.entries(data.gates || {}).map(([key, items]) => <section key={key}><strong>{key}</strong><ul>{(items as string[]).map(item => <li key={item}>{item}</li>)}</ul></section>)}</div></details>
    {object && <div className="role-plugin-actions"><button type="button" onClick={() => props.onReference?.(object)}>引用候选合同</button>{props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`继续完善“${value.roleTitle}”冷启动候选：请先核对来源与岗位边界（候选 ${value.artifactId}）`)}>继续补资料</button>}</div>}
    <p className="role-plugin-boundary">候选合同不是岗位事实，也不是已创建或已发布的快照。</p>
  </section>
}

function IterationCandidate(props: PluginToolRendererProps) {
  const object = props.objects.find(item => item.objectType === 'role_iteration_candidate')
  const value = (object?.value || {}) as RecordValue
  const data = (value.data || {}) as RecordValue
  return <section className="role-plugin-view role-plugin-candidate" aria-label="岗位迭代候选">
    <CandidateHeader value={value} />
    <div className="role-plugin-base-lock"><span>固定基线</span><strong>{String(value.baseSnapshotId || '—')}</strong><code>{String(value.expectedRootHash || '').slice(0, 18)}…</code></div>
    <div className="role-plugin-candidate-summary"><span>目标</span><strong>{String(data.objective || '—')}</strong><span>发起方式</span><strong>{String(data.initiativeProfile || 'co_guided')}</strong><span>范围</span><strong>{(data.targetIds || []).length ? `${data.targetIds.length} 个目标 / ${(data.neighborhoodIds || []).length} 个邻域对象` : '全局检查'}</strong></div>
    <section className="role-plugin-patch-list"><header><strong>候选 patch</strong><small>{(data.proposedChanges || []).length} 条</small></header>{(data.proposedChanges || []).length ? (data.proposedChanges || []).map((change: RecordValue) => <article key={String(change.id)}><span>{String(change.status)}</span><p>{String(change.statement)}</p></article>) : <p>尚无候选变更；需要先补充具体目标、证据或修改意图。</p>}</section>
    <ol className="role-plugin-workflow-stages">{(data.workItems || []).map((item: RecordValue, index: number) => <li key={String(item.id)} data-status={String(item.status)}><i>{index + 1}</i><span><strong>{String(item.title)}</strong><small>{item.deterministic ? '确定性阶段' : '候选研究阶段'}</small></span><b>{String(item.status)}</b></li>)}</ol>
    <details><summary>验收与停止条件</summary><div className="role-plugin-gates"><section><strong>acceptance</strong><ul>{(data.acceptancePolicy || []).map((item: string) => <li key={item}>{item}</li>)}</ul></section><section><strong>stop</strong><ul>{(data.stopConditions || []).map((item: string) => <li key={item}>{item}</li>)}</ul></section></div></details>
    {object && <div className="role-plugin-actions"><button type="button" onClick={() => props.onReference?.(object)}>引用迭代候选</button>{props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`审查并继续细化岗位迭代候选 ${value.artifactId}；基线必须保持 ${value.baseSnapshotId}`)}>继续细化</button>}</div>}
    <p className="role-plugin-boundary">原快照保持不变。只有独立验证通过且产生 meaningful diff，后续持久化能力才可创建后继快照。</p>
  </section>
}

function ProcessForest(props: PluginToolRendererProps) {
  const nodes = props.objects.filter(object => object.objectType === 'role_object')
  const scenarios = nodes.filter(object => categoryOf(object) === 'scenario')
  const processNodes = nodes.filter(object => categoryOf(object) !== 'scenario')
  const payload = (props.result.payload || {}) as RecordValue
  return (
    <section className="role-plugin-view role-plugin-process" aria-label="岗位事理森林">
      <SnapshotBadge result={props.result} />
      <p className="role-plugin-boundary">{String(payload.boundary || '')}</p>
      {scenarios.map(scenario => {
        const scenarioData = dataOf(scenario)
        const items = processNodes.filter(object => String(dataOf(object).scenarioId || '') === scenario.objectId)
          .sort((left, right) => Number(dataOf(left).sequenceHint || 999) - Number(dataOf(right).sequenceHint || 999))
        return <article className="role-plugin-scenario" key={scenario.objectId}>
          <header><span>{String(scenarioData.knowledgeState || 'process')}</span><strong>{scenario.label}</strong><p>{String(scenarioData.summary || '')}</p></header>
          <div className="role-plugin-process-lanes">
            {items.map((object, index) => {
              const data = dataOf(object)
              const category = categoryOf(object)
              return <div className="role-plugin-process-step" key={object.objectId} style={{ '--role-accent': colorFor(category) } as CSSProperties} {...interactiveObjectProps(props, object)}><i>{index + 1}</i><span><small>{category}</small><strong>{object.label}</strong><p>{String(data.summary || '')}</p><FollowActions props={props} objectId={object.objectId} label={object.label} /></span></div>
            })}
          </div>
        </article>
      })}
      {payload.truncated && <p className="role-plugin-warning">场景节点已按本次工具预算截断。</p>}
    </section>
  )
}

function PackageCatalog(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  return <section className="role-plugin-view role-plugin-catalog" aria-label="岗位包目录">
    <header><strong>已安装岗位包</strong><small>{String(payload.count || 0)} 个不可变版本</small></header>
    {(payload.packages || []).map((item: RecordValue) => <article key={String(item.snapshotId)}><span>{String(item.roleTitle)}</span><strong>v{String(item.packageVersion)}</strong><p>{String(item.snapshotAsOf)} · <code>{String(item.snapshotId)}</code></p>{props.onPrompt && <button type="button" onClick={() => props.onPrompt?.(`介绍岗位包“${String(item.roleTitle)}”（固定快照 ${String(item.snapshotId)}）`)}>使用此版本</button>}</article>)}
  </section>
}

function PackageComparison(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  const group = (title: string, values: string[]) => <section><header><strong>{title}</strong><b>{values.length}</b></header>{values.length ? <ul>{values.slice(0, 16).map(value => <li key={value}><code>{value}</code></li>)}</ul> : <p>无</p>}</section>
  return <section className="role-plugin-view role-plugin-comparison" aria-label="岗位包版本比较">
    <header><span>v{String(payload.base?.packageVersion || '—')}</span><i>→</i><span>v{String(payload.target?.packageVersion || '—')}</span></header>
    <div>{group('新增', payload.added || [])}{group('移除', payload.removed || [])}{group('内容变更', payload.changed || [])}{group('引用迁移', payload.referenceMigrationHits || [])}</div>
    {payload.truncated && <p className="role-plugin-boundary">差异列表已按单类 40 项截断。</p>}
  </section>
}

function EvidencePanel(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  return (
    <section className="role-plugin-view role-plugin-evidence" aria-label="岗位证据">
      <SnapshotBadge result={props.result} />
      <div className="role-plugin-evidence-list">
        {props.objects.map(object => {
          const evidence = dataOf(object)
          const binding = evidence.binding || {}
          const segment = evidence.segment || {}
          const source = evidence.source || {}
          return <article key={object.objectId}><header><strong>{String(source.title || object.label)}</strong><span>{String(binding.assertionType || binding.support || 'evidence')}</span></header><blockquote>{String(segment.text || '该绑定没有可发布的原文片段。')}</blockquote><p>{String(source.publisher || '')}{segment.locator ? ` · ${segment.locator}` : ''}</p>{Array.isArray(binding.limitations) && binding.limitations.length > 0 && <small>限制：{binding.limitations.join('；')}</small>}</article>
        })}
      </div>
      {payload.truncated && <p className="role-plugin-warning">目标数量超过证据工具预算，已显式截断。</p>}
    </section>
  )
}

function AuditPanel(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  const validation = payload.validation || {}
  const stats = validation.stats || {}
  const issues = validation.audit?.issues || []
  return (
    <section className="role-plugin-view role-plugin-audit" aria-label="岗位包审计">
      <SnapshotBadge result={props.result} />
      <header className={validation.valid ? 'valid' : 'invalid'}><strong>{validation.valid ? '协议有效' : '协议无效'}</strong><span>这表示包可读取，不表示内容已经完整，也不表示学习者掌握。</span></header>
      <div className="role-plugin-metrics">{Object.entries(stats).map(([key, value]) => <span key={key}><strong>{String(value)}</strong><small>{key}</small></span>)}</div>
      <div className="role-plugin-audit-issues">{issues.map((issue: RecordValue) => <article key={String(issue.id)}><span>{String(issue.severity)}</span><strong>{String(issue.title)}</strong><p>{String(issue.detail)}</p></article>)}</div>
      {Array.isArray(validation.warnings) && validation.warnings.length > 0 && <details><summary>已知警告 {validation.warnings.length}</summary><ul>{validation.warnings.map((warning: string) => <li key={warning}>{warning}</li>)}</ul></details>}
    </section>
  )
}

const plugin = defineLearnFlowPluginClient({
  pluginId: ROLE_CAPABILITY_PLUGIN.id,
  name: ROLE_CAPABILITY_PLUGIN.name,
  description: ROLE_CAPABILITY_PLUGIN.description,
  icon: ROLE_CAPABILITY_PLUGIN.icon,
  renderers: {
    [ROLE_RENDERERS.overview]: RoleOverview,
    [ROLE_RENDERERS.cards]: RoleCards,
    [ROLE_RENDERERS.radar]: CapabilityRadar,
    [ROLE_RENDERERS.graph]: RoleGraph,
    [ROLE_RENDERERS.process]: ProcessForest,
    [ROLE_RENDERERS.evidence]: EvidencePanel,
    [ROLE_RENDERERS.audit]: AuditPanel,
    [ROLE_RENDERERS.catalog]: PackageCatalog,
    [ROLE_RENDERERS.comparison]: PackageComparison,
    [ROLE_RENDERERS.buildCandidate]: ColdStartCandidate,
    [ROLE_RENDERERS.iterationCandidate]: IterationCandidate,
  },
})

export default plugin
