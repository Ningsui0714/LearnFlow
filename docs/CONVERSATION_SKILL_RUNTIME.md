# 阶段二：对话内学习 Skill Runtime

## 1. 阶段目标

阶段二把“学习方法”从提示词名称升级为对话 Session 内可恢复、可检查、可交接的运行流程。
学习者仍然在同一个 Tutor 对话里学习；Skill 只约束 Tutor 下一步怎样引导，不创建新的主
Agent，也不把对话表现写成掌握结论。

本阶段首批运行型 Skill 是：

- `socratic_dialogue`：暴露当前直觉、检验关键条件、连成推理、进入独立验证；
- `feynman_dialogue`：第一次复述、定位模糊处、修订解释、进入独立验证；
- `guided_explanation` 暂时保留为普通对话讲解基线，不创建 `LearningSkillRun`。

Tutor 可以根据当前一句话推荐方法，但返回 `requires_confirmation=true`；只有学习者点击
接受或在输入区明确选择后才启动。项目式学习继续作为对话可进入的长期模式，不与对话
Skill 竞争入口。

## 2. 运行模型与编排

`LearningSkillRun` 是 Session 范围的工作流投影，保存目标、当前状态、轮次预算、暂停点、
幂等动作和验证附件引用。它没有评分字段，也不是第二套用户画像或掌握权威。

```text
global Tutor Session
  -> 学习者选择 / Tutor 推荐后确认 Skill
  -> LearningSkillRun（确定性状态机）
       -> Tutor LLM 只渲染当前一步；无模型时使用确定性文案
       -> pause / resume（expected_version + client_action_id）
       -> verification_ready
  -> 学习者点击“开始独立验证”
  -> MicroLearningRun -> LearningAttempt -> RemediationCase -> ReviewSchedule
  -> LearningSkillRun completed（仍为 not_stable_yet）
```

苏格拉底状态机：

```text
eliciting_prior_model
  -> testing_assumption
  -> building_explanation
  -> verification_ready
  -> verification_in_progress
  -> completed
```

费曼状态机：

```text
awaiting_teach_back
  -> locating_gap
  -> revising_explanation
  -> verification_ready
  -> verification_in_progress
  -> completed
```

两条流程的引导预算均为三轮。状态迁移、轮次预算、暂停恢复、验证准入和完成归约由
`learning_skill_runtime.py` 确定性控制；LLM 只能生成当前已裁决步骤的表达，不能改变状态、
评分或掌握结论。

## 3. 前端逻辑

独立对话 `/agent/:sessionId` 是唯一主输入。输入区允许选择方法；自动模式只显示一张可
接受的推荐卡，不会静默切换。Skill 启动后，对话底部显示一张轻量进度卡，用户只看到：

- 当前方法、目标、正在进行的步骤和剩余引导轮次；
- 暂停、继续或在就绪后开始独立验证；
- “对话用于引导，独立题与复习才形成能力证据”的易懂说明；
- 已生成验证附件时的“打开独立验证/查看验证记录”。

刷新或重新登录后从服务端恢复卡片。验证仍打开既有 `/learn/:runId` 专注附件；这不是把
学习方法搬回固定页面，而是把需要判题、纠错和复习的部分交给权威证据系统。

## 4. API、事件与证据边界

| API | 用途 |
|---|---|
| `POST /api/agent/sessions/{sessionId}/skill-runs` | 幂等启动苏格拉底或费曼流程 |
| `POST /api/agent/sessions/{sessionId}/skill-runs/{runId}/actions` | 暂停、恢复或创建独立验证 |
| `GET /api/agent/sessions/{sessionId}` | 恢复 Session、最近 SkillRun 和待确认推荐 |
| `POST /api/agent/sessions/{sessionId}/turns` | 在当前确定性步骤内继续普通对话回合 |

以下事件全部是零 Kernel target：`learning_skill_run_started`、
`learning_skill_run_advanced`、`learning_skill_run_paused`、
`learning_skill_run_resumed`、`learning_skill_verification_started`、
`learning_skill_run_completed`。它们记录运行事实，不改变五核状态。

真正的能力证据从验证附件继续走既有 `micro_learning_started`、`LearningAttempt`、
`concept_attempt_evaluated`、纠错与复习链。完成 SkillRun 只表示本轮已有独立验证记录，
稳定掌握仍需跨时间、独立且包含变式的复习证据。

所有查询和动作校验 `learner_id + session_id + run_id` ownership；创建和动作分别使用
`client_request_id`、`client_action_id` 幂等，状态动作使用 `expected_version` 阻止陈旧覆盖。

## 5. 初步对比试验

固定集 `backend/evals/learning_skill_cases.json` 包含 24 条人工标注请求，清晰讲解、
苏格拉底和费曼各 8 条。运行：

```bash
cd backend
venv/bin/python scripts/evaluate_learning_skills.py
```

基线 `prompt_only_guided_explanation` 对所有请求都使用普通讲解。候选
`conversation_skill_runtime_v1` 使用确定性推荐和已登记工作流。独立评分项是路由准确率、
有界运行时、验证交接和零掌握写入边界。

第一轮候选路由准确率为 `0.917`，暴露两个边界：否定式“不要直接告诉”和“讲给一个
新手听”的同义表达。保持原样例不变，调整显式意图优先级和同义触发词后，第二轮为：

| 指标 | 候选 | 基线 |
|---|---:|---:|
| 路由准确率 | 1.000 | 0.333 |
| 有界运行时 | 1.000 | 0.000 |
| 验证交接 | 1.000 | 0.000 |
| 证据边界 | 1.000 | 0.000 |
| 四项平均提升 | 0.917 | — |

这只证明工程契约在小型冻结样例上可执行，不证明学生学习效果。下一轮产品试验应记录推荐
接受率、Skill 完成率、验证启动/完成率、所需提示数、24 小时与 7 天复习保持率，并配合
定性访谈；在这些结果出现前不扩展 SQ3R、康奈尔、番茄或西蒙的完整运行时。

## 6. Contract impact 与迁移

- 注册表版本提升为 `2026-08-21.4`，新增 `learning_skill_runtime` tool、三项 capability、
  苏格拉底/费曼运行输出契约和六个零 target 事件。
- 数据库迁移 `v14-conversation-skill-runtime` 只新增 `learning_skill_runs` 表；既有 Session、
  Project、Attempt、纠错、复习和五核数据不变。
- Tutor Session/turn 回包仅向后兼容地增加 `active_skill_run` 与
  `skill_recommendation`；旧前端可以忽略。
- 验证沿用 `MicroLearningRun` API 与证据语义，没有修改五核 reducer、评分、纠错或稳定
  掌握门槛。
