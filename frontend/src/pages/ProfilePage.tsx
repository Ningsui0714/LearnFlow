import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive, ArrowRight, Award, Brain, Check, Clock, Compass, Edit3, Hammer,
  History, Medal, RefreshCcw, Route, Save, Sparkles, Target, Trophy, UserRound, X,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  archiveProfileMemory, getGrowth, restoreProfileMemory, updateProfile,
} from '../services/api'

type Section = 'overview' | 'memories' | 'journey' | 'profile'
type MemoryFilter = 'active' | 'archived' | 'all'

interface GrowthMemory {
  memory_id: string
  title: string
  summary: string
  retention: 'long' | 'recent'
  retention_label: string
  source_kind: string
  source_label: string
  related_record_count: number
  updated_at?: string
  status: 'active' | 'archived'
  expires_at?: string
}

interface GrowthArea {
  id: string
  title: string
  description: string
  active_count: number
  memories: GrowthMemory[]
}

const areaMeta: Record<string, { icon: typeof Route; tone: string; iconTone: string }> = {
  progress: { icon: Route, tone: 'border-sky-200 bg-sky-50/60', iconTone: 'bg-sky-100 text-sky-700' },
  understanding: { icon: Brain, tone: 'border-violet-200 bg-violet-50/60', iconTone: 'bg-violet-100 text-violet-700' },
  ability: { icon: Hammer, tone: 'border-emerald-200 bg-emerald-50/60', iconTone: 'bg-emerald-100 text-emerald-700' },
  rhythm: { icon: Clock, tone: 'border-rose-200 bg-rose-50/60', iconTone: 'bg-rose-100 text-rose-700' },
  direction: { icon: Compass, tone: 'border-amber-200 bg-amber-50/60', iconTone: 'bg-amber-100 text-amber-700' },
}

const modeLabels: Record<string, string> = {
  explanation: '小讲解', example: '例子', practice: '动手练习',
  project: '项目推进', reflection: '复盘',
}

const educationLabels: Record<string, string> = {
  primary: '小学', middle_school: '初中', high_school: '高中',
  vocational: '职业教育', undergraduate: '本科', graduate: '研究生', other: '其他',
}

const sections: { id: Section; label: string; icon: typeof Route }[] = [
  { id: 'overview', label: '成长概览', icon: Sparkles },
  { id: 'memories', label: '关于我', icon: Brain },
  { id: 'journey', label: '成长足迹', icon: History },
  { id: 'profile', label: '个人资料', icon: UserRound },
]

function initialSection(): Section {
  const requested = new URLSearchParams(window.location.search).get('section')
  if (requested === 'memory' || requested === 'memories') return 'memories'
  if (requested === 'journey') return 'journey'
  if (requested === 'profile') return 'profile'
  return 'overview'
}

