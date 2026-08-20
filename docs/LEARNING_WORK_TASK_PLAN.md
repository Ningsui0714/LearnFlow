# 学习型工作任务 Agent Plan 接入

本阶段只接入可审计的 Plan 构建与确认，不把尚未完成的证据探索、步骤执行、候选评审和局部重规划描述为已实现。

## 运行链

```text
主 Agent 对话
  -> POST /api/learning-task-conversion/plans
  -> 远端 POST /api/v1/learning-work-task-agent/runs
  -> 锁定 task_contract + semantic_fingerprint
  -> 中央工作区 /learning-task-plans/:runId
  -> 用户检查目标、成功条件、不确定项和工作包依赖
  -> POST /api/learning-task-conversion/plans/:runId/confirm
  -> 远端 POST /api/v1/learning-work-task-agent/runs/:runId/plan
  -> PLAN_READY
```

远端返回的 `learning-work-task-plan-v1` 是显式计划产物，不包含或接收隐藏思维链字段。LearnFlow 会再次校验：

- Run ID 与任务语义指纹一致；
- 工作包 ID 唯一，依赖存在且无环；
- 角色、工具和产物类型属于版本化白名单；
- Plan 版本确认时严格递增；
- 当前学习者只能恢复和确认自己会话中创建的 Run。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/learning-task-conversion/plans` | 在当前 Tutor session 中创建真实远端 Run 和初始 Plan |
| `GET` | `/api/learning-task-conversion/plans/{run_id}` | 按 learner ownership 恢复远端状态；远端临时不可用时只读回退到已校验快照 |
| `POST` | `/api/learning-task-conversion/plans/{run_id}/confirm` | 幂等确认当前 Plan，并由远端校验后推进到 `PLAN_READY` |

创建与确认分别记录 `learning_work_task_plan_created` 和 `learning_work_task_plan_confirmed`。两者均为零 kernel target 的计划产物/操作事件，不代表学习、练习或掌握。

## 当前边界

- 已实现：任务契约锁定、初始 TaskPlan、中央页面展示、版本确认、远端恢复、learner 隔离和审计事件。
- 未实现：证据探索、`WorkStepPlan`、候选 A/B/C、Critic、Worker 执行、观察反馈、Plan v2 局部重规划和最终交付。
- 旧的完整任务生成接口仍保留在后端用于兼容；主对话的任务工具现在先进入 Plan 页面，不再把一次最终文本调用伪装成可观察 Planning。

## Contract impact

这是向后兼容的新增能力：增加 `plan_learning_work_task`、一个中央工作台和两个零核事件；没有修改三类主 Agent、五核键、EvidenceEvent schema、确定性归约或现有任务 Bundle 契约。
