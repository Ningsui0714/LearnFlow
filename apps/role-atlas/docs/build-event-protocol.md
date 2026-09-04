# Build Event Protocol v0.2

状态：`proposed`\
用途：冷启动运行进程、并行 Lane、图谱生长、暂停恢复与历史回放\
传输：实时 NDJSON/SSE；持久化为 append-only event log

## 1. 目标

同一份事件同时服务：

- 实时 Agent 运行展示；
- 图谱增量更新；
- 多并行分支进度；
- 用户中断与恢复；
- 断线重连；
- 构建历史回放；
- 调试、评测和审计。

事件只表达已经发生的领域变化或可验证运行活动，不把动画命令、React 状态或模型 token 当作领域事实。

现有对话 `AgentEvent v1.1` 保持不变。冷启动使用新的 `BuildEvent`，两者可以在右侧消息流中统一渲染，但不得混用版本和状态 reducer。

## 2. 事件信封

```ts
type BuildEvent<T = Record<string, unknown>> = {
  protocol: "role-atlas.build-event";
  version: "0.2";
  eventId: string;
  runId: string;
  projectId: string;
  seq: number;
  lane?: string;
  laneSeq?: number;
  kind: BuildEventKind;
  phase: BuildPhase;
  visibility: "summary" | "detail" | "debug";
  occurredAt: string;
  recordedAt: string;
  causationId?: string;
  correlationId?: string;
  workItemId?: string;
  payload: T;
};
```

### 2.1 字段规则

- `eventId`：全局唯一，重复投递时用于去重；
- `seq`：同一 run 内由服务端串行分配，严格递增；
- `laneSeq`：同一 Lane 内递增，便于诊断并行乱序；
- `occurredAt`：动作实际发生时间；
- `recordedAt`：事件持久化时间；
- `causationId`：直接触发本事件的事件或命令；
- `correlationId`：一次用户操作、工具调用或语义批次的关联 ID；
- `visibility`：决定默认 UI 层级，不是权限字段；
- `payload`：必须可 JSON 序列化，不能包含 API Key、原始隐私文件或不可稳定复现的对象。

## 3. 阶段

```ts
type BuildPhase =
  | "intake"
  | "clarify"
  | "plan"
  | "research"
  | "boundary"
  | "tasks"
  | "canonicalize"
  | "capabilities"
  | "knowledge_skills"
  | "relations"
  | "converge"
  | "audit"
  | "repair"
  | "compile"
  | "complete";
```

阶段是对用户和评测稳定的领域概念，不能直接使用 LangGraph node name。内部图可以重构而不改变历史事件语义。

## 4. 事件类型

### 4.1 Run

```text
build.run.created
build.run.queued
build.run.started
build.run.pausing
build.run.paused
build.run.resumed
build.run.cancelling
build.run.cancelled
build.run.failed
build.run.ready
build.run.completed
```

`build.run.started`：

```json
{
  "briefRevision": 3,
  "baseVersionId": null,
  "runnerBackend": "cloudflare-workflow",
  "budgets": {
    "maxSources": 80,
    "maxModelCalls": 120,
    "deadlineSeconds": 900
  }
}
```

`build.run.failed` 必须包含稳定错误码、是否可重试、由谁修复和保留到哪个阶段，不能只返回一段异常文本。

### 4.2 Phase

```text
build.phase.started
build.phase.progressed
build.phase.completed
build.phase.skipped
```

进度不能只是一百分比。`progressed` 同时包含：

```json
{
  "label": "正在归并任务候选",
  "completedItems": 18,
  "totalItems": 27,
  "produced": {"candidates": 14, "clusters": 8},
  "next": "检查任务交付物与边界"
}
```

### 4.3 Plan 与 Lane

```text
build.plan.proposed
build.plan.revised
build.lane.started
build.lane.progressed
build.lane.completed
build.lane.failed
```

`build.plan.proposed`：

```json
{
  "summary": "并行研究公开市场、职业标准和用户工作区，先形成任务层再归纳能力。",
  "lanes": [
    {"id": "job-market", "label": "招聘市场", "purpose": "提取市场任务表达", "dependsOn": []},
    {"id": "workspace", "label": "用户工作区", "purpose": "发现真实交付物与隐含职责", "dependsOn": []},
    {"id": "task-reducer", "label": "任务聚类", "purpose": "形成规范任务簇", "dependsOn": ["job-market", "workspace"]}
  ],
  "estimated": {"sources": 40, "firstGraphSeconds": 45}
}
```

### 4.4 Tool 与模型

```text
build.tool.started
build.tool.progressed
build.tool.completed
build.tool.failed
build.tool.retried
build.model.reasoning.delta
build.model.reasoning.completed
build.model.output.delta
build.model.output.completed
```

摘要事件默认 `visibility=detail`；reasoning 和 token delta 默认只在用户展开对应 Lane 时渲染。

`build.tool.completed`：

