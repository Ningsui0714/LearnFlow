import { useEffect, useMemo, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  BookOpenCheck, Bot, Braces, ChevronLeft, ChevronRight, Send, Sparkles,
} from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { askCodeQuestion, askQuestion } from '../../services/api'
import TutorPanel from '../tutor/TutorPanel'
import { useWorkspace } from './WorkspaceContext'
import {
  subscribeWorkspaceAgentContext, type WorkspaceAgentContext,
} from './workspaceAgentContext'

type PrimaryAgentId = 'tutor_agent' | 'learning_design_agent' | 'practice_agent'
type ConversationMessage = {
  role: 'user' | 'assistant'
  content: string
  kind?: 'chat' | 'trace'
  trace?: any
}

const AGENTS = {
  tutor_agent: {
    name: 'Tutor 控制 Agent',
    shortName: 'Tutor',
    subtitle: '目标澄清、项目协调与行动确认',
    icon: Bot,
    tone: 'emerald',
  },
  learning_design_agent: {
    name: '学习设计 Agent',
    shortName: 'Design',
    subtitle: '围绕当前讲义解释、举例与追问',
    icon: BookOpenCheck,
    tone: 'sky',
  },
  practice_agent: {
    name: '实践与验证 Agent',
    shortName: 'Practice',
    subtitle: '围绕当前练习、代码与错误继续对话',
    icon: Braces,
    tone: 'violet',
  },
} satisfies Record<PrimaryAgentId, {
  name: string
  shortName: string
  subtitle: string
  icon: typeof Bot
  tone: 'emerald' | 'sky' | 'violet'
}>

function deriveConversation(pathname: string) {
  const exercise = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)\/exercises$/)
  if (exercise) {
    return {
      agentId: 'practice_agent' as const,
      projectId: Number(exercise[1]),
      checkpointId: Number(exercise[2]),
      scope: `关卡 ${exercise[2]} · 当前练习`,
    }
  }

  const checkpoint = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)$/)
  if (checkpoint) {
    return {
      agentId: 'learning_design_agent' as const,
      projectId: Number(checkpoint[1]),
      checkpointId: Number(checkpoint[2]),
      scope: `关卡 ${checkpoint[2]} · 当前讲义`,
    }
  }

  const project = pathname.match(/^\/projects\/(\d+)$/)
  if (project) {
    return {
      agentId: 'tutor_agent' as const,
      projectId: Number(project[1]),
      checkpointId: undefined,
      scope: `项目 ${project[1]}`,
    }
  }

  return {
    agentId: 'tutor_agent' as const,
    projectId: undefined,
    checkpointId: undefined,
    scope: pathname === '/agent' ? '全局会话' : '学习者全局',
  }
}

const QUICK_PROMPTS: Record<'learning_design_agent' | 'practice_agent', string[]> = {
  learning_design_agent: ['换种讲法', '分步骤说明', '给我一个示例'],
  practice_agent: ['分析当前错误', '给下一步提示', '解释这段代码'],
}

function toneClasses(tone: 'emerald' | 'sky' | 'violet') {
  if (tone === 'sky') return 'bg-sky-600 text-white'
  if (tone === 'violet') return 'bg-violet-600 text-white'
  return 'bg-emerald-700 text-white'
}

