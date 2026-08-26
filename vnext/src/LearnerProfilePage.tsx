import { useMemo, useState } from 'react'
import type {
  FormalLearnerSnapshot,
  FormalRuntimeConnection,
  KernelName,
} from './formal-runtime'
import {
  presentClaimText,
  presentEvidenceCount,
  presentModuleScope,
  presentModuleTitle,
  presentVerification,
} from './profile-presentation'

const KERNELS: Array<{ id: KernelName; name: string; short: string; description: string }> = [
  { id: 'structure', name: '结构核', short: '结构', description: '学习位置、路径依赖、当前锚点与可返回的位置。它与知识核共享主题标识，但不替知识核判断掌握。' },
  { id: 'knowledge', name: '知识核', short: '知识', description: '概念理解、误解、缺口与经过验证的表现。自报学过只记为接触，不自动升级为掌握。' },
  { id: 'human', name: '人因核', short: '人因', description: '节奏、负荷、可访问性、偏好与支持需求。只保留能改善学习的凝练信息，敏感内容优先可见、可纠正。' },
  { id: 'value', name: '价值核', short: '价值', description: '目标、兴趣、优先级与意义连接。长期方向必须由你明确确认，规划 Agent 只能提出候选。' },
  { id: 'practice', name: '实践核', short: '实践', description: '尝试、支架等级、可检查产物、迁移与项目表现。讲解完成、一次答对或自述都不能代替独立实践证据。' },
]

type Props = {
  connection: FormalRuntimeConnection
  snapshot?: FormalLearnerSnapshot
  busyKey: string
  error: string
  onRefresh: () => void
  onOpenPath: () => void
  onMemoryArchive: (memoryId: string, archived: boolean) => void
  onClaimAction: (claimId: number, action: 'confirm' | 'correct' | 'retract', correction?: string) => void
  onRecordSelfReport: (rawText: string) => Promise<boolean>
}

