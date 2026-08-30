# 岗位能力图谱首插件：生成、解释与迭代

状态：implemented
插件 ID：`role_capability_graph`
包协议：`learnflow.plugin-package.v1`
对象协议：`role-capability.object.v1`
架构注册表：`2026-08-30.3`

岗位能力图谱是 LearnFlow 通用插件宿主的首个官方插件。它参考 `/Users/a1-6/CEG C/role-agent` 的可观察
产品不变量，按 LearnFlow 契约独立实现，不复制其运行代码、数据库或岗位包数据。通用安装、运行、权限、
制品和对象引用契约以 `docs/implementation/PLUGIN_HOST.md` 为准；本文只规定岗位领域语义与旧实现迁移。

## 1. 架构位置

```text
Project + 固定 SourceVersion / DomainKnowledgePacket / 显式任务种子
                            │
                            ▼
              role_capability_graph Instance
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
       generate          explain             iterate
   合同→候选→校验     pin→有界读取→引用   pin→合同→patch→diff
          │                 │                  │
          └─────────────────┴─────────► 宿主验证
                                            │
                                            ▼
                              immutable PluginSnapshot
                                 + PluginObjectIndex
                                            │
                         ┌──────────────────┴─────────────────┐
                         ▼                                    ▼
              项目 PluginSurfaceHost               Tutor 通用只读工具
                         │                                    │
                         └──────── Action proposal / zero-target event
```

插件 owner 是 `learning_design_agent`，不是第四类主 Agent。Tutor 仍拥有对话、工具发现和 handoff；
Learning Design 只生成岗位制品候选；Practice Agent、确定性评分、RemediationStrategy 与五核边界不变。
runner 内的解释/迭代 Agent 不能批准自己的结果或直接写对象、核心模型、EvidenceEvent 或 KernelState。

## 2. Bundle manifest

官方 `role_capability_graph.lfplugin` 声明：

- object types：`role`、`task`、`capability`、`knowledge_skill`、`claim`、`semantic_edge`、`scenario`、
  `process_event`、`actor`、`work_object`、`artifact`、`risk`、`bridge`；
- workflows：`generate`、`explain`、`iterate`、`validate`、`upgrade`；
- Product Skill：`role_capability_graphing`，owner 为 `learning_design_agent`；
- 项目 `project.context.tabs` Surface；
- 两个只读对话工具：读取图谱与固定快照解释；
- Host Ports：`project.read.v1`、`source.read.v1`、`knowledge_baseline.read.v1`、
  `model.generate_structured.v1`、`event.record.v1`；
- 运行事件：只允许 namespaced、零 Kernel target 的生成与迭代事件。

包不包含 SQL migration、ORM adapter、React/JavaScript、HTML、CSS 或核心对象写接口。生产运行要求受信、
未撤销发布者的 Ed25519 签名以及操作员显式开启 `trusted_signed_process`；即使官方签名受信，仍必须显示
`filesystem_isolation=false`、`network_isolation=false`、`secrets_isolation=false`、
`cpu_isolation=false` 和 `memory_isolation=false`。

## 3. 快照与领域对象

岗位领域事实只存在 `PluginSnapshot` 的内容寻址组件中：

| 组件 | 内容 | 约束 |
|---|---|---|
| evidence | 固定来源、断言和 provenance | SourceVersion/hash 必须可解析；来源内容不可信 |
| semantic graph | 对象节点、语义边、claim 与风险 | 稳定 ID；边两端必须闭合 |
| process forest | scenario、process_event、actor、work_object、artifact | 事件顺序与参与关系必须可验证 |
| views | 面向角色、任务、能力和过程的声明式投影 | 不复制或覆盖图谱事实 |
| retrieval index | 有界解释使用的确定性检索索引 | 可从事实组件重建 |
| validation report | 结构、证据、语义、引用与 Agent probe 结果 | 失败候选不得提交 |
| reference migrations | 前后版本对象引用迁移映射 | 不改写历史引用 |

