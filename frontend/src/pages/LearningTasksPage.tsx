import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, BookOpenCheck, CalendarClock, Check, ChevronRight,
  Circle, Clock3, ListTodo, Loader2, Pause, Play, Plus, RefreshCw,
  RotateCcw, Sparkles, Trash2,
} from 'lucide-react'
import {
  actOnLearningTask, createLearningTask, getLearningTask, listLearningTasks, materializeLearningTask,
  reorderLearningTasks, replanLearningTask, type LearningTask, type LearningTaskPhase,
} from '../services/api'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import LearningTaskSurfaceNotice from '../components/learning-task/LearningTaskSurfaceNotice'
import LearningPackagePanel from '../components/learning-task/LearningPackagePanel'
import {
  learningTaskOriginLabel,
  learningTaskPresentation,
  learningTaskStatusLabel,
} from '../components/learning-task/taskPresentation'

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

  const runAction = async (action: Parameters<typeof actOnLearningTask>[1]['action'], phaseId = ''): Promise<LearningTask | null> => {
    if (!selected || busy) return null
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
      return next
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '任务更新失败')
      return null
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

  const continueLearning = async () => {
    if (!selected || busy) return
    if (selected.status === 'proposed') {
      await runAction('accept')
      return
    }
    if (selected.status === 'canceled') {
      await runAction('reopen')
      return
    }
    if (selected.status === 'queued' || selected.status === 'paused') {
      const next = await runAction(selected.status === 'queued' ? 'start' : 'resume')
      if (next && next.navigation.kind !== 'task') navigate(next.navigation.path)
      return
    }
    if (selected.status === 'active' && selected.navigation.kind === 'task') {
      await materialize()
      return
    }
    if (selected.status === 'active') navigate(selected.navigation.path)
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
          <span className="block text-[10px] text-slate-400">{learningTaskStatusLabel[task.status]} · {learningTaskOriginLabel(task)} · {task.estimated_minutes} 分钟</span>
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
              <h1 className="mt-1 text-lg font-bold text-slate-900">学习任务控制台</h1>
            </div>
            <button type="button" onClick={() => setShowCreate(value => !value)} className="flex h-8 items-center gap-1 rounded-lg bg-emerald-700 px-2.5 text-xs font-semibold text-white hover:bg-emerald-800"><Plus size={13} />添加</button>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">这里管理顺序、计划和学习包；“继续学习”会返回对话、项目关卡或专注学习。</p>
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
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500"><span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800">{learningTaskStatusLabel[selected.status]}</span><span>{learningTaskOriginLabel(selected)}</span><span>计划 v{selected.plan_version}</span><span className="flex items-center gap-1"><Clock3 size={12} />{selected.estimated_minutes} 分钟</span></div>
                  <h2 className="mt-3 text-2xl font-bold text-slate-900">{selected.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{selected.objective}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span className="rounded-lg bg-indigo-50 px-2 py-1 text-indigo-700">下一步：{selected.runtime.next_action.label}</span>
                    <span>练习 {selected.runtime.evidence.practice_attempts}</span>
                    <span>已通过验证 {selected.runtime.evidence.successful_verifications}</span>
                    <span>复习项 {selected.runtime.evidence.review_items}</span>
                  </div>
                </div>
                {!['completed'].includes(selected.status) && (
                  <button type="button" disabled={busy} onClick={continueLearning} className="flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
                    <Play size={13} />{learningTaskPresentation(selected, 'task').primaryActionLabel}
                  </button>
                )}
              </div>
              <LearningTaskSurfaceNotice task={selected} currentSurface="task" className="mt-4" />
              <p className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">{selected.plan.summary}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {selected.status === 'active' && <button disabled={busy} onClick={() => runAction('pause')} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700"><Pause size={13} className="mr-1 inline" />暂停</button>}
                {['proposed', 'queued', 'active', 'paused'].includes(selected.status) && <button disabled={busy} onClick={() => runAction('cancel')} className="rounded-lg px-3 py-2 text-xs text-slate-500 hover:bg-red-50 hover:text-red-700"><Trash2 size={13} className="mr-1 inline" />从队列移除</button>}
              </div>
            </header>

            <LearningPackagePanel
              task={selected}
              sourceText={sourceText}
              preparing={preparingMaterials}
              disabled={busy}
              onSourceTextChange={setSourceText}
              onPrepare={materialize}
              onNavigate={navigate}
            />

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
