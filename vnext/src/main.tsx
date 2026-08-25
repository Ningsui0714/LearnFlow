import { FormEvent, lazy, Suspense, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
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
import VisualArtifact from './VisualArtifact'
import {
  TOOL_CHOICE_LABELS,
  type TutorToolChoice,
  type TutorToolRun,
} from './tooling'
import './styles.css'

type Message = {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  createdAt: number
  tutorMode?: TutorMode
  toolRuns?: TutorToolRun[]
}

type FollowUpSheet = {
  id: string
  title: string
  quote: string
  sourceMessageId: string
  parentSheetId: string
  messages: Message[]
  createdAt: number
}

type PendingSheetDelete = {
  conversationId: string
  sheetId: string
  title: string
  childCount: number
}

type PaperDeskView = {
  conversationId: string
  mode: 'overview' | 'tree'
}

type Conversation = {
  id: string
  title: string
  messages: Message[]
  updatedAt: number
  mode: TutorMode
  sheets: FollowUpSheet[]
  activeSheetId: string
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
    sheets: [],
    activeSheetId: 'main',
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
      sheets: Array.isArray(conversation.sheets) ? conversation.sheets : [],
      activeSheetId: conversation.activeSheetId === 'main'
        || (Array.isArray(conversation.sheets) && conversation.sheets.some(sheet => sheet.id === conversation.activeSheetId))
        ? conversation.activeSheetId || 'main'
        : 'main',
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

function surfaceKey(conversationId: string, sheetId: string) {
  return `${conversationId}:${sheetId}`
}

function activeSheet(conversation: Conversation) {
  return conversation.activeSheetId === 'main'
    ? undefined
    : conversation.sheets.find(sheet => sheet.id === conversation.activeSheetId)
}

function activeMessages(conversation: Conversation) {
  return activeSheet(conversation)?.messages || conversation.messages
}

function paperPreview(messages: Message[]) {
  const latest = [...messages].reverse().find(message => message.role !== 'system')
  return latest?.content
    .replace(/```[\s\S]*?```/g, ' 代码片段 ')
    .replace(/[#>*_`\[\]()~-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 150) || '还没有写入内容'
}

function inheritedContextMessages(conversation: Conversation) {
  if (conversation.activeSheetId === 'main') return conversation.messages
  const chain: FollowUpSheet[] = []
  const seen = new Set<string>()
  let current = activeSheet(conversation)
  while (current && !seen.has(current.id)) {
    chain.unshift(current)
    seen.add(current.id)
    current = current.parentSheetId === 'main'
      ? undefined
      : conversation.sheets.find(sheet => sheet.id === current?.parentSheetId)
  }
  return [...conversation.messages, ...chain.flatMap(sheet => sheet.messages)]
}

function WorkspaceIcon({ kind }: { kind: WorkspaceTab['kind'] }) {
  return <span aria-hidden="true" className="tab-icon">{kind === 'settings' ? '⚙' : '□'}</span>
}

function App() {
  const [workspace, setWorkspace] = useState<PersistedState>(restoreState)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [toolChoices, setToolChoices] = useState<Record<string, TutorToolChoice>>({})
  const [settingsSaved, setSettingsSaved] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const [pendingSheetDelete, setPendingSheetDelete] = useState<PendingSheetDelete | null>(null)
  const [paperDeskView, setPaperDeskView] = useState<PaperDeskView | null>(null)
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
    if (!pendingDelete && !pendingSheetDelete) return
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPendingDelete(null)
        setPendingSheetDelete(null)
      }
    }
    window.addEventListener('keydown', cancelOnEscape)
    return () => window.removeEventListener('keydown', cancelOnEscape)
  }, [pendingDelete, pendingSheetDelete])

  useEffect(() => {
    if (!paperDeskView) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPaperDeskView(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [paperDeskView])

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
      return Object.fromEntries(Object.entries(previous).filter(([key]) => !key.startsWith(`${conversationId}:`)))
    })
    setToolChoices(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => !key.startsWith(`${conversationId}:`))))
    setPendingTurns(previous => {
      const next = { ...previous }
      delete next[conversationId]
      return next
    })
    setPaperDeskView(current => current?.conversationId === conversationId ? null : current)
    setPendingDelete(null)
  }

  const requestSheetDelete = (conversation: Conversation, sheetId: string) => {
    if (sheetId === 'main' || pendingTurns[conversation.id]) return
    const sheet = conversation.sheets.find(item => item.id === sheetId)
    if (!sheet) return
    setPendingSheetDelete({
      conversationId: conversation.id,
      sheetId,
      title: sheet.title,
      childCount: conversation.sheets.filter(item => item.parentSheetId === sheetId).length,
    })
  }

  const deleteSheet = (conversationId: string, sheetId: string) => {
    if (sheetId === 'main') return
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => {
        if (conversation.id !== conversationId) return conversation
        const target = conversation.sheets.find(sheet => sheet.id === sheetId)
        if (!target) return conversation
        const parentSheetId = target.parentSheetId === 'main'
          || conversation.sheets.some(sheet => sheet.id === target.parentSheetId && sheet.id !== sheetId)
          ? target.parentSheetId
          : 'main'
        return {
          ...conversation,
          activeSheetId: conversation.activeSheetId === sheetId ? parentSheetId : conversation.activeSheetId,
          sheets: conversation.sheets
            .filter(sheet => sheet.id !== sheetId)
            .map(sheet => sheet.parentSheetId === sheetId ? { ...sheet, parentSheetId } : sheet),
          updatedAt: Date.now(),
        }
      }),
    }))
    const deletedSurface = surfaceKey(conversationId, sheetId)
    setDrafts(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => key !== deletedSurface)))
    setToolChoices(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => key !== deletedSurface)))
    setPendingSheetDelete(null)
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

  const setActiveSheet = (conversationId: string, sheetId: string) => {
    if (pendingTurns[conversationId]) return
    setPaperDeskView(current => current?.conversationId === conversationId ? null : current)
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => (
        conversation.id === conversationId
          && (sheetId === 'main' || conversation.sheets.some(sheet => sheet.id === sheetId))
          ? { ...conversation, activeSheetId: sheetId }
          : conversation
      )),
    }))
  }

  const createFollowUpSheet = (conversationId: string, sourceMessageId: string, quote: string) => {
    const cleaned = quote.replace(/\s+/g, ' ').trim().slice(0, 1200)
    if (cleaned.length < 2) return
    setPaperDeskView(null)
    const sheet: FollowUpSheet = {
      id: uid('sheet'),
      title: cleaned.slice(0, 28),
      quote: cleaned,
      sourceMessageId,
      parentSheetId: workspace.conversations.find(item => item.id === conversationId)?.activeSheetId || 'main',
      messages: [],
      createdAt: Date.now(),
    }
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => (
        conversation.id === conversationId
          ? { ...conversation, sheets: [...conversation.sheets, sheet], activeSheetId: sheet.id, updatedAt: Date.now() }
          : conversation
      )),
    }))
  }

  const finishTurn = (conversationId: string, sheetId: string, mode: TutorMode, message: Omit<Message, 'id' | 'createdAt'>) => {
    const finishedMessage = { ...message, id: uid('message'), createdAt: Date.now(), tutorMode: message.role === 'assistant' ? mode : undefined }
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => (
        conversation.id === conversationId
          ? {
              ...conversation,
              mode: 'free',
              updatedAt: Date.now(),
              messages: sheetId === 'main' ? [...conversation.messages, finishedMessage] : conversation.messages,
              sheets: sheetId === 'main' ? conversation.sheets : conversation.sheets.map(sheet => (
                sheet.id === sheetId ? { ...sheet, messages: [...sheet.messages, finishedMessage] } : sheet
              )),
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
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation) return
    const sheetId = conversation.activeSheetId
    const draftKey = surfaceKey(conversationId, sheetId)
    const content = (drafts[draftKey] || '').trim()
    if (!content || pendingTurns[conversationId]) return

    const mode = resolveTutorMode(conversation.mode, content)
    const now = Date.now()
    const contextMessages = [
      ...inheritedContextMessages(conversation)
        .filter((message): message is Message & { role: 'assistant' | 'user' } => message.role !== 'system')
        .map(message => ({ role: message.role, content: message.content })),
      { role: 'user' as const, content },
    ]

    setPendingTurns(previous => ({ ...previous, [conversationId]: mode }))
    setWorkspace(previous => {
      const conversations = previous.conversations.map(conversation => {
        if (conversation.id !== conversationId) return conversation
        const firstStudentMessage = !conversation.messages.some(message => message.role === 'user')
        const userMessage: Message = { id: uid('message'), role: 'user', content, createdAt: now, tutorMode: mode }
        return {
          ...conversation,
          title: sheetId === 'main' && firstStudentMessage ? content.slice(0, 22) : conversation.title,
          updatedAt: now,
          mode,
          messages: sheetId === 'main' ? [...conversation.messages, userMessage] : conversation.messages,
          sheets: sheetId === 'main' ? conversation.sheets : conversation.sheets.map(sheet => (
            sheet.id === sheetId ? { ...sheet, messages: [...sheet.messages, userMessage] } : sheet
          )),
        }
      })
      const current = conversations.find(item => item.id === conversationId)
      if (!current) return previous
      const tabs = previous.tabs.map(tab => tab.conversationId === current.id ? { ...tab, title: current.title } : tab)
      return { ...previous, conversations, tabs }
    })
    setDrafts(previous => ({ ...previous, [draftKey]: '' }))

    const configurationIssue = tutorConfigurationIssue(workspace.settings.baseUrl, workspace.settings.model)
    if (configurationIssue) {
      finishTurn(conversationId, sheetId, mode, {
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
        toolChoice: toolChoices[draftKey] || 'auto',
        selectionContext: activeSheet(conversation)?.quote,
      })
      finishTurn(conversationId, sheetId, mode, { role: 'assistant', content: reply.reply, toolRuns: reply.toolRuns })
      setToolChoices(previous => ({ ...previous, [draftKey]: 'auto' }))
    } catch (error) {
      finishTurn(conversationId, sheetId, mode, {
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
    const sheet = activeSheet(conversation)
    const sheetId = conversation.activeSheetId
    const draftKey = surfaceKey(conversation.id, sheetId)
    const pages = [
      { id: 'main', title: '主对话', quote: '', messages: conversation.messages, parentSheetId: '' },
      ...conversation.sheets.map((item, index) => ({
        id: item.id,
        title: `${index + 1}. ${item.title}`,
        quote: item.quote,
        messages: item.messages,
        parentSheetId: item.parentSheetId,
      })),
    ]
    const pageIndex = Math.max(0, pages.findIndex(page => page.id === sheetId))
    const backPages = pages.filter(page => page.id !== sheetId).slice(-6)
    const messages = activeMessages(conversation)
    const hasWorkbench = conversation.sheets.length > 0
    const paperMode = paperDeskView?.conversationId === conversation.id ? paperDeskView.mode : 'stack'
    const renderPaperTreeNode = (page: typeof pages[number], ancestors: string[] = []): ReactNode => {
      const childPages = pages.filter(candidate => (
        candidate.parentSheetId === page.id && !ancestors.includes(candidate.id)
      ))
      return (
        <li key={page.id}>
          <div className={`paper-tree-card-wrap${page.id === sheetId ? ' paper-tree-card-active' : ''}`}>
            <button type="button" className="paper-tree-card" onClick={() => setActiveSheet(conversation.id, page.id)}>
              <span>{page.id === 'main' ? 'ROOT' : 'FOLLOW-UP'}</span>
              <strong>{page.title}</strong>
              <p>{page.quote || paperPreview(page.messages)}</p>
              <small>{page.messages.length} 条内容{page.id === sheetId ? ' · 当前纸张' : ''}</small>
            </button>
            {page.id !== 'main' && (
              <button type="button" className="paper-tree-delete" onClick={() => requestSheetDelete(conversation, page.id)} disabled={Boolean(pendingMode)} aria-label={`删除纸张${page.title}`} title="删除这张纸">⌫</button>
            )}
          </div>
          {childPages.length > 0 && (
            <ul>{childPages.map(child => renderPaperTreeNode(child, [...ancestors, page.id]))}</ul>
          )}
        </li>
      )
    }
    return (
      <section className="chat-page">
        <header className="chat-heading">
          <h1>{conversation.title}</h1>
          <div className="chat-state-stack">
            <span className={`mode-badge mode-badge-${visibleMode}`}>{TUTOR_MODE_LABELS[visibleMode]}</span>
            <span className="local-label">{workspace.settings.model || '待配置模型'}</span>
          </div>
        </header>
        <div className={hasWorkbench ? 'paper-workbench' : 'chat-thread'}>
          {hasWorkbench && (
            <div className="paper-toolbar">
              <div>
                <span className="paper-toolbar-label">选中追问工作台</span>
                <strong>{pages[pageIndex]?.title}</strong>
              </div>
              <div className="paper-navigation">
                <button type="button" onClick={() => setActiveSheet(conversation.id, pages[Math.max(0, pageIndex - 1)].id)} disabled={pageIndex === 0 || Boolean(pendingMode)} aria-label="上一张纸">←</button>
                <select value={sheetId} onChange={event => setActiveSheet(conversation.id, event.target.value)} disabled={Boolean(pendingMode)} aria-label="选择追问纸张">
                  {pages.map(page => <option key={page.id} value={page.id}>{page.title}</option>)}
                </select>
                <button type="button" onClick={() => setActiveSheet(conversation.id, pages[Math.min(pages.length - 1, pageIndex + 1)].id)} disabled={pageIndex === pages.length - 1 || Boolean(pendingMode)} aria-label="下一张纸">→</button>
                {sheet && <button type="button" className="paper-delete" onClick={() => requestSheetDelete(conversation, sheet.id)} disabled={Boolean(pendingMode)} aria-label={`删除纸张${sheet.title}`} title="删除当前纸张">⌫</button>}
                <button
                  type="button"
                  className="paper-overview-toggle"
                  onClick={() => setPaperDeskView(current => {
                    if (current?.conversationId !== conversation.id) return { conversationId: conversation.id, mode: 'overview' }
                    if (current.mode === 'overview') return { conversationId: conversation.id, mode: 'tree' }
                    return null
                  })}
                  disabled={Boolean(pendingMode)}
                  aria-label={paperMode === 'stack' ? '平铺所有纸张' : paperMode === 'overview' ? '展开纸张关系树' : '退出纸张关系树'}
                  aria-pressed={paperMode !== 'stack'}
                  title={paperMode === 'stack' ? '平铺所有纸张' : paperMode === 'overview' ? '查看纸张树' : '回到纸堆'}
                >{paperMode === 'tree' ? '□' : paperMode === 'overview' ? '树' : '▦'}</button>
              </div>
            </div>
          )}
          <div
            className={hasWorkbench ? `paper-stage${paperMode !== 'stack' ? ' paper-stage-overview' : ''}` : 'conversation-surface'}
            onClick={hasWorkbench && paperMode === 'stack' && !pendingMode ? event => {
              if (event.target === event.currentTarget) setPaperDeskView({ conversationId: conversation.id, mode: 'overview' })
            } : undefined}
          >
            {hasWorkbench && paperMode === 'tree' ? (
              <div
                className="paper-tree"
                aria-label="纸张关系树"
                onClick={event => {
                  const target = event.target as Element
                  if (!target.closest('button')) setPaperDeskView(null)
                }}
              >
                <header>
                  <div><span>PAPER TREE</span><strong>追问关系</strong></div>
                  <p>从主对话沿选中原文向下展开 · 点击空白回到纸堆</p>
                </header>
                <ul className="paper-tree-root">{renderPaperTreeNode(pages[0])}</ul>
              </div>
            ) : hasWorkbench && paperMode === 'overview' ? (
              <div
                className="paper-overview"
                role="listbox"
                aria-label="全部追问纸张"
                onClick={event => {
                  const target = event.target as Element
                  if (!target.closest('button')) setPaperDeskView({ conversationId: conversation.id, mode: 'tree' })
                }}
              >
                <header>
                  <div><span>ALL SHEETS</span><strong>{pages.length} 张纸</strong></div>
                  <p>选择纸张，或再次点击空白展开关系树 · Esc 退出</p>
                </header>
                <div className="paper-overview-grid">
                  {pages.map((page, index) => (
                    <div className="paper-thumbnail-wrap" role="option" aria-selected={page.id === sheetId} key={page.id}>
                      <button
                        type="button"
                        className="paper-thumbnail"
                        onClick={() => setActiveSheet(conversation.id, page.id)}
                        aria-label={`打开${page.title}`}
                      >
                        <span className="paper-thumbnail-index">{String(index + 1).padStart(2, '0')}</span>
                        <strong>{page.title}</strong>
                        {page.quote && <blockquote>{page.quote}</blockquote>}
                        <p>{paperPreview(page.messages)}</p>
                        <small>{page.messages.length} 条内容{page.id === sheetId ? ' · 当前纸张' : ''}</small>
                      </button>
                      {page.id !== 'main' && (
                        <button
                          type="button"
                          className="paper-thumbnail-delete"
                          onClick={() => requestSheetDelete(conversation, page.id)}
                          disabled={Boolean(pendingMode)}
                          aria-label={`删除纸张${page.title}`}
                          title="删除这张纸"
                        >⌫</button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className={hasWorkbench ? 'paper-stack' : 'conversation-paper'}>
                {hasWorkbench && backPages.length > 0 && (
                  <div className="paper-edge-deck" aria-label="其他纸张；悬停展开">
                    {backPages.map((page, index) => (
                      <button
                        type="button"
                        key={page.id}
                        className="paper-edge"
                        style={{
                          '--paper-y': `${index * 3}px`,
                          '--paper-x': `${index * 4}px`,
                          '--paper-open-x': `${index * -44}px`,
                          '--paper-background': `hsl(135 15% ${98 - index * .7}%)`,
                        } as CSSProperties}
                        onClick={() => setActiveSheet(conversation.id, page.id)}
                        aria-label={`打开${page.title}`}
                        title={page.title}
                      ><span>{page.title}</span></button>
                    ))}
                    {pages.length - 1 > backPages.length && <span className="paper-edge-more">+{pages.length - 1 - backPages.length}</span>}
                  </div>
                )}
                <div className={hasWorkbench ? 'paper-sheet' : 'conversation-page-content'}>
                  {sheet && (
                    <blockquote className="selected-quote">
                      <span>本页从这段原文展开</span>
                      <p>{sheet.quote}</p>
                    </blockquote>
                  )}
                  <MessageList
                    messages={messages}
                    onQuoteFollowUp={(messageId, quote) => createFollowUpSheet(conversation.id, messageId, quote)}
                  />
                  {sheet && messages.length === 0 && (
                    <div className="empty-sheet-hint">这张纸已经继承原对话。直接在下方追问选中的句子。</div>
                  )}
                </div>
              </div>
            )}
            {hasWorkbench && paperMode === 'stack' && <span className="paper-desktop-hint">点击桌面空白，平铺全部纸张</span>}
          </div>
        </div>
        <div className="composer-dock">
          <form className="composer" onSubmit={event => sendMessage(conversation.id, event)}>
            {pendingMode && <div className="turn-progress" role="status"><i /> 正在判断工具并由{TUTOR_MODE_LABELS[pendingMode]}组织回复…</div>}
            <textarea
              value={drafts[draftKey] || ''}
              onChange={event => setDrafts(previous => ({ ...previous, [draftKey]: event.target.value }))}
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
                <label className="tool-choice">
                  <span>工具</span>
                  <select value={toolChoices[draftKey] || 'auto'} disabled={Boolean(pendingMode)} onChange={event => setToolChoices(previous => ({ ...previous, [draftKey]: event.target.value as TutorToolChoice }))}>
                    {(Object.keys(TOOL_CHOICE_LABELS) as TutorToolChoice[]).map(choice => <option key={choice} value={choice}>{TOOL_CHOICE_LABELS[choice]}</option>)}
                  </select>
                </label>
                <span>Shift + Enter 换行</span>
              </div>
              <button type="submit" disabled={Boolean(pendingMode) || !(drafts[draftKey] || '').trim()} aria-label={pendingMode ? 'Tutor 回复中' : '发送消息'}>{pendingMode ? '…' : '↑'}</button>
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
      {pendingSheetDelete && (
        <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setPendingSheetDelete(null) }}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-sheet-dialog-title">
            <span className="dialog-eyebrow">DELETE SHEET</span>
            <h2 id="delete-sheet-dialog-title">删除“{pendingSheetDelete.title}”？</h2>
            <p>
              只删除这张追问纸，主对话不会受到影响。
              {pendingSheetDelete.childCount > 0
                ? ` 它下面的 ${pendingSheetDelete.childCount} 张子纸会保留并移动到上一层。`
                : ''}
              此操作无法撤销。
            </p>
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={() => setPendingSheetDelete(null)}>取消</button>
              <button type="button" className="button-danger" onClick={() => deleteSheet(pendingSheetDelete.conversationId, pendingSheetDelete.sheetId)}>删除纸张</button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function ToolRunCard({ run }: { run: TutorToolRun }) {
  const icon = run.kind === 'search' ? '⌕' : run.kind === 'image' ? '▧' : '▶'
  const roleLabel: Record<NonNullable<TutorToolRun['sources']>[number]['role'], string> = {
    standard: '规范', reference: '参考', textbook: '教材', course: '课程',
    definition: '定义', research: '研究', example: '实例', discussion: '讨论',
  }
  return (
    <section className={`tool-run tool-run-${run.status}`} aria-label={`${run.title}${run.status === 'completed' ? '已完成' : '失败'}`}>
      <header>
        <span className="tool-run-icon">{icon}</span>
        <div><strong>{run.title}</strong><small>{run.status === 'completed' ? '调用完成' : '调用失败'} · {(run.durationMs / 1000).toFixed(1)}s</small></div>
        <i>{run.status === 'completed' ? '✓' : '!'}</i>
      </header>
      <p>{run.detail}</p>
      {run.sources && run.sources.length > 0 && (
        <div className="tool-sources">
          {run.sources.map(source => (
            <a key={source.url} href={source.url} target="_blank" rel="noreferrer">
              <span>{source.source} · {source.quality === 'official' ? '权威' : source.quality === 'academic' ? '论文' : source.quality === 'repository' ? '仓库' : '社区'} · {roleLabel[source.role]}</span>
              <strong>{source.title}</strong>
              {source.snippet && <small>{source.snippet}</small>}
              {source.reason && <em>{source.reason}</em>}
            </a>
          ))}
        </div>
      )}
      {run.artifact && <VisualArtifact artifact={run.artifact} />}
    </section>
  )
}

function MessageList({ messages, onQuoteFollowUp }: {
  messages: Message[]
  onQuoteFollowUp: (messageId: string, quote: string) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [selectedText, setSelectedText] = useState<{ messageId: string; quote: string; left: number; top: number } | null>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length])
  useEffect(() => { setSelectedText(null) }, [messages])
  useEffect(() => {
    const captureKeyboardSelection = () => {
      const selection = globalThis.getSelection()
      const quote = selection?.toString().replace(/\s+/g, ' ').trim() || ''
      if (!selection || selection.rangeCount === 0 || quote.length < 1 || quote.length > 1200) return
      const anchor = selection.anchorNode instanceof Element ? selection.anchorNode : selection.anchorNode?.parentElement
      const article = anchor?.closest<HTMLElement>('article[data-message-role="assistant"]')
      if (!article || !listRef.current?.contains(article)) return
      const rect = selection.getRangeAt(0).getBoundingClientRect()
      setSelectedText({
        messageId: article.dataset.messageId || '', quote,
        left: Math.min(globalThis.innerWidth - 126, Math.max(8, rect.left + rect.width / 2 - 58)),
        top: Math.max(8, rect.top - 42),
      })
    }
    document.addEventListener('selectionchange', captureKeyboardSelection)
    return () => document.removeEventListener('selectionchange', captureKeyboardSelection)
  }, [])
  const visibleMessages = useMemo(() => messages, [messages])

  const captureSelection = (messageId: string, container: HTMLElement) => {
    const selection = globalThis.getSelection()
    const quote = selection?.toString().replace(/\s+/g, ' ').trim() || ''
    if (!selection || selection.rangeCount === 0 || quote.length < 1 || quote.length > 1200) {
      setSelectedText(null)
      return
    }
    const range = selection.getRangeAt(0)
    if (!container.contains(range.commonAncestorContainer)) {
      setSelectedText(null)
      return
    }
    const rect = range.getBoundingClientRect()
    setSelectedText({
      messageId,
      quote,
      left: Math.min(globalThis.innerWidth - 126, Math.max(8, rect.left + rect.width / 2 - 58)),
      top: Math.max(8, rect.top - 42),
    })
  }

  return (
    <div className="messages" aria-live="polite" ref={listRef}>
      <div className="message-column">
        {visibleMessages.map(message => (
          <article key={message.id} data-message-id={message.id} data-message-role={message.role} className={`message message-${message.role}`}>
            {message.role !== 'user' && <span className="message-avatar">{message.role === 'assistant' ? '✦' : 'i'}</span>}
            <div className="message-content" onMouseUp={message.role === 'assistant' ? event => captureSelection(message.id, event.currentTarget) : undefined}>
              <div className="message-meta">
                {message.role === 'user' ? '你' : message.role === 'assistant' ? 'Tutor' : '系统'}
                {message.tutorMode && <em>{TUTOR_MODE_LABELS[message.tutorMode]}</em>}
                {message.role === 'assistant' && (
                  <button
                    type="button"
                    className="message-follow-up"
                    title="选中文字后追问；未选中时从本条回答开一张纸"
                    onMouseDown={event => event.preventDefault()}
                    onClick={event => {
                      const selection = globalThis.getSelection()
                      const selectedQuote = selection?.toString().replace(/\s+/g, ' ').trim() || ''
                      const article = event.currentTarget.closest('article')
                      const anchor = selection?.anchorNode
                      const quote = selectedQuote && anchor && article?.contains(anchor)
                        ? selectedQuote
                        : message.content.replace(/\s+/g, ' ').trim().slice(0, 600)
                      if (!quote) return
                      onQuoteFollowUp(message.id, quote)
                      selection?.removeAllRanges()
                      setSelectedText(null)
                    }}
                  >选中文字追问</button>
                )}
              </div>
              {message.toolRuns?.map(run => <ToolRunCard key={run.id} run={run} />)}
              <Suspense fallback={<div className="markdown-loading">正在排版…</div>}>
                <MarkdownContent content={message.content} />
              </Suspense>
            </div>
          </article>
        ))}
        <div ref={endRef} />
      </div>
      {selectedText && (
        <button
          type="button"
          className="selection-follow-up"
          style={{ left: selectedText.left, top: selectedText.top }}
          onMouseDown={event => event.preventDefault()}
          onClick={() => {
            onQuoteFollowUp(selectedText.messageId, selectedText.quote)
            globalThis.getSelection()?.removeAllRanges()
            setSelectedText(null)
          }}
        >在新纸上追问</button>
      )}
    </div>
  )
}

const rootElement = document.getElementById('root')!
const rootScope = globalThis as typeof globalThis & { __learnflowVNextRoot?: Root }
const root = rootScope.__learnflowVNextRoot || createRoot(rootElement)
rootScope.__learnflowVNextRoot = root
root.render(<App />)
