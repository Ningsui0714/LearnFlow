# 学习型任务转化与讯飞星辰接入

## 1. 目的与权威边界

该能力把项目中的具体真实工作任务与固定来源版本发送给运营方配置的讯飞星辰 workflow，并返回可复核的 `role-learning-task-candidate.v1`。它是 Tutor 所有的插件 Product Skill，不是第四个主 Agent，也不是正式学习计划发布器。

- 远程 workflow：生成不可信候选 bundle。
- LearnFlow 后端：校验项目归属、固定 `SourceVersion`、组装有界来源、调用 provider、拉取 bundle、执行确定性 validator、幂等保存候选。
- Tutor：解释候选、检查引用与警告、请求学习者确认。
- Learning Design：仅在未来显式确认合同落地后，才可消费候选并创建正式学习任务。
- Practice：仍独占评分、通过条件和独立验证结果。

候选生成、读取、来源检查、审计与 handoff 准备的 Kernel target 均为空。生成文本、任务卡、步骤数量、资源链接和 workflow 的“校验通过”声明都不是学习者掌握证据。

## 2. 插件合同

插件目录：`frontend/plugins/learning_task_conversion/`。Manifest 只使用 `learnflow.plugin-api.v1` 支持的四类扩展：`objects`、`tools`、`skills`、`renderers`。

| Tool | 类别 | 作用 |
| --- | --- | --- |
| `learning_task_conversion__draft_learning_task` | artifact | 生成未确认候选 |
| `learning_task_conversion__read_learning_task_candidate` | read-only | 读取当前项目候选 |
| `learning_task_conversion__inspect_learning_task_evidence` | read-only | 检查快照、引用、覆盖与 grounding |
| `learning_task_conversion__audit_learning_task_candidate` | read-only | 重新执行确定性校验 |
| `learning_task_conversion__prepare_learning_handoff` | read-only | 形成 Tutor 审阅包；不创建正式任务 |

学习者在对话工具选择器启用插件后，可直接输入具体任务。Skill 要求 Tutor 首先调用 artifact Tool，而不是跳转到另一个页面让用户重复输入。宿主仅暴露 allow-list 操作的 `projectIntegration.request`；插件无法取得后端地址、Cookie、任意 fetch 或 provider 凭据。

## 3. 请求合同

`POST /api/projects/{project_id}/integrations/xingchen/learning-task-candidates`

```json
{
  "schemaVersion": "role-learning-task-candidate-request.v1",
  "requestId": "stable-request-20260901-001",
  "taskTitle": "部署 Nginx 静态站点并验收 HTTPS",
  "taskDescription": "在隔离实训环境完成部署并提交验证记录。",
  "upstreamTask": {},
  "sourceVersionIds": [12, 18],
  "targetStepCount": 6,
  "maxSourceSegments": 16
}
```

`learner_id` 不在请求合同中，由登录会话获得。后端要求 `project_id` 属于当前学习者；`sourceVersionIds` 必须属于该项目，去重后最多 20 个。`requestId` 在 learner + project 范围幂等：相同输入返回同一候选，不同输入复用同一 ID 返回 409。

后端发送给讯飞的 `AGENT_USER_INPUT` 是序列化 JSON，版本为 `learnflow.xingchen-learning-task-request.v1`，包含任务、`source_snapshot`、有界 `source_segments` 与输出合同。来源最多 20 个片段、单片段 1200 字符、来源总量 10000 字符、总 provider 输入 24000 字符；截断会进入 `coverage` 和 `warnings`。

## 4. 候选响应合同

响应保留完整结构字段，不压缩成摘要：

```json
{
  "schemaVersion": "role-learning-task-candidate.v1",
  "candidateId": "ltc_...",
  "requestId": "stable-request-20260901-001",
  "packageId": "learnflow-project:1",
  "packageVersion": "source-set....",
  "snapshotId": "source_snapshot_...",
  "rootHash": "...",
  "lifecycle": "candidate",
  "confirmationStatus": "unconfirmed",
  "groundingStatus": "grounded",
  "sourceSnapshot": {
    "packageId": "learnflow-project:1",
    "packageVersion": "source-set....",
    "snapshotId": "source_snapshot_...",
    "rootHash": "..."
  },
  "sourceBindings": [],
  "citations": [],
  "task": { "steps": [] },
  "mappings": {},
  "assessment": {},
  "coverage": { "partial": false, "truncated": false, "omitted": 0 },
  "warnings": [],
  "assumptions": [],
  "validation": { "valid": true, "kernelWrites": 0, "masteryChanged": false },
  "provenance": {
    "provider": "xunfei-xingchen",
    "flowId": "...",
    "workflowRunIds": [],
    "taskCardId": "...",
    "contractVersion": "learning-task-conversion-integration-bundle-v1",
    "validatorVersion": "learning-task-candidate-validator.v1",
    "kernelTargets": []
  }
}
```

