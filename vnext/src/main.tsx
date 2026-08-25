import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Message = {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  createdAt: number
}

type Conversation = {
  id: string
  title: string
  messages: Message[]
  updatedAt: number
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
  settings: SettingsState
}

const STORAGE_KEY = 'learnflow.vnext.workspace.v1'
const SETTINGS_TAB: WorkspaceTab = { id: 'settings', kind: 'settings', title: '设置' }

function uid(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function createConversation(): Conversation {
  const now = Date.now()
  return {
    id: uid('chat'),
    title: '新对话',
    updatedAt: now,
    messages: [{
      id: uid('message'),
      role: 'assistant',
      content: '这是一个干净的 vNext 对话。现在只验证 Chat 和工作区，不接入旧系统逻辑。',
      createdAt: now,
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
    const conversationIds = new Set(value.conversations.map(item => item.id))
    const tabs = Array.isArray(value.tabs)
      ? value.tabs.filter(tab => tab?.kind === 'settings' || (tab?.conversationId && conversationIds.has(tab.conversationId)))
      : []
    const safeTabs = tabs.length > 0 ? tabs.slice(-12) : [chatTab(value.conversations[0])]
    const activeTabId = safeTabs.some(tab => tab.id === value.activeTabId)
      ? String(value.activeTabId)
      : safeTabs[0].id
    return {
      conversations: value.conversations,
      tabs: safeTabs,
      activeTabId,
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
  const [apiKey, setApiKey] = useState('')
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const activeTab = workspace.tabs.find(tab => tab.id === workspace.activeTabId) || workspace.tabs[0]
  const activeConversation = activeTab?.kind === 'chat'
    ? workspace.conversations.find(item => item.id === activeTab.conversationId)
    : undefined

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace))
  }, [workspace])

  useEffect(() => {
    if (!activeTab) return
    window.history.replaceState({ tabId: activeTab.id }, '', pathForTab(activeTab))
    document.title = `${activeTab.title} · LearnFlow vNext`
  }, [activeTab])

  const openTab = (next: WorkspaceTab) => {
    setWorkspace(previous => {
      const existing = previous.tabs.find(tab => tab.id === next.id)
      const tabs = existing
        ? previous.tabs.map(tab => tab.id === next.id ? { ...tab, ...next } : tab)
        : [...previous.tabs, next].slice(-12)
      return { ...previous, tabs, activeTabId: next.id }
    })
    setSidebarOpen(false)
  }

  const newConversation = () => {
    const conversation = createConversation()
    const tab = chatTab(conversation)
    setWorkspace(previous => ({
      ...previous,
      conversations: [conversation, ...previous.conversations],
      tabs: [...previous.tabs, tab].slice(-12),
      activeTabId: tab.id,
    }))
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
        }
      }
      const activeTabId = previous.activeTabId === tabId
        ? (tabs[index] || tabs[index - 1] || tabs[0]).id
        : previous.activeTabId
      return { ...previous, tabs, activeTabId }
    })
  }

  const sendMessage = (event: FormEvent) => {
    event.preventDefault()
    if (!activeConversation) return
    const content = (drafts[activeConversation.id] || '').trim()
    if (!content) return
    const now = Date.now()
    setWorkspace(previous => {
      const conversations = previous.conversations.map(conversation => {
        if (conversation.id !== activeConversation.id) return conversation
        const firstStudentMessage = !conversation.messages.some(message => message.role === 'user')
        return {
          ...conversation,
          title: firstStudentMessage ? content.slice(0, 22) : conversation.title,
          updatedAt: now,
          messages: [
            ...conversation.messages,
            { id: uid('message'), role: 'user' as const, content, createdAt: now },
            {
              id: uid('message'),
              role: 'system' as const,
              content: 'Tutor 尚未接入。这条输入只保存在当前浏览器中，没有被发送到模型。',
              createdAt: now + 1,
            },
          ],
        }
      })
      const current = conversations.find(item => item.id === activeConversation.id)!
      const tabs = previous.tabs.map(tab => tab.conversationId === current.id ? { ...tab, title: current.title } : tab)
      return { ...previous, conversations, tabs }
    })
    setDrafts(previous => ({ ...previous, [activeConversation.id]: '' }))
  }

  const updateSettings = (patch: Partial<SettingsState>) => {
    setSettingsSaved(false)
    setWorkspace(previous => ({ ...previous, settings: { ...previous.settings, ...patch } }))
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
              <button
                type="button"
                key={conversation.id}
                onClick={() => openTab(chatTab(conversation))}
                className={activeConversation?.id === conversation.id ? 'conversation-active' : ''}
              >
                <span className="conversation-glyph">□</span>
                <span><strong>{conversation.title}</strong><small>{conversation.messages.filter(message => message.role === 'user').length} 条输入</small></span>
              </button>
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
              <div key={tab.id} className={`tab ${tab.id === activeTab?.id ? 'tab-active' : ''}`}>
                <button type="button" className="tab-main" onClick={() => openTab(tab)}>
                  <WorkspaceIcon kind={tab.kind} />
                  <span>{tab.title}</span>
                </button>
                <button type="button" className="tab-close" onClick={() => closeTab(tab.id)} aria-label={`关闭${tab.title}`}>×</button>
              </div>
            ))}
          </nav>

          {activeTab?.kind === 'settings' ? (
            <section className="settings-page">
              <div className="settings-intro">
                <span className="eyebrow">SETTINGS</span>
                <h1>设置</h1>
                <p>先只保留模型连接。没有隐藏的学习逻辑，也不读取旧项目配置。</p>
              </div>
              <form className="settings-card" onSubmit={event => { event.preventDefault(); setSettingsSaved(true) }}>
                <div className="settings-card-heading"><span>01</span><div><h2>模型连接</h2><p>这里只保存地址和模型名称。</p></div></div>
                <label>
                  <span>Base URL</span>
                  <input value={workspace.settings.baseUrl} onChange={event => updateSettings({ baseUrl: event.target.value })} placeholder="https://api.example.com/v1" />
                </label>
                <label>
                  <span>模型名称</span>
                  <input value={workspace.settings.model} onChange={event => updateSettings({ model: event.target.value })} placeholder="例如 model-name" />
                </label>
                <label>
                  <span>API Key</span>
                  <input type="password" value={apiKey} onChange={event => { setApiKey(event.target.value); setSettingsSaved(false) }} placeholder="仅保留在当前页面内存" autoComplete="off" />
                  <small>不会写入 localStorage，刷新页面后自动清空。</small>
                </label>
                <div className="settings-actions">
                  <button type="submit">保存界面配置</button>
                  <span className={settingsSaved ? 'save-status save-status-visible' : 'save-status'}>✓ 已保存</span>
                </div>
              </form>
            </section>
          ) : activeConversation ? (
            <section className="chat-page">
              <header className="chat-heading">
                <div><span className="eyebrow">CONVERSATION</span><h1>{activeConversation.title}</h1></div>
                <span className="local-label">仅本地</span>
              </header>
              <MessageList messages={activeConversation.messages} />
              <form className="composer" onSubmit={sendMessage}>
                <textarea
                  value={drafts[activeConversation.id] || ''}
                  onChange={event => setDrafts(previous => ({ ...previous, [activeConversation.id]: event.target.value }))}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  placeholder="先写下你希望 Tutor 回应的问题…"
                  rows={3}
                />
                <div className="composer-footer"><span>Enter 发送 · Shift + Enter 换行</span><button type="submit" disabled={!(drafts[activeConversation.id] || '').trim()}>发送 ↑</button></div>
              </form>
            </section>
          ) : null}
        </main>
      </div>
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
            <div><small>{message.role === 'user' ? '你' : message.role === 'assistant' ? 'Tutor' : '系统'}</small><p>{message.content}</p></div>
          </article>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<App />)
