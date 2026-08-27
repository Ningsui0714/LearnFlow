# LearnFlow 架构权威与维护边界

本文规定 LearnFlow 的架构权威、两个维护域的边界和交叉修改流程。设计语义以 `docs/AGENT_ARCHITECTURE_GUIDE.md` 为准；可执行枚举、归属与写权限以 `backend/app/services/architecture_registry.py` 为准；实现是否符合契约以测试为准。

Contract impact（`2026-08-27.5`）：计算机知识检索升级为 Search Harness v2。模型仍只看两个目标级只读 ACI：`search_computer_knowledge` 负责 quick/standard/deep 的有界多角度召回、混合确定性重排、覆盖审计和最多一次补搜；`read_web_evidence` 只读取本轮候选中的精确 HTTPS URL，并返回相关原文片段。Provider 熔断、缓存、隐私清理、来源分层、MMR 去冗余、时效评分和研究简报均是 Harness 内部机制，不扩张工具面。两工具都为零 Kernel target；搜索、读取、研究简报和引用均不是学习掌握证据。旧 `{query}` 调用保持兼容，三类主 Agent、五核、事件 schema、数据库和状态机均不变。实现与评测见 `docs/implementation/SEARCH_HARNESS_IMPLEMENTATION.md`、`docs/validation/2026-08-27-search-harness-evaluation.md`。

Contract impact（`2026-08-27.4`）：`SkillSpec v2` 增加可声明的校准维度；费曼复述以受众层次、认知要求、支架强度和表征方式进行显式校准，并产生零 Kernel target 的 `TeachBackDiagnostic`。诊断只保存学习者原话、表面覆盖和一个待验证候选缺口；修订最多围绕该缺口循环两次，最终只能进入独立验证。稳定 Skill/状态 ID、三类主 Agent、五核 schema、评分、纠错和唯一 reducer 写入链均不变。详细契约见 `docs/SKILL_ENGINEERING.md` 与 `docs/CONVERSATION_SKILL_RUNTIME.md`。

Contract impact（`2026-08-27.2`）：学习路径图扩展到 108 个课程节点和 187 条有向关系，补入十二个稳定行业知识域；路线规划改为硬前置闭包、直接软前置和确定性拓扑排序，`co_learning` 不再产生先后约束。层次筛选保留被后续课程依赖的跨层硬前置，并在 UI 标为“补充前置”。检索策略升级为 `vnext-learning-path-retrieval-v3`；个人节点提案只接受 Harness 注入的结构化搜索结果，并通过主题相关性、来源等级和独立来源门槛，模型提供的任意 URL 不再是 provenance。现有事件 ID、Kernel reducer、数据库 schema 和已确认个人节点保持兼容。

Contract impact（`2026-08-27.1`）：学习路径读取拆分为 `vnext_learning_path_exact_reader`、`vnext_learning_path_fuzzy_reader` 与 `vnext_personal_path_node_proposer` 三个正交 ACI；旧 `vnext_learning_path_graph_reader` 只保留为非模型可见的兼容调度器。精确读取只比较稳定 ID、标题和别名；只有未命中才允许确定性模糊排序；歧义必须交还学习者确认；只有明确图谱缺口且存在带 provenance 的外部来源时才能形成个人节点提案。提案为零 Kernel target，正式节点仍须学习者确认并通过既有事件网关写入，没有新增 Kernel writer、事件 schema 或数据库迁移。

Contract impact（`2026-08-26.27`）：新增 `dynamic_practice_generator`、`similar_practice_generator`、`practice_quality_inspector` 三个受限 ACI 与 `dynamic_practice_loop` Playbook。它们只在正式带领学习任务和项目关卡 scope 内生成经过确定性校验、答案安全、心理测量状态为 `uncalibrated` 的 `ConceptQuestion` 集合；生成、检查、打开和纸张接入均为零 Kernel target。正式提交继续复用 `LearningAttempt -> concept_attempt_evaluated -> five_kernel_reducer`，固定写 Knowledge / Practice；仅学习者显式声明的前置卡点或已确认有效帮助可分别补充 Structure / Human。没有新增 Kernel writer 或数据库表，旧练习引用保持兼容。

Contract impact（`2026-08-26.21`）：新增 learner-owned 领域知识底座的只读 ACI、规划态资源策展 Playbook 和 vNext 正式学习文件工作台。领域来源从 Chat 输入区附加，隐藏存储 Project 不形成独立用户工作台；Tutor 请求携带当前对话 source id，从而在对话资料与联网检索之间选择。它们复用现有 `Source/Chunk`、`LearningTask`、`Lecture`、`ConceptQuestion` 与 `Exercise`，不新增长期画像权威或 Kernel writer。来源加入/处理以及学习文件生成/打开/接入纸张均为零 target 审计事件；显式讲义阅读继续是 exposure-only，正式练习提交继续走既有确定性评分与 EvidenceEvent 链。旧项目来源、旧讲义/评估 API 和数据库 schema 保持兼容。详细契约见 `docs/KNOWLEDGE_AND_LEARNING_FILES.md`。

## 1. 权威层级

1. `architecture_registry.py`：三类主 Agent、五核、能力、工具、产品技能、工作台和重要事件的机器可读清单。
2. `AGENT_ARCHITECTURE_GUIDE.md`：角色边界、证据规则、上下文装配和产品空间的规范说明。
3. `learning_runtime.py` 与 `memory_graph.py`：事件归约、五核投影与记忆图谱的运行实现。
4. 领域模块和页面文档：只能细化，不得重新定义上述权威。

运行中的注册表可以从 `GET /api/architecture/registry` 查看；`GET /api/architecture/validate` 返回是否发生注册漂移。注册表包含内容摘要 `digest`，方便演示环境和验收记录固定版本。

## 2. 三类主 Agent 契约

“三类主 Agent”是三个责任接口，不是三个同时争夺用户身份的聊天人格。

| 主契约 | 包含的实现 | 主要输入 | 结构化输出 | 禁止事项 |
|---|---|---|---|---|
| Tutor 控制 Agent | Global Main Agent、Project Tutor、Checkpoint Tutor、Learning Task Runtime | CurrentLearner、页面上下文、有作用域的五核只读投影、近期证据 | 意图、自然回复、Action、Learning Task 协调与 handoff 引用 | 直接写库、宣布掌握、绕过确认策略 |
| 学习设计 Agent | Roadmap、Learning Task Planner、Lecture、Concept、Animation | 项目 brief、任务目标、已处理来源、学习者投影、provenance | 路线提案、可修订任务计划、讲义、评估规格、视觉产物 | 未确认应用路线、伪造来源、写五核 |
| 实践与验证 Agent | Exercise、Code、Remediation renderer | 评估规格、提交、测试结果、错误证据 | 实践任务、反馈、讲解段落 | 选择纠错策略、覆盖确定性评分、写五核 |

