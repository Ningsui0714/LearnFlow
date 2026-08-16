import { Download, ExternalLink, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import WF03AnnotationPanel from '../components/wf03/WF03AnnotationPanel'
import WF03SelectionToolbar from '../components/wf03/WF03SelectionToolbar'
import WF03TaskDocument, { externalHref } from '../components/wf03/WF03TaskDocument'
import type { WF03Annotation, WF03Selection } from '../components/wf03/types'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  getLearningTaskConversionBundle,
  openPersonalizedLearningKnowledgeEntry,
  submitPersonalizedLearningFeedback,
  type LearningTaskConversionBundle,
  type WF03FeedbackIssue,
} from '../services/api'

function errorMessage(error: any) {
  return error?.response?.data?.detail || error?.message || '任务网页读取失败，请稍后重试。'
}

function targetFromElement(element: Element | null) {
  const step = element?.closest<HTMLElement>('[data-step-id]')
  if (step) return { targetType: 'step' as const, targetId: step.dataset.stepId }
  const knowledge = element?.closest<HTMLElement>('[data-knowledge-id]')
  if (knowledge) return { targetType: 'knowledge' as const, targetId: knowledge.dataset.knowledgeId }
  const skill = element?.closest<HTMLElement>('[data-skill-id]')
  if (skill) return { targetType: 'skill' as const, targetId: skill.dataset.skillId }
  return { targetType: 'document' as const, targetId: undefined }
}

function submittedIssueCount(bundle: LearningTaskConversionBundle) {
  const items = bundle.downstream_feedback?.items
  if (!Array.isArray(items)) return 0
  return items.reduce((total: number, item: any) => {
    // The service stores the original feedback envelope under `feedback` so
    // its correlation id and review state remain traceable. Accept the flat
    // legacy shape as well when reading older bundles.
    const issues = item?.feedback?.issues ?? item?.issues
    return total + (Array.isArray(issues) ? issues.length : 0)
  }, 0)
}

