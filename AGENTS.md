# LearnFlow GitHub 协作与 Codex 工作准则

本文是 LearnFlow 仓库级 Codex 指令，也是团队在 GitHub 上协作的共同基线。适用于仓库根目录及所有尚未提供更具体 `AGENTS.md` 或 `AGENTS.override.md` 的子目录。

目标不是限制模块内部创新，而是保证多人、多 Codex 并行开发时仍共享同一套架构权威、接口契约、证据语义和验收标准。

## 1. 开始任何任务前

Codex 必须先完成以下检查，再提出方案或修改文件：

1. 读取本文件和当前工作目录到仓库根目录之间所有适用的 `AGENTS.md`。
2. 涉及 GitHub 协作、分支、提交、发布或交接时，完整阅读 `docs/GITHUB_COLLABORATION.md`。
3. 读取用户指定的 GitHub Issue、PR 或任务说明，提取目标、范围、验收标准和非目标。
4. 执行 `git status -sb`，识别当前分支及已有未提交改动；已有改动默认属于用户，不得覆盖、删除或重置。
5. 根据任务阅读最少但足够的权威资料。涉及架构或跨模块契约时，至少阅读：
   - `docs/ARCHITECTURE_AUTHORITY.md`
   - `docs/AGENT_ARCHITECTURE_GUIDE.md`
   - `backend/app/services/architecture_registry.py`
6. 涉及五核、学习者状态或证据写回时，继续阅读：
   - `docs/FIVE_KERNEL_MEMORY_GRAPH.md`
   - `backend/app/services/learning_runtime.py`
   - `backend/app/services/memory_graph.py`
7. 涉及学习状态快速获取模块时，完整阅读 `docs/LEARNER_STATE_DISCOVERY_AGENT_BRIEF.md`。
8. 涉及比赛或 seeded demo 时，阅读 `docs/competition/README.md` 与 `docs/competition/DEMO_RUNBOOK.md`。

如果用户的直接指令、GitHub Issue 与现有文档存在实质冲突，停止扩大修改范围，明确指出冲突并请求架构裁决。不得以私有实现绕过冲突。

## 2. 架构事实与权威来源

LearnFlow 的架构事实按以下顺序核对：

1. `backend/app/services/architecture_registry.py`：机器可读的 Agent、五核、工具、产品技能、工作台、能力和重要事件清单。
2. `docs/AGENT_ARCHITECTURE_GUIDE.md`：角色、上下文、证据和产品空间的规范语义。
3. `backend/app/services/learning_runtime.py` 与 `backend/app/services/memory_graph.py`：事件归约、五核投影和记忆图谱的运行实现。
4. 自动化测试：验证实现是否遵守上述契约。
5. 领域文档与页面文档：只能细化，不得另建第二套权威。

任何新增能力都必须融入这套权威，不能只在代码、提示词、前端常量或外部工作流中私下登记。

## 3. 不可破坏的产品与架构约束

### 三类主 Agent

仓库只有三类主责任接口：

- `tutor_agent`：意图、对话、Action、工作台协调和 handoff。
- `learning_design_agent`：路线、内容、问题、评估规格和视觉产物。
- `practice_agent`：提交、测试、判题、反馈、诊断追问和纠错呈现。

具体领域 Agent 必须位于上述接口之后，不得新增与它们竞争用户控制权的第四个主 Agent。

### 五核

五核是学习者状态维度，不是五个 Agent：

- `structure`：学习位置、依赖、路径和返回锚点。
- `knowledge`：概念理解、缺口、问题、错误和误解证据。
- `human`：明确偏好、负荷、节奏、挫败和支持需求。
- `value`：目标、优先级、动机、兴趣和相关性。
- `practice`：尝试、辅助等级、产物、反馈和迁移准备。

唯一合法的权威写入链是：

```text
用户 / UI / Tool / Agent 行为
  -> EvidenceEvent
  -> five_kernel_reducer
  -> KernelMutation
  -> KernelState
  -> MemoryFact -> MemoryModule -> MemoryClaim
```