纠错讲解中的文字可以由模板或受约束生成器渲染，但教学策略、阶段跳转和通过条件必须来自 `RemediationStrategy` 与确定性评分。

## 3. 五核与记忆上下文

五核是学习者状态的五个互补维度，不是五个 Agent、五张独立画像表，也不是五种可以互相替代的评分。每个核都应同时说明：它回答的决策问题、状态所指向的对象、可接受的证据和不能越界推断的内容。

短期键空间由注册表维护，`learning_runtime.py` 直接导入该定义，避免两份 allow-list 漂移。当前统一结构如下：

| Kernel | 核心问题 | 状态对象 | 典型状态与证据 | 不应越界承担 |
|---|---|---|---|---|
| `structure` | 学习者现在位于哪里，下一步如何走，离开后怎样回来？ | 学习路径、项目、检查点与依赖 | 当前位置、路径转向、阻塞、返回锚点；项目/检查点/来源和导航事件 | 概念掌握、目标动机、情绪或实践能力 |
| `knowledge` | 学习者对哪个概念理解到什么程度，证据支持什么结论？ | 概念、问题、错误推理与理解状态 | 待解问题、知识缺口、近期错误、可定位误解；评分答案、理由和迁移证据 | 仅凭接触、讲解、自述或一次答错宣布掌握/稳定误解 |
| `human` | 在当前情境下，怎样教、怎样交互更合适？ | 学习者当下的负荷、注意、情绪反应与交互偏好 | 明确反馈、持续负荷信号、讲法有效/无效和跨 session 一致偏好 | 从分数或行为单独推断人格、医学状态或固定学习风格 |
| `value` | 为什么学，当前什么目标和投入更值得优先？ | 学习目标、优先级、动机、兴趣与相关性 | 目标候选、优先级陈述、兴趣信号、相关性理由；用户确认的目标 | 用模型猜测替代用户确认，或把目标当成能力证据 |
| `practice` | 能否在给定约束下独立做出来，并迁移到新情境？ | 尝试、辅助、产物、反馈与迁移表现 | `LearningAttempt`、辅助等级、测试/判题、产物、重做与变式结果 | 把有提示成功、原题重做或生成内容等同独立迁移能力 |

五核在决策链中的分工可以概括为：`structure` 决定“走哪儿”，`knowledge` 决定“学什么/哪里没懂”，`human` 决定“怎么教”，`value` 决定“为什么现在学这个”，`practice` 决定“怎样验证能不能做”。它们可以由同一行为分别产生证据，但每个目标都必须有独立理由；一个核的变化不能自动推导其他核的变化。

Contract impact（`2026-08-26.19`）：Knowledge 初始巩固增加一个严格的自述边界。只有同一概念至少两条显式 `learner_concept_observation_recorded` 且全部为 `self_reported` 时，才可形成 exposure-only Module/Claim；Claim 继续标记为 `self_reported`，现有重复评分证据、掌握校验、纠错链和 API schema 均保持不变。掌握校验区分肯定断言和“缺乏掌握证据 / 不代表掌握”等否定边界，后者允许保留但仍不能提供任何掌握升级。worker 还会依据 Claim 的不可变证据闭包确定性归一历史验证标签；全为 self-report Fact 的 Claim 只能显示为 `self_reported`。该规则让学习者可以要求系统长期记住“接触过哪些内容”，但不会把接触经历升级为掌握证据。

长期巩固不是把短期字段复制到长期区，而是按核使用不同门槛：

| Kernel | 长期巩固门槛 |
|---|---|
| `structure` | 稳定路径模式或已确认项目结构 |
| `knowledge` | 被评分证据支持的掌握，或由具体证据支持且可纠正的误解 |
| `human` | 学习者明确确认，或跨 session 的一致证据；情绪和负荷默认短期有效 |
| `value` | 学习者明确确认的长期目标或价值排序 |
| `practice` | 独立完成与变式迁移证据优先，辅助完成只保留为辅助等级与过程证据 |

跨核协作必须保留边界。例如，学习者在实践任务中答错：`practice` 记录失败尝试和辅助等级；只有错误答案或理由足以定位概念问题时，`knowledge` 才记录相应缺口；只有路径确实因此受阻时，`structure` 才记录阻塞；没有明确表达时，不得顺带写入 `human` 或 `value`。

唯一直接写入路径是：

```text
用户/工具/Agent 行为
  -> EvidenceEvent（只追加、带统一 provenance）
  -> five_kernel_reducer（确定性）
  -> KernelMutation + KernelState
  -> MemoryFact -> MemoryModule(Vn) -> MemoryClaim
```

`MemoryModule` 采用不可变版本快照。第一个达到本核巩固门槛的事实集合形成 V1；后续
有意义的新事实作为 delta，与当前版本的证据闭包共同形成 V2、V3。普通增量使用
`REFINES` 连接父版本，学习者纠正使用 `SUPERSEDES`；父 Module 与其 Claim 转为历史
状态，当前 `(learner, kernel, subject)` 只保留一个 active 版本供 `KernelHead` 使用。
每个版本必须公开 `version`、`parent_module_node_id`、`evidence_fact_ids`、
`delta_fact_ids`、`revision_kind` 和 `policy_version`，因此可以完整解释“新结论继承了
什么、增加了什么、替换了什么”。事实仍保持原始来源；同一事实可以通过图边支持
多个 Module 版本，首次消费归属不会被改写。

Module/Claim 异步合成属于默认开启的正常读取投影。worker 启动时会从仍为 `eligible`
的 Fact 重建遗漏的合成队列，再按每核门槛消费；模型供应商不可用时使用同一事实白名单
生成确定性降级摘要。因此已有学习者不会长期停留在“只有 Fact”的不完整图谱状态。

未被 reducer 归入某核的相关事件继续保留在 `EvidenceEvent` 账本中。若未来增加跨事件
模式发现，模式判断必须生成带 `source_event_ids` 的派生 `EvidenceEvent`，再经统一
reducer 形成该核的 Fact；模式分析器本身不直接生成 Module 或修改 KernelState。

五核 v2 在这条权威链之上增加两类可重建读取投影，但不增加事实来源：

```text
KernelState + Memory Graph
  -> KernelHead（每核有界热头部）
  -> ContextPolicy（按 capability / workbench 选择）
  -> FiveKernelRetriever（精确 scope、混合召回、一跳关系）
  -> ContextPacket（带预算、证据清单、冲突与省略说明）
  -> Agent / Skill / Workbench 只读消费
```

