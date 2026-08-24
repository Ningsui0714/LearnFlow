import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, BookOpenCheck, CalendarClock, Check, ChevronRight,
  Circle, Clock3, FileText, ListTodo, Loader2, Pause, Play, Plus, RefreshCw,
  RotateCcw, Sparkles, Trash2, WandSparkles,
} from 'lucide-react'
import {
  actOnLearningTask, createLearningTask, getLearningTask, listLearningTasks, materializeLearningTask,
  reorderLearningTasks, replanLearningTask, type LearningTask, type LearningTaskPhase,
} from '../services/api'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'

const statusLabel: Record<string, string> = {
  proposed: '待确认', queued: '待开始', active: '进行中', paused: '已暂停',
  completed: '已完成', canceled: '已移除',
}

const phaseLabel: Record<string, string> = {
  learn: '学习', practice: '练习', verify: '验证', consolidate: '复习转交',
}

const methodLabel: Record<string, string> = {
  guided_explanation: '清晰讲解', socratic_dialogue: '苏格拉底追问',
  feynman_dialogue: '费曼复述', evidence_grounded_teaching: '来源讲义',
  verified_micro_learning: '可验证微学习', practice_verification: '正式练习',
  remediation_loop: '纠错闭环', spaced_review: '间隔复习',
}

