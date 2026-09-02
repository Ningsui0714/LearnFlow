import {
  defineLearnFlowPlugin,
  LEARNFLOW_PLUGIN_API_VERSION,
  type PluginJson,
  type PluginJsonSchema,
} from '../../src/plugin-api.ts'
import { learningTaskConversionRuntime } from './runtime.ts'
import {
  LEARNING_TASK_CONVERSION_PLUGIN,
  LEARNING_TASK_OBJECT_SCHEMA_VERSION,
  LEARNING_TASK_OBJECT_TYPES,
  LEARNING_TASK_RENDERERS,
} from './shared.ts'

function objectSchema(properties: PluginJsonSchema['properties'], required: string[]): PluginJsonSchema {
  return { type: 'object', properties, required, additionalProperties: false }
}

const candidateSchema = objectSchema({
  schemaVersion: { type: 'string' }, candidateId: { type: 'string' }, requestId: { type: 'string' },
  packageId: { type: 'string' }, packageVersion: { type: 'string' }, snapshotId: { type: 'string' },
  rootHash: { type: 'string' }, lifecycle: { type: 'string' }, confirmationStatus: { type: 'string' },
  groundingStatus: { type: 'string' }, sourceSnapshot: { type: 'object' },
  sourceBindings: { type: 'array' }, citations: { type: 'array' }, task: { type: 'object' },
  mappings: { type: 'object' }, assessment: { type: 'object' }, coverage: { type: 'object' },
  warnings: { type: 'array' }, assumptions: { type: 'array' }, validation: { type: 'object' },
  provenance: { type: 'object' },
}, [
  'schemaVersion', 'candidateId', 'requestId', 'packageId', 'packageVersion', 'snapshotId',
  'rootHash', 'lifecycle', 'confirmationStatus', 'groundingStatus', 'sourceSnapshot',
  'sourceBindings', 'citations', 'task', 'mappings', 'assessment', 'coverage', 'warnings',
  'assumptions', 'validation', 'provenance',
])

const evidenceSchema = objectSchema({
  candidateId: { type: 'string' }, groundingStatus: { type: 'string' }, sourceSnapshot: { type: 'object' },
  sourceBindings: { type: 'array' }, citations: { type: 'array' }, coverage: { type: 'object' },
  warnings: { type: 'array' }, authority: { type: 'string' }, masteryInference: { type: 'boolean' },
}, ['candidateId', 'groundingStatus', 'sourceSnapshot', 'sourceBindings', 'citations', 'coverage', 'warnings', 'authority', 'masteryInference'])

const auditSchema = objectSchema({
  candidateId: { type: 'string' }, lifecycle: { type: 'string' }, validation: { type: 'object' },
  coverage: { type: 'object' }, warnings: { type: 'array' }, provenance: { type: 'object' },
  formalLearningTaskCreated: { type: 'boolean' }, kernelWrites: { type: 'integer' },
}, ['candidateId', 'lifecycle', 'validation', 'coverage', 'warnings', 'provenance', 'formalLearningTaskCreated', 'kernelWrites'])

const handoffSchema = objectSchema({
  schemaVersion: { type: 'string' }, candidateId: { type: 'string' }, status: { type: 'string' },
  consumer: { type: 'string' }, requiresUserConfirmation: { type: 'boolean' }, candidate: { type: 'object' },
  knowledgeId: { type: 'string' }, taskSteps: { type: 'array' }, skills: { type: 'array' },
  resources: { type: 'array' }, citations: { type: 'array' }, returnContract: { type: 'object' },
  validation: { type: 'object' }, instruction: { type: 'string' }, formalLearningTaskCreated: { type: 'boolean' },
  kernelWrites: { type: 'integer' },
}, [
  'schemaVersion', 'candidateId', 'status', 'consumer', 'requiresUserConfirmation', 'knowledgeId',
  'taskSteps', 'skills', 'resources', 'citations', 'returnContract', 'candidate', 'validation',
  'instruction', 'formalLearningTaskCreated', 'kernelWrites',
])

const candidateIdSchema: PluginJsonSchema = {
  type: 'object', properties: { candidateId: { type: 'string', minLength: 5, maxLength: 80 } },
  required: ['candidateId'], additionalProperties: false,
}

