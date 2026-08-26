# vNext 项目系统

## 一分钟逻辑

项目是一段以真实产物为目标的学徒旅程：

```text
创建项目（主题 + 目标 + 产物）
  -> 项目 Tutor（学习规划态）
  -> 读取项目五核 / 来源 / 路径 / 现有文件
  -> 给出关卡路线提案
  -> 学生确认
  -> Roadmap + Checkpoint + 关卡 Session + LearningTask
  -> 关卡对话（带领学习态）
  -> 讲义 / 练习提案 -> 学生确认 -> 受管文件
  -> 正式作答 -> LearningAttempt -> EvidenceEvent -> 五核
```

项目自由对话由学生自己创建。它共享项目上下文，但不推进关卡，也不能替代项目 Tutor。

## 对象与权威

| 对象 | 责任 | 权威位置 |
|---|---|---|
| Project | 主题、目标、真实产物 | 数据库 |
| Roadmap / Checkpoint | 已确认的项目关卡 DAG | 数据库 |
| AgentSession | 项目 Tutor、关卡对话、项目自由对话 | 数据库 |
| LearningTask | 每个关卡的可恢复学习闭环 | 数据库 |
| Source / Chunk | 项目本地文件、URL 及处理片段 | 数据库与受管上传目录 |
| Lecture / Exercise | 专属讲义与练习 | 数据库；逻辑文件只是引用 |
| KernelState | 学习者状态投影 | EvidenceEvent reducer |

项目页面只读写这些正式对象，不用 localStorage 创建影子项目。

## 会话角色

- `project_tutor`：每项目唯一，固定学习规划态，只规划当前项目。
- `checkpoint`：每关唯一，绑定正式 LearningTask，固定带领学习态。
- `project_free`：学生显式创建，保持自由态，不自动改变路线和任务。

三者都属于 `tutor_agent`。Learning Design 只在工具后提出路线与文件规格，Practice Agent 只负责
正式提交、判题与纠错。

## Agent 工具边界

| 工具 | 类型 | 输入与输出 | 副作用 |
|---|---|---|---|
| `read_project_workspace` | 感知 | 当前项目对象与五核有界投影 | 无 |
| `read_project_sources` | 感知 | 当前项目已处理 Chunk；带 provenance | 无 |
| `read_project_learning_file` | 感知 | 讲义或练习的答案安全预览 | 无 |
| `propose_project_roadmap` | 提案 | 主题锁定、前向 DAG、成功标准 | 无；需确认 |
| `propose_project_learning_files` | 提案 | 当前关卡 LearningTask 的讲义/练习规格 | 无；需确认 |

模型不获得 `apply/write/delete/confirm` 工具。确认按钮调用受 ownership、schema 与幂等键约束的
API，避免模型把一句自然语言当成授权。

## 五核与证据

- 创建项目：structure 建立项目锚点；用户明确目标可进入 value。
- 讨论路线：structure 只保存未确认提案，不生成长期结论。
- 确认路线：structure 保存 Roadmap、当前位置和返回锚点。
- 阅读来源、生成/打开讲义：最多是接触或操作事实，不是掌握。
- 练习：只有正式 LearningAttempt 的确定性判定能形成 knowledge/practice 证据。
- 项目产物：需后续登记的正式评估事件才能进入 practice；文件存在本身不是能力证据。

所有状态变化仍经过：

```text
UI / Tool / Agent 行为 -> EvidenceEvent -> reducer -> KernelMutation -> KernelState
```

## API 与恢复

- `GET/POST /api/vnext-projects`
- `GET /api/vnext-projects/:id`
- `POST /api/vnext-projects/:id/roadmap/apply`
- `POST /api/vnext-projects/:id/sessions`
- `GET /api/vnext-projects/:id/agent-context`
- `DELETE /api/vnext-projects/:id/sources/:sourceId`

项目工作台每次从服务端聚合恢复。路线初次确认后不能被同一接口覆盖；未来修订必须增加显式版本、
迁移与差异确认。

## 验收重点

1. 空项目没有假关卡；项目 Tutor 只规划项目主题。
2. 未确认提案不创建关卡、Session、LearningTask 或五核掌握。
3. 确认后每关都有正式 Session 与 LearningTask，前置关系保持 DAG。
4. 自由对话不会被恢复为项目 Tutor。
5. 来源越权、跨项目 checkpoint 和跨 learner 访问被拒绝。
6. 练习答案不进入 Agent 感知包；生成与打开文件不升级掌握。
7. 工具失败在 ReAct 轨迹中可见，模型可恢复，不伪装成功。
