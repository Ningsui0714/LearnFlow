import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export type WorkspaceTabKind =
  | 'home'
  | 'projects'
  | 'project'
  | 'lecture'
  | 'exercise'
  | 'memory'
  | 'profile'
  | 'settings'

const WORKSPACE_TAB_KINDS: WorkspaceTabKind[] = [
  'home', 'projects', 'project', 'lecture', 'exercise', 'memory', 'profile', 'settings',
]

export interface WorkspaceTab {
  id: string
  path: string
  title: string
  kind: WorkspaceTabKind
  projectId?: number
  checkpointId?: number
  pinned?: boolean
}

interface WorkspaceTabPatch {
  title?: string
  kind?: WorkspaceTabKind
  projectId?: number
  checkpointId?: number
}

interface WorkspaceContextValue {
  tabs: WorkspaceTab[]
  activeTabId: string
  splitTabIds: string[]
  draggingTabId: string | null
  openPath: (path: string, patch?: WorkspaceTabPatch) => void
  activateTab: (tabId: string) => void
  closeTab: (tabId: string) => void
  updateCurrentTab: (patch: WorkspaceTabPatch) => void
  splitTab: (tabId: string) => void
  closeSplit: (tabId: string) => void
  setDraggingTabId: (tabId: string | null) => void
}

const HOME_TAB: WorkspaceTab = {
  id: '/agent',
  path: '/agent',
  title: '学习工作台',
  kind: 'home',
  pinned: true,
}

const noOp = () => {}
const WorkspaceContext = createContext<WorkspaceContextValue>({
  tabs: [HOME_TAB],
  activeTabId: HOME_TAB.id,
  splitTabIds: [],
  draggingTabId: null,
  openPath: noOp,
  activateTab: noOp,
  closeTab: noOp,
  updateCurrentTab: noOp,
  splitTab: noOp,
  closeSplit: noOp,
  setDraggingTabId: noOp,
})

function normalizePath(path: string) {
  const url = new URL(path, window.location.origin)
  url.searchParams.delete('embed')
  const query = url.searchParams.toString()
  return `${url.pathname}${query ? `?${query}` : ''}${url.hash}`
}

function pathMeta(path: string): WorkspaceTab {
  const normalized = normalizePath(path)
  const pathname = new URL(normalized, window.location.origin).pathname
  const exercise = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)\/exercises$/)
  if (exercise) {
    return {
      id: normalized,
      path: normalized,
      title: `练习 · 关卡 ${exercise[2]}`,
      kind: 'exercise',
      projectId: Number(exercise[1]),
      checkpointId: Number(exercise[2]),
    }
  }
  const lecture = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)$/)
  if (lecture) {
    return {
      id: normalized,
      path: normalized,
      title: `讲义 · 关卡 ${lecture[2]}`,
      kind: 'lecture',
      projectId: Number(lecture[1]),
      checkpointId: Number(lecture[2]),
    }
  }
  const project = pathname.match(/^\/projects\/(\d+)$/)
  if (project) {
    return {
      id: normalized,
      path: normalized,
      title: `学习项目 ${project[1]}`,
      kind: 'project',
      projectId: Number(project[1]),
    }
  }
  const staticMeta: Record<string, Pick<WorkspaceTab, 'title' | 'kind' | 'pinned'>> = {
    '/agent': { title: '学习工作台', kind: 'home', pinned: true },
    '/projects': { title: '学习项目', kind: 'projects' },
    '/memory': { title: '五核记忆', kind: 'memory' },
    '/profile': { title: '个人画像', kind: 'profile' },
    '/settings': { title: '开发设置', kind: 'settings' },
  }
  const meta = staticMeta[pathname] || { title: 'LearnFlow', kind: 'home' as const }
  return { id: normalized, path: normalized, ...meta }
}

function validTab(value: unknown): value is WorkspaceTab {
  if (!value || typeof value !== 'object') return false
  const tab = value as WorkspaceTab
  return typeof tab.id === 'string'
    && typeof tab.path === 'string'
    && typeof tab.title === 'string'
    && tab.path.startsWith('/')
    && tab.id === normalizePath(tab.path)
    && WORKSPACE_TAB_KINDS.includes(tab.kind)
}

function limitTabs(items: WorkspaceTab[]) {
  const home = items.find(tab => tab.id === HOME_TAB.id) || HOME_TAB
  return [home, ...items.filter(tab => tab.id !== HOME_TAB.id).slice(-15)]
}

