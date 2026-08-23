# LearnFlow Claw 与 Learning Task Runtime

> 状态：v1 已实现
> 运行时版本：`learning-task-runtime-v1`
> 计划 schema：`learning-task-plan.v1`

## 1. 产品形态

LearnFlow 的主界面只有两类学习空间：

1. **对话**：Tutor 与学生讨论问题、澄清目标、规划路径，也可以在识别到原子学习目标后提出一个学习任务。普通问答仍然可以自由结束，不强迫进入流程。
2. **项目**：以真实产物或持续能力为目标的学徒旅程。项目包含来源、动态路线、关卡、项目 Tutor 与本地工作区；每个正式关卡对应一个固定 Session 和一个 Learning Task。

两条全局队列覆盖在这两类空间之上，而不是第三种教学模式：

- `/tasks`：待确认、待开始、进行中和暂停的学习任务。
- `/review`：由正式评估证据产生的复习任务。

`/learn/:runId` 继续存在，但语义从独立产品模式收敛为 **Learning Task 的专注附件**：当任务需要保存讲义、题目和正式验证时，Tutor 可以按需物化该附件。

## 2. 为什么要有 Learning Task

Session、项目、后台作业和复习解决的是不同问题：

| 对象 | 回答的问题 | 生命周期 | 是否是学习证据 |
|---|---|---|---|
| `AgentSession` | 在哪里继续这段对话？ | 多轮对话 | 否 |
| `LearningTask` | 学生当前承诺完成哪个原子学习闭环？ | 可排队、暂停、续跑、重规划 | 否 |
| `Project / Checkpoint` | 长期学徒旅程和正式关卡是什么？ | 长期、版本化 | 否 |
| 旧 `Task` | 哪个后台程序正在运行？ | queued → running → terminal | 否 |
| `LearningAttempt / EvidenceEvent` | 学生实际做了什么，结果怎样？ | 追加、可审计 | 是 |
| `ReviewSchedule` | 哪个正式评估项何时应再次检索？ | 可重建调度投影 | 只有复习提交后产生证据 |

因此，Learning Task 不能复用旧后台 `Task`，也不能变成第六个 Kernel 或第二套掌握状态。

## 3. Claw 运行关系

```mermaid
flowchart TD
    U[学生输入或点击] --> S[对话 Session]
    S --> T[Tutor 识别意图]
    T --> Q{是否形成原子学习任务}
    Q -->|普通问答| R[自由对话回复]
    Q -->|学生明确要求| LT[Learning Task queued/active]
    Q -->|Tutor 主动建议| P[Learning Task proposed]
    P -->|学生接受| LT
    P -->|学生拒绝| C[canceled]

    LT --> PLAN[Learning Design 生成候选计划]
    PLAN --> RUN[Tutor 管理暂停、续跑、重排与交互]
    RUN --> METHODS[按需组装 Skills / 可视化 / 来源讲义]
    RUN --> ART[讲义与习题受管文件]
    RUN --> PRACTICE[Practice 正式练习与纠错]
    PRACTICE --> E[LearningAttempt + EvidenceEvent]
    E --> REVIEW[ReviewSchedule]
    E --> MEMORY[五核 reducer 与 Memory Graph]
    REVIEW --> RW[/review 独立复习台]
```

Tutor 始终保持用户控制权。Learning Design 和 Practice 是 Tutor 背后的能力接口，不新增第四个主 Agent。
每个 Tutor 回合都会装配当前 Session 内任务的目标、状态、当前阶段、可用 Skill 与完成规则；
这是 answer-free 的只读协调上下文，使对话可以持续推进同一个闭环，也避免每回合重复建任务。

## 4. 原子学习任务触发

### 4.1 显式触发

学生明确提出边界清楚的学习目标，例如：

- “用 15 分钟弄懂事件循环。”
- “我拿着这道指针题来问，带我完成理解和验证。”
- “把理解闭包加入我的待学任务。”

参数充分且本轮措辞已明确授权开始学习时，建立 `active` 任务；结构化输出以
`consent_basis=explicit_user_request` 保留授权依据，并由服务端对原始用户措辞再次校验，
不能只凭模型字段造成入队。明确的 15 分钟/微学习请求继续直接物化 `/learn/:runId`，同时
自动创建并关联 Learning Task。

### 4.2 Tutor 建议

Tutor 在普通聊天中发现一个适合形成闭环的原子目标时，只能返回 `learning_task_opportunity`。服务端创建 `proposed` 任务；学生点击“加入学习任务”后才进入队列。

以下情况不应创建任务：

- 单次事实问答或寒暄。
- 目标仍然模糊、需要先探索方向。
- 已经更适合形成多周项目、多个来源或真实产物。
- Tutor 只是想追加一个可选追问。

### 4.3 项目关卡

路线一旦正式写入，每个 Checkpoint 会获得：

- 唯一的 checkpoint Session；
- 唯一的 checkpoint Learning Task；
- 关卡目标、退出条件和来源引用；
- 已存在或后续生成的 `.lflecture` / `.lfexercise` 受管文件。

关卡被路线重排时，任务保持稳定 ID；关卡完成时任务同步为流程完成。项目仍然是长期学徒旅程，任务只是可执行队列单元。

## 5. 自适应任务计划

计划由 Learning Design 生成候选结构，由服务端校验并保存不可变版本。计划只包含 2–4 个粗粒度阶段，避免把教学拆成机械清单：

规划器会读取五核权威投影中已登记的短期字段，并压缩成有界、answer-free 的教学提示，
例如当前知识缺口、认知负荷、目标优先级和辅助等级。计划保存
`personalization_basis` 说明用了哪些 Kernel 字段，但不复制原始记忆、答案或新的画像结论；
模型不可据此改变评分、掌握、纠错与复习策略。

