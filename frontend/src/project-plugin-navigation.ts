export type ProjectPanelCoreTab = 'checkpoints' | 'sources' | 'files' | 'plugins'
export type ProjectPluginSurfaceTab = `plugin:${string}:${string}`
export type ProjectPanelTab = ProjectPanelCoreTab | ProjectPluginSurfaceTab

export type ProjectPanelRequest = {
  conversationId: string
  requestedTab: ProjectPanelTab
  requestKey: number
}

export function initialProjectPanelRequest(): ProjectPanelRequest {
  return { conversationId: '', requestedTab: 'checkpoints', requestKey: 0 }
}

export function requestProjectPanel(
  current: ProjectPanelRequest,
  conversationId: string,
  requestedTab: ProjectPanelTab,
): ProjectPanelRequest {
  return {
    conversationId,
    requestedTab,
    requestKey: current.requestKey + 1,
  }
}

export function toggleProjectPanel(
  current: ProjectPanelRequest,
  conversationId: string,
): ProjectPanelRequest {
  if (current.conversationId === conversationId) {
    return { ...current, conversationId: '' }
  }
  return requestProjectPanel(current, conversationId, 'checkpoints')
}

export function closeProjectPanel(current: ProjectPanelRequest): ProjectPanelRequest {
  return { ...current, conversationId: '' }
}

export function pluginSurfaceTabId(pluginId: string, surfaceId: string): ProjectPluginSurfaceTab {
  return `plugin:${pluginId}:${surfaceId}`
}

export function reconcileProjectPanelTab(
  activeTab: ProjectPanelTab,
  availablePluginTabs: ReadonlySet<ProjectPluginSurfaceTab>,
): ProjectPanelTab {
  if (!activeTab.startsWith('plugin:')) return activeTab
  return availablePluginTabs.has(activeTab as ProjectPluginSurfaceTab) ? activeTab : 'plugins'
}