`grounded` 只在 provider 输出实际引用本次发送的 `citationId` 时成立。有来源但 provider 未绑定引用时为 `source_supplied_unverified`；没有可发送来源时为 `ungrounded` 且 `citations=[]`。

## 5. 确定性验证与重试

LearnFlow 不信任 workflow 自报的 gate。Validator 实际检查：候选版本与固定 SHA-256 快照、3—12 个步骤、步骤 ID 唯一、依赖存在且无环、每步 operation/交付物/验收依据、知识技能映射不悬空、citation 属于固定快照、截断遗漏量、外部资源为 HTTP(S) 绝对地址、高风险任务有明确安全要求。任务标题词汇不重合只产生复核 warning，不以硬编码别名阻止所有候选。

结构、引用、依赖或安全失败会把精确 JSON path 诊断送入完整 workflow 重生成，最多两次修复；不会用通用模板冒充 provider 成功。Audit 每次重新执行 validator，不复用候选中的旧 `validation.valid`。

## 6. 错误合同

错误 `detail` 含 `code`、`message`、`stage`、`retryable`、`whoFixes`、`suggestedAction`、`diagnostics`。`stage` 为 `request | provider | bundle | validation | commit`；`whoFixes` 为 `user | learnflow | provider | operator`。

- 422：请求来源或候选结构不满足合同。
- 409：幂等输入冲突。
- 429：provider 限流，可使用同一 requestId 稍后重试。
- 502：provider/bundle 非法响应。
- 503：服务端凭据、授权、网络或外部服务不可用。
- 504：provider 或 bundle 超时。

讯飞 401/403 是服务端集成授权问题，返回 `provider_authorization_failed`、`whoFixes=operator`，不会冒充当前 LearnFlow 用户登录失败。

## 7. 配置与安全

讯飞凭据和 `LEARNING_TASK_BUNDLE_SERVICE_TOKEN` 只从 `backend/.private/learning_task_conversion.xfyun.env` 或 `LEARNING_TASK_XFYUN_CREDENTIALS_PATH` 指向的私密文件读取；`.private/` 已被忽略。示例配置只列变量名，不包含值。bundle 服务必须是通过证书校验的 HTTPS DNS 域名，生产配置拒绝裸 IP；每次读取都携带服务间 Bearer token，`task_card_id` 不是访问凭证。插件和错误 payload 不含密钥。

未配置受信 DNS bundle 地址或服务间 token 时在线能力显式返回不可用，不能伪造成功。Seeded demo 不依赖该在线插件即可完成核心 LearnFlow 闭环。

## 8. Contract impact 与迁移

Registry 从 `2026-09-01.4` 提升为 `2026-09-01.5`，新增稳定 Tool、Product Skill、capability 和三个零 target 候选事件合同。新增 `learning_task_candidate_artifacts` 表；现有启动建表流程会为旧数据库创建该表，不修改现有学习对象或五核表。旧四类插件扩展合同、正式 `LearningTask` API、EvidenceEvent schema 与 reducer 不变。

旧 PR 基于已撤销 generic Plugin Host 的文件不得合并。迁移方式是在当前 main 上启用新内置插件目录、部署后端窄接口，并把旧的页面跳转/Plugin Host 调用替换为对话内 namespaced Tool。旧候选数据不自动迁移；若需迁移，必须先转成当前候选 schema 并重新校验来源快照。

## 9. 尚未完成的正式确认链

当前 handoff 使用 `learnflow.personalized-learning-handoff.v1`，包含 `taskSteps`、`skills`、`resources`、`citations` 和只允许审阅/修订/确认的 `returnContract`。它是 `ready_for_tutor_review` 的只读候选，确实进入 Tutor ToolResult 和 Renderer 消费链，但不会创建正式 `LearningTask`。下一阶段需要另行设计“用户明确确认候选 → Learning Design 创建正式任务”的版本化 API 与事件；在该合同完成前，界面只能显示“让 Tutor 审阅候选”，不能显示“已进入个性化学习”。