function formatDate(value?: string) {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function ProfilePage() {
  const navigate = useNavigate()
  const [data, setData] = useState<any>(null)
  const [section, setSection] = useState<Section>(initialSection)
  const [memoryFilter, setMemoryFilter] = useState<MemoryFilter>('active')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<any>({})
  const [busyMemory, setBusyMemory] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const next = await getGrowth()
      setData(next)
      setDraft(next.profile || {})
      setError('')
    } catch {
      setError('暂时无法读取成长记录，请稍后重试。')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const saveProfile = async () => {
    setSaving(true)
    try {
      await updateProfile({
        display_name: draft.display_name,
        education_stage: draft.education_stage,
        background: draft.background,
        focus_areas: draft.focus_areas,
        weekly_hours: Number(draft.weekly_hours),
        preferred_modes: draft.preferred_modes,
        career_goal: draft.career_goal,
        career_goal_status: draft.career_goal_status,
      })
      setEditing(false)
      await load()
    } catch {
      setError('资料保存失败，请检查填写内容后再试。')
    } finally {
      setSaving(false)
    }
  }

  const toggleMemory = async (memory: GrowthMemory) => {
    setBusyMemory(memory.memory_id)
    try {
      if (memory.status === 'archived') await restoreProfileMemory(memory.memory_id)
      else await archiveProfileMemory(memory.memory_id, '用户在“我的成长”中将该内容设为不再参考')
      await load()
    } catch {
      setError('这条内容暂时无法更新，请稍后再试。')
    } finally {
      setBusyMemory('')
    }
  }

  const visibleAreas = useMemo(() => (data?.areas || []).map((area: GrowthArea) => ({
    ...area,
    memories: area.memories.filter(memory => memoryFilter === 'all' || memory.status === memoryFilter),
  })), [data?.areas, memoryFilter])

  if (!data && !error) {
    return <div className="h-full overflow-y-auto bg-[#f6f7f4] p-8 text-sm text-slate-500">正在整理你的成长记录…</div>
  }
  if (!data) {
    return (
      <div className="flex h-full items-center justify-center bg-[#f6f7f4] p-6">
        <div className="max-w-sm text-center">
          <p className="text-sm text-slate-600">{error}</p>
          <button type="button" onClick={load} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white">重新读取</button>
        </div>
      </div>
    )
  }

  const profile = data.profile
  const stats = data.stats

  return (
    <div className="h-full w-full min-w-0 overflow-x-hidden overflow-y-auto bg-[#f6f7f4]">
      <div className="mx-auto w-full min-w-0 max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
        <header className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-100"><Sparkles size={14} /></span>
              @{profile.username}
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">我的成长</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">看看自己走到了哪里、有哪些真实进步，以及下一步最值得做什么。</p>
          </div>
          <button
            type="button"
            onClick={() => { setSection('profile'); setEditing(true) }}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <Edit3 size={15} /> 更新我的情况
          </button>
        </header>

        <nav className="mt-7 flex gap-1 overflow-x-auto border-b border-slate-200" aria-label="成长空间">
          {sections.map(item => {
            const Icon = item.icon
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setSection(item.id)}
                className={`flex shrink-0 items-center gap-1 border-b-2 px-1.5 py-3 text-sm font-medium transition-colors sm:gap-2 sm:px-3 ${
                  section === item.id
                    ? 'border-emerald-700 text-emerald-800'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <Icon size={15} /> {item.label}
              </button>
            )
          })}
        </nav>

        {error && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{error}</div>}

        {section === 'overview' && (
          <OverviewSection
            data={data}
            onNavigate={navigate}
            onOpenMemories={() => setSection('memories')}
            onOpenJourney={() => setSection('journey')}
          />
        )}
        {section === 'memories' && (
          <MemoriesSection
            areas={visibleAreas}
            evidence={data.evidence || []}
            filter={memoryFilter}
            onFilter={setMemoryFilter}
            busyMemory={busyMemory}
            onToggleMemory={toggleMemory}
            stats={stats}
          />
        )}
        {section === 'journey' && <JourneySection journey={data.journey} stats={stats} />}
        {section === 'profile' && (
          <ProfileSection
            profile={profile}
            draft={draft}
            editing={editing}
            saving={saving}
            onEdit={() => setEditing(true)}
            onCancel={() => { setEditing(false); setDraft(profile) }}
            onDraft={setDraft}
            onSave={saveProfile}
          />
        )}
      </div>
    </div>
  )
}

function OverviewSection({ data, onNavigate, onOpenMemories, onOpenJourney }: {
  data: any
  onNavigate: (route: string) => void
  onOpenMemories: () => void
  onOpenJourney: () => void
}) {
  const { overview, stats } = data
  return (
    <div className="pb-12 pt-6">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.8fr)]">
        <section className="overflow-hidden rounded-3xl bg-slate-950 p-6 text-white shadow-sm sm:p-8">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.15em] text-emerald-300"><Target size={15} /> 现在的重点</div>
          <h2 className="mt-5 max-w-2xl text-2xl font-semibold leading-tight sm:text-3xl">{overview.current_focus}</h2>
          <p className="mt-3 text-sm leading-6 text-slate-300">{overview.focus_context}</p>
          <div className="mt-8 flex flex-wrap items-center justify-between gap-4 border-t border-slate-700 pt-5">
            <div>
              <p className="text-xs text-slate-400">建议下一步</p>
              <p className="mt-1 text-sm font-semibold text-white">{overview.next_action.title}</p>
              <p className="mt-1 max-w-xl text-xs leading-5 text-slate-400">{overview.next_action.description}</p>
            </div>
            <button type="button" onClick={() => onNavigate(overview.next_action.route)} className="inline-flex items-center gap-2 rounded-xl bg-emerald-400 px-4 py-2.5 text-sm font-semibold text-emerald-950 hover:bg-emerald-300">
              {overview.next_action.action_label} <ArrowRight size={15} />
            </button>
          </div>
        </section>

        <section className="rounded-3xl border border-amber-200 bg-amber-50 p-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-400 text-amber-950"><Medal size={20} /></div>
          <h2 className="mt-5 text-lg font-semibold text-slate-950">进步正在发生</h2>
          <p className="mt-2 text-sm leading-6 text-slate-700">{overview.encouragement}</p>
          <button type="button" onClick={onOpenJourney} className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-amber-900 hover:text-amber-700">查看成长足迹 <ArrowRight size={14} /></button>
        </section>
      </div>

      <section className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-slate-200 bg-slate-200 sm:grid-cols-4">
        <GrowthStat value={stats.verified_records} label="条表现经过验证" />
        <GrowthStat value={stats.completed_learning_loops} label="次专注学习闭环" />
        <GrowthStat value={stats.badges} label="枚成长徽章" />
        <GrowthStat value={stats.due_reviews} label="项待处理复习" attention={stats.due_reviews > 0} />
      </section>

      <section className="mt-9">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">LearnFlow 目前这样了解你</h2>
            <p className="mt-1 text-sm text-slate-500">这些内容会帮助系统选择更合适的目标、讲法和练习。</p>
          </div>
          <button type="button" onClick={onOpenMemories} className="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-800 hover:text-emerald-600">查看和管理全部 <ArrowRight size={14} /></button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {(data.areas || []).map((area: GrowthArea) => {
            const meta = areaMeta[area.id] || areaMeta.progress
            const Icon = meta.icon
            const first = area.memories.find(memory => memory.status !== 'archived')
            return (
              <article key={area.id} className={`min-h-44 rounded-2xl border p-4 ${meta.tone}`}>
                <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${meta.iconTone}`}><Icon size={17} /></span>
                <h3 className="mt-4 text-sm font-semibold text-slate-900">{area.title}</h3>
                <p className="mt-1 text-xs leading-5 text-slate-500">{area.description}</p>
                <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-700">{first?.summary || '还没有足够的学习记录'}</p>
              </article>
            )
          })}
        </div>
      </section>

      <section className="mt-9 grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(280px,0.75fr)]">
        <div>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-slate-950">最近的成长足迹</h2>
            <button type="button" onClick={onOpenJourney} className="text-xs font-semibold text-slate-500 hover:text-slate-800">查看全部</button>
          </div>
          <div className="mt-3 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white px-5">
            {(data.journey?.events || []).slice(0, 4).map((event: any) => (
              <div key={event.id} className="flex gap-3 py-4">
                <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${event.badge ? 'bg-amber-100 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>{event.badge ? <Trophy size={15} /> : <Check size={15} />}</span>
                <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">{event.title}</p><p className="mt-1 text-xs leading-5 text-slate-500">{event.summary}</p></div>
                <time className="shrink-0 text-[11px] text-slate-400">{formatDate(event.occurred_at)}</time>
              </div>
            ))}
            {(data.journey?.events || []).length === 0 && <p className="py-8 text-center text-sm text-slate-400">完成一个学习闭环后，足迹会从这里开始。</p>}
          </div>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-950">积累概况</h2>
          <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-5">
            <p className="text-3xl font-semibold text-slate-950">{stats.learning_records}</p>
            <p className="mt-1 text-xs text-slate-500">条学习记录帮助系统逐渐了解你</p>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(100, Math.max(8, stats.active_memories * 8))}%` }} /></div>
            <div className="mt-4 flex items-center justify-between text-xs"><span className="text-slate-500">正在参考的内容</span><strong className="text-slate-800">{stats.active_memories} 条</strong></div>
            <div className="mt-2 flex items-center justify-between text-xs"><span className="text-slate-500">由你归档的内容</span><strong className="text-slate-800">{stats.archived_memories} 条</strong></div>
          </div>
        </div>
      </section>
    </div>
  )
}

function MemoriesSection({ areas, evidence, filter, onFilter, busyMemory, onToggleMemory, stats }: {
  areas: GrowthArea[]
  evidence: any[]
  filter: MemoryFilter
  onFilter: (filter: MemoryFilter) => void
  busyMemory: string
  onToggleMemory: (memory: GrowthMemory) => void
  stats: any
}) {
  return (
    <div className="pb-12 pt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-slate-950">LearnFlow 记得的我</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">这些内容来自你的表达和真实学习过程。觉得不准确或暂时不想使用时，可以归档；之后随时能恢复。</p>
        </div>
        <div className="flex rounded-xl border border-slate-200 bg-white p-1">
          {([['active', `正在参考 ${stats.active_memories}`], ['archived', `已归档 ${stats.archived_memories}`], ['all', '全部']] as [MemoryFilter, string][]).map(([id, label]) => (
            <button key={id} type="button" onClick={() => onFilter(id)} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${filter === id ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}>{label}</button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {areas.map(area => {
          const meta = areaMeta[area.id] || areaMeta.progress
          const Icon = meta.icon
          return (
            <section key={area.id} className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex items-start gap-3">
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${meta.iconTone}`}><Icon size={18} /></span>
                <div><h3 className="font-semibold text-slate-900">{area.title}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{area.description}</p></div>
              </div>
              <div className="mt-4 divide-y divide-slate-100">
                {area.memories.map(memory => (
                  <article key={memory.memory_id} className={`py-4 first:pt-1 last:pb-0 ${memory.status === 'archived' ? 'opacity-60' : ''}`}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-semibold text-slate-800">{memory.title}</h4>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${sourceTone(memory.source_kind)}`}>{memory.source_label}</span>
                          <span className="text-[10px] text-slate-400">{memory.retention_label}</span>
                        </div>
                        <p className="mt-2 break-words text-sm leading-6 text-slate-600">{memory.summary}</p>
                        <p className="mt-2 text-[11px] text-slate-400">{memory.related_record_count > 0 ? `关联 ${memory.related_record_count} 条学习记录` : '等待更多学习记录'}{memory.updated_at ? ` · 更新于 ${formatDate(memory.updated_at)}` : ''}</p>
                      </div>
                      <button
                        type="button"
                        disabled={busyMemory === memory.memory_id}
                        onClick={() => onToggleMemory(memory)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-40"
                      >
                        {memory.status === 'archived' ? <><RefreshCcw size={12} /> 恢复</> : <><Archive size={12} /> 归档</>}
                      </button>
                    </div>
                  </article>
                ))}
                {area.memories.length === 0 && <p className="py-7 text-center text-sm text-slate-400">这个分类下暂时没有内容</p>}
              </div>
            </section>
          )
        })}
      </div>

      <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div><h3 className="text-lg font-semibold text-slate-950">这些认识从哪里来</h3><p className="mt-1 text-sm text-slate-500">只展示最近、最相关的可读摘要，帮助你判断系统是否理解正确。</p></div>
          <span className="hidden rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 sm:inline">判断依据可检查</span>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {evidence.map(item => (
            <article key={item.id} className="rounded-xl border border-slate-100 bg-slate-50 p-4">
              <div className="flex items-start justify-between gap-3"><p className="text-sm font-semibold text-slate-800">{item.title}</p><time className="shrink-0 text-[10px] text-slate-400">{formatDate(item.occurred_at)}</time></div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{item.summary}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${sourceTone(item.source_kind)}`}>{item.source_label}</span><span className="text-[10px] text-slate-400">用于了解：{item.area_title}</span></div>
            </article>
          ))}
          {evidence.length === 0 && <p className="py-7 text-sm text-slate-400">完成复述、答题或练习后，这里会出现可检查的学习依据。</p>}
        </div>
        <p className="mt-5 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">归档一条“系统对你的了解”，不会抹掉已经发生的学习足迹和成绩记录。</p>
      </section>
    </div>
  )
}

function JourneySection({ journey, stats }: { journey: any; stats: any }) {
  return (
    <div className="pb-12 pt-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-950">成长足迹</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">这里记录真实发生的重要节点。学习中的修正会被保留，过去取得的成就也不会凭空消失。</p>
      </div>

      <section className="mt-6 rounded-3xl border border-amber-200 bg-amber-50 p-5 sm:p-6">
        <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-amber-400 text-amber-950"><Award size={21} /></span><div><h3 className="font-semibold text-slate-950">我的成就</h3><p className="text-xs text-slate-600">{stats.badges} 枚徽章，每一枚都对应确定发生的里程碑</p></div></div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(journey.badges || []).map((badge: any) => (
            <article key={badge.id} className="rounded-2xl border border-amber-200 bg-white p-4">
              <div className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700"><Trophy size={16} /></span><div><h4 className="text-sm font-semibold text-slate-900">{badge.title}</h4><p className="mt-1 text-xs leading-5 text-slate-500">{badge.description}</p><p className="mt-2 text-[10px] text-slate-400">{formatDate(badge.awarded_at)}</p></div></div>
            </article>
          ))}
          {(journey.badges || []).length === 0 && <div className="rounded-2xl border border-dashed border-amber-300 px-4 py-8 text-center text-sm text-amber-800">完成一个真实里程碑后，你的第一枚徽章会出现在这里。</div>}
        </div>
      </section>

      <section className="mt-8">
        <h3 className="text-lg font-semibold text-slate-950">一路走来的重要时刻</h3>
        <div className="mt-5 border-l-2 border-slate-200 pl-5">
          {(journey.events || []).map((event: any) => (
            <article key={event.id} className="relative mb-4 rounded-2xl border border-slate-200 bg-white p-4 last:mb-0">
              <span className={`absolute -left-[29px] top-5 h-4 w-4 rounded-full border-4 border-[#f6f7f4] ${event.badge ? 'bg-amber-400' : 'bg-emerald-500'}`} />
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold text-slate-900">{event.title}</h4>{event.status === 'corrected' && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">后来已修正</span>}</div><p className="mt-1 text-xs leading-5 text-slate-600">{event.summary}</p>{event.badge && <div className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-amber-100 px-2.5 py-1.5 text-xs font-medium text-amber-900"><Medal size={13} /> 获得「{event.badge.title}」</div>}</div>
                <time className="text-[11px] text-slate-400">{formatDate(event.occurred_at)}</time>
              </div>
            </article>
          ))}
          {(journey.events || []).length === 0 && <p className="py-8 text-sm text-slate-400">你的成长时间线会从第一次真实完成开始。</p>}
        </div>
      </section>
    </div>
  )
}

