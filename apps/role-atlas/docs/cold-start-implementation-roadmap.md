# 冷启动能力实施路线 v0.4

状态：`kernel-first core vertical slice implemented; durable cross-isolate runner pending`\
目标：在不破坏当前“大模型应用工程师”静态岗位包和对话闭环的前提下，逐步加入真实多项目冷启动。

## 1. 实施原则

1. 先固定领域协议，再接真实模型与联网工具；
2. UI fixture 与真实执行器共享 Build Event Protocol，不维护两套展示逻辑；
3. 当前静态岗位包继续可用，迁移期间不改写其事实；
4. 每个里程碑都有可独立演示的用户结果；
5. 真实并行必须有预算、限流、幂等和恢复，不用动画伪装；
6. 先把任务层做准，再扩展能力和知识技能层；
7. 候选图谱、版本和发布包必须分离；
8. 抽取提及和关系命题可以并行，规范实体与物化边必须经过全局归并；
9. 岗位语义图谱与岗位事理图谱共享证据但分层建模；二者都是完整岗位包的正式组件，发布前必须共同经过校验。

## 2. 推荐模块边界

```text
app/
  projects/new/                    新项目对话主导的混合交互入口
  projects/[projectId]/            项目工作台
  api/projects/                    项目与 ProjectBrief
  api/build-runs/                  运行命令、事件与工作图谱
  api/workspaces/                  工作区登记、扫描和上传
  api/versions/                    版本、Diff、Tag 与发布

lib/
  projects/                        Project / Brief 领域服务
  build/
    protocol.ts                    BuildEvent Zod schema
    state.ts                       BuildRun 状态机
    reducer.ts                     事件物化与恢复
    runner.ts                      DurableBuildRunner 接口
    graph.ts                       LangGraph 顶层阶段图
    scheduler.ts                   预算、优先级和并发限制
  sources/                         来源发现、摄取、分段和身份
  workspaces/                      工作区 manifest 与分类扫描
  candidates/
    types.ts                       Mention / Proposition / Candidate / Relation
    normalize.ts                   术语规范化与维度路由
    blocking.ts                    词法、别名、向量与结构候选召回
    matcher.ts                     duplicate/contains/adjacent/different 裁决
    pools.ts                       分维度候选池
    cluster.ts                     约束增量聚类与全局归并
    validators.ts                  语义判定测试
  relations/
    propositions.ts                局部关系命题
    materializer.ts                端点重写、聚合与边校验
  working-graph/                   Materializer 与 Graph Patch
  work-process/                    事理候选、场景森林、任务桥接与过程校验
  versions/                        Version / Branch / Tag / Diff
  package-compiler/                Static Role Package 编译与校验

db/
  schema.ts                        领域表
  migrations/

tests/
  build-protocol/
  orchestration/
  clustering/
  recovery/
  package-compiler/
  fixtures/build-runs/
```

当前 `lib/agent/*` 保持为“读取已发布岗位包并回答”的对话 Agent。冷启动编排放入 `lib/build/*`，不要让写入型构建逻辑进入只读岗位工具运行时。

## 3. M0：协议与持久化骨架

### 交付

- Project、ProjectBrief、Workspace、BuildRun、BuildWorkItem；
- SourceAsset、SourceSegment；
- ConceptMention、RelationProposition、CandidateObject、CandidateRelation、SemanticDecision；
- ProjectVersion、Branch、Tag、Release；
- BuildEvent Zod schema；
- BuildRun 状态机；
- Working Graph Snapshot 与 Graph Patch schema；
- 数据库 migration；
- ID、幂等和错误码规范。

### 验收

- 所有领域对象可以创建、读取和序列化；
- 重复命令不会产生重复 Project、WorkItem 或 Event；
- 非法状态迁移被拒绝；
- `seq` 在同一 run 内连续且唯一；
- Graph Patch 冲突能被检测；
- 数据库中没有 API Key 和原始 provider header。

## 4. M1：对话主导的混合交互新建项目

### 交付

- “新建岗位项目”变为对话主导的混合交互入口；
- 极简岗位意图输入；
- 可选工作区和资料上传入口；
- Agent 生成 RoleTargetHypothesis 与 ProjectBrief；
- 高价值问题判定；
- 选项卡、短字段、资料选择器、扫描预览、跳过和按推荐继续；
- 项目创建后立即出现在左侧；
- 项目空态、澄清态、可启动状态；
- 多项目和多会话基本路由。

### 验收场景

1. 输入“大模型应用工程师”时，无需追问即可形成可用 Brief；
2. 输入“AI 工程师”时，能解释为什么需要区分应用交付与模型训练；
3. 输入“我想做能开发智能体的工作”时，能提出岗位假设而不是要求用户填写岗位分类；
4. 用户跳过可选问题后，系统记录默认假设并继续；
5. 刷新页面后项目、Brief 和对话仍然存在。

## 5. M2：构建事件与生长界面

### 交付