`KernelHead` 被清空或重建不会丢失事实；`ContextPacket` 也不是新的长期记忆。它们不能
写 `KernelState`，不能改变掌握、评分或纠错策略。项目、关卡、session 与复习题 scope
必须由服务端确定，跨 scope 内容和答案字段在装配前过滤。详细契约见
`docs/FIVE_KERNEL_MEMORY_FABRIC_V2.md`。

工具和 Agent 只能读取经过 learner/project/checkpoint scope 的投影。它们不能直接更新 `KernelState`，也不能把模型生成的教学内容当成掌握证据。

### 复习调度与事实权威

`ReviewSchedule` 是由 `LearningAttempt`、`RemediationCase` 和已登记事件重建的运行投影，不是第六个 Kernel，也不是第二套掌握事实。全局 `/review` 工作台可以读取题目、历史 Attempt、纠错案例、Knowledge/Practice 的有作用域投影与调度状态，形成 `QuestionLearningState`；但它只有在完成确定性判题后，才可追加 `review_attempt_evaluated`。

```text
原练习 / 复习提交
  -> LearningAttempt(attempt_role=review)
  -> review_attempt_evaluated
  -> five_kernel_reducer -> Knowledge / Practice
  -> ReviewSchedule 重投影
```

跳过、延期、暂停和恢复是零 kernel target 的运行事件。`review-policy-v1` 使用固定 `1/3/7/14/30/60 天`阶梯；失败、辅助、独立成功和已校验变式只改变可审计调度，不自行宣布掌握。长期稳定至少需要两次相隔 72 小时的独立复习成功，且至少一次来自已校验变式。稳定后再次失败只增加风险与重新调度，不删除历史证据或长期声明。

`concept-proficiency-v1` 在此权威链上增加可重建的熟练度与 D/S/R 读取投影。它使用作答可靠性、当前可提取性、独立性、变式迁移和间隔稳定性，并以确定性证据上限阻止一次答对或辅助成功变成“掌握”。当前 D/S/R 参数是显式标注的冷启动代理，不是已经按个人日志训练的 FSRS。具体误解、有效启发、独立完成与学习者反思以带 provenance 的记忆条目呈现；学习者反思仍是待验证、可纠正且不升级掌握的 Knowledge 证据。详细公式、论文依据与工具边界见 `docs/REVIEW_EVIDENCE_MODEL.md`。

Contract impact：注册表版本提升到 `2026-08-26.18`。`/review` 工作台显式登记 `evaluate_transfer_variant`，统一提交入口按服务端拥有的 `RemediationCase` 状态确定性路由普通检索、原题重做与迁移变式；浏览器不再选择私有判题端点。复习、反思和纠错事件补充共享 ConceptAnchor 坐标，使 Knowledge 事实可重建为个人概念历程。保留既有 ReviewSchedule、Attempt、五核 schema 和旧纠错 API，属于向后兼容的行为修复。

### Chat Mode 与学习动作

Tutor 在每段 Chat 中使用四个显式但粗粒度的运行形态：`free / explain / learn / plan`。
它们都是 `tutor_agent` 的可恢复交互姿态，不是新的 Agent。`free` 负责开放探索与意图收敛；
`explain` 负责一次边界清楚的直接讲解且不自动创建任务；`learn` 负责围绕同一
`LearningTask` 灵活组合讲解与其他 Skill；`plan` 负责跨多个任务、来源、阶段或真实产物的
目标并优先形成项目。项目和关卡是 Session scope，不是第五种模式。

模式选择由 `chat_mode_runtime` 的确定性规则完成并保存在 `AgentSession.context_summary`，
LLM 只能在模式边界内生成表达。`chat_mode_entered` 是零 target 的运行事件；一次非自由模式
结束或转向时追加 `learning_action_segment_completed`，把该段的目标、消息边界、Skill、任务、
项目提案和产物引用经 reducer 投影为可恢复学习动作。讲解段只形成 Knowledge exposure 并固定
`mastery_unchanged`；只有明确的 learn/plan 目标才形成短期 Value 投影，不能自动巩固长期目标。

普通 LearnFlow 对话的跨浏览器权威是 learner-owned `AgentSession + AgentMessage`。浏览器
`localStorage` 只缓存未发送草稿、已开标签、并排布局和纸张工作台等 UI 状态；对话目录、标题和主纸消息
通过 `vnext_chat_session_store` 幂等归档到正式后端。该 adapter 不运行第二个 Tutor、不产生
`EvidenceEvent`，也不把聊天持久化视为学习暴露或掌握；需要进入五核的模式、学习动作与评估仍走各自已
登记的事件入口。旧浏览器本地对话在首次连接时以 `client_conversation_id` 安全迁移，多个浏览器随后读取
同一正式目录。

### LearnFlow Chat 的工具与选中追问

LearnFlow Tutor 回合由稳定 ID `vnext_agent_turn_runtime` 统一编排为有界 Turn Graph：

```text
ContextEnvelope
  -> observe（正式五核；规划态再读学习路径）
  -> decide（模型可回答或选择已登记原生工具）
  -> act（只读/产物工具）
  -> observe（结构化 ToolMessage）
  -> decide ...
  -> verify / finalize
  -> AgentTurnTrace
```

单回合最多 5 次模型决策、8 次工具调用并共享 90 秒 deadline；重复调用被阻断，暂时性模型错误
只允许在剩余 deadline 内重试一次。正式五核读取不再把 JSON 截断片段塞进提示，而是形成有 scope、
有预算、答案隔离的语义投影；历史工具观察以有界摘要进入下一回合。原生 ACI 按对话状态和 scope
动态过滤：基础观察包含五核、学习工作区、学习路径、计算机知识搜索和安全视觉产物；带领学习态且存在正式
`LearningTask + checkpoint` 时才额外开放动态出题、同构变式和题目质量检查。任何五核、个人节点、长期路线、
通用任务或任意文件写入能力仍由确定性 runtime 和显式确认控制。

传输层采用“即时输入确认 + 可撤销流式草稿 + 校验后持久化”：页面不等待正式上下文同步才显示用户消息；
Chat Completions 与 Responses 的原生文本增量直接形成 `text_delta`。模型改为调用工具、重试、校验回退
或草稿与最终正文不一致时必须发送 `text_reset`，因此 UI 不会把前一模型轮的工具前导语拼进最终答案。
只有通过 verifier 的最终正文写入正式消息；流式草稿不进入 EvidenceEvent、五核或 Memory Graph。

Contract impact（Tutor streaming transport）：`AgentTurnTrace` 仅增加向后兼容的可选 timings，流式联合类型仅增加
`text_reset` 分支；没有数据库迁移、工具/Skill/Event 注册变化，也没有新增 Kernel writer。

