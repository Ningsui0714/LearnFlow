import type { CSSProperties } from 'react'
import {
  defineLearnFlowPluginClient,
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

function FollowActions({ props, objectId, label }: { props: PluginToolRendererProps; objectId: string; label: string }) {
  if (!props.onPrompt) return null
  const snapshot = snapshotOf(props.result)
  const suffix = `（固定快照 ${String(snapshot.snapshotId || '')}，对象 ${objectId}）`
  return <div className="role-plugin-actions">
    <button type="button" onClick={() => props.onPrompt?.(`详细解释“${label}”${suffix}`)}>继续解释</button>
    <button type="button" onClick={() => props.onPrompt?.(`展示“${label}”与其他岗位对象的关系${suffix}`)}>查看关系</button>
    <button type="button" onClick={() => props.onPrompt?.(`核对“${label}”的证据和适用边界${suffix}`)}>查看证据</button>
  </div>
}

function RoleOverview(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  const sections = payload.sections || {}
  const nodes = new Map(props.objects.filter(object => object.objectType === 'role_object').map(object => [object.objectId, object]))
  const root = nodes.get(String(payload.rootId || ''))
  const renderSection = (title: string, ids: string[], empty: string) => <section className="role-plugin-overview-section">
    <header><strong>{title}</strong><small>{ids.length}</small></header>
    <div>{ids.map(id => nodes.get(id)).filter(Boolean).map(object => {
      const data = dataOf(object!)
      return <article key={object!.objectId} style={{ '--role-accent': colorFor(categoryOf(object!)) } as CSSProperties}>
        <span>{categoryOf(object!)}</span><strong>{object!.label}</strong><p>{String(data.summary || '')}</p>
        <FollowActions props={props} objectId={object!.objectId} label={object!.label} />
      </article>
    })}</div>
    {!ids.length && <p>{empty}</p>}
  </section>
  return <section className="role-plugin-view role-plugin-overview" aria-label="岗位全景">
    <SnapshotBadge result={props.result} />
    {root && <article className="role-plugin-identity"><span>岗位定位</span><strong>{root.label}</strong><p>{String(dataOf(root).summary || '')}</p><FollowActions props={props} objectId={root.objectId} label={root.label} /></article>}
    <div className="role-plugin-overview-grid">
      {renderSection('典型任务', sections.tasks || [], '当前视图没有任务对象。')}
      {renderSection('核心能力', sections.capabilities || [], '当前视图没有能力对象。')}
      {renderSection('工作场景', sections.scenarios || [], '当前视图没有场景对象。')}
      {renderSection('相邻岗位', sections.relatedRoles || [], '当前视图没有相邻岗位。')}
    </div>
    <p className="role-plugin-boundary">{String(payload.grounding?.requiredDisclosure || '')}</p>
  </section>
}

function CapabilityRadar(props: PluginToolRendererProps) {
  const payload = (props.result.payload || {}) as RecordValue
  const axes = (payload.axes || []) as Array<{ objectId: string; label: string; value: number }>
  const size = 420
  const center = size / 2
  const radius = 145
  const point = (index: number, value = 1) => {
    const angle = Math.PI * 2 * index / Math.max(axes.length, 1) - Math.PI / 2
    return { x: center + Math.cos(angle) * radius * value, y: center + Math.sin(angle) * radius * value }
  }
  const polygon = (value: number) => axes.map((_, index) => { const p = point(index, value); return `${p.x},${p.y}` }).join(' ')
  const values = axes.map((axis, index) => { const p = point(index, axis.value); return `${p.x},${p.y}` }).join(' ')
  return <section className="role-plugin-view role-plugin-radar" aria-label="岗位能力雷达">
    <SnapshotBadge result={props.result} />
    <div className="role-plugin-radar-layout">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${axes.length} 个岗位能力维度的雷达图`}>
        {[.25, .5, .75, 1].map(level => <polygon key={level} points={polygon(level)} className="grid" />)}
        {axes.map((axis, index) => { const outer = point(index); const label = point(index, 1.18); return <g key={axis.objectId}><line x1={center} y1={center} x2={outer.x} y2={outer.y} /><text x={label.x} y={label.y}>{axis.label.length > 10 ? `${axis.label.slice(0, 9)}…` : axis.label}</text></g> })}
        <polygon points={values} className="value" />
        {axes.map((axis, index) => { const p = point(index, axis.value); return <circle key={axis.objectId} cx={p.x} cy={p.y} r="5"><title>{axis.label} · {Math.round(axis.value * 100)}%</title></circle> })}
      </svg>
      <div className="role-plugin-radar-legend">{axes.map(axis => <article key={axis.objectId}><span style={{ width: `${Math.round(axis.value * 100)}%` }} /><strong>{axis.label}</strong><b>{Math.round(axis.value * 100)}%</b><FollowActions props={props} objectId={axis.objectId} label={axis.label} /></article>)}</div>
    </div>
    <p className="role-plugin-boundary">{String(payload.scale?.meaning || '')}</p>
  </section>
}

function RoleCards(props: PluginToolRendererProps) {
  const nodes = props.objects.filter(object => object.objectType === 'role_object')
  const payload = (props.result.payload || {}) as RecordValue
  return (
    <section className="role-plugin-view role-plugin-cards" aria-label="岗位对象卡片">
      <SnapshotBadge result={props.result} />
      <div className="role-plugin-card-grid">
        {nodes.map(object => {
          const data = dataOf(object)
          const category = categoryOf(object)
          return (
            <article key={object.objectId} style={{ '--role-accent': colorFor(category) } as CSSProperties}>
              <header><span>{category}</span><small>{String(data.lifecycle || data.knowledgeState || 'snapshot')}</small></header>
              <strong>{object.label}</strong>
              <p>{String(data.summary || '')}</p>
              <footer><code>{object.objectId}</code>{typeof data.confidence === 'number' && <b>{Math.round(data.confidence * 100)}%</b>}</footer>
              <FollowActions props={props} objectId={object.objectId} label={object.label} />
            </article>
          )
        })}
      </div>
      {payload.omittedIds?.length ? <p className="role-plugin-warning">未找到：{payload.omittedIds.join('、')}</p> : null}
      {payload.coverage?.omitted ? <p className="role-plugin-boundary">结果有界：另有 {payload.coverage.omitted} 个匹配对象未展示。</p> : null}
    </section>
  )
}

function RoleGraph(props: PluginToolRendererProps) {
  const allNodes = props.objects.filter(object => object.objectType === 'role_object')
  const relationObjects = props.objects.filter(object => object.objectType === 'role_relation')
  const payload = (props.result.payload || {}) as RecordValue
  const rootId = String(payload.rootId || allNodes[0]?.objectId || '')
  const nodeObjects = [allNodes.find(object => object.objectId === rootId), ...allNodes.filter(object => object.objectId !== rootId)].filter(Boolean).slice(0, 16) as typeof allNodes
  const visibleIds = new Set(nodeObjects.map(object => object.objectId))
  const visibleRelations = relationObjects.filter(object => {
    const relation = dataOf(object)
    return visibleIds.has(String(relation.source)) && visibleIds.has(String(relation.target))
  }).slice(0, 28)
  const width = 760
  const height = 430
  const center = { x: width / 2, y: height / 2 }
  const positions = new Map<string, { x: number; y: number }>()
  const ordered = [...nodeObjects].sort((left, right) => left.objectId === rootId ? -1 : right.objectId === rootId ? 1 : left.objectId.localeCompare(right.objectId))
  ordered.forEach((object, index) => {
    if (object.objectId === rootId) positions.set(object.objectId, center)
    else {
      const ringIndex = index - (ordered[0]?.objectId === rootId ? 1 : 0)
      const count = Math.max(1, ordered.length - 1)
      const angle = (Math.PI * 2 * ringIndex) / count - Math.PI / 2
      const radius = ringIndex < 8 ? 112 : 176
      positions.set(object.objectId, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius })
    }
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
      <div className="role-plugin-graph-focus">{ordered.map(object => <button key={object.objectId} type="button" onClick={() => props.onPrompt?.(`以“${object.label}”为中心展开一层岗位关系（固定快照 ${String(snapshotOf(props.result).snapshotId || '')}，对象 ${object.objectId}）`)}>{object.label}</button>)}</div>
      <p className="role-plugin-legend">关系类型：{[...new Set(visibleRelations.map(object => String(dataOf(object).type || 'relation')))].join(' · ')}</p>
      {payload.truncated && <p className="role-plugin-boundary">子图达到本次节点上限；这是有界投影，不是完整岗位包。</p>}
    </section>
  )
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
              return <div className="role-plugin-process-step" key={object.objectId} style={{ '--role-accent': colorFor(category) } as CSSProperties}><i>{index + 1}</i><span><small>{category}</small><strong>{object.label}</strong><p>{String(data.summary || '')}</p></span></div>
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
  },
})

export default plugin
