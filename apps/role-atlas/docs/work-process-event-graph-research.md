# 岗位事理图谱研究与协议草案 v0.1

状态：`research-track`\
用户界面名称：岗位事理图谱\
内部暂定名称：Work Process/Event Graph（WPEG）\
目标：表达岗位工作在具体情境中的事件、对象、状态、交付物、决策、交接和异常，并与岗位语义图谱交叉验证

## 1. 是否改变现有方案

它不推翻 Static Role Package、候选沙箱、事件流、版本/Tag 和岗位语义图谱，但要求现在预留四个接口：

1. 来源分片可以抽取工作事件、工作对象、交付物和参与者观察；
2. 证据层能够区分实际观察、资料描述和 Agent 归纳；
3. 岗位语义节点有稳定 ID，可被事理事件映射；
4. 审计系统允许来自事理图谱的交叉检查产生 Issue 和研究主题。

完整事理图谱不进入第一版冷启动关键路径。先做小样本研究，避免在 schema 未验证前扩大核心岗位包。

## 2. 两张图回答不同问题

### 2.1 岗位语义图谱

回答相对稳定的“是什么”：

- 这个岗位处于什么产业和岗位群；
- 承担哪些典型任务；
- 需要哪些跨场景能力；
- 应学习哪些知识技能；
- 与相邻岗位怎样不同。

### 2.2 岗位事理图谱

回答情境化的“怎样发生”：

- 什么触发一次工作；
- 哪些对象在过程中被创建、读取、修改或交付；
- 步骤是顺序、并行、分支、循环还是异常恢复；
- 谁与谁交接，使用什么系统；
- 在哪里检查质量、作出决策或升级风险；
- 最终产生什么结果；
- 实际 episode 与规范流程或 JD 描述有什么张力。

二者不能合并成一张默认雷达图。事理图谱是同一岗位包的独立投影，可从一个任务或场景进入。

## 3. 最关键的认识状态分离

### 3.1 WorkEpisode：真实或记录到的工作实例

来自工作区、业务系统、会议/工单/提交记录或用户提供的复盘。它描述“这一次发生了什么”，带时间和对象身份。

```text
WorkEpisode
  id
  project_id
  scenario_template_id?
  title
  started_at?
  ended_at?
  status
  object_refs[]
  source_refs[]
  observation_mode       direct_record | retrospective | document_trace
  privacy_class
  confidence
```

### 3.2 WorkScenarioTemplate：跨实例归纳的工作场景模板

来自多个 episode、职业标准、流程规范、实践资料或 Agent 归纳。它描述“在这种情境中通常怎样工作”，不是一次真实记录。

```text
WorkScenarioTemplate
  id
  role_id
  title
  goal
  trigger
  preconditions[]
  expected_outcomes[]
  variants[]
  task_refs[]
  source_refs[]
  knowledge_state       observed_pattern | documented_norm | inferred_pattern
  confidence
  temporal_scope
```

不得把单个企业或学生项目的 episode 直接提升为岗位共性模板；模板归纳必须保留支持样本、适用范围和反例。

## 4. 核心实体

| 实体 | 含义 | 关键字段 |
|---|---|---|
| `Scenario` | 有目标和边界的一类工作情境 | goal、trigger、outcome、variants |
| `WorkEvent` | 发生过或模板化的一次活动/事件 | verb、time/order、status、source |
| `Decision` | 改变后续路径的判断 | criterion、options、decision maker |
| `Actor` | 执行、协作、审批或接收者 | role ref、responsibility、organization scope |
| `WorkObject` | 被事件关联和推进的业务对象/case | type、identity scope、lifecycle |
| `Artifact` | 可读、可提交、可验证的工作产物 | format、version、acceptance criteria |
| `ToolSystem` | 承载事件或处理对象的系统 | usage、boundary、not a capability |
| `StateSnapshot` | 对象在某时刻的状态 | valid time、attributes、source |
| `ConstraintRule` | 规范、政策、SLA 或技术限制 | condition、scope、authority |
| `QualityCriterion` | 检查或验收要求 | measure、threshold、evidence |
| `ExceptionRisk` | 偏离常规路径的异常/风险 | trigger、impact、recovery/escalation |
| `Outcome` | episode 或场景的结果 | success/failure/partial、effect |