注册表中的 `TOOLS` 保留稳定 ID 以兼容既有 API，同时增加正交分类：`aci_tool / harness /
projection / policy / adapter`。只有 `aci_tool` 可以成为模型工具；`vnext_agent_turn_runtime`、
任务/规划 runtime 是 Harness，`five_kernel_reducer` 和 Memory Graph 是投影基础设施，不得冒充
Agent 动作。`SKILLS` 同样区分 `pedagogical_method / playbook / coordination_skill`：学习方法
定义局部教学转换，Playbook 组合多个能力完成闭环，二者不得用同一职责解释。

Contract impact：注册表版本提升到 `2026-08-26.25`。`frontend/` 成为唯一产品前端，原 vNext 稳定 ID
只作为 API、事件和持久化兼容标识保留，不代表第二套运行时。Web 与 Tauri 共享同一构建；桌面端通过
启动时注入的 sidecar 地址和 token 使用同一正式 API。没有数据库迁移、事件 schema 变化或新增
Kernel writer。

前一版本 `2026-08-26.24` 新增 `vnext_chat_session_store` adapter 与
向后兼容的 Session 创建/消息同步字段；既有 Session、Tutor turn、SkillRun、项目会话和五核 API 不变，
无需数据库迁移，没有新增 Kernel writer。普通对话删除继续复用 `workspace_lifecycle`，保留追加式学习证据。

Contract impact：注册表版本提升到 `2026-08-26.14`。新增只编排上下文的
`coordinate_vnext_agent_turn` capability 和 Harness 登记；所有既有稳定工具、Skill、事件与 API
保持兼容，没有新增 Kernel writer。浏览器 `LearningTask` 对象被明确为正式任务绑定或离线回退，
浏览器 `LearningPlan` 被明确为 Planning Dialogue；正式长期路线仍只有 `LearningPathPlan`。

### vNext 正式运行权威闭环

vNext 的生产回合只经过一个 `vnext_agent_turn_runtime`：模型原生选择 ACI，工具观察以正式
ToolMessage 回灌，并由确定性终态校验器拦截“未确认却声称已写入”、无证据掌握结论、隐去工具失败
和缺少来源链接。旧的预调用工具流水线已删除，不再与原生循环竞争决策权。

带领学习态以正式 `AgentSession -> LearningSkillRun -> LearningTask` 为运行权威。浏览器建立或恢复
Session，启动 SkillRun 后绑定其自动建立的 LearningTask；后续学生输入调用
`POST /api/agent/sessions/{session_id}/skill-runs/{run_id}/turns`，由确定性 Skill runtime 推进。
该端点不再调用 Tutor LLM，不生成第二份回答；浏览器步骤事件只是显示缓存，离线时才成为明确标注的
回退。点击“下一步”不能绕过 learner-reply gate，“不知道/换一种支架”停留在当前步骤。

学习规划通过 `LearningGraphAlignmentProjection` 显式连接官方课程图、个人课程覆盖层、个人概念图、
项目来源知识领域与已确认长期路线。每条 Alignment 记录图类型、对象 ID、匹配方式、置信度与依据；
未匹配对象保留为 gap，所有 Alignment 固定 `carriesMastery=false`。图的身份对齐因此可检查，但不会
把课程自报、仓库主题或路径目标转换成 Knowledge 掌握。

Contract impact：注册表版本提升到 `2026-08-26.15`。新增 SkillRun 确定性 turn API 与四图对齐
只读投影，收紧 vNext 浏览器绑定语义和终态校验；既有稳定 Agent、Skill、Event ID、LearningTask API
与五核写入链保持兼容，无数据库迁移、无新增 Kernel writer。

vNext 的 `read_learning_workspace` ACI 现在消费正式的学习工作区观察投影。后端按
learner/session/project/checkpoint 验证作用域，结构化返回近期 `LearningAttempt`、开放
`RemediationCase`、`ReviewSchedule` 队列和当前项目已处理来源的知识领域；投影过滤提交正文、答案、
solution 与测试用例。项目知识领域产生显式 `sourceConstraint`，只约束当前项目路线与讲解；Attempt
仍是 Practice/Knowledge 证据，ReviewSchedule 仍只是可重建调度，二者不会被来源覆盖或任务完成替代。

Contract impact：注册表版本提升到 `2026-08-26.16`。扩展既有
`vnext_learning_workspace_reader` 的只读输出和新增 answer-free 查询端点；稳定工具、Capability、
事件、数据库 schema、五核 reducer 与 writer 均保持兼容，没有新增模型可调用写工具。

正式前端 `frontend/` 登记三个零 Kernel 写入能力：`search_computer_knowledge` 先确定讲解/对比/排错/实现/研究/时效意图和证据角度，再按“规范与官方文档、教材与大学课程、论文、社区实践、代码仓库”分层召回和确定性重排；网页片段始终视为不可信输入，社区或仓库不得覆盖高层来源。`generate_learning_visual` 只接受结构化图计划，由本地代码生成消毒后的静态 SVG 或确定性 SVG 帧；`open_selection_followup` 按主对话、祖先纸、当前纸装配分支上下文。工具调用、搜索与讲解、图解、动画与纸张都不是掌握证据，也不建立第二套学习者状态。

Contract impact：注册表版本提升到 `2026-08-25.3`。`computer_knowledge_search` 的稳定 ID、owner、能力入口和零 Kernel 写入边界保持不变；其内部契约从“来源路由 + 实时适配器”收紧为“意图/证据角度规划 → 分层召回 → 确定性重排 → 有界不可信 Evidence Bundle”。没有新增 Agent、EventContract、Kernel writer 或既有 API 破坏。

vNext 通过 `vnext_learning_task_runtime` 在同一 Chat 中编排原子学习任务。明确请求或手动选择进入
`guided_learning`；四种已登记 Skill 各自拥有确定性步骤、循环和支架。Skill 步骤仍是零 Kernel
导航事件，但任务的创建、开始、暂停、恢复、取消、重开和流程完成同步到正式 LearningTask API，
并进入全局任务队列。模型只收到当前 Skill 步骤和有预算五核 ContextPacket。普通回复不切换步骤，
“不知道/要提示”留在本步。任务完成只表示流程里程碑；正式掌握仍必须走
`LearningAttempt -> EvidenceEvent -> reducer` 契约。

Contract impact：注册表版本提升到 `2026-08-25.5`，新增零 target 的
`vnext_learning_skill_step_entered` 与 `vnext_learning_skill_looped`。旧的
`vnext_learning_task_phase_entered` 保留为只读兼容事件，v0.5 浏览器任务会确定性映射到当前
Skill 的近似步骤；新任务不再写通用四阶段事件。既有三 Agent、五核、后端 LearningTask API、
Skill 稳定 ID 和模型 API 均保持兼容。

