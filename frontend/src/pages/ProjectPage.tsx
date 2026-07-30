import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getProject, addSource, listSources, listChunks, processAllSources, getRoadmap } from '../services/api'
import ChatInterface from '../components/workspace/ChatInterface'
import CheckpointGraph from '../components/checkpoint/CheckpointGraph'

interface CheckpointNode {
  id: number
  title: string
  description: string
  order: number
  prerequisites: number[]
  completed: boolean
  chunk_ids: number[]
}

export default function ProjectPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const pid = Number(projectId)

  const [project, setProject] = useState<any>(null)
  const [sources, setSources] = useState<any[]>([])
  const [chunks, setChunks] = useState<any[]>([])
  const [checkpoints, setCheckpoints] = useState<CheckpointNode[]>([])
  const [showAddSource, setShowAddSource] = useState(false)
  const [sourceType, setSourceType] = useState('url')
  const [sourceUrl, setSourceUrl] = useState('')
  const [processing, setProcessing] = useState(false)
  const [activeTab, setActiveTab] = useState<'sources' | 'roadmap'>('sources')
  const [initialTabSet, setInitialTabSet] = useState(false)

  // After loading, switch to roadmap tab if roadmap exists
  useEffect(() => {
    if (!initialTabSet && checkpoints.length > 0) {
      setActiveTab('roadmap')
      setInitialTabSet(true)
    }
  }, [checkpoints, initialTabSet])
  const [notification, setNotification] = useState<string | null>(null)

  useEffect(() => { load() }, [pid])

  const load = async () => {
    try {
      const [p, s, c] = await Promise.all([
        getProject(pid).catch(() => null),
        listSources(pid).catch(() => []),
        listChunks(pid).catch(() => []),
      ])
      setProject(p)
      setSources(s)
      setChunks(c)
      loadRoadmap()
    } catch (e) {
      console.error('Failed to load project', e)
    }
  }

  const loadRoadmap = async () => {
    try {
      const rm = await getRoadmap(pid)
      setCheckpoints(rm.checkpoints || [])
    } catch {
      // No roadmap yet
    }
  }

  const handleAddSource = async () => {
    if (!sourceUrl.trim()) return
    try {
      await addSource(pid, { type: sourceType, url: sourceUrl.trim() })
      setSourceUrl('')
      setShowAddSource(false)
      load()
    } catch (e) {
      console.error('Failed to add source', e)
    }
  }

  const handleProcessAll = async () => {
    setProcessing(true)
    try {
      const result = await processAllSources(pid)
      if (result.errors?.length) {
        setNotification(`处理完成，${result.processed} 个成功，${result.errors.length} 个失败`)
      } else {
        setNotification(`✅ 处理完成！共 ${chunks.length} 个切片`)
      }
      await load()
    } catch (e: any) {
      console.error('Failed to process', e)
      setNotification('❌ 处理失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'))
    } finally {
      setProcessing(false)
      setTimeout(() => setNotification(null), 4000)
    }
  }

  const handleRoadmapUpdate = useCallback((roadmap: any) => {
    if (roadmap.checkpoints) {
      setCheckpoints(roadmap.checkpoints)
      setActiveTab('roadmap')
    }
  }, [])

  const handleCheckpointClick = (checkpointId: number) => {
    navigate(`/projects/${pid}/checkpoints/${checkpointId}`)
  }

  if (!project) return <div className="p-8 text-gray-400">加载中...</div>

  const hasSources = sources.length > 0
  const hasProcessedChunks = chunks.length > 0
  const hasRoadmap = checkpoints.length > 0

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      {notification && (
        <div className="px-6 py-2 text-sm bg-primary-50 text-primary-700 border-b border-primary-200 shrink-0">
          {notification}
        </div>
      )}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-gray-600 mb-1">
          ← 返回
        </button>
        <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
        {project.description && (
          <p className="text-gray-500 text-sm mt-0.5">{project.description}</p>
        )}
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar: Sources */}
        <div className="w-72 border-r border-gray-200 bg-white overflow-y-auto shrink-0 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-sm">参考资料</h2>
            <button
              onClick={() => setShowAddSource(!showAddSource)}
              className="text-primary-600 text-xs hover:text-primary-700"
            >
              + 添加
            </button>
          </div>

          {showAddSource && (
            <div className="mb-3 p-2.5 bg-gray-50 rounded-lg text-sm">
              <select
                value={sourceType}
                onChange={e => setSourceType(e.target.value)}
                className={`w-full border rounded px-2 py-1 text-xs mb-2 ${
                  sourceType === 'github' ? 'border-purple-300 bg-purple-50' : 'border-gray-300'
                }`}
              >
                <option value="url">🌐 网页链接</option>
                <option value="github">📦 GitHub 仓库</option>
              </select>
              {sourceType === 'github' && (
                <div className="text-[10px] text-purple-500 mb-1.5 -mt-1">
                  ⚡ 检测到 GitHub 链接，自动切换为仓库模式
                </div>
              )}
              <input
                type="text"
                placeholder="URL"
                value={sourceUrl}
                onChange={e => {
                  setSourceUrl(e.target.value)
                  // Auto-detect GitHub URLs
                  if (e.target.value.includes('github.com')) {
                    setSourceType('github')
                  }
                }}
                className="w-full border border-gray-300 rounded px-2 py-1 text-xs mb-2"
                onKeyDown={e => e.key === 'Enter' && handleAddSource()}
              />
              <div className="flex gap-1.5">
                <button
                  onClick={handleAddSource}
                  className="bg-primary-600 text-white px-2.5 py-1 text-xs rounded hover:bg-primary-700"
                >
                  添加
                </button>
                <button
                  onClick={() => setShowAddSource(false)}
                  className="text-gray-500 text-xs px-2"
                >
                  取消
                </button>
              </div>
            </div>
          )}

          {sources.length === 0 && (
            <p className="text-gray-400 text-xs text-center py-6">暂无来源</p>
          )}

          <div className="space-y-1.5 mb-3">
            {sources.map(s => (
              <div key={s.id} className="text-xs p-2 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    s.status === 'processed' ? 'bg-green-400' :
                    s.status === 'processing' ? 'bg-yellow-400' :
                    s.status === 'failed' ? 'bg-red-400' : 'bg-gray-300'
                  }`} />
                  <span className="truncate flex-1 text-gray-700">
                    {s.type === 'github' ? '📦' : '🔗'} {s.url?.slice(0, 35)}
                  </span>
                  <span className="text-gray-400">{s.chunk_count || '-'}</span>
                </div>
                {s.status === 'failed' && s.error && (
                  <p className="text-red-400 mt-1 text-[10px] leading-tight">{s.error.slice(0, 80)}</p>
                )}
              </div>
            ))}
          </div>

          {hasSources && (
            <button
              onClick={handleProcessAll}
              disabled={processing}
              className="w-full text-xs bg-primary-50 text-primary-700 py-2 rounded-lg
                         hover:bg-primary-100 disabled:opacity-50 transition-colors mb-3"
            >
              {processing ? '处理中...' : '🔄 处理所有来源'}
            </button>
          )}

          {/* Chunks preview */}
          {chunks.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wider">
                切片 ({chunks.length})
              </h3>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {chunks.map(c => (
                  <div key={c.id} className="text-[11px] p-1.5 bg-gray-50 rounded cursor-pointer hover:bg-gray-100">
                    <span className="text-gray-400 mr-1">#{c.index}</span>
                    <span className="text-gray-600">{c.content.slice(0, 60)}...</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Main content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Tabs: empty state */}
          {!hasProcessedChunks && (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              <div className="text-center">
                <p className="text-4xl mb-2">📚</p>
                <p className="text-sm">添加参考资料并处理，即可开始规划学习路线</p>
              </div>
            </div>
          )}

          {/* With data: show split view */}
          {hasProcessedChunks && (
            <div className="flex-1 flex flex-col">
              {/* Tab buttons */}
              <div className="flex border-b border-gray-200 bg-white shrink-0">
                <button
                  onClick={() => setActiveTab('roadmap')}
                  className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'roadmap'
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  🗺️ 学习路线
                </button>
                <button
                  onClick={() => setActiveTab('sources')}
                  className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'sources'
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  📋 路线规划对话
                </button>
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-hidden">
                {activeTab === 'roadmap' && (
                  <div className="p-4 h-full overflow-y-auto">
                    {hasRoadmap ? (
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <h2 className="font-semibold text-sm text-gray-700">
                            已规划 {checkpoints.filter(c => c.completed).length}/{checkpoints.length} 关
                          </h2>
                        </div>
                        <CheckpointGraph
                          checkpoints={checkpoints}
                          onCheckpointClick={handleCheckpointClick}
                        />
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
                        切换到「路线规划对话」标签页，与 AI 对话生成学习路线
                      </div>
                    )}
                  </div>
                )}

                {activeTab === 'sources' && (
                  <div className="h-full p-4">
                    <ChatInterface
                      projectId={pid}
                      onRoadmapUpdate={handleRoadmapUpdate}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
