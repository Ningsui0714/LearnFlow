import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import {
  buildProviderRequest,
  errorFromTutorProviderResponse,
  isTutorMode,
  textFromTutorProviderResponse,
  tutorConfigurationIssue,
} from './src/tutor'
import { isTutorToolChoice } from './src/tooling'
import { sanitizeLearningTaskTutorContext } from './src/learning'
import { sanitizeLearningPlanTutorContext } from './src/planning'
import { runTutorAgentTurn } from './server/agent-runtime'
import type { SearchProviderConfiguration } from './server/computer-knowledge-search.ts'
import { sanitizeLearnerPathState } from './src/learning-path-graph.ts'

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

function loadSearchConfiguration(mode: string): SearchProviderConfiguration {
  const localEnv = loadEnv(mode, process.cwd(), '')
  const value = (name: string) => String(process.env[name] || localEnv[name] || '').trim()
  return {
    jinaApiKey: value('JINA_API_KEY'),
    exaApiKey: value('EXA_API_KEY'),
    tavilyApiKey: value('TAVILY_API_KEY'),
  }
}

function loadBackendBase(mode: string) {
  const localEnv = loadEnv(mode, process.cwd(), '')
  return String(
    process.env.VNEXT_BACKEND_URL
      || process.env.LEARNFLOW_FORMAL_BACKEND_URL
      || localEnv.VNEXT_BACKEND_URL
      || localEnv.LEARNFLOW_FORMAL_BACKEND_URL
      || 'http://127.0.0.1:8010',
  ).replace(/\/$/, '')
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

function tutorProxy(mode: string, backendBase: string): Plugin {
  const keyConfiguration = loadTutorKey(mode)
  const searchConfiguration = loadSearchConfiguration(mode)

  const callProvider = async (options: {
    endpoint: string
    body: unknown
    timeoutMs?: number
  }) => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 65_000)
    try {
      const providerResponse = await fetch(options.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(keyConfiguration.apiKey ? { Authorization: `Bearer ${keyConfiguration.apiKey}` } : {}),
        },
        body: JSON.stringify(options.body),
        signal: controller.signal,
      })
      const providerBody = await providerResponse.text()
      let providerPayload: unknown = null
      try {
        providerPayload = JSON.parse(providerBody)
      } catch {
        const streamParts = providerBody.split(/\r?\n/)
          .filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trim())
          .filter(line => line && line !== '[DONE]')
          .flatMap(line => {
            try {
              const part = textFromTutorProviderResponse(JSON.parse(line))
              return part ? [part] : []
            } catch {
              return []
            }
          })
        providerPayload = streamParts.length ? streamParts.join('') : providerBody
      }
      if (!providerResponse.ok) {
        throw new Error(errorFromTutorProviderResponse(providerPayload, providerResponse.status))
      }
      return providerPayload
    } finally {
      clearTimeout(timeout)
    }
  }

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
      const toolChoice = isTutorToolChoice(input.toolChoice) ? input.toolChoice : 'auto'
      const selectionContext = typeof input.selectionContext === 'string' ? input.selectionContext.slice(0, 1600) : ''
      const learningTaskContext = sanitizeLearningTaskTutorContext(input.learningTaskContext)
      const learningPlanContext = sanitizeLearningPlanTutorContext(input.learningPlanContext)
      const learnerPathState = sanitizeLearnerPathState(input.learnerPathState)
      const taskQueue = Array.isArray(input.taskQueue) ? input.taskQueue.filter((item): item is any => (
        item && typeof item === 'object' && typeof item.id === 'number'
        && typeof item.objective === 'string' && typeof item.status === 'string'
      )).slice(0, 30).map(item => ({
        id: item.id,
        objective: item.objective.slice(0, 300),
        status: item.status.slice(0, 60),
        sourceType: typeof item.sourceType === 'string' ? item.sourceType.slice(0, 80) : undefined,
        sourceId: typeof item.sourceId === 'string' ? item.sourceId.slice(0, 180) : undefined,
        updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt.slice(0, 80) : undefined,
      })) : []
      const knowledgeDomains = Array.isArray(input.knowledgeDomains) ? input.knowledgeDomains.filter((item): item is any => (
        item && typeof item === 'object' && typeof item.id === 'string' && typeof item.title === 'string'
      )).slice(0, 30).map(item => ({
        id: item.id.slice(0, 120),
        title: item.title.slice(0, 160),
        summary: typeof item.summary === 'string' ? item.summary.slice(0, 600) : undefined,
        labels: Array.isArray(item.labels) ? item.labels.filter((value: unknown) => typeof value === 'string').slice(0, 16) : [],
        sourceIds: Array.isArray(item.sourceIds) ? item.sourceIds.filter((value: unknown) => typeof value === 'string').slice(0, 12) : [],
      })) : []
      const rawFormalScope = input.formalScope && typeof input.formalScope === 'object'
        ? input.formalScope as Record<string, unknown> : {}
      const positiveInteger = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value > 0
        ? value : undefined
      const formalScope = {
        sessionId: positiveInteger(rawFormalScope.sessionId),
        projectId: positiveInteger(rawFormalScope.projectId),
        checkpointId: positiveInteger(rawFormalScope.checkpointId),
      }
      const configurationIssue = tutorConfigurationIssue(baseUrl, model)
      if (configurationIssue) throw new Error(configurationIssue)
      if (!isTutorMode(modeValue)) throw new Error('Tutor 状态无效')

      const messages = Array.isArray(input.messages)
        ? input.messages.filter((message): message is { role: 'assistant' | 'user'; content: string; toolRuns?: any[] } => {
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

      const latestMessage = [...messages].reverse().find(message => message.role === 'user')?.content || ''
      let formalLearnerContext: unknown = null
      let formalWorkspaceContext: unknown = null
      let formalReviewContext: unknown = null
      try {
        const contextPurpose = modeValue === 'learning_plan'
          ? 'learning_plan'
          : modeValue === 'guided_learning' ? 'learning_task' : 'global_tutor'
        const contextQuery = new URLSearchParams({
          query: latestMessage.slice(0, 1800),
          purpose: contextPurpose,
        })
        const contextResponse = await fetch(`${backendBase}/api/learner-state/context?${contextQuery}`, {
          headers: request.headers.cookie ? { Cookie: request.headers.cookie } : {},
          signal: AbortSignal.timeout(4_000),
        })
        if (contextResponse.ok) {
          formalLearnerContext = await contextResponse.json()
        }
      } catch {
        formalLearnerContext = null
      }
      if (modeValue === 'guided_learning' || modeValue === 'learning_plan') {
        try {
          const workspaceQuery = new URLSearchParams()
          if (formalScope.sessionId) workspaceQuery.set('session_id', String(formalScope.sessionId))
          if (formalScope.projectId) workspaceQuery.set('project_id', String(formalScope.projectId))
          if (formalScope.checkpointId) workspaceQuery.set('checkpoint_id', String(formalScope.checkpointId))
          const workspaceResponse = await fetch(
            `${backendBase}/api/learner-state/agent-workspace-context?${workspaceQuery}`,
            {
              headers: request.headers.cookie ? { Cookie: request.headers.cookie } : {},
              signal: AbortSignal.timeout(4_000),
            },
          )
          if (workspaceResponse.ok) formalWorkspaceContext = await workspaceResponse.json()
        } catch {
          formalWorkspaceContext = null
        }
      }
      if (/复习|错题|遗忘|记不住|熟练度|掌握度|记忆曲线|间隔|回忆|薄弱/i.test(latestMessage)) {
        try {
          const reviewQuery = new URLSearchParams({ query: latestMessage.slice(0, 1800), limit: '8' })
          const reviewResponse = await fetch(`${backendBase}/api/review/agent-context?${reviewQuery}`, {
            headers: request.headers.cookie ? { Cookie: request.headers.cookie } : {},
            signal: AbortSignal.timeout(4_000),
          })
          if (reviewResponse.ok) formalReviewContext = await reviewResponse.json()
        } catch {
          formalReviewContext = null
        }
      }
      const generate = async (instructions: string, inputText: string, timeoutMs?: number) => {
        const request = buildProviderRequest({
          baseUrl, model, instructions,
          messages: [{ role: 'user', content: inputText }],
          maxTokens: 1200,
        })
        const payload = await callProvider({ ...request, timeoutMs: timeoutMs || 32_000 })
        const text = textFromTutorProviderResponse(payload)
        if (!text) throw new Error('模型没有返回视觉生成文本')
        return text
      }
      const result = await runTutorAgentTurn({
        baseUrl,
        model,
        mode: modeValue,
        messages,
        toolChoice,
        selectionContext,
        learningTaskContext,
        learningPlanContext,
        learnerPathState,
        taskQueue,
        knowledgeDomains,
        formalLearnerContext,
        formalWorkspaceContext,
        formalReviewContext,
        conversationId: typeof input.conversationId === 'string' ? input.conversationId.slice(0, 160) : undefined,
        sheetId: typeof input.sheetId === 'string' ? input.sheetId.slice(0, 160) : undefined,
        generate,
        searchConfiguration,
        invokeProvider: callProvider,
      })
      sendJson(response, 200, result)
    } catch (error) {
      const message = error instanceof Error && error.name === 'AbortError'
        ? '模型请求超过当前时间预算，已停止等待'
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

function backendApiProxy(backendBase: string): Plugin {
  const middleware = async (request: any, response: any, next: () => void) => {
    const requestUrl = new URL(request.url || '/', 'http://127.0.0.1:4174')
    if (!requestUrl.pathname.startsWith('/api/') || requestUrl.pathname === '/api/tutor' || requestUrl.pathname === '/api/tutor/status') {
      next()
      return
    }
    try {
      const method = String(request.method || 'GET').toUpperCase()
      const body = method === 'GET' || method === 'HEAD'
        ? undefined
        : JSON.stringify(await readJsonBody(request))
      const upstream = await fetch(`${backendBase}${requestUrl.pathname}${requestUrl.search}`, {
        method,
        headers: {
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(request.headers.cookie ? { Cookie: request.headers.cookie } : {}),
          ...(request.headers.authorization ? { Authorization: request.headers.authorization } : {}),
        },
        body,
        signal: AbortSignal.timeout(30_000),
      })
      response.statusCode = upstream.status
      response.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/json; charset=utf-8')
      response.setHeader('Cache-Control', 'no-store')
      const setCookie = upstream.headers.get('set-cookie')
      if (setCookie) response.setHeader('Set-Cookie', setCookie)
      response.end(await upstream.text())
    } catch (error) {
      sendJson(response, 503, {
        detail: error instanceof Error && error.name === 'TimeoutError'
          ? '正式后端请求超时'
          : '正式五核后端未启动或无法连接',
      })
    }
  }
  return {
    name: 'learnflow-formal-backend-proxy',
    configureServer(server) { server.middlewares.use(middleware) },
    configurePreviewServer(server) { server.middlewares.use(middleware) },
  }
}

export default defineConfig(({ mode }) => {
  const backendBase = loadBackendBase(mode)
  return {
  plugins: [react(), tutorProxy(mode, backendBase), backendApiProxy(backendBase)],
  server: {
    host: '127.0.0.1',
    port: 4174,
    strictPort: true,
  },
  }
})
