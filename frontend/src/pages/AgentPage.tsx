import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowRight, BookOpen, CalendarClock, CheckCircle2, ChevronDown,
  Clock3, FileText, Loader2, MessageSquareText, Sparkles, TrendingUp,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  createMicroLearningRun, getReviewSummary, listMicroLearningRuns,
} from '../services/api'
import type { MicroLearningRun } from '../services/api'


const STATUS_LABELS: Record<string, string> = {
  learning_card: '阅读学习卡',
  teach_back: '等待复述',
  teach_back_feedback: '查看诊断',
  verification: '独立验证',
  remediation: '纠错中',
  paused: '已暂停',
  completed: '本轮完成',
}

export default function AgentPage() {
  const { user } = useAuth()
  const { openPath } = useWorkspace()
  const [goal, setGoal] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [showSource, setShowSource] = useState(false)
  const [recentRuns, setRecentRuns] = useState<MicroLearningRun[]>([])
  const [reviewSummary, setReviewSummary] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  useWorkspaceTitle('学习首页', { kind: 'home' })

  useEffect(() => {
    let active = true
    void Promise.all([
      listMicroLearningRuns(6).catch(() => [] as MicroLearningRun[]),
      getReviewSummary().catch(() => null),
    ]).then(([runs, summary]) => {
      if (!active) return
      setRecentRuns(runs)
      setReviewSummary(summary)
      setLoading(false)
    })
    return () => { active = false }
  }, [])

  const startLearning = async (event: FormEvent) => {
    event.preventDefault()
    if (goal.trim().length < 2 || creating) return
    setCreating(true)
    setError('')
    try {
      const run = await createMicroLearningRun({
        goal: goal.trim(),
        source_text: sourceText.trim(),
        client_request_id: `home-${Date.now()}-${crypto.randomUUID()}`,
      })
      openPath(`/learn/${run.id}`, {
        title: run.goal,
        kind: 'learning_run',
        projectId: run.project_id,
        checkpointId: run.checkpoint_id,
      })
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message || '暂时无法开始学习')
    } finally {
      setCreating(false)
    }
  }

  const resume = (run: MicroLearningRun) => openPath(`/learn/${run.id}`, {
    title: run.goal,
    kind: 'learning_run',
    projectId: run.project_id,
    checkpointId: run.checkpoint_id,
  })

  // The review API's `due` bucket already includes overdue items.
  const dueCount = Number(reviewSummary?.due || 0)

  return (
    <div className="h-full overflow-y-auto bg-[#f6f7f4]">
      <main className="mx-auto max-w-5xl px-5 py-8 sm:px-8 sm:py-12">
        <section className="relative overflow-hidden rounded-[2rem] bg-slate-950 px-6 py-8 text-white shadow-xl sm:px-10 sm:py-11">
          <div className="absolute -right-24 -top-24 h-64 w-64 rounded-full bg-emerald-500/20 blur-3xl" />
          <div className="relative">
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-300/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-200"><Sparkles size={14} />LearnFlow 学习入口</span>
            <h1 className="mt-5 max-w-3xl text-3xl font-bold tracking-tight sm:text-4xl">
              {user?.display_name ? `${user.display_name}，` : ''}今天想真正弄懂什么？
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">输入一个具体目标，系统会直接准备学习卡、费曼复述、验证题与复习计划。先完成一个有证据的闭环，不必先配置项目。</p>

            <form onSubmit={startLearning} className="mt-7 rounded-2xl bg-white p-2 shadow-2xl">
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={goal}
                  onChange={event => setGoal(event.target.value)}
                  maxLength={300}
                  placeholder="例如：15 分钟弄懂什么是贝叶斯定理"
                  className="min-w-0 flex-1 rounded-xl px-4 py-3.5 text-base text-slate-950 outline-none placeholder:text-slate-400"
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={creating || goal.trim().length < 2}
                  className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-emerald-700 px-5 py-3.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {creating ? <Loader2 size={17} className="animate-spin" /> : <ArrowRight size={17} />}
                  {creating ? '正在准备学习内容' : '开始 15 分钟学习'}
                </button>
              </div>
              <button type="button" onClick={() => setShowSource(value => !value)} className="ml-2 mt-1 inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-800"><FileText size={13} />我有一段材料<ChevronDown size={13} className={showSource ? 'rotate-180 transition-transform' : 'transition-transform'} /></button>
              {showSource && (
                <div className="mx-2 mb-2 mt-1 border-t border-slate-100 pt-2">
                  <textarea value={sourceText} onChange={event => setSourceText(event.target.value)} maxLength={20000} rows={5} placeholder="粘贴课堂笔记、文章片段或你想依据的材料。生成内容会优先受这段材料约束。" className="w-full resize-y rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-800 outline-none focus:ring-2 focus:ring-emerald-200" />
                  <p className="mt-1 text-right text-[10px] text-slate-400">{sourceText.length}/20000</p>
                </div>
              )}
            </form>
            {error && <p className="mt-3 rounded-xl bg-rose-500/15 px-3 py-2 text-sm text-rose-200">{error}</p>}
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <div className="flex items-center justify-between gap-3"><div><h2 className="text-base font-semibold text-slate-950">继续上次学习</h2><p className="mt-1 text-xs text-slate-500">每次学习都会保留到具体步骤</p></div><Clock3 size={20} className="text-slate-400" /></div>
            {loading ? (
              <p className="mt-6 flex items-center gap-2 text-sm text-slate-500"><Loader2 size={15} className="animate-spin" />正在读取学习记录…</p>
            ) : recentRuns.length ? (
              <div className="mt-4 divide-y divide-slate-100">
                {recentRuns.slice(0, 4).map(run => (
                  <button key={run.id} type="button" onClick={() => resume(run)} className="group flex w-full items-center gap-3 py-3 text-left">
                    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${run.status === 'completed' ? 'bg-emerald-100 text-emerald-700' : 'bg-indigo-100 text-indigo-700'}`}>{run.status === 'completed' ? <CheckCircle2 size={19} /> : <BookOpen size={19} />}</span>
                    <span className="min-w-0 flex-1"><strong className="block truncate text-sm text-slate-900">{run.goal}</strong><span className="mt-0.5 block text-xs text-slate-500">{STATUS_LABELS[run.state] || run.state} · {run.progress.completed_questions}/{run.progress.total_questions} 道题完成</span></span>
                    <ArrowRight size={16} className="text-slate-300 transition-transform group-hover:translate-x-1 group-hover:text-slate-600" />
                  </button>
                ))}
              </div>
            ) : (
              <div className="mt-5 rounded-2xl bg-slate-50 p-5 text-sm leading-6 text-slate-500">还没有学习记录。上面输入一个具体目标，就会生成你的第一条可恢复学习流程。</div>
            )}
          </div>

          <button type="button" onClick={() => openPath('/review', { title: '全局复习台', kind: 'review' })} className="group rounded-3xl border border-indigo-200 bg-indigo-50 p-5 text-left shadow-sm transition hover:border-indigo-300 hover:shadow-md sm:p-6">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-700 text-white"><CalendarClock size={21} /></span>
            <h2 className="mt-5 text-base font-semibold text-indigo-950">今天的复习</h2>
            <p className="mt-2 text-sm leading-6 text-indigo-900/75">{loading ? '正在读取复习计划…' : dueCount ? `有 ${dueCount} 项到期或逾期。用一次短检索把理解变得更稳定。` : '今天没有到期项。完成新的微学习后，系统会自动安排复习。'}</p>
            <span className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-indigo-800">打开复习台 <ArrowRight size={15} className="transition-transform group-hover:translate-x-1" /></span>
          </button>
        </section>

        <section className="mt-8">
          <div className="flex items-end justify-between gap-3"><div><h2 className="text-base font-semibold text-slate-950">需要更长的学习方式？</h2><p className="mt-1 text-xs text-slate-500">项目式学习现在是一种深度模式，而不是进入系统前的必选配置。</p></div><span className="hidden items-center gap-1 text-xs text-slate-400 sm:inline-flex"><MessageSquareText size={13} />右侧 Tutor 也可推荐合适模式</span></div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <button type="button" onClick={() => openPath('/projects', { title: '学习项目', kind: 'projects' })} className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-emerald-300"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800"><BookOpen size={17} /></span><strong className="mt-3 block text-sm text-slate-900">项目式深度学习</strong><span className="mt-1 block text-xs leading-5 text-slate-500">适合多周目标：组织来源、路线、讲义、代码实践与成果。</span></button>
            <button type="button" onClick={() => openPath('/growth', { title: '我的成长', kind: 'growth' })} className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-indigo-300"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-100 text-indigo-800"><TrendingUp size={17} /></span><strong className="mt-3 block text-sm text-slate-900">查看我的成长</strong><span className="mt-1 block text-xs leading-5 text-slate-500">了解当前状态、真实进步和系统记住的学习情况。</span></button>
          </div>
        </section>
      </main>
    </div>
  )
}