function ScopedConversation({
  agentId, checkpointId, context, histories, setHistories, drafts, setDrafts,
  loadingKey, setLoadingKey,
}: {
  agentId: 'learning_design_agent' | 'practice_agent'
  checkpointId: number
  context: WorkspaceAgentContext | null
  histories: Record<string, ConversationMessage[]>
  setHistories: Dispatch<SetStateAction<Record<string, ConversationMessage[]>>>
  drafts: Record<string, string>
  setDrafts: Dispatch<SetStateAction<Record<string, string>>>
  loadingKey: string | null
  setLoadingKey: Dispatch<SetStateAction<string | null>>
}) {
  const scopeSuffix = agentId === 'practice_agent'
    ? `${checkpointId}:${context?.kind === 'practice' ? context.exerciseId || 'checkpoint' : 'checkpoint'}`
    : String(checkpointId)
  const sessionKey = `${agentId}:${scopeSuffix}`
  const endRef = useRef<HTMLDivElement>(null)
  const messages = histories[sessionKey] || []
  const input = drafts[sessionKey] || ''
  const loading = loadingKey === sessionKey

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (prompt?: string) => {
    const question = (prompt ?? input).trim()
    if (!question || loading) return
    const history = messages.map(message => ({ role: message.role, content: message.content }))
    setDrafts(current => ({ ...current, [sessionKey]: '' }))
    setHistories(current => ({
      ...current,
      [sessionKey]: [...(current[sessionKey] || []), { role: 'user', content: question }],
    }))
    setLoadingKey(sessionKey)

    try {
      if (agentId === 'learning_design_agent') {
        const result = await askQuestion(checkpointId, {
          selection: context?.kind === 'learning_design' ? context.selection || '' : '',
          question,
          history,
        })
        const reply: ConversationMessage = result.kind === 'trace'
          ? { role: 'assistant', content: '', kind: 'trace', trace: result.trace }
          : { role: 'assistant', content: result.answer || '暂时没有生成回答。' }
        setHistories(current => ({
          ...current,
          [sessionKey]: [...(current[sessionKey] || []), reply],
        }))
      } else {
        const result = await askCodeQuestion({
          code: context?.kind === 'practice' ? context.code || '' : '',
          selection: context?.kind === 'practice' ? context.selection || '' : '',
          question,
          context: context?.kind === 'practice' ? context.title || '' : '',
        })
        setHistories(current => ({
          ...current,
          [sessionKey]: [...(current[sessionKey] || []), {
            role: 'assistant', content: result.answer || '暂时没有生成回答。',
          }],
        }))
      }
    } catch (error: any) {
      setHistories(current => ({
        ...current,
        [sessionKey]: [...(current[sessionKey] || []), {
          role: 'assistant',
          content: `请求失败：${error?.response?.data?.detail || error?.message || '请稍后重试'}`,
        }],
      }))
    } finally {
      setLoadingKey(current => current === sessionKey ? null : current)
    }
  }

  const contextSelection = context?.kind !== 'project_tutor'
    && context?.checkpointId === checkpointId
    ? context.selection
    : ''
  const prompts = QUICK_PROMPTS[agentId]

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="shrink-0 border-b border-slate-200 px-3 py-2">
        {contextSelection ? (
          <p className="truncate rounded-md bg-slate-100 px-2.5 py-1.5 text-[11px] text-slate-600" title={contextSelection}>
            当前选中：{contextSelection}
          </p>
        ) : (
          <p className="text-[11px] leading-5 text-slate-500">
            {agentId === 'practice_agent'
              ? '对话会自动带入当前练习与编辑器代码。'
              : '选中讲义文字后，对话会自动带入该段内容。'}
          </p>
        )}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {prompts.map(prompt => (
            <button
              key={prompt}
              type="button"
              onClick={() => send(prompt)}
              disabled={loading}
              className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] text-slate-600 hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="py-10 text-center text-xs leading-6 text-slate-400">
            {agentId === 'practice_agent'
              ? '可以询问当前练习、选中代码或错误原因。'
              : '可以追问当前讲义，也可以选中一段后再提问。'}
          </div>
        )}
        {messages.map((message, index) => (
          <div key={`${sessionKey}-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {message.kind === 'trace' ? (
              <div className="max-w-[94%] rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs leading-5 text-slate-700">
                <p className="font-semibold text-sky-800">溯源结果</p>
                <p className="mt-1">{message.trace?.preview || message.trace?.reason || '未找到对应来源。'}</p>
              </div>
            ) : (
              <div className={`max-w-[92%] rounded-lg px-3 py-2 text-sm leading-6 ${message.role === 'user' ? 'whitespace-pre-wrap bg-slate-900 text-white' : 'agent-drawer-markdown border border-slate-200 bg-slate-50 text-slate-800'}`}>
                {message.role === 'assistant'
                  ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                  : message.content}
              </div>
            )}
          </div>
        ))}
        {loading && <p className="text-xs text-slate-400 animate-pulse">正在思考...</p>}
        <div ref={endRef} />
      </div>

      <div className="shrink-0 border-t border-slate-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            data-agent-conversation-input
            rows={2}
            value={input}
            onChange={event => setDrafts(current => ({ ...current, [sessionKey]: event.target.value }))}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            placeholder="输入问题，Enter 发送"
            className="min-w-0 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-100"
          />
          <button
            type="button"
            onClick={() => send()}
            disabled={loading || !input.trim()}
            title="发送"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-300"
          >
            <Send size={15} />
          </button>
        </div>
      </div>
    </section>
  )
}

export default function WorkspaceAgentRail({
  expanded, onToggle,
}: {
  expanded: boolean
  onToggle: () => void
}) {
  const location = useLocation()
  const { openPath } = useWorkspace()
  const state = useMemo(() => deriveConversation(location.pathname), [location.pathname])
  const agent = AGENTS[state.agentId]
  const AgentIcon = agent.icon
  const [operationContext, setOperationContext] = useState<WorkspaceAgentContext | null>(null)
  const [histories, setHistories] = useState<Record<string, ConversationMessage[]>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loadingKey, setLoadingKey] = useState<string | null>(null)

  useEffect(() => subscribeWorkspaceAgentContext(setOperationContext), [])

  const projectContext = operationContext?.kind === 'project_tutor'
    && operationContext.projectId === state.projectId
    ? operationContext
    : null
  const checkpointContext = operationContext?.kind !== 'project_tutor'
    && operationContext?.checkpointId === state.checkpointId
    ? operationContext
    : null

  if (!expanded) {
    return (
      <aside className="flex h-full w-full flex-col items-center border-l border-slate-200 bg-white py-2" aria-label={`${agent.name} 对话已收起`}>
        <button
          type="button"
          onClick={onToggle}
          title={`展开 ${agent.name} 对话`}
          aria-label={`展开 ${agent.name} 对话`}
          className={`flex h-9 w-9 items-center justify-center rounded-lg ${toneClasses(agent.tone)}`}
        >
          <AgentIcon size={17} />
        </button>
        <button
          type="button"
          onClick={onToggle}
          className="mt-3 flex min-h-0 flex-1 items-start justify-center text-[10px] font-semibold tracking-[0.14em] text-slate-500 hover:text-slate-900"
          style={{ writingMode: 'vertical-rl' }}
        >
          {agent.name} · 点击展开对话
        </button>
        <button type="button" onClick={onToggle} title="展开对话" className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <ChevronLeft size={16} />
        </button>
      </aside>
    )
  }

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-slate-200 bg-white shadow-xl 2xl:shadow-none" aria-label={`${agent.name} 对话窗口`}>
      <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-slate-200 bg-white px-3">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${toneClasses(agent.tone)}`}>
          <AgentIcon size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h2 className="truncate text-xs font-semibold text-slate-900">{agent.name}</h2>
            <Sparkles size={11} className="shrink-0 text-amber-500" />
          </div>
          <p className="truncate text-[10px] text-slate-500">{state.scope} · {agent.subtitle}</p>
        </div>
        <button type="button" onClick={onToggle} title="收起 Agent 对话" className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <ChevronRight size={16} />
        </button>
      </header>

      {state.agentId === 'tutor_agent' ? (
        <TutorPanel
          key={`tutor:${state.projectId || 'global'}`}
          projectId={state.projectId}
          className="min-h-0 flex-1 rounded-none border-0"
          onProjectChange={project => project?.id && openPath(`/projects/${project.id}`, { title: project.name || `项目 ${project.id}`, kind: 'project', projectId: project.id })}
          onProposalAccepted={project => project?.id && openPath(`/projects/${project.id}`, { title: project.name || `项目 ${project.id}`, kind: 'project', projectId: project.id })}
          onCheckpointChange={checkpoint => state.projectId && openPath(`/projects/${state.projectId}/checkpoints/${checkpoint.id}`, { title: checkpoint.title || `关卡 ${checkpoint.id}`, kind: 'lecture', projectId: state.projectId, checkpointId: checkpoint.id })}
          onRoadmapUpdate={roadmap => {
            projectContext?.onRoadmapUpdate?.(roadmap)
            window.dispatchEvent(new CustomEvent('learnflow:roadmap-changed'))
          }}
          projectProposal={projectContext?.projectProposal}
          projectSources={projectContext?.projectSources}
          candidateSourcesRefreshing={projectContext?.candidateSourcesRefreshing}
          addingCandidateUrl={projectContext?.addingCandidateUrl}
          onRefreshCandidateSources={projectContext?.onRefreshCandidateSources}
          onAddCandidateSource={projectContext?.onAddCandidateSource}
        />
      ) : (
        <ScopedConversation
          agentId={state.agentId}
          checkpointId={state.checkpointId!}
          context={checkpointContext}
          histories={histories}
          setHistories={setHistories}
          drafts={drafts}
          setDrafts={setDrafts}
          loadingKey={loadingKey}
          setLoadingKey={setLoadingKey}
        />
      )}
    </aside>
  )
}
