import { useMemo, useRef, useState, type DragEvent, type FormEvent, type MouseEvent } from 'react'
import { runProjectPluginWorkflow, type ProjectPluginSurface } from './plugin-runtime'

type LearningTask = {
  id: string
  title: string
  source_title: string
  context: string
  objective: string
  tools: string[]
  safety: string[]
  acceptance: string[]
  status: string
}

type TaskStep = {
  id: string
  order: number
  title: string
  operation: string
  deliverable: string
  acceptance: string
  prerequisites: string[]
  knowledge_ids: string[]
  skill_ids: string[]
  resource_ids: string[]
  review_state?: string
}

type KnowledgePoint = { id: string; title: string; summary: string }
type SkillPoint = { id: string; title: string; summary: string }
type Relation = { id: string; relation: string; source_id: string; target_id: string; reason: string }
type Resource = { id: string; title: string; provider: string; query: string; url: string }
type ReviewNote = { id: string; target_id: string; quote: string; note: string; status: string }

type TaskDocument = {
  task: LearningTask
  steps: TaskStep[]
  knowledge: KnowledgePoint[]
  skills: SkillPoint[]
  relations: Relation[]
  resources: Resource[]
  notes: ReviewNote[]
  snapshotId?: number
  snapshotVersion?: number
  validation: Record<string, unknown>
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown, fallback = '') {
  return typeof value === 'string' ? value.trim() : fallback
}

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter(item => typeof item === 'string').map(item => item.trim()).filter(Boolean) : []
}

function objects(value: unknown) {
  return Array.isArray(value) ? value.filter(item => item && typeof item === 'object' && !Array.isArray(item)).map(record) : []
}

function safeHttpUrl(value: unknown) {
  if (typeof value !== 'string') return ''
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : ''
  } catch { return '' }
}

function taskDocumentFromSurface(surface?: ProjectPluginSurface): TaskDocument | null {
  const snapshot = record(surface?.data?.snapshot)
  const components = record(snapshot.components)
  const taskDocument = record(components['task-document'])
  const knowledgeMap = record(components['knowledge-map'])
  const reviewNotes = record(components['review-notes'])
  const rawTask = record(taskDocument.task)
  const rawSteps = objects(taskDocument.steps)
  if (!rawTask.id || !rawSteps.length) return null
  const task: LearningTask = {
    id: text(rawTask.id), title: text(rawTask.title, '学习型工作任务'),
    source_title: text(rawTask.source_title), context: text(rawTask.context),
    objective: text(rawTask.objective), tools: strings(rawTask.tools),
    safety: strings(rawTask.safety), acceptance: strings(rawTask.acceptance),
    status: text(rawTask.status, 'reviewable'),
  }
  const steps = rawSteps.map((item, index): TaskStep => ({
    id: text(item.id, `step-${index + 1}`), order: Number(item.order) || index + 1,
    title: text(item.title, `步骤 ${index + 1}`), operation: text(item.operation),
    deliverable: text(item.deliverable), acceptance: text(item.acceptance),
    prerequisites: strings(item.prerequisites), knowledge_ids: strings(item.knowledge_ids),
    skill_ids: strings(item.skill_ids), resource_ids: strings(item.resource_ids),
    review_state: text(item.review_state),
  })).sort((left, right) => left.order - right.order)
  const knowledge = objects(knowledgeMap.knowledge_points).map(item => ({
    id: text(item.id), title: text(item.title), summary: text(item.summary),
  })).filter(item => item.id)
  const skills = objects(knowledgeMap.skill_points).map(item => ({
    id: text(item.id), title: text(item.title), summary: text(item.summary),
  })).filter(item => item.id)
  const relations = objects(knowledgeMap.relations).map(item => ({
    id: text(item.id), relation: text(item.relation), source_id: text(item.source_id),
    target_id: text(item.target_id), reason: text(item.reason),
  })).filter(item => item.id)
  const resources = objects(knowledgeMap.resources).map(item => ({
    id: text(item.id), title: text(item.title), provider: text(item.provider, '学习资源'),
    query: text(item.query), url: safeHttpUrl(item.url),
  })).filter(item => item.id)
  const notes = objects(reviewNotes.notes).map(item => ({
    id: text(item.id), target_id: text(item.target_id), quote: text(item.quote),
    note: text(item.note), status: text(item.status),
  })).filter(item => item.id)
  return {
    task, steps, knowledge, skills, relations, resources, notes,
    snapshotId: Number(snapshot.id) || undefined,
    snapshotVersion: Number(snapshot.version) || undefined,
    validation: record(snapshot.validation),
  }
}

