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
}

export default function LearnerProfilePage({
  connection, snapshot, busyKey, error, onRefresh, onOpenPath, onMemoryArchive, onClaimAction,
}: Props) {
  const [activeKernel, setActiveKernel] = useState<KernelName>('structure')
  const [corrections, setCorrections] = useState<Record<number, string>>({})
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
