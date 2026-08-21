# 阶段一：可验证微学习 MVP

## 1. 阶段目标

阶段一验证一个最小产品承诺：学习者只需输入“我想弄懂什么”，就能在约 15 分钟内完成一次有内容、有复述、有判题、有纠错、有后续复习的学习闭环，并能随时离开后恢复。

本阶段不追求一次学习后“精通”，也不同时实现西蒙、SQ3R、番茄和康奈尔的完整产品形态。费曼复述是第一个可见教学技能；项目式学习保留为适合长期目标的深度模式。

用户验收语言：

- 一上手先看到学习目标输入框，而不是项目配置。
- 输入主题后立即得到结构化学习卡；没有模型或网络时仍可运行确定性降级内容。
- 学习者必须用自己的话复述，再完成不泄露答案的独立题目。
- 答错后直接进入“讲解—原题重做—变式验证—证据回写”。
- 完成本轮后看到具体结果与下一次复习，而不是模糊的“学会了”。
- 刷新、暂停或再次登录后可以恢复到上次步骤。

## 2. 系统层级

阶段一没有增加第四类主 Agent，也没有增加第六个 Kernel。

```text
Tutor 控制 Agent
  └─ verified_micro_learning 产品技能
      ├─ micro_learning_orchestrator：创建和恢复流程
      ├─ Learning Design：学习卡与题目候选
      ├─ feynman_teach_back：确定性覆盖诊断
      ├─ Practice：确定性判题与纠错
      └─ review_scheduler：间隔复习投影

既有学习领域对象
  ├─ Project / Roadmap / Checkpoint：内部 scope 与 ownership
  ├─ Lecture / ConceptQuestion：内容与评估契约
  ├─ LearningAttempt / RemediationCase：权威尝试与纠错记录
  ├─ ReviewSchedule：可重建复习计划
  └─ MicroLearningRun：仅为可恢复 UI/工作流投影
```

`MicroLearningRun` 不保存另一套掌握结论。题目判定、纠错状态和复习计划始终由既有权威对象重建；运行摘要固定声明 `mastery_claim=not_stable_yet`。

## 3. 用户流程与前端逻辑

### 学习首页 `/agent`

主操作是“今天想真正弄懂什么”。学习者可以只输入主题，也可以展开材料框粘贴笔记或文章片段。首页同时显示可恢复的最近学习和今日到期复习。项目式学习、五核证据作为次级入口。

### 专注学习 `/learn/:runId`

专注页不显示项目 Explorer、IDE 标签和常驻 Agent Rail，避免让内部架构成为用户任务。页面仅保留：

- 当前目标、步骤和暂停/恢复；
- 学习卡、复述、诊断反馈、题目、纠错或完成总结之一；
- 按需打开的当前关卡 Tutor；
- 完成后进入复习台或再学一个主题。

页面状态机：

```text
learning_card
  -> teach_back
  -> teach_back_feedback
  -> verification
       ├─ correct -> next question
       └─ wrong -> remediation
                    -> retry original
                    -> validated variant
                    -> next question
  -> completed -> review

任意 active 状态 -> paused -> 原状态恢复
```

页面动作使用 `expected_version` 防止陈旧状态覆盖，创建、复述、作答和同步均有客户端幂等 ID。取题响应、运行响应和 Tutor 上下文不包含正确答案或私有变式契约。

## 4. 内容与生成算法

### 输入

- 必填：一个 2–300 字的具体目标。
- 可选：最多 20,000 字的用户材料。
- 只读适配：教育阶段和自述背景。

### 输出契约

学习卡必须包含：目标、3–5 个关键点、2–5 个目标概念、具体例子、常见混淆和可观察完成标准。每轮必须有 2–3 道通过结构校验的概念题；每题先声明细粒度目标和证据声明，并带一个后端私有的已校验变式。

在线生成只负责候选内容。服务端会校验字段、题型、选项、答案索引和变式契约；不合格题目由确定性模板补齐。无 API Key、供应商失败或离线 demo 时使用同一输出契约的确定性降级算法。

