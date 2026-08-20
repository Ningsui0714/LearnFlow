import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, CircleDot,
  FileJson2, GitBranch, RefreshCw, ShieldCheck,
} from 'lucide-react'
import {
  confirmLearningTaskPlan, getLearningTaskPlan,
  type LearningTaskPlanRun, type LearningTaskPlanWorkPackage,
} from '../services/api'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'

const phaseLabels: Record<LearningTaskPlanRun['phase'], string> = {
  INTAKE: '等待任务明确',
  CONTRACT_READY: '计划待确认',
  PLAN_READY: '计划已就绪',
  EVIDENCE_READY: '证据已就绪',
  STEP_PLAN_READY: '步骤计划已就绪',
  CANDIDATES_READY: '候选已就绪',
  REVIEWED: '评审完成',
  PATCH_REQUIRED: '需要局部修订',
  COMMIT_READY: '等待交付',
  COMMITTED: '已交付',
  FAILED: '运行失败',
}

const roleLabels: Record<string, string> = {
  task_contract_compiler: '任务契约编译',
  plan_builder: '计划构建',
  evidence_explorer: '证据探索',
  candidate_planner: '候选规划',
  critic_committee: '独立评审',
  targeted_patch_agent: '定向修订',
  artifact_publisher: '交付编译',
}

const artifactLabels: Record<string, string> = {
  task_contract: '任务契约',
  task_plan: '任务 Plan',
  evidence_ledger: '证据账本',
  step_plan: '作业步骤 Plan',
  candidate_set: '候选任务集',
  critic_report: '评审报告',
  patch_plan: '局部修订计划',
  selected_candidate: '选定候选',
  delivery_bundle: '最终交付包',
  failure_report: '失败报告',
}

const toolLabels: Record<string, string> = {
  task_database: '任务数据库',
  knowledge_base_pro: '知识库 Pro',
  official_web: '权威 Web',
  evidence_verifier: '证据校验器',
  candidate_generator: '候选生成器',
  candidate_critic: '候选评审器',
  task_compiler: '任务编译器',
}

const evidenceLabels: Record<string, string> = {
  upstream: '上游数据',
  database: '任务数据库',
  knowledge_base: '知识库',
  official_web: '权威网络来源',
  official_or_upstream: '权威来源或上游确认',
  user_confirmation: '用户确认',
}

function WorkPackageCard({ item, index }: { item: LearningTaskPlanWorkPackage; index: number }) {
  return (
    <article className="relative rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-700">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-950">{roleLabels[item.agent_role] || item.agent_role}</h3>
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
              输出：{artifactLabels[item.expected_artifact] || item.expected_artifact}
            </span>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-600">{item.objective}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">依赖</p>
              <p className="mt-1 text-[11px] text-slate-700">{item.depends_on.length ? item.depends_on.join('、') : '无，可直接开始'}</p>
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">允许工具</p>
              <p className="mt-1 text-[11px] leading-4 text-slate-700">{item.allowed_tools.map(tool => toolLabels[tool] || tool).join('、')}</p>
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">完成条件</p>
              <p className="mt-1 text-[11px] leading-4 text-slate-700">{item.completion_condition}</p>
            </div>
          </div>
        </div>
      </div>
      {index > 0 && <ArrowRight size={14} className="absolute -top-4 left-5 rotate-90 text-slate-300" />}
    </article>
  )
}