vNext 的只读工具 `vnext_five_kernel_profile_reader` 已收敛为正式 `five_kernel_retriever` 的前端入口。
它按问题、Tutor mode、LearningTask 与当前 Skill 请求有预算的跨核 ContextPacket，不读取浏览器
模拟画像；敏感 Human Claim 只能转成静默适配指令。Reader 不写任何 Kernel、不声明掌握，且
Global Tutor 允许深读五核但仍受 ContextPolicy、scope、关系展开和 token budget 约束。

Contract impact：注册表版本提升到 `2026-08-25.6`，新增 capability
`read_vnext_five_kernel_profile` 与同名稳定工具登记。既有三 Agent、正式
`five_kernel_retriever`、EvidenceEvent/reducer、后端 API 与 vNext 模型请求均向后兼容；这是一项
vNext 只读能力登记，没有新增 EventContract 或 Kernel writer。

vNext 的教学状态采用单向包含关系：`Tutor 主状态 -> 已绑定 Learning Skill -> 当前 Skill 步骤子状态`。
首批四个 Skill 都只能绑定 `guided_learning`；选择 Skill 只能让下一轮进入带领学习态，不能在自由态
或简单讲解态中独立运行。`vnext_learning_skill_step_entered` 同时投影步骤与可见子状态，例如
`带领学习态 · 引导态`；循环事件保持本步和本子状态。页面与 Tutor LLM 只读该投影，均无权自行转换。

Contract impact：注册表版本提升到 `2026-08-25.7`。此次只把既有 Skill 步骤收紧为显式子状态契约，
复用既有 `vnext_learning_skill_step_entered` 和浏览器本地事件队列；稳定 Skill ID、EventContract、
后端 API、三 Agent 与五核写入链均向后兼容，没有新增 Kernel writer 或掌握语义。

vNext 现有第四种 Tutor 姿态 `learning_plan`。确定性规则只把跨多个任务/阶段、较复杂真实产物，
以及职业、科研和长期方向问题送入规划态；原子目标仍进入 `guided_learning`。规划态投影
`project_seed` 或 `direction` 草案。前者只收集项目启动信息，当前不得生成项目 ID、
关卡或文件夹；后者可以提出 Value Claim 候选，但必须展示当前内容、建议、学生原话依据和作用域，
并等待接受、修改或拒绝。拒绝和未确认候选不写 Value；接受由 `confirm_value_claim` capability
追加正式、带作用域的确认事件，再经过 `EvidenceEvent -> five_kernel_reducer -> KernelMutation`。
Tutor、UI 与规划模型都不能直接改长期 Value。

Contract impact：注册表版本提升到 `2026-08-25.8`，新增 `vnext_learning_plan_runtime`、capability
`run_vnext_learning_plan` 与八个浏览器本地零 target 规划事件。既有三 Agent、正式项目 API、
LearningTask、Value reducer、模型 API 和 Skill ID 均向后兼容；当前没有新增 Kernel writer，
也没有把本地候选确认视为正式 Value Claim 写入。

vNext 使用三段式路径检索。`vnext_learning_path_exact_reader` 先对版本化官方课程 DAG 与正式个人
覆盖层做稳定 ID、标题和别名等值匹配；只有未命中时，`vnext_learning_path_fuzzy_reader` 才做
拼写、词法、主题三个独立排序并进行确定性 rank fusion。结果必须显式区分 `resolved`、`ambiguous`
和 `not_found`：歧义只能请求学习者选择，不能生成路线；复合主题也不能因为包含较短课程名而被
错误折叠。`vnext_learning_path_graph_reader` 仅作为兼容调度器存在，不向模型暴露。

只有 `not_found` 被判为图谱缺口后，Tutor 才能搜索外部来源，并调用
`vnext_personal_path_node_proposer`。Harness 只把刚刚实际取得的结构化搜索结果注入工具元数据；模型参数
不能自行提供 provenance。提案器确定性检查主题相关性、来源等级、独立主机数量、重复节点和快照 ID，
不满足门槛时返回可观察失败，不生成占位节点。合格提案仍然可拒绝，且不改图、不改
掌握度、不写五核。`vnext_personal_path_node_runtime` 只接受学习者点击确认后的自报状态或个人节点
变更，并通过正式事件网关落盘。完整检索契约、阈值和评测矩阵见
`docs/LEARNING_PATH_RETRIEVAL.md`。

路线规划使用 `vnext-learning-path-planner-v2`。目标必须先被检索为唯一节点；规划器随后闭包收集硬
前置、加入目标的直接软前置，并对诱导子图做确定性拓扑排序。硬前置和软前置都必须位于后继之前，
`co_learning` 只表示适合并行学习，不参与拓扑约束。高职、本科、研究生筛选展示各自课程集，同时
递归保留可见课程依赖的硬前置；这些跨层节点必须标为“补充前置”，不能静默隐藏或冒充该层主课。

`/learning-path` 负责图谱查看、筛选、自报标记和个人节点管理，`/learner-profile` 负责分核展示
正式 KernelState、MemoryFact、Module/Claim 及路径摘要，`/tasks` 负责正式原子任务队列。三者
继续使用 vNext 多页签和并排容器，不新增主 Agent。路径状态与个人节点通过三个正式事件投影：
`vnext_learning_path_node_status_set`、`vnext_personal_path_node_added`、
`vnext_personal_path_node_removed`。正式网关校验 learner scope、所有权、稳定节点和 allow-list，
然后统一调用 `record_event()`。自报“学过/掌握”更新 Structure，最多在 Knowledge 记录
self-reported exposure，不能生成 mastery。

Contract impact：注册表版本提升到 `2026-08-25.11`。新增正式学习者状态网关、记忆管理工具、
任务队列工作台及五核内容策略元数据；原有 API、稳定事件 ID、正式五核写入链、三类主 Agent 和
vNext 浏览器工作区均向后兼容。浏览器路径状态继续作为离线缓存，联网后由正式投影覆盖；没有
数据库 schema 迁移。

### 个人概念学习图投影

Knowledge 与 Structure 现在通过稳定 `concept_key` 共享 `ConceptAnchor` 身份坐标，并分别拥有
`KnowledgeProjection` 与 `StructureProjection`。前者保存概念内部的接触、定义理解、例子、题目、
错误、纠正、回忆、变式和迁移历程；后者只保存硬/软前置、阻碍、推动、联想、类比、易混淆、共生、
应用、返回锚点和迁移关系。该图直接从 EvidenceEvent、KernelMutation 与 MemoryFact 重建，不增加
数据库长期权威表，也不改变 Module/Claim 门槛。