- Build Event append-only 存储；
- 实时订阅和 `afterSeq` 补发；
- Build Event 前端 reducer；
- Build Mode；
- 并行 Lane 运行卡；
- Graph Patch reducer；
- 候选、稳定、注意和已发布视觉状态；
- 暂停、继续、取消；
- 断线重连和运行回放；
- 一套完整、可重放的真实协议 fixture。

fixture 只替代执行器，不伪造另一套 UI。后续真实运行产生相同事件即可接入。

### 验收

- 刷新后从最新 Working Graph Snapshot 和 `lastEventSeq` 恢复；
- 重复事件不会重复添加节点；
- seq 缺口触发重新同步；
- 原子 merge patch 不产生悬挂边；
- 对话增长不改变图谱区域高度；
- 54+ 节点持续更新时交互仍可用；
- reduced-motion 下不依赖动画传达状态。

## 6. M3：来源与工作区基础设施

### 交付

- 公开来源、职业标准、JD 市场和用户工作区的来源身份；
- 文件 manifest、类型识别、hash 和重复检测；
- 内容解析、稳定分段和 SourceSegment；
- 面向岗位图谱的 ConceptMention/RelationProposition 抽取接口；
- 面向事理图谱的工作事件、工作对象、交付物与交接观察接口；候选抽取可降级，但完整组合包发布必须经过过程校验；
- 私域/公开来源隔离；
- 来源状态、时间状态和 claim-use；
- 失败记录，不静默补写；
- 来源活动实时事件；
- 来源预算和 per-host 限流。

### 执行位置

浏览器选择本地文件并不等于服务器可以长期访问该目录。首期明确支持两种模式：

1. `upload_set`：用户确认后上传项目所需文件，后台运行可以继续；
2. `linked_local_workspace`：由本地/桌面 Runner 读取，离线时相应 Lane 暂停。

不能仅保存浏览器本地绝对路径并假设后台可以继续访问。

### 凭据

当前模型 API Key 位于 `sessionStorage`。这意味着标签页关闭后，后台不能继续发起新的模型请求。首期有三个可选部署策略：

- 演示模式：要求标签页保持打开，凭据不持久化；
- 系统模型模式：服务器使用项目统一配置的模型密钥；
- 用户密钥后台模式：单独设计加密凭据库，用户明确授权，只在运行时解析 `credentialRef`。

无论选择哪一种，BuildEvent、BuildRun 和 LangGraph State 都不得存储原始密钥。

### 验收

- 同一文件重复上传只产生一个内容实体；
- 私域文件不会显示本地绝对路径；
- 来源正文与发布包元数据分离；
- 单一来源失败不终止其他研究 Lane；
- 用户取消后停止继续抓取和模型调用。

## 7. M4：真实冷启动——岗位边界与任务层

### 交付

- LangGraph 顶层阶段图；
- DurableBuildRunner 第一种实现；
- 意图规范化与 RoleTargetHypothesis 修订；
- 多来源并行研究；
- 来源分片联合抽取任务提及与局部关系命题；
- 任务最低信息检查；
- 分维度规范化、候选阻塞和 Top-K 召回；
- duplicate/contains/adjacent/different/uncertain 语义裁决；
- Lane 内局部聚类；
- 跨 Lane 全局任务归并；
- 关系命题端点重写与任务层边物化；
- 岗位边界第二、三次修订；
- 岗位、产业/岗位群/相邻岗位和任务层实时生长；
- 真实工具和模型 reasoning/output 事件。

### 验收数据集

至少覆盖：

- 明确岗位名；
- 模糊岗位名；
- 岗位群输入；
- 相邻岗位高混淆输入；
- 只有公开研究；
- 只有用户资料；
- 公开资料与真实工作区冲突；
- 来源稀少；
- 部分来源失败；
- 运行中断后恢复。

### 验收指标

- 任务候选均有交付物和完成标准；
- 明显同义任务被归并；
- 越界任务进入相邻岗位或被拒绝；
- 边界修订有输入引用和理由；
- 用户不需要逐个批准节点。

## 8. M5：能力、能力单元与知识技能

### 交付

- task barrier；
- 跨任务能力归纳；
- 能力“情境—行为—标准”验证；
- 能力单元可观察性验证；
- 按任务并行提取知识技能；
- 知识技能提及的跨任务约束聚类；
- 任务—知识技能关系命题聚合与多对多边物化；
- 知识技能课程化/项目化/测评测试；
- 前置关系无环检查；
- 全维度聚类和污染检查；
- 任务—能力与学习路径投影；
- 节点简介质量审计。

### 验收

- 不存在按每个任务复制的一组近义能力；
- 工具、框架和流程步骤不直接冒充抽象能力；
- 每个知识技能至少能说明学习成果、评价方式或实践产物；
- 重要知识技能绑定至少一个任务；
- 同维度节点有明确类别感和可比较粒度。

## 8.1 M5P 核心并行支线：岗位事理图谱

