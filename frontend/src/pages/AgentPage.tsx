import { useCallback, useEffect, useState } from 'react'
import { Loader2, MessageSquareText } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import TutorPanel from '../components/tutor/TutorPanel'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import { createTutorSession, listTutorSessions } from '../services/api'


export default function AgentPage() {
  const { sessionId: routeSessionId } = useParams()
  const navigate = useNavigate()
  const { openPath } = useWorkspace()
  const numericSessionId = routeSessionId ? Number(routeSessionId) : null
  const [title, setTitle] = useState('新对话')
  const [resolving, setResolving] = useState(!numericSessionId)
  const [error, setError] = useState('')

  useWorkspaceTitle(title, { kind: 'home' })

  useEffect(() => {
    if (numericSessionId) {
      setResolving(false)
      setError('')
      return
    }
    let active = true
    setResolving(true)
    void listTutorSessions('global', 1)
      .then(async sessions => sessions[0] || createTutorSession({
        session_type: 'global',
        create_new: true,
      }))
      .then(session => {
        if (!active) return
        navigate(`/agent/${session.id}`, { replace: true })
      })
      .catch((requestError: any) => {
        if (!active) return
        setError(requestError?.response?.data?.detail || '暂时无法打开对话')
        setResolving(false)
      })
    return () => { active = false }
  }, [navigate, numericSessionId])

  const handleSessionLoaded = useCallback((session: any) => {
    if (session?.title) setTitle(session.title)
  }, [])

  if (resolving || !numericSessionId) {
    return (
      <div className="flex h-full items-center justify-center bg-[#fafaf8] text-sm text-slate-500">
        {error ? (
          <div className="text-center"><MessageSquareText className="mx-auto mb-3 text-slate-400" /><p>{error}</p></div>
        ) : (
          <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" />正在打开对话…</span>
        )}
      </div>
    )
  }

  return (
    <TutorPanel
      key={`standalone-chat:${numericSessionId}`}
      requestedSessionId={numericSessionId}
      standalone
      showSkillPicker
      autoOpenLearningRun={false}
      surfaceKind="conversation"
      surfaceTitle={title}
      surfaceDescription="独立学习对话 · 方法由当前 Session 调用"
      className="h-full rounded-none border-0"
      onSessionLoaded={handleSessionLoaded}
      onProjectChange={project => project?.id && openPath(`/projects/${project.id}`, {
        title: project.name || `项目 ${project.id}`,
        kind: 'project',
        projectId: project.id,
      })}
      onLearningRunCreated={run => run?.id && openPath(`/learn/${run.id}`, {
        title: run.goal || `专注学习 ${run.id}`,
        kind: 'learning_run',
        projectId: run.project_id,
        checkpointId: run.checkpoint_id,
      })}
      onProposalAccepted={project => project?.id && openPath(`/projects/${project.id}`, {
        title: project.name || `项目 ${project.id}`,
        kind: 'project',
        projectId: project.id,
      })}
    />
  )
}
