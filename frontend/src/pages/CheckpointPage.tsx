import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getLecture, saveLecture,
  createLectureTask, getActiveLectureTask, cancelTask, lectureTaskEventsUrl,
  listLectureVersions, rollbackLecture,
} from '../services/api'
import LectureRenderer from '../components/lecture/LectureRenderer'
import BottomWorkspace from '../components/workspace/BottomWorkspace'

interface Section {
  title: string
  content: string
  keywords?: string[]
  questions?: string[]
}

export default function CheckpointPage() {
  const { projectId, checkpointId } = useParams()
  const navigate = useNavigate()
  const cid = Number(checkpointId)
  const pid = Number(projectId)

  const [sections, setSections] = useState<Section[]>([])
  const [status, setStatus] = useState<'loading' | 'none' | 'draft' | 'published'>('loading')
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [taskError, setTaskError] = useState<any>(null)  // structured {code, message, guidance}
  const [taskId, setTaskId] = useState<number | null>(null)
  const [checkpointTitle, setCheckpointTitle] = useState('')
  const [selectedText, setSelectedText] = useState('')
  const [showWorkspace, setShowWorkspace] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [versionLoading, setVersionLoading] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  // ── Load lecture on mount ──
  useEffect(() => {
    loadLecture()
    // Recover: if a generation task is still running, re-subscribe
    getActiveLectureTask(cid).then((snap: any) => {
      if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
        setTaskId(snap.task_id)
        setGenerating(true)
        setProgress(snap.progress?.message || '生成中...')
        if (snap.sections?.length) setSections(snap.sections)
        subscribeTask(snap.task_id)
      } else if (snap?.status === 'failed' && snap.sections?.length) {
        setTaskError(snap.error)
        setError(snap.error?.message || '上次生成失败')
      }
    }).catch(() => {})
    return () => closeEventSource()
  }, [cid])

  const closeEventSource = () => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
  }

  const loadLecture = async () => {
    setStatus('loading')
    setError('')
    try {
      try {
        const rmResp = await fetch(`/api/projects/${pid}/roadmap`)
        const rm = await rmResp.json()
        const cp = (rm.checkpoints || []).find((c: any) => c.id === cid)
        if (cp) {
          setCheckpointTitle(`#${cp.order} ${cp.title}`)
        }
      } catch {}

      const data = await getLecture(cid)
      if (data.sections && data.sections.length > 0) {
        setSections(data.sections)
        setStatus(data.status || 'published')
      } else {
        setSections([])
        setStatus('none')
      }
    } catch {
      setStatus('none')
    }
  }

  // ── Task subscription (EventSource auto-reconnects on network drops) ──
  const subscribeTask = (id: number) => {
    closeEventSource()
    const es = new EventSource(lectureTaskEventsUrl(id))
    esRef.current = es

    es.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data)
        if (snap.type === 'snapshot') {
          if (snap.sections) setSections(snap.sections)
          if (snap.progress?.message) setProgress(snap.progress.message)

          if (snap.status === 'completed') {
            setGenerating(false)
            setTaskError(null)
            setError('')
            setProgress(`✅ ${snap.progress?.message || '完成！'}`)
            setStatus('published')
            // Sections already applied from snapshot; sync status
            closeEventSource()
            saveLecture(cid, snap.sections || []).catch(() => {})
          } else if (snap.status === 'failed') {
            setGenerating(false)
            setTaskError(snap.error)
            setError(snap.error?.message || '生成失败')
            setProgress(`❌ ${snap.error?.guidance || '生成失败'}`)
            if (snap.sections?.length) setStatus('draft')
            closeEventSource()
          } else if (snap.status === 'canceled') {
            setGenerating(false)
            setProgress('已取消')
            setStatus(snap.sections?.length ? 'draft' : 'none')
            closeEventSource()
          }
        }
      } catch {}
    }

    es.onerror = () => {
      // EventSource retries automatically; only surface if connection is dead
      // and we're still marked as generating (task may still be running server-side)
    }
  }

  const handleGenerate = (mode: 'fresh' | 'resume' = 'fresh') => {
    setGenerating(true)
    setError('')
    setTaskError(null)
    if (mode === 'fresh') {
      setSections([])
      setProgress('排队中...')
    } else {
      setProgress('从上次进度续生成...')
    }

    createLectureTask(cid, mode)
      .then((res: any) => {
        setTaskId(res.task_id)
        if (res.already_running) {
          setProgress('检测到进行中的任务，正在恢复...')
        }
        subscribeTask(res.task_id)
      })
      .catch((e: any) => {
        setGenerating(false)
        const msg = e?.response?.data?.detail || e.message
        setError(msg)
        setProgress(`❌ ${msg}`)
      })
  }

  const handleCancel = async () => {
    if (!taskId) return
    try {
      await cancelTask(taskId)
      setProgress('正在取消...')
    } catch {}
  }

  // ── T5: version history + rollback ──
  const openVersions = async () => {
    setShowVersions(true)
    setVersionLoading(true)
    try {
      const data = await listLectureVersions(cid)
      setVersions(data || [])
    } catch {
      setVersions([])
    }
    setVersionLoading(false)
  }

  const handleRollback = async (versionId: number, preview: string) => {
    if (!window.confirm(`确定回滚到版本「${preview || versionId}」？当前讲义会被存档后替换。`)) return
    setVersionLoading(true)
    try {
      await rollbackLecture(cid, versionId)
      await loadLecture()
      setShowVersions(false)
      setProgress('✅ 已回滚到历史版本')
    } catch (e: any) {
      setError('回滚失败: ' + (e?.response?.data?.detail || e.message))
    }
    setVersionLoading(false)
  }

  const handleTextSelect = useCallback((text: string) => {
    setSelectedText(text)
  }, [])

  const handleCloseWorkspace = () => {
    setShowWorkspace(false)
    setSelectedText('')
  }

  const canResume = status === 'draft' && sections.length > 0 && !generating

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(`/projects/${pid}`)}
            className="text-sm text-gray-400 hover:text-gray-600">
            ← 返回项目
          </button>
          <span className="text-gray-300">|</span>
          <h1 className="text-lg font-semibold text-gray-900">
            {checkpointTitle || `关卡 ${checkpointId}`}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {status !== 'published' && !generating && (
            <>
              <button
                onClick={() => handleGenerate('fresh')}
                className="bg-primary-600 text-white px-4 py-1.5 rounded-lg text-sm
                           hover:bg-primary-700 transition-colors"
              >
                📝 生成讲义
              </button>
              {canResume && (
                <button
                  onClick={() => handleGenerate('resume')}
                  className="bg-amber-500 text-white px-4 py-1.5 rounded-lg text-sm
                             hover:bg-amber-600 transition-colors"
                >
                  ⏯ 续生成（{sections.length} 节）
                </button>
              )}
            </>
          )}
          {generating && (
            <button
              onClick={handleCancel}
              className="bg-red-50 text-red-600 px-4 py-1.5 rounded-lg text-sm
                         hover:bg-red-100 transition-colors"
            >
              ⏹ 取消
            </button>
          )}
          <button
            onClick={() => navigate(`/projects/${pid}/checkpoints/${cid}/exercises`)}
            className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                       hover:bg-gray-200 transition-colors"
          >
            💻 练习
          </button>
          {sections.length > 0 && !generating && (
            <button
              onClick={openVersions}
              className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                         hover:bg-gray-200 transition-colors"
            >
              🕘 版本
            </button>
          )}
          {selectedText && !showWorkspace && (
            <button
              onClick={() => setShowWorkspace(true)}
              className="bg-primary-50 text-primary-700 px-3 py-1.5 rounded-lg text-sm
                         hover:bg-primary-100 transition-colors"
            >
              💬 追问选中内容
            </button>
          )}
        </div>
      </div>

      {/* Progress / error bar */}
      {(generating || progress) && (
        <div className={`px-6 py-2 text-sm border-b shrink-0 ${
          error ? 'bg-red-50 text-red-700 border-red-200' :
          generating ? 'bg-primary-50 text-primary-700 border-primary-200' :
          progress.includes('❌') || progress.includes('已取消') ? 'bg-amber-50 text-amber-700 border-amber-200' :
          'bg-green-50 text-green-700 border-green-200'
        }`}>
          <div className="flex items-center gap-2">
            {generating && !error && (
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
            )}
            {progress}
          </div>
        </div>
      )}

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto">
            {/* Empty state */}
            {status === 'none' && sections.length === 0 && !error && (
              <div className="text-center text-gray-400 py-20">
                <p className="text-5xl mb-4">📖</p>
                <p className="text-lg mb-2">此关卡还没有讲义</p>
                <p className="text-sm">点击右上角「📝 生成讲义」，AI 将根据参考资料生成结构化讲义</p>
              </div>
            )}

            {/* Persistent error in content area */}
            {error && sections.length === 0 && (
              <div className="text-center py-16">
                <p className="text-4xl mb-3">⚠️</p>
                <p className="text-red-600 font-medium mb-2">讲义生成失败</p>
                <p className="text-gray-500 text-sm mb-2">{error}</p>
                {taskError?.guidance && (
                  <p className="text-gray-400 text-xs mb-4">{taskError.guidance}</p>
                )}
                <button
                  onClick={() => handleGenerate('fresh')}
                  className="mt-4 bg-primary-600 text-white px-5 py-2 rounded-lg text-sm
                             hover:bg-primary-700 transition-colors"
                >
                  重新生成
                </button>
              </div>
            )}

            {/* Partial failure banner (some sections saved) */}
            {error && sections.length > 0 && (
              <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                <p className="font-medium mb-1">⚠️ 生成中断：已保留 {sections.length} 节内容</p>
                <p className="text-xs text-amber-700 mb-2">{taskError?.guidance || error}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleGenerate('resume')}
                    className="bg-amber-500 text-white px-3 py-1 rounded text-xs hover:bg-amber-600"
                  >
                    ⏯ 续生成
                  </button>
                  <button
                    onClick={() => handleGenerate('fresh')}
                    className="bg-white border border-amber-300 text-amber-700 px-3 py-1 rounded text-xs hover:bg-amber-50"
                  >
                    重新生成
                  </button>
                </div>
              </div>
            )}

            {/* Loading */}
            {status === 'loading' && sections.length === 0 && (
              <div className="text-center text-gray-400 py-20">
                <span className="animate-pulse">加载中...</span>
              </div>
            )}

            {/* Lecture content */}
            {sections.length > 0 && (
              <LectureRenderer
                sections={sections}
                onSelect={handleTextSelect}
              />
            )}
          </div>
        </div>

        {/* Bottom workspace */}
        {showWorkspace && (
          <BottomWorkspace
            checkpointId={cid}
            selectedText={selectedText}
            onClose={handleCloseWorkspace}
          />
        )}
      </div>

      {/* Version history modal (T5) */}
      {showVersions && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
             onClick={() => setShowVersions(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[480px] max-h-[70vh] flex flex-col"
               onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
              <h3 className="font-semibold text-gray-800">🕘 讲义版本历史</h3>
              <button onClick={() => setShowVersions(false)}
                      className="text-gray-400 hover:text-gray-600 text-sm px-1">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {versionLoading && <p className="text-gray-400 text-sm text-center py-6">加载中...</p>}
              {!versionLoading && versions.length === 0 && (
                <p className="text-gray-400 text-sm text-center py-6">
                  暂无历史版本。重新生成讲义时会自动保存上一版。
                </p>
              )}
              {versions.map((v: any, i: number) => (
                <div key={v.id} className="border border-gray-100 rounded-lg p-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-gray-800 font-medium truncate">
                      {v.preview || `版本 #${v.id}`}
                    </p>
                    <p className="text-xs text-gray-400">
                      {v.sections_count} 节 · {v.reason === 'regenerate_before' ? '重新生成前自动存档' : v.reason === 'before_rollback' ? '回滚前存档' : v.reason}
                      {v.created_at ? ` · ${new Date(v.created_at).toLocaleString('zh-CN')}` : ''}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRollback(v.id, v.preview)}
                    disabled={versionLoading}
                    className="bg-amber-50 text-amber-700 border border-amber-200 px-3 py-1 rounded-lg text-xs
                               hover:bg-amber-100 disabled:opacity-50 shrink-0"
                  >
                    回滚
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