`ConceptAnchor.official_node_id` 以及稳定 key/名称/别名可以确定性投影为 `ConceptPathAlignment`。
该投影只说明个人概念节点与官方课程节点的身份对齐、匹配方式和置信度，不携带掌握度；Knowledge
历程与 Structure 边仍分别归约。这样规划态可以叠加两张图，而无需复制概念结论或建立第三张状态图。

`concept_self_report_gateway` 接受学习者显式提交的原文，产生一个零 target 原文事件，再为每个已
抽取/核对概念和关系追加独立注册事件。所有自述固定为 unverified、`mastery_inference=false`。
`personal_concept_graph_reader` 向 Tutor 和画像页返回有界只读图；`/api/learner-state/context` 同步附带
相关概念子图。v17 启动迁移只把已有 `LearnerProfile.background` 中的明确课程接触投影为自报事实，
不生成掌握或结构关系。

Contract impact：注册表版本提升到 `2026-08-26.12`。新增两个工具、两个 capability 和三个事件；
`registration_profile_completed/profile_updated` 的登记 targets 修正为与既有 reducer 一致的
Knowledge + Human + Value。现有 EvidenceEvent、KernelState、Memory Graph schema 与旧 API 保持兼容，
没有新增 Agent、Kernel writer 或掌握推断路径。

vNext 的规划态现已把正式五核、官方/个人学习路径和长期目标收敛为一个闭环。Tutor 每轮先通过
`vnext_five_kernel_profile_reader` 按 mode 请求 ContextPacket；`learning_plan` policy 会优先读取
Structure、Knowledge、Human、Value 以及当前活动路线。`vnext_learning_path_planner` 只生成可检查
proposal，学习者点击确认后才由 `vnext_learning_path_plan_manager` 追加 commit/revise/archive 事件。
Reducer 把活动路线投影到 Structure，把明确目标投影到 Value；路径页只显示这份正式投影。

五核同时增加学习者明确修订入口 `vnext_five_kernel_explicit_editor`。它不是第二个 writer，而是按核
把操作路由到既有 profile、concept、path plan 与 memory gateway：Knowledge 接受待验证背景/概念
自述，Structure 接受关系与路线，Human 接受明确节奏偏好，Value 接受经确认方向，Practice 只允许
纠正已有认识或提交可验证产物，不能靠自述升级能力。

Contract impact：注册表版本提升到 `2026-08-26.13`。新增长期路径 planner/manager 和五核明确修订
工具登记，新增三个长期路径事件，并为 ContextPacket 增加 `learning_plan` policy。`profile_updated` 与
`career_goal_confirmed` 的 capability owner 收敛到显式画像编辑入口；事件 ID、API schema、三类 Agent、
五核唯一 writer 和既有数据均向后兼容。长期路线使用既有 JSON 投影，不需要数据库 schema 迁移。

五核内容策略由注册表公开，避免“所有核都长成同一种摘要”：Structure 使用稀疏锚点 Claim，
Knowledge 使用证据声明，Human 使用交互指令，Value 使用经同意的目标声明，Practice 使用带产物、
辅助等级和迁移证据的表现声明。每个策略分别声明 Fact/Module/Claim 的对象角色、共享主题和硬边界；
worker 在生成后再次执行确定性越界校验，拒绝 Structure 掌握、Human 人格/医学标签、未确认 Value
长期目标和无验证 Practice 能力声明。

### Learning Task 与双队列

`LearningTask` 是对话、项目关卡和可验证微学习共用的学习执行基础设施。它表达学习者
准备完成的一个原子学习目标、AI 生成且可修订的阶段计划、暂停点、受管产物引用和验证
交接，不是第四类主 Agent、不是记忆对象，也不替代后台执行用的旧 `Task`。

```text
Tutor 识别或用户创建任务
  -> proposed（Tutor 推荐时必须等待接受）/ queued
  -> Learning Design 生成 coarse plan
  -> active <-> paused
  -> 讲解 / Skill / 受管讲义 / Practice 验证按需组合
  -> completed（仅流程里程碑）
  -> ReviewSchedule（若已有合格 Attempt）
```

任务计划只规定 `learn / practice / verify / consolidate` 等粗阶段，不把一次学习固化成
大量细碎关卡。每次改计划都写入不可变 `LearningTaskPlanRevision`，已完成阶段必须保留；
生命周期动作使用乐观版本和幂等动作 ID。Tutor 提议任务必须停留在 `proposed`，只有学习者
明确接受后才能进入学习任务队列。项目每个 Checkpoint 唯一对应一段 checkpoint Session
和一个 Learning Task；项目仍是面向真实产物的学徒旅程，任务只是关卡执行单元。

`/tasks` 只管理待接受、待完成、进行中和历史任务的顺序、暂停、恢复和返回锚点，不执行
教学、重规划或材料生成；对话任务回原 Chat，项目任务回原关卡。`/review` 继续显示由确定性调度生成的
复习任务。两者是并列队列，不把复习降级为普通待办。`LearningTask` 完成及其计划事件均为
零 Kernel target；只有 `LearningAttempt`、判题、纠错和复习事件可以形成能力证据。受管
讲义、练习和题目仍以现有 `Lecture / Exercise / ConceptQuestion` 为权威，任务只保存引用。
完整对象、状态、API 与迁移见 `docs/LEARNING_TASK_RUNTIME.md`。

### 对话与项目的工作区删除

学习者可以从 Explorer、项目列表或项目工作台删除独立对话和项目。删除必须先显示对象名称、
影响范围和二次确认；前端按钮与 API 统一使用 `workspace_lifecycle`：

- `delete_conversation` 只处理 global Session。对话从活动列表移除，关联的未完成 LearningTask、
  SkillRun、待确认 Action 和项目提案终止；项目/关卡 Session 必须由所属项目统一管理。
- `delete_project` 将项目、关卡、来源和学习文件从活动工作区移除，并终止项目内未完成任务、
  Session、生成任务和本地 Agent 运行。项目绑定的本地目录本身不被删除。
- 删除使用 `AgentSession.status=deleted` 与 `Project.visibility=deleted` 作为可审计 tombstone。
  `LearningAttempt`、`ReviewSchedule`、`EvidenceEvent`、KernelState 和 Memory Graph 历史不被
  反向擦除；删除不是新的遗忘协议，也不能改变掌握结论。
- `conversation_deleted` 与 `project_deleted` 只记录经过确认的工作区操作，Kernel target 为空。

Contract impact：注册表版本提升到 `2026-08-25.1`，新增一个零 Kernel 写入的生命周期工具、
两个 capability 与两个运行事件。既有 `DELETE /api/projects/{id}` 路径保持兼容，但语义从物理
级联删除收敛为证据安全的工作区删除；列表与所有受保护读取接口继续把已删除对象视为不存在。