```json
{
  "tool": "search_public_sources",
  "inputSummary": "生成式 AI 应用工程岗位公开资料",
  "durationMs": 1840,
  "resultSummary": "发现 12 项，保留 7 项",
  "producedRefs": ["source:S-021", "source:S-022"],
  "warnings": []
}
```

不能写入：

- API Key；
- 完整 Authorization header；
- 大段原始私域正文；
- 未经处理的供应商错误正文；
- 无长度上限的完整 prompt。

### 4.5 Project Brief 与边界

```text
build.brief.hypothesized
build.brief.revised
build.boundary.revised
build.boundary.converged
```

`build.boundary.revised`：

```json
{
  "previousRevision": 2,
  "revision": 3,
  "workingTitle": "大模型应用工程师",
  "changed": {
    "addedExclusions": ["以预训练模型架构研究为核心的算法岗位"],
    "addedAdjacentRoles": ["大模型算法工程师"]
  },
  "reason": "任务聚类显示训练与业务应用交付形成两个稳定责任簇。",
  "inputRefs": ["cluster:task-04", "source:S-011"],
  "confidence": 0.81
}
```

### 4.6 Source

```text
build.source.discovered
build.source.capture.started
build.source.captured
build.source.segmented
build.source.rejected
build.source.failed
```

公开来源事件可以显示标题、域名和日期；私域来源默认只显示工作区内相对标签和类型，不显示本地绝对路径。

### 4.7 提及、命题、Candidate 与聚类

```text
build.mention.extracted
build.mention.normalized
build.proposition.extracted
build.entity_match.reviewed
build.candidate.created
build.candidate.updated
build.candidate.stabilized
build.candidate.retyped
build.candidate.rejected
build.cluster.created
build.cluster.merged
build.cluster.split
build.semantic.distinction_added
build.relation.materialized
build.relation.rejected
```

提及和命题事件默认是 `detail` 或计数摘要；原文只通过 `sourceSegmentRef` 引用，不复制到事件日志。它们与 Candidate/聚类事件用于审计和详情，不直接驱动可视图。可视图只消费由同一事务生成的 `build.graph.patched`。

`build.proposition.extracted` 记录的是未物化命题：

```json
{
  "propositionId": "prop:01J...",
  "subjectMentionId": "mention:task:01J...",
  "predicateHint": "requires",
  "objectMentionId": "mention:ks:01J...",
  "sourceSegmentRef": "segment:S-013#p4",
  "assertionMode": "explicit",
  "confidence": 0.82
}
```

`build.relation.materialized` 必须列出规范端点和支持它的命题引用；它与实际增加边的 `build.graph.patched` 在同一事务中产生。

`build.cluster.merged`：

```json
{
  "dimension": "task",
  "canonicalId": "candidate:task:T-03",
  "mergedIds": ["candidate:task:X-19", "candidate:task:X-24"],
  "aliasesAdded": ["编排 Agent 工作流", "构建智能体执行链"],
  "reason": "交付物、触发情境和完成标准一致。",
  "inputRefs": ["source:S-013", "source:S-027"]
}
```

### 4.8 Graph

```text
build.graph.initialized
build.graph.patched
build.graph.layer.started
build.graph.layer.stabilized
build.graph.revision.created
```

`build.graph.patched` 是唯一的增量可视图修改事件。

### 4.9 Audit

```text
build.audit.started
build.audit.issue_found
build.audit.issue_resolved
build.audit.completed
build.repair.started
build.repair.completed
```

Issue 至少包含：

```text
issueId
profile                  structural | semantic | evidence | temporal
severity                 info | warning | error
code
targetRefs[]
summary
repairability            automatic | research | user | developer
```

### 4.10 Human Input

```text
build.human_input.required
build.human_input.received
build.human_input.expired
```

`required`：

```json
{
  "interruptId": "interrupt:01J...",
  "question": "你希望聚焦模型训练还是业务应用交付？",
  "why": "两种解释会生成不同的核心任务集合。",
  "options": [
    {"id": "application", "label": "业务应用交付", "recommended": true},
    {"id": "training", "label": "模型训练"}
  ],
  "allowFreeText": true,
  "attemptedResolution": ["比较任务簇", "检索相邻岗位"],
  "resumePhase": "boundary"
}
```

### 4.11 Version 与发布

```text
build.version.created
build.package.compile.started
build.package.compile.completed
build.package.validation.completed
build.package.publish.completed
build.tag.created
```

## 5. Graph Patch Protocol

### 5.1 信封

```ts
type GraphPatch = {
  patchId: string;
  baseRevision: number;
  nextRevision: number;
  semanticBatch: {
    label: string;
    reason: string;
    phase: BuildPhase;
  };
  operations: GraphPatchOperation[];
  focus?: {
    nodeIds: string[];
    edgeIds: string[];
    mode: "reveal" | "merge" | "stabilize" | "attention";
  };
  stats: {
    nodesAdded: number;
    nodesUpdated: number;
    nodesRemoved: number;
    edgesAdded: number;
    edgesUpdated: number;
    edgesRemoved: number;
  };
};
```

