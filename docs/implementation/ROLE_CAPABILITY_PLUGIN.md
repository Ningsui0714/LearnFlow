# 岗位能力图谱插件：生成、解释与迭代

状态：implemented
协议：`learnflow.role-capability.v1`
架构注册表：`2026-08-29.2`

## 1. 来源与重构原则

本插件参考 `/Users/a1-6/CEG C/role-agent` 的可观察产品不变量，按 LearnFlow 契约独立实现，没有复制其运行代码、数据库或岗位包数据。逆向阅读聚焦三条纵向链：冷启动生成、固定快照解释、合同化迭代。

阅读前预测及校正：

| 预测 | 结果 | LearnFlow 取舍 |
|---|---|---|
| 岗位包/快照是真相源 | 成立；发布包由不可变快照编译并校验 | `RoleCapabilitySnapshot` 保存完整图、来源闭包、root hash 和校验报告 |
| 解释 Agent 可直接读取工作图 | 不成立；它先 pin 确切快照，再执行有界读取 | 对话工具只读当前不可变快照，返回对象、关系和引用 |
| 迭代 Agent 直接重跑生成 | 不成立；先形成合同、检查、patch、评估，再决定是否建新快照 | `iterate` 只有候选有效且 diff meaningful 才生成后继版本 |
| 工作区观察可直接成为岗位共性 | 不成立；observed pattern 与 documented norm 分层 | 用户迭代和无正式来源任务保持 `inferred_pattern`，不冒充规范事实 |

## 2. 架构位置

```text
Project + processed SourceVersion / explicit task seeds
                    │
                    ▼
        learning_design_agent 领域插件
                    │
   ┌────────────────┼──────────────────┐
   ▼                ▼                  ▼
生成 workflow    解释 workflow       迭代 workflow
合同→编译→校验   pin→有界读取→引用   合同→检查→patch→校验→diff
   │                │                  │
   └──────────► immutable RoleCapabilitySnapshot
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
        项目“岗位图谱”工作台         Tutor 只读对话工具
                 │                         │
                 └────────── zero-target operational events
```

插件位于 `learning_design_agent` 后面，不是第四类主 Agent。Tutor 仍拥有对话和跨空间协调；Learning Design 拥有岗位制品；Practice Agent 与确定性判题边界不变。

## 3. 核心对象

| 对象 | 责任 | 不变量 |
|---|---|---|
| `RoleCapabilityPackage` | learner + project 唯一插件根与当前快照指针 | 指针可变，但不承载岗位事实 |
| `RoleCapabilitySnapshot` | 完整岗位图、来源闭包、校验、root hash | 创建后不可覆盖；版本与 hash 唯一 |
| `RoleCapabilityRun` | 生成/迭代的幂等请求、合同、检查、diff 和结果 | `learner_id + idempotency_key` 唯一；失败可审计 |
| role graph node | role/task/capability/knowledge_skill | 稳定内容 ID、认识状态、evidence refs |
| role graph edge | owns_task/requires_capability/requires_knowledge_skill | 两端必须可解析，禁止悬空引用 |

岗位包是领域知识供给，不是学习者状态。它不会直接成为 `KernelState`、`MemoryFact` 或掌握声明。后续若把图谱节点投影为项目关卡或学习任务，仍需经过既有提案/确认合同；学习证据仍只能来自正式 Attempt/Event reducer 链。

## 4. Workflow

### 4.1 生成

1. 工作台显式提交岗位名称、已处理项目来源和可选任务种子。
2. 固定 SourceVersion ID/hash；来源内容按不可信数据处理。
3. 创建有预算和停止条件的 generation contract。
4. 编译 role → task → capability → knowledge_skill 图。
5. 检查协议版本、稳定 ID、引用闭包、最小对象集合和 Agent probes。
6. 计算 canonical root hash；相同内容复用已有快照。
7. 记录 `role_capability_package_generated` 零 Kernel target 事件。

没有已处理来源且没有显式任务种子时进入 blocked，不发布 generic 岗位壳。

### 4.2 解释 Agent

1. 验证 learner/project ownership。
2. pin 当前或显式指定的包内快照。
3. 对问题做有界对象匹配，最多返回 8 个对象和 12 条关系。
4. 返回 answer、objects、relations、citations、coverage 与 snapshot ref。
5. 不改变岗位事实，不写事件，不写五核。

对话工具：

- `read_role_capability_graph`：回答“图谱里有什么”。
- `explain_role_capability`：回答“为什么需要某能力、任务和知识怎样关联”。

生成和迭代不暴露给模型；当用户在聊天中要求修改岗位包时，Tutor 应引导打开项目的“岗位图谱”页完成显式动作。

### 4.3 迭代 Agent

1. pin base snapshot。
2. 创建含 objective、target IDs、操作预算、验收策略与停止条件的 iteration contract。
3. 检查 base 的协议、覆盖与 evidence readiness。
4. 应用最多 24 个结构化 operation；首版支持 `add_node` 和 `update_node`。
5. 检查候选；悬空边、删除根岗位、无有效操作都会停止。
6. 只有 `meaningful=true` 且无协议错误时创建不可变后继快照。
7. 记录 `role_capability_snapshot_iterated` 零 Kernel target 事件。

## 5. Product Skill、Tool 与对话融合

注册的 Product Skill 为 `role_capability_graphing`，它组合：

- `role_capability_package_runtime`：生成与确定性编译 Harness；
- `role_capability_graph_reader`：模型可见只读 ACI tool；
- `role_capability_explainer`：模型可见只读 ACI tool；
- `role_capability_iteration_runtime`：显式工作台迭代 Harness；
- `project_source_reader`：复用项目来源边界。

工作台 `role_capability_plugin` 嵌入 `/projects/:projectId` 的项目抽屉。用户可以：生成首包、查看版本/hash/校验、浏览对象、提问解释、显式补充任务并形成新版本。它复用 LearnFlow 现有鉴权、项目 ownership、来源版本和 runtime client。

## 6. 异常、恢复与兼容性

- 重复请求：幂等 run 返回原结果，不重复建快照或事件。
- 生成失败：run 保留 `failed` 与 error；当前快照不移动。
- 无变化迭代：run 为 `no_change`；当前快照不移动。
- 候选协议失败：保存 inspection/error；不创建后继快照。
- 取消/崩溃：当前快照仍是最后一个完成且通过校验的版本；running run 可供后续恢复策略识别。
- 权限：所有 API 先校验 learner 对 project 的 ownership；历史快照必须属于同一 package。
- 数据迁移：新增三张表由现有 `create_all` 加法创建，没有修改既有表或 API；旧项目按需首次创建插件根。

Contract impact：新增 Tool、Product Skill、Workbench、Capability、零目标 Event 和四个 API；注册表版本提升。三类主 Agent、五核 schema、EvidenceEvent schema、reducer、RemediationStrategy 与现有项目 API 均保持兼容。

## 7. 验收

- 同输入编译出相同稳定 ID 与图结构；
- 解释固定到 snapshot root hash 且输出有界；
- 悬空迭代候选被协议检查捕获；
- 生成请求幂等；
- 有意义迭代产生 version + 1 和新 root hash；
- 两个运行事件不会产生任何 `KernelMutation`；
- 架构注册表能够解析 API、前端 tool handler 与工作台组件 binding。
