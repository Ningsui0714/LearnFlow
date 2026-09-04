# 冷启动图谱构建算法研究 v0.1

状态：`proposed`\
范围：岗位语义图谱的并行抽取、实体规范化、关系物化与实验设计\
不包含：岗位事理图谱的完整协议，见 `work-process-event-graph-research.md`

## 1. 决策摘要

首版采用**局部联合抽取、延迟规范化、约束聚类、关系后物化、周期性全局修复**的混合算法。

不是：

- 每个任务分支直接创建正式知识技能节点和边；
- 等所有资料完成后，把全文交给一次大模型统一生成；
- 先丢弃关系上下文，完成实体聚类后再凭空补边；
- 对所有提及做两两大模型比较；
- 把多对多关系误判为重复。

核心流程：

```text
SourceSegment 分片
      ↓ 并行
实体提及 + 局部关系命题联合抽取
      ↓
维度路由与确定性规范化
      ↓
同维度 Blocking / ANN Top-K 候选召回
      ↓
语义配对裁决 + must-link / cannot-link
      ↓
增量约束聚类 ── 周期性全局 reducer 修复
      ↓
Canonical Entity Pool
      ↓
命题端点重写 + 谓词规范化 + 证据聚合
      ↓
多对多关系物化 + 全图审计
```

## 2. 为什么不选择单一算法

### 2.1 按来源或任务并行直接生图

优点：首批结果快、每条关系有局部语境、容易按任务扩展知识技能。

缺点：每个分支会重复发明相同知识技能；同名异义和异名同义混在一起；到达顺序会影响 canonical 名称；边会指向尚未归并的临时节点。

结论：保留它作为“提及和命题抽取器”，取消它直接写正式图谱的权力。

### 2.2 先全局生成每个维度，再生成关系

优点：节点类别感较强，重复较少，容易控制每层数量。

缺点：需要全量上下文或大摘要；第一批图谱出现较慢；先压缩资料会丢失任务—技能关系的原文证据；新来源加入时容易整体重算。

结论：作为全局 reducer 和修复器使用，不作为唯一生成路径。

### 2.3 完全联合抽取实体和关系

优点：共享实体、重叠三元组和局部关系更容易保留。

缺点：开放世界岗位资料中的 schema、粒度和别名并不稳定；联合模型输出的节点仍需跨文档 canonicalization；很难用单次上下文覆盖公开资料和私域工作区。

结论：在单个 SourceSegment 或工作分片内联合抽取，在跨来源层延迟规范化。

### 2.4 完全流水线

优点：各阶段可测、可替换、可恢复，便于使用确定性检查。

缺点：前一阶段的错误会传播；如果实体阶段不保留关系线索，后续无法准确恢复边。

结论：保留流水线的工程边界，但让实体裁决使用关系邻域反馈，并保存原始命题。

## 3. 推荐数据路径

### 3.1 A：来源分片

稳定的 `SourceSegment` 是重跑、证据定位和增量更新的最小单位。分片不能只按 token 截断，应尽量保持一个 JD 条目、流程步骤、段落或表格行的语义完整。

每个分片生成稳定 `content_hash`；同一版本重跑时复用已有抽取结果。

### 3.2 B：局部联合抽取

一个抽取调用同时输出：

- `ConceptMention[]`；
- `RelationProposition[]`；
- 每项对应的 source segment 和文本 span；
- explicit/inferred 认识状态；
- 缺失字段，而不是编造字段。

例如一段资料写“负责搭建 RAG 系统并评估检索质量”，可产生两个任务/技能提及和一条局部命题。此时不决定“RAG 评测指标”是否与别处的“检索质量评估”相同。

### 3.3 C：维度路由与规范化

先执行低成本规则：

- Unicode、空格、大小写、全半角和常见缩写规范化；
- 已注册 alias 命中；
- 维度 schema、domain/range 和禁用泛词检查；
- 将标题、定义、交付物、行为标准、学习成果分别保存，不拼成一个不可解释向量。

维度不确定的提及进入隔离队列，不为了完成率强行分类。

### 3.4 D：候选阻塞

若某维度有 `N` 个提及，全量两两比较需要 `O(N²)` 次配对，尤其不能把这些配对都变成大模型调用。

Blocking 为每个提及只召回少量可能匹配项：

1. 精确 canonical/alias/hash；
2. 字符、词法和领域缩写；
3. 向量 ANN Top-K；
4. 交付物、行为、学习成果等结构字段；
5. 已有关系邻域，如服务相同任务、产出相同交付物；
6. 来源或行业限定只作特征，不作为自动同义依据。

目标比较量约为 `O(N × K)`，其中 `K` 是小型候选集。K 应通过召回实验选择，而不是硬编码为“看起来合适”的数字。

### 3.5 E：配对裁决

裁决输出固定为：

```text
duplicate | contains | adjacent | different | uncertain
```