`Artifact` 是 `WorkObject` 的可交付子类或角色，具体实现时可用类型而非继承，避免 ontology 过重。

## 5. 关系与限定条件

```text
instance_of
part_of
triggered_by
directly_follows
eventually_follows
precedes
consumes
produces
transforms
uses
performed_by
participated_by
hands_off_to
checks
governed_by
branches_on
retries
escalates_to
blocks
resolves
changes_state
realizes_task
requires_knowledge_skill
demonstrates_capability
```

关系必须允许 qualifiers：

- `directly_follows` 要注明从哪个工作对象/观察视角成立；
- `hands_off_to` 要注明交付物、责任变化和接收标准；
- `changes_state` 要注明 before/after；
- `performed_by` 要区分执行、审批、协作和知会；
- `causes/enables` 只有存在明确证据或被标记为推断时才使用，不能把时间先后自动解释为因果。

首版内部协议优先保留 partial order、对象关联和状态变化。BPMN 风格的顺序流、泳道和网关是投影视图，不是唯一存储格式。

## 6. 与岗位语义图谱的桥接

```text
WorkScenarioTemplate ──realizes──> TypicalTask
WorkEvent ──instance_of/realizes──> TaskStep or TypicalTask
WorkEvent ──requires──> KnowledgeSkill
WorkEvent ──demonstrates──> CapabilityUnit
Artifact ──evidence_of──> TaskDeliverable
QualityCriterion ──operationalizes──> CompletionCriterion
ExceptionRisk ──challenges──> Capability
Actor ──maps_to──> Role / AdjacentRole
ToolSystem ──used_in──> Task
```

桥接边仍是有来源、有认识状态的 claim。实际 workspace 中一次使用某工具，不足以证明整个市场岗位都要求该工具。

## 7. 岗位工作的周期如何建模

不存在适用于所有岗位的唯一线性周期。建议以一个通用认知骨架帮助抽取，再用不同场景族表达差异：

```text
触发/受理
   ↓
理解情境与界定范围
   ↓
计划、准备资源与分工
   ↓
执行/转换工作对象 ─────┐
   ↓                    │ 返工/重试
协作、交接与依赖处理     │
   ↓                    │
验证、评审与决策 ───────┘
   ↓
交付、发布或关闭
   ↓
运行、监控与响应（如适用）
   ↓
复盘、改进与知识沉淀
```

它只是一组常见功能，不是强制每个场景都具备全部步骤。具体岗位由多种场景组合：

### 7.1 项目/交付型

需求进入 → 方案与计划 → 构建 → 集成 → 验收 → 发布 → 复盘。

### 7.2 持续运营型

对象/指标持续到达 → 处理 → 监控 → 调整 → 周期报告与改进。结束边界可能由周期而不是单个交付定义。

### 7.3 事件/异常型

告警或异常 → 分诊 → 止损 → 定位 → 修复 → 验证 → 恢复 → 复盘。需要明确升级、回滚和未解决状态。

### 7.4 治理/评审型

提交物进入 → 合规/质量检查 → 反馈或决策 → 修订 → 批准/拒绝 → 留痕。

### 7.5 学习/改进型

发现缺口 → 研究/实验 → 形成新方法 → 小范围验证 → 标准化 → 扩散。

一个岗位不是“一条大流程”，而是这些 scenario template 的组合；同一任务也可以出现在多个场景中。

## 8. 从不同来源生成

### 8.1 JD、标准和叙述材料

抽取出的通常是规范性或概括性模板：职责、交付物、协作对象和质量要求。它们缺少真实时间顺序，不能伪装为 event log。

路径：

```text
SourceSegment
  → event/object/artifact/actor mentions
  → local process propositions
  → canonicalization
  → documented_norm / inferred_pattern ScenarioTemplate
```

### 8.2 真实工作区

