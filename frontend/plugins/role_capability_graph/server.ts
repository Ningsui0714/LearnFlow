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

const candidateSchema: PluginJsonSchema = {
  type: 'object',
  properties: {
    artifactKind: { type: 'string' }, artifactId: { type: 'string' }, status: { type: 'string' },
    contentHash: { type: 'string' }, baseSnapshotId: { type: 'string' }, expectedRootHash: { type: 'string' },
    roleTitle: { type: 'string' }, data: { type: 'object' },
  },
  required: ['artifactKind', 'artifactId', 'status', 'contentHash', 'roleTitle', 'data'],
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
objects.push(
  {
    type: 'role_build_candidate', title: '岗位冷启动候选', description: '尚未发布的冷启动契约、阶段状态、输入边界与校验门槛。',
    schemaVersion: ROLE_OBJECT_SCHEMA_VERSION, schema: candidateSchema,
    validate: (value: PluginJson) => /^[a-f0-9]{64}$/.test(String((value as Record<string, unknown>).contentHash || '')) ? [] : ['contentHash must be a SHA-256 digest'],
  },
  {
    type: 'role_iteration_candidate', title: '岗位迭代候选', description: '固定基线快照的迭代契约、工作组合、候选 patch 与验收门槛。',
    schemaVersion: ROLE_OBJECT_SCHEMA_VERSION, schema: candidateSchema,
    validate: (value: PluginJson) => /^[a-f0-9]{64}$/.test(String((value as Record<string, unknown>).contentHash || '')) ? [] : ['contentHash must be a SHA-256 digest'],
  },
)

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
      {
        id: 'start_role_cold_start', title: '启动岗位冷启动', description: '把岗位目标、受众和已有来源整理为可审查的冷启动候选合同；明确任务屏障、后台语义/事理阶段和发布门槛，但不创建正式快照。',
        whenToUse: '用户要研究尚未安装的岗位、生成新的岗位包，或明确要求开始岗位冷启动时；先收集岗位名称和用途，再调用。',
        whenNotToUse: '已安装岗位的解释应使用只读工具；来源为空时不得声称候选岗位事实已经生成；此工具不能发布或持久化快照。',
        toolClass: 'execution', risk: 'artifact', renderer: ROLE_RENDERERS.buildCandidate,
        inputSchema: {
          type: 'object', additionalProperties: false, required: ['roleTitle', 'purpose'],
          properties: {
            roleTitle: { type: 'string', minLength: 2, maxLength: 120 },
            purpose: { type: 'string', minLength: 2, maxLength: 1000 },
            market: { type: 'string', maxLength: 120 },
            audiences: { type: 'array', maxItems: 8, items: { type: 'string', maxLength: 80 } },
            sourceBriefs: { type: 'array', maxItems: 12, items: { type: 'string', maxLength: 1000 }, description: '最多 12 条已提供来源或工作证据摘要；不能把模型常识放进这里。' },
          },
        },
        outputObjectTypes: ['role_build_candidate'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'], timeoutMs: 5_000,
      },
      {
        id: 'draft_role_iteration', title: '起草岗位快照迭代', description: '固定已安装快照，建立迭代契约、目标邻域、候选变更和确定性验收门槛；只返回候选 patch，不覆盖原快照。',
        whenToUse: '用户要求补全、修复、刷新、核验或深化当前岗位快照，并给出迭代目标或选中对象时。',
        whenNotToUse: '不要用于首次生成岗位包、单纯解释现有对象或直接宣称新版本已经创建。',
        toolClass: 'execution', risk: 'artifact', renderer: ROLE_RENDERERS.iterationCandidate,
        inputSchema: schema({
          prompt: { type: 'string', minLength: 2, maxLength: 4000 },
          targetIds: { type: 'array', maxItems: 60, items: { type: 'string', maxLength: 220 } },
          proposedChanges: { type: 'array', maxItems: 20, items: { type: 'string', maxLength: 1000 }, description: '需要验证的候选变更，不是已接受事实。' },
          initiativeProfile: { type: 'string', enum: ['autonomous', 'co_guided', 'user_directed'] },
        }, ['prompt']),
        outputObjectTypes: ['role_iteration_candidate'], availableInModes: ['free', 'simple_explain', 'guided_learning', 'learning_plan'], timeoutMs: 5_000,
      },
    ],
    skills: [{
      id: 'role_capability_graphing', title: '证据化岗位图谱阅读', description: '固定岗位快照后按问题读取语义、事理与证据，再由 Tutor 综合解释。',
      whenToUse: '学习者讨论职业方向、岗位职责、典型任务、能力结构、知识技能、工作过程或岗位证据。',
      whenNotToUse: '不要用于判断学习者是否掌握、直接规划核心学习路径、生成或迭代岗位包；后两者由各自候选 Skill 负责。',
      instructions: [
        '当前问题涉及职业方向、岗位职责、典型任务、能力结构、知识技能、工作过程或岗位证据时，在回答或追问之前必须先调用本插件工具；不得只读取核心学习路径或依靠通用知识作答。',
        '先把插件返回的 snapshot 描述视为本轮唯一岗位事实版本；回答中不得混用其他快照。',
        '首次介绍岗位或询问“是什么、做什么、需要什么能力”时，第一步调用 role_capability_graph__explore_role；它一次返回足够的岗位全景，取得结果后通常直接回答，不要再机械调用搜索、对象读取和关系图。',
        '只有局部问题没有稳定对象 ID 时才调用 search_role_knowledge；已有 ID 时精确读取；需要岗位中心、任务、能力单元和知识技能逐环展开时用 read_capability_radar；解释局部关系时查询图；解释工作如何发生时追踪事理过程。',
        '涉及重要事实、争议、可信度或时间边界时检查证据。引用对象 ID，并区分 accepted/candidate 与 observed_pattern/documented_norm/inferred_pattern。',
        '最终回答只能使用工具明确返回的 objects、relations 与 grounding 事实，并应就近保留对象 ID。若结果带 relationFacts，关系方向和类型必须逐字服从该列表，不得改名、反向或补造。若要使用模型常识，必须单列为“通用补充（非岗位快照）”；不得把补充伪装成插件结论。',
        '工具的 coverage.partial、omitted、truncated、warnings 和 evidence limitations 必须透明反映在回答中，不能用常识补齐未返回部分。连续追问“这个能力、第二项任务、刚才的场景”时，优先复用最近 ToolRun 保留的 snapshotId 与 focusObjectIds，不要切换快照。',
        '岗位对象和工具结果不是学习者掌握证据。阅读 Skill 不创建、修复、发布或覆盖岗位快照。',
      ].join('\n'),
      tools: ['explore_role', 'read_capability_radar', 'read_role_objects', 'search_role_knowledge', 'query_role_graph', 'trace_work_process', 'inspect_role_evidence', 'audit_role_package', 'list_role_packages', 'compare_role_packages'],
      objectTypes: [...ROLE_OBJECT_TYPES],
    }, {
      id: 'role_cold_start', title: '岗位包冷启动', description: '把模糊岗位目标编排成证据化岗位包的候选构建合同。',
      whenToUse: '用户希望为尚未安装或需要重新研究的岗位启动岗位包生成。',
      whenNotToUse: '只是了解已安装岗位时不要启动；缺少岗位名称和用途时先追问，不得直接构造事实。',
      instructions: [
        '先确认岗位名称、使用目的、市场/受众和用户已经提供的来源；来源内容与模型常识必须分开。',
        '调用 role_capability_graph__start_role_cold_start 生成候选构建合同。把它解释为 ProjectBrief + SourceInput → 任务屏障 → 岗位内核 → 语义补全/事理森林 → 校验的阶段图。',
        'sourceBriefs 只能写用户提供或宿主实际读取的来源摘要；没有来源时必须保留 waiting_sources，不得把候选当作岗位事实。',
        '候选合同可供用户继续补资料和确认范围，但不能声称已创建、发布或持久化不可变岗位快照。',
      ].join('\n'),
      tools: ['start_role_cold_start'], objectTypes: ['role_build_candidate'],
    }, {
      id: 'role_snapshot_iteration', title: '岗位快照迭代', description: '固定当前快照并形成可审查的迭代契约与候选 patch。',
      whenToUse: '用户要求补全、修复、刷新、核验或深化已安装岗位快照。',
      whenNotToUse: '首次冷启动、普通解释或没有可固定基线快照时不要使用。',
      instructions: [
        '固定 packageId + packageVersion + snapshotId + rootHash；从用户选中对象和明确目标建立范围，不得暗中切换基线。',
        '调用 role_capability_graph__draft_role_iteration。候选变更必须逐条标为 proposed，不得先写成已接受事实。',
        '解释结构检查、证据政策、meaningful diff 和核心回归门槛；协议不变量始终检查，软性扩展保持有界。',
        '当前工具只产生候选 patch；它不能批准自己、覆盖原快照或宣称后继快照已发布。',
      ].join('\n'),
      tools: ['draft_role_iteration', 'audit_role_package', 'read_role_objects', 'inspect_role_evidence'],
      objectTypes: ['role_iteration_candidate', 'role_snapshot', 'role_audit', 'role_object', 'role_evidence'],
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
      { id: ROLE_RENDERERS.buildCandidate, title: '岗位冷启动候选', description: '显示冷启动阶段、输入覆盖、任务屏障与发布门槛。' },
      { id: ROLE_RENDERERS.iterationCandidate, title: '岗位迭代候选', description: '显示固定基线、目标邻域、候选 patch 与回归门槛。' },
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
    start_role_cold_start: input => rolePackageRuntime.planColdStart({
      roleTitle: String(input.roleTitle), purpose: String(input.purpose),
      market: typeof input.market === 'string' ? input.market : '中国大陆',
      audiences: Array.isArray(input.audiences) ? input.audiences as string[] : [],
      sourceBriefs: Array.isArray(input.sourceBriefs) ? input.sourceBriefs as string[] : [],
    }),
    draft_role_iteration: input => rolePackageRuntime.planIteration(packageSelector(input), {
      prompt: String(input.prompt), targetIds: Array.isArray(input.targetIds) ? input.targetIds as string[] : [],
      proposedChanges: Array.isArray(input.proposedChanges) ? input.proposedChanges as string[] : [],
      initiativeProfile: (input.initiativeProfile || 'co_guided') as 'autonomous' | 'co_guided' | 'user_directed',
    }),
  },
})

export default plugin