并返回：

- 字段级理由；
- 支持合并的共同点；
- 阻止合并的区别；
- 使用了哪些来源和关系邻域；
- 可校准置信度。

判定模板按维度不同：

| 维度 | 合并主要依据 | 不能只看 |
|---|---|---|
| 任务 | 触发情境、独立交付物、完成标准、责任边界 | 动词相似 |
| 能力 | 情境、可观察行为、质量标准、跨任务适用性 | 标题或工具名 |
| 能力单元 | 可观察表现及所属能力 | 同一上位能力 |
| 知识技能 | 学习成果、实践对象、评价方式、服务任务 | 关键词重合 |
| 岗位 | 核心责任与任务组合 | 招聘标题 |

### 3.6 F：约束增量聚类

- `duplicate` 高置信结果形成 must-link；
- `different/adjacent` 形成 cannot-link；
- `contains` 不自动当作 duplicate，可形成层级建议或将较窄表达收为情境/别名；
- `uncertain` 保留为未决，不强行归簇；
- 一个 merge 如果违反 cannot-link、维度或专属判定测试，必须拒绝；
- merge/split/rename/retype 全部写 `SemanticDecision`，不物理删除历史。

在线 reducer 让图谱尽快出现；批次 Barrier 后的全局 reducer 检查跨 Lane 重复、簇内不一致和早期误合并。全局 reducer 的输入是候选簇摘要和近邻，不是全部原文。

### 3.7 G：关系命题重写和物化

对每条 `RelationProposition`：

1. 将 subject/object mention 映射到 canonical ID；
2. 若任一端点未决，则命题继续等待；
3. 将谓词映射到注册关系类型；
4. 执行 domain/range 和维度判定；
5. 聚合相同端点、谓词和限定条件的多条证据；
6. 显式事实与模型推断分开计数和显示；
7. 产生或更新一条 `CandidateRelation`；
8. 在同一事务中发送原子 `graph.patch`。

多对多是正常结构：一个任务可以需要多个知识技能，一个知识技能也可以服务多个任务。应去重的是重复命题或同一语义实体，不是合法的共享关系。

### 3.8 H：关系反馈的修复循环

实体规范化与关系物化不是只走一次：

- 两个候选名称相似但关系邻域完全不同，降低合并概率；
- 两个候选名称不同但交付物、服务任务和学习成果高度一致，提高复核优先级；
- merge 造成异常超高出度、跨维度冲突或区别说明自相矛盾时，触发 split review；
- 新来源只重算受影响的提及、近邻簇和关系，不全图重建。

修复循环有上限，无法解决的项进入研究队列。

## 4. 并行、队列与 Barrier

### 4.1 并行单位

- 来源通道；
- 文件、页面或稳定分片；
- 任务分支上的知识技能提及；
- 同维度的 blocking bucket；
- 互不依赖的语义配对；
- 确定性图审计。

### 4.2 必要 Barrier

| Barrier | 允许继续的最低条件 | 目的 |
|---|---|---|
| 岗位边界 | 核心岗位假设可用 | 避免研究两个不同岗位 |
| 任务规范化 | 核心任务簇达到覆盖基线 | 能力必须跨任务归纳 |
| 维度规范化 | 当前批次 canonical map 可用 | 防止边指向临时提及 |
| 关系物化 | 端点和谓词通过约束 | 防止脏边进入可视图 |
| 发布 | 全局审计与证据覆盖通过 | 产生不可变岗位包 |

Barrier 不要求等待全部低价值来源；达到最低覆盖后可先形成一个稳定批次，后续资料以新批次 patch 进入。

### 4.3 背压

每个队列记录 pending/running/succeeded/failed/deferred。Scheduler 同时考虑：

- 供应商并发与速率；
- token、来源和截止时间预算；
- 当前维度的未决比例；
- 候选池拥塞；
- 用户当前关注的层；
- 新调用对覆盖或消歧的预期价值。

当聚类队列积压时，应减慢同维度的新抽取，而不是继续制造临时节点。

## 5. 算法组合实验

至少比较四组：

| 组 | 抽取 | 规范化 | 关系 | 预期用途 |
|---|---|---|---|---|
| A 基线 | 按任务直接生成节点 | 标题向量聚类 | 分支直接生边 | 量化当前最直观方案的重复和污染 |
| B 全局 | 全维度批量生成 | 单次全局归并 | 后生成 | 观察质量上限与首图延迟 |
| C 流水线 | 实体提及先行 | blocking + 配对 + 聚类 | 重新抽取 | 测量关系上下文损失 |
| D 推荐 | 局部提及+命题联合抽取 | 增量约束聚类+全局 reducer | 端点重写后物化 | 平衡速度、证据与一致性 |

可选 E：让关系邻域参与第二轮实体修复，用来测量联合反馈的增益与成本。

## 6. 数据集与金标准