任何 Agent、工具、工作台、外部 workflow 或 LLM 都不得直接写 `KernelState`，不得把生成内容直接视为掌握证据，也不得维护与五核并列的长期用户画像权威。

### 确定性教学与证据

- `RemediationStrategy`、评分、阶段跳转、通过条件和证据升级必须由确定性规则控制。
- LLM 可以生成候选题目、讲解、措辞或摘要，但不能自行决定教学策略、掌握状态或长期记忆。
- 答错、跳过、缺失输入和“不会”必须区分。
- 有提示成功不得等同于独立成功；原题重做不得等同于变式迁移。
- 一次答对不能直接宣称稳定掌握；一次答错不能据此推断情绪、人格、医学状态或固定学习风格。
- “换种讲法 / 看步骤 / 看示例”的选择及无效讲法必须形成可检查的用户级证据。
- 所有写入必须验证 learner、project、checkpoint、session 的 scope 与 ownership。
- 重复请求必须幂等，不能重复计分、重复创建 Attempt 或重复写证据。
- seeded demo 必须固定种子、使用隔离数据库，并在无 LLM、无网络情况下完成核心闭环。

## 4. 团队维护边界

### 工作线 A：主要架构、三类 Agent 与五核记忆

权威维护范围包括：

- 三类主 Agent 的请求、响应、身份和 handoff 契约。
- 五核短期键、上下文投影、长期巩固门槛和状态迁移。
- `EvidenceEvent`、确定性 reducer、Memory Graph 与可纠正历史。
- learner ownership、幂等、证据等级和通过条件。
- 架构注册表及其版本、digest 和漂移校验。

### 工作线 B：工具、产品技能、工作台与重要事件

主要维护范围包括：

- Action Board handler、来源处理、RAG、生成器、执行器和外部 adapter。
- 路线、教学产物、实践验证、纠错等产品能力的实现。
- Tutor、项目、讲义、练习、纠错、画像、记忆和 demo 工作台。
- 工具运行状态、页面行为、外部工作流和比赛资产。

工作线 B 读取五核时只能消费有 scope 的只读投影。需要改变学习状态时，必须复用或提出登记过的 capability 和 EventContract，再通过统一事件入口写入。是否归约、写入哪些核以及能否长期巩固，由工作线 A 的确定性规则裁决。

### 学习状态快速获取模块

模块负责人对内部产品方案、算法、选题、判题、评估、追问、停止条件、UI 和测试拥有充分自主权，但其外部边界必须满足：

- 输入是题目/任务上下文、有 scope 的五核投影与近期证据。
- 输出是结构化判定、置信度、依据、追问建议和事件提案。
- 只有已登记的 `EvidenceEvent` 可以进入五核链路。
- 模块不得直接生成 `KernelMutation`，不得自行覆盖五核状态。
- 追问必须有预算和停止条件，且摸底追问不得泄露答案、污染后续证据。
- 在线模型只能增强生成和表达；离线 seeded 模式必须可以验收核心行为。

## 5. 共享契约的修改协议

以下属于共享热点，修改时必须在 PR 中声明 `Contract impact`：

- `backend/app/services/architecture_registry.py`
- `backend/app/services/learning_runtime.py`
- `backend/app/services/memory_graph.py`
- `backend/app/models/learning.py`
- `backend/app/api/architecture.py`
- `docs/ARCHITECTURE_AUTHORITY.md`
- `docs/AGENT_ARCHITECTURE_GUIDE.md`
- 五核、EvidenceEvent、Action Board、RemediationStrategy 的 schema 或状态机

修改共享契约时必须同时：

1. 说明现有契约为何不足。
2. 给出向后兼容性或迁移方案。
3. 更新注册表、实现、测试和对应文档，不能只改其中一处。
4. 为稳定 ID、schema version 或 registry version 的变化给出理由。
5. 请求架构维护者审查；模块负责人不能自行批准影响其他模块的权威变更。

