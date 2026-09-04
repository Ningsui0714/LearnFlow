# Role Atlas 智能体与环境设计

状态：`proposal`\
日期：2026-08-26\
研究依据：《AI Agents in Depth（中文版）》第 1 章逐项对照，以及由差距触发的第 2、3、4、7、9 章定向阅读

## 0. 结论先行

Role Atlas 不需要把当前主问答改造成可以自由联网、写文件或自动修改岗位包的通用 Agent。它需要的是三个边界清楚、共享同一岗位包协议的运行环境：

1. **岗位理解环境**：固定一个不可变 Role Package，只允许有界读取、解释、比较和证据追问；
2. **岗位研究环境**：冷启动、迭代、节点深化和真实工作区接入在候选区运行，只有经过验证和人工审视才能形成新版本；
3. **岗位评测环境**：固定快照、问题、初始状态、允许动作和判定标准，评价“模型 + Harness + 岗位包环境”，并可回放完整运行轨迹。

当前主问答的准确定位不是“自主 Agent”，而是：

> **证据约束的岗位理解工作流，带有确定性路由和有限工具读取。**

这个定位没有问题。问题在于当前流程只有“规划—读取—生成”，尚未完整实现 Harness 所需的“约束—验证—纠正”，上下文也没有保留标准消息与工具结果结构。下一版应升级为：

> **混合规划、有界观察、覆盖检查、独立答案验证、一次受控纠正的岗位智能体。**

本设计不改变 Role Package 的 `evidence / semantic / process` 三空间协议，不引入第二套知识架构。

## 1. 阅读方法与使用边界

本次不是按照书的目录逐章照抄方案，而是采用以下顺序：

1. 完整阅读第 1 章，提取 Agent、Environment、Context、Tools、Harness、Loop、Guardrail 和 Evaluation 的对照项；
2. 对照 Role Atlas 的文档、运行时代码、事件协议、持久化和测试；
3. 先形成项目差距假设；
4. 只针对实际差距回看对应章节；
5. 用现有产品目标和协议筛选建议，而不是把书中示例当成产品指令。

书中内容只作为方法论和技术论据。最终设计仍以 Role Atlas 已批准的岗位包协议、黄金岗位包目标和产品边界为准。

## 2. 第 1 章逐项对照

| 第 1 章对照项 | 当前实现 | 判断 | 设计结论 |
|---|---|---|---|
| Agent = 模型 + 上下文 + 工具 | 有模型、岗位包上下文和六个读取工具 | 基本成立，但模型只负责最终综合，不参与工具选择 | 对外可以称岗位智能体；工程上应标明它是受控工作流 |
| Environment 位于 Agent 外部 | 快照、会话、选中节点、数据库和运行配置共同构成环境 | 概念存在，但没有显式环境契约 | 新增 `RoleAgentEnvironmentState`，不新增知识架构 |
| Observation / Action 边界 | 六个工具提供观察；主问答无写操作 | 只读边界设计正确 | 明确动作空间只有读取、回答、请求澄清或建议启动 Skill |
| Context 五部分 | 系统提示、历史、引用表、工具上下文、当前问题被拼进两条消息 | 信息存在，但角色和来源结构被压平 | 改为稳定前缀、结构化历史、环境状态、工具结果和引用表 |
| 工具是 Agent 的 ACI | 六个工具相对正交、有限、带统一信封 | 是当前架构最强的部分 | 保留六工具边界，补齐 schema、适用/不适用条件和结果预算 |
| ReAct / 反馈循环 | 固定执行一次计划；零引用时补一次检索 | 不是完整反馈循环 | 不做无限 ReAct；只增加最多一次“覆盖不足→补充观察” |
| Harness = 管理上下文、工具、约束、验证、纠正 | 上下文、工具和部分约束较强 | 生成答案后没有独立验证和纠正 | 增加模型外验证器和一次修复，失败则保守降级 |
| 工作流与自主 Agent 的选择 | 主问答固定图；长任务是独立 Skill | 选择正确 | 保持“双层 Agent”，不把研究写入能力塞进问答循环 |
| 三层护栏 | 快照固定、工具白名单、参数限制、不可变版本较强 | 输入和数据层较强，输出层偏弱 | 引用、状态措辞、越界事实必须由程序验证，不只靠 Prompt |
| 长任务持久运行 | 长 Skill 有追加日志、租约、检查点、提交屏障 | 与书中长任务思想一致，且实现较成熟 | 继续增强阶段状态和人工审视，不更换运行模型 |
| 轨迹可观察、可评测 | 浏览器能看到事件；问答最终只保存折叠消息 | 可看但不可完整回放和归因 | 为问答补充独立 run/event 日志，保存可审计轨迹而非私密思维链 |
| 渐进披露、追加式、最小 Diff、回滚 | Skill 目录、事件日志、不可变版本和语义 Diff 已具备 | 与方法论高度一致 | 将这些原则扩展到 Prompt、Harness 和评测资产版本化 |

