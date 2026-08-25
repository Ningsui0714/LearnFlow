import { FormEvent, lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import {
  isTutorMode,
  requestTutorEnvironmentStatus,
  requestTutorReply,
  resolveTutorMode,
  TUTOR_MODE_LABELS,
  tutorConfigurationIssue,
  type TutorMode,
} from './tutor'
import './styles.css'

type Message = {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  createdAt: number
  tutorMode?: TutorMode
}

type Conversation = {
  id: string
  title: string
  messages: Message[]
  updatedAt: number
  mode: TutorMode
}

type WorkspaceTab = {
  id: string
  kind: 'chat' | 'settings'
  title: string
  conversationId?: string
}

type SettingsState = {
  baseUrl: string
  model: string
}

type PersistedState = {
  conversations: Conversation[]
  tabs: WorkspaceTab[]
  activeTabId: string
  splitTabId: string
  settings: SettingsState
}

const STORAGE_KEY = 'learnflow.vnext.workspace.v1'
const SETTINGS_TAB: WorkspaceTab = { id: 'settings', kind: 'settings', title: '设置' }
const MarkdownContent = lazy(() => import('./MarkdownContent'))

function uid(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function createConversation(): Conversation {
  const now = Date.now()
  return {
    id: uid('chat'),
    title: '新对话',
    updatedAt: now,
    mode: 'free',
    messages: [{
      id: uid('message'),
      role: 'assistant',
      content: '现在处于自由态。你可以直接讨论学习问题；遇到明确的解释请求时，我会把那一轮切到简单讲解态。',
      createdAt: now,
      tutorMode: 'free',
    }],
  }
}

function chatTab(conversation: Conversation): WorkspaceTab {
  return {
    id: `chat:${conversation.id}`,
    kind: 'chat',
    title: conversation.title,
    conversationId: conversation.id,
  }
}

function initialState(): PersistedState {
  const conversation = createConversation()
  const tab = chatTab(conversation)
  return {
    conversations: [conversation],
    tabs: [tab],
    activeTabId: tab.id,
    splitTabId: '',
    settings: {
      baseUrl: 'https://api.example.com/v1',
      model: '',
    },
  }
}

function restoreState(): PersistedState {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') as Partial<PersistedState> | null
    if (!value || !Array.isArray(value.conversations) || value.conversations.length === 0) return initialState()
    const conversations = value.conversations.map(conversation => ({
      ...conversation,
      mode: isTutorMode(conversation.mode) ? conversation.mode : 'free' as const,
    }))
    const conversationIds = new Set(conversations.map(item => item.id))
    const tabs = Array.isArray(value.tabs)
      ? value.tabs.filter(tab => tab?.kind === 'settings' || (tab?.conversationId && conversationIds.has(tab.conversationId)))
      : []
    const safeTabs = tabs.length > 0 ? tabs.slice(-12) : [chatTab(conversations[0])]
    const activeTabId = safeTabs.some(tab => tab.id === value.activeTabId)
      ? String(value.activeTabId)
      : safeTabs[0].id
    const splitTabId = safeTabs.some(tab => tab.id === value.splitTabId)
      && value.splitTabId !== activeTabId
      ? String(value.splitTabId)
      : ''
    return {
      conversations,
      tabs: safeTabs,
      activeTabId,
      splitTabId,
      settings: {
        baseUrl: value.settings?.baseUrl || 'https://api.example.com/v1',
        model: value.settings?.model || '',
      },
    }
  } catch {
    return initialState()
  }
}

function pathForTab(tab: WorkspaceTab) {
  return tab.kind === 'settings' ? '/settings' : `/chat/${tab.conversationId}`
}

function WorkspaceIcon({ kind }: { kind: WorkspaceTab['kind'] }) {
  return <span aria-hidden="true" className="tab-icon">{kind === 'settings' ? '⚙' : '□'}</span>
}

function App() {
  const [workspace, setWorkspace] = useState<PersistedState>(restoreState)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const [pendingTurns, setPendingTurns] = useState<Record<string, TutorMode>>({})
  const [tutorEnvironment, setTutorEnvironment] = useState({ checking: true, configured: false, source: '' })

  const activeTab = workspace.tabs.find(tab => tab.id === workspace.activeTabId) || workspace.tabs[0]
  const splitTab = workspace.tabs.find(tab => tab.id === workspace.splitTabId && tab.id !== activeTab?.id)
  const activeConversation = activeTab?.kind === 'chat'
    ? workspace.conversations.find(item => item.id === activeTab.conversationId)
    : undefined
  const splitConversation = splitTab?.kind === 'chat'
    ? workspace.conversations.find(item => item.id === splitTab.conversationId)
    : undefined

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace))
  }, [workspace])

  useEffect(() => {
    let active = true
    requestTutorEnvironmentStatus().then(status => {
      if (active) setTutorEnvironment({ checking: false, ...status })
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!activeTab) return
    window.history.replaceState({ tabId: activeTab.id }, '', pathForTab(activeTab))
    document.title = `${activeTab.title} · LearnFlow vNext`
  }, [activeTab])

  useEffect(() => {
    if (!pendingDelete) return
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPendingDelete(null)
    }
    window.addEventListener('keydown', cancelOnEscape)
    return () => window.removeEventListener('keydown', cancelOnEscape)
  }, [pendingDelete])

  const openTab = (next: WorkspaceTab) => {
    setWorkspace(previous => {
      const existing = previous.tabs.find(tab => tab.id === next.id)
      const tabs = existing
        ? previous.tabs.map(tab => tab.id === next.id ? { ...tab, ...next } : tab)
        : [...previous.tabs, next].slice(-12)
      const splitTabId = previous.splitTabId === next.id
        ? previous.activeTabId
        : previous.splitTabId
      return {
        ...previous,
        tabs,
        activeTabId: next.id,
        splitTabId: splitTabId !== next.id && tabs.some(tab => tab.id === splitTabId) ? splitTabId : '',
      }
    })
    setSidebarOpen(false)
  }

  const newConversation = () => {
    const conversation = createConversation()
    const tab = chatTab(conversation)
    setWorkspace(previous => {
      const tabs = [...previous.tabs, tab].slice(-12)
      return {
        ...previous,
        conversations: [conversation, ...previous.conversations],
        tabs,
        activeTabId: tab.id,
        splitTabId: tabs.some(item => item.id === previous.splitTabId) ? previous.splitTabId : '',
      }
    })
    setSidebarOpen(false)
  }

  const closeTab = (tabId: string) => {
    setWorkspace(previous => {
      const index = previous.tabs.findIndex(tab => tab.id === tabId)
      if (index < 0) return previous
      let tabs = previous.tabs.filter(tab => tab.id !== tabId)
      if (tabs.length === 0) {
        const fallbackConversation = previous.conversations[0] || createConversation()
        const fallbackTab = chatTab(fallbackConversation)
        tabs = [fallbackTab]
        return {
          ...previous,
          conversations: previous.conversations.length ? previous.conversations : [fallbackConversation],
          tabs,
          activeTabId: fallbackTab.id,
          splitTabId: '',
        }
      }
      const survivingSplit = tabs.find(tab => tab.id === previous.splitTabId)
      const activeTabId = previous.activeTabId === tabId
        ? (survivingSplit || tabs[index] || tabs[index - 1] || tabs[0]).id
        : previous.activeTabId
      const splitTabId = previous.activeTabId === tabId || previous.splitTabId === tabId
        ? ''
        : previous.splitTabId
      return {
        ...previous,
        tabs,
        activeTabId,
        splitTabId: splitTabId !== activeTabId && tabs.some(tab => tab.id === splitTabId) ? splitTabId : '',
      }
    })
  }

  const toggleSplit = (tabId: string) => {
    setWorkspace(previous => {
      if (tabId === previous.activeTabId || !previous.tabs.some(tab => tab.id === tabId)) return previous
      return { ...previous, splitTabId: previous.splitTabId === tabId ? '' : tabId }
    })
  }

  const closeSplit = () => {
    setWorkspace(previous => ({ ...previous, splitTabId: '' }))
  }

  const deleteConversation = (conversationId: string) => {
    setWorkspace(previous => {
      let conversations = previous.conversations.filter(conversation => conversation.id !== conversationId)
      let tabs = previous.tabs.filter(tab => tab.conversationId !== conversationId)

      if (conversations.length === 0) {
        const conversation = createConversation()
        const tab = chatTab(conversation)
        return {
          ...previous,
          conversations: [conversation],
          tabs: [tab],
          activeTabId: tab.id,
          splitTabId: '',
        }
      }

      if (tabs.length === 0) tabs = [chatTab(conversations[0])]
      const activeSurvives = tabs.some(tab => tab.id === previous.activeTabId)
      const splitSurvives = tabs.find(tab => tab.id === previous.splitTabId)
      const activeTabId = activeSurvives ? previous.activeTabId : (splitSurvives || tabs[0]).id
      const splitTabId = activeSurvives && splitSurvives && splitSurvives.id !== activeTabId
        ? splitSurvives.id
        : ''

      return { ...previous, conversations, tabs, activeTabId, splitTabId }
    })
    setDrafts(previous => {
      const next = { ...previous }
      delete next[conversationId]
      return next
    })
    setPendingTurns(previous => {
      const next = { ...previous }
      delete next[conversationId]
      return next
    })
    setPendingDelete(null)
  }

  const setConversationMode = (conversationId: string, mode: TutorMode) => {
    if (pendingTurns[conversationId]) return
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => (
        conversation.id === conversationId ? { ...conversation, mode } : conversation
      )),
    }))
  }

  const finishTurn = (conversationId: string, mode: TutorMode, message: Omit<Message, 'id' | 'createdAt'>) => {
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => (
        conversation.id === conversationId
          ? {
              ...conversation,
              mode: 'free',
              updatedAt: Date.now(),
              messages: [
                ...conversation.messages,
                { ...message, id: uid('message'), createdAt: Date.now(), tutorMode: message.role === 'assistant' ? mode : undefined },
              ],
            }
          : conversation
      )),
    }))
    setPendingTurns(previous => {
      const next = { ...previous }
      delete next[conversationId]
      return next
    })
  }

  const sendMessage = async (conversationId: string, event: FormEvent) => {
    event.preventDefault()
    const content = (drafts[conversationId] || '').trim()
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!content || !conversation || pendingTurns[conversationId]) return

    const mode = resolveTutorMode(conversation.mode, content)
    const now = Date.now()
    const contextMessages = [
      ...conversation.messages
        .filter((message): message is Message & { role: 'assistant' | 'user' } => message.role !== 'system')
        .map(message => ({ role: message.role, content: message.content })),
      { role: 'user' as const, content },
    ]

    setPendingTurns(previous => ({ ...previous, [conversationId]: mode }))
    setWorkspace(previous => {
      const conversations = previous.conversations.map(conversation => {
        if (conversation.id !== conversationId) return conversation
        const firstStudentMessage = !conversation.messages.some(message => message.role === 'user')
        return {
          ...conversation,
          title: firstStudentMessage ? content.slice(0, 22) : conversation.title,
          updatedAt: now,
          mode,
          messages: [
            ...conversation.messages,
            { id: uid('message'), role: 'user' as const, content, createdAt: now, tutorMode: mode },
          ],
        }
      })
      const current = conversations.find(item => item.id === conversationId)
      if (!current) return previous
      const tabs = previous.tabs.map(tab => tab.conversationId === current.id ? { ...tab, title: current.title } : tab)
      return { ...previous, conversations, tabs }
    })
    setDrafts(previous => ({ ...previous, [conversationId]: '' }))

    const configurationIssue = tutorConfigurationIssue(workspace.settings.baseUrl, workspace.settings.model)
    if (configurationIssue) {
      finishTurn(conversationId, mode, {
        role: 'system',
        content: `本轮已识别为“${TUTOR_MODE_LABELS[mode]}”，但模型连接还不能使用：${configurationIssue}`,
      })
      return
    }

    try {
      const reply = await requestTutorReply({
        baseUrl: workspace.settings.baseUrl,
        model: workspace.settings.model,
        mode,
        messages: contextMessages,
      })
      finishTurn(conversationId, mode, { role: 'assistant', content: reply })
    } catch (error) {
      finishTurn(conversationId, mode, {
        role: 'system',
        content: `“${TUTOR_MODE_LABELS[mode]}”请求失败：${error instanceof Error ? error.message : '未知错误'}`,
      })
    }
  }

  const updateSettings = (patch: Partial<SettingsState>) => {
    setSettingsSaved(false)
    setWorkspace(previous => ({ ...previous, settings: { ...previous.settings, ...patch } }))
  }

  const renderTab = (tab: WorkspaceTab | undefined) => {
    if (!tab) return null
    if (tab.kind === 'settings') {
      return (
        <section className="settings-page">
          <div className="settings-intro">
            <span className="eyebrow">SETTINGS</span>
            <h1>设置</h1>
            <p>自由态和简单讲解态共用这一条模型连接，不读取旧项目配置。</p>
          </div>
          <form className="settings-card" onSubmit={event => { event.preventDefault(); setSettingsSaved(true) }}>
            <div className="settings-card-heading"><span>01</span><div><h2>模型连接</h2><p>支持 OpenAI 兼容的 Chat Completions 或 Responses 地址。</p></div></div>
            <label>
              <span>Base URL</span>
              <input value={workspace.settings.baseUrl} onChange={event => updateSettings({ baseUrl: event.target.value })} placeholder="https://api.example.com/v1" />
            </label>
            <label>
              <span>模型名称</span>
              <input value={workspace.settings.model} onChange={event => updateSettings({ model: event.target.value })} placeholder="例如 model-name" />
            </label>
            <div className={`environment-key ${tutorEnvironment.configured ? 'environment-key-ready' : 'environment-key-missing'}`}>
              <span className="environment-key-icon">{tutorEnvironment.checking ? '…' : tutorEnvironment.configured ? '✓' : '!'}</span>
              <div>
                <span>API Key</span>
                <strong>{tutorEnvironment.checking ? '正在检查本地环境' : tutorEnvironment.configured ? '本地环境已配置' : '本地环境未配置'}</strong>
                <small>
                  {tutorEnvironment.configured
                    ? `来源：${tutorEnvironment.source}。Key 只由本地服务读取，不会发送到页面。`
                    : '在 vnext/.env.local 中设置 LEARNFLOW_API_KEY，然后重启服务。'}
                </small>
              </div>
            </div>
            <div className="settings-actions">
              <button type="submit">保存界面配置</button>
              <span className={settingsSaved ? 'save-status save-status-visible' : 'save-status'}>✓ 已保存</span>
            </div>
          </form>
        </section>
      )
    }

    const conversation = workspace.conversations.find(item => item.id === tab.conversationId)
    if (!conversation) return null
    const pendingMode = pendingTurns[conversation.id]
    const visibleMode = pendingMode || conversation.mode
    return (
      <section className="chat-page">
        <header className="chat-heading">
          <h1>{conversation.title}</h1>
          <div className="chat-state-stack">
            <span className={`mode-badge mode-badge-${visibleMode}`}>{TUTOR_MODE_LABELS[visibleMode]}</span>
            <span className="local-label">{workspace.settings.model || '待配置模型'}</span>
          </div>
        </header>
        <MessageList messages={conversation.messages} />
        <div className="composer-dock">
          <form className="composer" onSubmit={event => sendMessage(conversation.id, event)}>
            {pendingMode && <div className="turn-progress" role="status"><i /> {TUTOR_MODE_LABELS[pendingMode]}正在组织回复…</div>}
            <textarea
              value={drafts[conversation.id] || ''}
              onChange={event => setDrafts(previous => ({ ...previous, [conversation.id]: event.target.value }))}
              disabled={Boolean(pendingMode)}
              onKeyDown={event => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
              placeholder="发送消息…"
              rows={2}
            />
            <div className="composer-footer">
              <div className="composer-tools">
                <div className="mode-options" aria-label="选择 Tutor 状态">
                  <button type="button" title="自由讨论；解释请求仍可自动进入简单讲解" aria-pressed={conversation.mode === 'free'} disabled={Boolean(pendingMode)} onClick={() => setConversationMode(conversation.id, 'free')}>自由态</button>
                  <button type="button" title="下一轮使用简单讲解，完成后回到自由态" aria-pressed={conversation.mode === 'simple_explain'} disabled={Boolean(pendingMode)} onClick={() => setConversationMode(conversation.id, 'simple_explain')}>简单讲解</button>
                </div>
                <span>Shift + Enter 换行</span>
              </div>
              <button type="submit" disabled={Boolean(pendingMode) || !(drafts[conversation.id] || '').trim()} aria-label={pendingMode ? 'Tutor 回复中' : '发送消息'}>{pendingMode ? '…' : '↑'}</button>
            </div>
          </form>
        </div>
      </section>
    )
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="icon-button mobile-only" type="button" onClick={() => setSidebarOpen(value => !value)} aria-label="打开对话列表">☰</button>
        <button className="brand" type="button" onClick={newConversation} aria-label="新建 LearnFlow 对话">
          <span className="brand-mark">✦</span>
          <span><strong>LearnFlow</strong><small>vNext · clean start</small></span>
        </button>
        <div className="topbar-spacer" />
        <span className="prototype-badge"><i /> 本地界面原型</span>
        <button className="icon-button" type="button" onClick={() => openTab(SETTINGS_TAB)} aria-label="打开设置">⚙</button>
      </header>

      <div className="workspace">
        <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
          <div className="sidebar-heading">
            <div><span>CONVERSATIONS</span><strong>对话</strong></div>
            <button type="button" onClick={newConversation} aria-label="新建对话">＋</button>
          </div>
          <nav className="conversation-list" aria-label="对话列表">
            {workspace.conversations.map(conversation => (
              <div
                key={conversation.id}
                className={`conversation-row ${activeConversation?.id === conversation.id ? 'conversation-active' : ''} ${splitConversation?.id === conversation.id ? 'conversation-secondary' : ''}`}
              >
                <button type="button" className="conversation-open" onClick={() => openTab(chatTab(conversation))}>
                  <span className="conversation-glyph">□</span>
                  <span><strong>{conversation.title}</strong><small>{conversation.messages.filter(message => message.role === 'user').length} 条输入</small></span>
                </button>
                <button type="button" className="conversation-delete" onClick={() => setPendingDelete(conversation)} aria-label={`删除对话${conversation.title}`} title="删除对话">⌫</button>
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <p>当前只有 Chat 和设置。</p>
            <span>产品逻辑见 LOGIC.md</span>
          </div>
        </aside>

        {sidebarOpen && <button className="sidebar-scrim" type="button" onClick={() => setSidebarOpen(false)} aria-label="关闭对话列表" />}

        <main className="main-stage">
          <nav className="tabs" aria-label="已打开页面">
            {workspace.tabs.map(tab => (
              <div key={tab.id} className={`tab ${tab.id === activeTab?.id ? 'tab-active' : ''} ${tab.id === splitTab?.id ? 'tab-secondary' : ''}`}>
                <button type="button" className="tab-main" onClick={() => openTab(tab)}>
                  <WorkspaceIcon kind={tab.kind} />
                  <span>{tab.title}</span>
                </button>
                {tab.id !== activeTab?.id && (
                  <button
                    type="button"
                    className="tab-split"
                    onClick={() => toggleSplit(tab.id)}
                    aria-label={`${tab.id === splitTab?.id ? '取消并排' : '并排显示'}${tab.title}`}
                    title={tab.id === splitTab?.id ? '取消并排' : '并排显示'}
                  >▥</button>
                )}
                <button type="button" className="tab-close" onClick={() => closeTab(tab.id)} aria-label={`关闭${tab.title}`}>×</button>
              </div>
            ))}
          </nav>

          <div className={`pane-group ${splitTab ? 'pane-group-split' : ''}`}>
            <div className="page-pane">{renderTab(activeTab)}</div>
            {splitTab && (
              <div className="page-pane page-pane-secondary">
                <header className="split-pane-bar"><span>并排 · {splitTab.title}</span><button type="button" onClick={closeSplit} aria-label="关闭并排页面">×</button></header>
                {renderTab(splitTab)}
              </div>
            )}
          </div>
        </main>
      </div>

      {pendingDelete && (
        <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setPendingDelete(null) }}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
            <span className="dialog-eyebrow">DELETE CONVERSATION</span>
            <h2 id="delete-dialog-title">删除“{pendingDelete.title}”？</h2>
            <p>只会删除 vNext 当前浏览器中的这段对话和对应页签。此操作无法撤销。</p>
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={() => setPendingDelete(null)}>取消</button>
              <button type="button" className="button-danger" onClick={() => deleteConversation(pendingDelete.id)}>删除对话</button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function MessageList({ messages }: { messages: Message[] }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length])
  const visibleMessages = useMemo(() => messages, [messages])

  return (
    <div className="messages" aria-live="polite">
      <div className="message-column">
        {visibleMessages.map(message => (
          <article key={message.id} className={`message message-${message.role}`}>
            {message.role !== 'user' && <span className="message-avatar">{message.role === 'assistant' ? '✦' : 'i'}</span>}
            <div className="message-content">
              <div className="message-meta">
                {message.role === 'user' ? '你' : message.role === 'assistant' ? 'Tutor' : '系统'}
                {message.tutorMode && <em>{TUTOR_MODE_LABELS[message.tutorMode]}</em>}
              </div>
              <Suspense fallback={<div className="markdown-loading">正在排版…</div>}>
                <MarkdownContent content={message.content} />
              </Suspense>
            </div>
          </article>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}

const rootElement = document.getElementById('root')!
const rootScope = globalThis as typeof globalThis & { __learnflowVNextRoot?: Root }
const root = rootScope.__learnflowVNextRoot || createRoot(rootElement)
rootScope.__learnflowVNextRoot = root
root.render(<App />)
