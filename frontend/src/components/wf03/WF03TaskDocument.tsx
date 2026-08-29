import {
  ArrowRight, ExternalLink, MessageSquarePlus, PlayCircle, Sparkles, Wrench,
} from 'lucide-react'
import type { LearningTaskConversionBundle, LearningTaskStepHandoff } from '../../services/api'
import type { WF03Selection } from './types'

const HIGH_RISK_TERMS = /安全|风险|断电|高压|权限|分区|格式化|删除|加密|认证|生产环境|回滚|故障|异常|冲突|兼容|校准|电池|驱动|网络|数据库/g
const CRITICAL_ACTION_TERMS = /安装|部署|配置|迁移|调试|联调|验收|验证|测试|诊断|恢复|备份|切换/g
const KEY_STEP_NAME_TERMS = /重装|安装|部署|配置|校验|验证|测试|验收|调试|联调|迁移|恢复/

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function platformLabel(platform?: string, linkKind?: string) {
  if (platform === 'bilibili') return linkKind === 'curated_video' ? 'B站精选' : 'B站搜索'
  if (platform === 'douyin') return linkKind === 'curated_video' ? '抖音精选' : '抖音搜索'
  return platform || '学习资源'
}

export function isKeyTaskStep(step: LearningTaskStepHandoff) {
  const action = step.action.trim()
  const instruction = text(step.instruction).trim()
  const body = [step.name, action, instruction, step.deliverable, step.check].join(' ')
  const highRiskTermCount = new Set(body.match(HIGH_RISK_TERMS) || []).size
  const criticalActionCount = new Set(body.match(CRITICAL_ACTION_TERMS) || []).size
  const mappingCount = step.knowledge_point_ids.length + step.skill_point_ids.length

  let score = 0
  if (instruction && instruction !== action) score += 1
  if (body.length >= 150) score += 1
  if (mappingCount >= 4) score += 1
  if (step.deliverable.length >= 36 || step.check.length >= 36) score += 1
  if (highRiskTermCount > 0) score += 2
  if (criticalActionCount > 0) score += 1
  if (KEY_STEP_NAME_TERMS.test(step.name)) score += 2

  return score >= 3
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

function ResourceLinks({ resources }: { resources: Array<any> }) {
  if (!resources.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {resources.map((resource, index) => {
        const href = externalHref(resource.resource_url)
        if (!href) return null
        return (
          <a
            key={`${resource.resource_id || resource.resource_url}-${index}`}
            href={href}
            target="_blank"
            rel="noreferrer"
            title={resource.resource_name}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 transition hover:border-emerald-300 hover:text-emerald-800"
          >
            {resource.platform === 'bilibili' || resource.platform === 'douyin'
              ? <PlayCircle size={11} />
              : <ExternalLink size={11} />}
            {platformLabel(resource.platform, resource.link_kind)}
          </a>
        )
      })}
    </div>
  )
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

  const relationsForStep = (stepName: string, knowledgeId?: string, skillId?: string) => (
    (bundle.strong_relationships || []).filter(relation => {
      const applies = Array.isArray(relation.applies_to_steps) ? relation.applies_to_steps.map(String) : []
      const stepMatches = !applies.length || applies.includes(stepName)
      const knowledgeMatches = !knowledgeId || String(relation.knowledge_id || '') === knowledgeId
      const skillMatches = !skillId || String(relation.skill_id || '') === skillId
      return stepMatches && knowledgeMatches && skillMatches
    })
  )

  return (
    <article className="mx-auto w-full max-w-[980px] pb-16" data-task-document>
      <header className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-6 py-5 shadow-sm sm:flex-row sm:items-end sm:justify-between sm:px-8">
        <div className="min-w-0">
          <p className="text-[10px] font-bold tracking-[0.14em] text-emerald-700">具体作业步骤</p>
          <h1 className="mt-1.5 text-xl font-bold leading-tight tracking-tight text-slate-950 sm:text-2xl">
            {task.teaching_task_name || task.enterprise_task_name}
          </h1>
        </div>
        <span className="shrink-0 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-800">
          共 {task.task_steps.length} 步
        </span>
      </header>

      <section className="mt-5">
        <div className="flex items-end gap-3 px-1">
          <div>
            <p className="text-[10px] font-bold tracking-[0.14em] text-emerald-700">WORK PROCESS</p>
            <h2 className="mt-1 text-xl font-bold tracking-tight text-slate-950">真实作业流程</h2>
          </div>
          <p className="mb-0.5 ml-auto hidden text-xs text-slate-400 sm:block">关键步骤展开，常规步骤精简</p>
        </div>

        <div className="relative mt-5">
          <div className="absolute bottom-8 left-[22px] top-8 w-px bg-emerald-200 sm:left-[27px]" />
          <div className="space-y-4">
            {task.task_steps.map((step, index) => {
              const keyStep = isKeyTaskStep(step)
              return (
                <section
                key={step.step_id}
                className="group relative grid gap-3 pl-[58px] sm:pl-[72px] 2xl:grid-cols-[minmax(0,1fr)_235px]"
                data-step-id={step.step_id}
              >
                <div className="absolute left-0 top-5 z-10 flex h-11 w-11 items-center justify-center rounded-xl border-4 border-slate-100 bg-emerald-700 text-xs font-black text-white shadow-sm sm:left-1 sm:h-12 sm:w-12">
                  {String(step.step || index + 1).padStart(2, '0')}
                </div>
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition group-hover:-translate-y-0.5 group-hover:border-emerald-300 group-hover:shadow-md">
                  <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-[10px] font-bold tracking-[0.12em] text-emerald-700">阶段 {index + 1}</p>
                        {keyStep && (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-bold text-amber-700">关键步骤</span>
                        )}
                      </div>
                      <h3 className="mt-1 text-base font-bold text-slate-950">{step.name}</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => onAnnotate(annotationTarget('step', step.step_id, `${step.name}：${step.action}`))}
                      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[10px] font-semibold text-slate-500 transition hover:border-emerald-300 hover:text-emerald-800"
                    >
                      <MessageSquarePlus size={12} /> 批注
                    </button>
                  </div>
                  <div className="px-5 py-4 sm:px-6">
                    <p className="text-sm leading-7 text-slate-700">{step.action}</p>
                    {keyStep ? (
                      <>
                        {step.instruction && step.instruction.trim() !== step.action.trim() && (
                          <p className="mt-2 border-l-2 border-amber-200 pl-3 text-xs leading-6 text-slate-500">{step.instruction}</p>
                        )}
                        <div className="mt-4 grid gap-3 sm:grid-cols-2">
                          <div className="rounded-lg bg-sky-50 px-3.5 py-3">
                            <p className="text-[10px] font-bold tracking-[0.1em] text-sky-700">阶段产物</p>
                            <p className="mt-1.5 text-xs leading-5 text-slate-700">{step.deliverable}</p>
                          </div>
                          <div className="rounded-lg bg-emerald-50 px-3.5 py-3">
                            <p className="text-[10px] font-bold tracking-[0.1em] text-emerald-700">验收检查</p>
                            <p className="mt-1.5 text-xs leading-5 text-slate-700">{step.check}</p>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="mt-3 space-y-1.5 border-t border-slate-100 pt-3 text-[11px] leading-5">
                        <p className="flex gap-2 text-slate-600"><span className="w-8 shrink-0 font-bold text-sky-700">产物</span><span>{step.deliverable}</span></p>
                        <p className="flex gap-2 text-slate-600"><span className="w-8 shrink-0 font-bold text-emerald-700">验收</span><span>{step.check}</span></p>
                      </div>
                    )}
                  </div>
                </div>

                {keyStep ? (
                  <aside className="rounded-xl border border-slate-200 bg-slate-50/80 p-4">
                  <p className="text-[10px] font-bold tracking-[0.12em] text-slate-500">步骤能力映射</p>
                  <div className="mt-3 space-y-2.5">
                    {step.knowledge_point_ids.map((id, mappingIndex) => {
                      const knowledge = knowledgeById.get(id)
                      const relations = relationsForStep(step.name, id)
                      return (
                        <div key={`${id}-${mappingIndex}`} className="rounded-lg border border-emerald-100 bg-white p-3" data-knowledge-id={id}>
                          <div className="flex w-full items-start gap-2 text-left">
                            <Sparkles size={13} className="mt-0.5 shrink-0 text-emerald-700" />
                            <span className="min-w-0 flex-1 text-[11px] font-semibold leading-4 text-slate-800">
                              {knowledge?.name || id}
                            </span>
                          </div>
                          {knowledge && (
                            <p className="mt-2 text-[10px] leading-4 text-slate-500">
                              {text(knowledge.scope) || text(knowledge.description) || text(knowledge.concept) || text(knowledge.operation) || '支撑完成并验收本步任务。'}
                            </p>
                          )}
                          {relations.map(relation => relation.reason ? (
                            <p key={String(relation.relation_id || relation.reason)} className="mt-2 rounded-md bg-emerald-50 px-2.5 py-2 text-[9px] leading-4 text-emerald-900">
                              <span className="font-bold">关联理由：</span>{String(relation.reason)}
                            </p>
                          ) : null)}
                          {!!knowledge?.learning_resources?.length && <div className="mt-2.5"><ResourceLinks resources={knowledge.learning_resources} /></div>}
                          <button
                            type="button"
                            onClick={() => onOpenPersonalizedLearning(id)}
                            disabled={openingKnowledgeId === id}
                            title="携带本知识点、当前任务步骤和强关联技能进入个性化学习"
                            className="mt-3 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-emerald-700 px-3 text-[10px] font-bold text-white transition hover:bg-emerald-800 disabled:cursor-wait disabled:bg-emerald-300"
                          >
                            <Sparkles size={11} />
                            {openingKnowledgeId === id ? '正在生成个性化学习…' : '进入本步个性化学习'}
                            <ArrowRight size={11} />
                          </button>
                        </div>
                      )
                    })}
                    {step.skill_point_ids.map((id, mappingIndex) => {
                      const skill = skillById.get(id)
                      const relations = relationsForStep(step.name, undefined, id)
                      return (
                        <div key={`${id}-${mappingIndex}`} className="rounded-lg border border-amber-100 bg-amber-50/70 p-3" data-skill-id={id}>
                          <div className="flex items-start gap-2">
                            <Wrench size={12} className="mt-0.5 shrink-0 text-amber-700" />
                            <span className="text-[11px] font-semibold leading-4 text-amber-950">{skill?.name || id}</span>
                          </div>
                          {skill && <p className="mt-2 text-[10px] leading-4 text-amber-900/75">{text(skill.observable_action) || text(skill.expected_artifact) || text(skill.description) || '通过对应任务产物进行观察与验收。'}</p>}
                          {relations.map(relation => relation.reason ? (
                            <p key={String(relation.relation_id || relation.reason)} className="mt-2 text-[9px] leading-4 text-amber-900/70">{String(relation.reason)}</p>
                          ) : null)}
                        </div>
                      )
                    })}
                    </div>
                  </aside>
                ) : (
                  <aside className="rounded-xl border border-slate-200 bg-slate-50/80 p-4">
                    <p className="text-[10px] font-bold tracking-[0.12em] text-slate-500">本步知识与技能</p>
                    <div className="mt-3 space-y-2">
                      {step.knowledge_point_ids.map((id, mappingIndex) => {
                        const knowledge = knowledgeById.get(id)
                        return (
                          <button
                            key={`${id}-${mappingIndex}`}
                            type="button"
                            onClick={() => onOpenPersonalizedLearning(id)}
                            disabled={openingKnowledgeId === id}
                            data-knowledge-id={id}
                            className="flex min-h-9 w-full items-center gap-2 rounded-lg border border-emerald-100 bg-white px-3 py-2 text-left text-[10px] font-semibold text-slate-700 transition hover:border-emerald-300 hover:text-emerald-800 disabled:cursor-wait disabled:opacity-60"
                          >
                            <Sparkles size={12} className="shrink-0 text-emerald-700" />
                            <span className="min-w-0 flex-1">{knowledge?.name || id}</span>
                            <ArrowRight size={11} className="shrink-0" />
                          </button>
                        )
                      })}
                    </div>
                    {!!step.skill_point_ids.length && (
                      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-200 pt-3">
                        {step.skill_point_ids.map((id, mappingIndex) => {
                          const skill = skillById.get(id)
                          return (
                            <span key={`${id}-${mappingIndex}`} data-skill-id={id} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-[9px] font-semibold text-amber-900">
                              <Wrench size={10} /> {skill?.name || id}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </aside>
                )}
                </section>
              )
            })}
          </div>
        </div>
      </section>

    </article>
  )
}