### vNext 项目学徒旅程

`/projects` 与 `/projects/:projectId` 复用正式 `Project -> Roadmap -> Checkpoint` 权威，不建立
浏览器本地项目模型。新项目先只固定主题、学习目标和真实产物，并创建唯一的项目 Tutor；空项目
不得预填假关卡。项目 Tutor 固定处于学习规划态，先读取当前项目的五核投影、来源、关卡、正式
LearningTask 与受管学习文件。只有 `project_tutor` Session 能通过 `project_roadmap_reader` 读取完整
关卡 DAG，并通过 `project_roadmap_proposer` 返回类型化创建或修订提案。没有路线时 reader 返回带
`revision=0` 的空图，不把空状态当异常。只有学习者
明确点击确认后，`roadmap_applied` 才能一次性物化关卡 DAG、关卡 Session 和对应 LearningTask。

路线修订使用完整图提案和乐观 `expected_revision`。已经进入学习或完成的关卡及其顺序、前置边、
目标和成功标准全部锁定；只有 `not_started` 关卡可以修改、重排、增加或归档。确认后由
`roadmap_revised` 写 structure 投影；被归档关卡的活动 LearningTask 通过正式任务事件取消。项目
自由对话和关卡对话均不暴露路线 reader/proposer，防止一般讨论越权改变项目结构。

每个关卡对话固定绑定 `learner_id + project_id + checkpoint_id + learning_task_id`，自然进入带领
学习态；项目自由对话只能由学习者显式创建，读取同一项目上下文但不会自动推进关卡。项目 Tutor、
关卡对话和自由对话都是 `tutor_agent` 的不同 scope，不是新的主 Agent。

项目来源正文属于不可信数据，只能由 `project_source_reader` 返回有 provenance 的有界片段；项目
对话输入栏与项目侧栏复用同一 `Source/Chunk` 接口，所有项目会话观察同一来源集合，不建立对话级
影子附件。讲义
与练习由 `project_learning_file_proposer` 先形成待确认提案，确认后复用正式文件生成服务。讲义可
打开为标签页或附加为对话纸张；阅读只形成接触，生成和打开均不形成掌握。练习答案保持服务端
隔离，只有正式提交产生的 LearningAttempt 才能进入证据链。

项目行为的五核边界如下：`project_created` 可把明确目标写入 value 并建立 structure 项目锚点；
`roadmap_discussed` 只能写未确认的短期 structure 提案；`roadmap_applied/roadmap_revised` 只写已确认路线、当前位置
和返回锚点；自由对话创建、来源移除和文件打开是零 kernel target。任何项目模型输出都不能直接
写 `KernelState`。

`learning-task-runtime-v2` 在每次读取时从受管产物、同 scope Attempt 和 ReviewSchedule
确定性重建 `materials / current_phase / next_action / evidence`。讲义或题目生成只建立材料，
查看材料只形成接触证据，复述形成诊断证据，只有判题成功的独立 Attempt 才能通过 verify，
只有已有 ReviewSchedule 才能通过 consolidate。浏览器、Tutor LLM 和任务生命周期动作均
不得手工推进这些证据阶段。

交互路径上的模型调用是有时间预算的可选增强：Tutor 的结构化输出与纯文本兼容重试共享
同一个总截止时间，任务计划和学习包生成各自使用独立截止时间。超时、供应商失败或输出
校验失败时，服务端返回并持久化同一契约下的确定性计划或学习材料；降级来源可以被检查，
但不能形成掌握证据，也不能改变评分、纠错、复习或五核语义。

对话中的 `user_message` 可携带 `learning_task_id` 作为 scope 链接，reducer 仍只依据真实
消息内容处理 goal、缺口、负荷或偏好等语义；任务创建、接受、开始、暂停、物化和完成事件
保持零 target。Session 负责对话连续性，LearningTask 负责流程位置，五核负责学习者证据，
三者是相互引用而非相互复制的权威。

### 可验证微学习与流程投影

`/agent` 与 `/agent/:sessionId` 是独立学习对话空间。学习者可以拥有多段 global Session，
项目则是对话可以创建、进入或挂载的长期上下文，不是开始学习前的必选入口。清晰讲解、
苏格拉底追问、费曼复述和示例渐隐等学习方法由当前 Session 调用；选择结果保存在 Session 上，
`learning_skill_selected` 只记录零 Kernel target 的操作事实，不构成偏好巩固或掌握证据。
Tutor 可以推荐已登记 Skill，但未得到用户选择时不得声称已经切换。

四种首批方法都使用 Session 范围的 `LearningSkillRun` 确定性状态机，并在启动时绑定同一
learner-visible `LearningTask`：状态迁移、轮次预算、暂停恢复、任务同步和验证准入不由
LLM 决定。运行事件及任务同步事件的 Kernel target 全部为空；
对话回答、追问和复述只用于教学与诊断。达到 `verification_ready` 后，学习者必须主动
在同一任务上创建既有 `MicroLearningRun` 附件，随后才由 `LearningAttempt`、纠错和复习链产生能力
证据。详细状态、API、迁移和初步对比见 `docs/CONVERSATION_SKILL_RUNTIME.md`。

运行时必须把“不会/不知道”、请求解释、跳过和仅确认与可检查尝试分开；前几类输入不消耗
有效引导轮次、不推进 Skill 状态，只触发当前步骤的最小支架。陌生主题中的苏格拉底或费曼
调用必须先建立知识起点。SkillRun 与其绑定的 LearningTask 是同一闭环的教学状态和任务状态，
在对话中不得渲染成两套并行下一步。

`/learn/:runId` 是 Learning Task 可以按需物化的学习文件工作台附件，由 Tutor 控制 Agent 所有，并通过
`verified_micro_learning` 产品技能编排学习设计、费曼复述诊断、确定性判题、既有纠错
和复习调度。明确的“15 分钟/微学习/可验证学习”请求可以直接启动它；普通原子学习则先
形成 Learning Task，由 Tutor 在原对话中自由教学，必要时再物化该附件。附件中的 Tutor
必须复用原 `session_id`；使用后主返回锚点也是原对话或原关卡。它不是第四类主
Agent；内部创建的单关卡 Project 只提供 learner/project/checkpoint/session scope，标记为
`task_artifact/internal`，不出现在真实项目列表中，用户无需先配置项目。

`MicroLearningRun` 只保存可恢复步骤和 answer-free 的 UI 投影。题目结果以 `LearningAttempt` 和 `concept_attempt_evaluated` 为权威，纠错以 `RemediationCase` 为权威，后续计划以 `ReviewSchedule` 为投影。`teach_back_analyzed` 只写诊断缺口并固定 `mastery_unchanged`；`micro_learning_completed` 是零 kernel target 的运行里程碑。微学习题在同一轮的多次正确不能直接形成稳定掌握，跨时间稳定规则仍由 `review-policy-v1` 裁决。微学习契约见 `docs/MICRO_LEARNING_MVP.md`，对话 Skill 运行契约见 `docs/CONVERSATION_SKILL_RUNTIME.md`。