`PluginObjectIndex` 只保存 object ID、type、label、component/JSON Pointer、content hash、生命周期和引用；
它必须能从快照重建，不能成为第二份岗位图谱。岗位节点的 `accepted / candidate / deprecated` 是领域对象
生命周期；`documented_norm / inferred_pattern` 是岗位断言的认识状态，二者都不是 Knowledge 或 Practice
掌握等级。

跨核心对象引用岗位节点时必须固定完整 `learnflow.plugin-object-ref.v1`，包括 plugin/instance/snapshot ID、
snapshot root hash、object type/ID、schema version 和 object content hash。读取历史任务时不得自动替换成
当前快照的同名对象。

## 4. Workflow

### 4.1 `generate`

1. 宿主验证 learner/project ownership、Instance/release、授权、配置、幂等键和输入 schema。
2. 固定 SourceVersion ID/hash、已确认的 DomainKnowledgePacket 和显式任务种子；来源正文标为不可信。
   每个 Chunk 保留自己的 SourceVersion ref，不得把多来源内容统一归因到第一条来源。宿主注入的
   `max_tasks` 与 `include_process_view` 配置分别约束任务预算和过程视图投影。
3. runner 建立有预算和停止条件的 generation contract，并生成候选 evidence、semantic graph、process forest
   与 views。
4. `validate` 检查协议、稳定 ID、引用闭包、证据可解析性、最小对象集合、process/semantic bridge 和 probes。
5. 宿主重新校验组件、构建 retrieval/object index、计算 canonical root hash 并原子提交 Snapshot。
6. 宿主通过 `record_event()` 记录声明过的生成事件；该事件零 Kernel target。

没有可用的已处理来源且没有显式任务种子时，Run 进入 blocked，不发布通用岗位壳。相同 instance 幂等键
绑定 canonical request hash：同键同请求返回原 Run，同键不同请求返回 `409 Conflict`。

### 4.2 `explain`

1. 宿主验证 ownership，并固定显式或当前 snapshot 的 ID 与 root hash。
2. runner 对 retrieval index 做有界搜索，再进行有界关系遍历，并从同一 Snapshot 的 evidence 组件读取
   source 与 claim 摘要。
3. 返回 answer、objects、relations、带固定 source/claim 的 citations、coverage 和完整 snapshot ref。
4. 宿主检查所有引用都属于固定 Snapshot；超预算或悬空引用使本次 Run 失败。

解释不修改对象、不移动 Instance 指针、不记录学习掌握事件。旧
`read_role_capability_graph` 与 `explain_role_capability` 只是该通用只读调用路径的兼容别名。

### 4.3 `iterate`

1. 请求必须提交 `expected_snapshot_id`；与当前基线不一致返回 `409 Conflict`。
2. runner 固定 base snapshot，形成 objective、target IDs、操作预算、验收策略和停止条件。
3. 检查 base 的协议、覆盖、evidence readiness 和目标引用。
4. 生成结构化 patch，随后运行结构、节点/关系类型、证据闭包、语义端点类型、process/semantic bridge 与
   引用校验；缺失证据不再只是 warning。
5. 计算 meaningful diff；无有效变化进入 `no_change`，不创建 Snapshot。
6. 只有宿主复验通过才创建不可变后继 Snapshot、重建 ObjectIndex 并原子移动 current snapshot 指针。
7. 宿主记录零 Kernel target 的迭代事件。

### 4.4 `validate` 与 `upgrade`

`validate` 是宿主提交前的必经 workflow，不能由 runner 的“自报成功”替代。`upgrade` 在旧 release 与当前
Snapshot 上运行兼容/迁移；只有候选满足新 release 的 schemas、引用和 root hash 契约，宿主才在同一事务中
切换 release 与 snapshot。失败时 Instance 继续固定旧 release 和旧 snapshot。

## 5. Surface、Tool 与对话

项目岗位页由通用 `PluginSurfaceHost` 渲染，只使用 section、text、metric、list、table、graph、form、input、
citation、status 和 action。它展示当前 snapshot/version/root hash、校验报告、对象/关系、过程视图、来源
引用和 Run 状态；不执行插件脚本、HTML、CSS 或任意 URL。generate/iterate/upgrade action 只能引用 manifest
workflow，并遵守 expected snapshot、幂等和用户确认。

