# LearnFlow 架构权威与维护分工

本文规定融合仓库的架构权威、两条工作线的边界和交叉修改流程。设计语义以 `docs/AGENT_ARCHITECTURE_GUIDE.md` 为准；可执行枚举、归属与写权限以 `backend/app/services/architecture_registry.py` 为准；实现是否符合契约以测试为准。

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
| Tutor 控制 Agent | Global Main Agent、Project Tutor、Checkpoint Tutor | CurrentLearner、页面上下文、有作用域的五核只读投影、近期证据 | 意图、自然回复、Action、handoff 引用 | 直接写库、宣布掌握、绕过确认策略 |
| 学习设计 Agent | Roadmap、Lecture、Concept、Animation | 项目 brief、已处理来源、学习者投影、provenance | 路线提案、讲义、评估规格、视觉产物 | 未确认应用路线、伪造来源、写五核 |
| 实践与验证 Agent | Exercise、Code、Remediation renderer | 评估规格、提交、测试结果、错误证据 | 实践任务、反馈、讲解段落 | 选择纠错策略、覆盖确定性评分、写五核 |

纠错讲解中的文字可以由模板或受约束生成器渲染，但教学策略、阶段跳转和通过条件必须来自 `RemediationStrategy` 与确定性评分。

## 3. 五核与记忆上下文

五核是学习者状态维度，不是 Agent。短期键空间由注册表维护，`learning_runtime.py` 直接导入该定义，避免两份 allow-list 漂移。

| Kernel | 短期上下文 | 长期巩固门槛 |
|---|---|---|
| structure | 位置、依赖、返回锚点、转向、阻塞 | 稳定路径模式或已确认项目结构 |
| knowledge | 理解、缺口、待解问题、近期错误、误解 | 被评分证据支持的掌握或可定位误解 |
| human | 情绪、负荷、注意、挫败、节奏、讲法偏好 | 用户确认或跨 session 一致证据 |
| value | 优先级、动机、目标候选、兴趣、相关性 | 学习者明确确认的长期目标 |
| practice | 当前尝试、辅助等级、产物、反馈、迁移准备 | 独立完成与变式迁移证据优先 |

唯一直接写入路径是：

```text
用户/工具/Agent 行为
  -> EvidenceEvent（只追加、带统一 provenance）
  -> five_kernel_reducer（确定性）
  -> KernelMutation + KernelState
  -> MemoryFact -> MemoryModule -> MemoryClaim
```

工具和 Agent 只能读取经过 learner/project/checkpoint scope 的投影。它们不能直接更新 `KernelState`，也不能把模型生成的教学内容当成掌握证据。

## 4. 两条工作线

### 工作线 A：主要架构与记忆权威

维护范围：

- 三类主 Agent 的请求/结果边界和身份边界。
- 五核短期键、长期巩固门槛、上下文装配与 handoff。
- EvidenceEvent schema、确定性 reducer、Memory Graph 和可纠正历史。
- learner ownership、幂等、证据等级与通过条件。

### 工作线 B：工具、产品技能、工作台与流程事件

维护范围：

- Action Board handler、来源处理、RAG、生成器、代码执行器和外部工作流 adapter。
- 路线规划、教学产物、实践验证、纠错等产品技能的实现。
- `/agent`、项目、讲义、练习、纠错、画像、记忆、demo 等工作台。
- 工具运行状态、页面行为、第三方工作流和比赛演示资产。

### 重合区处理

工作线 B 需要五核信息时，只声明 `reads_kernels` 并消费只读投影；需要改变学习状态时，先在注册表新增或复用 capability 与 event contract，再通过 `record_event` 写证据。工作线 A 决定该事件是否归约、写入哪些核以及能否长期巩固。双方都不得在自己的模块内创建第二套画像缓存作为权威事实。

## 5. 标准变更流程

新增工具、产品技能、工作台或重要事件时：

1. 在 `architecture_registry.py` 声明稳定 ID、owner、origin 和允许的五核读取范围。
2. 复用或新增 Action Board capability，明确 side effect、确认策略和 evidence target。
3. 为重要行为注册 EventContract；所有写入经过 `record_event`。
4. 若需要五核变化，由工作线 A 在 reducer 中增加确定性规则与测试。
5. 外部工作流输出先校验为 LearnFlow artifact；不得直接写五核或决定纠错状态。
6. 更新架构/融合/比赛文档，提升注册表版本，并运行注册漂移、后端、前端与 demo 验收。

破坏性接口调整必须保留迁移说明。仅增加讲法、模型或供应商 adapter，不应改变 EvidenceEvent 和五核语义。

## 6. 桌面工作区的权威边界

`desktop_workspace` 是 Tutor 控制 Agent 所有的产品工作台，不是第四类主 Agent。`workspace_file_service` 可读取和修改用户明确关联的项目目录，但没有五核写权限。

- 普通项目文件以本地磁盘为权威。
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