const plugin = defineLearnFlowPlugin({
  manifest: {
    apiVersion: LEARNFLOW_PLUGIN_API_VERSION,
    ...LEARNING_TASK_CONVERSION_PLUGIN,
    defaultEnabled: false,
    objects: [
      {
        type: 'learning_task_candidate', title: '学习型任务候选',
        description: '讯飞工作流生成、LearnFlow 校验但尚未确认的候选 artifact。',
        schemaVersion: LEARNING_TASK_OBJECT_SCHEMA_VERSION, schema: candidateSchema,
        validate: (value: PluginJson) => {
          const candidate = value as Record<string, any>
          return candidate.lifecycle === 'candidate'
            && candidate.confirmationStatus === 'unconfirmed'
            && candidate.validation?.valid === true
            && candidate.provenance?.kernelTargets?.length === 0
            ? [] : ['candidate must remain valid, unconfirmed and kernel-free']
        },
      },
      {
        type: 'learning_task_evidence', title: '候选来源检查', description: '固定来源版本、引用、覆盖与事实边界。',
        schemaVersion: LEARNING_TASK_OBJECT_SCHEMA_VERSION, schema: evidenceSchema,
        validate: (value: PluginJson) => (value as Record<string, any>).masteryInference === false ? [] : ['evidence view cannot infer mastery'],
      },
      {
        type: 'learning_task_audit', title: '候选确定性审计', description: '结构、依赖、映射、引用与零内核写入检查。',
        schemaVersion: LEARNING_TASK_OBJECT_SCHEMA_VERSION, schema: auditSchema,
        validate: (value: PluginJson) => Number((value as Record<string, any>).kernelWrites) === 0 ? [] : ['audit must report zero kernel writes'],
      },
      {
        type: 'learning_task_handoff', title: 'Tutor 审阅候选包', description: '仅供 Tutor 解释和用户确认的候选交接包。',
        schemaVersion: LEARNING_TASK_OBJECT_SCHEMA_VERSION, schema: handoffSchema,
        validate: (value: PluginJson) => {
          const handoff = value as Record<string, any>
          return handoff.requiresUserConfirmation === true && handoff.formalLearningTaskCreated === false
            ? [] : ['handoff must require confirmation and must not create a formal task']
        },
      },
    ],
    tools: [
      {
        id: 'draft_learning_task', title: '生成学习型任务候选',
        description: '把真实工作任务、固定项目来源与目标步骤数发送给服务端固定讯飞工作流，返回未提交候选。',
        whenToUse: '插件已启用且用户要求把一个具体、可执行的真实工作任务转成学习步骤时，直接调用。',
        whenNotToUse: '不要用于知识章节规划、判断学习者掌握、评分，或在没有具体任务对象和交付目标时虚构岗位事实。',
        toolClass: 'execution', risk: 'artifact', requiresProject: true,
        renderer: LEARNING_TASK_RENDERERS.candidate,
        inputSchema: {
          type: 'object', additionalProperties: false, required: ['taskTitle'],
          properties: {
            taskTitle: { type: 'string', minLength: 2, maxLength: 300 },
            taskDescription: { type: 'string', maxLength: 2000 },
            upstreamTask: { type: 'object', description: '可选的上游典型工作任务 JSON；按不可信输入处理。' },
            sourceVersionIds: { type: 'array', maxItems: 20, items: { type: 'integer', minimum: 1 } },
            targetStepCount: { type: 'integer', minimum: 3, maximum: 12 },
            maxSourceSegments: { type: 'integer', minimum: 1, maximum: 20 },
            requestId: { type: 'string', minLength: 8, maxLength: 160 },
          },
        },
        outputObjectTypes: ['learning_task_candidate'],
        availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'], timeoutMs: 120_000,
      },
      {
        id: 'read_learning_task_candidate', title: '读取学习任务候选',
        description: '按 candidateId 读取当前用户、当前项目的未提交候选。',
        whenToUse: '对话中已有候选 ID，需要继续解释、比较步骤或恢复查看时。',
        whenNotToUse: '不要读取其他项目候选，不要把候选表述为正式 LearningTask。',
        toolClass: 'perception', risk: 'read_only', requiresProject: true,
        renderer: LEARNING_TASK_RENDERERS.candidate, inputSchema: candidateIdSchema,
        outputObjectTypes: ['learning_task_candidate'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'inspect_learning_task_evidence', title: '检查候选来源证据',
        description: '检查固定 SourceVersion、来源片段引用、覆盖、截断和 grounding 状态。',
        whenToUse: '用户追问候选依据、来源是否真正进入工作流、引用或覆盖缺口时。',
        whenNotToUse: '不要把候选来源当作学习者掌握证据，也不要补造 citation。',
        toolClass: 'perception', risk: 'read_only', requiresProject: true,
        renderer: LEARNING_TASK_RENDERERS.evidence, inputSchema: candidateIdSchema,
        outputObjectTypes: ['learning_task_evidence'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'audit_learning_task_candidate', title: '审计学习任务候选',
        description: '重新执行确定性结构、ID、引用、依赖 DAG、资源 URL 与零内核写入检查。',
        whenToUse: '用户要求复核候选是否可进入确认环节，或怀疑结构、映射、截断问题时。',
        whenNotToUse: '审计通过不等于用户确认、正式发布、评分或掌握。',
        toolClass: 'perception', risk: 'read_only', requiresProject: true,
        renderer: LEARNING_TASK_RENDERERS.audit, inputSchema: candidateIdSchema,
        outputObjectTypes: ['learning_task_audit'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'prepare_learning_handoff', title: '准备 Tutor 审阅候选',
        description: '把已校验候选整理为 Tutor 可解释、可追问、等待用户确认的只读交接包。',
        whenToUse: '用户希望继续由 Tutor 审阅、解释或确认候选步骤时。',
        whenNotToUse: '不要声称已进入个性化学习；本工具不创建正式 LearningTask。',
        toolClass: 'perception', risk: 'read_only', requiresProject: true,
        renderer: LEARNING_TASK_RENDERERS.handoff, inputSchema: candidateIdSchema,
        outputObjectTypes: ['learning_task_handoff'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
    ],
    skills: [{
      id: 'draft_learning_task', title: '真实工作任务转学习任务候选',
      description: '选中插件后，把本轮输入直接转为讯飞候选，再由 Tutor 解释并等待确认。',
      whenToUse: '用户要求把具体工作任务转成可执行学习步骤、任务工单或学习型工作任务。',
      whenNotToUse: '用户只是问概念、要求评分、修改掌握状态或尚未给出可执行任务时。',
      instructions: [
        '用户本轮给出了具体真实工作任务并要求转化时，第一步直接调用 learning_task_conversion__draft_learning_task，不要把用户引导到另一个插件页面重复输入。',
        'taskTitle 保留用户任务对象、动作和交付目标；可从当前项目读取到的来源由服务端固定 SourceVersion 后注入，插件不得自行伪造 sourceVersionIds 或 citations。',
        '工具结果是 learning_task_candidate。必须明确它尚未成为正式 LearningTask，不得修改学习者五核、掌握状态、长期记忆、评分或学习路径。',
        '若 groundingStatus 为 ungrounded 或 source_supplied_unverified，必须就近说明来源边界；不要把模型生成内容表述为岗位来源事实。',
        '需要核对依据时调用 inspect_learning_task_evidence；需要结构复核时调用 audit_learning_task_candidate；用户希望继续审阅时调用 prepare_learning_handoff。',
        'handoff 只进入 Tutor 当前轮的候选消费上下文。用户明确确认之前，不得声称已进入个性化学习或正式发布。',
      ].join('\n'),
      tools: ['draft_learning_task', 'read_learning_task_candidate', 'inspect_learning_task_evidence', 'audit_learning_task_candidate', 'prepare_learning_handoff'],
      objectTypes: [...LEARNING_TASK_OBJECT_TYPES],
    }],
    renderers: [
      { id: LEARNING_TASK_RENDERERS.candidate, title: '学习任务候选工作台', description: '按先后依赖显示任务步骤、产物、验收和步骤内知识技能。' },
      { id: LEARNING_TASK_RENDERERS.evidence, title: '候选来源证据', description: '显示固定来源、引用、覆盖与事实边界。' },
      { id: LEARNING_TASK_RENDERERS.audit, title: '候选确定性审计', description: '显示结构校验、警告与零内核写入边界。' },
      { id: LEARNING_TASK_RENDERERS.handoff, title: 'Tutor 审阅候选包', description: '显示等待用户确认的只读候选交接。' },
    ],
  },
  handlers: {
    draft_learning_task: (input, context) => learningTaskConversionRuntime.draft(input, context),
    read_learning_task_candidate: (input, context) => learningTaskConversionRuntime.read(input, context),
    inspect_learning_task_evidence: (input, context) => learningTaskConversionRuntime.evidence(input, context),
    audit_learning_task_candidate: (input, context) => learningTaskConversionRuntime.audit(input, context),
    prepare_learning_handoff: (input, context) => learningTaskConversionRuntime.handoff(input, context),
  },
})

export default plugin
