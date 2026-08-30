import { useEffect, useState } from 'react'
import { loadProjectPluginSurfaces, type ProjectPluginSurface } from './plugin-runtime.ts'
import {
  pluginChatContext,
  roleCapabilityChatState,
  type RoleCapabilityChatArtifact,
} from './plugin-chat.ts'

const TYPE_LABELS: Record<string, string> = {
  role: '岗位', task: '典型任务', capability: '能力', knowledge_skill: '知识技能',
  claim: '主张', scenario: '场景', process_event: '过程事件', actor: '参与者',
  work_object: '工作对象', artifact: '产物', risk: '风险', bridge: '语义桥',
}

export function RoleCapabilityArtifactView({ artifact }: { artifact: RoleCapabilityChatArtifact }) {
  const [view, setView] = useState<'radar' | 'forest' | 'cards'>('radar')
  const [expanded, setExpanded] = useState<string>('')
  const radarNodes = artifact.nodes.slice(0, 18)
  const center = 180
  const radius = 128
  const position = (index: number) => {
    const angle = (Math.PI * 2 * index / Math.max(1, radarNodes.length)) - Math.PI / 2
    return { x: center + Math.cos(angle) * radius, y: center + Math.sin(angle) * radius }
  }
  const positions = new Map(radarNodes.map((item, index) => [item.id, position(index)]))
  const groups = Object.entries(artifact.nodes.reduce<Record<string, typeof artifact.nodes>>((output, item) => {
    ;(output[item.type] ||= []).push(item)
    return output
  }, {}))
  return (
    <section className="role-chat-artifact" aria-label={artifact.title}>
      <header className="role-chat-artifact-heading">
        <div><span>岗位图谱快照</span><strong>{artifact.title}</strong></div>
        <small>{artifact.snapshot?.version ? `v${artifact.snapshot.version}` : '固定快照'} · {artifact.nodes.length} 对象 · {artifact.edges.length} 关系</small>
      </header>
      {artifact.explanation && <p className="role-chat-explanation">{artifact.explanation}</p>}
      <nav className="role-chat-view-tabs" aria-label="岗位图谱视图">
        <button type="button" className={view === 'radar' ? 'active' : ''} onClick={() => setView('radar')}>雷达图</button>
        <button type="button" className={view === 'forest' ? 'active' : ''} onClick={() => setView('forest')}>事理森林</button>
        <button type="button" className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')}>对象卡片</button>
      </nav>
      {view === 'radar' && (
        <div className="role-radar-view">
          {radarNodes.length ? <svg viewBox="0 0 360 360" role="img" aria-label="岗位任务能力知识关系雷达">
            {[44, 84, 128].map(value => <circle key={value} cx={center} cy={center} r={value} className="role-radar-ring" />)}
            {artifact.edges.slice(0, 60).map(edge => {
              const from = positions.get(edge.source)
              const to = positions.get(edge.target)
              return from && to ? <line key={edge.id} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className="role-radar-edge" /> : null
            })}
            <circle cx={center} cy={center} r="28" className="role-radar-center" />
            <text x={center} y={center + 4} textAnchor="middle" className="role-radar-center-label">岗位</text>
            {radarNodes.map((item, index) => {
              const point = position(index)
              return <g key={item.id} className={`role-radar-node role-radar-node-${item.type}`} onClick={() => { setExpanded(item.id); setView('cards') }}>
                <circle cx={point.x} cy={point.y} r="13" />
                <text x={point.x} y={point.y + (point.y < center ? -19 : 25)} textAnchor="middle">{item.label.slice(0, 10)}</text>
              </g>
            })}
          </svg> : <p className="role-chat-empty">当前工具结果没有返回可绘制的关系节点。</p>}
          <div className="role-radar-legend"><span>任务</span><span>能力</span><span>知识技能</span><span>其他对象</span></div>
        </div>
      )}
      {view === 'forest' && (
        <div className="role-process-forest">
          {artifact.scenarios.map(scenario => <section key={scenario.id}>
            <header><span>场景</span><strong>{scenario.label}</strong></header>
            <div className="role-process-branch">
              {scenario.eventIds.map((eventId, index) => {
                const event = artifact.events.find(item => item.id === eventId)
                const workObject = artifact.workObjects.find(item => item.id === event?.workObjectId)
                const bridge = artifact.bridges.find(item => item.processEventId === eventId)
                return event ? <article key={event.id}>
                  <i>{index + 1}</i><div><strong>{event.label}</strong><small>{event.lifecycle || 'candidate'}{workObject ? ` · ${workObject.label}` : ''}</small>{bridge && <span>{bridge.label}</span>}</div>
                </article> : null
              })}
            </div>
          </section>)}
          {!artifact.scenarios.length && <p className="role-chat-empty">当前结果没有过程场景；读取完整快照后会显示事件顺序、工作对象与任务桥接。</p>}
        </div>
      )}
      {view === 'cards' && (
        <div className="role-object-groups">
          {groups.map(([type, items]) => <section key={type}>
            <header><strong>{TYPE_LABELS[type] || type}</strong><span>{items.length}</span></header>
            <div>{items.map(item => <article key={item.id} className={expanded === item.id ? 'expanded' : ''}>
              <button type="button" onClick={() => setExpanded(current => current === item.id ? '' : item.id)}>
                <span>{item.lifecycle || 'active'}</span><strong>{item.label}</strong><i>{expanded === item.id ? '−' : '+'}</i>
              </button>
              {expanded === item.id && <div><p>{item.summary || '这个对象的完整说明可继续在对话中要求解释 Agent 按固定快照读取。'}</p><small>对象 ID：{item.id} · {item.evidenceCount} 条证据引用</small></div>}
            </article>)}</div>
          </section>)}
        </div>
      )}
      {artifact.validation && (artifact.validation.errors.length > 0 || artifact.validation.warnings.length > 0) && (
        <footer className="role-chat-validation">校验：{artifact.validation.errors.length} 个错误 · {artifact.validation.warnings.length} 个提示</footer>
      )}
    </section>
  )
}