## 3. 当前实现的明确优点

以下设计应保留，不应因为“做 Agent”而推翻：

### 3.1 一个岗位包、三个认识空间

`evidence / semantic / process` 已经分别回答“依据是什么”“岗位包含什么”“工作如何发生”。主问答和长任务都应继续围绕同一包身份工作，不能另建一套 Agent 专属知识库。

### 3.2 主问答只读，研究写入另走 Skill

普通问答不联网、不修改快照，冷启动、迭代、深化和工作区接入是显式长任务。这一边界能避免用户只是提问时系统悄悄改变岗位认识。

### 3.3 固定快照和统一引用

`packageId + packageVersion + snapshotId` 使回答、图谱和证据追问可复现。节点引用不匹配当前快照时 fail closed，是环境真实性的重要基础。

### 3.4 六个岗位感知工具

精确读取、知识检索、图查询、事理追踪、证据检查和包审计覆盖了主要观察需求。工具数量小、职责相对分离，也符合渐进披露原则。

### 3.5 长任务日志与不可变发布

追加事件、阶段检查点、执行租约、提交屏障和不可变 ProjectVersion 已经构成可靠的长任务 Harness。新的设计应复用它，而不是再造一套任务系统。

## 4. 当前最严重的五个缺口

### 4.1 环境没有成为显式协议

当前环境信息分散在 API 请求、`SnapshotRoleRuntime`、会话表、选中节点和供应商配置中。系统虽然能运行，但很难回答：模型本轮到底看到了哪个快照、哪些节点、哪些环境约束、还剩多少调用预算、哪些证据空间尚未覆盖。

影响：难以复现、难以评测、难以在运行中正确纠偏。

### 4.2 上下文被压成“system + user”两条字符串

历史对话被拼成文本，工具结果也只是拼接到用户消息中；模型看不到标准的 `assistant / tool` 轨迹。API 最多读取 20 条历史，而提示构造只保留最后 6 条，且没有显式说明压缩了什么。

影响：来源角色混淆、工具结果难以对应调用、长对话决策容易丢失、上下文变更无法精确评估。

### 4.3 规划与反馈都过于单次化

规划器是关键词正则，所有工具一次并行执行。只有完全没有引用时才补一次搜索。它无法表达“先检索找到任务 ID，再读取关系和证据”这类依赖，也不会因为证据类型单一、事理缺失或候选状态过多而重新观察。

影响：简单问题稳定，复杂比较、证据追问和跨空间问题容易停在不完整上下文上。

### 4.4 答案没有独立验证器

当前测试明确允许模型正文原样输出，即使引用句柄不存在。Prompt 要求逐段引用、候选降格和推断说明，但程序不会核对这些要求。

影响：最关键的事实约束由同一个生成模型自我保证，无法作为黄金岗位包的可靠回答基准。

### 4.5 问答轨迹不可完整回放

事件在浏览器中实时出现，但入库后被折叠为正文、推理文本、活动摘要和引用表。计划参数、工具结果指纹、覆盖判断、上下文选择和验证结果没有形成独立的问答运行日志。

影响：失败时只能看到最终回答，难以确定第一个错误发生在路由、检索、组装还是生成。

## 5. 定向章节对初步结论的修正

### 5.1 第 2 章：上下文工程

书中第 2.2 节说明消息角色和工具结果关联是 Agent 轨迹本身，不只是 API 格式细节。第 2.6 节的状态栏说明，快照、目标、调用次数、剩余预算和覆盖缺口应被提炼成靠近模型当前决策位置的显式状态。第 2.7 节进一步说明压缩应保留决策、约束、失败和引用。

