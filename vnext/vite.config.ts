import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import {
  buildProviderRequest,
  buildTutorProviderRequest,
  errorFromTutorProviderResponse,
  ensureSearchCitations,
  isDisplayableTutorReply,
  isTutorMode,
  textFromTutorProviderResponse,
  tutorConfigurationIssue,
} from './src/tutor'
import { isTutorToolChoice } from './src/tooling'
import { sanitizeLearningTaskTutorContext } from './src/learning'
import { sanitizeLearningPlanTutorContext } from './src/planning'
import { runTutorTools } from './server/tool-runtime'
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
      const text = textFromTutorProviderResponse(providerPayload)
      if (!text) {
        const root = providerPayload && typeof providerPayload === 'object' ? providerPayload as Record<string, unknown> : {}
        const firstChoice = Array.isArray(root.choices) && root.choices[0] && typeof root.choices[0] === 'object'
          ? root.choices[0] as Record<string, unknown> : {}
        const message = firstChoice.message && typeof firstChoice.message === 'object'
          ? firstChoice.message as Record<string, unknown> : {}
        console.warn('[LearnFlow vNext] provider returned no display text', {
          rootKeys: Object.keys(root), choiceKeys: Object.keys(firstChoice), messageKeys: Object.keys(message),
          contentType: Array.isArray(message.content) ? 'array' : typeof message.content,
        })
        throw new Error('模型服务没有返回可显示的文本')
      }
      return text
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

      const latestMessage = [...messages].reverse().find(message => message.role === 'user')?.content || ''
      let formalLearnerContext = ''
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
          const packet = await contextResponse.json()
          formalLearnerContext = `正式五核 ContextPacket（只读、答案隔离）：\n${JSON.stringify(packet).slice(0, 14_000)}`
        }
      } catch {
        formalLearnerContext = ''
      }
      const generate = async (instructions: string, inputText: string, timeoutMs?: number) => {
        const request = buildProviderRequest({
          baseUrl, model, instructions,
          messages: [{ role: 'user', content: inputText }],
          maxTokens: 1200,
        })
        return callProvider({ ...request, timeoutMs })
      }
      const tools = await runTutorTools({
        message: latestMessage,
        choice: toolChoice,
        generate,
        searchConfiguration,
        mode: modeValue,
        learningTaskContext,
        learnerPathState,
        formalLearnerContext,
      })
      const providerRequest = buildTutorProviderRequest({
        baseUrl, model, mode: modeValue, messages,
        toolContext: tools.context,
        selectionContext,
        learningTaskContext,
        learningPlanContext,
      })
      let reply = tools.directReply
      if (!reply) {
        try {
          reply = await callProvider(providerRequest)
        } catch (error) {
          if (!(error instanceof Error) || error.message !== '模型服务没有返回可显示的文本') throw error
          const compactToolContext = tools.runs.map(run => {
            const sourceLines = (run.sources || []).slice(0, 5).map(source => `- ${source.title}: ${source.url}`)
            return `${run.title}：${run.detail}${sourceLines.length ? `\n${sourceLines.join('\n')}` : ''}`
          }).join('\n\n')
          const retryRequest = buildTutorProviderRequest({
            baseUrl, model, mode: modeValue, messages: messages.slice(-10),
            toolContext: compactToolContext,
            selectionContext,
            learningTaskContext,
            learningPlanContext,
          })
          reply = await callProvider({ ...retryRequest, timeoutMs: 32_000 })
        }
      }
      if (!isDisplayableTutorReply(reply)) {
        const repairRequest = buildTutorProviderRequest({
          baseUrl, model, mode: modeValue, messages: messages.slice(-10),
          toolContext: `${tools.context}\n\n回复契约修正：上一次模型输出了不可展示的内部工具协议。请重新回答当前学生问题，只输出自然的中文教学正文，不得输出任何 tool_call、function、XML 参数或内部状态指令。`,
          selectionContext,
          learningTaskContext,
          learningPlanContext,
        })
        reply = await callProvider({ ...repairRequest, timeoutMs: 32_000 })
        if (!isDisplayableTutorReply(reply)) {
          throw new Error('模型连续返回内部工具协议，已停止展示；请重试本轮')
        }
      }
      reply = ensureSearchCitations(reply, tools.runs)
      sendJson(response, 200, { reply, toolRuns: tools.runs })
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
