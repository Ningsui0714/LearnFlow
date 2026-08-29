import { useEffect, useMemo, useState } from 'react'
import {
  explainRoleCapability, generateRoleCapabilityPackage, iterateRoleCapabilityPackage,
  loadRoleCapabilityPlugin, type RoleCapabilityNode, type RoleCapabilityPluginView,
} from './formal-runtime'

function requestKey(prefix: string) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${suffix}`
}

export default function RoleCapabilityPluginPanel({ projectId, projectName, projectDescription, sourceIds }: {
  projectId: number; projectName: string; projectDescription: string; sourceIds: number[]
}) {
  const [view, setView] = useState<RoleCapabilityPluginView>()
  const [roleTitle, setRoleTitle] = useState(projectName)
  const [taskSeeds, setTaskSeeds] = useState('')
  const [question, setQuestion] = useState('这个岗位最核心的任务和能力是什么？')
  const [explanation, setExplanation] = useState<Record<string, any>>()
  const [newTask, setNewTask] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refresh = async () => {
    const next = await loadRoleCapabilityPlugin(projectId)
    setView(next)
    if (next.package?.role_title) setRoleTitle(next.package.role_title)
    return next
  }
  useEffect(() => { void refresh().catch(failure => setError(failure instanceof Error ? failure.message : '岗位插件读取失败')) }, [projectId])
  const grouped = useMemo(() => (view?.snapshot?.graph.nodes || []).reduce<Record<string, RoleCapabilityNode[]>>((result, node) => {
    ;(result[node.type] ||= []).push(node)
    return result
  }, {}), [view])

  const generate = async () => {
    setBusy('generate'); setError('')
    try {
      setView(await generateRoleCapabilityPackage(projectId, {
        role_title: roleTitle.trim(), role_summary: projectDescription, source_ids: sourceIds,
        task_seeds: taskSeeds.split(/\n|；|;/).map(item => item.trim()).filter(Boolean),
        idempotency_key: requestKey('role-generate'),
      }))
    } catch (failure) { setError(failure instanceof Error ? failure.message : '岗位包生成失败') }
    finally { setBusy('') }
  }
  const explain = async () => {
    if (!question.trim()) return
    setBusy('explain'); setError('')
    try { setExplanation((await explainRoleCapability(projectId, question.trim())).explanation) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '岗位解释失败') }
    finally { setBusy('') }
  }
  const iterate = async () => {
    const roleId = view?.snapshot?.graph.role.id
    if (!newTask.trim() || !roleId) return
    setBusy('iterate'); setError('')
    try {
      setView(await iterateRoleCapabilityPackage(projectId, {
        objective: `补充岗位任务：${newTask.trim()}`, target_ids: [roleId],
        operations: [{ op: 'add_node', type: 'task', label: newTask.trim(), parent_id: roleId, evidence_refs: ['user:explicit-plugin-iteration'] }],
        idempotency_key: requestKey('role-iterate'),
      }))
      setNewTask('')
    } catch (failure) { setError(failure instanceof Error ? failure.message : '岗位快照迭代失败') }
    finally { setBusy('') }
  }

  return <div className="role-plugin">
    <div className="role-plugin-boundary">Learning Design 插件 · 岗位制品不等于学习者掌握</div>
    {!view?.package && <section className="role-plugin-card">
      <strong>生成首个岗位能力包</strong>
      <label>岗位名称<input value={roleTitle} onChange={event => setRoleTitle(event.target.value)} /></label>
      <label>任务种子（可选，每行一项）<textarea value={taskSeeds} onChange={event => setTaskSeeds(event.target.value)} placeholder={'设计 Agent 工具契约\n构建离线评测集'} /></label>
      <small>{sourceIds.length ? `将固定引用 ${sourceIds.length} 个已处理来源` : '没有项目来源时，至少填写一个任务种子'}</small>
      <button type="button" disabled={busy !== '' || !roleTitle.trim() || (!sourceIds.length && !taskSeeds.trim())} onClick={() => void generate()}>{busy === 'generate' ? '正在生成…' : '生成并校验'}</button>
    </section>}
    {view?.snapshot && <>
      <section className="role-plugin-version"><div><strong>{view.package?.role_title}</strong><span>v{view.snapshot.version} · {view.snapshot.root_hash.slice(0, 12)}</span></div><i>{view.snapshot.validation.valid ? '协议通过' : '协议异常'}</i></section>
      <section className="role-plugin-stats">{(['task', 'capability', 'knowledge_skill'] as const).map(kind => <div key={kind}><strong>{grouped[kind]?.length || 0}</strong><span>{kind === 'task' ? '任务' : kind === 'capability' ? '能力' : '知识技能'}</span></div>)}</section>
      <section className="role-plugin-card"><strong>图谱对象</strong><div className="role-plugin-nodes">{view.snapshot.graph.nodes.filter(node => node.type !== 'role').slice(0, 18).map(node => <article key={node.id}><span>{node.type === 'task' ? '任务' : node.type === 'capability' ? '能力' : '知识'}</span><div><strong>{node.label}</strong><small>{node.knowledge_state} · {node.evidence_refs.length} 条依据</small></div></article>)}</div></section>
      <section className="role-plugin-card"><strong>解释 Agent</strong><textarea value={question} onChange={event => setQuestion(event.target.value)} /><button type="button" disabled={busy !== '' || !question.trim()} onClick={() => void explain()}>{busy === 'explain' ? '正在读取固定快照…' : '基于证据解释'}</button>{explanation && <div className="role-plugin-answer"><p>{String(explanation.answer || '')}</p><small>引用：{(explanation.citations || []).join('、') || '用户显式任务种子'} · 不改变五核</small></div>}</section>
      <section className="role-plugin-card"><strong>迭代 Agent</strong><p>显式提出一项新任务；运行时先建合同、检查候选，再决定是否形成不可变后继快照。</p><input value={newTask} onChange={event => setNewTask(event.target.value)} placeholder="例如：监控线上质量与成本" /><button type="button" disabled={busy !== '' || !newTask.trim()} onClick={() => void iterate()}>{busy === 'iterate' ? '正在检查候选…' : '形成迭代候选'}</button></section>
    </>}
    {error && <div className="project-panel-error">{error}</div>}
  </div>
}
