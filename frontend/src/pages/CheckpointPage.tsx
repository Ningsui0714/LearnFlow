import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getLecture, subscribeLectureSSE, saveLecture,
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
  const [checkpointTitle, setCheckpointTitle] = useState('')
  const [selectedText, setSelectedText] = useState('')
  const [showWorkspace, setShowWorkspace] = useState(false)
  const sectionsRef = useRef<Section[]>([])

  useEffect(() => {
    loadLecture()
  }, [cid])

  const loadLecture = async () => {
    setStatus('loading')
    setError('')
    try {
      // Load checkpoint order and title from roadmap
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
        sectionsRef.current = data.sections
        setStatus('published')
      } else {
        setStatus('none')
      }
    } catch {
      setStatus('none')
    }
  }

  const handleGenerate = () => {
    setGenerating(true)
    setSections([])
    sectionsRef.current = []
    setProgress('规划大纲中...')
    setError('')  // 清除旧错误

    const conn = subscribeLectureSSE(
      cid,
      // onSection
      (data) => {
        setError('')  // 有数据来了，清除错误
        const newSection: Section = {
          title: data.title,
          content: data.content,
          keywords: data.keywords || [],
          questions: data.questions || [],
        }
        sectionsRef.current = [...sectionsRef.current, newSection]
        setSections([...sectionsRef.current])
        setProgress(`生成中... ${data.index + 1}/${data.total}`)
      },
      // onDone
      async (data) => {
        setGenerating(false)
        setProgress(`✅ 完成！共 ${data.sections_count} 节`)
        setStatus('published')

        // Save to backend
        try {
          await saveLecture(cid, sectionsRef.current)
        } catch (e: any) {
          console.error('Save failed', e)
          setError('讲义保存失败: ' + (e?.response?.data?.detail || e.message))
        }
      },
      // onError
      (msg) => {
        setGenerating(false)
        setProgress(`❌ ${msg}`)
        setError(msg)
      },
      // onStatus — 进度状态
      (msg) => {
        setProgress(msg)
      },
    )

    // Store for cleanup
    // eslint-disable-next-line react-hooks/rules-of-hooks
    if (typeof window !== 'undefined') {
      ;(window as any).__lf_lecture_close = conn.close
    }
  }

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      const close = (window as any).__lf_lecture_close
      if (close) { close(); (window as any).__lf_lecture_close = null }
    }
  }, [])

  const handleTextSelect = useCallback((text: string) => {
    setSelectedText(text)
  }, [])

  const handleCloseWorkspace = () => {
    setShowWorkspace(false)
    setSelectedText('')
  }

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
            关卡 {checkpointId}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {status !== 'published' && (
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="bg-primary-600 text-white px-4 py-1.5 rounded-lg text-sm
                         hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
            >
              {generating ? '生成中...' : '📝 生成讲义'}
            </button>
          )}
          <button
            onClick={() => navigate(`/projects/${pid}/checkpoints/${cid}/exercises`)}
            className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                       hover:bg-gray-200 transition-colors"
          >
            💻 练习
          </button>
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

      {/* Progress / error bar — 无论 generating 状态都显示 */}
      {(generating || progress) && (
        <div className={`px-6 py-2 text-sm border-b shrink-0 ${
          error ? 'bg-red-50 text-red-700 border-red-200' :
          generating ? 'bg-primary-50 text-primary-700 border-primary-200' :
          progress.includes('❌') ? 'bg-red-50 text-red-700 border-red-200' :
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
                <p className="text-gray-500 text-sm mb-4">{error}</p>
                <p className="text-gray-400 text-xs">
                  请检查 API Key 配置（backend/.env），然后重试。
                  <br />
                  如果问题持续，按 F12 打开开发者工具查看 Console 日志。
                </p>
                <button
                  onClick={handleGenerate}
                  className="mt-4 bg-primary-600 text-white px-5 py-2 rounded-lg text-sm
                             hover:bg-primary-700 transition-colors"
                >
                  重新生成
                </button>
              </div>
            )}

            {/* Loading */}
            {status === 'loading' && (
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
    </div>
  )
}