该支线与 M3 后并行启动。模型分支失败不应使其他 Lane 丢失进度，但完整组合包发布必须具有可检查的事理组件、认识状态和任务—场景覆盖报告。

### W0：协议与小样本

- 定义 `WorkEpisode`、`WorkScenarioTemplate`、事件、对象、状态、交付物、Actor、系统、决策、异常和交接；
- 选择 3—5 种岗位工作场景，人工建立金标准；
- 对照 OCEL 2.0、事件知识图谱和 BPMN 投影验证表达能力。

### W1：双通道抽取

- 从 JD、规范和叙述文档抽取规范性/描述性场景模板；
- 从真实工作区记录抽取有时间戳的工作 episode；
- 保留“模板推断”与“真实观察”的认识状态差异。

### W2：交叉健康分析

- 用事件、交付物和交接反查任务覆盖、隐藏职责、孤立知识技能和角色边界泄漏；
- 将结论写为审计 Issue 或研究主题，不直接覆写岗位事实；
- 评估事理视图是否值得进入 Static Role Package 的后续协议版本。

## 9. M6：审计、版本与发布

### 交付

- 结构、语义、证据和时间审计；
- 事理图谱交叉检查，包括任务—场景—事件—交付物覆盖、隐藏职责和岗位边界泄漏；
- 两轮有界自动修复；
- known gap 和 research question；
- ProjectVersion；
- 语义 Diff；
- Tag；
- Package Compiler；
- Static Role Package Validator；
- 发布与当前版本指针；
- 已发布岗位包接回现有八个只读岗位工具和对话 Agent。

### 验收

- 发布失败不移动当前版本；
- 旧包不被原地改写；
- 同一 ProjectVersion 重复编译产生相同核心 hash；
- 包含 manifest、snapshot、sources、graph、views、object index、retrieval 和 validation report；
- 节点引用固定 package/version/snapshot；
- 新旧版本可以生成语义 Diff；
- Tag 与版本在数据和 UI 上明确分开。

## 10. M7：用户通过对话修订图谱

后续里程碑，不阻塞首个冷启动闭环：

- 引用节点表达质疑；
- Agent 生成 change proposal；
- 风险发现与结构扫描 Skill 复用候选沙箱；
- 基于版本创建 repair run；
- 修改后产生新版本和 Diff；
- 不允许对已发布包进行无历史编辑。

## 11. 首个端到端演示脚本

```text
1. 用户点击“新建岗位项目”。
2. 输入“我想了解开发智能体相关的岗位”，选择一个混合资料工作区。
3. Agent 识别模糊性，提出一个影响任务边界的问题。
4. 用户选择偏业务应用交付。
5. 项目立即出现在左侧；运行计划和 5 个并行 Lane 出现。
6. 公开市场、职业标准和工作区来源开始产生真实活动。
7. 中心岗位节点出现，边界假设从 r1 修订到 r2。
8. 多个任务候选并行出现，近义节点可视化归并。
9. 任务层稳定后，能力与知识技能分支并行生长；重复知识技能提及在全局层归并，关系随后物化。
10. 审计发现一个维度污染和一个低证据节点，自动修复前者，保留后者为研究问题。
11. 系统创建“建立首个岗位图谱”版本。
12. 用户查看 Diff，创建“首个可用版”Tag 并发布静态岗位包。
13. 新对话固定该岗位包，用户拖入任务或知识技能节点继续学习。
```

## 12. 开发 Gate

进入下一里程碑前检查：

### M0 → M1

- 状态机、事件 schema 和 ID 策略稳定；
- 项目与现有静态包概念不冲突。

### M1 → M2

- 澄清问题确实改变研究范围；
- 不依赖长表单。

### M2 → M3

- 断线、重复事件、乱序 Lane 和 patch 冲突已验证；
- UI 可以在真实事件速率下工作。

### M3 → M4

- 来源身份、隐私和失败语义稳定；
- 提及与关系命题可以回溯到稳定 SourceSegment；
- 执行凭据策略已选择。

### M4 → M5

- 任务层质量达到基线；
- 候选阻塞召回率、错误合并率和未决比例达到实验基线；
- 不通过增加更多模型调用掩盖边界或聚类缺陷。

### M5 → M6

- 全维度语义纪律可以自动检测；
- 工作图谱能确定性编译。

## 13. 下一阶段基础设施决策

不是产品语义问题，而是部署问题：

1. 首个真实冷启动是否要求浏览器标签页保持打开；
2. 比赛演示使用用户 MiMo/DeepSeek Key，还是部署统一服务端 Key；
3. 工作区首期采用上传集合，还是同时开发本地桌面 Runner；
4. Durable Runner 首个实现采用 Cloudflare Workflows，还是先做本地 Node/Postgres。

当前浏览器内纵向闭环已经实现，以上决策决定它如何升级为可跨进程恢复、可摄取真实工作区并可正式发布的生产系统。
