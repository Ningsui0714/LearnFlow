import type { FormalProjectWorkspace } from './project.ts'
import {
  loadProjectPluginSurfaces,
  runProjectPluginWorkflow,
  type ProjectPluginSurface,
} from './plugin-runtime.ts'
import {
  pluginChatContext,
  roleCapabilityArtifactFromSnapshot,
  type PluginChatContext,
  type RoleCapabilityChatArtifact,
} from './plugin-chat.ts'

const GENERIC_PROJECT_NAMES = new Set(['岗位分析', '岗位研究', '职业规划', '职业发展', '职业方向', '发展方向', '岗位方向'])
const ROLE_SUFFIX = '(?:工程师|开发者|架构师|产品经理|项目经理|设计师|分析师|科学家|研究员|顾问|运营|测试|专家|教师|医生|律师|会计|经理)'

function compact(value: unknown, limit = 120) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, limit)
}

function stableToken(value: string) {
  let hash = 0x811c9dc5
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function stripRoleIntent(value: string) {
  return value
    .replace(/^(?:(?:请|帮我|我想|我希望|目标是|目标岗位是|岗位是|研究一下|研究|分析一下|分析|了解一下|了解|规划一下|规划|成为|转型为|转行做|应聘)\s*)+/u, '')
    .replace(/(?:这个岗位|的岗位能力|的能力图谱|岗位图谱|岗位包)$/u, '')
    .replace(/[。！？!?，,；;：:]+$/u, '')
    .trim()
}

export type RoleCapabilityBootstrapPlan = {
  roleTitle: string
  taskSeeds: string[]
  origin: 'message' | 'project_objective' | 'project_name'
}

export function planRoleCapabilityBootstrap(input: {
  message?: string
  projectName?: string
  projectObjective?: string
}): RoleCapabilityBootstrapPlan | undefined {
  const candidates: Array<[RoleCapabilityBootstrapPlan['origin'], string]> = [
    ['message', compact(input.message)],
    ['project_objective', compact(input.projectObjective)],
    ['project_name', compact(input.projectName)],
  ]
  for (const [origin, raw] of candidates) {
    if (!raw || GENERIC_PROJECT_NAMES.has(raw)) continue
    const explicit = raw.match(new RegExp(`([\\u4e00-\\u9fffA-Za-z0-9+#./· -]{2,64}${ROLE_SUFFIX})`, 'u'))?.[1]
    const roleTitle = compact(stripRoleIntent(explicit || raw), 64)
    if (!roleTitle || GENERIC_PROJECT_NAMES.has(roleTitle) || roleTitle.length < 2) continue
    if (!explicit && origin === 'message' && !/(?:岗位|职业|转行|应聘|成为|工程师|开发|架构|产品|设计|分析|研究员|顾问|运营|测试|教师|医生|律师|会计|经理)/u.test(raw)) continue
    return {
      roleTitle,
      origin,
      taskSeeds: [
        `梳理${roleTitle}在真实工作场景中的核心职责与典型任务`,
        `识别${roleTitle}完成关键交付所需的能力、知识技能与质量标准`,
        `验证${roleTitle}常见工作过程、产物、协作对象与风险边界`,
      ],
    }
  }
  return undefined
}

export type RoleCapabilityTutorActivation = {
  status: 'ready' | 'generated' | 'needs_role'
  context: PluginChatContext
  surface: ProjectPluginSurface
  roleTitle?: string
  artifact?: RoleCapabilityChatArtifact
}

export async function activateRoleCapabilityForTutor(options: {
  projectId: number
  surface: ProjectPluginSurface
  project: FormalProjectWorkspace['project']
  latestUserMessage?: string
  sourceIds?: number[]
}): Promise<RoleCapabilityTutorActivation> {
  const existingContext = pluginChatContext(options.surface)
  if (existingContext.snapshotId) {
    return { status: 'ready', context: existingContext, surface: options.surface }
  }
  const plan = planRoleCapabilityBootstrap({
    message: options.latestUserMessage,
    projectName: options.project.name,
    projectObjective: options.project.objective,
  })
  if (!plan) return { status: 'needs_role', context: existingContext, surface: options.surface }

  await runProjectPluginWorkflow(options.projectId, options.surface, 'generate', {
    role_title: plan.roleTitle,
    task_seeds: plan.taskSeeds,
    source_ids: options.sourceIds || [],
  }, {
    idempotencyKey: `plugin:${options.surface.plugin_id}:bootstrap:p${options.projectId}:i${options.surface.instance_id}:r${stableToken(plan.roleTitle)}:v1`,
  })
  const refreshedPage = await loadProjectPluginSurfaces(options.projectId)
  const refreshed = refreshedPage.surfaces.find(item => item.plugin_id === options.surface.plugin_id)
  if (!refreshed) throw new Error('岗位图谱生成完成，但 Tutor 无法重新读取插件 Surface')
  const context = pluginChatContext(refreshed)
  if (!context.snapshotId) throw new Error('岗位图谱 workflow 未提交可读取的首个快照')
  const artifact = roleCapabilityArtifactFromSnapshot(refreshed.data, `${plan.roleTitle}岗位图谱`)
  if (!artifact) throw new Error('岗位图谱快照缺少可在对话中呈现的对象')
  return { status: 'generated', context, surface: refreshed, roleTitle: plan.roleTitle, artifact }
}
