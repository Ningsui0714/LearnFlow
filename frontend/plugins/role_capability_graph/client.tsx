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
  const nodeObjects = props.objects.filter(object => object.objectType === 'role_object')
  const relationObjects = props.objects.filter(object => object.objectType === 'role_relation')
  const payload = (props.result.payload || {}) as RecordValue
  const rootId = String(payload.rootId || nodeObjects[0]?.objectId || '')
  const width = 720
  const height = 390
  const center = { x: width / 2, y: height / 2 }
  const positions = new Map<string, { x: number; y: number }>()
  const ordered = [...nodeObjects].sort((left, right) => left.objectId === rootId ? -1 : right.objectId === rootId ? 1 : left.objectId.localeCompare(right.objectId))
  ordered.forEach((object, index) => {
    if (object.objectId === rootId) positions.set(object.objectId, center)
    else {
      const ringIndex = index - (ordered[0]?.objectId === rootId ? 1 : 0)
      const count = Math.max(1, ordered.length - 1)
      const angle = (Math.PI * 2 * ringIndex) / count - Math.PI / 2
      const radius = Math.min(155, 90 + Math.floor(ringIndex / 10) * 48)
      positions.set(object.objectId, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius })
    }
  })
  return (
    <section className="role-plugin-view role-plugin-graph" aria-label="岗位关系雷达">
      <SnapshotBadge result={props.result} />
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${nodeObjects.length} 个岗位对象的关系图`}>
        <g className="role-plugin-graph-edges">
          {relationObjects.map(object => {
            const relation = dataOf(object)
            const source = positions.get(String(relation.source))
            const target = positions.get(String(relation.target))
            if (!source || !target) return null
            return <g key={object.objectId}><line x1={source.x} y1={source.y} x2={target.x} y2={target.y} /><text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2}>{String(relation.type || '')}</text></g>
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
    [ROLE_RENDERERS.cards]: RoleCards,
    [ROLE_RENDERERS.graph]: RoleGraph,
    [ROLE_RENDERERS.process]: ProcessForest,
    [ROLE_RENDERERS.evidence]: EvidencePanel,
    [ROLE_RENDERERS.audit]: AuditPanel,
  },
})

export default plugin