function PersonalConceptGraph({ snapshot, kernel }: { snapshot: FormalLearnerSnapshot; kernel: KernelName }) {
  const [selectedKey, setSelectedKey] = useState('')
  const graph = snapshot.concept_graph
  const visibleNodes = graph.nodes.slice(0, 18)
  const visibleKeys = new Set(visibleNodes.map(node => node.concept_key))
  const visibleEdges = graph.edges.filter(edge => visibleKeys.has(edge.source_key) && visibleKeys.has(edge.target_key))
  const selected = graph.nodes.find(node => node.concept_key === selectedKey) || visibleNodes[0]
  const width = 760
  const height = 330
  const center = { x: 350, y: 165 }
  const innerCount = Math.min(7, visibleNodes.length)
  const outerCount = Math.max(visibleNodes.length - innerCount, 0)
  const positions = new Map(visibleNodes.map((node, index) => {
    const inner = index < innerCount
    const ring = inner ? 98 : 151
    const ringIndex = inner ? index : index - innerCount
    const ringCount = inner ? innerCount : outerCount
    const angle = -Math.PI / 2 + (Math.PI * 2 * ringIndex) / Math.max(ringCount, 1)
    return [node.concept_key, {
      x: center.x + Math.cos(angle) * ring,
      y: center.y + Math.sin(angle) * ring * .72,
    }]
  }))
  const selectedEdges = selected
    ? graph.edges.filter(edge => edge.source_key === selected.concept_key || edge.target_key === selected.concept_key)
    : []
  const currentState = selected?.knowledge.current_state || {
    status: selected?.knowledge.timeline.length ? 'self_report_only' : 'relation_only',
    certain_claims: [],
    uncertain_observations: [],
    conflicts: [],
  }

  return (
    <section className={`personal-concept-panel concept-panel-${kernel}`}>
      <header>
        <div><span>KNOWLEDGE × STRUCTURE</span><h2>个人概念学习图</h2><p>节点身份共享；节点内部的认识历程归知识核，节点之间的关系归结构核。</p></div>
        <div><strong>{graph.manifest.node_count}</strong><small>概念</small><strong>{graph.manifest.edge_count}</strong><small>关系</small></div>
      </header>
      {visibleNodes.length === 0 ? (
        <p className="formal-empty-copy">尚无个人概念节点。可在上方录入明确自述，或在学习过程中由正式事件逐步形成。</p>
      ) : (
        <div className="personal-concept-layout">
          <div className="concept-graph-canvas">
            <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="个人概念学习图">
              <defs>
                <marker id="concept-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" /></marker>
              </defs>
              {visibleEdges.map(edge => {
                const source = positions.get(edge.source_key)
                const target = positions.get(edge.target_key)
                if (!source || !target) return null
                const highlighted = selected?.concept_key === edge.source_key || selected?.concept_key === edge.target_key
                const mx = (source.x + target.x) / 2
                const my = (source.y + target.y) / 2
                return <g key={edge.id} className={highlighted ? 'concept-edge highlighted' : 'concept-edge'}>
                  <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} markerEnd="url(#concept-arrow)" />
                  {highlighted && <text x={mx} y={my - 4}>{edge.label}</text>}
                </g>
              })}
              {visibleNodes.map(node => {
                const position = positions.get(node.concept_key)!
                const active = selected?.concept_key === node.concept_key
                return <g key={node.concept_key} role="button" tabIndex={0} aria-label={`查看${node.name}`} className={active ? 'concept-node active' : 'concept-node'} transform={`translate(${position.x},${position.y})`} onClick={() => setSelectedKey(node.concept_key)} onKeyDown={event => { if (event.key === 'Enter') setSelectedKey(node.concept_key) }}>
                  <circle r={active ? 31 : 25} />
                  <text textAnchor="middle" y="-2">{node.name.length > 8 ? `${node.name.slice(0, 7)}…` : node.name}</text>
                  <text className="concept-node-count" textAnchor="middle" y="11">{kernel === 'knowledge' ? `${node.knowledge_event_count} 历程` : `${node.structure_relation_count} 关系`}</text>
                </g>
              })}
            </svg>
            {graph.nodes.length > visibleNodes.length && <small>当前显示最相关的 {visibleNodes.length} 个节点；详情列表仍保留全部 {graph.nodes.length} 个节点。</small>}
          </div>
          <aside className="concept-node-inspector">
            {selected && <>
              <span>{selected.official_node_id ? '官方课程节点叠加' : '个人概念节点'}</span>
              <h3>{selected.name}</h3>
              <code>{selected.concept_key}</code>
              <div className="concept-inspector-stats"><b>{selected.knowledge_event_count}<small>知识历程</small></b><b>{selected.structure_relation_count}<small>结构关系</small></b><b>{selected.knowledge.verified_count}<small>验证证据</small></b></div>
              {kernel === 'knowledge' ? (
                <div className="concept-timeline">
                  <h4>节点内部发生了什么</h4>
                  <div className={`concept-current-state state-${currentState.status}`}>
                    <b>{currentState.status === 'self_report_only' ? '目前只有自述，等待验证' : currentState.status === 'evidence_backed_claim' ? '已有证据支持的可纠正认识' : currentState.status === 'conflicting_evidence' ? '当前证据存在冲突' : currentState.status === 'verified_events' ? '已有验证事件，尚未凝练 Claim' : '尚无节点内部证据'}</b>
                    <span>{currentState.uncertain_observations.length} 条模糊/缺口 · {currentState.conflicts.length} 条冲突</span>
                  </div>
                  {currentState.certain_claims.slice(-2).map(claim => <article key={`claim-${claim.claim_id}`} className="concept-evidence-claim">
                    <i /><div><span>Claim · {claim.verification_status} · {Math.round(claim.confidence * 100)}%</span><p>{claim.statement}</p></div>
                  </article>)}
                  {selected.knowledge.timeline.length === 0 && <p>目前只有结构关系，还没有知识历程。</p>}
                  {[...selected.knowledge.timeline].reverse().slice(0, 6).map(item => <article key={item.fact_id}>
                    <i /><div><span>{item.observation_type} · {item.verification}</span><p>{item.statement}</p>{item.raw_text && <details><summary>查看保留的原文</summary><q>{item.raw_text}</q></details>}</div>
                  </article>)}
                </div>
              ) : (
                <div className="concept-relation-list">
                  <h4>它与什么相连</h4>
                  {selectedEdges.length === 0 && <p>还没有记录概念关系。</p>}
                  {selectedEdges.slice(0, 8).map(edge => {
                    const outgoing = edge.source_key === selected.concept_key
                    const peerKey = outgoing ? edge.target_key : edge.source_key
                    const peer = graph.nodes.find(node => node.concept_key === peerKey)
                    return <article key={edge.id}><b>{outgoing ? '→' : '←'} {edge.label}</b><span>{peer?.name || peerKey}</span><p>{edge.rationale || '暂无关系说明'}</p><small>{edge.verification} · 不推断掌握</small></article>
                  })}
                </div>
              )}
            </>}
          </aside>
        </div>
      )}
      <footer>官方课程图描述一般培养路径；这里描述你实际怎样理解、联想、受阻和迁移。规划时两张图可以叠加，但不会合并权威。</footer>
    </section>
  )
}

