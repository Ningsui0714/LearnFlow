# 统一岗位包、联合工具与事理森林实现 v3

> 文件路径保留用于兼容旧链接；“组合快照”和“事理独立包”不再是当前产品概念。

## 1. 唯一事实与唯一身份

一个静态、不可变、版本化的 `Role Package` 是岗位认识的唯一可寻址事实源：

```text
Role Package
├─ evidence：SourceAsset / SourceSegment / EvidenceBinding
├─ semantic：产业链 / 岗位群 / 岗位 / 任务 / 能力 / 能力单元 / 知识技能
└─ process：Scenario / Event / Actor / WorkObject / Artifact / Risk / semantic bridge
```

三个命名空间有不同 schema 和生成节奏，但共享 `packageId + packageVersion + snapshotId`。它们不是三个产品包，也不能分别漂移。卡片、雷达图、事理森林、对话上下文、JD 和学习路径都只是同一岗位包的投影。

旧版持久化数据仍可能包含 `rolePackage / workProcessPackage / compositeSnapshot`。系统只在读取边界兼容它们，并立即归一为 v3 manifest；新写入、发布、引用和 Registry 不再产生这些旧身份。

## 2. 语义图与事理森林的分工

语义链回答“这个岗位稳定地包含什么”；事理森林回答“这些任务在具体场景中如何发生”。一个任务可在多棵场景树出现，一棵树也可实现多个任务，所以过程事件不应伪装成新的典型任务。二者通过 `realizes_task / uses_skill / produces_deliverable` 稳定桥接。

事理对象保留三种认识状态：

- `observed_pattern`：来自有组织、项目、时间和对象边界的真实工作观察；
- `documented_norm`：来自 SOP、制度或公开规范；
- `inferred_pattern`：由 JD、任务或实践资料归纳的候选模式。

## 3. 主 Agent 的读取契约

主 Agent 固定一个岗位包版本，只暴露六个有界感知工具：精确读取、岗位检索、关系查询、事理追踪、证据检查和岗位包审计。节点引用无论来自语义图还是事理森林，都携带同一个包三元组；引用同时标明 `artifactKind`，因此界面仍能切回正确投影。

工具返回统一信封、覆盖信息、引用和可机器处理错误。模型负责综合与表达，不负责重新解释包身份、绕过证据绑定或修改静态快照。

## 4. 前端投影

- 雷达图默认展示低信息熵的岗位内核，细粒度事实仍留在包内；
- 卡片视图按维度纵向切换、同维度横向浏览；
- 事理森林按场景切换，并显示阶段、分支、返工、参与者和交付物；
- 任意节点可点击或拖入对话；引用永久固定到具体岗位包版本；
- 后台语义与事理 enrichment 生成新的不可变子版本，而不是修改当前图。

## 5. 兼容边界

`lib/role-package/runtime.ts` 暂时保留 v1/v2 低级工具与旧静态制品的只读兼容。产品主 Agent、项目岗位包、发布链和 Registry 均使用 `SnapshotRoleRuntime` 与 v3 统一 manifest。兼容层不得成为新功能的依赖入口。
