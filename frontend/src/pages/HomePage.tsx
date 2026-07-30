import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, createProject } from '../services/api'

interface ProjectSummary {
  id: number
  name: string
  description: string
  source_count: number
  checkpoint_count: number
  completed_count: number
  created_at: string
}

export default function HomePage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const navigate = useNavigate()

  useEffect(() => { loadProjects() }, [])

  const loadProjects = async () => {
    try {
      const data = await listProjects()
      setProjects(data)
    } catch (e) {
      console.error('Failed to load projects', e)
    }
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    try {
      const project = await createProject({ name: name.trim(), description })
      navigate(`/projects/${project.id}`)
    } catch (e) {
      console.error('Failed to create project', e)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">学习项目</h1>
        <p className="text-gray-500 mb-8">选择一个项目开始学习，或创建一个新的学习路线。</p>

        {/* Create card */}
        <button
          onClick={() => setShowNew(!showNew)}
          className="w-full border-2 border-dashed border-gray-300 rounded-xl p-6 text-center
                     hover:border-primary-400 hover:bg-primary-50 transition-all mb-6"
        >
          <span className="text-3xl text-gray-400">+</span>
          <p className="text-gray-500 mt-1">新建学习项目</p>
        </button>

        {showNew && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
            <h2 className="text-lg font-semibold mb-4">新建项目</h2>
            <input
              type="text" placeholder="项目名称（如：深度学习）"
              value={name} onChange={e => setName(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-2 mb-3 focus:outline-none focus:ring-2 focus:ring-primary-400"
              autoFocus
            />
            <textarea
              placeholder="项目描述（选填）"
              value={description} onChange={e => setDescription(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-primary-400 resize-none"
              rows={3}
            />
            <div className="flex gap-3">
              <button onClick={handleCreate}
                className="bg-primary-600 text-white px-6 py-2 rounded-lg hover:bg-primary-700 transition-colors"
              >创建</button>
              <button onClick={() => setShowNew(false)}
                className="text-gray-500 px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors"
              >取消</button>
            </div>
          </div>
        )}

        {/* Project list */}
        {projects.length === 0 && !showNew && (
          <div className="text-center text-gray-400 py-16">
            <p className="text-5xl mb-4">📚</p>
            <p>还没有项目，点击上方按钮创建一个</p>
          </div>
        )}

        <div className="grid gap-4">
          {projects.map(p => (
            <div
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 cursor-pointer
                         hover:border-primary-300 hover:shadow-md transition-all"
            >
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{p.name}</h3>
                  {p.description && <p className="text-gray-500 text-sm mt-1">{p.description}</p>}
                </div>
                <div className="flex gap-4 text-sm text-gray-500 shrink-0">
                  <span>📄 {p.source_count} 来源</span>
                  <span>🎯 {p.completed_count}/{p.checkpoint_count} 关卡</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
