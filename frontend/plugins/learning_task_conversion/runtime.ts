import { createHash } from 'node:crypto'
import {
  LEARNFLOW_PLUGIN_OBJECT_VERSION,
  type LearnFlowPluginObject,
  type PluginJson,
  type PluginToolContext,
  type PluginToolResult,
} from '../../src/plugin-api.ts'
import {
  LEARNING_TASK_CONVERSION_PLUGIN,
  LEARNING_TASK_OBJECT_SCHEMA_VERSION,
  LEARNING_TASK_RENDERERS,
} from './shared.ts'

type JsonRecord = Record<string, any>

function integration(context: PluginToolContext) {
  if (!context.scope.projectId) throw new Error('plugin_contract_invalid:learning-task conversion requires a project')
  if (!context.projectIntegration) throw new Error('plugin_integration_error:backend_unavailable:项目集成通道不可用')
  return context.projectIntegration
}

function stableRequestId(input: JsonRecord, context: PluginToolContext) {
  if (typeof input.requestId === 'string' && input.requestId.trim()) return input.requestId.trim()
  const fingerprint = createHash('sha256').update(JSON.stringify({
    projectId: context.scope.projectId,
    conversationId: context.scope.conversationId || '',
    taskTitle: input.taskTitle,
    taskDescription: input.taskDescription || '',
    sourceVersionIds: input.sourceVersionIds || [],
  })).digest('hex').slice(0, 24)
  return `plugin:${context.scope.projectId}:${fingerprint}`
}

function object(objectType: string, objectId: string, label: string, value: PluginJson): LearnFlowPluginObject {
  return {
    protocol: LEARNFLOW_PLUGIN_OBJECT_VERSION,
    pluginId: LEARNING_TASK_CONVERSION_PLUGIN.id,
    objectType,
    objectId,
    schemaVersion: LEARNING_TASK_OBJECT_SCHEMA_VERSION,
    label,
    value,
  }
}

function candidateResult(candidate: JsonRecord, summary = ''): PluginToolResult {
  const title = String(candidate.task?.title || '学习型任务候选')
  return {
    summary: summary || `已生成“${title}”候选，共 ${candidate.task?.steps?.length || 0} 个步骤；尚未创建正式 LearningTask。`,
    objects: [object('learning_task_candidate', String(candidate.candidateId), title, candidate as PluginJson)],
    payload: {
      candidateId: candidate.candidateId,
      lifecycle: candidate.lifecycle,
      groundingStatus: candidate.groundingStatus,
      sourceSnapshot: candidate.sourceSnapshot,
      coverage: candidate.coverage,
      warnings: candidate.warnings,
      formalLearningTaskCreated: false,
      kernelWrites: 0,
    },
    presentation: { renderer: LEARNING_TASK_RENDERERS.candidate },
  }
}

export const learningTaskConversionRuntime = {
  async draft(input: JsonRecord, context: PluginToolContext): Promise<PluginToolResult> {
    const candidate = await integration(context).request('create_candidate', {
      schemaVersion: 'role-learning-task-candidate-request.v1',
      requestId: stableRequestId(input, context),
      taskTitle: String(input.taskTitle || '').trim(),
      taskDescription: String(input.taskDescription || '').trim(),
      upstreamTask: input.upstreamTask && typeof input.upstreamTask === 'object' ? input.upstreamTask : null,
      sourceVersionIds: Array.isArray(input.sourceVersionIds) ? input.sourceVersionIds : [],
      targetStepCount: Number(input.targetStepCount || 6),
      maxSourceSegments: Number(input.maxSourceSegments || 16),
    }) as JsonRecord
    return candidateResult(candidate)
  },

  async read(input: JsonRecord, context: PluginToolContext): Promise<PluginToolResult> {
    const candidate = await integration(context).request('read_candidate', {
      candidateId: String(input.candidateId || ''),
    }) as JsonRecord
    return candidateResult(candidate, `已读取“${candidate.task?.title || candidate.candidateId}”候选；生命周期仍为未确认。`)
  },

  async evidence(input: JsonRecord, context: PluginToolContext): Promise<PluginToolResult> {
    const evidence = await integration(context).request('inspect_evidence', {
      candidateId: String(input.candidateId || ''),
    }) as JsonRecord
    return {
      summary: `候选 ${evidence.candidateId} 绑定 ${evidence.citations?.length || 0} 条可核验引用；不构成掌握证据。`,
      objects: [object('learning_task_evidence', String(evidence.candidateId), '候选来源与引用', evidence as PluginJson)],
      payload: evidence as PluginJson,
      presentation: { renderer: LEARNING_TASK_RENDERERS.evidence },
    }
  },

  async audit(input: JsonRecord, context: PluginToolContext): Promise<PluginToolResult> {
    const audit = await integration(context).request('audit_candidate', {
      candidateId: String(input.candidateId || ''),
    }) as JsonRecord
    return {
      summary: audit.validation?.valid
        ? `候选 ${audit.candidateId} 已通过当前确定性结构校验；仍需用户确认。`
        : `候选 ${audit.candidateId} 未通过当前确定性结构校验。`,
      objects: [object('learning_task_audit', String(audit.candidateId), '学习任务候选审计', audit as PluginJson)],
      payload: audit as PluginJson,
      presentation: { renderer: LEARNING_TASK_RENDERERS.audit },
    }
  },

  async handoff(input: JsonRecord, context: PluginToolContext): Promise<PluginToolResult> {
    const handoff = await integration(context).request('prepare_handoff', {
      candidateId: String(input.candidateId || ''),
    }) as JsonRecord
    return {
      summary: `候选 ${handoff.candidateId} 已整理为 Tutor 审阅包；用户确认前不会创建正式学习任务。`,
      objects: [object('learning_task_handoff', String(handoff.candidateId), 'Tutor 审阅候选包', handoff as PluginJson)],
      payload: handoff as PluginJson,
      presentation: { renderer: LEARNING_TASK_RENDERERS.handoff },
    }
  },
}
