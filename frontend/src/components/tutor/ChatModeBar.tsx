import { BookOpenText, Compass, ListTree, Route, Sparkles } from 'lucide-react'
import type { ChatMode, ChatModeContract, ChatModeId } from '../../services/api'

const iconByMode = {
  free: Compass,
  explain: BookOpenText,
  learn: ListTree,
  plan: Route,
}

const toneByMode: Record<ChatModeId, string> = {
  free: 'border-slate-200 bg-white text-slate-700',
  explain: 'border-sky-200 bg-sky-50 text-sky-900',
  learn: 'border-emerald-200 bg-emerald-50 text-emerald-950',
  plan: 'border-violet-200 bg-violet-50 text-violet-950',
}

export default function ChatModeBar({ mode, contracts = [] }: {
  mode: ChatMode | null
  contracts?: ChatModeContract[]
}) {
  const current = mode || {
    id: 'free' as const,
    name: '自由探索',
    status: 'active' as const,
    skills: ['intent_and_handoff'],
  }
  const Icon = iconByMode[current.id]
  const contract = contracts.find(item => item.id === current.id)
  const completed = current.status === 'completed'

  return (
    <section className={`border-b px-4 py-2.5 ${toneByMode[current.id]}`} data-testid="chat-mode-bar">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-xs font-bold">
          <Icon size={14} />{current.name}
        </span>
        <span className="text-[11px] opacity-75">
          {completed ? '本段已完成 · 下一轮回到自由探索' : current.reason || contract?.boundary || '根据当前意图继续协作'}
        </span>
        {current.id === 'learn' && current.learning_task_id && (
          <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium">任务 #{current.learning_task_id}</span>
        )}
        {current.id === 'plan' && current.project_proposal_id && (
          <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium">项目提案 #{current.project_proposal_id}</span>
        )}
      </div>
      {current.goal && current.id !== 'free' && (
        <p className="mt-1 flex items-start gap-1.5 truncate text-[11px] opacity-80" title={current.goal}>
          <Sparkles size={11} className="mt-0.5 shrink-0" />{current.goal}
        </p>
      )}
    </section>
  )
}
