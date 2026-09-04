# 完整岗位包冷启动 Skill v0.2

状态：`workflow 4.2 task-barrier-first vertical slice implemented`

## 1. 目标

冷启动不是“生成一张岗位图”，而是从同一来源与证据层编译完整的候选岗位知识包：

```text
ProjectBrief + SourceInput
  → SourceAsset / SourceSegment / Mention / Proposition
  → TASK BARRIER
  → Role Kernel（第一份不可变岗位快照）
  → 返回项目图谱工作台
      ├→ Cross-task Capability + Knowledge Detail + Skill Dependencies → semantic child version
      └→ Work-process Forest                                      → full child version
      └→ LearnFlow LearningPathGraph → roleLearningProjection      → shared learning interface
  → cross audit + non-blocking structure inspection
```

可视化图谱、事理森林和岗位快照是同一候选事实层的不同制品，不能由三个相互独立的模型回答生成。

## 2. 已实现模块

```text
lib/build/types.ts       领域对象与完整产物类型
lib/build/events.ts      Build Event v2.0
lib/build/model.ts       语义/事理结构化模型适配与 Prompt
lib/build/kernel.ts      任务代表选择、多分辨率投影与事理胶囊
lib/build/compiler.ts    来源分段、规范化、证据绑定、审计与统一岗位包编译
lib/build/graph.ts       LangGraph 并行 Lane、Barrier 与事件流
app/api/build-runs       岗位内核 NDJSON 构建入口
app/api/build-runs/enrich 后台语义/事理增量入口
app/projects/new         新建项目与实时构建工作台
```

## 3. LangGraph 拓扑

```text
START
  → research_sources
  → prepare_sources
  → extract_mentions（按来源分片并发）
  → converge_tasks
  → build_kernel
  → END

BACKGROUND START
  → hydrate_kernel
      ├→ capability + task_knowledge + skill_dependencies ─→ semantic child version
      └→ task_process_expansion ────────────────────────────→ process materialization
  → audit_and_compile
  → full child version
  → END
```

后台知识与事理分支真正并行调用模型。语义分支不等待较慢的事理分支，先提交可寻址的知识技能与依赖子版本；事理完成后提交完整子版本。分支错误被转换为保守降级和研究缺口，不撤销已经提交的岗位内核。

图内节点不依赖进程内 `MemorySaver`。每次运行仍固定 `thread_id = projectId:runId` 作为追踪身份；D1 追加事件、阶段边界和不可变 ProjectVersion 才是恢复与审计依据。

## 4. 证据纪律

1. 用户简报总是登记为 `user_brief` 来源，但只能直接支持用户明确表达的边界。
2. 模型只能引用已经提供的 `SourceSegment.id`。
3. 编译器会检查目标标签是否直接出现在来源分段中；否则绑定降为 `inferred`，置信度上限降低。
4. `observed_pattern` 只有在绑定 `workspace_observation` 时才能成立；其他来源会被确定性降为 `documented_norm` 或 `inferred_pattern`。
5. 没有外部来源、没有任务、任务缺少场景、直接证据覆盖不足等问题都会生成结构化 Issue 和研究主题。
6. 编译完成后统一结构检查器会检查协议、语义、相对覆盖、证据、时间、事理与 Agent 可用性。只有协议不变量是硬阻断；其他发现不会让候选图谱消失。

## 5. 规范化与双图物化

语义节点先以模型 `tempId` 存在。编译器在同一实体类型内通过规范标签和显式 alias 进行约束归并，生成稳定 ID，再重写关系端点。岗位—任务缺失关系可以由编译器生成候选 `performs` 边，但置信度受任务证据限制。

事理节点独立生成 Scenario、Event、Actor、WorkObject、Artifact、Risk 和 Decision。语义桥接只能通过 `realizes_task`、`uses_skill` 或 `produces_deliverable` 建立，事件不会直接混入岗位雷达实体层。

