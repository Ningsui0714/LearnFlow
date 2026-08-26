# 隐形领域知识底座与学习文件

## 一分钟逻辑

```text
本地文件 / URL / GitHub
  -> learner-owned Source
  -> 处理为 Chunk + KnowledgeDomain
  -> read_domain_knowledge（只读、带 provenance、不可信内容边界）
  -> 规划态资源策展 / Tutor 讲解上下文

LearningTask
  -> 显式“生成讲义与练习”
  -> hidden task_artifact Project + Checkpoint
  -> Lecture + ConceptQuestion / Exercise
  -> 独立工作台或对话纸张（只保存 artifact ref）
```

来源内容不是学习者状态；文件被生成、打开或接入对话也不是掌握证据。

## 对象权威

- 领域知识底座复用正式 `Project -> Source -> Chunk`。每个 learner 有一个 `project_kind=knowledge_library`、`visibility=internal` 的隐藏 Project，纯粹作为权限与存储边界，不是课程项目，也不显示为独立页面。学习者从 Chat 输入区给当前对话附加文件或 URL；Tutor 只读取该对话明确附加的 source id。
- 讲义权威仍是 `Lecture`；练习权威仍是 `ConceptQuestion` 与 `Exercise`。`.lflecture` / `.lfexercise` 是逻辑文件名，不复制数据库内容。
- 对话纸张只保存 `{kind, ref, title}`，打开时由服务端重新检查 learner ownership，并返回答案安全视图。

## Tool 与 Skill 分工

- `domain_knowledge_reader` 是 ACI Tool：按当前对话附件和问题返回有界领域索引、来源片段和 provenance，不做资源选择。输入区可以显式选择“对话资料”，也可由 Tutor 在“自动”模式中与联网搜索比较。
- `learning_resource_curation` 是规划态 Playbook Skill：先比较个人来源和学习路径覆盖，再用计算机知识搜索补缺；从目标匹配、来源层级、实践价值和成本说明推荐理由。
- `learning_file_service` 管理正式讲义/练习的生成、列表、打开和纸张接入。模型没有文件写工具；生成由显式 UI 动作与确定性 LearningTask runtime 发起。

## 五核与证据

| 事件 | Kernel target | 含义 |
|---|---:|---|
| `knowledge_source_added/processed` | 无 | 资料进入上下文空间 |
| `learning_file_generated/opened/attached_to_chat` | 无 | 产物与 UI 审计 |
| `lecture_viewed` | Knowledge exposure | 明确读过，`mastery_unchanged=true` |
| `concept_attempt_evaluated` | Knowledge + Practice | 确定性评分后的概念题证据 |
| `exercise_attempt_evaluated` | Knowledge + Practice | 沙箱/测试后的实践证据 |

任何文件内容中的指令都被当作不可信数据，不能改变 Agent 目标、安全边界、路径或五核。练习读取接口在提交前隐藏答案、解释、solution 和私有测试预期。

## 后续项目来源迁移

隐藏领域底座中的 Source 具有稳定 owner、Source ID、Chunk ID 与 provenance。项目创建后应通过显式 Action 选择“链接/复制哪些来源到项目 scope”，而不是让规划态静默把全部个人资料变成项目主来源。项目路线仍以项目已确认来源为约束。
