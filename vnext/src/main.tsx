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
import {
  activeLearningTaskProjection,
  advanceLearningSkillStep,
  appendLearningEvents,
  canAdvanceLearningSkillStep,
  createLearningTask,
  currentLearningSkillStep,
  isLearningSkillId,
  isSupportRequest,
  latestLearningTaskProjection,
  LEARNING_SKILLS,
  learningTaskTutorContext,
  loopLearningSkillStep,
  nextLearningSkillStep,
  projectLearningTask,
  switchLearningSkill,
  type LearningEvent,
  type LearningSkillId,
  type LearningSubstateId,
  type LearningTask,
  type LearningTaskProjection,
} from './learning'
import VisualArtifact from './VisualArtifact'
import {
  TOOL_CHOICE_LABELS,
  type TutorToolChoice,
  type TutorToolRun,
} from './tooling'
import {
  activeLearningPlanProjection,
  closeLearningPlan,
  createLearningPlan,
  decideValueClaimProposal,
  learningPlanTutorContext,
  planningKindLabel,
  projectLearningPlan,
  updateLearningPlan,
  type LearningPlan,
  type LearningPlanProjection,
  type PlanningEvent,
  type ValueProposalDecision,
} from './planning'
import {
  addPersonalPathNode,
  createInitialLearnerPathState,
  projectLearnerPath,
  removePersonalPathNode,
  sanitizeLearnerPathState,
  setLearnerPathStatus,
  type LearnerPathState,
  type LearnerPathStatus,
  type PersonalPathNodeProposal,
} from './learning-path-graph'
import {
  actOnFormalLearningTask,
  addFormalPersonalPathNode,
  bootstrapFormalRuntime,
  confirmFormalValueClaim,
  createFormalLearningTask,
  learnerPathStateFromFormal,
  loadFormalLearnerSnapshot,
  removeFormalPersonalPathNode,
  setFormalMemoryArchived,
  setFormalPathStatus,
  submitFormalClaimFeedback,
  syncFormalEvent,
  syncFormalEvents,
  type FormalLearnerSnapshot,
  type FormalRuntimeConnection,
} from './formal-runtime'
import './styles.css'

type Message = {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  createdAt: number
  tutorMode?: TutorMode
  toolRuns?: TutorToolRun[]
  learningActionLabel?: string
  learningSkillId?: LearningSkillId
  learningSubstateId?: LearningSubstateId
  learningSubstateLabel?: string
  learningTaskId?: string
  formalTaskId?: number
  learningGoal?: string
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
  learningTasks: LearningTask[]
  learningEvents: LearningEvent[]
  preferredSkillId?: LearningSkillId
  learningPlans: LearningPlan[]
  planningEvents: PlanningEvent[]
}

type WorkspaceTab = {
  id: string
  kind: 'chat' | 'settings' | 'learning-path' | 'profile' | 'tasks'
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
  learningPath: LearnerPathState
}

const STORAGE_KEY = 'learnflow.vnext.workspace.v1'
const SETTINGS_TAB: WorkspaceTab = { id: 'settings', kind: 'settings', title: '设置' }
const LEARNING_PATH_TAB: WorkspaceTab = { id: 'learning-path', kind: 'learning-path', title: '学习路径' }
const PROFILE_TAB: WorkspaceTab = { id: 'profile', kind: 'profile', title: '我的画像' }
const TASKS_TAB: WorkspaceTab = { id: 'tasks', kind: 'tasks', title: '学习任务' }
const MarkdownContent = lazy(() => import('./MarkdownContent'))
const LearningPathPage = lazy(() => import('./LearningPathPage'))
const LearnerProfilePage = lazy(() => import('./LearnerProfilePage'))
const LearningTasksPage = lazy(() => import('./LearningTasksPage'))

function uid(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function formalModeId(mode: TutorMode) {
  if (mode === 'simple_explain') return 'explain'
  if (mode === 'guided_learning') return 'learn'
  if (mode === 'learning_plan') return 'plan'
  return 'free'
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
    learningTasks: [],
    learningEvents: [],
    learningPlans: [],
    planningEvents: [],
    messages: [{
      id: uid('message'),
      role: 'assistant',
      content: '现在处于自由态。你可以直接讨论学习问题；明确的解释请求会进入简单讲解，“带我学 / 带我练”会开始原子学习任务，较大的学习、项目或发展方向会进入学习规划态。',
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
    learningPath: createInitialLearnerPathState(),
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
      learningTasks: Array.isArray(conversation.learningTasks) ? conversation.learningTasks : [],
      learningEvents: Array.isArray(conversation.learningEvents) ? conversation.learningEvents : [],
      learningPlans: Array.isArray(conversation.learningPlans) ? conversation.learningPlans : [],
      planningEvents: Array.isArray(conversation.planningEvents) ? conversation.planningEvents : [],
      preferredSkillId: isLearningSkillId(conversation.preferredSkillId) ? conversation.preferredSkillId : undefined,
      activeSheetId: conversation.activeSheetId === 'main'
        || (Array.isArray(conversation.sheets) && conversation.sheets.some(sheet => sheet.id === conversation.activeSheetId))
        ? conversation.activeSheetId || 'main'
        : 'main',
    }))
    const conversationIds = new Set(conversations.map(item => item.id))
    const tabs = Array.isArray(value.tabs)
      ? value.tabs.filter(tab => ['settings', 'learning-path', 'profile', 'tasks'].includes(tab?.kind) || (tab?.kind === 'chat' && tab?.conversationId && conversationIds.has(tab.conversationId)))
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
      learningPath: sanitizeLearnerPathState(value.learningPath),
    }
  } catch {
    return initialState()
  }
}