| Phase | 目的 | 可组合能力 |
|---|---|---|
| `learn` | 建立可解释理解 | 清晰讲解、苏格拉底追问、费曼复述、来源讲义、可视化 |
| `practice` | 主动尝试并暴露缺口 | 概念题、代码练习、产物任务、纠错闭环 |
| `verify` | 形成独立正式证据 | 无提示作答、测试、变式迁移 |
| `consolidate` | 转交复习队列 | `ReviewSchedule` 创建与 `/review` 导航 |

每个阶段保存：

- `id / kind / title / purpose`
- `methods`：只能引用注册表中的产品 Skill
- `required / status`
- `completion_rule`
- `artifact_outputs`

模型可以提出阶段和方法，但不能决定正式判题、掌握升级、纠错策略或复习间隔。服务端会拒绝没有正式 Attempt 的 `verify` 完成，也会拒绝没有 ReviewSchedule 的 `consolidate` 完成。

重规划使用乐观版本：

1. 学生说明调整原因或新方向。
2. Learning Design 只重组剩余计划。
3. 已完成阶段和正式证据引用被保留。
4. 追加 `LearningTaskPlanRevision(Vn)`，旧版本不可修改。
5. 重复 `client_request_id` 幂等重放，陈旧 `expected_version` 返回 409。

## 6. 文件与产物

Learning Task 不建立第二套讲义/习题存储。正式学习文件继续使用现有领域对象：

- `Lecture` 对外表现为 `.lflecture`；
- `Exercise` 与概念题集对外表现为 `.lfexercise`；
- 数据库对象、版本、答案保护和判题规则仍是权威；
- Task 只保存 `artifact_refs` 并提供打开路径。

普通对话任务可以先只在 Session 中学习。需要保存材料和正式验证时，调用 `materialize`：系统创建内部 `task_artifact` 空间、Lecture、ConceptQuestion 和 checkpoint Session，并返回 `/learn/:runId`。该内部空间从真实项目列表隐藏，旧链接仍可恢复。

## 7. 两条队列

### 学习任务队列

状态机：

```text
proposed -> queued -> active <-> paused -> completed
    |          |         |          |
    +----------+---------+----------+-> canceled -> queued(reopen)
```

学生可以：

- 接受或拒绝 Tutor 建议；
- 自行新增任务；
- 重排、设置优先级和时间预算；
- 暂停、恢复、移除或重新加入；
- 要求 AI 重组剩余计划；
- 打开原对话、项目关卡或专注附件。

### 复习任务队列

复习仍使用 `/review` 和 `ReviewSchedule`。学习任务只做 `review_handoff`，不复制复习状态，不自行计算掌握，也不把“任务完成”当作“复习完成”。

## 8. Agent 与权限

| 责任 | 允许 | 禁止 |
|---|---|---|
| Tutor | 识别任务、提出建议、管理队列、组装 Skill、控制 handoff | 未经同意接受建议；直接判定掌握 |
| Learning Design | 生成和调整候选计划、讲义、题目规格、视觉产物 | 直接完成阶段；决定评分或五核写入 |
| Practice | 执行确定性判题、纠错呈现、验证产物 | 选择任务优先级；直接写 KernelState |
| Learning Task Runtime | 持久化状态、计划版本、关联和零目标事件 | 充当证据权威或长期画像 |

Learning Task 生命周期事件全部是零 Kernel target。任务中的正式作答仍走：

```text
LearningAttempt -> EvidenceEvent -> reducer -> KernelMutation -> Memory Graph
```

## 9. API

主要接口：

- `GET /api/learning-tasks/summary`
- `GET /api/learning-tasks`
- `POST /api/learning-tasks`
- `PATCH /api/learning-tasks/{id}`
- `POST /api/learning-tasks/reorder`
- `POST /api/learning-tasks/{id}/actions`
- `POST /api/learning-tasks/{id}/replan`
- `POST /api/learning-tasks/{id}/materialize`

所有写入必须校验 learner/session/project/checkpoint ownership，并使用版本或幂等 ID。

## 10. 兼容与迁移

`v15-learning-task-runtime` 是增量迁移：

- 新增 `learning_tasks` 与 `learning_task_plan_revisions`。
- 为现有 Checkpoint 回填唯一 Learning Task 和 checkpoint Session。
- 把现有 MicroLearningRun 关联到对应任务。
- 把微学习产生的单关卡 Project 标记为 `task_artifact/internal`，不再出现在真实项目列表。
- 保留旧 `/learn/:runId`、项目关卡、Attempt、ReviewSchedule 和所有证据 ID。
- 旧后台 `tasks` 表和 `/api/tasks/{id}` 保持原语义，不做重命名。

## 11. 外部架构参考

本设计吸收了以下架构原则，但保持 LearnFlow 自己的教学证据边界：

- [OpenClaw Agent Loop](https://docs.openclaw.ai/concepts/agent-loop)：Session 内运行串行化、生命周期事件和持久化。
- [OpenClaw Queue](https://docs.openclaw.ai/concepts/queue)：按 Session 隔离并允许跨 Session 并行。
- [OpenClaw Background Tasks](https://docs.openclaw.ai/automation/tasks)：明确区分 Session、后台运行记录和更高层流程。
- [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/)：Session 是连续对话上下文，不应替代应用领域状态。
- [OpenAI Agents SDK Handoffs](https://openai.github.io/openai-agents-python/handoffs/)：专业能力通过受约束 handoff 或工具被协调。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：短期线程状态与跨线程长期数据分离。
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：暂停、恢复和副作用幂等是长流程的基础能力。