const requestId = (prefix: string) =>
  globalThis.crypto?.randomUUID?.() || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`

function PhaseRow({ phase, task, busy, onComplete }: {
  phase: LearningTaskPhase
  task: LearningTask
  busy: boolean
  onComplete: (phaseId: string) => void
}) {
  const completed = phase.status === 'completed'
  return (
    <div className={`rounded-xl border px-3 py-3 ${completed ? 'border-emerald-200 bg-emerald-50/60' : 'border-slate-200 bg-white'}`}>
      <div className="flex items-start gap-2.5">
        {completed
          ? <Check size={17} className="mt-0.5 shrink-0 text-emerald-700" />
          : <Circle size={17} className="mt-0.5 shrink-0 text-slate-300" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-800">{phase.title}</p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">{phaseLabel[phase.kind] || phase.kind}</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{phase.purpose}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {phase.methods.map(method => (
              <span key={method} className="rounded-md border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-700">
                {methodLabel[method] || method}
              </span>
            ))}
          </div>
          {!completed && task.status === 'active' && phase.kind === 'learn' && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onComplete(phase.id)}
              className="mt-2 text-[11px] font-medium text-emerald-700 hover:text-emerald-900 disabled:opacity-50"
            >
              我已完成本阶段互动
            </button>
          )}
          {!completed && task.status === 'active' && phase.kind !== 'learn' && (
            <p className="mt-2 text-[11px] leading-4 text-slate-400">
              {phase.kind === 'practice' && '完成真实作答或复述诊断后自动推进'}
              {phase.kind === 'verify' && '无提示作答通过或完成纠错后自动推进'}
              {phase.kind === 'consolidate' && '生成正式复习计划后自动推进'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default function LearningTasksPage() {
  useWorkspaceTitle('学习任务', { kind: 'tasks' })
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = Number(searchParams.get('task') || 0)
  const [tasks, setTasks] = useState<LearningTask[]>([])
  const [selected, setSelected] = useState<LearningTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [includeCompleted, setIncludeCompleted] = useState(false)
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [replanReason, setReplanReason] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [preparingMaterials, setPreparingMaterials] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [response, requested] = await Promise.all([
        listLearningTasks({ include_terminal: includeCompleted }),
        selectedId ? getLearningTask(selectedId).catch(() => null) : Promise.resolve(null),
      ])
      const items = requested && !response.items.some(item => item.id === requested.id)
        ? [requested, ...response.items]
        : response.items
      setTasks(items)
      const target = items.find(item => item.id === selectedId)
        || items.find(item => item.status === 'active')
        || items[0]
        || null
      setSelected(target)
      if (target && target.id !== selectedId) setSearchParams({ task: String(target.id) }, { replace: true })
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '学习任务加载失败')
    } finally {
      setLoading(false)
    }
  }, [includeCompleted, selectedId, setSearchParams])

  useEffect(() => { load() }, [load])

  const queue = useMemo(
    () => tasks.filter(task => ['queued', 'active', 'paused'].includes(task.status)),
    [tasks],
  )
  const proposals = useMemo(() => tasks.filter(task => task.status === 'proposed'), [tasks])
  const terminal = useMemo(() => tasks.filter(task => ['completed', 'canceled'].includes(task.status)), [tasks])

  const replaceTask = (next: LearningTask) => {
    setTasks(items => items.map(item => item.id === next.id ? next : item))
    setSelected(next)
    window.dispatchEvent(new CustomEvent('learnflow:learning-tasks-changed'))
  }

  const runAction = async (action: Parameters<typeof actOnLearningTask>[1]['action'], phaseId = '') => {
    if (!selected || busy) return
    setBusy(true)
    setNotice('')
    try {
      const next = await actOnLearningTask(selected.id, {
        action,
        phase_id: phaseId,
        expected_version: selected.version,
        client_action_id: requestId(`task-${action}`),
      })
      replaceTask(next)
      setNotice(action === 'complete_task' ? '任务闭环已完成；这不等于稳定掌握。' : '')
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '任务更新失败')
    } finally {
      setBusy(false)
    }
  }

  const create = async () => {
    if (!title.trim() || !objective.trim() || busy) return
    setBusy(true)
    try {
      const task = await createLearningTask({
        title: title.trim(), objective: objective.trim(),
        client_request_id: requestId('manual-task'), estimated_minutes: 20,
      })
      setTasks(items => [...items, task])
      setSelected(task)
      setSearchParams({ task: String(task.id) })
      setTitle('')
      setObjective('')
      setShowCreate(false)
      window.dispatchEvent(new CustomEvent('learnflow:learning-tasks-changed'))
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const move = async (task: LearningTask, direction: -1 | 1) => {
    const index = queue.findIndex(item => item.id === task.id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= queue.length || busy) return
    const ids = queue.map(item => item.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    setBusy(true)
    try {
      const response = await reorderLearningTasks(ids, requestId('task-reorder'))
      const byId = new Map(response.items.map(item => [item.id, item]))
      setTasks(items => items.map(item => byId.get(item.id) || item))
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '重排失败')
    } finally {
      setBusy(false)
    }
  }

  const replan = async () => {
    if (!selected || !replanReason.trim() || busy) return
    setBusy(true)
    try {
      const next = await replanLearningTask(selected.id, {
        reason: replanReason.trim(), expected_version: selected.version,
        client_request_id: requestId('task-replan'),
      })
      replaceTask(next)
      setReplanReason('')
      setNotice(`计划已更新为第 ${next.plan_version} 版，已完成阶段被保留。`)
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '调整计划失败')
    } finally {
      setBusy(false)
    }
  }

  const materialize = async () => {
    if (!selected || busy) return
    setBusy(true)
    setPreparingMaterials(true)
    try {
      const next = await materializeLearningTask(selected.id, {
        source_text: sourceText.trim(),
        expected_version: selected.version,
        client_request_id: requestId('task-materialize'),
      })
      replaceTask(next)
      setSourceText('')
      navigate(next.navigation.path)
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '生成讲义与习题失败')
    } finally {
      setBusy(false)
      setPreparingMaterials(false)
    }
  }

  const selectTask = (task: LearningTask) => {
    setSelected(task)
    setSearchParams({ task: String(task.id) })
  }

  const taskList = (items: LearningTask[], reorderable = false) => items.map((task, index) => (
    <div key={task.id} className={`group flex items-center rounded-lg ${selected?.id === task.id ? 'bg-emerald-50' : 'hover:bg-slate-50'}`}>
      <button type="button" onClick={() => selectTask(task)} className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left">
        <span className={`h-2 w-2 shrink-0 rounded-full ${task.status === 'active' ? 'bg-emerald-500' : task.status === 'proposed' ? 'bg-amber-500' : task.status === 'completed' ? 'bg-indigo-400' : 'bg-slate-300'}`} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-slate-700">{task.title}</span>
          <span className="block text-[10px] text-slate-400">{statusLabel[task.status]} · {task.estimated_minutes} 分钟</span>
        </span>
        <ChevronRight size={13} className="text-slate-300" />
      </button>
      {reorderable && (
        <div className="mr-1 hidden gap-0.5 group-hover:flex">
          <button type="button" disabled={index === 0 || busy} onClick={() => move(task, -1)} className="rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700 disabled:opacity-20"><ArrowUp size={12} /></button>
          <button type="button" disabled={index === items.length - 1 || busy} onClick={() => move(task, 1)} className="rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700 disabled:opacity-20"><ArrowDown size={12} /></button>
        </div>
      )}
    </div>
  ))

  return (
    <div className="flex h-full min-h-0 bg-slate-50">
      <aside className="flex w-[310px] shrink-0 flex-col border-r border-slate-200 bg-white">
        <header className="border-b border-slate-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-emerald-700">Learning queue</p>
              <h1 className="mt-1 text-lg font-bold text-slate-900">学习任务</h1>
            </div>
            <button type="button" onClick={() => setShowCreate(value => !value)} className="flex h-8 items-center gap-1 rounded-lg bg-emerald-700 px-2.5 text-xs font-semibold text-white hover:bg-emerald-800"><Plus size={13} />添加</button>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">自由安排要完成的学习闭环；复习有自己的独立队列。</p>
        </header>

        {showCreate && (
          <div className="space-y-2 border-b border-slate-200 bg-emerald-50/50 p-3">
            <input value={title} onChange={event => setTitle(event.target.value)} placeholder="任务名称" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-emerald-400" />
            <textarea value={objective} onChange={event => setObjective(event.target.value)} placeholder="结束时你希望能解释或做出什么？" rows={3} className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-emerald-400" />
            <div className="flex justify-end gap-2"><button type="button" onClick={() => setShowCreate(false)} className="px-2 py-1 text-xs text-slate-500">取消</button><button type="button" disabled={busy || !title.trim() || !objective.trim()} onClick={create} className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">创建并规划</button></div>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {proposals.length > 0 && <><p className="px-2 pb-1 pt-2 text-[10px] font-bold uppercase tracking-[0.12em] text-amber-600">Tutor 建议 · 待确认</p>{taskList(proposals)}</>}
          <p className="px-2 pb-1 pt-3 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">待完成 · {queue.length}</p>
          {taskList(queue, true)}
          {queue.length === 0 && proposals.length === 0 && !loading && <div className="mx-2 mt-3 rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-xs leading-5 text-slate-400">任务队列是空的。<br />可以从对话、项目关卡或这里添加。</div>}
          <button type="button" onClick={() => setIncludeCompleted(value => !value)} className="mt-4 flex w-full items-center gap-2 px-2 py-2 text-xs text-slate-500 hover:text-slate-800"><RotateCcw size={13} />{includeCompleted ? '隐藏历史任务' : '查看历史任务'}</button>
          {includeCompleted && taskList(terminal)}
        </div>
        <button type="button" onClick={() => navigate('/review')} className="m-3 flex items-center justify-between rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-3 text-left text-xs text-indigo-800"><span className="flex items-center gap-2 font-semibold"><CalendarClock size={15} />打开复习任务队列</span><ChevronRight size={14} /></button>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-5 lg:p-8">
        {loading && <div className="flex h-full items-center justify-center text-slate-400"><Loader2 size={20} className="animate-spin" /></div>}
        {!loading && !selected && <div className="flex h-full items-center justify-center text-sm text-slate-400">选择或创建一个学习任务</div>}
        {selected && (
          <div className="mx-auto max-w-4xl">
            {notice && <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">{notice}</div>}
            <header className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500"><span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800">{statusLabel[selected.status]}</span><span>计划 v{selected.plan_version}</span><span className="flex items-center gap-1"><Clock3 size={12} />{selected.estimated_minutes} 分钟</span></div>
                  <h2 className="mt-3 text-2xl font-bold text-slate-900">{selected.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{selected.objective}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span className="rounded-lg bg-indigo-50 px-2 py-1 text-indigo-700">下一步：{selected.runtime.next_action.label}</span>
                    <span>练习 {selected.runtime.evidence.practice_attempts}</span>
                    <span>已通过验证 {selected.runtime.evidence.successful_verifications}</span>
                    <span>复习项 {selected.runtime.evidence.review_items}</span>
                  </div>
                </div>
                <button type="button" onClick={() => navigate(selected.navigation.path)} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"><Play size={13} />打开学习现场</button>
              </div>
              <p className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">{selected.plan.summary}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {selected.status === 'proposed' && <button disabled={busy} onClick={() => runAction('accept')} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white"><Check size={13} className="mr-1 inline" />接受并加入队列</button>}
                {selected.status === 'queued' && <button disabled={busy} onClick={() => runAction('start')} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white"><Play size={13} className="mr-1 inline" />开始任务</button>}
                {selected.status === 'active' && <button disabled={busy} onClick={() => runAction('pause')} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"><Pause size={13} className="mr-1 inline" />暂停</button>}
                {selected.status === 'paused' && <button disabled={busy} onClick={() => runAction('resume')} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white"><Play size={13} className="mr-1 inline" />继续</button>}
                {selected.status === 'canceled' && <button disabled={busy} onClick={() => runAction('reopen')} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"><RotateCcw size={13} className="mr-1 inline" />重新加入</button>}
                {['proposed', 'queued', 'active', 'paused'].includes(selected.status) && <button disabled={busy} onClick={() => runAction('cancel')} className="rounded-lg px-3 py-2 text-xs text-slate-500 hover:bg-red-50 hover:text-red-700"><Trash2 size={13} className="mr-1 inline" />从队列移除</button>}
              </div>
            </header>

            <section className="mt-5 grid gap-5 lg:grid-cols-[1fr,300px]">
              <div>
                <div className="mb-2 flex items-center justify-between"><h3 className="flex items-center gap-2 text-sm font-bold text-slate-800"><ListTodo size={16} />AI 任务计划</h3><span className="text-[10px] text-slate-400">可按互动动态重组</span></div>
                <div className="space-y-2.5">
                  {(selected.plan.phases || []).map(phase => <PhaseRow key={phase.id} phase={phase} task={selected} busy={busy} onComplete={phaseId => runAction('complete_phase', phaseId)} />)}
                </div>
                {selected.status === 'active' && (
                  <button type="button" disabled={busy} onClick={() => runAction('complete_task')} className="mt-3 w-full rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-semibold text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"><BookOpenCheck size={15} className="mr-1.5 inline" />检查并完成任务闭环</button>
                )}
              </div>

              <aside className="space-y-4">
                {!selected.micro_learning_run_id && !selected.checkpoint_id && ['queued', 'active', 'paused'].includes(selected.status) && (
                  <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
                    <h3 className="flex items-center gap-2 text-sm font-bold text-indigo-950"><WandSparkles size={15} />准备学习包</h3>
                    <p className="mt-2 text-xs leading-5 text-indigo-800/80">系统会生成并保存一份讲义文件和一组验证题。它们属于当前任务，不会因为生成完成就被视为掌握。</p>
                    <textarea value={sourceText} onChange={event => setSourceText(event.target.value)} rows={4} placeholder="可选：粘贴题目、教材段落、代码或笔记；留空则使用对话中的原始问题" className="mt-3 w-full resize-y rounded-lg border border-indigo-200 bg-white px-3 py-2 text-xs leading-5 outline-none focus:border-indigo-400" />
                    <button type="button" disabled={busy} onClick={materialize} className="mt-3 w-full rounded-lg bg-indigo-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
                      {preparingMaterials ? '正在准备；模型超时会自动使用稳定模板…' : '生成讲义与验证题并开始'}
                    </button>
                  </div>
                )}
                <div className="rounded-2xl border border-slate-200 bg-white p-4"><h3 className="flex items-center gap-2 text-sm font-bold text-slate-800"><FileText size={15} />任务学习文件</h3><p className="mt-1 text-[10px] leading-4 text-slate-400">讲义负责学习，题目负责练习与验证；只有正式提交进入五核证据。</p>{selected.artifact_refs.length === 0 ? <p className="mt-2 text-xs leading-5 text-slate-400">当前任务还没有保存的讲义或题目。</p> : <div className="mt-2 space-y-1.5">{selected.artifact_refs.map((artifact, index) => <button key={`${artifact.type}-${artifact.id || index}`} type="button" onClick={() => artifact.path && navigate(artifact.path)} className="flex w-full items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-2 text-left text-[11px] text-slate-600 hover:bg-slate-100"><FileText size={12} className="text-emerald-600" /><span className="truncate">{artifact.logical_filename || artifact.type}</span></button>)}</div>}</div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4"><h3 className="flex items-center gap-2 text-sm font-bold text-slate-800"><RefreshCw size={15} />调整计划</h3><textarea value={replanReason} onChange={event => setReplanReason(event.target.value)} rows={3} placeholder="例如：先做一个可视化，再减少讲解、增加代码练习" className="mt-2 w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-emerald-400" /><button type="button" disabled={busy || !replanReason.trim()} onClick={replan} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"><Sparkles size={13} className="mr-1 inline" />让 AI 重组剩余计划</button></div>
                <p className="rounded-xl bg-slate-100 px-3 py-2 text-[10px] leading-4 text-slate-500">{selected.evidence_notice}</p>
              </aside>
            </section>
          </div>
        )}
      </main>
    </div>
  )
}
