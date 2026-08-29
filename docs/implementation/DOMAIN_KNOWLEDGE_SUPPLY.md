# 统一领域知识供给与来源自维护

## 目标与边界

LearnFlow 的项目 Tutor、简单讲解和五种带领学习 Skill 共用同一条领域真实性链：

```text
用户问题 / 项目目标 / Skill 目标
-> DomainBrief
-> 用户资料 + 项目基线 + 策展底座 + 已读网页原文
-> SourceVersion 健康检查
-> DomainKnowledgePacket
-> TeachingContentBrief
-> Lecture + ConceptQuestion / Exercise
```

这是领域事实平面，不是学习者状态。来源处理、搜索、讲义生成、文件打开和来源失效全部为零 Kernel target；五核 `knowledge` 仍只表示学习者理解证据。

## 正式对象

### SourceVersion

`Source` 保留学习者 ownership 和来源身份。每次内容变化创建不可变 `SourceVersion`；`Chunk.source_version_id` 把片段固定到当时版本。相同内容哈希只刷新 `retrieved_at`，不重复建版本或 Chunk。

可用状态为 `active / stale / conflicted / quarantined / superseded / failed`。新版本不覆盖旧版；旧讲义的引用仍可重放。

### DomainKnowledgePacket

Packet 是按 learner/project/checkpoint/session/learning-task scope 编译的只读 JSON 投影。它保存：

- 已剥离“带我学”等操作语句的 `DomainBrief`；
- 定义、声明、关系、过程、例子、反例、误解和评估依据；
- 每条关键声明的 `source_version_id + chunk_id + locator`；
- 覆盖、时效、冲突、未解决缺口和输入指纹。

Packet 第一版不建第二套全局知识图。只有在跨任务复用率和冲突管理需求被评测证明后，才把 KnowledgeUnit 晋升到更重的领域底座。

### TeachingContentBrief

正式讲义和练习消费同一个 brief：目标、已教声明、完整例子、误解、评估目标、Packet ID/指纹和来源闭包。练习不得测量 brief 中没有教的目标。

## 三种运行模式

- **项目 Tutor**：项目来源先形成 `draft` 基线提案。关键覆盖不足时禁止确认；达标后由学习者显式确认。后续项目 Packet 固定该基线的 SourceVersion，不静默跟随新版。
- **简单讲解**：先读当前附件、项目基线和个人库。覆盖不足、时效问题、版本不匹配、冲突、用户指错或精确机制未读原文时，Harness 再调用现有 Search/Page Reader。稳定且覆盖足够的基础概念复用本地 Packet。
- **带领学习**：五种可选 Skill 在 manifest 中声明 `knowledge_requirements`。Harness 在正式步骤前编译 `guided_skill` Packet；Skill 只组织教学，不自己宣布来源充分。

网页搜索摘要不能支持正式 Claim。`read_web_evidence` 读到原文后，Harness 通过非模型工具接口把原文保存为 `source_role=temporary` 的 SourceVersion，重新编译当前 Packet。它可以用于本轮，但进入项目长期基线仍需学习者确认。

## 教学门禁和失败语义

- `ready`：关键知识槽位、引用闭包、时效和冲突全部通过。
- `ready_with_gaps`：只有非关键缺口，可交付并必须披露。
- `blocked_knowledge`：正式教学所需的定义、机制、例子、边界、误解或评估依据缺失。LearningTask/SkillRun 继续保留，但不创建 Lecture/Practice。

不再存在“把整句用户指令填进关键点并发布”的 generic scaffold 路径。阻塞时只显示简短起点和具体缺口。

## 污染、冲突和时效

```text
discovered -> inspected -> active
                         |-> stale
                         |-> conflicted
                         |-> quarantined
                         `-> superseded
```

- prompt injection、空正文和解析异常自动隔离，并排除出新 Packet。
- 高权威事实冲突保留双方，标记适用范围，不自动删除。
- 来源变化创建新版本；依赖旧版的 Packet/产物标记 stale。
- 理论、版本化软件、当前研究和实时信息分别使用 180 天、30 天、7 天和 1 小时的默认惰性检查窗口。
- 污染只使领域 Packet 和产物失效；不直接回滚五核。要改变掌握结论，仍需新的正式练习证据。

## 兼容与迁移

`v20-domain-knowledge-supply` 为历史 processed/quarantined Source 建立 version 1，回填旧 Chunk。旧 Source/Chunk API 保留，当旧客户端未指定版本时读 active SourceVersion。Teaching Contract schema 从 v1 升到 v2；旧关卡可读，但没有 Packet 时不再获得发布权。

## 验收指标

单元与端到端评测覆盖 SourceVersion 幂等、旧 Chunk 保留、附件优先、Claim 定位引用、污染隔离、网页原文回填、空讲义阻断、讲义—练习同源和零 Kernel target。具体回归位于 `tests/test_domain_knowledge_supply.py`。