费曼复述使用 `deterministic_concept_coverage_v1`：通过目标概念和中文/字母数字二元片段覆盖率定位未讲清的关键点。结果只形成诊断 Attempt 与 `teach_back_analyzed` 事件，显式设置 `mastery_unchanged=true`，随后仍必须独立作答。

### 对比试验

固定样例位于 `backend/evals/micro_learning_cases.json`，包含 10 个纯主题与 10 个材料约束主题。运行：

```bash
cd backend
venv/bin/python scripts/evaluate_micro_learning.py
```

第一轮比较 `verified_micro_learning_fallback_v1` 与只产出阅读提纲的 `naive_outline`。指标为学习卡契约、评估契约、材料约束和可恢复闭环准备度。当前 20 个样例中候选四项均为 `1.0`，基线综合差距为 `0.75`。这是结构和可执行性门槛，不代表真实学习效果；后续必须用完成率、首轮用时、复述缺口、答题、纠错完成率和跨日复习保持率做用户实验。

## 5. API 与事件

| API | 用途 |
|---|---|
| `POST /api/micro-learning/runs` | 幂等创建学习内容和内部 scope |
| `GET /api/micro-learning/runs` | 当前学习者的最近流程 |
| `GET /api/micro-learning/runs/{id}` | 恢复并重投影权威尝试状态 |
| `POST /api/micro-learning/runs/{id}/advance` | 阅读完成、反馈后继续、暂停或恢复 |
| `POST /api/micro-learning/runs/{id}/teach-back` | 写入复述诊断 Attempt 和事件 |
| `POST /api/micro-learning/runs/{id}/sync` | 把题目/纠错权威状态重投影到流程 |

新增重要事件：

| 事件 | 证据语义 | Kernel 目标 |
|---|---|---|
| `micro_learning_started` | 学习者明确提交本轮目标 | structure、value |
| `learning_card_generated` | 内容产物 | 无 |
| `micro_learning_card_viewed` | 接触内容，不代表掌握 | knowledge |
| `teach_back_analyzed` | 诊断覆盖缺口，不晋级掌握 | knowledge、practice |
| `micro_learning_paused/resumed` | 运行操作 | 无 |
| `micro_learning_completed` | 本轮流程完成，不是稳定掌握 | 无 |

正式概念作答继续使用 `concept_attempt_evaluated`；微学习题即使在同一轮独立答对两题，也只保持 `verified_once`。稳定掌握仍要求后续跨时间复习和已校验变式证据。

## 6. 验收、观测与下一阶段入口

工程验收：

- 创建和动作幂等；learner ownership 与乐观版本冲突有测试。
- 回包不泄露答案；没有 LLM/网络可完成核心闭环。
- 费曼诊断不改长期掌握；正确题会生成 `ReviewSchedule`。
- 错题进入既有确定性纠错；完成摘要不夸大稳定掌握。
- 架构注册表无漂移，后端全量测试和前端构建通过。

产品事件分析至少按 `run_id` 统计：开始率、学习卡到复述转化、复述到验证转化、首题正确率、纠错进入/完成率、本轮完成率、暂停恢复率、完成用时、复习到期参与率。阶段二是否扩展 SQ3R、康奈尔、番茄或西蒙模式，应由这些行为数据与定性访谈决定，而不是按功能数量决定。

## 7. Contract impact 与迁移

- 注册表版本提升为 `2026-08-21.1`，新增已登记 tool、skill、workbench、capability 和 event contract。
- `concept_attempt_evaluated.payload` 向后兼容地增加可选 `assessment_mode`；只有 `verified_micro_learning` 禁止同一 session 的多题结果直接升级稳定掌握，旧题语义保持不变。
- 数据库迁移 `v13-focused-micro-learning` 只新增 `micro_learning_runs` 表，不修改或删除旧数据。
- 回滚前端入口和新 router 不影响既有项目学习、练习、纠错和复习记录；保留的内部项目与 Attempt 仍可从原工作台查看。
