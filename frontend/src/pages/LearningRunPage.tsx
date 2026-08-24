import { useCallback, useEffect, useState } from 'react'
import {
  ArrowLeft, BookOpen, CalendarClock, CheckCircle2, ChevronRight,
  Lightbulb, Loader2, MessageCircle, Pause, Play, RefreshCw,
  RotateCcw, Send, ShieldCheck, Sparkles, X,
} from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import RemediationPanel from '../components/exercise/RemediationPanel'
import TutorPanel from '../components/tutor/TutorPanel'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  advanceMicroLearningRun,
  getMicroLearningRun,
  regenerateMicroLearningRun,
  submitConcept,
  submitMicroLearningTeachBack,
  syncMicroLearningRun,
} from '../services/api'
import type { MicroLearningQuestion, MicroLearningRun } from '../services/api'


const STEP_LABELS = ['讲义', '引导练习', '练习反馈', '独立验证', '复习安排']

function actionId(prefix: string) {
  return `${prefix}-${Date.now()}-${crypto.randomUUID()}`
}

function LearningCardContent({ card }: { card: MicroLearningRun['learning_card'] }) {
  return (
    <>
      <section>
        <h2 className="text-sm font-semibold text-slate-900">先抓住这几个关键关系</h2>
        <ol className="mt-3 space-y-3">
          {(card.key_points || []).map((point, index) => (
            <li key={`${index}-${point}`} className="flex gap-3 text-sm leading-7 text-slate-700"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{index + 1}</span><span>{point}</span></li>
          ))}
        </ol>
      </section>
      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-2xl bg-indigo-50 p-4"><h2 className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><Sparkles size={15} />具体例子</h2><p className="mt-2 text-sm leading-6 text-indigo-900/80">{card.example}</p></section>
        <section className="rounded-2xl bg-amber-50 p-4"><h2 className="flex items-center gap-2 text-sm font-semibold text-amber-950"><Lightbulb size={15} />容易混淆</h2><p className="mt-2 text-sm leading-6 text-amber-900/80">{card.common_confusion}</p></section>
      </div>
      <div className="rounded-2xl border border-slate-200 p-4 text-sm text-slate-600"><strong className="text-slate-900">本轮完成标准：</strong>{card.success_criteria}</div>
    </>
  )
}