因此，不能只增加更长 Prompt；应建立可审计的上下文组装器，并记录每项内容为什么被纳入或排除。

### 5.2 第 3 章：知识检索

当前 `search_role_knowledge` 是字符、词和精确标签加权，适合稳定 ID、术语和中文短词匹配，但无法稳定覆盖同义问题。第 3.2 节关于稀疏、稠密和混合检索的比较支持一个直接改进：保留精确/稀疏检索，再增加语义召回和结构过滤，最后统一重排。

因此，不应把所有知识转成纯向量库；Role Package 的稳定对象、图关系和证据绑定仍是主索引，向量只是候选召回的一路。

### 5.3 第 4 章：工具

第 4.1 节的五类工具有助于澄清产品边界：六个岗位工具全部是感知工具；主问答没有执行工具；“启动研究 Skill”属于协作/交接，不应伪装为普通感知；长任务完成通知属于事件和用户沟通。

第 4.2 节进一步要求工具说明回答“何时用、何时不用、参数示例、返回什么、代价多少”。当前工具用途只有一句正向描述，应补齐边界和示例。

### 5.4 第 7 章：评估

第 7 章把评测对象定义为模型与 Harness 的组合，并要求同时验证结果与轨迹。对 Role Atlas，最终答案正确不代表过程正确：模型可能碰巧说对，却没有读取证据；也可能读取了正确节点，却在引用和状态表达上出错。

因此，评测至少要分别衡量观察是否充分、工具是否正确、回答是否有据、限制是否诚实，以及相同问题多次运行是否稳定。主指标应偏向业务可靠性的连续通过，而不是“多跑几次总有一次好答案”。

### 5.5 第 9 章：持续进化

第 9 章强调从轨迹学习之前先做评价，并把更新载体分为知识、Prompt/Skill、程序/Harness 和模型参数。对 Role Atlas：

- 新岗位事实进入候选 Role Package；
- 可解释的研究方法进入研究手册或 Skill；
- 可确定验证的引用、权限和版本规则进入程序；
- 不应因为一次失败就改系统 Prompt，更不应让在线问答直接修改正式能力。

因此采用在线执行与离线改进双循环：线上只回答并记录，线下聚合失败、提出最小变更、跑冻结评测、人工批准后发布。

## 6. 总体架构

```text
用户 / 教师 / 企业人员
          │
          ▼
┌──────────────────────────────┐
│ 岗位理解 Harness             │
│ 校验 → 规划 → 观察 → 覆盖检查│
│      → 综合 → 验证 → 纠正    │
└───────────┬──────────────────┘
            │ 只读
            ▼
┌──────────────────────────────┐
│ Role Agent Environment       │
│ 固定 Role Package 快照       │
│ evidence / semantic / process│
│ 六个有界感知工具             │
└──────────────────────────────┘

用户明确启动研究
          │
          ▼
┌──────────────────────────────┐
│ 岗位研究 Harness             │
│ 冷启动 / 迭代 / 深化 / 工作区│
│ 候选区 + 追加日志 + 检查点   │
└───────────┬──────────────────┘
            │ 验证 + 人工审视
            ▼
     新的不可变 Role Package

两类运行轨迹 ──► 冻结评测环境 ──► 最小改进提案
                                  │
                                  └─ 人工批准后发布
```

## 7. 岗位理解环境契约

### 7.1 环境状态

建议新增运行时类型，不改变 Role Package schema：

```ts
type RoleAgentEnvironmentState = {
  runId: string;
  sessionId: string;
  projectId?: string;
  snapshot: {
    packageId: string;
    packageVersion: string;
    snapshotId: string;
    asOf: string;
    status: "candidate" | "ready" | "published";
  };
  selectedReferences: NodeReference[];
  intent: {
    kind: "explain" | "compare" | "process" | "evidence" | "learning" | "audit";
    requiredSpaces: Array<"evidence" | "semantic" | "process">;
  };
  budget: {
    maxRounds: 2;
    maxToolCalls: 6;
    maxContextTokens: number;
  };
  progress: {
    round: number;
    toolCallCounts: Record<string, number>;
    coveredSpaces: string[];
    unresolvedGaps: string[];
  };
  policy: {
    readOnly: true;
    externalResearch: false;
    allowCandidate: boolean;
    requireCitations: true;
  };
};
```