function pathForTab(tab: WorkspaceTab) {
  if (tab.kind === 'settings') return '/settings'
  if (tab.kind === 'learning-path') return '/learning-path'
  if (tab.kind === 'profile') return '/learner-profile'
  if (tab.kind === 'tasks') return '/tasks'
  return `/chat/${tab.conversationId}`
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
  const icon = kind === 'settings' ? '⚙' : kind === 'learning-path' ? '⌁' : kind === 'profile' ? '◉' : kind === 'tasks' ? '☷' : '□'
  return <span aria-hidden="true" className="tab-icon">{icon}</span>
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
  const [formalConnection, setFormalConnection] = useState<FormalRuntimeConnection>({ status: 'connecting', detail: '正在连接正式五核事件链' })
  const [formalSnapshot, setFormalSnapshot] = useState<FormalLearnerSnapshot>()
  const [formalBusyKey, setFormalBusyKey] = useState('')
  const [formalError, setFormalError] = useState('')

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
    let active = true
    bootstrapFormalRuntime().then(result => {
      if (!active) return
      setFormalConnection(result.connection)
      if (result.snapshot) {
        setFormalSnapshot(result.snapshot)
        setWorkspace(previous => ({
          ...previous,
          learningPath: learnerPathStateFromFormal(result.snapshot!.learning_path),
        }))
      }
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!activeTab) return
    window.history.replaceState({ tabId: activeTab.id }, '', pathForTab(activeTab))
    document.title = `${activeTab.title} · LearnFlow vNext`
  }, [activeTab])

  const refreshFormalSnapshot = async (includeTerminalTasks = false) => {
    setFormalError('')
    try {
      const snapshot = await loadFormalLearnerSnapshot(includeTerminalTasks)
      setFormalSnapshot(snapshot)
      setFormalConnection({ status: 'connected', detail: snapshot.authority, learner: snapshot.learner })
      setWorkspace(previous => ({ ...previous, learningPath: learnerPathStateFromFormal(snapshot.learning_path) }))
      return snapshot
    } catch (error) {
      const detail = error instanceof Error ? error.message : '正式五核刷新失败'
      setFormalError(detail)
      setFormalConnection(previous => ({ ...previous, status: 'offline', detail }))
      return undefined
    }
  }

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
        conversation.id === conversationId
          ? { ...conversation, mode, preferredSkillId: mode === 'guided_learning' ? conversation.preferredSkillId : undefined }
          : conversation
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
      conversations: previous.conversations.map(conversation => {
        if (conversation.id !== conversationId) return conversation
        const activeTask = activeLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
        return {
          ...conversation,
          mode: activeTask ? 'guided_learning' : mode === 'simple_explain' ? 'free' : mode,
          updatedAt: Date.now(),
          messages: sheetId === 'main' ? [...conversation.messages, finishedMessage] : conversation.messages,
          sheets: sheetId === 'main' ? conversation.sheets : conversation.sheets.map(sheet => (
            sheet.id === sheetId ? { ...sheet, messages: [...sheet.messages, finishedMessage] } : sheet
          )),
        }
      }),
    }))
    setPendingTurns(previous => {
      const next = { ...previous }
      delete next[conversationId]
      return next
    })
    if (message.role === 'assistant' && formalConnection.status === 'connected') {
      void syncFormalEvent({
        id: `learning-segment:${finishedMessage.id}`,
        type: 'learning_action_segment_completed',
        at: finishedMessage.createdAt,
        detail: `完成一段${TUTOR_MODE_LABELS[mode]}输出；只表示发生学习暴露，不表示掌握`,
        payload: {
          segment_id: finishedMessage.id,
          mode: formalModeId(mode),
          goal: message.learningGoal || '',
          outcome: 'tutor_output_delivered',
          content_exposure: mode === 'simple_explain' || mode === 'guided_learning',
          learning_task_id: message.formalTaskId || message.learningTaskId,
          skills: message.learningSkillId ? [message.learningSkillId] : [],
          conversation_id: conversationId,
          exit_message_id: finishedMessage.id,
        },
      }).catch(error => setFormalError(error instanceof Error ? error.message : '学习片段事件同步失败'))
    }
  }

  const runTutorTurn = async (
    conversationId: string,
    rawContent: string,
    options: { advanceStep?: boolean; repeatStep?: boolean; learningActionLabel?: string } = {},
  ) => {
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation) return
    const sheetId = conversation.activeSheetId
    const draftKey = surfaceKey(conversationId, sheetId)
    const content = rawContent.trim()
    if (!content || pendingTurns[conversationId]) return

    const now = Date.now()
    const priorLearningEventIds = new Set(conversation.learningEvents.map(item => item.id))
    const priorPlanningEventIds = new Set(conversation.planningEvents.map(item => item.id))
    let learningTasks = [...conversation.learningTasks]
    let learningEvents = [...conversation.learningEvents]
    let learningProjection = activeLearningTaskProjection(learningTasks, learningEvents)
    let learningPlans = [...conversation.learningPlans]
    let planningEvents = [...conversation.planningEvents]
    let planningProjection = activeLearningPlanProjection(learningPlans, planningEvents)
    let createdLocalTask: LearningTask | undefined
    const mode = resolveTutorMode(conversation.mode, content, Boolean(learningProjection))

    if (mode === 'guided_learning') {
      if (!learningProjection) {
        const created = createLearningTask(content, now, learningEvents, conversation.preferredSkillId)
        learningTasks = [...learningTasks, created.task]
        createdLocalTask = created.task
        learningEvents = created.events
        learningProjection = projectLearningTask(created.task, learningEvents)
      }
      if (options.advanceStep && learningProjection) {
        learningEvents = advanceLearningSkillStep(learningEvents, learningProjection, now + 8)
        learningProjection = projectLearningTask(learningProjection.task, learningEvents)
      }
      if (options.repeatStep && learningProjection) {
        learningEvents = loopLearningSkillStep(learningEvents, learningProjection, '学生选择再来一轮', now + 8)
        learningProjection = projectLearningTask(learningProjection.task, learningEvents)
      }
      if (learningProjection && !options.learningActionLabel) {
        const step = currentLearningSkillStep(learningProjection)
        const additions: Array<Omit<LearningEvent, 'id' | 'sequence' | 'taskId' | 'at'>> = [{
          type: 'vnext_learning_task_learner_replied',
          detail: `学生回应：${content.slice(0, 80)}`,
          skillId: learningProjection.skillId,
          stepId: step.id,
        }]
        if (isSupportRequest(content)) additions.push(
          {
            type: 'vnext_learning_support_requested',
            detail: '学生需要补充支架，本轮不自动推进',
            skillId: learningProjection.skillId,
            stepId: step.id,
          },
          {
            type: 'vnext_learning_skill_looped',
            detail: `补充支架并重做：${step.title}`,
            skillId: learningProjection.skillId,
            stepId: step.id,
          },
        )
        learningEvents = appendLearningEvents(learningEvents, learningProjection.task.id, additions, now + 16)
        learningProjection = projectLearningTask(learningProjection.task, learningEvents)
      }
    }

    if (mode === 'learning_plan') {
      if (!planningProjection) {
        const created = createLearningPlan(content, now, planningEvents)
        learningPlans = [...learningPlans, created.plan]
        planningEvents = created.events
        planningProjection = projectLearningPlan(created.plan, planningEvents)
      } else {
        planningEvents = updateLearningPlan(planningEvents, planningProjection, content, now + 8)
        planningProjection = projectLearningPlan(planningProjection.plan, planningEvents)
      }
    }

    if (formalConnection.status === 'connected') {
      try {
        if (createdLocalTask && learningProjection) {
          const queuedFormalTask = await createFormalLearningTask(createdLocalTask, learningProjection.skillId, conversationId)
          const formalTask = queuedFormalTask.available_actions.includes('start')
            ? await actOnFormalLearningTask(queuedFormalTask, 'start')
            : queuedFormalTask
          learningTasks = learningTasks.map(task => task.id === createdLocalTask?.id
            ? { ...task, formalTaskId: formalTask.id, formalTaskVersion: formalTask.version }
            : task)
          const linkedLocalTask = learningTasks.find(task => task.id === createdLocalTask?.id)
          if (linkedLocalTask) learningProjection = projectLearningTask(linkedLocalTask, learningEvents)
          setFormalSnapshot(previous => previous ? {
            ...previous,
            learning_tasks: [...previous.learning_tasks.filter(task => task.id !== formalTask.id), formalTask],
          } : previous)
        }
        const atomicEvents = [
          ...learningEvents.filter(item => !priorLearningEventIds.has(item.id)),
          ...planningEvents.filter(item => !priorPlanningEventIds.has(item.id)),
        ]
        await Promise.all([
          syncFormalEvent({
            id: `chat-mode:${conversationId}:${now}`,
            type: 'chat_mode_entered',
            at: now,
            detail: `对话进入${TUTOR_MODE_LABELS[mode]}`,
            payload: { mode: formalModeId(mode), previous_mode: formalModeId(conversation.mode), conversation_id: conversationId },
          }),
          syncFormalEvents(atomicEvents),
        ])
      } catch (error) {
        setFormalError(error instanceof Error ? error.message : '原子事件同步失败')
      }
    }

    const contextMessages = [
      ...inheritedContextMessages(conversation)
        .filter((message): message is Message & { role: 'assistant' | 'user' } => message.role !== 'system')
        .map(message => ({ role: message.role, content: message.content })),
      { role: 'user' as const, content },
    ]
    const turnStep = learningProjection ? currentLearningSkillStep(learningProjection) : undefined

    setPendingTurns(previous => ({ ...previous, [conversationId]: mode }))
    setWorkspace(previous => {
      const conversations = previous.conversations.map(conversation => {
        if (conversation.id !== conversationId) return conversation
        const firstStudentMessage = !conversation.messages.some(message => message.role === 'user')
        const userMessage: Message = {
          id: uid('message'), role: 'user', content, createdAt: now, tutorMode: mode,
          learningActionLabel: options.learningActionLabel,
          learningSkillId: learningProjection?.skillId,
          learningSubstateId: turnStep?.substateId,
          learningSubstateLabel: turnStep?.substateLabel,
        }
        return {
          ...conversation,
          title: sheetId === 'main' && firstStudentMessage ? content.slice(0, 22) : conversation.title,
          updatedAt: now,
          mode,
          learningTasks,
          learningEvents,
          learningPlans,
          planningEvents,
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
        learningSkillId: learningProjection?.skillId,
        learningSubstateId: turnStep?.substateId,
        learningSubstateLabel: turnStep?.substateLabel,
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
        learningTaskContext: learningProjection ? learningTaskTutorContext(learningProjection) : undefined,
        learningPlanContext: planningProjection ? learningPlanTutorContext(planningProjection) : undefined,
        learnerPathState: workspace.learningPath,
      })
      finishTurn(conversationId, sheetId, mode, {
        role: 'assistant', content: reply.reply, toolRuns: reply.toolRuns,
        learningSkillId: learningProjection?.skillId,
        learningSubstateId: turnStep?.substateId,
        learningSubstateLabel: turnStep?.substateLabel,
        learningTaskId: learningProjection?.task.id,
        formalTaskId: learningProjection?.task.formalTaskId,
        learningGoal: learningProjection?.task.objective || planningProjection?.plan.objective || content,
      })
      setToolChoices(previous => ({ ...previous, [draftKey]: 'auto' }))
    } catch (error) {
      finishTurn(conversationId, sheetId, mode, {
        role: 'system',
        content: `“${TUTOR_MODE_LABELS[mode]}”请求失败：${error instanceof Error ? error.message : '未知错误'}`,
        learningSkillId: learningProjection?.skillId,
        learningSubstateId: turnStep?.substateId,
        learningSubstateLabel: turnStep?.substateLabel,
      })
    }
  }

  const sendMessage = async (conversationId: string, event: FormEvent) => {
    event.preventDefault()
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation) return
    const draftKey = surfaceKey(conversationId, conversation.activeSheetId)
    await runTutorTurn(conversationId, drafts[draftKey] || '')
  }

  const updateLearningTask = async (
    conversationId: string,
    action: 'pause' | 'resume' | 'complete' | 'skill',
    skillId?: LearningSkillId,
  ) => {
    if (pendingTurns[conversationId]) return
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation) return
    const projection = latestLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
    if (!projection || projection.status === 'completed') return
    let learningEvents = conversation.learningEvents
    if (action === 'skill') {
      learningEvents = switchLearningSkill(learningEvents, projection, skillId || projection.skillId, Date.now())
    } else {
      const event = action === 'pause'
        ? { type: 'vnext_learning_task_paused' as const, detail: '暂停学习任务' }
        : action === 'resume'
          ? { type: 'vnext_learning_task_resumed' as const, detail: '恢复学习任务' }
          : { type: 'vnext_learning_task_completed' as const, detail: '结束本段 Skill 流程；不代表掌握，正式任务仍需可检查证据' }
      learningEvents = appendLearningEvents(learningEvents, projection.task.id, [event], Date.now())
    }
    const previousIds = new Set(conversation.learningEvents.map(item => item.id))
    const newEvents = learningEvents.filter(item => !previousIds.has(item.id))
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(item => item.id === conversationId ? {
        ...item,
        learningEvents,
        mode: action === 'resume' || action === 'skill' ? 'guided_learning' : 'free',
        preferredSkillId: action === 'complete' ? undefined : item.preferredSkillId,
        updatedAt: Date.now(),
      } : item),
    }))
    if (formalConnection.status === 'connected') {
      try {
        await syncFormalEvents(newEvents)
        const formalTask = formalSnapshot?.learning_tasks.find(item => item.id === projection.task.formalTaskId)
        if (formalTask && action !== 'skill' && action !== 'complete') {
          const updated = await actOnFormalLearningTask(formalTask, action)
          setFormalSnapshot(previous => previous ? {
            ...previous,
            learning_tasks: previous.learning_tasks.map(item => item.id === updated.id ? updated : item),
          } : previous)
        }
      } catch (error) {
        setFormalError(error instanceof Error ? error.message : '学习任务状态同步失败')
      }
    }
  }

  const selectLearningSkill = (conversationId: string, value: string) => {
    if (pendingTurns[conversationId]) return
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation) return
    const activeProjection = activeLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
    const latestProjection = latestLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
    if (latestProjection?.status === 'paused') return
    if (activeProjection && isLearningSkillId(value)) {
      updateLearningTask(conversationId, 'skill', value)
      return
    }
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(item => item.id === conversationId
        ? {
            ...item,
            mode: 'guided_learning',
            preferredSkillId: isLearningSkillId(value) ? value : undefined,
            updatedAt: Date.now(),
          }
        : item),
    }))
  }

  const updateValueProposal = async (
    conversationId: string,
    projection: LearningPlanProjection,
    decision: Exclude<ValueProposalDecision, 'proposed'>,
    draftKey?: string,
  ) => {
    if (pendingTurns[conversationId]) return
    const conversation = workspace.conversations.find(item => item.id === conversationId)
    if (!conversation || !projection.valueProposal) return
    let formalWriteCompleted = false
    if (decision === 'accepted' && formalConnection.status === 'connected') {
      setFormalBusyKey(`value:${projection.valueProposal.id}`)
      try {
        await confirmFormalValueClaim(projection.valueProposal, `value-confirm:${projection.valueProposal.id}`)
        formalWriteCompleted = true
        await refreshFormalSnapshot()
      } catch (error) {
        setFormalError(error instanceof Error ? error.message : '价值核确认写入失败')
      } finally {
        setFormalBusyKey('')
      }
    }
    const planningEvents = decideValueClaimProposal(
      conversation.planningEvents, projection, decision, Date.now(), formalWriteCompleted,
    )
    const newEvents = planningEvents.filter(item => !conversation.planningEvents.some(previous => previous.id === item.id))
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => conversation.id === conversationId
        ? {
            ...conversation,
            planningEvents,
            updatedAt: Date.now(),
          }
        : conversation),
    }))
    if (decision === 'revision_requested' && draftKey) {
      setDrafts(previous => ({ ...previous, [draftKey]: '我希望把价值核建议改成：' }))
    }
    if (decision !== 'accepted' && formalConnection.status === 'connected') {
      void syncFormalEvents(newEvents).catch(error => setFormalError(error instanceof Error ? error.message : '价值核决定事件同步失败'))
    }
  }

  const finishLearningPlan = (conversationId: string, projection: LearningPlanProjection) => {
    if (pendingTurns[conversationId]) return
    const current = workspace.conversations.find(item => item.id === conversationId)
    if (!current) return
    const planningEvents = closeLearningPlan(current.planningEvents, projection)
    const additions = planningEvents.filter(item => !current.planningEvents.some(previous => previous.id === item.id))
    setWorkspace(previous => ({
      ...previous,
      conversations: previous.conversations.map(conversation => conversation.id === conversationId
        ? {
            ...conversation,
            mode: 'free',
            planningEvents,
            updatedAt: Date.now(),
          }
        : conversation),
    }))
    if (formalConnection.status === 'connected') {
      void syncFormalEvents(additions).catch(error => setFormalError(error instanceof Error ? error.message : '规划结束事件同步失败'))
    }
  }

  const advanceTaskAndContinue = async (conversation: Conversation, projection: LearningTaskProjection) => {
    const next = nextLearningSkillStep(projection)
    if (!next || !canAdvanceLearningSkillStep(projection) || pendingTurns[conversation.id]) return
    await runTutorTurn(conversation.id, `继续当前学习任务，进入“${next.title}”。`, {
      advanceStep: true,
      learningActionLabel: `进入${next.title}`,
    })
  }

  const repeatTaskStep = async (conversation: Conversation, projection: LearningTaskProjection) => {
    if (pendingTurns[conversation.id]) return
    const step = currentLearningSkillStep(projection)
    await runTutorTurn(conversation.id, `换一种支架，再完成一轮“${step.title}”。`, {
      repeatStep: true,
      learningActionLabel: `再来一轮 · ${step.shortTitle}`,
    })
  }

  const updateSettings = (patch: Partial<SettingsState>) => {
    setSettingsSaved(false)
    setWorkspace(previous => ({ ...previous, settings: { ...previous.settings, ...patch } }))
  }

  const updatePathStatus = async (nodeId: string, status: LearnerPathStatus) => {
    const nodeTitle = projectLearnerPath(workspace.learningPath).nodes.find(node => node.id === nodeId)?.title || nodeId
    if (formalConnection.status !== 'connected') {
      setWorkspace(previous => ({ ...previous, learningPath: setLearnerPathStatus(previous.learningPath, nodeId, status) }))
      setFormalError('正式事件链离线：该标记目前只保存在本机，恢复连接后请重新确认。')
      return
    }
    setFormalBusyKey(`path:${nodeId}`)
    try {
      const result = await setFormalPathStatus(nodeId, nodeTitle, status, `path-status:${nodeId}:${status}:${Date.now()}`)
      setWorkspace(previous => ({ ...previous, learningPath: learnerPathStateFromFormal(result.learning_path) }))
      await refreshFormalSnapshot()
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : '学习路径状态写入失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const acceptPersonalPathNode = async (proposal: PersonalPathNodeProposal) => {
    if (formalConnection.status !== 'connected') {
      setWorkspace(previous => ({ ...previous, learningPath: addPersonalPathNode(previous.learningPath, proposal) }))
      setFormalError('正式事件链离线：个人节点目前只保存在本机。')
      return
    }
    setFormalBusyKey(`path:${proposal.id}`)
    try {
      const result = await addFormalPersonalPathNode(proposal, `personal-path-add:${proposal.id}`)
      setWorkspace(previous => ({ ...previous, learningPath: learnerPathStateFromFormal(result.learning_path) }))
      await refreshFormalSnapshot()
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : '个人路径节点写入失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const deletePersonalPathNode = async (nodeId: string) => {
    const nodeTitle = projectLearnerPath(workspace.learningPath).nodes.find(node => node.id === nodeId)?.title || nodeId
    if (formalConnection.status !== 'connected') {
      setWorkspace(previous => ({ ...previous, learningPath: removePersonalPathNode(previous.learningPath, nodeId) }))
      setFormalError('正式事件链离线：移除动作目前只保存在本机。')
      return
    }
    setFormalBusyKey(`path:${nodeId}`)
    try {
      const result = await removeFormalPersonalPathNode(nodeId, nodeTitle, `personal-path-remove:${nodeId}:${Date.now()}`)
      setWorkspace(previous => ({ ...previous, learningPath: learnerPathStateFromFormal(result.learning_path) }))
      await refreshFormalSnapshot()
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : '个人路径节点移除失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const updateFormalMemoryArchive = async (memoryId: string, archived: boolean) => {
    setFormalBusyKey(`memory:${memoryId}`)
    setFormalError('')
    try {
      await setFormalMemoryArchived(memoryId, archived)
      await refreshFormalSnapshot(true)
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : '记忆归档失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const updateFormalClaim = async (claimId: number, action: 'confirm' | 'correct' | 'retract', correction = '') => {
    setFormalBusyKey(`claim:${claimId}`)
    setFormalError('')
    try {
      await submitFormalClaimFeedback(claimId, action, correction, action === 'retract' ? '学习者明确撤回该 Claim' : '')
      await refreshFormalSnapshot(true)
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : 'Claim 更新失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const updateFormalTask = async (task: NonNullable<FormalLearnerSnapshot['learning_tasks'][number]>, action: 'start' | 'pause' | 'resume' | 'cancel' | 'reopen') => {
    setFormalBusyKey(`task:${task.id}`)
    setFormalError('')
    try {
      const updated = await actOnFormalLearningTask(task, action)
      setFormalSnapshot(previous => previous ? {
        ...previous,
        learning_tasks: previous.learning_tasks.map(item => item.id === updated.id ? updated : item),
      } : previous)
    } catch (error) {
      setFormalError(error instanceof Error ? error.message : '正式学习任务更新失败')
    } finally {
      setFormalBusyKey('')
    }
  }

  const renderTab = (tab: WorkspaceTab | undefined) => {
    if (!tab) return null
    if (tab.kind === 'learning-path') {
      return (
        <Suspense fallback={<div className="page-loading">正在载入学习路径…</div>}>
          <LearningPathPage
            state={workspace.learningPath}
            onStatusChange={updatePathStatus}
            onAddPersonalNode={acceptPersonalPathNode}
            onRemovePersonalNode={deletePersonalPathNode}
          />
        </Suspense>
      )
    }
    if (tab.kind === 'profile') {
      return (
        <Suspense fallback={<div className="page-loading">正在载入正式五核画像…</div>}>
          <LearnerProfilePage
            connection={formalConnection}
            snapshot={formalSnapshot}
            busyKey={formalBusyKey}
            error={formalError}
            onRefresh={() => { void refreshFormalSnapshot(true) }}
            onOpenPath={() => openTab(LEARNING_PATH_TAB)}
            onMemoryArchive={(memoryId, archived) => { void updateFormalMemoryArchive(memoryId, archived) }}
            onClaimAction={(claimId, action, correction) => { void updateFormalClaim(claimId, action, correction) }}
          />
        </Suspense>
      )
    }
    if (tab.kind === 'tasks') {
      return (
        <Suspense fallback={<div className="page-loading">正在载入学习任务队列…</div>}>
          <LearningTasksPage
            connection={formalConnection}
            tasks={formalSnapshot?.learning_tasks || []}
            busyTaskId={formalBusyKey.startsWith('task:') ? Number(formalBusyKey.slice(5)) : undefined}
            error={formalError}
            onRefresh={() => { void refreshFormalSnapshot(true) }}
            onAction={(task, action) => { void updateFormalTask(task, action) }}
          />
        </Suspense>
      )
    }
    if (tab.kind === 'settings') {
      return (
        <section className="settings-page">
          <div className="settings-intro">
            <span className="eyebrow">SETTINGS</span>
            <h1>设置</h1>
            <p>四种 Tutor 状态共用模型连接；五核、学习路径与任务队列使用下方正式后端事件链。</p>
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
          <section className="settings-card profile-settings-card" aria-labelledby="formal-profile-title">
            <div className="settings-card-heading">
              <span>02</span>
              <div>
                <h2 id="formal-profile-title">正式学习者状态</h2>
                <p>{formalConnection.status === 'connected' ? `已连接 ${formalConnection.learner?.display_name || '当前学习者'}；所有写入经过 EvidenceEvent 与 reducer。` : formalConnection.detail}</p>
              </div>
              <i>{formalConnection.status === 'connected' ? '已连接' : '未连接'}</i>
            </div>
            <div className="settings-actions"><button type="button" onClick={() => { void refreshFormalSnapshot(true) }}>重新连接</button><button type="button" className="button-secondary" onClick={() => openTab(PROFILE_TAB)}>打开五核画像</button><button type="button" className="button-secondary" onClick={() => openTab(TASKS_TAB)}>打开任务队列</button></div>
          </section>
        </section>
      )
    }

    const conversation = workspace.conversations.find(item => item.id === tab.conversationId)
    if (!conversation) return null
    const pendingMode = pendingTurns[conversation.id]
    const taskProjection = latestLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
    const activeTaskProjection = activeLearningTaskProjection(conversation.learningTasks, conversation.learningEvents)
    const planProjection = activeLearningPlanProjection(conversation.learningPlans, conversation.planningEvents)
    const taskSkill = taskProjection ? LEARNING_SKILLS[taskProjection.skillId] : undefined
    const taskStep = taskProjection ? currentLearningSkillStep(taskProjection) : undefined
    const activeTaskStep = activeTaskProjection ? currentLearningSkillStep(activeTaskProjection) : undefined
    const taskCanAdvance = taskProjection ? canAdvanceLearningSkillStep(taskProjection) : false
    const visibleMode = pendingMode || (activeTaskProjection ? 'guided_learning' : conversation.mode)
    const visibleSkillId = activeTaskProjection?.skillId
      || (conversation.mode === 'guided_learning' ? conversation.preferredSkillId : undefined)
    const visibleSkill = visibleSkillId ? LEARNING_SKILLS[visibleSkillId] : undefined
    const visibleSubstateLabel = activeTaskStep?.substateLabel
      || (visibleMode === 'guided_learning' ? '准备态' : '')
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
            <span className={`mode-badge mode-badge-${visibleMode}`}>
              {TUTOR_MODE_LABELS[visibleMode]}{visibleSubstateLabel ? ` · ${visibleSubstateLabel}` : ''}
            </span>
            {visibleSkill && <span className="skill-badge">{visibleSkill.name}</span>}
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
                    onAcceptPathProposal={acceptPersonalPathNode}
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
            {planProjection && conversation.mode === 'learning_plan' && (
              <>
                <section className="planning-anchor" aria-label="当前学习规划">
                  <span className="planning-mark">◇</span>
                  <div className="planning-anchor-main">
                    <strong>{planProjection.plan.objective}</strong>
                    <span>
                      学习规划态 · {planningKindLabel(planProjection.plan.kind)} · 已确认 {planProjection.requirements.length - planProjection.missingRequirements.length}/{planProjection.requirements.length}
                      {planProjection.missingRequirements.length ? ` · 待确认 ${planProjection.missingRequirements.slice(0, 2).map(item => item.label).join('、')}` : ' · 草案信息已齐'}
                    </span>
                  </div>
                  {planProjection.plan.kind === 'project_seed' && <span className="project-stub-badge">项目尚未接入</span>}
                  <details className="planning-menu">
                    <summary role="button" aria-label="学习规划详情">•••</summary>
                    <div className="planning-popover">
                      <header><strong>{planningKindLabel(planProjection.plan.kind)}</strong><span>信息来自当前对话，可继续补充和修订。</span></header>
                      <div className="planning-requirements">
                        {planProjection.requirements.map(requirement => (
                          <span key={requirement.id} className={planProjection.signals[requirement.id] ? 'confirmed' : ''}>
                            <i>{planProjection.signals[requirement.id] ? '✓' : '·'}</i>{requirement.label}
                          </span>
                        ))}
                      </div>
                      <p>{planProjection.plan.kind === 'project_seed'
                        ? '信息足够后只形成项目启动草案；当前版本不会创建项目、关卡或文件夹。'
                        : '先用项目、阅读或实践实验收集方向证据；不替你决定职业。'}</p>
                      <button type="button" onClick={() => finishLearningPlan(conversation.id, planProjection)} disabled={Boolean(pendingMode)}>结束规划</button>
                    </div>
                  </details>
                </section>
                {planProjection.valueProposal && (
                  <section className={`value-proposal-card value-proposal-${planProjection.valueProposal.decision}`} aria-label="价值核修改建议">
                    <header><span>VALUE CLAIM PROPOSAL</span><strong>价值核修改建议</strong></header>
                    <div className="value-proposal-change">
                      <div><span>当前内容</span><p>{planProjection.valueProposal.currentClaim}</p></div>
                      <i>→</i>
                      <div><span>建议内容</span><p>{planProjection.valueProposal.proposedClaim}</p></div>
                    </div>
                    <blockquote>依据：你说“{planProjection.valueProposal.evidenceQuote}”</blockquote>
                    <p>{planProjection.valueProposal.rationale} 接受时会先显示原文与建议，再通过正式事件入口写入价值核；你仍可在画像页纠正或撤回。</p>
                    {planProjection.valueProposal.decision === 'proposed' ? (
                      <div className="value-proposal-actions">
                        <button type="button" className="value-accept" onClick={() => { void updateValueProposal(conversation.id, planProjection, 'accepted') }} disabled={Boolean(pendingMode) || formalBusyKey.startsWith('value:')}>确认并写入价值核</button>
                        <button type="button" onClick={() => updateValueProposal(conversation.id, planProjection, 'revision_requested', draftKey)} disabled={Boolean(pendingMode)}>我要修改</button>
                        <button type="button" onClick={() => updateValueProposal(conversation.id, planProjection, 'rejected')} disabled={Boolean(pendingMode)}>不写入</button>
                      </div>
                    ) : (
                      <strong className="value-proposal-decision">
                        {planProjection.valueProposal.decision === 'accepted' && (planProjection.valueProposal.formalWriteCompleted ? '✓ 你已确认，正式价值核已记录' : '已确认但正式后端离线，当前只保留待同步状态')}
                        {planProjection.valueProposal.decision === 'rejected' && '已拒绝；不会写入'}
                        {planProjection.valueProposal.decision === 'revision_requested' && '等待你在输入框中写出修改版本'}
                      </strong>
                    )}
                  </section>
                )}
              </>
            )}
            {taskProjection && taskProjection.status !== 'completed' && (
              <section className={`learning-task-anchor learning-task-anchor-${taskProjection.status}`} aria-label="当前学习任务">
                <span className="learning-task-mark">◎</span>
                <div className="learning-task-anchor-main">
                  <strong>{taskProjection.task.objective}</strong>
                  <span>
                    {taskProjection.status === 'paused' ? '已暂停 · ' : ''}带领学习态 · {taskStep?.substateLabel} · {taskSkill?.name} · {taskStep?.title}
                    {taskProjection.loopCount > 0 ? ` · 本步第 ${taskProjection.loopCount + 1} 轮` : ''}
                  </span>
                </div>
                <div className="learning-skill-dots" aria-label={`${taskSkill?.name}：第 ${taskProjection.stepIndex + 1}/${taskSkill?.steps.length} 步`}>
                  {taskSkill?.steps.map((step, index) => (
                    <i key={step.id} className={index < taskProjection.stepIndex ? 'done' : index === taskProjection.stepIndex ? 'current' : ''} />
                  ))}
                </div>
                {taskProjection.status === 'paused' ? (
                  <button type="button" className="learning-primary-action" onClick={() => updateLearningTask(conversation.id, 'resume')}>继续</button>
                ) : nextLearningSkillStep(taskProjection) ? (
                  <button
                    type="button"
                    className="learning-primary-action"
                    title={taskCanAdvance ? taskStep?.nextAction : '先在对话中完成当前动作'}
                    onClick={() => advanceTaskAndContinue(conversation, taskProjection)}
                    disabled={Boolean(pendingMode) || !taskCanAdvance}
                  >
                    {taskCanAdvance ? taskStep?.nextAction : '等待回答'}
                  </button>
                ) : (
                  <button type="button" className="learning-primary-action" onClick={() => updateLearningTask(conversation.id, 'complete')} disabled={Boolean(pendingMode) || !taskCanAdvance}>完成本轮</button>
                )}
                <details className="learning-task-menu">
                  <summary role="button" aria-label="学习任务选项">•••</summary>
                  <div className="learning-task-popover">
                    <header><strong>带领学习态 · {taskStep?.substateLabel} · {taskSkill?.name}</strong><span>{taskSkill?.description}</span></header>
                    <ol>
                      {taskSkill?.steps.map((step, index) => (
                        <li key={step.id} className={index === taskProjection.stepIndex ? 'current' : index < taskProjection.stepIndex ? 'done' : ''}>
                          <i>{index + 1}</i><span>{step.title}</span>
                        </li>
                      ))}
                    </ol>
                    <label>
                      <span>切换学习方法</span>
                      <select
                        value={taskProjection.skillId}
                        disabled={Boolean(pendingMode) || taskProjection.status === 'paused'}
                        onChange={event => {
                          updateLearningTask(conversation.id, 'skill', event.target.value as LearningSkillId)
                          event.currentTarget.closest('details')?.removeAttribute('open')
                        }}
                      >
                        {(Object.keys(LEARNING_SKILLS) as LearningSkillId[]).map(skillId => (
                          <option key={skillId} value={skillId}>{LEARNING_SKILLS[skillId].name}</option>
                        ))}
                      </select>
                    </label>
                    <div className="learning-task-menu-actions">
                      {taskProjection.status === 'active' && taskStep?.canLoop && (
                        <button type="button" onClick={event => {
                          event.currentTarget.closest('details')?.removeAttribute('open')
                          repeatTaskStep(conversation, taskProjection)
                        }} disabled={Boolean(pendingMode)}>再来一轮</button>
                      )}
                      {taskProjection.status === 'active' && <button type="button" onClick={event => {
                        event.currentTarget.closest('details')?.removeAttribute('open')
                        updateLearningTask(conversation.id, 'pause')
                      }} disabled={Boolean(pendingMode)}>暂停</button>}
                      <button type="button" onClick={event => {
                        event.currentTarget.closest('details')?.removeAttribute('open')
                        updateLearningTask(conversation.id, 'complete')
                      }} disabled={Boolean(pendingMode)}>结束任务</button>
                    </div>
                    <details className="learning-event-queue">
                      <summary>运行记录 {taskProjection.eventCount}</summary>
                      <div>
                        {conversation.learningEvents
                          .filter(item => item.taskId === taskProjection.task.id)
                          .slice(-6)
                          .reverse()
                          .map(item => <span key={item.id}><i>{item.sequence}</i>{item.detail}</span>)}
                      </div>
                    </details>
                  </div>
                </details>
              </section>
            )}
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
                  <button type="button" title="自由讨论；解释请求仍可自动进入简单讲解" aria-pressed={!activeTaskProjection && conversation.mode === 'free'} disabled={Boolean(pendingMode) || Boolean(activeTaskProjection)} onClick={() => setConversationMode(conversation.id, 'free')}>自由态</button>
                  <button type="button" title="下一轮使用简单讲解，完成后回到自由态" aria-pressed={!activeTaskProjection && conversation.mode === 'simple_explain'} disabled={Boolean(pendingMode) || Boolean(activeTaskProjection)} onClick={() => setConversationMode(conversation.id, 'simple_explain')}>简单讲解</button>
                  <button
                    type="button"
                    title="围绕一个原子目标在当前对话中持续学习"
                    aria-pressed={Boolean(activeTaskProjection) || conversation.mode === 'guided_learning'}
                    disabled={Boolean(pendingMode)}
                    onClick={() => taskProjection?.status === 'paused'
                      ? updateLearningTask(conversation.id, 'resume')
                      : setConversationMode(conversation.id, 'guided_learning')}
                  >带领学习</button>
                  <button
                    type="button"
                    title="规划较大的学习、真实产物项目或未来发展方向"
                    aria-pressed={!activeTaskProjection && conversation.mode === 'learning_plan'}
                    disabled={Boolean(pendingMode) || Boolean(activeTaskProjection)}
                    onClick={() => setConversationMode(conversation.id, 'learning_plan')}
                  >学习规划</button>
                </div>
                <label className="skill-choice" title="学习方法只在带领学习态运行；选择后下一条消息会建立任务">
                  <span>方法</span>
                  <select
                    aria-label="学习方法"
                    value={activeTaskProjection?.skillId || (conversation.mode === 'guided_learning' ? conversation.preferredSkillId || 'auto' : 'auto')}
                    disabled={Boolean(pendingMode) || taskProjection?.status === 'paused'}
                    onChange={event => selectLearningSkill(conversation.id, event.target.value)}
                  >
                    <option value="auto" disabled={Boolean(activeTaskProjection)}>自动选择</option>
                    {(Object.keys(LEARNING_SKILLS) as LearningSkillId[]).map(skillId => (
                      <option key={skillId} value={skillId}>{LEARNING_SKILLS[skillId].name}</option>
                    ))}
                  </select>
                </label>
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
        <span className={`prototype-badge formal-status-badge formal-status-${formalConnection.status}`}><i /> {formalConnection.status === 'connected' ? '正式五核已连接' : '五核离线'}</span>
        <button className="topbar-profile-button" type="button" onClick={() => openTab(TASKS_TAB)}><span>☷</span><strong>学习任务</strong></button>
        <button className="topbar-profile-button" type="button" onClick={() => openTab(LEARNING_PATH_TAB)}><span>⌁</span><strong>学习路径</strong></button>
        <button className="topbar-profile-button" type="button" onClick={() => openTab(PROFILE_TAB)}><span>现</span><strong>我的画像</strong></button>
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
            <button type="button" className="sidebar-profile-button sidebar-task-button" onClick={() => openTab(TASKS_TAB)}>
              <span className="sidebar-profile-avatar">☷</span>
              <span><strong>学习任务</strong><small>{formalSnapshot?.learning_tasks.filter(task => !['completed', 'canceled'].includes(task.status)).length || 0} 个待完成</small></span>
              <i>›</i>
            </button>
            <button type="button" className="sidebar-profile-button sidebar-path-button" onClick={() => openTab(LEARNING_PATH_TAB)}>
              <span className="sidebar-profile-avatar">⌁</span>
              <span><strong>学习路径</strong><small>{projectLearnerPath(workspace.learningPath).nodes.length} 节点 · 可个性化</small></span>
              <i>›</i>
            </button>
            <button type="button" className="sidebar-profile-button" onClick={() => openTab(PROFILE_TAB)}>
              <span className="sidebar-profile-avatar">现</span>
              <span><strong>{formalSnapshot?.learner.display_name || '学习者画像'}</strong><small>{formalConnection.status === 'connected' ? `${formalSnapshot?.learner.education_stage || ''} · 五核正式接入` : '正式五核未连接'}</small></span>
              <i>›</i>
            </button>
            <small className="sidebar-logic-note">Chat · 任务 · 路径 · 五核画像 · 设置</small>
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

function ToolRunCard({ run, onAcceptPathProposal }: { run: TutorToolRun; onAcceptPathProposal: (proposal: PersonalPathNodeProposal) => void }) {
  const icon = run.kind === 'memory' ? '◇' : run.kind === 'path' ? '⌁' : run.kind === 'search' ? '⌕' : run.kind === 'image' ? '▧' : '▶'
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
      {run.pathProposal && (
        <div className="path-proposal-card">
          <span>个人节点提案</span>
          <strong>{run.pathProposal.title}</strong>
          <p>{run.pathProposal.summary}</p>
          <small>{run.pathProposal.connections.length} 条建议关系 · {run.pathProposal.sourceUrls.length} 个联网来源</small>
          <button type="button" onClick={() => onAcceptPathProposal(run.pathProposal!)}>确认加入我的学习路径</button>
        </div>
      )}
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

function MessageList({ messages, onQuoteFollowUp, onAcceptPathProposal }: {
  messages: Message[]
  onQuoteFollowUp: (messageId: string, quote: string) => void
  onAcceptPathProposal: (proposal: PersonalPathNodeProposal) => void
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
          <article key={message.id} data-message-id={message.id} data-message-role={message.role} className={`message message-${message.role}${message.learningActionLabel ? ' message-learning-action' : ''}`}>
            {message.role !== 'user' && <span className="message-avatar">{message.role === 'assistant' ? '✦' : 'i'}</span>}
            <div className="message-content" onMouseUp={message.role === 'assistant' ? event => captureSelection(message.id, event.currentTarget) : undefined}>
              <div className="message-meta">
                {message.role === 'user' ? '你' : message.role === 'assistant' ? 'Tutor' : '系统'}
                {message.tutorMode && (
                  <em>
                    {TUTOR_MODE_LABELS[message.tutorMode]}
                    {message.tutorMode === 'guided_learning' && message.learningSubstateLabel ? ` · ${message.learningSubstateLabel}` : ''}
                  </em>
                )}
                {message.learningSkillId && <em className="message-skill">{LEARNING_SKILLS[message.learningSkillId]?.name}</em>}
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
              {message.toolRuns?.map(run => <ToolRunCard key={run.id} run={run} onAcceptPathProposal={onAcceptPathProposal} />)}
              {message.learningActionLabel ? (
                <div className="learning-action-chip"><span>学习任务</span>{message.learningActionLabel}</div>
              ) : (
                <Suspense fallback={<div className="markdown-loading">正在排版…</div>}>
                  <MarkdownContent content={message.content} />
                </Suspense>
              )}
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
