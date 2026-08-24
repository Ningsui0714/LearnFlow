# 原子学习 Skill Runtime v2

- 状态：已实现
- 运行时版本：`atomic-learning-skill-runtime-v2`
- 数据迁移：`v16-atomic-learning-skill-runtime`

## 1. 产品承诺

学习 Skill 不是一段提示词，也不是新的 Agent。它是 Tutor 在一项明确学习目标中采用的、
可恢复且有边界的教学策略。首批四种主 Skill 共用一个外层闭环：

```text
学生选择方法，或接受 Tutor 推荐
  -> LearningSkillRun + 同一 LearningTask
  -> 有界教学互动
  -> 无提示独立验证
  -> 必要时进入确定性纠错
  -> ReviewSchedule 复习转交
```

`LearningSkillRun` 只负责“当前怎样教”，`LearningTask` 负责“这项原子学习任务如何安排和
恢复”，`LearningAttempt / EvidenceEvent` 才负责“学生实际做得怎样”。三者不得互相替代。

Tutor 可以推荐方法，但推荐固定返回 `requires_confirmation=true`，不能静默切换。显式选择
后立即建立或复用一个学习者可见的原子任务；退出方法只暂停流程和任务，不删除历史。

## 2. 首批四种方法

| Skill | 适用情境 | 三轮教学骨架 | 不适用情境 |
|---|---|---|---|
| `guided_explanation` 清晰讲解 | 陌生概念、认知负荷高、先建立最小模型 | 核心模型和最小例子 → 新例子检查 → 用“条件—机制—结果”重述 | 学生明确要自行推导；主要目标是程序步骤 |
| `socratic_dialogue` 苏格拉底追问 | 因果、证明、不变量；已有部分直觉 | 暴露直觉 → 检验条件/反例 → 连成推理 | 完全没有先备知识；学生明确要求直接解释 |
| `feynman_dialogue` 费曼复述 | 已接触主题后的查漏、概念组织 | 首次复述 → 定位一个跳步 → 无术语修订并补例子/边界 | 初次接触；只需先看程序步骤 |
| `worked_example_fading` 示例渐隐 | 代码、算法、配置和其他程序性技能 | 子目标标注的完整示例 → 隐去最后一步 → 只保留子目标与起始条件 | 单纯事实解释；已经能独立完成且只需迁移验证 |

四条流程的引导预算均为三轮。每轮只推进一个可检查动作；预算结束必须停止追加教学，转入
独立验证。学习者可随时要求直接解释、暂停、换方法或稍后继续。

详细选型依据与产品研究见 `docs/ATOMIC_LEARNING_SKILLS.md`。

## 3. 运行与任务同步

SkillRun 启动时会创建或复用同 Session、同目标的非终态 `LearningTask`，并把 Skill 写入
任务计划的 `learn` 阶段。运行同步规则是确定性的：

| SkillRun 动作 | LearningTask 变化 |
|---|---|
| 启动 / 恢复 | `queued/paused -> active` |
| 暂停 / 切换方法 | `active -> paused` |
| 到达 `verification_ready` | 完成 `learn` 阶段；不产生掌握证据 |
| 开始独立验证 | 在同一任务上物化 `MicroLearningRun`，不创建第二个任务身份 |
| 验证完成 | 重投影任务阶段、证据引用和复习转交 |

这些变化使用现有 Learning Task 零 Kernel target 事件，只是运行协调。`LearningSkillRun` 新增
可空 `learning_task_id`；旧 SkillRun 若已有微学习附件，迁移会按 learner ownership 回填其
现有任务引用，无法匹配的旧记录保持可读。

状态迁移、轮次预算、暂停恢复、任务同步和验证准入由
`backend/app/services/learning_skill_runtime.py` 确定性控制。LLM 只能渲染当前步骤，不得改
状态、评分、纠错策略、复习间隔或掌握结论。无模型时使用同一状态机的确定性文案。

## 4. 前端与 API

独立对话 `/agent/:sessionId` 仍是唯一主输入。Skill 卡显示当前方法、目标、步骤、剩余轮次、
暂停/继续/验证动作，以及“查看原子任务”入口。刷新后从服务端恢复；正式验证仍打开
`/learn/:runId` 专注附件。

| API | 用途 |
|---|---|
| `GET /api/agent/skills` | 返回四种可选方法及适用/避用元数据 |
| `POST /api/agent/sessions/{sessionId}/skill-runs` | 幂等启动任一运行型 Skill，并绑定任务 |
| `POST /api/agent/sessions/{sessionId}/skill-runs/{runId}/actions` | 暂停、恢复或在同一任务上开始验证 |
| `GET /api/agent/sessions/{sessionId}` | 恢复 Session、最近 SkillRun、任务引用和推荐 |
| `POST /api/agent/sessions/{sessionId}/turns` | 在 runtime 已裁决的当前步骤内继续对话 |

查询和动作都校验 `learner_id + session_id + run_id` ownership；创建和动作使用
`client_request_id / client_action_id` 幂等，状态动作使用 `expected_version` 防止陈旧覆盖。

## 5. 事件与证据边界

以下 Skill 事件全部为零 Kernel target：`learning_skill_run_started`、
`learning_skill_run_advanced`、`learning_skill_run_paused`、
`learning_skill_run_resumed`、`learning_skill_verification_started`、
`learning_skill_run_completed`。任务同步继续复用已登记的 Learning Task 生命周期和阶段事件。

讲解、追问、复述、阅读示例和有提示补全都不是掌握证据。真正的能力证据必须从验证附件进入
`LearningAttempt -> EvidenceEvent -> reducer -> KernelMutation -> Memory Graph`，答错后继续
使用既有 `RemediationCase`，验证结果再由 `ReviewSchedule` 转交复习。完成 SkillRun 只表示
本轮已有独立验证记录，稳定掌握仍要求跨时间、独立且含已校验变式的复习证据。

## 6. 工程评测与产品实验

`backend/evals/learning_skill_cases.json` 固定 32 条人工标注请求，四种方法各 8 条。运行：

```bash
cd backend
venv/bin/python scripts/evaluate_learning_skills.py
```

当前 `atomic_learning_skill_runtime_v2` 的冻结样例结果为：路由准确率、有界运行、验证交接和
证据边界均为 `1.000`；只会普通讲解的基线分别为 `0.250 / 0 / 0 / 0`，四项平均提升
`0.938`。这只证明工程契约可执行，不证明真实学习效果。

线上必须继续测量：推荐接受率、任务启动/完成率、验证启动/完成率、平均提示等级、纠错完成
率、暂停恢复率、24 小时和 7 天复习保持率，并结合访谈检查学生是否感到被流程绑架。

## 7. Contract impact

- 注册表版本提升为 `2026-08-24.2`，四种 learner-selectable Skill 都声明
  `best_for / avoid_when / atomic_task_capable`，没有新增主 Agent、Kernel 或直接写入路径。
- `LearningSkillRun.learning_task_id` 是可空、向后兼容字段；迁移 `v16` 只补链接，不删除旧
  Session、Attempt、纠错、复习或五核数据。
- API 回包只向后兼容地增加 Skill 元数据和 `learning_task` 摘要；旧前端可以忽略。
- 评分、`RemediationStrategy`、复习策略和五核 reducer 均未改变。