它是 Harness 的运行状态，不进入岗位包，也不是长期用户记忆。

### 7.2 观察空间

环境只向主问答暴露以下观察：

- 当前快照身份、时点、状态和结构健康；
- 精确对象及一跳关系；
- 检索候选及其命中原因；
- 有界图邻域；
- 任务对应的事理场景、事件、分支、返工和交付物；
- 原文片段、来源资格、适用时点和证据绑定；
- 覆盖、不确定性、候选状态、冲突和工具错误。

每次观察都使用统一信封，并额外记录：`query / inputs / resultCount / coverage / warnings / snapshotIdentity / contentHash / elapsedMs`。

### 7.3 动作空间

主问答允许的动作只有：

1. 调用六个感知工具；
2. 在证据不足且会改变结论时提出一个必要问题；
3. 形成有据回答；
4. 建议用户显式启动某个长任务 Skill。

禁止动作：

- 联网搜索；
- 修改岗位包；
- 自动启动冷启动、迭代或工作区接入；
- 调用 shell、代码解释器、文件写入或外部系统；
- 把候选、推断或未来信号写成已接受事实。

## 8. 岗位理解 Harness

### 8.1 推荐循环

```text
1. validate_environment
   固定快照，校验节点引用和请求规模

2. classify_intent
   识别问题类型、所需空间和最低证据要求

3. plan_observations
   确定性规则提供默认计划；模型只能在六工具内补充查询参数

4. execute_observations
   无依赖调用可并行；依赖上一步解析 ID 的调用必须串行

5. evaluate_coverage
   检查 requiredSpaces、引用数、来源状态、冲突和目标对象覆盖

6. repair_observation_once
   仅在可明确修复的缺口上再规划一轮；总轮数不超过 2

7. synthesize_answer
   用结构化上下文形成回答

8. verify_answer
   程序先验引用、状态措辞和越界事实；必要时再用独立 Rubric 评审

9. repair_answer_once_or_fail_safe
   修复一次；仍不通过则输出证据不足或运行失败，不展示未经验证正文
```

这不是开放式无限 ReAct。环境很小、动作固定、风险边界明确，所以有界循环比通用自治更适合。

### 8.2 混合规划器

完全正则路由对可预测问题很快，应保留为默认和降级路径；但应把模型规划限制为一份结构化计划：

```ts
type ObservationPlan = {
  intent: RoleIntent;
  requiredSpaces: RoleSpace[];
  calls: Array<{
    tool: CoreRoleToolName;
    purpose: string;
    args: Record<string, unknown>;
    dependsOn?: number[];
  }>;
  stopWhen: string[];
};
```

Harness 校验工具白名单、参数 schema、调用数和依赖，再决定执行。模型无权增加工具或提升权限。

### 8.3 覆盖控制器

“有引用”不等于“证据够用”。覆盖控制器至少检查：

- 是否覆盖问题要求的 `semantic / process / evidence` 空间；
- 选中节点是否全部读取或明确报告缺失；
- 比较问题的双方是否对称取证；
- 证据追问是否真的调用 `inspect_role_evidence`；
- 事理问题是否读取任务桥接和知识状态；
- 是否只有候选或推断材料；
- 是否出现冲突、过时或来源单一；
- 是否因为 top-k 或上下文预算截断了关键材料。

### 8.4 答案验证器

验证分三层：

1. **确定性验证**：引用句柄存在；逐事实段至少一个引用；节点 ID 和数字出现在观察中；不得引用其他快照；HTML/脚本按前端安全策略处理；
2. **认识状态验证**：候选、推断、未来或证据不足是否使用正确措辞；
3. **质量 Rubric**：是否直接回答、是否混淆任务与事件、是否把岗位能力写成工具清单、是否对教师和学生可理解。

前两层尽量使用程序。只有难以形式化的表达质量才交给独立评审模型。评审模型不能修改引用注册表或发布门槛。

## 9. 上下文设计

### 9.1 不再把全部信息压入一个 user 字符串

建议的逻辑结构：