仅增加讲法、模型供应商、外部 workflow adapter 或 UI 表达时，不应改变五核和 EvidenceEvent 的语义。

## 6. GitHub 协作流程

### Issue 或明确任务先行

功能、修复和跨模块重构必须先有 GitHub Issue 或维护者给出的等价明确任务。任务至少应包含：

- 目标和用户价值。
- 输入、输出和影响范围。
- 验收标准。
- 明确非目标和禁止事项。
- 是否影响共享契约、数据迁移、外部网络或 LLM。

Codex 可以帮助补全方案和验收标准，但不得把未确认的扩展自动加入实现范围。

### 一项任务一个分支

- 禁止直接在 `main` 开发或推送。
- 默认分支格式：`codex/<type>-<issue>-<short-name>`。
- `type` 使用 `feat`、`fix`、`docs`、`refactor`、`test` 或 `chore`。
- 示例：`codex/feat-12-learner-state-discovery`。
- 一个分支只解决一个主要 Issue；一个功能分支只由一名负责人或一个明确协作小组维护。
- 开工前从最新 `main` 建分支。若远程功能分支已经被别人使用，先确认负责人，不能覆盖历史。
- 禁止 force push、`git reset --hard` 或用强制手段覆盖协作者提交。

Codex 只有在用户明确授权发布时才能 commit、push、创建或更新 PR。只要求分析、诊断或评审时，不得擅自修改远程状态。

### Commit

- 提交应小而完整，避免把无关格式化、生成文件或临时调试混入功能修改。
- 推荐使用 Conventional Commit：`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`。
- 提交前必须检查 `git diff`、`git diff --check` 和 `git status -sb`。
- 不得提交 `.env`、密钥、token、日常数据库、比赛生成数据库、模型权重、缓存、虚拟环境、`node_modules` 或本地日志。
- 新配置只提交安全的 `.env.example` 占位符，不提交真实凭据。

### Draft PR

实现开始并形成可讨论边界后应尽早建立 Draft PR。PR 描述至少包含：

```markdown
## What
本 PR 改变了什么。

## Why
为什么需要这一变化。

## Contract impact
是否影响三类 Agent、五核、事件、API、数据库或注册表；若无，写 None。

## Evidence
执行了哪些测试，结果是什么。

## Demo
人工或 seeded demo 如何复现。

## Risks and rollback
已知风险、兼容性和回滚方式。
```

有 UI 修改时提供截图或录屏；有 API/schema 修改时提供请求响应示例；有迁移时提供升级和回退说明。PR 未满足验收标准时保持 Draft。

### Review 与合并

- 作者不能仅依赖自己的 Codex 自审；至少需要另一名成员或独立 Codex 任务检查 PR diff。
- 共享契约变化必须由架构维护者批准。
- 工具、技能和工作台变化由相应维护者审查；涉及五核写入时追加架构审查。
- 所有适用测试、构建和 CI 必须通过；人工验证不能替代自动测试。
- 审查意见在原分支修复，不另开失去上下文的替代 PR。
- 推荐 Squash Merge；合并后删除功能分支。
- `main` 应始终保持可运行、可测试、可执行 seeded demo。

## 7. 实现与登记要求

新增工具、产品技能、工作台、能力或重要事件时，Codex 必须：

1. 在 `architecture_registry.py` 声明稳定 ID、owner、origin、模式、五核读取范围和写入路径。
2. 复用或新增 Action Board capability，并明确 side effect、确认策略和 evidence target。
3. 对重要行为注册 EventContract；写回统一经过 `record_event()`。
4. 若事件需要改变五核，由 reducer 增加确定性归约规则和测试。
5. 外部 workflow 输出先校验为 LearnFlow artifact 或事件输入，不能直接决定策略或写五核。
6. 更新架构、融合目录和必要的比赛文档。
7. 提升注册表版本，并验证 registry digest/漂移检查。

如果只完成运行实现而没有登记、事件、测试或文档，应视为尚未完成。

## 8. 测试与验收

按修改范围运行最小充分测试；提交 PR 前运行全部适用检查。