### 5.2 Operation

```ts
type GraphPatchOperation =
  | { op: "add_node"; node: WorkingGraphNode }
  | { op: "update_node"; id: string; revision: number; changes: Record<string, unknown> }
  | { op: "remove_node"; id: string; reason: string; mergedIntoId?: string }
  | { op: "add_edge"; edge: WorkingGraphEdge }
  | { op: "update_edge"; id: string; revision: number; changes: Record<string, unknown> }
  | { op: "remove_edge"; id: string; reason: string }
  | { op: "redirect_edges"; fromId: string; toId: string; edgeIds: string[] };
```

### 5.3 原子性

候选合并时，节点移除、alias 更新和关系重定向必须位于同一个 patch。前端要么全部应用，要么请求完整 working graph，不能显示半完成合并。

### 5.4 版本冲突

客户端只有在 `baseRevision === currentRevision` 时应用 patch。否则：

1. 停止应用后续 patch；
2. 请求 `/graph?runId=...&revision=latest`；
3. 替换本地工作图谱；
4. 从服务端返回的 `lastEventSeq` 继续订阅。

### 5.5 动画规则

前端根据 patch 语义生成动画：

- `add_node`：从关联节点或环层入口出现；
- `add_edge`：在两个节点存在后绘制；
- `merge`：被合并节点向 canonical node 收束；
- `stabilize`：从候选样式过渡为稳定样式；
- `attention`：只标记问题，不持续闪烁。

事件不包含坐标和具体动画时长。布局来自 view 配置，避免运行日志污染语义数据。

## 6. 连接、断线与回放

### 6.1 实时订阅

```text
GET /api/projects/:projectId/build-runs/:runId/events?afterSeq=123
```

服务端先返回 `seq > afterSeq` 的历史事件，再继续实时推送。客户端必须按 `eventId` 去重。

### 6.2 快照加事件

首次打开或事件差距过大时：

1. 获取 `BuildRunView`；
2. 获取最新 `WorkingGraphSnapshot(revision, lastEventSeq)`；
3. 从 `lastEventSeq` 后继续消费事件。

不能依靠从零重放所有 token delta 恢复页面。

### 6.3 回放模式

回放使用领域事件和 Graph Patch，不重新调用模型或工具。允许：

- 1×、2×、4×；
- 按阶段跳转；
- 只看图谱变化；
- 查看某个节点的形成历史；
- 查看一次合并的来源和理由。

模型 reasoning delta 可以保留为运行详情，但不是图谱回放的必要输入。

## 7. 前端 Reducer

前端为每个 run 维护：

```text
lastSeq
runStatus
phase
lanesById
activitiesById
workingGraphRevision
workingGraph
pendingInterrupts
summaryFeed
detailFeed
reasoningStreams
```

Reducer 必须：

- 忽略重复 `eventId`；
- 检测 seq 缺口；
- 不假设并行 Lane 的结束顺序；
- 把 summary/detail/debug 分层；
- 将 Graph Patch 作为原子操作；
- 对未知事件类型前向兼容：保存但不让页面崩溃。

## 8. API 命令

```text
POST /api/projects
POST /api/projects/:id/briefs
POST /api/projects/:id/build-runs
POST /api/build-runs/:id/pause
POST /api/build-runs/:id/resume
POST /api/build-runs/:id/cancel
POST /api/build-runs/:id/human-input
GET  /api/build-runs/:id
GET  /api/build-runs/:id/events
GET  /api/build-runs/:id/graph
POST /api/build-runs/:id/compile
POST /api/projects/:id/tags
```

所有改变运行状态的命令接收 `idempotencyKey`。命令返回当前状态和命令接收事件，不要求 HTTP 连接等待运行完成。

## 9. 存储与保留

建议表：

```text
build_events(run_id, seq) unique
build_events(event_id) unique
working_graph_snapshots(run_id, revision) unique
build_run_views(run_id) unique
```

高频 token delta 可以在运行结束后压缩为 reasoning/content block；领域事件、Graph Patch、SemanticDecision 和版本事件不得被压缩丢失。

## 10. 与现有 AgentEvent v1.1 的关系

| 对话 AgentEvent | 冷启动 BuildEvent |
|---|---|
| 一次问答 run | 一次可持续数分钟或更久的构建 run |
| 固定并读取已发布岗位包 | 生成候选图谱并编译新岗位包 |
| `reasoning.delta`、`answer.delta` | reasoning/output + graph/source/audit/version 事件 |
| 前端会话内恢复 | 数据库事件、工作图谱快照和 Durable Runner 恢复 |
| 不修改岗位包 | 只修改候选沙箱，发布时生成新包 |

两种流可以共享通用的 NDJSON decoder、错误信封和 Markdown 渲染，但必须保持独立类型定义。