不能只用“大模型应用工程师”一个岗位。最小实验集应包含：

- 标题高度混乱的新兴岗位；
- 任务标准化程度较高的成熟岗位；
- 工具密集、容易把工具当能力的岗位；
- 相邻岗位边界高度重叠的岗位；
- 公开资料与真实工作区存在张力的岗位。

每个岗位人工标注：

- source span 到 mention；
- mention 到 canonical cluster；
- must-link/cannot-link 难例；
- canonical 实体类型和最低字段；
- proposition 到 canonical relation；
- 显式/推断和来源；
- 已知缺口，不把未标注当错误事实。

## 7. 评测指标

### 7.1 抽取与实体规范化

- mention precision/recall；
- blocking recall@K：真匹配是否进入候选集；
- pair classification macro-F1；
- cluster pairwise F1、B-cubed F1；
- false merge rate：优先级高于“少几个重复节点”；
- fragmentation rate；
- unresolved rate；
- dimension contamination rate。

### 7.2 关系与证据

- canonical edge precision/recall/F1；
- endpoint resolution accuracy；
- evidence binding precision；
- many-to-many coverage；
- orphan node rate；
- unsupported edge rate；
- domain/range violation rate。

### 7.3 产品与性能

- time to first role node / first task cluster / first useful layer；
- p50/p95 全流程延迟；
- 模型调用数、token、网络请求和失败重试；
- 每新增一个稳定节点/有证据边的成本；
- merge 后图谱视觉抖动次数；
- 15 秒有效进度窗口覆盖率；
- 用户理解测试：能否区分相邻节点、解释节点为何存在。

## 8. 首版参数原则

以下是实验参数，不是协议常量：

- ANN Top-K 从 5、8、12 三档开始；
- 高置信规则命中可直接 must-link，但仍写决定记录；
- 大模型只裁决阻塞后的难例，不承担全部配对；
- 在线 reducer 小批运行，全局 reducer 在语义 Barrier 和发布前运行；
- 自动 merge 阈值从保守侧起步，宁可短期碎片化，不可大规模误合并；
- 自动修复最多两轮，随后生成研究项。

参数必须按维度校准，不能让任务和知识技能共享同一阈值。

## 9. 研究依据

- EDC 将开放三元组抽取、schema 定义和 canonicalization 拆开，说明开放抽取后的冗余关系需要显式规范化：[Extract, Define, Canonicalize, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.548/)。
- 实体—关系抽取没有永远占优的单一路径；实证比较显示联合方案可能更好，但设计不佳也会落后于流水线：[Pipeline vs. Joint Approaches, AACL 2022](https://aclanthology.org/2022.aacl-short.55/)。
- 简单流水线通过为实体和关系使用不同上下文表示也能取得强结果，且存在以轻微精度代价换取显著速度的近似方法：[A Frustratingly Easy Approach, NAACL 2021](https://aclanthology.org/2021.naacl-main.5/)。
- TPLinker 和 CasRel 证明单阶段/级联联合抽取适合重叠三元组与共享实体，支持在局部分片内保存实体—关系共现：[TPLinker, COLING 2020](https://aclanthology.org/2020.coling-main.138/)、[CasRel, ACL 2020](https://aclanthology.org/2020.acl-main.136/)。
- Ditto 的实体匹配流程使用 blocking 缩小候选配对，再做语义判定，支持本方案避免全量两两大模型比较：[Ditto, VLDB 2020](https://www.vldb.org/pvldb/vol14/p50-li.pdf)。
- 文档级联合研究显示关系与指代信息可以相互帮助，支持把关系邻域用于第二轮实体修复：[Joint Entity and Relation Extraction with Coreference, NAACL 2022](https://aclanthology.org/2022.naacl-main.395/)。
- O*NET 明确维护任务与 Detailed Work Activities 的多对多映射，说明共享关系不是需要被清洗掉的噪声：[O*NET Tasks to DWAs](https://www.onetcenter.org/dictionary/30.3/excel/tasks_to_dwas.html)。

这些论文提供方法依据，不直接证明其原始 benchmark 参数适用于中文岗位资料；最终算法选择以本项目金标准实验为准。

## 10. 当前决策与未决问题

已决：

- 引入 `ConceptMention` 与 `RelationProposition`；
- 正式节点和边延迟物化；
- 分维度队列、局部在线 reducer 与全局 reducer 共存；
- 实体聚类和关系覆盖分开评测；
- 事理图谱另设层与研究支线。

待实验：

- 各维度 blocking 特征与 K；
- 小模型/embedding/主模型在配对裁决中的成本质量边界；
- 关系邻域反馈对 false merge 与 fragmentation 的净影响；
- 在线图谱可见速度与后续 merge 视觉抖动的平衡；
- 工作区资料中流程事件是否应在 M3 同步抽取，或使用独立 Runner。
