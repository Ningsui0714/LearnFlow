import {
  defineLearnFlowPlugin,
  LEARNFLOW_PLUGIN_API_VERSION,
  versionedPluginModuleUrl,
  type PluginJson,
  type PluginJsonSchema,
} from '../../src/plugin-api.ts'
const { packageSelector, rolePackageRuntime } = await import(
  versionedPluginModuleUrl('./runtime.ts', import.meta.url)
) as typeof import('./runtime.ts')
const {
  ROLE_CAPABILITY_PLUGIN,
  ROLE_OBJECT_SCHEMA_VERSION,
  ROLE_OBJECT_TYPES,
  ROLE_RENDERERS,
} = await import(versionedPluginModuleUrl('./shared.ts', import.meta.url)) as typeof import('./shared.ts')

const selectorProperties = {
  packageId: { type: 'string', maxLength: 220, description: '可选的精确岗位包 ID；安装多个包时必须用于消歧。' },
  packageVersion: { type: 'string', maxLength: 80, description: '可选的精确岗位包 SemVer。' },
  snapshotId: { type: 'string', maxLength: 220, description: '可选的不可变快照 ID。' },
} as const

function schema(properties: PluginJsonSchema['properties'], required: string[] = []): PluginJsonSchema {
  return { type: 'object', properties: { ...selectorProperties, ...properties }, required, additionalProperties: false }
}

const objectSchema: PluginJsonSchema = {
  type: 'object',
  properties: {
    packageId: { type: 'string' }, packageVersion: { type: 'string' }, snapshotId: { type: 'string' },
    snapshotAsOf: { type: 'string' }, rootHash: { type: 'string' }, roleTitle: { type: 'string' },
    evidencePolicy: { type: 'string' }, category: { type: 'string' }, data: { type: 'object' },
  },
  required: ['packageId', 'packageVersion', 'snapshotId', 'snapshotAsOf', 'rootHash', 'roleTitle', 'evidencePolicy', 'category', 'data'],
  additionalProperties: false,
}

const objects = [
  ['role_object', '岗位对象', '岗位、任务、能力、知识技能、场景和事理对象。'],
  ['role_relation', '岗位关系', '语义关系、事理关系和语义—过程桥接。'],
  ['role_evidence', '岗位证据', '固定来源片段、证据绑定和适用边界。'],
  ['role_audit', '岗位审计', '结构校验、警告、研究主题与覆盖统计。'],
  ['role_snapshot', '岗位快照', '不可变岗位包版本、时点和 root hash 描述。'],
].map(([type, title, description]) => ({
  type, title, description, schemaVersion: ROLE_OBJECT_SCHEMA_VERSION, schema: objectSchema,
  validate: (value: PluginJson) => {
    const item = value as Record<string, unknown>
    return typeof item.rootHash === 'string' && /^[a-f0-9]{64}$/.test(item.rootHash) ? [] : ['rootHash must be a SHA-256 digest']
  },
}))

