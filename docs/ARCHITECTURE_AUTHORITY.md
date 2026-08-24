# LearnFlow 架构权威与维护边界

本文规定 LearnFlow 的架构权威、两个维护域的边界和交叉修改流程。设计语义以 `docs/AGENT_ARCHITECTURE_GUIDE.md` 为准；可执行枚举、归属与写权限以 `backend/app/services/architecture_registry.py` 为准；实现是否符合契约以测试为准。

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