export default function WF03TaskPage() {
  const { taskCardId = '' } = useParams()
  const navigate = useNavigate()
  const contentRef = useRef<HTMLDivElement>(null)
  const loadRequestRef = useRef(0)
  const activeTaskIdRef = useRef(taskCardId)
  const loadedTaskIdRef = useRef('')
  const [bundle, setBundle] = useState<LearningTaskConversionBundle | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selection, setSelection] = useState<WF03Selection | null>(null)
  const [composerSelection, setComposerSelection] = useState<WF03Selection | null>(null)
  const [annotations, setAnnotations] = useState<WF03Annotation[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submittedCount, setSubmittedCount] = useState(0)
  const [annotationsHydrated, setAnnotationsHydrated] = useState(false)
  const [openingKnowledgeId, setOpeningKnowledgeId] = useState('')
  useWorkspaceTitle(bundle?.task.work_task.teaching_task_name || '学习型任务网页', { kind: 'wf03' })

  const storageKey = `learnflow.learning-task.annotations.${taskCardId}`

  useEffect(() => {
    setAnnotationsHydrated(false)
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]')
      setAnnotations(Array.isArray(saved) ? saved : [])
    } catch {
      setAnnotations([])
    } finally {
      setAnnotationsHydrated(true)
    }
  }, [storageKey])

  useEffect(() => {
    if (!annotationsHydrated) return
    localStorage.setItem(storageKey, JSON.stringify(annotations))
  }, [annotations, annotationsHydrated, storageKey])

  const load = useCallback(async () => {
    if (!taskCardId) return
    activeTaskIdRef.current = taskCardId
    const requestId = ++loadRequestRef.current
    setLoading(true)
    if (loadedTaskIdRef.current !== taskCardId) setError('')
    try {
      const nextBundle = await getLearningTaskConversionBundle(taskCardId)
      if (activeTaskIdRef.current !== taskCardId) return
      loadedTaskIdRef.current = taskCardId
      setBundle(nextBundle)
      setSubmittedCount(submittedIssueCount(nextBundle))
      setError('')
      setLoading(false)
    } catch (failure) {
      if (
        requestId !== loadRequestRef.current
        || activeTaskIdRef.current !== taskCardId
        || loadedTaskIdRef.current === taskCardId
      ) return
      setError(errorMessage(failure))
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false)
    }
  }, [taskCardId])

  useEffect(() => { load() }, [load])

  const captureSelection = () => {
    window.setTimeout(() => {
      const nativeSelection = window.getSelection()
      const root = contentRef.current
      if (!nativeSelection || nativeSelection.isCollapsed || !root || !nativeSelection.rangeCount) {
        setSelection(null)
        return
      }
      const range = nativeSelection.getRangeAt(0)
      const common = range.commonAncestorContainer
      const commonElement = common.nodeType === Node.ELEMENT_NODE ? common as Element : common.parentElement
      if (!commonElement || !root.contains(commonElement)) {
        setSelection(null)
        return
      }
      const selectedText = nativeSelection.toString().replace(/\s+/g, ' ').trim()
      if (selectedText.length < 2) {
        setSelection(null)
        return
      }
      const bounds = range.getBoundingClientRect()
      const target = targetFromElement(commonElement)
      setSelection({
        text: selectedText.slice(0, 1200),
        ...target,
        rect: { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
      })
    }, 0)
  }

  const startAnnotation = () => {
    if (!selection) return
    setComposerSelection(selection)
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }

  const submitAnnotations = async () => {
    if (!annotations.length || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const issues: WF03FeedbackIssue[] = annotations.map(annotation => ({
        issue_id: annotation.id,
        feedback_code: annotation.feedbackCode,
        severity: annotation.severity,
        ...(annotation.targetType === 'step' && annotation.targetId ? { step_id: annotation.targetId } : {}),
        ...(annotation.targetType === 'knowledge' && annotation.targetId ? { knowledge_id: annotation.targetId } : {}),
        ...(annotation.targetType === 'skill' && annotation.targetId ? { skill_id: annotation.targetId } : {}),
        message: `选中“${annotation.selectedText.slice(0, 280)}”：${annotation.message}`,
        suggested_correction: annotation.suggestedCorrection,
      }))
      await submitPersonalizedLearningFeedback({
        schema_version: 'personalized-learning-to-task-conversion-feedback-v1',
        task_card_id: taskCardId,
        correlation_id: globalThis.crypto?.randomUUID?.() || `learnflow-${Date.now()}`,
        source_system: 'learnflow-task-review',
        status: 'accepted_with_feedback',
        issues,
        summary: `学习型任务网页提交 ${issues.length} 条选区复核意见。`,
      })
      setAnnotations([])
      await load()
    } catch (failure) {
      setError(errorMessage(failure))
    } finally {
      setSubmitting(false)
    }
  }

  const openPersonalizedLearning = async (knowledgeId: string) => {
    if (!taskCardId || openingKnowledgeId) return
    setOpeningKnowledgeId(knowledgeId)
    setError('')
    try {
      const entry = await openPersonalizedLearningKnowledgeEntry(taskCardId, knowledgeId)
      sessionStorage.setItem(
        `learnflow.personalized-learning.entry.${entry.entry_id}`,
        JSON.stringify(entry),
      )
      navigate(entry.navigation.entry_path, { state: { entry } })
    } catch (failure) {
      setError(errorMessage(failure))
      setOpeningKnowledgeId('')
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500">
        <Loader2 size={18} className="mr-2 animate-spin text-emerald-700" /> 正在读取生成的任务网页…
      </div>
    )
  }

  if (!bundle) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-8">
        <div className="max-w-md border border-red-200 bg-white p-6 text-center shadow-sm">
          <p className="text-sm font-semibold text-slate-900">任务网页暂时无法打开</p>
          <p className="mt-2 text-xs leading-5 text-red-600">{error}</p>
          <button type="button" onClick={load} className="mt-4 inline-flex h-9 items-center gap-1.5 bg-slate-900 px-4 text-xs font-semibold text-white">
            <RefreshCw size={13} /> 重新加载
          </button>
        </div>
      </div>
    )
  }

  const artifactLinks = [
    { label: '原交互页', href: externalHref(bundle.artifacts.interactive_html_url), icon: ExternalLink },
    { label: 'PDF', href: externalHref(bundle.artifacts.pdf_url), icon: Download },
    { label: 'JSON', href: externalHref(bundle.artifacts.personalized_learning_json_url), icon: ExternalLink },
    {
      label: '图谱回传',
      href: externalHref(
        bundle.upstream_feedback?.feedback_json_url
          || bundle.artifacts.feedback_json_url,
      ),
      icon: ExternalLink,
    },
  ].filter(item => item.href)

  return (
    <div className="flex h-full min-h-0 bg-slate-100">
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4">
          <span className="flex h-7 w-7 items-center justify-center bg-emerald-700 text-white"><ShieldCheck size={14} /></span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-slate-900">生成的学习型任务网页</p>
            <p className="truncate font-mono text-[9px] text-slate-400">{taskCardId}</p>
          </div>
          <span className="hidden text-[10px] text-slate-400 md:block">点击“批注”或拖选文字</span>
          {artifactLinks.map(({ label, href, icon: Icon }) => (
            <a key={label} href={href} target="_blank" rel="noreferrer" className="flex h-8 items-center gap-1.5 border border-slate-200 px-2.5 text-[10px] text-slate-600 hover:bg-slate-50">
              <Icon size={12} /> {label}
            </a>
          ))}
        </header>
        {error && <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{error}</div>}
        <div
          ref={contentRef}
          onMouseUp={captureSelection}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-5 selection:bg-amber-200 selection:text-slate-950 sm:px-7"
        >
          <WF03TaskDocument
            bundle={bundle}
            openingKnowledgeId={openingKnowledgeId}
            onOpenPersonalizedLearning={openPersonalizedLearning}
            onAnnotate={target => {
              setSelection(null)
              setComposerSelection(target)
              window.getSelection()?.removeAllRanges()
            }}
          />
        </div>
      </section>

      <WF03AnnotationPanel
        selection={composerSelection}
        annotations={annotations}
        submitting={submitting}
        submittedCount={submittedCount}
        onCancelSelection={() => setComposerSelection(null)}
        onAdd={annotation => setAnnotations(previous => [...previous, annotation])}
        onRemove={id => setAnnotations(previous => previous.filter(annotation => annotation.id !== id))}
        onSubmit={submitAnnotations}
      />

      {selection && <WF03SelectionToolbar selection={selection} onAnnotate={startAnnotation} />}
    </div>
  )
}