代码提交、Issue、工单、文档版本、构建、评审、聊天或日历只反映工作的一部分。先将其统一成 object-centric event observations：

```text
event_id, event_type, timestamp
object_refs[]
actor_ref?
artifact_refs[]
system_ref
attributes
source_ref
```

同一个事件可关联多个对象，例如一次发布同时关联需求、代码版本、测试报告和部署环境；不能强迫每个事件只属于一个 case。

### 8.3 人工复盘

用户可以通过对话补充“为什么这样做”“当时有哪些选择”“哪里返工”。复盘是来源，不自动高于系统记录；它适合补足意图、决策和隐性协作。

### 8.4 模板归纳

从多个 episode 归纳模板时：

1. 按目标、触发和核心工作对象候选分组；
2. 对事件类型、交付物和角色做 canonicalization；
3. 识别稳定 partial order、常见并行和可选分支；
4. 分离主路径、变体、异常和反例；
5. 记录支持 episode、覆盖范围和版本时间；
6. 把无法验证的因果关系标为推断或研究问题。

## 9. 用事理图谱检查岗位快照健康度

事理图谱不直接改写岗位事实，而是产生可追踪 Issue：

| 检查 | 可能发现的问题 |
|---|---|
| Task → Scenario coverage | 快照任务没有任何场景或 episode 支持，可能是空泛/过时/证据不足 |
| Scenario → Task coverage | 真实工作反复出现但快照没有任务，可能是隐藏职责 |
| Event → KS usage | 知识技能节点从未服务任何真实步骤，可能孤立或粒度不当 |
| Deliverable alignment | 图谱任务的交付物与工作区实际产物不一致 |
| Handoff analysis | 快照忽略协作、审批、对接和相邻岗位边界 |
| Variant/exception coverage | 图谱只描述理想主流程，没有返工、回滚、升级和异常恢复 |
| Role boundary leakage | 大量事件实际由相邻岗位执行，核心岗位边界可能漂移 |
| Parallelism mismatch | 快照或生成文本暗示线性流程，但实际 episode 存在并行与多对象同步 |
| JD—workspace tension | 招聘表述与真实工作负载不同，应单列张力而非互相覆盖 |
| Capability evidence | 高频、关键步骤没有对应能力单元，或能力从未在事件中体现 |

Issue 的修复路径可以是 `automatic | research | user | organization_specific`。企业特有流程默认不能自动上升为公开岗位共性。

## 10. 存储与投影建议

首期不要把高频 event log 全塞进 `snapshot.yaml`，也不要假设图数据库是唯一存储。

建议：

```text
work-process/
  manifest.yaml
  episodes.jsonl              真实/记录 episode 元数据
  events.parquet|jsonl        可追加的对象中心事件
  objects.jsonl
  state-snapshots.jsonl
  scenario-templates.yaml     归纳模板
  process-claims.jsonl        有来源的关系/状态命题
  semantic-bridges.jsonl      到岗位语义图谱的桥接边
  views/
    scenario-flow.json
    handoff-map.json
    object-lifecycle.json
    task-evidence.json
```

开发期以关系表/JSONL/Parquet 保存追加事件，以 materialized graph 生成交互视图。是否引入图数据库应由查询和规模基准决定。

隐私要求：

- 对人、客户、仓库、项目和业务对象使用作用域内 pseudonymous ID；
- 原始内容与可发布模板物理分离；
- 对话引用默认展示相对标签，不暴露本地路径或组织秘密；
- 从私域归纳为岗位共性必须经过来源身份与 claim-use 检查。

## 11. 前端展示

从图谱节点卡或顶部视图切换进入：

- `场景地图`：场景卡按任务/目标聚类；
- `工作流`：事件、网关、交付物和异常路径；
- `交接地图`：岗位/团队与交付物的 handoff；
- `对象生命周期`：一个需求、工单、模型或报告如何变化；
- `真实 episode`：按时间回放一次工作，但受隐私权限约束；
- `快照对照`：语义图谱声称的任务/能力与实际事件覆盖差异。

默认先显示场景模板和关键交付物，不把全部事件堆到一张力导向图里。用户点击场景后再钻入 episode 或对象视角。

