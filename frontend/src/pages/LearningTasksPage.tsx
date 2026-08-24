import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, CalendarClock, CheckCircle2, Clock3, FileText,
  ListTodo, Loader2, MessageSquareText, Pause, Play, RotateCcw, Trash2,
} from 'lucide-react'
import {
  actOnLearningTask, listLearningTasks, reorderLearningTasks,
  type LearningTask,
} from '../services/api'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  learningTaskOriginLabel,
  learningTaskStatusLabel,
} from '../components/learning-task/taskPresentation'

const requestId = (prefix: string) =>
  globalThis.crypto?.randomUUID?.() || `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`

function returnLabel(task: LearningTask) {
  if (task.origin_navigation.kind === 'conversation') return '回到原对话'
  if (task.origin_navigation.kind === 'checkpoint') return '进入项目关卡'
  if (task.navigation.kind === 'focused_learning') return '打开学习文件'
  return '查看来源'
}

export default function LearningTasksPage() {
  useWorkspaceTitle('学习任务队列', { kind: 'tasks' })
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const focusedId = Number(searchParams.get('task') || 0)
  const [tasks, setTasks] = useState<LearningTask[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [includeCompleted, setIncludeCompleted] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await listLearningTasks({ include_terminal: includeCompleted })
      setTasks(response.items)
      setNotice('')
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '学习任务队列加载失败')
    } finally {
      setLoading(false)
    }
  }, [includeCompleted])

  useEffect(() => { void load() }, [load])

  const proposals = useMemo(() => tasks.filter(task => task.status === 'proposed'), [tasks])
  const queue = useMemo(() => tasks.filter(task => ['queued', 'active', 'paused'].includes(task.status)), [tasks])
  const history = useMemo(() => tasks.filter(task => ['completed', 'canceled'].includes(task.status)), [tasks])

  const replaceTask = (next: LearningTask) => {
    setTasks(items => items.map(item => item.id === next.id ? next : item))
    window.dispatchEvent(new CustomEvent('learnflow:learning-tasks-changed'))
  }

  const act = async (task: LearningTask, action: 'accept' | 'start' | 'resume' | 'pause' | 'cancel' | 'reopen') => {
    if (busyId) return false
    setBusyId(task.id)
    try {
      const next = await actOnLearningTask(task.id, {
        action,
        expected_version: task.version,
        client_action_id: requestId(`queue-${action}`),
      })
      replaceTask(next)
      return true
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '任务状态没有更新成功')
      return false
    } finally {
      setBusyId(null)
    }
  }

  const move = async (task: LearningTask, direction: -1 | 1) => {
    const index = queue.findIndex(item => item.id === task.id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= queue.length || busyId) return
    const ids = queue.map(item => item.id)
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    setBusyId(task.id)
    try {
      const response = await reorderLearningTasks(ids, requestId('queue-reorder'))
      const byId = new Map(response.items.map(item => [item.id, item]))
      setTasks(items => items.map(item => byId.get(item.id) || item))
    } catch (error: any) {
      setNotice(error?.response?.data?.detail || '任务顺序没有保存成功')
    } finally {
      setBusyId(null)
    }
  }

  const openOrigin = async (task: LearningTask) => {
    if (task.status === 'proposed') {
      await act(task, 'accept')
      return
    }
    if (task.status === 'queued' && !await act(task, 'start')) return
    if (task.status === 'paused' && !await act(task, 'resume')) return
    navigate(task.origin_navigation.path || task.navigation.path)
  }

  const renderTask = (task: LearningTask, index: number, reorderable: boolean) => {
    const focused = task.id === focusedId
    const currentPhase = task.runtime.current_phase
    const artifacts = task.artifact_refs.filter(item => item.path)
    return (
      <article key={task.id} className={`rounded-2xl border bg-white p-4 shadow-sm transition ${focused ? 'border-emerald-400 ring-2 ring-emerald-100' : 'border-slate-200'}`} data-testid={`learning-task-${task.id}`}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
              <span className={`rounded-full px-2 py-0.5 font-semibold ${task.status === 'active' ? 'bg-emerald-100 text-emerald-800' : task.status === 'proposed' ? 'bg-amber-100 text-amber-800' : 'bg-slate-100'}`}>{learningTaskStatusLabel[task.status]}</span>
              <span>{learningTaskOriginLabel(task)}</span>
              <span className="inline-flex items-center gap-1"><Clock3 size={11} />{task.estimated_minutes} 分钟</span>
            </div>
            <h2 className="mt-2 text-base font-bold text-slate-900">{task.title}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-600">{task.objective}</p>
            {currentPhase?.title && (
              <p className="mt-2 rounded-lg bg-slate-50 px-2.5 py-2 text-[11px] text-slate-600">
                当前阶段：<strong className="text-slate-800">{currentPhase.title}</strong>
                {currentPhase.purpose ? ` · ${currentPhase.purpose}` : ''}
              </p>
            )}
            {artifacts.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {artifacts.map((item, artifactIndex) => (
                  <button key={`${item.type}-${item.id || artifactIndex}`} type="button" onClick={() => item.path && navigate(item.path)} className="inline-flex items-center gap-1 rounded-lg border border-indigo-100 bg-indigo-50 px-2 py-1 text-[10px] font-medium text-indigo-700">
                    <FileText size={11} />{item.logical_filename || '学习文件'}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 sm:max-w-[250px] sm:justify-end">
            {reorderable && (
              <>
                <button type="button" title="上移" disabled={index === 0 || !!busyId} onClick={() => move(task, -1)} className="rounded-lg border border-slate-200 p-2 text-slate-500 disabled:opacity-25"><ArrowUp size={13} /></button>
                <button type="button" title="下移" disabled={index === queue.length - 1 || !!busyId} onClick={() => move(task, 1)} className="rounded-lg border border-slate-200 p-2 text-slate-500 disabled:opacity-25"><ArrowDown size={13} /></button>
              </>
            )}
            {!['completed', 'canceled'].includes(task.status) && (
              <button type="button" disabled={busyId === task.id} onClick={() => void openOrigin(task)} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
                {busyId === task.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                {task.status === 'proposed' ? '加入队列' : returnLabel(task)}
              </button>
            )}
            {task.status === 'active' && <button type="button" title="暂停" disabled={!!busyId} onClick={() => act(task, 'pause')} className="rounded-lg border border-slate-200 p-2 text-slate-500"><Pause size={13} /></button>}
            {['proposed', 'queued', 'active', 'paused'].includes(task.status) && <button type="button" title="移除" disabled={!!busyId} onClick={() => act(task, 'cancel')} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-700"><Trash2 size={13} /></button>}
            {task.status === 'canceled' && <button type="button" disabled={!!busyId} onClick={() => act(task, 'reopen')} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600">重新加入</button>}
          </div>
        </div>
      </article>
    )
  }

  return (
    <div className="h-full overflow-y-auto bg-slate-50">
      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:py-9">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-emerald-700">Learning task queue</p>
            <h1 className="mt-1 text-2xl font-bold text-slate-950">学习任务队列</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">这里只负责安排、暂停和返回。对话生成的任务回原 Chat 学，项目任务回对应关卡；讲义与练习作为文件工作台单独打开。</p>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => navigate('/agent')} className="inline-flex items-center gap-1.5 rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-semibold text-white"><MessageSquareText size={14} />去 Chat 创建任务</button>
            <button type="button" onClick={() => navigate('/review')} className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-xs font-semibold text-indigo-800"><CalendarClock size={14} />复习队列</button>
          </div>
        </header>

        {notice && <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">{notice}</p>}
        {loading ? (
          <div className="flex min-h-[45vh] items-center justify-center text-sm text-slate-400"><Loader2 size={18} className="mr-2 animate-spin" />正在加载任务队列…</div>
        ) : (
          <div className="mt-7 space-y-7">
            {proposals.length > 0 && (
              <section>
                <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-amber-800"><ListTodo size={16} />Tutor 建议 · 待确认</h2>
                <div className="space-y-3">{proposals.map((task, index) => renderTask(task, index, false))}</div>
              </section>
            )}
            <section>
              <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-800"><ListTodo size={16} />待完成 · {queue.length}</h2>
              {queue.length > 0 ? <div className="space-y-3">{queue.map((task, index) => renderTask(task, index, true))}</div> : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-400">队列是空的。你可以在 Chat 中从一个问题开始，或从项目关卡进入任务。</div>
              )}
            </section>
            <section>
              <button type="button" onClick={() => setIncludeCompleted(value => !value)} className="flex items-center gap-2 text-xs font-medium text-slate-500"><RotateCcw size={13} />{includeCompleted ? '隐藏历史任务' : '查看历史任务'}</button>
              {includeCompleted && history.length > 0 && <div className="mt-3 space-y-3">{history.map((task, index) => renderTask(task, index, false))}</div>}
              {includeCompleted && history.length === 0 && <p className="mt-3 text-xs text-slate-400"><CheckCircle2 size={13} className="mr-1 inline" />还没有历史任务</p>}
            </section>
          </div>
        )}
      </main>
    </div>
  )
}