export default function RoleCapabilityChatPlugin({ projectId, pluginId, snapshotId, disabled, onManage, onPrompt }: {
  projectId: number
  pluginId: string
  snapshotId?: number
  disabled?: boolean
  onManage: () => void
  onPrompt: (prompt: string) => void
}) {
  const [surface, setSurface] = useState<ProjectPluginSurface>()
  const [error, setError] = useState('')
  const refresh = async () => {
    const page = await loadProjectPluginSurfaces(projectId)
    const selected = page.surfaces.find(item => item.plugin_id === pluginId)
    setSurface(selected)
    return selected
  }
  useEffect(() => { void refresh().catch(failure => setError(failure instanceof Error ? failure.message : '插件状态读取失败')) }, [projectId, pluginId, snapshotId])
  const state = roleCapabilityChatState(surface)
  const context = surface ? pluginChatContext(surface) : undefined

  return (
    <details className="composer-plugin-control" aria-label="岗位能力图谱插件选项">
      <summary role="button" aria-label="打开岗位能力图谱插件选项">
        <span className="composer-plugin-glyph">岗</span>
        <strong>{surface?.title || '岗位能力图谱'}</strong>
        <small>{context?.snapshotVersion ? `v${context.snapshotVersion}` : '待生成'}</small>
      </summary>
      <div className="composer-plugin-popover">
        <header><div><span>PRODUCT SKILL</span><strong>{context?.productSkillId || 'role_capability_graphing'}</strong></div><button type="button" onClick={onManage}>管理</button></header>
        <div className={`plugin-chat-status plugin-chat-status-${state.id}`}><i />{state.label}</div>
        <p>{context?.snapshotId ? '岗位包已进入当前 Tutor 对话；解释和调整都从消息发起，不写五核。' : 'Tutor 会从项目目标或下一条岗位名自动启动。'}</p>
        <div className="plugin-chat-actions">
          <button type="button" disabled={disabled || !context?.snapshotId} onClick={() => onPrompt('请固定到当前岗位图谱快照，解释这个岗位最关键的任务、能力、知识技能和证据。')}>在对话中解释</button>
          <button type="button" disabled={disabled || !context?.snapshotId} onClick={() => onPrompt('我想调整当前岗位图谱。请先在对话中确认我要改变的岗位对象和依据，再形成候选迭代。')}>在对话中调整</button>
        </div>
        {error && <div className="plugin-chat-error">{error}</div>}
      </div>
    </details>
  )
}