Tutor 不把岗位插件专用工具常驻硬编码进模型工具面。标准路径为：

```text
discover_project_plugin_tools
  -> 当前项目已启用、获授权的岗位只读 tool + schema
  -> call_project_plugin_tool
  -> 固定 Snapshot 的有界结果与引用
```

插件若要把 capability/task 节点转成 Roadmap、Checkpoint、LearningTask 或 LearningFile，只能返回带固定
`PluginObjectRef` 的 `action.propose.v1` proposal。Action Board 展示确认卡，用户确认后由核心 capability 和
既有对象服务执行。生成和迭代不直接暴露给 Tutor 模型。

## 6. 迁移与兼容性

历史 `RoleCapabilityPackage / RoleCapabilitySnapshot / RoleCapabilityRun` 通过幂等迁移转换为：

```text
RoleCapabilityPackage  -> PluginInstance(role_capability_graph)
RoleCapabilitySnapshot -> PluginSnapshot + 可重建 PluginObjectIndex
RoleCapabilityRun      -> PluginRun / PluginRunEvent
```

迁移保留原 version、parent、root hash、来源引用、合同、检查、diff、结果和 provenance；转换后的对象引用必须
解析到内容一致的通用 Snapshot。旧三表随后冻结为只读兼容源，不再双写，也不再作为新运行的权威。迁移可
重复执行且不得重复创建 Instance、Snapshot、ObjectIndex、Run 或事件。

旧 `/api/role-capability/...` 路由保留为 deprecated compatibility aliases，内部按 ownership 转发通用宿主，
响应附带 deprecation metadata 和通用 replacement route。旧 `read_role_capability_graph`、
`explain_role_capability` 工具名同样保留，但内部走 discovery/call，并返回 replacement tool metadata。
禁用 Instance 后旧别名也不可继续运行；历史固定引用仍可读取。

## 7. 五核与证据边界

岗位图谱是领域知识供给，不是学习者画像、掌握声明或第六个 Kernel。以下行为都不能产生
`KernelMutation`：安装/启用插件、生成/校验 Snapshot、解释/阅读对象、迭代/升级、打开 Surface、创建
Action proposal。

外部插件只能提议 manifest 已声明的零 Kernel target 事件，宿主经统一 `record_event()` 写入。即使岗位对象
被确认转成 Roadmap、Checkpoint 或 LearningTask，也只证明核心对象已创建；学习状态仍唯一经过：

```text
LearningAttempt / 已登记用户行为
  -> EvidenceEvent
  -> five_kernel_reducer
  -> KernelMutation
  -> KernelState
```

## 8. 失败与验收

- 生成失败、协议失败或 runner 崩溃：Run 可审计，current snapshot 不移动。
- 无变化迭代：Run 为 `no_change`，不创建新版本。
- expected snapshot 过期或同幂等键异请求：返回 `409`。
- 发布者/release 撤销：历史可读，立即阻止新运行。
- 升级失败：旧 release/snapshot 继续可用。
- 同输入生成稳定对象 ID 与 root hash；索引删除后可从 Snapshot 重建。
- 解释结果固定精确 snapshot、输出有界且 citation 可解析。
- 迭代必须有结构/证据/语义校验和 meaningful diff，悬空引用不得提交。
- 迁移前后 root hash、对象内容和固定引用一致；旧接口返回 deprecation metadata。
- generate/explain/iterate/validate/upgrade 与 Surface 阅读均不产生 `KernelMutation`。

Contract impact：专用岗位三表、四 API 和两个静态 Tutor tool 从事实权威降为只读迁移源/兼容别名；新增
通用 Plugin Instance/Snapshot/ObjectIndex/Run、官方 Bundle、声明式 Surface 与动态只读工具发现路径。
该迁移保持旧数据和引用可读，不改变三类主 Agent、五核 schema、EvidenceEvent schema、reducer、
RemediationStrategy 或核心学习对象 API。