## 12. 研究与实验计划

### 12.1 样本

选择 3—5 个结构不同的工作场景：

- 软件/Agent 功能交付；
- 线上故障或质量异常；
- 需求评审与方案决策；
- 版本发布；
- 周期性数据/运营分析。

每个场景同时准备：叙述材料、实际工作痕迹、人工复盘和岗位语义图谱对应任务。

### 12.2 比较路径

1. 仅大模型从叙述生成流程；
2. 仅从 event log 发现 directly-follows；
3. 对象中心事件 + 模板归纳；
4. 对象中心事件 + 人工复盘 + 语义图谱桥接。

### 12.3 指标

- event/object/artifact/actor extraction precision/recall；
- temporal/partial-order accuracy；
- handoff、decision、exception recall；
- episode-to-template alignment；
- task/KS bridge precision；
- 对隐藏职责和错误任务的发现率；
- 错误因果边率；
- 人类能否用该视图复述工作目标、关键路径、交付物和风险；
- 构建延迟、存储规模和增量更新时间。

## 13. 研究依据

- OCEL 2.0 允许事件与对象多对多关联、带限定词的对象关系和随时间变化的对象属性，适合作为真实工作区事件的基础表达：[OCEL 2.0 Specification](https://arxiv.org/abs/2403.01975)。
- Event Knowledge Graph 将 Event、Entity、Log、Class 以及关联、直接跟随和对象关系放入图模型；`directly-follows` 依赖对象视角，说明同一事件流不能只按单一 case 展开：[Multi-Dimensional Event Data in Graph Databases](https://link.springer.com/article/10.1007/s13740-021-00122-1)。
- 对象中心过程挖掘官方说明指出，传统单 case 事件日志难以表达事件与多个对象的关系：[Process Mining — Event Data](https://processmining.org/event-data.html)。
- 将 OCEL 2.0 转为时间事件知识图谱的研究引入对象快照，支持 before/after 状态与时间查询：[Temporal Event Knowledge Graphs](https://arxiv.org/abs/2406.07596)。
- BPMN 适合作为活动、事件、网关、泳道、消息、数据和异常的标准化展示/交换参考，但本项目不把 BPMN XML 当唯一事实源：[OMG BPMN Specification](https://www.omg.org/spec/BPMN)。
- O*NET 将任务与不同粒度工作活动分层并建立映射，支持岗位语义任务与场景/活动之间需要桥接而非混为同一实体：[O*NET Content Model](https://www.onetcenter.org/content.html)。
- ILO 的职业标准方法从岗位定义、关键任务/功能/技能群到学习成果并强调专家验证，支持把实际工作过程与教学结构连接，但避免只按一次工作实例定义课程：[ILO Occupational Profiles and Curricula](https://www.ilo.org/topics/apprenticeships/publications-and-tools/digital-toolkit-quality-apprenticeships/programme-and-project-level/developing-quality-apprenticeship-programmes/developing-occupational-profiles-and-curricula-based-skills-needs/steps-and-tips-developing-occupational-profiles-and-curricula-based-skills)。
- ProPara 通过跟踪程序步骤中的实体状态变化来理解过程，说明步骤文本中的关键效果往往隐含，需要显式记录状态变化及不确定性：[ProPara, NAACL 2018](https://aclanthology.org/N18-1144/)。

这些来源共同支持“对象中心事件 + 状态 + 模板 + 语义桥接”的方向；它们没有直接给出适用于岗位教育场景的完整 schema，因此 W0 小样本验证不可省略。

## 14. 当前决策

1. 岗位事理图谱是独立但可桥接的层，不是岗位雷达的新实体维度；
2. 真实 episode 与归纳 template 分离；
3. 事件与多个工作对象多对多关联；
4. 流程以 partial order、分支、并行、循环和异常表达，不强制线性；
5. 时间先后不自动等于因果；
6. 先用事理图谱产生健康审计与研究主题，不直接覆盖岗位快照；
7. W 研究支线与冷启动 M3 后并行，不阻塞首版语义图谱。
