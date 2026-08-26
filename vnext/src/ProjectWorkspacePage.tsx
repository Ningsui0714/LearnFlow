import { useEffect, useMemo, useRef, useState } from 'react'
import {
  addFormalProjectUrl,
  createFormalProjectFreeSession,
  loadFormalProject,
  processFormalProjectSource,
  removeFormalProjectSource,
  uploadFormalProjectFile,
} from './formal-runtime'
import type { FormalProjectCheckpoint, FormalProjectWorkspace } from './project'
import type { FormalLearningFileRef, FormalLearningTask } from './formal-runtime'

export default function ProjectWorkspacePage({ projectId, onOpenTutor, onOpenCheckpoint, onOpenFree, onOpenFile, onGenerateFiles }: {
  projectId: number
  onOpenTutor: (workspace: FormalProjectWorkspace) => void
  onOpenCheckpoint: (workspace: FormalProjectWorkspace, checkpoint: FormalProjectCheckpoint) => void
  onOpenFree: (workspace: FormalProjectWorkspace, session: { session_id: number; title: string }) => void
  onOpenFile: (file: FormalLearningFileRef) => void
  onGenerateFiles: (task: FormalLearningTask) => Promise<void>
}) {
  const [workspace, setWorkspace] = useState<FormalProjectWorkspace>()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [url, setUrl] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const refresh = async () => {
    try { setWorkspace(await loadFormalProject(projectId)); setError('') }
    catch (error) { setError(error instanceof Error ? error.message : '项目工作台加载失败') }
  }
  useEffect(() => { void refresh() }, [projectId])
  const checkpointNames = useMemo(() => new Map((workspace?.roadmap.checkpoints || []).map(item => [item.id, item.title])), [workspace])

  const addUrl = async () => {
    if (!url.trim()) return
    setBusy('url'); setError('')
    try { await addFormalProjectUrl(projectId, url.trim()); setUrl(''); await refresh() }
    catch (error) { setError(error instanceof Error ? error.message : '来源添加失败') }
    finally { setBusy('') }
  }
  const upload = async (file?: File) => {
    if (!file) return
    setBusy('upload'); setError('')
    try { await uploadFormalProjectFile(projectId, file); await refresh() }
    catch (error) { setError(error instanceof Error ? error.message : '来源上传失败') }
    finally { setBusy(''); if (fileInput.current) fileInput.current.value = '' }
  }
  const mutateSource = async (sourceId: number, action: 'process' | 'remove') => {
    setBusy(`${action}:${sourceId}`); setError('')
    try {
      if (action === 'process') await processFormalProjectSource(projectId, sourceId)
      else await removeFormalProjectSource(projectId, sourceId)
      await refresh()
    } catch (error) { setError(error instanceof Error ? error.message : '来源操作失败') }
    finally { setBusy('') }
  }
  const addFree = async () => {
    if (!workspace) return
    setBusy('free')
    try {
      const session = await createFormalProjectFreeSession(projectId, `${workspace.project.name} · 自由对话`)
      await refresh(); onOpenFree(workspace, session)
    } catch (error) { setError(error instanceof Error ? error.message : '自由对话创建失败') }
    finally { setBusy('') }
  }

  if (!workspace) return <section className="project-workspace-page"><div className="page-loading">{error || '正在打开项目工作台…'}</div></section>
  const files = [...workspace.files.lectures, ...workspace.files.practices]
  return (
    <section className="project-workspace-page">
      <header className="project-workspace-hero">
        <div><span className="eyebrow">PROJECT APPRENTICESHIP</span><h1>{workspace.project.name}</h1><p>{workspace.project.objective}</p></div>
        <div className="project-outcome"><span>真实产物</span><strong>{workspace.project.expected_outcome || '在项目 Tutor 中继续明确'}</strong></div>
      </header>
      {error && <div className="project-error-banner">{error}<button type="button" onClick={() => void refresh()}>重试</button></div>}

      <section className="project-tutor-entry">
        <div><span>PROJECT TUTOR · 学习规划态</span><h2>围绕这个项目规划，而不是泛泛列课程</h2><p>它能读取本项目来源、关卡、学习文件与 scope 内五核；路线只会以待确认卡片出现。</p></div>
        <button type="button" onClick={() => onOpenTutor(workspace)}>进入项目 Tutor</button>
      </section>

      <section className="project-panel checkpoint-panel">
        <header><div><span>CHECKPOINT GRAPH</span><h2>关卡图</h2></div><small>{workspace.roadmap.checkpoints.length ? `${workspace.roadmap.checkpoints.length} 个正式关卡` : '等待项目 Tutor 给出路线并由你确认'}</small></header>
        {workspace.roadmap.checkpoints.length ? (
          <div className="checkpoint-flow">
            {workspace.roadmap.checkpoints.map(checkpoint => (
              <article className={`checkpoint-node checkpoint-${checkpoint.learning_status}`} key={checkpoint.id}>
                <span>关卡 {String(checkpoint.order).padStart(2, '0')}</span>
                <h3>{checkpoint.title}</h3><p>{checkpoint.objective}</p>
                <small>{checkpoint.prerequisites.length ? `前置：${checkpoint.prerequisites.map(id => checkpointNames.get(id) || `#${id}`).join('、')}` : '起始关卡'}</small>
                <div><button type="button" onClick={() => onOpenCheckpoint(workspace, checkpoint)}>进入关卡对话</button>{checkpoint.learning_task && <button type="button" className="secondary" onClick={() => void onGenerateFiles(checkpoint.learning_task!).then(refresh)}>生成讲义与练习</button>}</div>
              </article>
            ))}
          </div>
        ) : <div className="project-empty-state"><strong>这里不会自动塞入假关卡。</strong><p>先进入项目 Tutor，说明时间、基础、产物标准与可用来源；确认路线后会一次性生成关卡对话和学习任务。</p></div>}
      </section>

      <div className="project-two-column">
        <section className="project-panel source-panel">
          <header><div><span>SOURCE CONTROL</span><h2>来源控制</h2></div><small>本地文件 · URL · 后续仓库</small></header>
          <div className="project-source-add"><input value={url} onChange={event => setUrl(event.target.value)} placeholder="添加教材、文档或仓库 URL" /><button type="button" onClick={() => void addUrl()} disabled={busy === 'url'}>添加 URL</button><button type="button" onClick={() => fileInput.current?.click()} disabled={busy === 'upload'}>上传文件</button><input ref={fileInput} hidden type="file" onChange={event => void upload(event.target.files?.[0])} /></div>
          <div className="project-source-list">{workspace.sources.map(source => <article key={source.id}><span>{source.type}</span><div><strong>{source.name}</strong><small>{source.status} · {source.chunk_count} 片段</small></div><button type="button" disabled={busy.includes(String(source.id)) || source.status === 'processed'} onClick={() => void mutateSource(source.id, 'process')}>处理</button><button type="button" className="danger" disabled={busy.includes(String(source.id))} onClick={() => { if (confirm(`移除来源“${source.name}”？`)) void mutateSource(source.id, 'remove') }}>移除</button></article>)}</div>
          {!workspace.sources.length && <p className="project-empty-inline">来源不是必需门槛，但添加后规划与讲义会优先受这些材料约束。</p>}
        </section>

        <section className="project-panel project-files-panel">
          <header><div><span>MANAGED LEARNING FILES</span><h2>讲义与练习总览</h2></div><small>{files.length} 个专属文件</small></header>
          <div className="project-file-list">{files.map(file => <button type="button" key={`${file.kind}:${file.ref}`} onClick={() => onOpenFile(file)}><span>{file.kind === 'lecture' ? '讲义' : '练习'}</span><strong>{file.title}</strong><small>{file.logical_filename} · 打开为标签页</small></button>)}</div>
          {!files.length && <p className="project-empty-inline">在关卡上生成后，文件会留存在这里；对话中的文件卡也能打开标签页或附加为一张纸。</p>}
        </section>
      </div>

      <section className="project-panel free-chat-panel">
        <header><div><span>PROJECT FREE CHATS</span><h2>项目自由对话</h2></div><button type="button" onClick={() => void addFree()} disabled={busy === 'free'}>＋ 新建项目自由对话</button></header>
        <div>{workspace.free_sessions.map(session => <button type="button" key={session.session_id} onClick={() => onOpenFree(workspace, session)}><strong>{session.title}</strong><small>共享项目上下文，但不自动推进关卡</small></button>)}</div>
      </section>
    </section>
  )
}