function QuestionCard({
  question, busy, result, retrying, onSubmit, onContinue,
}: {
  question: MicroLearningQuestion
  busy: boolean
  result: any
  retrying: boolean
  onSubmit: (answers: number[]) => void
  onContinue: () => void
}) {
  const [answers, setAnswers] = useState<number[]>([])

  const toggle = (index: number) => {
    if (result) return
    setAnswers(current => question.q_type === 'multi'
      ? current.includes(index) ? current.filter(item => item !== index) : [...current, index]
      : [index])
  }

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="rounded-full bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700">
          {retrying ? '原题重做' : `第 ${question.order} 题`}
        </span>
        <span>{question.q_type === 'multi' ? '多选题' : '单选题'}</span>
        <span>·</span>
        <span>{question.learning_target}</span>
      </div>
      <h2 className="mt-4 text-xl font-semibold leading-8 text-slate-950">{question.question}</h2>
      <div className="mt-5 space-y-3">
        {question.options.map((option, index) => {
          const selected = answers.includes(index)
          const correct = result?.answer_indexes?.includes(index)
          const wrongSelected = result && selected && !correct
          return (
            <button
              key={`${question.id}-${index}`}
              type="button"
              onClick={() => toggle(index)}
              className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left text-sm leading-6 transition ${
                correct ? 'border-emerald-300 bg-emerald-50 text-emerald-950'
                  : wrongSelected ? 'border-rose-300 bg-rose-50 text-rose-900'
                    : selected ? 'border-indigo-400 bg-indigo-50 text-indigo-950'
                      : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
              }`}
            >
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
                selected ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-slate-300 text-slate-500'
              }`}>{String.fromCharCode(65 + index)}</span>
              <span>{option}</span>
            </button>
          )
        })}
      </div>
      {result ? (
        <div className={`mt-5 rounded-2xl border p-4 ${result.correct ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
          <p className={`font-semibold ${result.correct ? 'text-emerald-800' : 'text-rose-800'}`}>
            {result.correct ? '这次独立回答正确' : '这次回答还没有通过'}
          </p>
          {result.explanation && <p className="mt-2 text-sm leading-6 text-slate-700">{result.explanation}</p>}
          {result.correct && (
            <button
              type="button"
              onClick={onContinue}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800"
            >
              继续 <ChevronRight size={16} />
            </button>
          )}
        </div>
      ) : (
        <button
          type="button"
          disabled={busy || answers.length === 0}
          onClick={() => onSubmit(answers)}
          className="mt-5 inline-flex items-center gap-2 rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          提交验证
        </button>
      )}
    </section>
  )
}

export default function LearningRunPage() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const numericRunId = Number(runId)
  const [run, setRun] = useState<MicroLearningRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [teachBack, setTeachBack] = useState('')
  const [questionResult, setQuestionResult] = useState<any>(null)
  const [pendingRun, setPendingRun] = useState<MicroLearningRun | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [remediation, setRemediation] = useState<any>(null)
  const [tutorOpen, setTutorOpen] = useState(false)

  useWorkspaceTitle(run?.goal || '专注学习', {
    kind: 'learning_run',
    projectId: run?.project_id,
    checkpointId: run?.checkpoint_id,
  })

  const load = useCallback(async () => {
    if (!Number.isInteger(numericRunId) || numericRunId <= 0) {
      setError('学习记录地址无效')
      setLoading(false)
      return
    }
    try {
      const next = await getMicroLearningRun(numericRunId)
      setRun(next)
      setRemediation(next.remediation || null)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message || '读取学习记录失败')
    } finally {
      setLoading(false)
    }
  }, [numericRunId])

  useEffect(() => {
    void load()
  }, [load])

  const updateFlow = async (
    action: 'complete_card' | 'continue_after_feedback' | 'pause' | 'resume',
  ) => {
    if (!run) return
    setBusy(action)
    setError('')
    try {
      const next = await advanceMicroLearningRun(run.id, {
        action,
        expected_version: run.version,
        client_action_id: actionId(action),
      })
      setRun(next)
      setQuestionResult(null)
      setPendingRun(null)
      setRetrying(false)
      setRemediation(next.remediation || null)
      if (action === 'complete_card' && searchParams.has('view')) {
        const nextParams = new URLSearchParams(searchParams)
        nextParams.delete('view')
        setSearchParams(nextParams, { replace: true })
      }
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const regenerateLearningPackage = async () => {
    if (!run || busy) return
    setBusy('regenerate')
    setError('')
    try {
      const next = await regenerateMicroLearningRun(run.id, {
        expected_version: run.version,
        client_request_id: actionId('regenerate-learning-package'),
      })
      setRun(next)
      setTeachBack('')
      setQuestionResult(null)
      setPendingRun(null)
      setRemediation(null)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message || '学习包重新生成失败')
    } finally {
      setBusy('')
    }
  }

  const submitTeachBack = async () => {
    if (!run || teachBack.trim().length < 20) return
    setBusy('teach-back')
    setError('')
    try {
      setRun(await submitMicroLearningTeachBack(run.id, {
        response: teachBack.trim(),
        expected_version: run.version,
        client_submission_id: actionId('teach-back'),
      }))
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const syncAfterAttempt = async (baseRun: MicroLearningRun) => syncMicroLearningRun(
    baseRun.id,
    { expected_version: baseRun.version, client_action_id: actionId('attempt-sync') },
  )

  const submitQuestion = async (answers: number[]) => {
    if (!run?.current_question) return
    setBusy('question')
    setError('')
    try {
      const result = await submitConcept(
        run.checkpoint_id,
        run.current_question.id,
        answers,
        retrying ? 'guided' : 'none',
        retrying ? remediation?.id : undefined,
        retrying ? 'retry' : 'original',
        actionId('concept'),
      )
      if (retrying) {
        const next = await syncAfterAttempt(run)
        setRun(next)
        setRemediation(result.remediation || next.remediation || null)
        setRetrying(false)
        setQuestionResult(null)
      } else if (result.correct) {
        setQuestionResult(result)
        setPendingRun(await syncAfterAttempt(run))
      } else {
        const next = await syncAfterAttempt(run)
        setRun(next)
        setRemediation(result.remediation || next.remediation || null)
        setQuestionResult(null)
      }
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const continueAfterCorrect = () => {
    if (!pendingRun) return
    setRun(pendingRun)
    setRemediation(pendingRun.remediation || null)
    setPendingRun(null)
    setQuestionResult(null)
  }

  const handleRemediationChange = async (nextRemediation: any) => {
    setRemediation(nextRemediation)
    if (!run || nextRemediation?.status !== 'completed') return
    setBusy('remediation-sync')
    try {
      const next = await syncAfterAttempt(run)
      setRun(next)
      setRemediation(next.remediation || null)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const lectureReferenceOpen = Boolean(
    run && run.state !== 'learning_card' && searchParams.get('view') === 'lecture',
  )

  const openLectureReference = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.set('view', 'lecture')
    setSearchParams(next)
  }, [searchParams, setSearchParams])

  const closeLectureReference = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.delete('view')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!lectureReferenceOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeLectureReference()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [closeLectureReference, lectureReferenceOpen])

  if (loading) {
    return <div className="flex h-screen items-center justify-center bg-slate-50 text-slate-500"><Loader2 className="mr-2 animate-spin" />正在恢复学习现场…</div>
  }

  if (!run) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-50 px-6 text-center">
        <h1 className="text-xl font-semibold text-slate-900">无法打开这次学习</h1>
        <p className="mt-2 text-sm text-rose-700">{error}</p>
        <button type="button" onClick={() => navigate('/agent')} className="mt-5 rounded-xl bg-slate-900 px-4 py-2 text-sm text-white">返回首页</button>
      </div>
    )
  }

  const card = run.learning_card
  const paused = run.state === 'paused'
  const displayQuestion = run.current_question && (run.state === 'verification' || retrying)
  const originNavigation = run.learning_task?.origin_navigation
  const needsQualityRefresh = (
    run.state === 'learning_card'
    && (
      card.quality_status === 'blocked'
      || (
        card.generation_mode === 'deterministic_fallback'
        && card.generation_source === 'generic_goal_scaffold'
      )
    )
  )
  return (
    <div className="min-h-screen bg-[#f6f7f4] text-slate-900">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <button type="button" onClick={() => navigate(originNavigation?.path || run.learning_task?.path || '/agent')} className="flex h-9 w-9 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100" title={originNavigation?.kind === 'conversation' ? '返回原对话' : originNavigation?.kind === 'checkpoint' ? '返回项目关卡' : '返回任务控制台'}><ArrowLeft size={19} /></button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-slate-900">{run.goal}</p>
            <p className="text-[11px] text-slate-500">学习文件工作台 · 讲义与独立验证附件 · 第 {Math.max(1, run.progress.current)}/{run.progress.total} 步</p>
          </div>
          {run.status !== 'completed' && (
            <button
              type="button"
              disabled={!!busy || !!pendingRun}
              onClick={() => updateFlow(paused ? 'resume' : 'pause')}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              {paused ? <Play size={14} /> : <Pause size={14} />}{paused ? '继续' : '稍后继续'}
            </button>
          )}
          {run.state !== 'learning_card' && (
            <button type="button" onClick={openLectureReference} className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-100"><BookOpen size={14} />回看讲义</button>
          )}
          <button type="button" onClick={() => setTutorOpen(true)} className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-800"><MessageCircle size={14} />问 Tutor</button>
        </div>
        <div className="h-1 bg-slate-100">
          <div className="h-full bg-emerald-600 transition-all" style={{ width: `${Math.max(4, run.progress.current / run.progress.total * 100)}%` }} />
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-7 sm:px-6 sm:py-10">
        {needsQualityRefresh && (
          <section className="mb-5 flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 sm:flex-row sm:items-center sm:justify-between" data-testid="learning-package-quality-warning">
            <div>
              <p className="text-sm font-semibold">讲义未通过内容质量门槛</p>
              <p className="mt-1 text-xs leading-5 text-amber-800">当前没有可靠模型结果或受审核主题模板，因此不会让通用占位内容进入复述、练习和证据流程。检查模型设置后可原位重建，任务与对话入口不会改变。</p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <button type="button" onClick={() => navigate('/settings')} className="inline-flex items-center justify-center rounded-xl border border-amber-300 bg-white px-4 py-2.5 text-xs font-semibold text-amber-950">检查模型设置</button>
              <button type="button" disabled={busy === 'regenerate'} onClick={regenerateLearningPackage} className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-amber-900 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">
                {busy === 'regenerate' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}重试生成讲义
              </button>
            </div>
          </section>
        )}
        <div className="mb-7 grid grid-cols-5 gap-1 sm:gap-2" aria-label="学习步骤">
          {STEP_LABELS.map((label, index) => (
            <div key={label} className={`text-center text-[10px] sm:text-xs ${index + 1 <= run.progress.current ? 'font-medium text-emerald-700' : 'text-slate-400'}`}>
              <span className={`mx-auto mb-1 flex h-6 w-6 items-center justify-center rounded-full ${index + 1 < run.progress.current ? 'bg-emerald-600 text-white' : index + 1 === run.progress.current ? 'border-2 border-emerald-600 bg-white text-emerald-700' : 'bg-slate-200 text-slate-500'}`}>
                {index + 1 < run.progress.current ? <CheckCircle2 size={14} /> : index + 1}
              </span>
              {label}
            </div>
          ))}
        </div>
        <div className="mb-6 rounded-2xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-xs leading-5 text-indigo-950" data-testid="learning-package-usage-note">
          <strong>这是一份按顺序使用的学习包：</strong>讲义负责建立理解，复述是低风险引导练习；只有独立验证题的正式提交才会形成能力证据，答错后自动进入纠正与变式。
        </div>

        {paused && (
          <section className="rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
            <Pause className="mx-auto text-slate-400" size={34} />
            <h1 className="mt-4 text-2xl font-semibold">学习现场已保存</h1>
            <p className="mt-2 text-sm text-slate-500">学习卡、复述反馈和作答进度都会保留。</p>
            <button type="button" onClick={() => updateFlow('resume')} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white"><Play size={16} />从上次位置继续</button>
          </section>
        )}

        {run.state === 'learning_card' && !needsQualityRefresh && (
          <article className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-emerald-100 bg-emerald-50 px-5 py-5 sm:px-8">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-800"><BookOpen size={15} />学习卡</div>
              <h1 className="mt-3 text-2xl font-bold leading-tight text-slate-950 sm:text-3xl">{card.title}</h1>
              <p className="mt-3 text-sm leading-7 text-slate-600">{card.objective}</p>
            </div>
            <div className="space-y-7 p-5 sm:p-8">
              <LearningCardContent card={card} />
              <button type="button" disabled={!!busy} onClick={() => updateFlow('complete_card')} className="inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">我读完了，开始复述 <ChevronRight size={16} /></button>
            </div>
          </article>
        )}

        {run.state === 'teach_back' && (
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-100 text-violet-700"><MessageCircle size={21} /></div>
            <h1 className="mt-5 text-2xl font-semibold">现在，请把它讲给一个没学过的人</h1>
            <p className="mt-2 text-sm leading-7 text-slate-600">不要照抄学习卡。用自己的话说明它是什么、关键关系为什么成立，再给一个例子。系统只做缺口诊断，不会因为这次复述就宣布你已经掌握。</p>
            <textarea value={teachBack} onChange={event => setTeachBack(event.target.value)} rows={9} placeholder="例如：我会先这样解释……" className="mt-5 w-full resize-y rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 outline-none focus:border-violet-400 focus:bg-white" />
            <div className="mt-3 flex items-center justify-between gap-4"><span className={`text-xs ${teachBack.trim().length >= 20 ? 'text-slate-400' : 'text-amber-700'}`}>至少写 20 个字，当前 {teachBack.trim().length} 字</span><button type="button" disabled={busy === 'teach-back' || teachBack.trim().length < 20} onClick={submitTeachBack} className="inline-flex items-center gap-2 rounded-xl bg-violet-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-40">{busy === 'teach-back' ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}提交复述</button></div>
          </section>
        )}

        {run.state === 'teach_back_feedback' && (
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
            <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-800">诊断反馈 · 不改变掌握状态</span>
            <h1 className="mt-5 text-2xl font-semibold">你的复述覆盖了 {Math.round(Number(run.teach_back.coverage_ratio || 0) * 100)}% 的关键点</h1>
            {!!run.teach_back.covered_points?.length && <div className="mt-5 rounded-2xl bg-emerald-50 p-4"><h2 className="text-sm font-semibold text-emerald-900">已经讲清楚</h2><ul className="mt-2 space-y-1 text-sm leading-6 text-emerald-900/80">{run.teach_back.covered_points.map((point: string) => <li key={point}>✓ {point}</li>)}</ul></div>}
            {!!run.teach_back.missing_points?.length && <div className="mt-4 rounded-2xl bg-amber-50 p-4"><h2 className="text-sm font-semibold text-amber-900">验证前再想一想</h2><ul className="mt-2 space-y-1 text-sm leading-6 text-amber-900/80">{run.teach_back.missing_points.map((point: string) => <li key={point}>· {point}</li>)}</ul></div>}
            <div className="mt-4 rounded-2xl border border-violet-200 bg-violet-50 p-4 text-sm leading-7 text-violet-950"><strong>诊断追问：</strong>{run.teach_back.diagnostic_question}</div>
            <button type="button" disabled={!!busy} onClick={() => updateFlow('continue_after_feedback')} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800">进入独立验证 <ChevronRight size={16} /></button>
          </section>
        )}

        {displayQuestion && (
          <QuestionCard
            key={`${run.current_question!.id}-${retrying ? 'retry' : 'original'}`}
            question={run.current_question!}
            busy={busy === 'question'}
            result={questionResult}
            retrying={retrying}
            onSubmit={submitQuestion}
            onContinue={continueAfterCorrect}
          />
        )}

        {run.state === 'remediation' && !retrying && (
          <div className="space-y-4">
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">答错不是终点。先修正具体误解，再重做原题，最后完成变式验证。</div>
            <RemediationPanel remediation={remediation || run.remediation} onChange={handleRemediationChange} onRetry={() => { setQuestionResult(null); setRetrying(true) }} />
            {busy === 'remediation-sync' && <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 size={14} className="animate-spin" />正在回写纠错证据…</p>}
          </div>
        )}

        {run.state === 'completed' && (
          <section className="rounded-3xl border border-emerald-200 bg-white p-6 shadow-sm sm:p-9">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700"><CheckCircle2 size={30} /></div>
            <h1 className="mt-5 text-3xl font-bold">这次学习闭环完成了</h1>
            <p className="mt-3 text-sm leading-7 text-slate-600">你完成了学习卡、独立复述和 {run.progress.total_questions} 道验证题。这里证明的是“本轮已经验证”，还不是跨时间的稳定掌握。</p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl bg-slate-50 p-4"><span className="text-xs text-slate-500">独立验证</span><strong className="mt-1 block text-lg">{run.summary.independently_verified_question_ids?.length || 0} 题</strong></div>
              <div className="rounded-2xl bg-amber-50 p-4"><span className="text-xs text-amber-800">经过纠错后通过</span><strong className="mt-1 block text-lg text-amber-950">{run.summary.remediated_question_ids?.length || 0} 题</strong></div>
            </div>
            <div className="mt-5 rounded-2xl border border-indigo-200 bg-indigo-50 p-4"><h2 className="flex items-center gap-2 text-sm font-semibold text-indigo-950"><CalendarClock size={16} />下一次复习</h2><p className="mt-2 text-sm leading-6 text-indigo-900/80">{run.summary.review_due_at ? new Date(run.summary.review_due_at).toLocaleString('zh-CN') : '复习计划已建立，可前往复习台查看。'}</p><p className="mt-1 text-xs text-indigo-700">{run.summary.next_step}</p></div>
            <div className="mt-6 flex flex-wrap gap-3"><button type="button" onClick={() => navigate('/review')} className="inline-flex items-center gap-2 rounded-xl bg-indigo-700 px-5 py-3 text-sm font-semibold text-white"><CalendarClock size={16} />查看复习计划</button><button type="button" onClick={() => navigate(originNavigation?.path || run.learning_task?.path || '/agent')} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700"><RotateCcw size={16} />返回原对话继续</button></div>
          </section>
        )}

        {error && <p className="mt-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      </main>

      {lectureReferenceOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-3 sm:p-6" onClick={closeLectureReference}>
          <article role="dialog" aria-modal="true" aria-label="讲义回看" className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-3xl bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
            <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-indigo-100 bg-indigo-50/95 px-5 py-4 backdrop-blur sm:px-8">
              <div>
                <p className="flex items-center gap-2 text-xs font-semibold text-indigo-800"><BookOpen size={14} />讲义回看 · 不改变当前任务步骤</p>
                <h1 className="mt-2 text-xl font-bold text-slate-950">{card.title}</h1>
                <p className="mt-1 text-xs leading-5 text-slate-600">{card.objective}</p>
              </div>
              <button type="button" onClick={closeLectureReference} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-slate-500 shadow-sm hover:text-slate-900" aria-label="关闭讲义回看"><X size={17} /></button>
            </header>
            <div className="space-y-7 p-5 sm:p-8"><LearningCardContent card={card} /></div>
          </article>
        </div>
      )}

      {tutorOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" onClick={() => setTutorOpen(false)}>
          <aside className="flex h-full w-[min(94vw,430px)] flex-col bg-white shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4"><div><strong className="text-sm">当前步骤 Tutor</strong><p className="text-[10px] text-slate-500">能看当前目标与证据，不会直接宣布掌握</p></div><button type="button" onClick={() => setTutorOpen(false)} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"><X size={17} /></button></div>
            <TutorPanel
              requestedSessionId={run.session_id}
              projectId={originNavigation?.kind === 'checkpoint' ? run.project_id : undefined}
              checkpointId={originNavigation?.kind === 'checkpoint' ? run.checkpoint_id : undefined}
              surfaceKind="focused_learning"
              surfaceTitle="专注学习 Tutor"
              surfaceDescription="围绕当前微学习步骤答疑"
              quickPrompts={['换一种方式解释当前关键点', '给我一个不泄露答案的提示', '我为什么会在这里混淆？']}
              turnContext={{
                micro_learning_run_id: run.id,
                learning_goal: run.goal,
                workflow_state: run.state,
                target_concepts: card.target_concepts || [],
                teach_back_diagnosis: run.teach_back?.status || '',
                current_learning_target: run.current_question?.learning_target || '',
              }}
              className="min-h-0 flex-1"
            />
          </aside>
        </div>
      )}
    </div>
  )
}