export default function LearningTaskPlanPage() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<LearningTaskPlanRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')

  useWorkspaceTitle(run?.plan.goal || '学习型任务 Plan', { kind: 'wf03' })

  const load = useCallback(async () => {
    if (!runId) return
    setLoading(true)
    setError('')
    try {
      setRun(await getLearningTaskPlan(runId))
    } catch (failure: any) {
      setError(failure?.response?.data?.detail || '任务 Plan 加载失败。')
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => { load() }, [load])

  const confirm = async () => {
    if (!run || run.phase !== 'CONTRACT_READY' || confirming) return
    setConfirming(true)
    setError('')
    try {
      const result = await confirmLearningTaskPlan(
        run.run_id,
        run.plan.plan_version,
        globalThis.crypto?.randomUUID?.() || `plan-confirm-${run.run_id}-${Date.now()}`,
      )
      setRun(result)
    } catch (failure: any) {
      setError(failure?.response?.data?.detail || '任务 Plan 确认失败。')
    } finally {
      setConfirming(false)
    }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500"><RefreshCw size={16} className="mr-2 animate-spin" />正在恢复任务 Plan…</div>
  }

  if (!run) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-8">
        <div className="max-w-md rounded-xl border border-red-200 bg-white p-6 text-center shadow-sm">
          <AlertTriangle className="mx-auto text-red-500" size={24} />
          <p className="mt-3 text-sm text-slate-800">{error || '没有找到任务 Plan。'}</p>
          <button type="button" onClick={load} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white">重新加载</button>
        </div>
      </div>
    )
  }

  const contract = run.task_contract || {}
  const confirmed = run.phase === 'PLAN_READY' || !['INTAKE', 'CONTRACT_READY'].includes(run.phase)

  return (
    <div className="h-full overflow-y-auto bg-slate-50 px-5 py-6 sm:px-8">
      <div className="mx-auto max-w-5xl pb-12">
        <header className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${confirmed ? 'bg-emerald-100 text-emerald-800' : run.phase === 'INTAKE' ? 'bg-amber-100 text-amber-800' : 'bg-indigo-100 text-indigo-800'}`}>
                  {phaseLabels[run.phase]}
                </span>
                <span className="text-[10px] text-slate-400">Plan v{run.plan.plan_version} · checkpoint {run.checkpoint_version}</span>
              </div>
              <h1 className="mt-3 text-xl font-bold tracking-tight text-slate-950 sm:text-2xl">{run.plan.goal}</h1>
              <p className="mt-2 text-xs leading-5 text-slate-500">这是可检查的计划产物，不包含隐藏思维链。后续阶段必须沿用同一 Run 和任务语义指纹。</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button type="button" onClick={load} disabled={loading} className="flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-600 hover:bg-slate-50">
                <RefreshCw size={13} />刷新
              </button>
              {run.phase === 'CONTRACT_READY' && (
                <button type="button" onClick={confirm} disabled={confirming} className="flex h-9 items-center gap-1.5 rounded-lg bg-indigo-700 px-3.5 text-xs font-semibold text-white hover:bg-indigo-800 disabled:opacity-50">
                  {confirming ? <RefreshCw size={13} className="animate-spin" /> : <ShieldCheck size={14} />}
                  {confirming ? '正在校验' : '确认并提交 Plan'}
                </button>
              )}
            </div>
          </div>
          {error && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
          {confirmed && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3 text-xs leading-5 text-emerald-900">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              <span>Plan 已通过远端语义指纹、依赖图和工具权限校验，当前停在 PLAN_READY。证据探索与执行尚未启动。</span>
            </div>
          )}
        </header>

        <section className="mt-5 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2"><FileJson2 size={17} className="text-indigo-700" /><h2 className="text-sm font-semibold text-slate-950">任务契约</h2></div>
            <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
              <div><dt className="text-slate-400">用户原始任务</dt><dd className="mt-1 leading-5 text-slate-800">{String(contract.raw_input || contract.normalized_input || '')}</dd></div>
              <div><dt className="text-slate-400">输入层级</dt><dd className="mt-1 text-slate-800">{contract.input_level === 'single_work_task' ? '单个可执行工作任务' : '需要进一步明确'}</dd></div>
              <div><dt className="text-slate-400">动作与对象</dt><dd className="mt-1 text-slate-800">{[contract.action, contract.object].filter(Boolean).join(' · ') || '待补充'}</dd></div>
              <div><dt className="text-slate-400">预期交付</dt><dd className="mt-1 text-slate-800">{String(contract.expected_deliverable || '待补充')}</dd></div>
            </dl>
            <p className="mt-4 break-all rounded-lg bg-slate-50 px-3 py-2 font-mono text-[9px] text-slate-400">语义指纹：{run.plan.task_contract_fingerprint}</p>
          </article>

          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2"><Check size={17} className="text-emerald-700" /><h2 className="text-sm font-semibold text-slate-950">成功条件</h2></div>
            <ul className="mt-3 space-y-2">
              {run.plan.success_criteria.map(item => <li key={item} className="flex gap-2 text-xs leading-5 text-slate-700"><Check size={13} className="mt-1 shrink-0 text-emerald-600" />{item}</li>)}
            </ul>
          </article>
        </section>

        <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2"><CircleDot size={17} className="text-amber-600" /><h2 className="text-sm font-semibold text-slate-950">规划前需要解决的不确定项</h2></div>
            <span className="text-[10px] text-slate-400">{run.plan.unknowns.filter(item => item.blocking).length} 个阻塞项</span>
          </div>
          {run.plan.unknowns.length ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {run.plan.unknowns.map(item => (
                <div key={item.unknown_id} className={`rounded-xl border p-3 ${item.blocking ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
                  <p className="text-xs font-medium leading-5 text-slate-900">{item.question}</p>
                  <p className="mt-1 text-[10px] text-slate-500">所需依据：{evidenceLabels[item.required_evidence] || item.required_evidence}</p>
                </div>
              ))}
            </div>
          ) : <p className="mt-3 text-xs text-slate-500">任务契约没有待补充的不确定项。</p>}
        </section>

        <section className="mt-5">
          <div className="mb-3 flex items-center gap-2"><GitBranch size={17} className="text-indigo-700" /><h2 className="text-sm font-semibold text-slate-950">工作包与依赖图</h2></div>
          <div className="space-y-4">
            {run.plan.work_packages.map((item, index) => <WorkPackageCard key={item.package_id} item={item} index={index} />)}
          </div>
        </section>

        <section className="mt-5 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5">
          <h2 className="text-sm font-semibold text-slate-950">计划产物链</h2>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {run.plan.work_packages.map((item, index) => (
              <div key={item.package_id} className="flex items-center gap-2">
                {index > 0 && <ArrowRight size={13} className="text-indigo-300" />}
                <span className="rounded-lg border border-indigo-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-indigo-900">
                  {artifactLabels[item.expected_artifact] || item.expected_artifact}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-600">当前下一步：{run.next_actions.join('；') || '等待用户确认'}</p>
        </section>

        <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-slate-950">停止条件与修订预算</h2><span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] text-slate-600">最多 {run.plan.repair_budget} 轮局部修订</span></div>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {run.plan.stop_conditions.map(item => <li key={item} className="flex gap-2 text-xs leading-5 text-slate-600"><AlertTriangle size={13} className="mt-1 shrink-0 text-amber-500" />{item}</li>)}
          </ul>
        </section>
      </div>
    </div>
  )
}
