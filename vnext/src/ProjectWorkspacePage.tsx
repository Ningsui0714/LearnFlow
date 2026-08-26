import { useEffect, useRef, useState } from 'react'
import { loadFormalProject } from './formal-runtime'
import type { FormalProjectCheckpoint, FormalProjectWorkspace } from './project'
import type { FormalLearningFileRef, FormalLearningTask } from './formal-runtime'

export default function ProjectWorkspacePage({ projectId, onOpenTutor }: {
  projectId: number
  onOpenTutor: (workspace: FormalProjectWorkspace) => void
  onOpenCheckpoint: (workspace: FormalProjectWorkspace, checkpoint: FormalProjectCheckpoint) => void
  onOpenFree: (workspace: FormalProjectWorkspace, session: { session_id: number; title: string }) => void
  onOpenFile: (file: FormalLearningFileRef) => void
  onGenerateFiles: (task: FormalLearningTask) => Promise<void>
}) {
  const [workspace, setWorkspace] = useState<FormalProjectWorkspace>()
  const [error, setError] = useState('')
  const openedProject = useRef<number>()
  const refresh = async () => {
    try { setWorkspace(await loadFormalProject(projectId)); setError('') }
    catch (error) { setError(error instanceof Error ? error.message : '项目工作台加载失败') }
  }
  useEffect(() => { void refresh() }, [projectId])
  useEffect(() => {
    if (!workspace || openedProject.current === workspace.project.id) return
    openedProject.current = workspace.project.id
    onOpenTutor(workspace)
  }, [onOpenTutor, workspace])

  return <section className="project-workspace-page project-workspace-redirect"><div className="page-loading">{error || `正在进入 ${workspace?.project.name || '项目'} Tutor…`}</div></section>
}
