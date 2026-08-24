import { ArrowUpRight, Check, CheckCircle2, Lightbulb, Pause, Play, ShieldCheck, Sparkles } from 'lucide-react'
import { useState } from 'react'
import type { LearningSkillRun } from '../../services/api'

type SkillRunAction = 'pause' | 'resume' | 'start_verification'

interface Props {
  run: LearningSkillRun
  onAction: (action: SkillRunAction) => Promise<void>
  onOpenLearningRun?: (run: NonNullable<LearningSkillRun['micro_learning_run']>) => void
}

const stageClass = {
  completed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  current: 'border-indigo-300 bg-indigo-50 text-indigo-900 ring-1 ring-indigo-100',
  locked: 'border-slate-200 bg-slate-50 text-slate-400',
}

export default function LearningSkillRunCard({ run, onAction, onOpenLearningRun }: Props) {
  const [busyAction, setBusyAction] = useState<SkillRunAction | null>(null)
  const [error, setError] = useState('')
  const progress = Math.max(0, Math.min(100, Math.round(100 * run.step_index / run.total_steps)))
  const learningRun = run.micro_learning_run

  const act = async (action: SkillRunAction) => {
    if (busyAction) return
    setBusyAction(action)
    setError('')
    try {
      await onAction(action)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || '学习方法状态没有更新成功，请重试。')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <section
      className="mx-auto w-full max-w-3xl overflow-hidden rounded-xl border border-emerald-200 bg-white shadow-sm"
      aria-label={`${run.skill.name}学习进度`}
      data-testid="learning-skill-run-card"
    >
      <div className="flex items-start justify-between gap-3 px-3.5 py-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-emerald-800">
            <Sparkles size={13} />{run.skill.name}
          </p>
          <p className="mt-1 truncate text-sm font-medium text-slate-900" title={run.goal}>{run.goal}</p>
          <p className="mt-1 text-[11px] text-slate-500">
            第 {run.step_index}/{run.total_steps} 步 · {run.stage_label}
            {run.status === 'paused' ? ' · 可以稍后继续' : ''}
          </p>
        </div>
        {run.status === 'completed' ? (
          <CheckCircle2 size={20} className="shrink-0 text-emerald-600" aria-label="本轮完成" />
        ) : (
          <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-medium text-emerald-700">
            {run.turn_count}/{run.turn_budget} 轮有效引导
          </span>
        )}
      </div>

      <div className="h-1 bg-emerald-50" aria-hidden="true">
        <div className="h-full bg-emerald-600 transition-[width]" style={{ width: `${progress}%` }} />
      </div>

      <div className="grid grid-cols-2 gap-1.5 border-t border-emerald-100 bg-white px-3.5 py-3 sm:grid-cols-4" aria-label="学习方法流程">
        {(run.stages || []).map((stage, index) => (
          <div key={stage.id} className={`min-w-0 rounded-lg border px-2 py-2 text-[10px] font-medium ${stageClass[stage.status]}`}>
            <span className="flex items-center gap-1">
              {stage.status === 'completed' ? <Check size={11} /> : <span className="tabular-nums">{index + 1}</span>}
              <span className="truncate" title={stage.label}>{stage.label}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="border-t border-emerald-100 bg-emerald-50/50 px-3.5 py-2.5">
        <p className="mb-2 flex items-start gap-1.5 rounded-lg bg-white/80 px-2.5 py-2 text-[11px] leading-5 text-slate-700">
          <Lightbulb size={13} className="mt-0.5 shrink-0 text-amber-600" />
          <span>{run.flow_note}</span>
        </p>
        {run.learning_task && run.status !== 'completed' && (
          <p className="mb-2 text-[10px] leading-4 text-emerald-800">
            这张卡就是当前原子任务的教学阶段；完成引导后才会准备独立验证，不需要并行生成另一套流程。
          </p>
        )}
        <p className="flex items-start gap-1.5 text-[11px] leading-5 text-slate-600">
          <ShieldCheck size={13} className="mt-0.5 shrink-0 text-emerald-700" />
          <span>{run.evidence_note}</span>
        </p>
        {error && <p role="alert" className="mt-2 text-[11px] text-red-700">{error}</p>}
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {run.learning_task && (
            <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-emerald-200 bg-white px-2.5 text-[11px] font-medium text-emerald-800">
              当前任务就在这段对话中
            </span>
          )}
          {run.can_pause && (
            <button
              type="button"
              onClick={() => act('pause')}
              disabled={Boolean(busyAction)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              <Pause size={12} />{busyAction === 'pause' ? '暂停中…' : '暂停方法'}
            </button>
          )}
          {run.can_resume && (
            <button
              type="button"
              onClick={() => act('resume')}
              disabled={Boolean(busyAction)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-700 px-3 text-[11px] font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
            >
              <Play size={12} />{busyAction === 'resume' ? '继续中…' : '继续学习'}
            </button>
          )}
          {run.can_start_verification && (
            <button
              type="button"
              onClick={() => act('start_verification')}
              disabled={Boolean(busyAction)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-slate-950 px-3 text-[11px] font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <ShieldCheck size={12} />{busyAction === 'start_verification' ? '正在准备…' : '开始独立验证'}
            </button>
          )}
          {learningRun && onOpenLearningRun && (
            <button
              type="button"
              onClick={() => onOpenLearningRun(learningRun)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-slate-950 px-3 text-[11px] font-semibold text-white hover:bg-slate-800"
            >
              {learningRun.status === 'completed' ? '查看验证记录' : '打开独立验证'}<ArrowUpRight size={12} />
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
