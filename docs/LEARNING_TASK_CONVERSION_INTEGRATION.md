# 岗位典型工作任务转化模块接入 LearnFlow（v1）

## 定位

岗位典型工作任务转化服务由讯飞星辰工作流负责任务规划、检索与候选评审，由独立后端负责语义锁、确定性校验、持久化以及 HTML、PDF、结构化 JSON 交付。LearnFlow 将它作为 `workflow_gateway` 外部产物适配器使用。

该适配器属于学习设计能力平面，不是第四类主 Agent。它的输出必须先通过 LearnFlow 契约校验，不能直接写五核、宣布掌握、决定个性化学习策略或跳过正式验证。

## 配置

```env
LEARNING_TASK_CONVERSION_BASE_URL=http://82.156.199.145
LEARNING_TASK_CONVERSION_TIMEOUT_SECONDS=30
```

调用目标地址只来自服务端配置，前端不能传入任意主机，避免形成开放代理。生产环境可以把地址替换为 HTTPS 域名；讯飞凭据仍只保存在岗位任务转化服务端，不进入 LearnFlow 浏览器。

## LearnFlow API

所有接口位于 LearnFlow 自身 `/api` 下并复用当前登录态：

| LearnFlow 接口 | 用途 | 远端接口 |
|---|---|---|
| `GET /api/learning-task-conversion/capabilities` | 契约发现与健康检查 | `/api/v1/learning-task-conversion/capabilities` |
| `POST /api/learning-task-conversion/upstream-handoffs` | 转交岗位能力图谱确认的单项企业任务 | `/api/v1/learning-task-conversion/upstream-handoffs` |
| `GET /api/learning-task-conversion/tasks/{task_card_id}/bundle` | 获取任务、强关系、追溯和展示产物 | `/api/v1/learning-task-conversion/tasks/{task_card_id}/bundle` |
| `GET /api/learning-task-conversion/tasks/{task_card_id}/personalized-learning` | 获取个性化学习输入 JSON | `/api/v1/learning-task-conversion/tasks/{task_card_id}/personalized-learning.json` |
| `POST /api/learning-task-conversion/downstream-feedback` | 回传关系过弱、知识范围错误或步骤映射问题 | `/api/v1/learning-task-conversion/downstream-feedback` |

## 前端使用

`frontend/src/services/api.ts` 已提供：

```ts
const bundle = await getLearningTaskConversionBundle(taskCardId)
const task = bundle.task.work_task

// 一个企业真实工作任务，对应按真实作业顺序生成的可变数量步骤。
for (const step of task.task_steps) {
  console.log(step.action, step.deliverable, step.check)
  console.log(step.knowledge_point_ids, step.skill_point_ids)
}

window.open(bundle.artifacts.interactive_html_url, '_blank', 'noopener,noreferrer')
```

LearnFlow 后续个性化学习只组织“怎么学”：路线、讲解、练习、反馈与补弱；不得改写交付中的企业任务名称、任务步骤以及步骤—知识点—技能点映射。

## 上游交接示例

```json
{
  "schema_version": "competency-graph-learning-task-handoff-v1",
  "upstream_task_id": "network_vlan_001",
  "correlation_id": "learnflow-demo-001",
  "task_name": "交换机 VLAN 配置与连通性验收",
  "task_brief": "依据网络规划创建 VLAN、配置端口、验证终端连通性并提交验收记录。",
  "source_context": {"source_system": "岗位能力图谱生成功能"},
  "knowledge_points": [
    {
      "knowledge_id": "knowledge_vlan_01",
      "name": "VLAN 划分与 802.1Q 标记",
      "description": "理解 VLAN 广播域、Access/Trunk 端口及 802.1Q 标签的作用。"
    }
  ],
  "skill_points": [
    {
      "skill_id": "skill_vlan_01",
      "name": "创建 VLAN 并配置端口模式",
      "observable_action": "能够按规划创建 VLAN、配置 Access/Trunk 端口并保存配置。"
    }
  ],
  "relations": [
    {
      "relation_id": "relation_vlan_01",
      "knowledge_id": "knowledge_vlan_01",
      "skill_id": "skill_vlan_01",
      "relation_type": "required_for_step",
      "strength": "critical",
      "reason": "端口模式和 VLAN 标记知识直接支撑交换机配置与验收。",
      "applies_to_steps": ["configure_vlan"]
    }
  ]
}
```

远端服务会执行完整契约校验并返回可回传上游的语义反馈。

## 下游反馈示例

```json
{
  "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
  "task_card_id": "ltc_xxx",
  "correlation_id": "learnflow-demo-001",
  "source_system": "LearnFlow",
  "status": "accepted_with_feedback",
  "issues": [
    {
      "issue_id": "issue-001",
      "feedback_code": "step_mapping_mismatch",
      "severity": "warning",
      "step_id": "step_03",
      "knowledge_id": "knowledge_vlan_trunk",
      "message": "该知识点与当前步骤的直接关系不足。",
      "suggested_correction": "移动到 Trunk 配置步骤，或补充本步骤需要该知识的验收依据。"
    }
  ],
  "summary": "任务主体可用，建议修正一处步骤映射。"
}
```

反馈只提出问题，不能在 LearnFlow 内静默改写企业任务事实。修订后的任务必须重新经过岗位任务转化服务的门禁。

## v1 验收边界

- 已实现：服务端固定地址代理、超时和错误归一化、版本校验、步骤字段校验、知识/技能引用完整性校验、前端调用封装、上下游反馈通道。
- 未在本版实现：把任务自动物化为 LearnFlow 项目和关卡。该操作会引入 Action Board 副作用、学习者作用域和路线确认，需要作为下一阶段单独登记和实现。
