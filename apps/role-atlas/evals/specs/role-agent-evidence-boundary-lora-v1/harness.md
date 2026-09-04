# Harness 规格：role-agent-evidence-boundary-lora-v1

Status: approved

## Entrypoint

- 生产核心入口：`createRoleAgent(modelInvoker, new SnapshotRoleRuntime(snapshot)).stream(...)`。
- 代码位置：`lib/agent/graph.ts`、`lib/agent/model.ts`、`lib/agent/planner.ts`、`lib/agent/grounding.ts`、`lib/agent/snapshot-runtime.ts`。
- 源码基线：Git `c8f4bc6894946768c788138adcce17a1a41de64b` 加当前工作树中的 Agent 实现。正式运行前必须生成包含全部可达 Harness 源码、`package.json` 和锁文件的 SHA-256 清单；源码摘要变化后旧结果失效。

## Preserved behavior

- 保留现有线性 LangGraph：请求校验 → 确定性工具规划 → 并行工具执行 → 覆盖检查 → 模型生成。
- 保留现有系统提示词、上下文拼装顺序、36,000 字符上限、引用注册表及候选内容告警。
- 保留六个只读岗位工具及其原始参数、结果、错误和缓存行为；本题预计由现有规划器选择 `read_role_objects` 与 `inspect_role_evidence`，但评测不把工具名或调用次数作为得分条件。
- 保留 `provider_raw` 输出：模型正文不会被后处理、补写引用或拦截。这是本题要覆盖的真实风险。
- 使用生产模型调用器 `createModelInvoker`，配置为 `provider=mimo`、`model=mimo-v2.5`、`thinking=true`；保留流式响应和现有超时语义。
- 单轮请求，`history=[]`，LangGraph `checkpointer=false`；每次 trial 新建 Runtime、run ID 和 session ID。

## Adapter

Harbor 适配器仅做边界翻译，不改变 Agent 决策：

1. 将 `instruction.md` 全文原样写入 `AgentRequest.message`。
2. 把环境提供、且对 Agent 可见的已选节点卡片写入 `AgentRequest.references`：
   - packageId: `role-package:llm-app-engineer-golden`
   - packageVersion: `1.0.0`
   - snapshotId: `snapshot:role:llm-app-engineer@2026-08-24-gold-v1`
   - targetId: `knowledge:llmapp:peft-lora-conditional`
3. 从冻结静态文件组装 `ColdStartBuildResult`，注入 `SnapshotRoleRuntime`；不调用默认 bundled snapshot。
4. 消费 `streamMode=custom` 的原始 Agent 事件，保存 ATIF/等价事件记录与最终正文；不得修订正文、决定答案或伪造工具事件。

## Session

- 单轮、单会话、无预置历史。
- 首个且唯一用户消息必须等于 `instruction.md`；节点卡片作为与生产 API 一致的结构化引用随请求传入。
- `answer.completed` 后结束，不追加模拟用户消息。

## Credentials

- Harness 仅接收 `MIMO_API_KEY`。
- 不向 Harness 注入验证器规则、隐藏证据或 judge 凭据。

## Recorded evidence

- 用户消息、结构化节点引用和非秘密模型配置。
- 全部 Agent 事件及时间顺序，包括规划、工具参数、工具结果摘要、告警、覆盖状态和引用注册表。
- 模型 reasoning/text 流、最终正文、终止原因、错误与超时类型。
- 黄金包根哈希和 Harness 源码清单摘要。

## Reconstruction differences

- 不经过 `app/api/agent/route.ts` 的 HTTP/NDJSON、Provider session 解析和数据库会话持久化，而是直接运行同一个生产 Agent 图。
- 本题是合法的单轮只读请求，因此上述省略不改变提示词、规划器、工具实现、模型调用或答案生成；若实现验证发现任何这些行为发生变化，必须将其标为 reconstruction 并重新审批本规格。