```text
稳定前缀
├─ system：身份、认识纪律、安全边界、回答协议
└─ tools：六个工具的稳定元数据或规划 schema

动态轨迹
├─ user / assistant：保留真实消息角色
├─ environment_status：固定快照、选中节点、预算、覆盖状态
├─ tool results：与调用一一对应的结构化结果
└─ current user request
```

供应商不支持原生工具消息时，由 provider adapter 映射为带来源标签的结构块，但内部 `ContextItem` 仍保持角色、来源和调用关联，不能先压平再传递。

### 9.2 环境状态栏

每轮规划或生成前追加短状态：

```xml
<role_environment_status>
snapshot: role-package:llm-app-engineer@1.2.0
as_of: 2026-08-19
selected: [task:T-02, capability:C-03]
intent: compare
required_spaces: [semantic, evidence]
covered_spaces: [semantic]
unresolved_gaps: [evidence_for_capability:C-03]
tool_budget: 3/6 used, round 1/2
policy: read_only, no_external_research
</role_environment_status>
```

状态由 Harness 计算，模型只能读取，不能自行改写。

### 9.3 上下文预算与清单

不再用最终 `.slice(0, 36000)` 静默截断。组装器按任务分配预算，并生成 `ContextManifest`：

- 精确选中对象和直接证据优先；
- 问题所需空间优先；
- 关系、事理和审计按需求进入；
- 相同对象去重；
- 大结果保存完整内容哈希，模型只看摘要和必要片段；
- 被排除内容记录原因；
- 决策、约束、失败、冲突和引用不被普通摘要丢弃。

## 10. 工具设计

### 10.1 保留六个核心工具

不建议把六个工具继续拆细，也不建议给主问答增加通用 shell 或代码执行器。每个工具补充以下元数据：

```ts
type RoleToolDefinition = {
  name: CoreRoleToolName;
  kind: "perception";
  whenToUse: string[];
  doNotUseWhen: string[];
  inputSchema: JsonSchema;
  outputSchema: JsonSchema;
  examples: ToolExample[];
  cost: "low" | "medium";
  risk: "read_only";
};
```

### 10.2 必须修正的现有行为

- `trace_work_process.depth` 目前进入返回值但没有真正限制事件范围，应使参数生效或删除参数，不能制造虚假的控制感；
- `search_role_knowledge` 增加精确/稀疏 + 语义召回 + 结构过滤 + 重排，并在结果中说明每项为何命中；
- 图、事理和证据工具应返回明确的截断游标或缺口，不能只给模糊 `partial`；
- `confidence` 不应直接被解释成事实概率。运行时兼容保留数值，同时向回答层提供来源资格、独立性、直接/归纳/推断和适用范围等可解释字段；
- 工具错误继续保留 `whoFixes / retryable / suggestedAction`，并把连续失败次数加入环境状态。

### 10.3 五类工具在 Role Atlas 中的落位

| 工具类型 | Role Atlas 对应设计 |
|---|---|
| 感知 | 主问答六个岗位读取工具 |
| 执行 | 主问答不提供；研究 Skill 的候选写入和版本提交由专用程序执行 |
| 协作 | 请求人工确认、建议启动长 Skill；不自动创建额外 Agent |
| 事件触发 | 长任务完成、租约丢失、等待人工审视、版本形成 |
| 用户沟通 | 流式活动、证据不足说明、审批请求、最终回答 |

## 11. 岗位研究环境

长任务保持现有四个 Skill，不成为主问答的隐式工具。每次研究运行有独立环境状态：

- 基础快照与岗位边界假设；
- 当前研究问题、来源类别计划和预算；
- 已读来源、拒绝来源和拒绝理由；
- Claim、Mention、候选任务和争议；
- TASK BARRIER 状态；
- 当前候选 Diff；
- 协议检查、证据检查和人工待审项；
- 检查点、租约、重试与提交状态。

研究环境的动作分级：

1. **观察**：读取仓库、材料、来源和现有岗位包；
2. **候选加工**：抽取、聚类、归并、建立候选关系；
3. **候选写入**：只写运行候选区；
4. **版本提交**：通过硬不变量和评测后形成新不可变版本；
5. **发布**：岗位边界变化、争议结论和黄金版本必须经过人工审视。