当前版本完成精确/alias 归并、任务代表的 farthest-first 选择和多分辨率投影；Blocking、向量 Top-K、must-link/cannot-link 和可实验的全局 reducer 仍是扩展点。

后台语义完成时不会把全部细粒度知识技能重新铺满首屏：系统用词面距离和命名技术锚点选取最多 5 个技能簇代表、最多 3 个能力入口，其余节点保留稳定 ID 并作为 facet 挂到最近代表节点。这样降低的是默认视图信息熵，不是岗位包信息量。

来源原子抽取还为任务/工作事件记录 `actorRelation`。外部用户、客户、学生和相邻岗位的行动可进入证据层和事理参与者，但确定性 Task Barrier 会阻止它们成为目标岗位的典型任务。

能力由两个以上任务的共同表现要求归纳。能力单元除可观察行为外，必须形成日常培养契约：练习情境、微练习、频率、反馈信号、证据作品、递进和独立完成标准。知识技能区分 knowledge / skill / hybrid，并可对接 LearnFlow 的共享学习路径协议。

学习路径不是第四事实空间。冷启动在 `semantic.learningPathProjection` 中保存岗位节点到 LearnFlow 节点的派生映射：先精确匹配，再模糊读取；歧义保持待选，可靠缺口才形成兼容 `PersonalPathNodeProposal` 的候选。Role Atlas 不写学习者状态，个人节点仍须由 LearnFlow 经学习者确认后写入。

## 6. 产物与状态

完整冷启动版本提交后，项目工作台会自动串联两段全量后处理：

1. `deep_research`：以完整快照为基线，从全局检查中选择最多 5 个高价值工作项，优先处理影响岗位边界、任务骨架、能力抽象、日常培养、学习路径和事理森林的 3—5 个重要问题；
2. `risk_repair`：固定深研输出快照，对协议、重复、维度污染、孤立、失证、覆盖、培养契约、学习路径映射和事理桥接执行全量扫描，只应用可验证的最小补丁。

两段分别产生迭代契约、事件、Diff 和不可变版本。深研未产生新快照时，风险修复继续使用完整冷启动快照；任一段失败都不撤销已经提交的可用版本。

一次成功运行返回：

- `sources.assets / segments / evidenceBindings`；
- `semantic.nodes / edges / claims`；
- `process.scenarios / nodes / edges / bridges`；
- `snapshot.sections`；
- `audit.issues / researchTopics`；
- `packages.rolePackage`：一个外部身份，内含 `evidence / semantic / process` 三个命名空间 manifest；
- `validation` 的结构、语义、证据、时间和过程报告。
- `audit.inspection` 的六个健康轴、核心/前沿、任务覆盖和 Agent 读取探针。

`build.kernel.completed` 表示岗位内核已经可用并已提交版本，不等于后台补全或公开发布成功。`build.enrichment.semantic.completed` 与 `build.run.completed` 分别提交语义子版本和完整子版本；只有 `validation.publishable = true` 才能进入公开发布事务。

## 7. 当前边界

- 真实调用用户配置的 MiMo/DeepSeek，并使用 Tavily 做六类来源检索与知识缺口定点补研；
- 支持粘贴公开、私域和脱敏工作观察资料，尚未实现多文件上传与本地 Workspace Runner；
- 岗位内核、语义补全和完整补全均写入不可变 ProjectVersion，并以父子链保持增量历史；
- 已发布的大模型应用工程师岗位包保持只读，新建项目不会覆盖它；
- Static Role Package 编译、hash manifest、语义 Diff、Tag 与发布事务已有实现；跨 isolate 的 Durable Runner 与后台 checkpoint 恢复尚未完成。

## 8. 下一步

1. 把后台 enrichment 从“有日志”提升为可跨进程租约恢复的阶段任务；
2. 增加本地目录、ZIP 与多文件工作区摄取；
3. 把模型 temp entity 接入向量 Blocking、Top-K 和可实验的约束聚类；
4. 增加远程 Registry 联邦、制品签名与多组织权限；
5. 用获批的端到端评测持续验证 Agent 的有据回答与节点深化。