### 用户成长只读投影

`/growth` 将个人资料、五核当前状态、Memory Fact 依据、复习待办、重大事件和 Badge
合并为用户可理解的“我的成长”工作台。它只读取现有权威数据，不创建第二套画像，
不直接写 `KernelState`，也不改变掌握、评分、纠错或复习策略。

默认界面使用“正在进行、理解情况、实践表现、学习节奏、目标与兴趣”等用户语言，
不展示 Kernel 名称、节点 ID、predicate、原始置信度或 JSON。归档和恢复仍走已有
`memory_archived` / `memory_restored` 事件链；这只改变后续是否参考该内容，不删除
历史 EvidenceEvent、Attempt、重大事件或 Badge。`/profile` 与 `/memory` 保留为兼容
跳转，避免旧书签和已保存工作区标签失效。

## 4. 两个维护域

### 维护域 A：主要架构与记忆权威

维护范围：

- 三类主 Agent 的请求/结果边界和身份边界。
- 五核短期键、长期巩固门槛、上下文装配与 handoff。
- EvidenceEvent schema、确定性 reducer、Memory Graph 和可纠正历史。
- learner ownership、幂等、证据等级与通过条件。

### 维护域 B：工具、产品技能、工作台与流程事件

维护范围：

- Action Board handler、来源处理、RAG、生成器、代码执行器和外部工作流 adapter。
- 路线规划、教学产物、实践验证、纠错等产品技能的实现。
- `/agent/:sessionId` 带轻量工作台的独立对话、`/tasks` 纯管理任务队列、`/learn/:runId` 学习文件附件、项目、讲义、练习、纠错、全局复习、`/growth` 我的成长、demo 等工作台。
- 工具运行状态、页面行为、第三方工作流和比赛演示资产。

### 重合区处理

维护域 B 需要五核信息时，只声明 `reads_kernels` 并消费只读投影；需要改变学习状态时，先在注册表新增或复用 capability 与 event contract，再通过 `record_event` 写证据。维护域 A 的确定性规则决定该事件是否归约、写入哪些核以及能否长期巩固。任何模块都不得创建第二套画像缓存作为权威事实。

仓库来源的目录、章节和文件摘要可以被 `repository_knowledge_domains` 整理为路线规划上下文。它是来源内容约束，不是第六个 kernel，也不是学习者状态：只能帮助学习设计 Agent 选择可覆盖的主题，不能据此推断掌握、跳过验证或直接写入 `KernelState`。

## 5. 标准变更流程

新增工具、产品技能、工作台或重要事件时：

1. 在 `architecture_registry.py` 声明稳定 ID、owner、origin 和允许的五核读取范围。
2. 复用或新增 Action Board capability，明确 side effect、确认策略和 evidence target。
3. 为重要行为注册 EventContract；所有写入经过 `record_event`。
4. 若需要五核变化，在 reducer 中增加确定性规则与测试。
5. 外部工作流输出先校验为 LearnFlow artifact；不得直接写五核或决定纠错状态。
6. 更新架构/融合/比赛文档，提升注册表版本，并运行注册漂移、后端、前端与 demo 验收。

破坏性接口调整必须保留迁移说明。仅增加讲法、模型或供应商 adapter，不应改变 EvidenceEvent 和五核语义。

路线确认后若已物化出可进入的首关，`apply_learning_path` 可以在同一高层事务中立即
触发标准 `checkpoint_entered` 导航事件。这只是结构核的可回放上下文切换，不是自动
开课、自动出题或能力升级；讲义、评估和证据写回仍分别受其自身 Action 与确定性规则约束。

## 6. 桌面工作区的权威边界

`desktop_workspace` 是 Tutor 控制 Agent 所有的产品工作台，不是第四类主 Agent。`workspace_file_service` 可读取和修改用户明确关联的项目目录，但没有五核写权限。

- 普通项目文件以本地磁盘为权威。
- GitHub/网页链接和用户上传文件属于项目参考来源；来源原件与处理缓存保存在应用数据中，不进入项目工作区，也不参与普通文件树。
- 讲义、练习、测试和判题规则以数据库为权威；`.lflecture/.lfexercise` 只是受管引用。
- Agent 修改普通文件必须形成 `WorkspaceOperation` diff，并由用户确认；不能直接写文件。
- `checkpoint` 会话以 `learner_id + project_id + checkpoint_id` 唯一恢复，建立后作用域不可原地切换。
- 同一关讲义和练习显示同一个关卡 Tutor；学习设计与实践验证 Agent 仍是内部能力接口，不成为第四类主 Agent，也不维护另一份聊天历史。
- 关卡上下文只装配本关 brief、分配资源摘要、讲义/练习摘要、项目文件树和本关消息；文件正文必须按需读取，其他关卡资源与聊天不得进入。
- `workspace_linked`、`workspace_change_applied` 属于零 kernel target 的操作事件。
- 普通项目文件只有查看和轻量文本编辑能力，不提供编译、解释器、终端或运行入口。
- `.lflecture/.lfexercise` 是数据库学习对象的逻辑文件入口；讲义修改通过 `base_version` 版本化保存，练习只能修改个人草稿与批注。
- 练习草稿和原有练习“运行”都不写掌握证据；正式提交继续走 `LearningAttempt -> EvidenceEvent`，重复 `client_submission_id` 只产生一次尝试与评估事件。
- 本地代码 Agent 通过独立 `local_agent_broker` 工具接入，它仍由 Tutor 控制 Agent 所有，不构成第四类主 Agent，也不能修改学习对象和五核。Tutor 只提交任务类型、目标、约束和所需能力；Broker 按 capability 与 priority 确定性选择已启用 Profile。
- 本地 Agent 固定经过两次确认：第一次确认只在隔离副本启动；第二次确认才通过 `workspace_file_service` 批量写回。写回前重新校验全部基础 hash，删除和移动必须逐项确认，失败时恢复批量回滚快照。
- `local_agent_started`、`local_agent_completed`、`local_agent_canceled`、`local_agent_result_applied` 是零 kernel target 的操作事件。执行、测试成功或文件写回都不是掌握证据。

桌面令牌、路径规范化、符号链接和恢复规则见 `docs/DESKTOP_WORKSPACE_SECURITY.md`。任何放宽 WebView 文件权限、允许访问 `.learnflow`、或把草稿/运行当作学习证据的改动，均视为架构契约变更。