### 文档或任意修改

```bash
git diff --check
```

### 后端

```bash
cd backend
venv/bin/python -m pytest -q
```

### 架构注册表

```bash
cd backend
venv/bin/python -m pytest tests/test_architecture_registry.py -q
```

### 纠错闭环

```bash
cd backend
venv/bin/python -m pytest tests/test_remediation.py -q
```

### 前端

```bash
cd frontend
npm run build
```

### Seeded demo

```bash
bash start.sh demo
```

随后按照 `docs/competition/DEMO_RUNBOOK.md` 验证 `/demo`、`/api/demo/status` 与 `/api/architecture/validate`。不要为了让测试通过而删除断言、跳过关键用例或把确定性逻辑改为模型判断。

最终报告必须区分：已执行且通过、已执行但失败、因环境原因未执行。不得声称未实际运行的测试已通过。

## 9. Codex 工作方式

- 先理解现有实现，再修改；优先复用现有 registry、event gateway、reducer 和测试工具。
- 使用搜索和小范围读取定位事实，不凭对话记忆猜测当前代码状态。
- 保留用户和其他成员的未提交改动，只修改任务范围内文件。
- 不为追求“大而完整”擅自重写相邻模块。
- 内部实现可以创新，但跨模块输出必须是版本化、结构化、可测试和可登记的。
- 对高影响设计给出理由、替代方案和迁移影响；对普通局部实现自主推进。
- 发现契约缺口时，可以提出更好的接口，但不得先绕过权威再补文档。
- 诊断任务只报告原因；只有用户要求修复或任务明确包含实现时才改代码。
- 发布、合并、删除、迁移数据、修改 GitHub 设置等外部状态变化必须有明确授权。

## 10. Code Review Rules

Codex 审查 PR 时优先寻找会造成真实后果的问题。格式、lint 和其他机械检查交给 CI。

### 架构与状态权威

- 标记新增第四类主 Agent、第二套用户画像权威或绕过注册表的私有能力登记。
- 标记 Agent、工具、UI、LLM 或外部 workflow 对 `KernelState` 的直接写入。
- 标记绕过 `EvidenceEvent -> reducer -> KernelMutation` 链路的状态修改。
- 标记 LLM 决定评分、RemediationStrategy、通过条件、掌握升级或长期记忆的行为。

### 证据正确性

- 标记把生成文本、自述、一次答对、有提示成功或原题重做误当成高等级掌握/迁移证据。
- 标记从普通错误直接推断情绪、人格、医学状态或固定学习风格。
- 标记不能区分答错、跳过、缺失输入和不会作答的逻辑。
- 标记缺少 scope ownership、幂等键、provenance、策略版本或可重放依据的重要写入。

### 注册与兼容性

- 标记新增工具、产品技能、工作台、能力或重要事件却未更新 `architecture_registry.py` 的变化。
- 标记共享 schema/API 发生破坏性变化却没有迁移、版本、测试和文档。
- 标记模块维护自己的五核 allow-list、事件类型或 capability owner 副本而造成漂移。

### 闭环与可验收性

- 标记答错—纠错—重做—变式—证据回写链条被截断、乱序或错误升级证据的情况。
- 标记“换种讲法 / 看步骤 / 看示例”只改变 UI、没有记录无效/有效讲法证据的情况。
- 标记 seeded demo 依赖网络、LLM、日常数据库或非确定性数据的变化。
- 标记关键行为缺少回归测试，或测试没有验证状态、事件顺序和用户隔离。

## 11. 完成定义

任务只有同时满足以下条件才算完成：

- 实现符合 Issue/任务验收标准，没有无授权扩展。
- 三类 Agent、五核、事件链和确定性策略边界保持成立。
- 新能力已经登记，相关文档和版本已同步。
- 适用测试、构建和 demo 已实际执行并如实报告。
- diff 不包含秘密、本地数据、无关改动或协作者文件损失。
- PR 描述提供足够证据，让未参与实现的成员和 Codex 可以独立复现与审查。
