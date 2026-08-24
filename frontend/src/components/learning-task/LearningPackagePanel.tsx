import {
  BookOpen, CalendarClock, Check, ChevronRight, CircleDotDashed,
  FileQuestion, GraduationCap, LockKeyhole, MessageSquareText,
  ShieldCheck, Sparkles, Wrench, type LucideIcon,
} from 'lucide-react'
import type { LearningTask } from '../../services/api'
import {
  learningPackagePresentation,
  type LearningPackageStageId,
  type LearningPackageStageStatus,
} from './learningPackagePresentation'

const stageIcons: Record<LearningPackageStageId, LucideIcon> = {
  lecture: BookOpen,
  guided_practice: MessageSquareText,
  verification: ShieldCheck,
  remediation: Wrench,
  review: CalendarClock,
}

const statusClass: Record<LearningPackageStageStatus, string> = {
  not_ready: 'bg-slate-100 text-slate-500',
  ready: 'bg-indigo-100 text-indigo-700',
  current: 'bg-emerald-100 text-emerald-800',
  completed: 'bg-emerald-100 text-emerald-800',
  locked: 'bg-slate-100 text-slate-400',
  standby: 'bg-amber-100 text-amber-800',
  scheduled: 'bg-violet-100 text-violet-800',
}

export default function LearningPackagePanel({
  task,
  sourceText,
  preparing = false,
  disabled = false,
  onSourceTextChange,
  onPrepare,
  onNavigate,
}: {
  task: LearningTask
  sourceText?: string
  preparing?: boolean
  disabled?: boolean
  onSourceTextChange?: (value: string) => void
  onPrepare?: () => void
  onNavigate: (path: string) => void
}) {
  const presentation = learningPackagePresentation(task)

  return (
    <section className="mt-5 overflow-hidden rounded-2xl border border-indigo-200 bg-white shadow-sm" data-testid="learning-package-panel">
      <header className="flex flex-col gap-3 border-b border-indigo-100 bg-gradient-to-r from-indigo-50 via-white to-emerald-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-sm font-bold text-slate-900"><GraduationCap size={17} className="text-indigo-700" />任务学习包</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">讲义负责输入，引导练习负责暴露缺口，独立验证才形成能力证据。</p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 shadow-sm">讲义 {presentation.lectureCount} 份</span>
          <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 shadow-sm">验证题 {presentation.questionCount} 道</span>
          <span className="rounded-full bg-white px-2.5 py-1 text-emerald-700 shadow-sm">已完成 {presentation.completedRequiredStageCount}/4 个必经环节</span>
        </div>
      </header>

      <div className="grid gap-0 lg:grid-cols-5">
        {presentation.stages.map((stage, index) => {
          const Icon = stageIcons[stage.id]
          const locked = ['locked', 'not_ready'].includes(stage.status)
          return (
            <article key={stage.id} className={`relative min-w-0 border-b border-slate-100 p-4 last:border-b-0 lg:border-b-0 ${index > 0 ? 'lg:border-l' : ''}`}>
              <div className="flex items-start justify-between gap-2">
                <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${stage.status === 'current' ? 'bg-emerald-700 text-white' : stage.status === 'completed' || stage.status === 'scheduled' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                  {stage.status === 'completed' || stage.status === 'scheduled' ? <Check size={17} /> : locked ? <LockKeyhole size={15} /> : <Icon size={17} />}
                </span>
                <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusClass[stage.status]}`}>{stage.statusLabel}</span>
              </div>
              <p className="mt-3 text-[10px] font-bold uppercase tracking-[0.13em] text-slate-400">第 {stage.order} 环</p>
              <h3 className="mt-1 text-sm font-bold text-slate-900">{stage.title}</h3>
              <p className="mt-1.5 min-h-14 text-xs leading-5 text-slate-500">{stage.purpose}</p>
              <p className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-700"><CircleDotDashed size={12} className="text-indigo-500" />{stage.amount}</p>
              {stage.logicalFilename && <p className="mt-1 truncate text-[10px] text-slate-400" title={stage.logicalFilename}>{stage.logicalFilename}</p>}
              {stage.actionLabel && stage.path && (
                <button type="button" disabled={disabled} onClick={() => stage.path && onNavigate(stage.path)} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-indigo-700 hover:text-indigo-900 disabled:opacity-40">
                  {stage.actionLabel}<ChevronRight size={13} />
                </button>
              )}
            </article>
          )
        })}
      </div>

      {!presentation.packageReady && (
        <div className="border-t border-indigo-100 bg-indigo-50/60 p-4 sm:p-5">
          {presentation.canMaterialize && onPrepare ? (
            <div className="grid gap-3 sm:grid-cols-[1fr,auto] sm:items-end">
              <label className="text-xs font-medium text-indigo-950">
                可选学习来源
                <textarea value={sourceText || ''} onChange={event => onSourceTextChange?.(event.target.value)} rows={3} placeholder="粘贴题目、教材段落、代码或笔记；留空则使用原对话中的问题" className="mt-1.5 w-full resize-y rounded-xl border border-indigo-200 bg-white px-3 py-2 text-xs font-normal leading-5 outline-none focus:border-indigo-400" />
              </label>
              <button type="button" disabled={disabled || preparing} onClick={onPrepare} className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-indigo-700 px-4 text-xs font-semibold text-white hover:bg-indigo-800 disabled:opacity-40">
                <Sparkles size={14} />{preparing ? '正在准备学习包…' : '生成学习包并开始'}
              </button>
            </div>
          ) : task.checkpoint_id ? (
            <button type="button" onClick={() => onNavigate(task.navigation.path)} className="inline-flex items-center gap-2 rounded-xl bg-indigo-700 px-4 py-2.5 text-xs font-semibold text-white hover:bg-indigo-800">
              <FileQuestion size={14} />进入关卡准备和使用学习内容
            </button>
          ) : (
            <p className="text-xs leading-5 text-indigo-900">先通过页面上方的主按钮接受并开始任务，之后即可生成这份学习包。</p>
          )}
        </div>
      )}
    </section>
  )
}
