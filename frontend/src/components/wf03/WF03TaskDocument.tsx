import {
  ArrowDown, ArrowUpRight, BookOpenCheck, CheckCircle2, ClipboardCheck, Database,
  ExternalLink, MessageSquarePlus, PlayCircle, Sparkles, Wrench,
} from 'lucide-react'
import type { LearningTaskConversionBundle } from '../../services/api'
import type { WF03Selection } from './types'

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function platformLabel(platform?: string, linkKind?: string) {
  if (platform === 'bilibili') return linkKind === 'curated_video' ? 'B站精选' : 'B站搜索'
  if (platform === 'douyin') return linkKind === 'curated_video' ? '抖音精选' : '抖音搜索'
  return platform || '资源'
}

export function externalHref(value: unknown) {
  const raw = text(value).trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  if (raw.startsWith('//')) return `https:${raw}`
  if (/^(localhost|127\.0\.0\.1)(:\d+)?(?:\/|$)/i.test(raw)) return `http://${raw}`
  if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:\/|$)/.test(raw)) return `https://${raw}`
  return ''
}

function displayItem(value: unknown) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return ''
  const item = value as Record<string, unknown>
  return text(item.name) || text(item.title) || text(item.description) || text(item.check) || text(item.action)
}

function annotationTarget(
  targetType: WF03Selection['targetType'],
  targetId: string | undefined,
  selectedText: string,
): WF03Selection {
  return {
    text: selectedText,
    targetType,
    targetId,
    rect: { left: 0, top: 0, width: 0, height: 0 },
  }
}