export function WorkspaceProvider({ learnerKey, children }: { learnerKey: string; children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const storageKey = `learnflow.workspace.v1.${learnerKey}`
  const [tabs, setTabs] = useState<WorkspaceTab[]>([HOME_TAB])
  const [activeTabId, setActiveTabId] = useState(HOME_TAB.id)
  const [splitTabIds, setSplitTabIds] = useState<string[]>([])
  const [draggingTabId, setDraggingTabId] = useState<string | null>(null)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '{}')
      const restored = Array.isArray(saved.tabs) ? saved.tabs.filter(validTab) : []
      const withHome = restored.some((tab: WorkspaceTab) => tab.id === HOME_TAB.id)
        ? restored.map((tab: WorkspaceTab) => tab.id === HOME_TAB.id ? HOME_TAB : tab)
        : [HOME_TAB, ...restored]
      const limited = limitTabs(withHome)
      setTabs(limited)
      setSplitTabIds(
        Array.isArray(saved.splitTabIds)
          ? saved.splitTabIds.filter((id: unknown) => typeof id === 'string' && limited.some((tab: WorkspaceTab) => tab.id === id)).slice(0, 2)
          : [],
      )
    } catch {
      setTabs([HOME_TAB])
      setSplitTabIds([])
    }
    setHydrated(true)
  }, [storageKey])

  useEffect(() => {
    if (!hydrated) return
    localStorage.setItem(storageKey, JSON.stringify({ tabs, splitTabIds }))
  }, [hydrated, splitTabIds, storageKey, tabs])

  useEffect(() => {
    if (!hydrated) return
    const path = normalizePath(`${location.pathname}${location.search}${location.hash}`)
    const next = pathMeta(path)
    setTabs(previous => {
      const existing = previous.find(tab => tab.id === next.id)
      return existing ? previous : limitTabs([...previous, next])
    })
    setActiveTabId(next.id)
  }, [hydrated, location.hash, location.pathname, location.search])

  const openPath = useCallback((path: string, patch: WorkspaceTabPatch = {}) => {
    const base = pathMeta(path)
    const next = { ...base, ...patch, id: base.id, path: base.path }
    setTabs(previous => {
      const index = previous.findIndex(tab => tab.id === next.id)
      if (index < 0) return limitTabs([...previous, next])
      const copy = [...previous]
      copy[index] = { ...copy[index], ...next }
      return copy
    })
    setActiveTabId(next.id)
    navigate(next.path)
  }, [navigate])

  const activateTab = useCallback((tabId: string) => {
    const tab = tabs.find(item => item.id === tabId)
    if (!tab) return
    setActiveTabId(tab.id)
    navigate(tab.path)
  }, [navigate, tabs])

  const closeTab = useCallback((tabId: string) => {
    const index = tabs.findIndex(tab => tab.id === tabId)
    const target = tabs[index]
    if (index < 0 || target?.pinned) return
    const remaining = tabs.filter(tab => tab.id !== tabId)
    setTabs(remaining)
    setSplitTabIds(previous => previous.filter(id => id !== tabId))
    if (activeTabId === tabId) {
      const next = remaining[index] || remaining[index - 1] || HOME_TAB
      setActiveTabId(next.id)
      navigate(next.path)
    }
  }, [activeTabId, navigate, tabs])

  const updateCurrentTab = useCallback((patch: WorkspaceTabPatch) => {
    const currentId = normalizePath(`${location.pathname}${location.search}${location.hash}`)
    setTabs(previous => previous.map(tab => tab.id === currentId ? { ...tab, ...patch } : tab))
  }, [location.hash, location.pathname, location.search])

  const splitTab = useCallback((tabId: string) => {
    if (!tabs.some(tab => tab.id === tabId)) return
    setSplitTabIds(previous => {
      if (previous.includes(tabId)) return previous
      return [...previous, tabId].slice(-2)
    })
  }, [tabs])

  const closeSplit = useCallback((tabId: string) => {
    setSplitTabIds(previous => previous.filter(id => id !== tabId))
  }, [])

  const value = useMemo<WorkspaceContextValue>(() => ({
    tabs,
    activeTabId,
    splitTabIds,
    draggingTabId,
    openPath,
    activateTab,
    closeTab,
    updateCurrentTab,
    splitTab,
    closeSplit,
    setDraggingTabId,
  }), [
    tabs, activeTabId, splitTabIds, draggingTabId, openPath, activateTab,
    closeTab, updateCurrentTab, splitTab, closeSplit,
  ])

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}

export function useWorkspaceTitle(title: string, patch: WorkspaceTabPatch = {}) {
  const { updateCurrentTab } = useWorkspace()
  const { kind, projectId, checkpointId } = patch
  useEffect(() => {
    if (!title) return
    updateCurrentTab({ title, kind, projectId, checkpointId })
  }, [checkpointId, kind, projectId, title, updateCurrentTab])
}

export function workspaceEmbedPath(path: string) {
  const url = new URL(path, window.location.origin)
  url.searchParams.set('embed', '1')
  return `${url.pathname}${url.search}${url.hash}`
}
