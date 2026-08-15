# 岗位典型工作任务转化模块接入 LearnFlow（v1）

## 定位

岗位典型工作任务转化服务由讯飞星辰工作流负责任务规划、检索与候选评审，由独立后端负责语义锁、确定性校验、持久化以及 HTML、PDF、结构化 JSON 交付。LearnFlow 将它作为 `workflow_gateway` 外部产物适配器使用。

该适配器属于学习设计能力平面，不是第四类主 Agent。它的输出必须先通过 LearnFlow 契约校验，不能直接写五核、宣布掌握、决定个性化学习策略或跳过正式验证。

## 配置

```env
LEARNING_TASK_CONVERSION_BASE_URL=http://82.156.199.145
LEARNING_TASK_CONVERSION_TIMEOUT_SECONDS=30
XINGCHEN_API_KEY=...
XINGCHEN_API_SECRET=...
XINGCHEN_FLOW_ID=...
XINGCHEN_UID=learnflow-wf03
XINGCHEN_WORKFLOW_TIMEOUT_SECONDS=240
# 下游模块接入后填写其站内路由；接入前留空
PERSONALIZED_LEARNING_ENTRY_PATH=/personalized-learning/start
```

调用目标地址只来自服务端配置，前端不能传入任意主机，避免形成开放代理。生产环境可以把地址替换为 HTTPS 域名。讯飞 APIKey、API Secret 和 Flow ID 只保存在 LearnFlow 后端环境变量中，不进入浏览器或前端 `.env`。

## LearnFlow API

所有接口位于 LearnFlow 自身 `/api` 下并复用当前登录态：

| LearnFlow 接口 | 用途 | 远端接口 |
|---|---|---|
| `GET /api/learning-task-conversion/capabilities` | 契约发现与健康检查 | `/api/v1/learning-task-conversion/capabilities` |
| `POST /api/learning-task-conversion/generate` | 以对话原文调用已发布的讯飞异步工作流并取得任务包 | 讯飞 `async/chat/completions` 与 `async/chat/result` |
| `POST /api/learning-task-conversion/upstream-handoffs` | 转交岗位能力图谱确认的单项企业任务 | `/api/v1/learning-task-conversion/upstream-handoffs` |
| `GET /api/learning-task-conversion/upstream-handoffs/{handoff_id}` | 查询已接收的上游原始 JSON、状态和语义反馈 | `/api/v1/learning-task-conversion/upstream-handoffs/{handoff_id}` |
| `GET /api/learning-task-conversion/tasks/{task_card_id}/bundle` | 获取任务、强关系、追溯和展示产物 | `/api/v1/learning-task-conversion/tasks/{task_card_id}/bundle` |
| `GET /api/learning-task-conversion/tasks/{task_card_id}/personalized-learning` | 获取个性化学习输入 JSON | `/api/v1/learning-task-conversion/tasks/{task_card_id}/personalized-learning.json` |
| `POST /api/learning-task-conversion/tasks/{task_card_id}/downstream-launch` | 校验交付数据并生成下游启动包；本身不创建项目、不写学习状态 | 读取任务包与个性化学习 JSON |
| `POST /api/learning-task-conversion/downstream-feedback` | 回传关系过弱、知识范围错误或步骤映射问题 | `/api/v1/learning-task-conversion/downstream-feedback` |

## 两侧对接顺序

### 上游岗位任务进入本模块

1. 上游在用户点击某个具体岗位任务后，调用 `POST /api/learning-task-conversion/upstream-handoffs`，请求体使用 `competency-graph-learning-task-handoff-v1`。
2. LearnFlow 先用严格模型检查任务、知识点、技能点和关系字段，再交给转化服务保存。响应中的 `handoff_id` 是后续唯一引用；页面地址中不传整包 JSON。
3. 上游可使用响应里的 `learnflow_integration.handoff_status_path` 查询保存结果和语义反馈。
4. 当前已发布的讯飞工作流只声明 `AGENT_USER_INPUT`。若要让“点击上游任务后直接生成”完整保留 `handoff_id`，下一次发布工作流时还需增加 `COMPETENCY_GRAPH_HANDOFF_ID` 输入并传入提交插件。接口会明确返回 `generation_binding_status=pending_xingchen_handoff_parameter`，避免把未关联的对话生成误报为已关联生成。

### 本模块进入个性化学习

前端点击“进入个性化学习”时调用：

```json
{
  "schema_version": "personalized-learning-launch-request-v1",
  "entry_mode": "whole_task"
}
```

如需从一个知识点进入，则使用 `entry_mode=knowledge_point` 并提供 `selected_knowledge_id`。接口会同时校验任务包、下游 JSON、核验状态以及知识点归属，返回 `learning-task-to-personalized-learning-launch-v1`：

- `handoff.payload`：下游可以直接接收的完整 JSON。
- `handoff.url`：下游需要按需拉取时使用的 LearnFlow 登录态地址。
- `correlation_id`：两侧日志、回调和问题定位共用的关联 ID。
- `formal_release_allowed`：只有来源核验通过时才为 `true`。
- `open_path`：配置 `PERSONALIZED_LEARNING_ENTRY_PATH` 后生成，只携带任务 ID、关联 ID 和可选知识点 ID，不把 JSON 放进 URL。

在下游页面尚未绑定时，接口正常返回 `status=pending_binding` 和 `open_path=null`。这表示 JSON 已准备好但路由未接通，不会创建空项目或伪造跳转成功。下游团队确定站内路由后只需配置 `PERSONALIZED_LEARNING_ENTRY_PATH`，例如 `/personalized-learning/start`。

## 前端使用

主工作区的使用流程：

1. 用户在右侧主 Agent 对话栏开启“生成学习型任务网页”，输入计算机专业真实工作任务。
2. LearnFlow 后端调用讯飞异步工作流，轮询完成后解析任务卡 ID，并取得通过契约校验的结构化任务包。
3. 结果通过公开站内路径 `/learning-tasks/{task_card_id}` 直接在中间编辑区渲染，左侧项目栏和右侧对话栏保持不变，不打开新的浏览器窗口。旧路径仅作兼容，不用于新跳转。
4. 用户可以用鼠标左键拖选任务步骤、知识点或技能点，在任务页右侧添加批注并提交复核。

`frontend/src/services/api.ts` 提供生成、读取和反馈调用：

```ts
const generated = await generateLearningTaskConversion(userMessage)
const bundle = generated.bundle
const task = bundle.task.work_task

// 一个企业真实工作任务，对应按真实作业顺序生成的可变数量步骤。
for (const step of task.task_steps) {
  console.log(step.action, step.deliverable, step.check)
  console.log(step.knowledge_point_ids, step.skill_point_ids)
}
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

- 已实现：服务端固定地址代理、讯飞异步 Workflow API 调用、严格上游 JSON 模型、交接记录查询、下游启动包、核验与知识点归属校验、可配置站内入口、中间编辑区任务网页、鼠标选区批注、前端调用封装、上下游反馈通道。
- 未在本版实现：讯飞工作流接收上游 `handoff_id` 的发布参数、下游个性化学习页面本身，以及把任务物化为 LearnFlow 项目和关卡。后两项属于下游职责和 Action Board 副作用，不能在本适配器内提前伪造。

## Contract impact

本次只扩展已登记的 `workflow_gateway` 外部适配器，新增版本化的上下游边界，不改变三类主 Agent、五核、`EvidenceEvent`、Action Board 或学习状态语义；因此无需提升架构注册表版本。旧任务页路径和既有 API 均保持兼容。
