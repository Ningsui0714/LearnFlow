import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// ── Project ──
export const createProject = (data: { name: string; description?: string; user_level?: string }) =>
  api.post('/projects', data).then(r => r.data)

export const listProjects = () =>
  api.get('/projects').then(r => r.data)

export const getProject = (id: number) =>
  api.get(`/projects/${id}`).then(r => r.data)

// ── Source ──
export const addSource = (projectId: number, data: { type: string; url?: string }) =>
  api.post(`/projects/${projectId}/sources`, data).then(r => r.data)

export const listSources = (projectId: number) =>
  api.get(`/projects/${projectId}/sources`).then(r => r.data)

export const processSource = (projectId: number, sourceId: number) =>
  api.post(`/projects/${projectId}/sources/${sourceId}/process`).then(r => r.data)

export const processAllSources = (projectId: number) =>
  api.post(`/projects/${projectId}/sources/process-all`).then(r => r.data)

export const startImageCaptioning = (projectId: number, sourceId: number, limit?: number, mode: 'free' | 'api' = 'free') =>
  api.post(`/projects/${projectId}/sources/${sourceId}/images/caption`, { limit, mode }).then(r => r.data)

// ── Chunk ──
export const listChunks = (projectId: number) =>
  api.get(`/projects/${projectId}/chunks`).then(r => r.data)

// ── Roadmap ──
export const getRoadmap = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap`).then(r => r.data)

// ── Agent ──
export const sendAgentMessage = (projectId: number, data: { message: string; history: any[] }) =>
  api.post(`/projects/${projectId}/roadmap/chat`, data).then(r => r.data)

export const getRoadmapHistory = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap/history`).then(r => r.data)

// ── Lecture (Phase 2) ──
export const getLecture = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture`).then(r => r.data)

// SSE stream for lecture generation — uses fetch for proper error handling
// Deprecated in favor of task-based generation (createLectureTask + lectureTaskEventsUrl)
export function subscribeLectureSSE(
  checkpointId: number,
  onSection: (data: any) => void,
  onDone: (data: any) => void,
  onError: (msg: string) => void,
  onStatus?: (msg: string) => void,
) {
  let aborted = false
  let firstData = false

  // Timeout: if no data within 90s, report error
  const timeoutId = setTimeout(() => {
    if (!firstData && !aborted) {
      aborted = true
      onError('生成超时（90s）：AI 模型响应较慢，请稍后重试。如果持续出现，检查 API Key 和网络连接。')
    }
  }, 90000)

  const abort = () => {
    aborted = true
    clearTimeout(timeoutId)
  }

  const doFetch = async () => {
    try {
      const resp = await fetch(`/api/checkpoints/${checkpointId}/lecture/generate`)

      if (!resp.ok) {
        clearTimeout(timeoutId)
        const body = await resp.text().catch(() => '')
        onError(`服务器错误 (${resp.status}): ${body.slice(0, 200)}`)
        return
      }

      firstData = true
      clearTimeout(timeoutId)

      const reader = resp.body?.getReader()
      if (!reader) {
        onError('响应无数据流')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (!aborted) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const event of events) {
          for (const line of event.split('\n')) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === 'section') {
                  onSection(data)
                } else if (data.type === 'status') {
                  if (onStatus) onStatus(data.message || '')
                } else if (data.type === 'done') {
                  onDone(data)
                  return
                } else if (data.type === 'error') {
                  onError(data.message || '未知错误')
                  return
                }
              } catch { /* skip parse errors */ }
            }
          }
        }
      }
    } catch (e: any) {
      if (!aborted) {
        onError(`连接失败: ${e.message || '网络错误'}`)
      }
    }
  }

  doFetch()

  return { close: abort }
}

export const saveLecture = (checkpointId: number, sections: any[]) =>
  api.post(`/checkpoints/${checkpointId}/lecture/save`, { sections }).then(r => r.data)

// ── Tasks (T1: background jobs) ──
export const createLectureTask = (checkpointId: number, mode: 'fresh' | 'resume' = 'fresh') =>
  api.post(`/checkpoints/${checkpointId}/lecture/generate`, { mode }).then(r => r.data)

export const getActiveLectureTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/task`).then(r => r.data)

export const listLectureVersions = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/versions`).then(r => r.data)

export const rollbackLecture = (checkpointId: number, versionId: number) =>
  api.post(`/checkpoints/${checkpointId}/lecture/rollback`, { version_id: versionId }).then(r => r.data)

export const getTaskStatus = (taskId: number) =>
  api.get(`/tasks/${taskId}`).then(r => r.data)

export const cancelTask = (taskId: number) =>
  api.post(`/tasks/${taskId}/cancel`).then(r => r.data)

export const lectureTaskEventsUrl = (taskId: number) => `/api/tasks/${taskId}/events`

export const askQuestion = (checkpointId: number, data: { selection: string; question: string; history: any[]; action?: string }) =>
  api.post(`/checkpoints/${checkpointId}/ask`, data).then(r => r.data)

// ── T9: anchored notes ──
export const listNotes = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/notes`).then(r => r.data)

export const createNote = (checkpointId: number, data: { section_index: number; selection: string; note: string }) =>
  api.post(`/checkpoints/${checkpointId}/notes`, data).then(r => r.data)

export const updateNote = (noteId: number, note: string) =>
  api.put(`/notes/${noteId}`, { note }).then(r => r.data)

export const deleteNote = (noteId: number) =>
  api.delete(`/notes/${noteId}`).then(r => r.data)

// ── Phase 3: Exercises & Code ──
export const listExercises = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/exercises`).then(r => r.data)

export const getExercise = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}`).then(r => r.data)

export const runCode = (code: string, exerciseId?: number) => {
  const url = exerciseId ? `/exercises/${exerciseId}/run` : '/exercises/run'
  return api.post(url, { code }).then(r => r.data)
}

export const reviewCode = (exerciseId: number, code: string, selection?: string) =>
  api.post(`/exercises/${exerciseId}/review`, { code, selection }).then(r => r.data)

export const askCodeQuestion = (data: { code: string; selection: string; question: string; context?: string }) =>
  api.post('/code/ask', data).then(r => r.data)

export default api
