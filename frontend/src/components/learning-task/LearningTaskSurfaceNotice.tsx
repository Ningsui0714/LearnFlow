import { MapPin } from 'lucide-react'
import type { LearningTask } from '../../services/api'
import {
  type CurrentLearningSurface,
  learningTaskPresentation,
} from './taskPresentation'

export default function LearningTaskSurfaceNotice({
  task,
  currentSurface,
  compact = false,
  className = '',
}: {
  task: LearningTask
  currentSurface?: CurrentLearningSurface
  compact?: boolean
  className?: string
}) {
  const presentation = learningTaskPresentation(task, currentSurface)
  return (
    <div
      className={`rounded-xl border border-emerald-200 bg-emerald-50/70 ${compact ? 'px-3 py-2' : 'px-4 py-3'} ${className}`}
      data-testid="learning-task-surface-notice"
    >
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-medium text-emerald-800">
        <span className="rounded-full bg-white/80 px-2 py-0.5">学习任务 · {presentation.statusLabel}</span>
        <span>{presentation.originLabel}</span>
      </div>
      <p className={`mt-1.5 flex items-center gap-1.5 font-semibold text-emerald-950 ${compact ? 'text-xs' : 'text-sm'}`}>
        <MapPin size={compact ? 12 : 14} />{presentation.locationTitle}
      </p>
      {!compact && (
        <p className="mt-1 text-xs leading-5 text-emerald-900/75">{presentation.locationDescription}</p>
      )}
    </div>
  )
}
