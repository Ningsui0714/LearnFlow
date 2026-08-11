import { configureDesktopApi } from './api'

export interface DesktopRuntime {
  available: boolean
  apiBaseUrl?: string
  desktopToken?: string
  startupError?: string
}

let runtime: DesktopRuntime = { available: false }

function isTauriWindow() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function waitForSidecar(apiBaseUrl: string) {
  const healthUrl = `${apiBaseUrl.replace(/\/api\/?$/, '')}/health`
  let lastError: unknown
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(healthUrl)
      if (response.ok) return
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => window.setTimeout(resolve, 100))
  }
  throw new Error(lastError instanceof Error ? lastError.message : '本地服务启动超时')
}

export async function initializeDesktopRuntime(): Promise<DesktopRuntime> {
  if (!isTauriWindow()) return runtime
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const config = await invoke<{ apiBaseUrl: string; desktopToken: string }>('desktop_runtime_config')
    configureDesktopApi(config.apiBaseUrl, config.desktopToken)
    await waitForSidecar(config.apiBaseUrl)
    runtime = {
      available: true,
      apiBaseUrl: config.apiBaseUrl,
      desktopToken: config.desktopToken,
    }
    document.documentElement.dataset.learnflowDesktop = 'true'
  } catch (error) {
    runtime = {
      available: true,
      startupError: error instanceof Error ? error.message : '桌面本地服务启动失败',
    }
  }
  return runtime
}

export function getDesktopRuntime() {
  return runtime
}

export async function chooseWorkspaceDirectory() {
  if (!runtime.available) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({ directory: true, multiple: false })
  return typeof selected === 'string' ? selected : null
}

export async function choosePythonInterpreter() {
  if (!runtime.available) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({
    directory: false,
    multiple: false,
    title: '选择项目使用的 Python 解释器',
  })
  return typeof selected === 'string' ? selected : null
}