export default function LearnerProfilePage({
  connection, snapshot, busyKey, error, onRefresh, onOpenPath, onMemoryArchive, onClaimAction, onRecordSelfReport,
}: Props) {
  const [activeKernel, setActiveKernel] = useState<KernelName>('structure')
  const [corrections, setCorrections] = useState<Record<number, string>>({})
  const [selfReport, setSelfReport] = useState('')
  const meta = KERNELS.find(item => item.id === activeKernel) || KERNELS[0]
  const area = snapshot?.growth.areas.find(item => item.id === activeKernel)
  const modules = useMemo(
    () => snapshot?.modules.filter(item => item.kernel === activeKernel) || [],
    [activeKernel, snapshot],
  )
  const rawKernel = snapshot?.kernels[activeKernel]

  if (!snapshot) {
    return (
      <section className="profile-page formal-empty-page">
        <div className="formal-empty-card">
          <span className="eyebrow">FIVE-KERNEL AUTHORITY</span>
          <h1>正式五核尚未连接</h1>
          <p>{connection.detail || '正在读取正式用户状态。'}</p>
          <button type="button" onClick={onRefresh}>重新连接</button>
        </div>
      </section>
    )
  }

  return (
    <section className="profile-page formal-profile-page">
      <header className="profile-page-heading">
        <div>
          <span className="eyebrow">FIVE-KERNEL LEARNER MODEL</span>
          <h1>{snapshot.learner.display_name}的五核画像</h1>
          <p>所有内容都来自 EvidenceEvent 的确定性归约。原始事件不可改写；你的“删除”和“修改”会记录为归档、撤回或纠正，后续 Agent 读取最新有效版本。</p>
        </div>
        <div className="profile-version formal-authority-badge">
          <strong>{connection.status === 'connected' ? '已接入' : '离线'}</strong>
          <span>{snapshot.authority}</span>
        </div>
      </header>

      {error && <div className="formal-inline-error" role="alert">{error}</div>}

      <div className="formal-profile-overview">
        <div><span>当前重点</span><strong>{String(snapshot.growth.overview.current_focus || '尚未确定')}</strong></div>
        <div><span>有效记忆</span><strong>{snapshot.growth.stats.active_memories || 0}</strong></div>
        <div><span>可追溯记录</span><strong>{snapshot.growth.stats.learning_records || 0}</strong></div>
        <button type="button" onClick={onOpenPath}>查看结构核的学习路径</button>
      </div>

      <section className="formal-self-report-card">
        <div className="formal-profile-source">
          <span>学习者明确资料</span>
          <h2>原始自述保持可见</h2>
          <p>{snapshot.profile.background || '尚未填写学习基础。'}</p>
          <dl>
            <div><dt>关注方向</dt><dd>{snapshot.profile.focus_areas.join('、') || '未填写'}</dd></div>
            <div><dt>偏好形式</dt><dd>{snapshot.profile.preferred_modes.join('、') || '未填写'}</dd></div>
            <div><dt>方向目标</dt><dd>{snapshot.profile.career_goal || '仍在探索'}</dd></div>
          </dl>
        </div>
        <form onSubmit={event => {
          event.preventDefault()
          if (!selfReport.trim()) return
          void onRecordSelfReport(selfReport.trim()).then(saved => { if (saved) setSelfReport('') })
        }}>
          <span>补充到个人概念图</span>
          <p>写下“我学过……”“我不懂……”或明确的阻碍、推动、联想。系统只记录为用户自输入、待验证，不会据此宣称掌握。</p>
          <textarea value={selfReport} onChange={event => setSelfReport(event.target.value)} placeholder="例如：我学过概率论，但条件概率总是搞混。链式法则帮助我理解反向传播。" />
          <button type="submit" disabled={!selfReport.trim() || busyKey === 'concept-report'}>{busyKey === 'concept-report' ? '正在写入事件链…' : '记录明确自述'}</button>
        </form>
      </section>

      <nav className="kernel-tabs" aria-label="五核切换" role="tablist">
        {KERNELS.map(item => (
          <button key={item.id} type="button" role="tab" aria-selected={activeKernel === item.id} className={activeKernel === item.id ? 'active' : ''} onClick={() => setActiveKernel(item.id)}>
            <span>{item.short}</span><small>{snapshot.modules.filter(module => module.kernel === item.id).length} modules</small>
          </button>
        ))}
      </nav>

      <div className="kernel-definition-card">
        <div><span>{meta.name}</span><p>{meta.description}</p></div>
        <small>短期键 {Object.keys(rawKernel?.short_term || {}).length} · 长期键 {Object.keys(rawKernel?.long_term || {}).length} · 置信度 {Math.round((rawKernel?.confidence || 0) * 100)}%</small>
      </div>

      {(activeKernel === 'knowledge' || activeKernel === 'structure') && <PersonalConceptGraph snapshot={snapshot} kernel={activeKernel} />}

      <div className="formal-profile-grid" role="tabpanel" aria-label={meta.name}>
        <section className="kernel-memory-column">
          <header><div><span>Agent 当前可参考</span><h2>核状态记忆</h2></div><small>{area?.active_count || 0} 条有效</small></header>
          {(area?.memories || []).length === 0 && <p className="formal-empty-copy">这个核还没有可展示的有效记忆。它会随着明确自述、学习事件和可验证表现逐步形成。</p>}
          {(area?.memories || []).map(memory => (
            <article key={memory.memory_id} className={`kernel-memory-row ${memory.status === 'archived' ? 'archived' : ''}`}>
              <div><span>{memory.retention_label} · {memory.source_label}</span><h3>{memory.title}</h3><p>{memory.summary}</p><small>{memory.related_record_count} 条关联记录</small></div>
              <button
                type="button"
                disabled={busyKey === `memory:${memory.memory_id}`}
                onClick={() => onMemoryArchive(memory.memory_id, memory.status !== 'archived')}
              >{memory.status === 'archived' ? '恢复参考' : '不再参考'}</button>
            </article>
          ))}
        </section>

        <section className="kernel-module-column">
          <header><div><span>长期认识如何形成</span><h2>主题记忆与可纠正认识</h2></div><small>{modules.length} 个主题</small></header>
          <div className="memory-formation-map" aria-label="长期记忆形成过程">
            <div><b>学习事件</b><span>回答、选择与实践</span></div><i aria-hidden="true">→</i>
            <div><b>Fact</b><span>记录发生了什么</span></div><i aria-hidden="true">→</i>
            <div className="module-stage"><b>Module</b><span>按主题归在一起</span></div><i aria-hidden="true">→</i>
            <div className="claim-stage"><b>Claim</b><span>形成可纠正认识</span></div>
          </div>
          {modules.length === 0 && <p className="formal-empty-copy">当前还没有形成稳定的主题记忆。学习事件会先成为事实；只有相关事实达到本核门槛，才会凝练为 Module 和可纠正的 Claim。</p>}
          {modules.map(module => {
            const title = presentModuleTitle(module)
            return (
              <details key={module.id} className="formal-module-card" open={modules.length <= 2}>
                <summary>
                  <div className="module-node-mark" aria-hidden="true">M</div>
                  <div className="module-summary-copy">
                    <span>主题记忆 Module · {presentModuleScope(module)}</span>
                    <strong>{title}</strong>
                    <p>{presentEvidenceCount(module)}</p>
                  </div>
                  <div className="module-summary-meta"><em>第 {module.version} 版</em><small>{module.claims.length} 条认识</small></div>
                </summary>
                <div className="formal-claim-list">
                  {module.claims.map(claim => (
                    <article key={claim.id} className={claim.status === 'challenged' ? 'challenged' : ''}>
                      <div className="claim-node-mark" aria-hidden="true">C</div>
                      <div className="claim-node-body">
                        <div className="claim-node-heading"><span>可纠正认识 Claim</span><b>{presentVerification(claim)} · {Math.round(claim.confidence * 100)}%</b></div>
                        <p>{presentClaimText(module, claim)}</p>
                        <div className="claim-actions">
                          <button type="button" disabled={busyKey === `claim:${claim.id}`} onClick={() => onClaimAction(claim.id, 'confirm')}>仍然准确</button>
                          <details>
                            <summary>纠正</summary>
                            <textarea value={corrections[claim.id] || ''} onChange={event => setCorrections(previous => ({ ...previous, [claim.id]: event.target.value }))} placeholder="写出你认为更准确的版本" />
                            <button type="button" disabled={!corrections[claim.id]?.trim() || busyKey === `claim:${claim.id}`} onClick={() => onClaimAction(claim.id, 'correct', corrections[claim.id])}>提交纠正</button>
                          </details>
                          <button type="button" className="claim-retract" disabled={busyKey === `claim:${claim.id}`} onClick={() => onClaimAction(claim.id, 'retract')}>撤回这条</button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
                <details className="memory-technical-record">
                  <summary>查看形成依据与技术记录</summary>
                  <div><span>主题键</span><code>{module.subject_key}</code></div>
                  <div><span>事实依据</span><code>{module.evidence_fact_ids.length ? module.evidence_fact_ids.join('、') : '未公开编号'}</code></div>
                  <div><span>版本类型</span><code>{module.revision_kind || 'initial'}</code></div>
                  <pre>{module.summary || module.title}</pre>
                </details>
              </details>
            )
          })}
        </section>
      </div>
    </section>
  )
}
