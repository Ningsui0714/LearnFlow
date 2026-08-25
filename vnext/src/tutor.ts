export type TutorMode = 'free' | 'simple_explain'

export type TutorContextMessage = {
  role: 'assistant' | 'user'
  content: string
}

export const TUTOR_MODE_LABELS: Record<TutorMode, string> = {
  free: '自由态',
  simple_explain: '简单讲解态',
}

const EXPLANATION_INTENT = /(?:什么是|讲讲|讲一下|解释(?:一下)?|怎么理解|如何理解|帮我理解|介绍一下)/

export function isTutorMode(value: unknown): value is TutorMode {
  return value === 'free' || value === 'simple_explain'
}

export function resolveTutorMode(selectedMode: TutorMode, input: string): TutorMode {
  if (selectedMode === 'simple_explain') return selectedMode
  return EXPLANATION_INTENT.test(input) ? 'simple_explain' : 'free'
}

export function tutorConfigurationIssue(baseUrl: string, model: string) {
  if (!baseUrl.trim() || !model.trim()) return '请先在设置中填写 Base URL 和模型名称。'
  try {
    const url = new URL(baseUrl.trim())
    if (!['http:', 'https:'].includes(url.protocol)) return 'Base URL 必须使用 http 或 https。'
  } catch {
    return 'Base URL 不是有效地址。'
  }
  return ''
}

function systemPrompt(mode: TutorMode) {
  const common = [
    '你是 LearnFlow Tutor，面向正在学习计算机知识的学生。',
    '只基于可靠知识回答；不确定时明确说明，不编造来源、进度或掌握结论。',
    '使用清楚、自然的中文，根据学生已有上下文决定术语密度。',
  ].join('\n')

  if (mode === 'simple_explain') {
    return `${common}\n\n当前状态：简单讲解态。\n这一轮必须先直接给出必要的启发或解释，不能用一个空泛追问代替讲解。按需组织为：直观认识、核心机制、一个最小例子、一个简短自检问题。不要机械套标题；简单问题可以更短。只完成这一轮解释，不宣称学生已经掌握。`
  }

  return `${common}\n\n当前状态：自由态。\n自然回应学生当前意图，可以讨论、澄清、共同规划或回答短问题。只有在缺少关键信息时才追问，不擅自创建学习任务，不宣称学生已经掌握。`
}

function endpointFor(baseUrl: string) {
  const normalized = baseUrl.trim().replace(/\/+$/, '')
  if (/\/(?:responses|chat\/completions)$/.test(normalized)) return normalized
  return `${normalized}/chat/completions`
}

export function textFromTutorProviderResponse(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return ''
  const root = payload as Record<string, unknown>
  if (typeof root.output_text === 'string') return root.output_text.trim()

  if (Array.isArray(root.choices)) {
    const first = root.choices[0]
    if (first && typeof first === 'object') {
      const message = (first as Record<string, unknown>).message
      if (message && typeof message === 'object') {
        const content = (message as Record<string, unknown>).content
        if (typeof content === 'string') return content.trim()
        if (Array.isArray(content)) {
          return content
            .map(part => part && typeof part === 'object' ? (part as Record<string, unknown>).text : '')
            .filter((part): part is string => typeof part === 'string')
            .join('\n')
            .trim()
        }
      }
    }
  }

  if (Array.isArray(root.output)) {
    const parts: string[] = []
    root.output.forEach(item => {
      if (!item || typeof item !== 'object') return
      const content = (item as Record<string, unknown>).content
      if (!Array.isArray(content)) return
      content.forEach(part => {
        if (!part || typeof part !== 'object') return
        const text = (part as Record<string, unknown>).text
        if (typeof text === 'string') parts.push(text)
      })
    })
    return parts.join('\n').trim()
  }

  return ''
}

export function errorFromTutorProviderResponse(payload: unknown, status: number) {
  if (payload && typeof payload === 'object') {
    const error = (payload as Record<string, unknown>).error
    if (error && typeof error === 'object') {
      const message = (error as Record<string, unknown>).message
      if (typeof message === 'string' && message.trim()) return message.trim()
    }
  }
  return `模型服务返回 HTTP ${status}`
}

export function buildTutorProviderRequest(options: {
  baseUrl: string
  model: string
  mode: TutorMode
  messages: TutorContextMessage[]
}) {
  const endpoint = endpointFor(options.baseUrl)
  const responsesApi = endpoint.endsWith('/responses')
  const recentMessages = options.messages.slice(-16)
  const body = responsesApi
    ? {
        model: options.model.trim(),
        instructions: systemPrompt(options.mode),
        input: recentMessages,
      }
    : {
        model: options.model.trim(),
        messages: [
          { role: 'system', content: systemPrompt(options.mode) },
          ...recentMessages,
        ],
      }

  return { endpoint, body }
}

export async function requestTutorReply(options: {
  baseUrl: string
  model: string
  mode: TutorMode
  messages: TutorContextMessage[]
}) {
  const controller = new AbortController()
  const timeout = globalThis.setTimeout(() => controller.abort(), 50_000)
  try {
    const response = await fetch('/api/tutor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
      signal: controller.signal,
    })
    const payload = await response.json().catch(() => null) as { reply?: unknown; error?: unknown } | null
    if (!response.ok) {
      throw new Error(typeof payload?.error === 'string' ? payload.error : `本地 Tutor 服务返回 HTTP ${response.status}`)
    }
    if (typeof payload?.reply !== 'string' || !payload.reply.trim()) {
      throw new Error('本地 Tutor 服务没有返回可显示的文本')
    }
    return payload.reply.trim()
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Tutor 请求超过 50 秒，已停止等待')
    }
    if (error instanceof TypeError) {
      throw new Error('无法连接本地 Tutor 服务，请确认 vNext 服务正在运行')
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeout)
  }
}

export async function requestTutorEnvironmentStatus() {
  try {
    const response = await fetch('/api/tutor/status')
    const payload = await response.json() as { configured?: unknown; source?: unknown }
    return {
      configured: response.ok && payload.configured === true,
      source: typeof payload.source === 'string' ? payload.source : '',
    }
  } catch {
    return { configured: false, source: '' }
  }
}