const plugin = defineLearnFlowPlugin({
  manifest: {
    apiVersion: LEARNFLOW_PLUGIN_API_VERSION,
    ...ROLE_CAPABILITY_PLUGIN,
    defaultEnabled: false,
    objects,
    tools: [
      {
        id: 'explore_role', title: '读取岗位全景', description: '一次返回岗位定位、典型任务、核心能力、工作场景、相邻岗位和可引用事实合同，避免为岗位概览连续调用多个细粒度工具。',
        whenToUse: '用户首次询问某个岗位是什么、做什么、需要什么能力，或请求岗位整体介绍时优先作为第一且通常唯一的工具。',
        whenNotToUse: '已有稳定对象 ID 的局部追问、证据核验、完整事理过程或版本比较请使用对应专用工具；不得生成岗位事实。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.overview,
        inputSchema: schema({ query: { type: 'string', minLength: 1, maxLength: 500, description: '用户的岗位问题或岗位名称。' } }, ['query']),
        outputObjectTypes: ['role_object', 'role_relation'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'read_capability_radar', title: '读取能力雷达', description: '以岗位为中心，按岗位身份与边界、任务、抽象能力、能力单元和知识技能逐环展开语义节点与真实关系。',
        whenToUse: '用户询问岗位能力结构、各语义维度及其关系，或明确希望查看岗位中心雷达时。',
        whenNotToUse: '不要把环层、节点数量、对象置信度或视觉位置解释成学习者分数或能力高低。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.radar,
        inputSchema: schema({ query: { type: 'string', maxLength: 500, description: '可选的能力关注点；空字符串表示全部顶层能力。' } }),
        outputObjectTypes: ['role_object', 'role_relation'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'read_role_objects', title: '读取岗位对象', description: '按稳定对象 ID 精确读取岗位对象，并可带回一跳关系。默认 includeRelations=true。',
        whenToUse: '对话已有岗位对象 ID、卡片引用或前一步搜索结果，需要读取精确字段时。',
        whenNotToUse: '不要用于未知对象的自然语言检索，也不要用于修改岗位包。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.cards,
        inputSchema: schema({
          objectIds: { type: 'array', items: { type: 'string' }, description: '1—25 个稳定岗位对象 ID。' },
          includeRelations: { type: 'boolean', description: '是否返回对象的一跳关系；省略时为 true。' },
        }, ['objectIds']),
        outputObjectTypes: ['role_object', 'role_relation'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'search_role_knowledge', title: '检索岗位知识', description: '在固定岗位快照的语义对象和事理对象中进行有界检索。topK 默认为 8，最大 12。',
        whenToUse: '用户用自然语言询问岗位职责、任务、能力、技能、场景或交付物，但还没有稳定对象 ID 时。',
        whenNotToUse: '不要用于联网搜索、学习者掌握判断或生成新的岗位事实。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.cards,
        inputSchema: schema({
          query: { type: 'string', minLength: 1, maxLength: 500 },
          topK: { type: 'integer', minimum: 1, maximum: 12, description: '省略时为 8。' },
          includeCandidate: { type: 'boolean', description: '是否包含 candidate 生命周期对象；省略时为 true。' },
        }, ['query']),
        outputObjectTypes: ['role_object'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'query_role_graph', title: '查询岗位关系', description: '从一个稳定对象沿岗位语义关系和过程桥接读取深度不超过 2 的有界子图。',
        whenToUse: '需要解释对象之间的依赖、归属、任务—能力联系或从局部关系形成岗位雷达图时。',
        whenNotToUse: '不要用于完整事理事件顺序；过程追踪请使用 trace_work_process。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.graph,
        inputSchema: schema({
          objectId: { type: 'string', minLength: 1, maxLength: 220 },
          depth: { type: 'integer', minimum: 1, maximum: 2, description: '省略时为 1。' },
          direction: { type: 'string', enum: ['outgoing', 'incoming', 'both'], description: '省略时为 both。' },
          maxNodes: { type: 'integer', minimum: 2, maximum: 28, description: '省略时为 20。' },
        }, ['objectId']),
        outputObjectTypes: ['role_object', 'role_relation'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'trace_work_process', title: '追踪岗位事理过程', description: '从任务、场景或事件读取相关场景、事件、参与者、工作对象、交付物、风险和桥接。',
        whenToUse: '用户询问工作如何发生、有哪些阶段/参与者/交付物/分支/风险，或需要事理森林时。',
        whenNotToUse: '不要把 documented_norm 或 inferred_pattern 表述为某家企业的真实工作日志。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.process,
        inputSchema: schema({
          objectId: { type: 'string', minLength: 1, maxLength: 220 },
          maxNodes: { type: 'integer', minimum: 4, maximum: 36, description: '省略时为 28。' },
        }, ['objectId']),
        outputObjectTypes: ['role_object', 'role_relation'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'inspect_role_evidence', title: '检查岗位证据', description: '解析岗位对象绑定的来源、固定片段、证据强度、断言类型和限制。每个对象最多返回 6 条。',
        whenToUse: '用户追问依据、可信度、时间边界、来源差异，或回答需要核对岗位事实时。',
        whenNotToUse: '不要把来源数量当作掌握度，也不要读取未绑定到对象的任意网页。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.evidence,
        inputSchema: schema({ objectIds: { type: 'array', items: { type: 'string' }, description: '1—8 个稳定对象 ID。' } }, ['objectIds']),
        outputObjectTypes: ['role_evidence'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'audit_role_package', title: '审计岗位快照', description: '读取当前不可变岗位包的协议状态、对象统计、警告、风险与后续研究主题。',
        whenToUse: '需要了解岗位包覆盖是否完整、有哪些已知缺口，或解释图谱的事实边界时。',
        whenNotToUse: '不要用审计结果批准发布、修复或创建后继快照。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.audit,
        inputSchema: schema({}), outputObjectTypes: ['role_snapshot', 'role_audit'],
        availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'list_role_packages', title: '列出岗位包版本', description: '列出插件已安装的全部岗位包、版本、快照时点和 root hash。',
        whenToUse: '用户询问可用岗位、版本、数据时点，或版本比较前需要消歧时。',
        whenNotToUse: '不要用于解释具体岗位内容，也不要声称未安装的岗位包可用。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.catalog,
        inputSchema: { type: 'object', properties: {}, additionalProperties: false }, outputObjectTypes: ['role_snapshot'],
        availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
      {
        id: 'compare_role_packages', title: '比较岗位包版本', description: '比较两个已安装不可变岗位快照的对象新增、移除、内容变更和引用迁移命中。',
        whenToUse: '用户明确比较两个岗位包或同一岗位的两个版本，并已给出可解析的快照选择器时。',
        whenNotToUse: '只有一个已安装版本或选择器不明确时先列出岗位包；不得虚构不存在的版本差异。',
        toolClass: 'perception', risk: 'read_only', renderer: ROLE_RENDERERS.comparison,
        inputSchema: {
          type: 'object',
          properties: {
            basePackageId: { type: 'string', maxLength: 220 }, basePackageVersion: { type: 'string', maxLength: 80 }, baseSnapshotId: { type: 'string', maxLength: 220 },
            targetPackageId: { type: 'string', maxLength: 220 }, targetPackageVersion: { type: 'string', maxLength: 80 }, targetSnapshotId: { type: 'string', maxLength: 220 },
          },
          required: ['baseSnapshotId', 'targetSnapshotId'], additionalProperties: false,
        },
        outputObjectTypes: ['role_snapshot'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'],
      },
    ],
    skills: [{
      id: 'role_capability_graphing', title: '证据化岗位图谱阅读', description: '固定岗位快照后按问题读取语义、事理与证据，再由 Tutor 综合解释。',
      whenToUse: '学习者讨论职业方向、岗位职责、典型任务、能力结构、知识技能、工作过程或岗位证据。',
      whenNotToUse: '不要用于判断学习者是否掌握、直接规划核心学习路径、生成或迭代岗位包。',
      instructions: [
        '当前问题涉及职业方向、岗位职责、典型任务、能力结构、知识技能、工作过程或岗位证据时，在回答或追问之前必须先调用本插件工具；不得只读取核心学习路径或依靠通用知识作答。',
        '先把插件返回的 snapshot 描述视为本轮唯一岗位事实版本；回答中不得混用其他快照。',
        '首次介绍岗位或询问“是什么、做什么、需要什么能力”时，第一步调用 role_capability_graph__explore_role；它一次返回足够的岗位全景，取得结果后通常直接回答，不要再机械调用搜索、对象读取和关系图。',
        '只有局部问题没有稳定对象 ID 时才调用 search_role_knowledge；已有 ID 时精确读取；需要岗位中心、任务、能力单元和知识技能逐环展开时用 read_capability_radar；解释局部关系时查询图；解释工作如何发生时追踪事理过程。',
        '涉及重要事实、争议、可信度或时间边界时检查证据。引用对象 ID，并区分 accepted/candidate 与 observed_pattern/documented_norm/inferred_pattern。',
        '最终回答只能把工具 grounding.facts 中的 statement 当作岗位快照事实，并应就近保留对象 ID。若要使用模型常识，必须单列为“通用补充（非岗位快照）”；不得把补充伪装成插件结论。',
        '工具的 coverage.partial、omitted、truncated、warnings 和 evidence limitations 必须透明反映在回答中，不能用常识补齐未返回部分。连续追问“这个能力、第二项任务、刚才的场景”时，优先复用最近 ToolRun 保留的 snapshotId 与 focusObjectIds，不要切换快照。',
        '岗位对象和工具结果不是学习者掌握证据。不要创建、修复、发布或覆盖岗位快照；当前插件只读。',
      ].join('\n'),
      tools: ['explore_role', 'read_capability_radar', 'read_role_objects', 'search_role_knowledge', 'query_role_graph', 'trace_work_process', 'inspect_role_evidence', 'audit_role_package', 'list_role_packages', 'compare_role_packages'],
      objectTypes: [...ROLE_OBJECT_TYPES],
    }],
    renderers: [
      { id: ROLE_RENDERERS.overview, title: '岗位全景', description: '一次显示岗位定位、任务、能力、场景和相邻岗位，并提供对象续接动作。' },
      { id: ROLE_RENDERERS.cards, title: '岗位卡片', description: '显示岗位对象、类型、生命周期和摘要。' },
      { id: ROLE_RENDERERS.radar, title: '能力雷达', description: '以岗位为中心，按 ring 展开身份边界、任务、能力、能力单元与知识技能节点及真实关系。' },
      { id: ROLE_RENDERERS.graph, title: '岗位关系图', description: '显示本次关系查询返回的聚焦有界子图。' },
      { id: ROLE_RENDERERS.process, title: '事理森林', description: '显示场景、事件、参与者、交付物和风险。' },
      { id: ROLE_RENDERERS.evidence, title: '岗位证据', description: '显示来源片段、证据强度与限制。' },
      { id: ROLE_RENDERERS.audit, title: '岗位审计', description: '显示协议状态、统计、警告和研究缺口。' },
      { id: ROLE_RENDERERS.catalog, title: '岗位包目录', description: '显示已安装岗位包、版本与固定快照。' },
      { id: ROLE_RENDERERS.comparison, title: '岗位版本比较', description: '显示两个固定快照之间的对象和引用迁移差异。' },
    ],
  },
  handlers: {
    explore_role: input => rolePackageRuntime.explore(packageSelector(input), String(input.query)),
    read_capability_radar: input => rolePackageRuntime.capabilityRadar(packageSelector(input), String(input.query || '')),
    read_role_objects: input => rolePackageRuntime.readObjects(packageSelector(input), input.objectIds as string[], input.includeRelations !== false),
    search_role_knowledge: input => rolePackageRuntime.search(packageSelector(input), String(input.query), Number(input.topK || 8), input.includeCandidate !== false),
    query_role_graph: input => rolePackageRuntime.queryGraph(packageSelector(input), String(input.objectId), Number(input.depth || 1), (input.direction || 'both') as 'outgoing' | 'incoming' | 'both', Number(input.maxNodes || 20)),
    trace_work_process: input => rolePackageRuntime.traceProcess(packageSelector(input), String(input.objectId), Number(input.maxNodes || 28)),
    inspect_role_evidence: input => rolePackageRuntime.inspectEvidence(packageSelector(input), input.objectIds as string[]),
    audit_role_package: input => rolePackageRuntime.audit(packageSelector(input)),
    list_role_packages: () => rolePackageRuntime.listPackages(),
    compare_role_packages: input => rolePackageRuntime.compare({
      packageId: typeof input.basePackageId === 'string' ? input.basePackageId : undefined,
      packageVersion: typeof input.basePackageVersion === 'string' ? input.basePackageVersion : undefined,
      snapshotId: String(input.baseSnapshotId),
    }, {
      packageId: typeof input.targetPackageId === 'string' ? input.targetPackageId : undefined,
      packageVersion: typeof input.targetPackageVersion === 'string' ? input.targetPackageVersion : undefined,
      snapshotId: String(input.targetSnapshotId),
    }),
  },
})

export default plugin
