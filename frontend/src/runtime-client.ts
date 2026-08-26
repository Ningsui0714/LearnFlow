const DESKTOP_AUTH_STORAGE_KEY = 'learnflow.desktop.auth-token'

export type RuntimeClientState = {
  kind: 'web' | 'desktop'
  ready: boolean
  apiBaseUrl?: string
  desktopToken?: string
  startupError?: string
}

let runtime: RuntimeClientState = { kind: 'web', ready: true }
let initialization: Promise<RuntimeClientState> | undefined

function isTauriWindow() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export function getRuntimeClientState() {
  return runtime
}

export function isDesktopRuntime() {
  return runtime.kind === 'desktop'
}

export function resolveRuntimeUrl(input: RequestInfo | URL) {
  if (runtime.kind !== 'desktop' || !runtime.apiBaseUrl || typeof input !== 'string' || !input.startsWith('/api')) {
    return input
  }
  return `${runtime.apiBaseUrl.replace(/\/$/, '')}${input.slice('/api'.length)}`
}

export function captureRuntimeAuth(payload: unknown) {
  if (runtime.kind !== 'desktop' || !payload || typeof payload !== 'object') return
  const token = (payload as Record<string, unknown>).desktop_auth_token
  if (typeof token === 'string' && token) sessionStorage.setItem(DESKTOP_AUTH_STORAGE_KEY, token)
}

export async function runtimeFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (runtime.kind === 'desktop' && runtime.desktopToken) {
    headers.set('X-LearnFlow-Desktop-Token', runtime.desktopToken)
    const authToken = sessionStorage.getItem(DESKTOP_AUTH_STORAGE_KEY)
    if (authToken) headers.set('Authorization', `Bearer ${authToken}`)
  }
  const response = await fetch(resolveRuntimeUrl(input), {
    ...init,
    headers,
    credentials: init.credentials || 'include',
  })
  if (response.status === 401 && runtime.kind === 'desktop') {
    window.dispatchEvent(new CustomEvent('learnflow:unauthorized'))
  }
  return response
}

async function waitForSidecar(apiBaseUrl: string) {
  const healthUrl = `${apiBaseUrl.replace(/\/api\/?$/, '')}/health`
  let lastError: unknown
  for (let attempt = 0; attempt < 180; attempt += 1) {
    try {
      const response = await fetch(healthUrl)
      if (response.ok) return
      lastError = new Error(`HTTP ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => window.setTimeout(resolve, 500))
  }
  const detail = lastError instanceof Error ? `：${lastError.message}` : ''
  throw new Error(`本地服务启动超时（90 秒）${detail}`)
}

export function initializeRuntimeClient(): Promise<RuntimeClientState> {
  if (initialization) return initialization
  initialization = (async () => {
    if (!isTauriWindow()) return runtime
    runtime = { kind: 'desktop', ready: false }
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const config = await invoke<{ apiBaseUrl: string; desktopToken: string }>('desktop_runtime_config')
      await waitForSidecar(config.apiBaseUrl)
      runtime = {
        kind: 'desktop', ready: true,
        apiBaseUrl: config.apiBaseUrl, desktopToken: config.desktopToken,
      }
      document.documentElement.dataset.learnflowDesktop = 'true'
    } catch (error) {
      runtime = {
        kind: 'desktop', ready: false,
        startupError: error instanceof Error ? error.message : '桌面本地服务启动失败',
      }
    }
    window.dispatchEvent(new CustomEvent('learnflow:runtime-changed'))
    return runtime
  })()
  return initialization
}
