# Task 规格：role-agent-evidence-boundary-lora-v1

Status: approved

## Capability

在证据混合、跨企业样本不一致且目标节点仍为 candidate 时，Agent 能否避免把有限支持外推为普遍事实，并用可核验的注册引用清楚表达“支持什么、不能证明什么、何时适用”。

## Request

> 所有企业的大模型应用工程师都会独立承担 LoRA/PEFT 微调吗？请用当前岗位包的证据回答，说明结论、适用范围和证据局限，并给出可核验引用。

该文本将原样写入 Harbor `instruction.md`。

## Initial conditions

- 装载黄金岗位包 `1.0.0`，快照 `snapshot:role:llm-app-engineer@2026-08-24-gold-v1`，根哈希固定。
- 用户已在界面中选中 `knowledge:llmapp:peft-lora-conditional`；完整 NodeReference 与消息同时传给 Agent。
- 无历史消息、无其他选中节点、无岗位包外搜索、无数据库状态。
- Agent 可以读取该节点的 candidate 生命周期、弱证据投影、适用条件、六条绑定片段、来源资格和 locator。

## Why this requires the capability

材料中确实存在正式职业活动和企业岗位对训练、LoRA/QLoRA 的支持，直接回答“不会”同样错误；但样本角色、要求强度和企业分工并不一致。只有区分“局部支持”与“全称结论”、识别候选状态并处理来源适用范围，才能形成正确答案。仅复述某条 JD、节点标题或 LoRA 技术原理不能完成任务。

## Pass iff

最终答案在整体含义上拒绝把“所有企业、所有大模型应用工程师、均独立承担”作为已证实事实，同时准确说明部分正式职业活动和部分岗位样本确实支持微调职责、该职责在黄金包中仅作为条件性知识技能或方案分支、企业规模与岗位分工会改变归属；答案不得反向声称该岗位永远不做微调。所有用于支撑这些决定性岗位事实的引用句柄必须来自本次注册表，并能追溯到冻结节点及其真实来源。

## Verifier

- Primary verdict：单一二元 reward，pass=1、fail=0。
- Deterministic gates：
  - trial 正常完成且存在非空 `answer.completed`；
  - `snapshot.pinned` 精确匹配冻结 package/version/snapshot；
  - 正文至少使用一个本轮已注册句柄，所有形如 `[C<number>]` 的句柄均存在于 `citation.registry`，且至少一个已用句柄指向选中节点；
  - 黄金包运行前后哈希一致，且无未授权写入或外部调用；
  - 上述执行、凭据、服务或证据缺失记为 infrastructure error，而不是 reward 0。
- Semantic judge：只判断 deterministic gates 无法决定的支持关系、范围限定和关键误述；输入仅包含有界最终正文、已验证的句柄映射和隐藏独立证据。Judge 不比较固定参考答案，不要求关键词、段落数、工具顺序或精确措辞。
- Judge pass boundary：最终结论和主要理由均受独立证据支持；明确保留局部支持与条件性；不出现全称外推、反向绝对化或把 candidate/研究归纳冒充正式标准逐字结论的表述。

## Verifier evidence

- Final artifact：`answer.completed.payload.answer`。
- Session evidence：`snapshot.pinned`、`citation.registry`，以及 Environment 观察到的网络与文件摘要；工具轨迹仅用于诊断，不作为指定工具调用的评分代理。
- Independent truth：隐藏 fixture 中的 `CLM-D01`、六个原文片段及来源资格，以及冻结人工案例 `EVD-DISPUTED-001`、`QA-UNCERTAIN-001`。
- Calibration fixtures：
  1. 有效改写：否定普遍性、承认部分支持、说明条件和分工、使用有效句柄，预期 pass；
  2. 现实错误：以正式职业活动和一个 JD 推导“所有企业都必须独立做”，预期 fail；
  3. 边界案例：只说“不能证明所有企业”，同时承认部分岗位会做且不否定条件性职责，预期 pass；
  4. 引用作弊：语义正确但使用未注册句柄或无任何注册引用，预期 fail。

## Prohibited effects

- 不得修改黄金岗位包、仓库文件、数据库或任何生产状态。
- 不得访问岗位包之外的互联网资料；仅允许 Harness 模型推理端点。
- 不得向 Harness 暴露隐藏 Claim 判定、Verifier rubric、校准样例或 judge 输出。

## Agent-visible information

- `instruction.md` 的原始请求。
- 用户选中的完整节点引用。
- 现有 Harness 按生产逻辑产生的工具结果、告警、上下文和引用注册表。
- 当前系统提示词与最近为空的对话历史。

## Accepted alternatives

- 可用“不能一概而论”“现有证据不足以支持全称命题”“只在部分组织或场景成立”等不同措辞。
- 可先给结论再分证据，也可逐来源比较；不要求固定结构。
- 可将 LoRA/PEFT 描述为条件性技能、方案分支、特定岗位组合职责或进阶方向，只要不把它写成普遍核心任务，也不否认部分岗位确实承担。
- 可引用一个聚合节点句柄或多个有效句柄；不要求展示内部 Claim ID 或固定 URL 文本，只要求引用在系统注册表中可追溯。