生成者无权修改验证器、冻结评测集、发布门槛或稳定版本备份。

## 12. 运行轨迹与持久化

### 12.1 保存什么

建议为短问答增加 `agent_runs` 和 `agent_events`，或复用一套通用追加日志：

```text
agent_runs
  id, session_id, snapshot_id, harness_version, model_id,
  prompt_version, status, started_at, completed_at,
  verifier_status, privacy_class

agent_events
  run_id, seq, kind, phase, payload_json, content_hash, created_at
```

事件至少包括：环境固定、意图、计划、工具调用、结果摘要和哈希、覆盖判断、上下文清单、生成完成、验证问题、修复和最终状态。

### 12.2 不保存什么

- 不把供应商原始 chain-of-thought 当成评测真值；
- 不默认长期保存敏感工具全文；
- 不把模型自述的“我已经验证”当成验证事件；
- 不把一次运行摘要直接升级为长期 Skill 或系统 Prompt。

现有 `messages.reasoning` 可保留为兼容字段，但应明确保留策略和访问范围。评测主要使用可观察的计划、工具、结果、引用、验证和最终回答。

## 13. 岗位评测环境

### 13.1 冻结任务格式

```ts
type RoleAgentEvalCase = {
  id: string;
  frozenSnapshotId: string;
  initialHistory: AgentMessage[];
  selectedReferences: NodeReference[];
  userRequest: string;
  expected: {
    intent: RoleIntent;
    requiredSpaces: RoleSpace[];
    evidenceTargets?: string[];
    allowedTools: CoreRoleToolName[];
    forbiddenTools?: CoreRoleToolName[];
    answerAssertions: string[];
    requiredLimitations?: string[];
    forbiddenClaims?: string[];
  };
  tags: string[];
};
```

### 13.2 三层评测

1. **岗位包产品评测**：结构、语义、证据、事理和 Agent 问答案例，即黄金岗位包已要求的冻结资产；
2. **主问答 Harness 评测**：检索、调用、覆盖、引用、状态表达、拒答和稳定性；
3. **研究工作流评测**：来源资格、Claim 抽取、任务骨架、跨产物一致性、版本 Diff 和人工审视负担。

### 13.3 指标

结果指标：

- 事实正确性与完整性；
- 引用有效率和事实段引用覆盖；
- 候选/推断/未来信号表达正确率；
- 相邻岗位和语义维度不混淆；
- 无证据时的诚实限制；
- 多次运行连续通过率。

过程指标：

- 意图和所需空间识别正确率；
- 工具选择、参数和依赖顺序正确率；
- 检索 Recall@K、Precision@K、MRR；
- 无效、重复和无收益调用率；
- 首个错误步骤与错误类别；
- 上下文纳入/排除是否符合预算；
- token、延迟、缓存和修复次数。

安全底线：

- 不跨快照引用；
- 不把材料中的指令当系统指令；
- 不隐式联网或写入；
- 不伪造来源、节点、数字或工具执行；
- 不允许验证器和冻结评测被生成流程修改。

## 14. 在线执行与离线改进

```text
在线：回答问题 → 保存可观察轨迹 → 收集用户纠正与验证结果
                                      │
                                      ▼
离线：聚类失败 → 定位首个错误 → 选择更新载体 → 提出最小 Diff
                                      │
                                      ▼
              边界集 + 保留集 + 安全集 + 人工审视
                                      │
                                      ▼
                         新 Harness / Prompt / Skill 版本
```

更新载体的选择规则：

| 发现 | 应进入哪里 |
|---|---|
| 新岗位事实、证据或争议 | 候选 Role Package |
| 可解释的研究判断方法 | 研究手册或按需 Skill |
| 确定性引用、权限、schema、版本约束 | Harness 程序 |
| 表达风格或高维识别能力 | 先评测模型，必要时才考虑后训练 |

每次更新采用最小 Diff，并同时跑触发问题的边界集与原有正常任务的保留集。

## 15. 明确不采用的设计

- 不给主问答增加自由 shell、代码执行、文件写入或外部账号权限；
- 不把主问答改成无限 ReAct；
- 不因为有多种任务就默认引入多 Agent；
- 不使用对话记忆替代固定岗位包；
- 不把所有岗位知识迁移到纯向量数据库；
- 不把原始思维链作为系统计划、事实证据或质量证明；
- 不让在线运行自动修改正式 Prompt、Skill、工具、评测集或岗位包；
- 不为本设计重构 `evidence / semantic / process` 协议。