export default function WF03TaskDocument({
  bundle,
  onAnnotate,
  onOpenPersonalizedLearning,
  openingKnowledgeId,
}: {
  bundle: LearningTaskConversionBundle
  onAnnotate: (selection: WF03Selection) => void
  onOpenPersonalizedLearning: (knowledgeId: string) => void
  openingKnowledgeId?: string
}) {
  const task = bundle.task.work_task
  const knowledgeById = new Map(task.knowledge_points.map(item => [item.knowledge_id, item]))
  const skillById = new Map(task.skill_points.map(item => [item.skill_id, item]))

  return (
    <article className="mx-auto w-full max-w-[920px] pb-20" data-task-document>
      <header className="border border-slate-200 bg-white px-7 py-7 shadow-sm sm:px-10">
        <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em]">
          <span className="bg-emerald-50 px-2 py-1 text-emerald-800">学习型工作任务</span>
          <span className="bg-sky-50 px-2 py-1 text-sky-700">{bundle.verification_status === 'verified' ? '已通过校验' : '待补充证据'}</span>
        </div>
        <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">
          {task.teaching_task_name || task.enterprise_task_name}
        </h1>
        <p className="mt-3 text-sm leading-7 text-slate-600">
          {task.teaching_task_description || task.enterprise_task_description || '按真实工作过程完成任务并提交可检查成果。'}
        </p>
        <div className="mt-5 border-l-2 border-emerald-600 pl-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">企业典型工作任务</p>
          <p className="mt-1 text-sm font-medium text-slate-800">{task.enterprise_task_name}</p>
          {task.enterprise_task_description && <p className="mt-1 text-xs leading-5 text-slate-500">{task.enterprise_task_description}</p>}
        </div>
        {!!task.work_situation && (
          <div className="mt-5 border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">工作情境</p>
            <p className="mt-1 text-xs leading-6 text-slate-700">{displayItem(task.work_situation) || task.teaching_task_description}</p>
          </div>
        )}
      </header>

      <section className="mt-5 border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={17} className="text-emerald-700" />
          <h2 className="text-base font-bold text-slate-900">工作步骤与验收点</h2>
          <span className="ml-auto text-[10px] text-slate-400">共 {task.task_steps.length} 步</span>
        </div>
        <div className="mt-5 space-y-0">
          {task.task_steps.map((step, index) => (
            <div key={step.step_id}>
              <section className="group relative border border-slate-200 bg-slate-50/70 p-5 hover:border-emerald-300 hover:bg-white" data-step-id={step.step_id}>
                <div className="flex items-start gap-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center bg-slate-900 text-xs font-bold text-white">
                    {String(step.step || index + 1).padStart(2, '0')}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <h3 className="min-w-0 flex-1 text-sm font-bold text-slate-900">{step.name}</h3>
                      <button
                        type="button"
                        onClick={() => onAnnotate(annotationTarget('step', step.step_id, `${step.name}：${step.action}`))}
                        className="inline-flex h-7 shrink-0 items-center gap-1 border border-slate-200 bg-white px-2 text-[10px] font-medium text-slate-600 hover:border-emerald-400 hover:text-emerald-700"
                      >
                        <MessageSquarePlus size={11} /> 批注本步
                      </button>
                    </div>
                    <p className="mt-2 text-sm leading-7 text-slate-700">{step.action}</p>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <div className="border-l-2 border-sky-400 bg-sky-50/60 px-3 py-2.5">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-sky-700">本步产物</p>
                        <p className="mt-1 text-xs leading-5 text-slate-700">{step.deliverable}</p>
                      </div>
                      <div className="border-l-2 border-emerald-500 bg-emerald-50/60 px-3 py-2.5">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-emerald-700">检查方式</p>
                        <p className="mt-1 text-xs leading-5 text-slate-700">{step.check}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {step.knowledge_point_ids.map((id, mappingIndex) => {
                        const knowledge = knowledgeById.get(id)
                        const resources = knowledge?.learning_resources || []
                        return (
                          <span key={`${id}-${mappingIndex}`} className="inline-flex flex-wrap items-center gap-1 border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700">
                            <button
                              type="button"
                              onClick={() => onOpenPersonalizedLearning(id)}
                              disabled={openingKnowledgeId === id}
                              title="携带本知识点的步骤、技能与关系 JSON 进入个性化学习"
                              className="inline-flex items-center gap-1 font-semibold hover:text-indigo-950 hover:underline disabled:cursor-wait disabled:opacity-60"
                            >
                              <Sparkles size={10} />
                              {openingKnowledgeId === id ? '正在进入个性化学习…' : `知识 · ${knowledge?.name || id}`}
                              <ArrowUpRight size={9} />
                            </button>
                            {resources.slice(0, 3).map((resource, resourceIndex) => {
                              const href = externalHref(resource.resource_url)
                              return href ? <a
                                key={`${resource.resource_id || resource.resource_url}-${resourceIndex}`}
                                href={href}
                                target="_blank"
                                rel="noreferrer"
                                title={resource.resource_name}
                                className="inline-flex items-center gap-0.5 border-l border-indigo-200 pl-1 font-semibold hover:text-indigo-950 hover:underline"
                              >
                                <PlayCircle size={10} /> {platformLabel(resource.platform, resource.link_kind)}
                              </a> : null
                            })}
                          </span>
                        )
                      })}
                      {step.skill_point_ids.map((id, mappingIndex) => (
                        <span key={`${id}-${mappingIndex}`} className="border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-800">
                          技能 · {skillById.get(id)?.name || id}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </section>
              {index < task.task_steps.length - 1 && (
                <div className="flex h-8 items-center justify-center text-slate-300"><ArrowDown size={15} /></div>
              )}
            </div>
          ))}
        </div>
      </section>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className="border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2">
            <Database size={16} className="text-indigo-700" />
            <h2 className="text-sm font-bold text-slate-900">支撑知识</h2>
          </div>
          <div className="mt-4 space-y-2.5">
            {task.knowledge_points.map((item, index) => (
              <article key={item.knowledge_id} className="border border-slate-200 p-3.5" data-knowledge-id={item.knowledge_id}>
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 text-[10px] font-bold text-indigo-600">K{String(index + 1).padStart(2, '0')}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <h3 className="min-w-0 flex-1 text-xs font-semibold text-slate-900">{item.name}</h3>
                      <button
                        type="button"
                        onClick={() => onAnnotate(annotationTarget('knowledge', item.knowledge_id, item.name))}
                        className="inline-flex h-6 shrink-0 items-center gap-1 border border-slate-200 px-1.5 text-[9px] text-slate-500 hover:border-indigo-300 hover:text-indigo-700"
                      >
                        <MessageSquarePlus size={10} /> 批注
                      </button>
                      <button
                        type="button"
                        onClick={() => onOpenPersonalizedLearning(item.knowledge_id)}
                        disabled={openingKnowledgeId === item.knowledge_id}
                        title="以该知识点和强关联任务步骤生成个性化学习内容"
                        className="inline-flex h-6 shrink-0 items-center gap-1 bg-indigo-600 px-2 text-[9px] font-semibold text-white hover:bg-indigo-700 disabled:cursor-wait disabled:bg-indigo-300"
                      >
                        <Sparkles size={10} />
                        {openingKnowledgeId === item.knowledge_id ? '正在交接…' : '个性化学习'}
                      </button>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-slate-500">
                      {text(item.scope) || text(item.description) || text(item.concept) || text(item.operation) || '用于支撑对应任务步骤。'}
                    </p>
                    {item.verification && <p className="mt-1 text-[10px] leading-4 text-emerald-700">验证：{item.verification}</p>}
                    {!!item.learning_resources?.length && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {item.learning_resources.map((resource, resourceIndex) => {
                          const href = externalHref(resource.resource_url)
                          return href ? <a
                            key={`${resource.resource_id || resource.resource_url}-${resourceIndex}`}
                            href={href}
                            target="_blank"
                            rel="noreferrer"
                            title={resource.review_status || resource.resource_name}
                            className="inline-flex items-center gap-1 border border-indigo-100 bg-indigo-50 px-2 py-1 text-[9px] font-medium text-indigo-700 hover:border-indigo-300 hover:bg-indigo-100"
                          >
                            {resource.platform === 'bilibili' || resource.platform === 'douyin'
                              ? <PlayCircle size={10} />
                              : <ExternalLink size={10} />}
                            {platformLabel(resource.platform, resource.link_kind)}
                          </a> : null
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2">
            <Wrench size={16} className="text-amber-700" />
            <h2 className="text-sm font-bold text-slate-900">目标技能</h2>
          </div>
          <div className="mt-4 space-y-2.5">
            {task.skill_points.map((item, index) => (
              <article key={item.skill_id} className="border border-slate-200 p-3.5" data-skill-id={item.skill_id}>
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 text-[10px] font-bold text-amber-700">S{String(index + 1).padStart(2, '0')}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <h3 className="min-w-0 flex-1 text-xs font-semibold text-slate-900">{item.name}</h3>
                      <button
                        type="button"
                        onClick={() => onAnnotate(annotationTarget('skill', item.skill_id, item.name))}
                        className="inline-flex h-6 shrink-0 items-center gap-1 border border-slate-200 px-1.5 text-[9px] text-slate-500 hover:border-amber-300 hover:text-amber-800"
                      >
                        <MessageSquarePlus size={10} /> 批注
                      </button>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-slate-500">
                      {text(item.observable_action) || text(item.expected_artifact) || text(item.description) || '通过对应任务产物进行观察与验收。'}
                    </p>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>

      {!!task.tools?.length && (
        <section className="mt-5 border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2">
            <BookOpenCheck size={16} className="text-emerald-700" />
            <h2 className="text-sm font-bold text-slate-900">工具与环境</h2>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {task.tools.map((tool, index) => <span key={`${tool}-${index}`} className="border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600">{tool}</span>)}
          </div>
        </section>
      )}

      {!!task.safety_points?.length && (
        <section className="mt-5 border border-amber-200 bg-amber-50/70 p-6 shadow-sm">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-amber-700" />
            <h2 className="text-sm font-bold text-slate-900">安全要点与作业边界</h2>
          </div>
          <ol className="mt-3 space-y-2 text-xs leading-6 text-slate-700">
            {task.safety_points.map((item, index) => (
              <li key={index} className="flex gap-2"><span className="font-semibold text-amber-700">{index + 1}.</span>{displayItem(item)}</li>
            ))}
          </ol>
        </section>
      )}

      <footer className="mt-5 flex items-center gap-2 border border-emerald-200 bg-emerald-50 px-5 py-4 text-xs text-emerald-900">
        <CheckCircle2 size={16} className="shrink-0" />
        此网页由服务端校验后的结构化任务包实时渲染；批注进入复核流程，不直接覆盖原始任务。
      </footer>
    </article>
  )
}