function downloadJson(name: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function LearningTaskPluginWorkspace({ projectId, surface, onRefresh, onOpenPersonalized }: {
  projectId: number
  surface?: ProjectPluginSurface
  onRefresh: () => Promise<ProjectPluginSurface | undefined>
  onOpenPersonalized: () => void
}) {
  const document = useMemo(() => taskDocumentFromSurface(surface), [surface])
  const [selectedStepId, setSelectedStepId] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [quote, setQuote] = useState('')
  const [note, setNote] = useState('')
  const [taskTitle, setTaskTitle] = useState('')
  const [createPanelOpen, setCreatePanelOpen] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [draggedStepId, setDraggedStepId] = useState('')
  const [handoffStatus, setHandoffStatus] = useState('')
  const documentArea = useRef<HTMLDivElement>(null)
  const selectedStep = document?.steps.find(step => step.id === selectedStepId) || document?.steps[0]
  const stepKnowledge = document?.knowledge.filter(item => selectedStep?.knowledge_ids.includes(item.id)) || []
  const stepSkills = document?.skills.filter(item => selectedStep?.skill_ids.includes(item.id)) || []
  const stepRelations = document?.relations.filter(item => item.source_id === selectedStep?.id) || []
  const stepResources = document?.resources.filter(item => selectedStep?.resource_ids.includes(item.id)) || []
  const stepNotes = document?.notes.filter(item => item.target_id === selectedStep?.id || item.target_id === 'document') || []

  const runAndRefresh = async (workflow: string, input: Record<string, unknown>) => {
    if (!surface) return
    setBusy(workflow)
    setError('')
    try {
      await runProjectPluginWorkflow(projectId, surface, workflow, input)
      await onRefresh()
    } catch (error) {
      setError(error instanceof Error ? error.message : '插件运行失败')
      throw error
    } finally { setBusy('') }
  }

  const generate = async (event: FormEvent) => {
    event.preventDefault()
    const title = taskTitle.trim()
    if (!title) return
    try {
      await runAndRefresh('generate', { task_title: title })
      setTaskTitle('')
      setSelectedStepId('')
      setCreatePanelOpen(false)
    } catch { /* displayed above */ }
  }

  const captureSelection = (_event: MouseEvent<HTMLDivElement>) => {
    const selection = globalThis.getSelection()
    const selected = selection?.toString().replace(/\s+/g, ' ').trim() || ''
    if (!selected || !documentArea.current || !selection?.anchorNode || !documentArea.current.contains(selection.anchorNode)) return
    setQuote(selected.slice(0, 1_000))
    setDrawerOpen(true)
  }

  const saveNote = async (event: FormEvent) => {
    event.preventDefault()
    if (!note.trim()) return
    try {
      await runAndRefresh('revise', {
        target_id: selectedStep?.id || 'document', quote, note: note.trim(),
      })
      setNote('')
      setQuote('')
    } catch { /* displayed above */ }
  }

  const reorder = async (targetId: string) => {
    if (!document || !draggedStepId || draggedStepId === targetId) return
    const ids = document.steps.map(step => step.id)
    const from = ids.indexOf(draggedStepId)
    const to = ids.indexOf(targetId)
    if (from < 0 || to < 0) return
    ids.splice(to, 0, ids.splice(from, 1)[0])
    setDraggedStepId('')
    try { await runAndRefresh('revise', { target_id: draggedStepId, step_order: ids }) } catch { /* displayed above */ }
  }

  const openPersonalized = async (knowledgeId: string) => {
    setHandoffStatus('正在准备知识点级启动包…')
    try {
      await runAndRefresh('handoff', { knowledge_id: knowledgeId })
      setHandoffStatus('启动包已准备，可进入个性化学习。')
      onOpenPersonalized()
    } catch { setHandoffStatus('启动包准备失败，请稍后重试。') }
  }

  if (!surface) return <div className="page-loading">正在读取学习型任务插件…</div>
  if (!document) {
    return (
      <section className="learning-task-plugin-page learning-task-plugin-empty">
        <div className="learning-task-plugin-empty-card">
          <span className="learning-task-plugin-mark">✦</span>
          <p className="learning-task-plugin-kicker">LEARNING TASK COMPILER</p>
          <h1>把真实工作任务转成可执行步骤</h1>
          <p>输入一个明确的计算机专业工作任务。系统会生成按作业先后排列的步骤、产物、验收依据，以及每一步需要的知识与技能。</p>
          <form onSubmit={generate}>
            <label htmlFor="learning-task-title">真实工作任务</label>
            <div><input id="learning-task-title" value={taskTitle} onChange={event => setTaskTitle(event.target.value)} placeholder="例如：实现 Unity 第三人称摄像机跟随与遮挡处理" autoFocus /><button type="submit" disabled={busy === 'generate' || !taskTitle.trim()}>{busy === 'generate' ? '生成中…' : '生成任务步骤'}</button></div>
          </form>
          <div className="learning-task-plugin-examples">
            {['配置交换机 VLAN 与 Trunk 并验收连通性', '实现 Java REST 接口并完成自动化测试', '实现 Unity 摄像机跟随与遮挡处理'].map(item => <button type="button" key={item} onClick={() => setTaskTitle(item)}>{item}</button>)}
          </div>
          {error && <p className="learning-task-plugin-error" role="alert">{error}</p>}
        </div>
      </section>
    )
  }

  return (
    <section className={`learning-task-plugin-page${drawerOpen ? ' annotation-open' : ''}`}>
      <header className="learning-task-plugin-header">
        <div>
          <span className="learning-task-plugin-mark">✦</span>
          <div><p>学习型任务 · 快照 v{document.snapshotVersion || 1}</p><h1>{document.task.title}</h1></div>
        </div>
        <div className="learning-task-plugin-actions">
          <span className="learning-task-plugin-ready"><i />已生成 · {document.steps.length} 个步骤</span>
          <button
            type="button"
            className="learning-task-create-trigger"
            onClick={() => setCreatePanelOpen(value => !value)}
            aria-expanded={createPanelOpen}
            aria-controls="learning-task-create-panel"
          >{createPanelOpen ? '收起输入' : '＋ 新建任务'}</button>
          <button type="button" onClick={() => setDrawerOpen(value => !value)} aria-expanded={drawerOpen}>批注复核{document.notes.length ? ` ${document.notes.length}` : ''}</button>
          <button type="button" onClick={() => downloadJson(`${document.task.source_title || 'learning-task'}.json`, document)}>导出 JSON</button>
        </div>
      </header>

      {createPanelOpen && <form id="learning-task-create-panel" className="learning-task-create-panel" onSubmit={generate} aria-label="生成新的学习型任务">
        <label htmlFor="learning-task-new-title">新的真实工作任务</label>
        <div>
          <input
            id="learning-task-new-title"
            value={taskTitle}
            onChange={event => setTaskTitle(event.target.value)}
            placeholder="例如：实现 Python FastAPI 文件上传服务并完成接口测试"
            autoFocus
          />
          <button type="submit" disabled={busy === 'generate' || !taskTitle.trim()}>{busy === 'generate' ? '正在生成…' : '生成新任务'}</button>
          <button type="button" onClick={() => { setCreatePanelOpen(false); setTaskTitle('') }} disabled={busy === 'generate'}>取消</button>
        </div>
      </form>}

      <div className="learning-task-evidence-strip">
        <span><i>✓</i>任务对象已锁定</span><span><i>✓</i>步骤产物可检查</span><span><i>✓</i>知识技能跟随步骤</span><strong>规划产物不等于掌握证据</strong>
      </div>
      {error && <div className="learning-task-plugin-error" role="alert">{error}</div>}

      <div className="learning-task-plugin-workspace">
        <nav className="learning-task-step-rail" aria-label="任务步骤；可拖动调整顺序">
          <header><span>WORK STEPS</span><strong>任务步骤</strong><small>拖动可调整先后顺序</small></header>
          <ol>
            {document.steps.map(step => <li key={step.id}>
              <button
                type="button" draggable={!busy}
                className={step.id === selectedStep?.id ? 'active' : ''}
                onClick={() => setSelectedStepId(step.id)}
                onDragStart={() => setDraggedStepId(step.id)}
                onDragOver={(event: DragEvent) => event.preventDefault()}
                onDrop={() => { void reorder(step.id) }}
              >
                <span>{String(step.order).padStart(2, '0')}</span>
                <div><strong>{step.title}</strong><small>{step.deliverable}</small></div>
                {step.review_state === 'pending_review' && <i title="待复核">•</i>}
              </button>
            </li>)}
          </ol>
          <footer><span>{document.steps.length} 个步骤</span><i>→</i><strong>可验收交付</strong></footer>
        </nav>

        <main className="learning-task-document-area" ref={documentArea} onMouseUp={captureSelection}>
          <div className="learning-task-breadcrumb"><span>{document.task.source_title}</span><i>›</i><strong>{selectedStep?.title}</strong></div>
          <article className="learning-task-step-document">
            <header>
              <span>{String(selectedStep?.order || 1).padStart(2, '0')}</span>
              <div><p>WORK STEP</p><h2>{selectedStep?.title}</h2><small>按真实作业顺序执行 · 本步骤完成后留下可检查产物</small></div>
            </header>
            <section className="learning-task-operation">
              <div className="learning-task-section-label"><span>01</span><strong>具体操作</strong></div>
              <p>{selectedStep?.operation}</p>
            </section>
            <div className="learning-task-delivery-grid">
              <section><span>步骤产物</span><strong>{selectedStep?.deliverable}</strong><p>完成本步骤时必须留下的中间结果。</p></section>
              <section><span>验收依据</span><strong>{selectedStep?.acceptance}</strong><p>用观察、命令输出或测试记录判定是否通过。</p></section>
            </div>
            <section className="learning-task-dependency-section">
              <div className="learning-task-section-label"><span>02</span><strong>前置与依赖</strong></div>
              <div className="learning-task-dependency-flow">
                {selectedStep?.prerequisites.length ? selectedStep.prerequisites.map(item => <span key={item}>{document.steps.find(step => step.id === item)?.title || item}</span>) : <span>环境与任务契约已就绪</span>}
                <i>→</i><strong>{selectedStep?.title}</strong><i>→</i><span>{selectedStep?.deliverable}</span>
              </div>
            </section>
            <section className="learning-task-context-section">
              <div className="learning-task-section-label"><span>03</span><strong>任务边界</strong></div>
              <dl><div><dt>工作情境</dt><dd>{document.task.context}</dd></div><div><dt>整体目标</dt><dd>{document.task.objective}</dd></div></dl>
            </section>
          </article>
        </main>

        <aside className="learning-task-inspector">
          <header><div><span>STEP MAPPING</span><strong>本步骤知识与技能</strong></div><small>{stepRelations.length} 条强关系</small></header>
          <section>
            <h3><i>知</i>知识点</h3>
            {stepKnowledge.map(item => <article key={item.id}>
              <strong>{item.title}</strong><p>{item.summary}</p>
              <button type="button" onClick={() => { void openPersonalized(item.id) }} disabled={busy === 'handoff'}>进入个性化学习 <span>→</span></button>
            </article>)}
          </section>
          <section>
            <h3><i>技</i>技能点</h3>
            {stepSkills.map(item => <article key={item.id}><strong>{item.title}</strong><p>{item.summary}</p></article>)}
          </section>
          <section className="learning-task-relation-list">
            <h3><i>链</i>关系依据</h3>
            {stepRelations.map(item => <p key={item.id}>{item.reason}</p>)}
          </section>
          <section className="learning-task-resource-list">
            <h3><i>资</i>学习资源</h3>
            {stepResources.map(item => item.url ? <a key={item.id} href={item.url} target="_blank" rel="noreferrer"><span>▶</span><div><strong>{item.provider}</strong><small>{item.title}</small></div><i>↗</i></a> : null)}
            {!stepResources.some(item => item.url) && <p>当前步骤还没有可打开的资源链接。</p>}
          </section>
          {handoffStatus && <p className="learning-task-handoff-status">{handoffStatus}</p>}
        </aside>
      </div>

      <aside className="learning-task-annotation-drawer" aria-hidden={!drawerOpen}>
        <header><div><span>REVIEW NOTE</span><strong>批注与复核</strong></div><button type="button" onClick={() => setDrawerOpen(false)} aria-label="关闭批注">×</button></header>
        <p>批注会固定到当前步骤和快照，并形成可追溯的后继版本。</p>
        {quote && <blockquote><span>已选择文本</span>{quote}</blockquote>}
        <form onSubmit={saveNote}>
          <label htmlFor="learning-task-review-note">复核意见</label>
          <textarea id="learning-task-review-note" value={note} onChange={event => setNote(event.target.value)} placeholder="说明哪里需要补充、调整或重新验证…" rows={7} />
          <button type="submit" disabled={busy === 'revise' || !note.trim()}>{busy === 'revise' ? '提交中…' : '提交复核'}</button>
        </form>
        <section><h3>当前步骤记录</h3>{stepNotes.length ? stepNotes.map(item => <article key={item.id}><p>{item.note}</p>{item.quote && <small>“{item.quote}”</small>}<span>{item.status === 'pending_review' ? '待复核' : item.status}</span></article>) : <p>暂无批注。选中正文也可以直接创建批注。</p>}</section>
      </aside>
    </section>
  )
}