## 16. 最小实施路径

### P0：先补可靠性闭环

1. 定义 `RoleAgentEnvironmentState`、`ContextItem` 和 `ContextManifest`；
2. Provider adapter 支持结构化消息，不再只接受 `system + user`；
3. 增加确定性答案验证器和一次受控修复；
4. 持久化短问答 run/event 轨迹，不默认持久化原始思维链；
5. 修正 `trace_work_process.depth`；
6. 建立首批冻结问答和轨迹前缀评测。

### P1：增强观察质量

1. 将确定性路由升级为受 schema 约束的混合规划；
2. 增加一次覆盖驱动的补充观察；
3. 将岗位检索升级为稀疏 + 语义 + 结构过滤的混合检索；
4. 为六工具补充使用边界、反例、schema、示例和成本信息；
5. 增加检索和引用覆盖指标。

### P2：建立离线改进基础设施

1. Prompt、Harness、工具定义和评测集独立版本化；
2. 建立消融开关，区分模型问题、检索问题和 Harness 问题；
3. 从失败轨迹生成待审回归案例和最小改进提案；
4. 只有通过边界集、保留集和人工审视的版本才能发布。

## 17. 与当前文件的兼容映射

| 当前文件 | 最小变化 |
|---|---|
| `lib/agent/events.ts` | 增加环境、覆盖缺口、验证和修复事件；事件协议向后兼容升级 |
| `lib/agent/model.ts` | 从两字符串输入升级为 provider-neutral 结构化 messages |
| `lib/agent/grounding.ts` | 演进为上下文组装器和清单生成器 |
| `lib/agent/planner.ts` | 保留确定性默认计划，增加受约束的结构化规划 |
| `lib/agent/graph.ts` | 增加一次覆盖修复、答案验证和保守降级节点 |
| `lib/agent/snapshot-runtime.ts` | 工具 schema、事理深度修复、混合检索、明确截断信息 |
| `app/api/agent/route.ts` | 固定 Harness/Prompt 版本并追加保存运行事件 |
| `db/schema.ts` | 增加短问答 run/event，或抽象通用运行日志 |
| `tests/agent-grounding.test.ts` | 从“原样输出”测试改为引用、状态和降级验证 |
| `evals/role-agent/*`（建议新增） | 冻结问答、轨迹前缀、检索标注、Rubric 和运行报告 |

Role Package、ProjectVersion、Release、Registry 和四个长任务 Skill 的领域身份不需要改变。

## 18. 设计验收标准

本设计进入实现前，应由团队确认以下判断：

1. 主问答是受控岗位理解 Agent，不追求通用自治；
2. 六个主工具保持只读，研究写入继续走显式 Skill；
3. 未通过引用和认识状态验证的正文不能作为正式回答直接展示；
4. 运行轨迹用于复现和评测，但不把原始思维链当成系统真值；
5. 黄金岗位包既是知识产品，也是主问答与研究工作流的冻结环境；
6. Agent 和环境的任何改进都不得绕过现有岗位包版本与发布协议。

## 19. 参考定位

本设计主要使用书中以下章节的概念，不复制其示例实现：

- 第 1 章：Agent、Environment、Context、Tools、Harness、工作流与自主 Agent、护栏、长任务模式；
- 第 2.2、2.6、2.7 节：消息结构、Agent 状态栏、分层上下文压缩；
- 第 3.2、3.3 节：混合检索、结构化知识与 Agentic RAG；
- 第 4.1、4.2、4.6、4.7 节：工具分类、ACI、人工介入、渐进披露；
- 第 7.2—7.5、7.8—7.10 节：结果与过程指标、评测环境、失败归因、轨迹回归、可观察性和消融；
- 第 9.1—9.3 节：先评价再学习、更新载体选择、在线/离线双循环、安全进化。

项目协议依据：

- `README.md`
- `docs/role-agent-vnext.md`
- `docs/composite-snapshot-and-tools.md`
- `docs/versioning-and-publication.md`
- `docs/work-process-event-graph-research.md`