function ProfileSection({ profile, draft, editing, saving, onEdit, onCancel, onDraft, onSave }: {
  profile: any
  draft: any
  editing: boolean
  saving: boolean
  onEdit: () => void
  onCancel: () => void
  onDraft: (draft: any) => void
  onSave: () => void
}) {
  const toggleMode = (mode: string) => {
    const modes = draft.preferred_modes || []
    onDraft({ ...draft, preferred_modes: modes.includes(mode) ? modes.filter((item: string) => item !== mode) : [...modes, mode] })
  }
  return (
    <div className="pb-12 pt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><h2 className="text-2xl font-semibold text-slate-950">个人资料</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">这些是由你直接提供的信息。它们帮助系统理解起点和偏好，但不会被当作“已经掌握”的证明。</p></div>
        {!editing && <button type="button" onClick={onEdit} className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"><Edit3 size={15} /> 编辑资料</button>}
      </div>

      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
        {editing ? (
          <div className="grid gap-5 sm:grid-cols-2">
            <ProfileField label="昵称"><input className="form-input" value={draft.display_name || ''} onChange={event => onDraft({ ...draft, display_name: event.target.value })} /></ProfileField>
            <ProfileField label="学习阶段"><select className="form-input" value={draft.education_stage || 'other'} onChange={event => onDraft({ ...draft, education_stage: event.target.value })}>{Object.entries(educationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></ProfileField>
            <ProfileField label="已有基础"><textarea className="form-input resize-none" rows={4} value={draft.background || ''} onChange={event => onDraft({ ...draft, background: event.target.value })} /></ProfileField>
            <div className="grid gap-5">
              <ProfileField label="每周计划投入"><input className="form-input" type="number" min={1} max={80} value={draft.weekly_hours || 1} onChange={event => onDraft({ ...draft, weekly_hours: Number(event.target.value) })} /></ProfileField>
              <ProfileField label="关注方向"><input className="form-input" value={(draft.focus_areas || []).join('，')} onChange={event => onDraft({ ...draft, focus_areas: event.target.value.split(/[，,]/).map((item: string) => item.trim()).filter(Boolean) })} /></ProfileField>
            </div>
            <div className="sm:col-span-2"><p className="text-sm font-medium text-slate-700">偏好的学习方式</p><div className="mt-2 flex flex-wrap gap-2">{Object.entries(modeLabels).map(([mode, label]) => <button key={mode} type="button" onClick={() => toggleMode(mode)} className={`rounded-full border px-3 py-1.5 text-xs font-medium ${(draft.preferred_modes || []).includes(mode) ? 'border-emerald-600 bg-emerald-50 text-emerald-800' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}>{(draft.preferred_modes || []).includes(mode) ? '✓ ' : ''}{label}</button>)}</div></div>
            <ProfileField label="长期方向"><input className="form-input" value={draft.career_goal || ''} onChange={event => onDraft({ ...draft, career_goal: event.target.value })} /></ProfileField>
            <ProfileField label="方向状态"><select className="form-input" value={draft.career_goal_status || 'exploring'} onChange={event => onDraft({ ...draft, career_goal_status: event.target.value })}><option value="exploring">还在探索</option><option value="confirmed">已经确定</option></select></ProfileField>
            <div className="flex gap-2 sm:col-span-2"><button type="button" disabled={saving} onClick={onSave} className="inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"><Save size={15} /> {saving ? '正在保存…' : '保存资料'}</button><button type="button" onClick={onCancel} className="inline-flex items-center gap-2 rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50"><X size={15} /> 取消</button></div>
          </div>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <ProfileInfo label="昵称" value={profile.display_name} />
            <ProfileInfo label="学习阶段" value={educationLabels[profile.education_stage] || '其他'} />
            <ProfileInfo label="每周计划投入" value={`${profile.weekly_hours} 小时`} />
            <ProfileInfo label="方向状态" value={profile.career_goal_status === 'confirmed' ? '已经确定' : '还在探索'} />
            <ProfileInfo label="已有基础" value={profile.background || '尚未填写'} wide />
            <ProfileInfo label="关注方向" value={(profile.focus_areas || []).join('、') || '探索中'} />
            <ProfileInfo label="学习方式" value={(profile.preferred_modes || []).map((item: string) => modeLabels[item] || item).join('、') || '未设置'} />
            <ProfileInfo label="长期方向" value={profile.career_goal || '探索中'} wide />
          </div>
        )}
      </section>
    </div>
  )
}

function sourceTone(kind: string) {
  if (kind === 'verified') return 'bg-emerald-100 text-emerald-800'
  if (kind === 'corrected') return 'bg-sky-100 text-sky-800'
  if (kind === 'self_reported') return 'bg-amber-100 text-amber-800'
  if (kind === 'exposure_only') return 'bg-slate-100 text-slate-600'
  return 'bg-violet-100 text-violet-700'
}

function GrowthStat({ value, label, attention = false }: { value: number; label: string; attention?: boolean }) {
  return <div className="bg-white px-4 py-5 sm:px-5"><p className={`text-2xl font-semibold ${attention ? 'text-amber-700' : 'text-slate-950'}`}>{value}</p><p className="mt-1 text-xs leading-5 text-slate-500">{label}</p></div>
}

function ProfileField({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="text-sm font-medium text-slate-700">{label}<div className="mt-1.5">{children}</div></label>
}

function ProfileInfo({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <div className={wide ? 'sm:col-span-2' : ''}><p className="text-xs text-slate-400">{label}</p><p className="mt-1.5 break-words text-sm font-medium leading-6 text-slate-800">{value}</p></div>
}
