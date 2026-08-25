import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import {
  buildTutorProviderRequest,
  errorFromTutorProviderResponse,
  isTutorMode,
  textFromTutorProviderResponse,
  tutorConfigurationIssue,
} from './src/tutor'

type KeyConfiguration = {
  apiKey: string
  source: string
}

function loadTutorKey(mode: string): KeyConfiguration {
  const localEnv = loadEnv(mode, process.cwd(), '')
  const candidates: Array<[string, string | undefined]> = [
    ['启动环境', process.env.LEARNFLOW_API_KEY],
    ['vnext/.env.local', localEnv.LEARNFLOW_API_KEY],
  ]
  const match = candidates.find(([, value]) => value && value !== 'sk-your-key-here')
  return { apiKey: match?.[1]?.trim() || '', source: match?.[0] || '' }
}

function readJsonBody(request: any): Promise<unknown> {
  return new Promise((resolveBody, rejectBody) => {
    let body = ''
    let tooLarge = false
    request.setEncoding('utf8')
    request.on('data', (chunk: string) => {
      if (tooLarge) return
      body += chunk
      if (body.length > 1_000_000) tooLarge = true
    })
    request.on('end', () => {
      if (tooLarge) {
        rejectBody(new Error('请求内容过大'))
        return
      }
      try {
        resolveBody(JSON.parse(body || '{}'))
      } catch {
        rejectBody(new Error('请求不是有效 JSON'))
      }
    })
    request.on('error', rejectBody)
  })
}

function sendJson(response: any, status: number, payload: unknown) {
  response.statusCode = status
  response.setHeader('Content-Type', 'application/json; charset=utf-8')
  response.setHeader('Cache-Control', 'no-store')
  response.end(JSON.stringify(payload))
}

function tutorProxy(mode: string): Plugin {
  const keyConfiguration = loadTutorKey(mode)
  const middleware = async (request: any, response: any, next: () => void) => {
    const requestUrl = new URL(request.url || '/', 'http://127.0.0.1:4174')
    if (requestUrl.pathname === '/api/tutor/status') {
      if (request.method !== 'GET') {
        sendJson(response, 405, { error: '只允许 GET' })
        return
      }
      sendJson(response, 200, {
        configured: Boolean(keyConfiguration.apiKey),
        source: keyConfiguration.source,
      })
      return
    }

    if (requestUrl.pathname !== '/api/tutor') {
      next()
      return
    }
    if (request.method !== 'POST') {
      sendJson(response, 405, { error: '只允许 POST' })
      return
    }

    const origin = request.headers.origin
    if (origin && !['http://127.0.0.1:4174', 'http://localhost:4174'].includes(origin)) {
      sendJson(response, 403, { error: '拒绝非本地页面请求' })
      return
    }

    try {
      const payload = await readJsonBody(request)
      if (!payload || typeof payload !== 'object') throw new Error('请求内容无效')
      const input = payload as Record<string, unknown>
      const baseUrl = typeof input.baseUrl === 'string' ? input.baseUrl : ''
      const model = typeof input.model === 'string' ? input.model : ''
      const modeValue = input.mode
      const configurationIssue = tutorConfigurationIssue(baseUrl, model)
      if (configurationIssue) throw new Error(configurationIssue)
      if (!isTutorMode(modeValue)) throw new Error('Tutor 状态无效')

      const messages = Array.isArray(input.messages)
        ? input.messages.filter((message): message is { role: 'assistant' | 'user'; content: string } => {
            if (!message || typeof message !== 'object') return false
            const item = message as Record<string, unknown>
            return (item.role === 'assistant' || item.role === 'user') && typeof item.content === 'string'
          })
        : []
      if (messages.length === 0) throw new Error('没有可发送的对话内容')

      const providerUrl = new URL(baseUrl)
      const localProvider = ['localhost', '127.0.0.1', '::1'].includes(providerUrl.hostname)
      if (!localProvider && !keyConfiguration.apiKey) {
        throw new Error('本地环境没有 API Key。请在 vnext/.env.local 设置 LEARNFLOW_API_KEY，然后重启服务。')
      }

      const providerRequest = buildTutorProviderRequest({ baseUrl, model, mode: modeValue, messages })
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 45_000)
      try {
        const providerResponse = await fetch(providerRequest.endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(keyConfiguration.apiKey ? { Authorization: `Bearer ${keyConfiguration.apiKey}` } : {}),
          },
          body: JSON.stringify(providerRequest.body),
          signal: controller.signal,
        })
        const providerPayload = await providerResponse.json().catch(() => null)
        if (!providerResponse.ok) {
          throw new Error(errorFromTutorProviderResponse(providerPayload, providerResponse.status))
        }
        const reply = textFromTutorProviderResponse(providerPayload)
        if (!reply) throw new Error('模型服务没有返回可显示的文本')
        sendJson(response, 200, { reply })
      } finally {
        clearTimeout(timeout)
      }
    } catch (error) {
      const message = error instanceof Error && error.name === 'AbortError'
        ? '模型请求超过 45 秒，已停止等待'
        : error instanceof TypeError
          ? '本地服务无法连接模型地址，请检查 Base URL 和网络'
          : error instanceof Error ? error.message : 'Tutor 请求失败'
      sendJson(response, 400, { error: message })
    }
  }

  return {
    name: 'learnflow-local-tutor-proxy',
    configureServer(server) {
      server.middlewares.use(middleware)
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware)
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tutorProxy(mode)],
  server: {
    host: '127.0.0.1',
    port: 4174,
    strictPort: true,
  },
}))
