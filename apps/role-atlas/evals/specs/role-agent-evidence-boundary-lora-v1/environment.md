# Environment 规格：role-agent-evidence-boundary-lora-v1

Status: approved

## Dependencies

| 依赖 | 模式 | 实现与固定标识 | 凭据 | 可见效果 |
|---|---|---|---|---|
| 黄金岗位包 | frozen | `packages/golden/llm-app-engineer/1.0.0/`；tag `golden/llm-app-engineer/v1.0.0`；rootHash `206e01b0285eb9b7c3ff5e432bbd2ccbc2561f61ba954e730339b249ca084a76` | 无 | 只读工具查询 |
| 用户所选节点卡片 | frozen | 固定引用 `knowledge:llmapp:peft-lora-conditional`，作为 Agent 可见请求上下文 | 无 | 只读 |
| MiMo 模型服务 | live | 生产 `createModelInvoker` 调用 `mimo-v2.5`；仅允许生产配置中的模型 API 主机 | `MIMO_API_KEY` | 流式模型推理；不允许其他外网访问 |
| Verifier 独立证据 | frozen/hidden | 从黄金研究台账和 `frozen-v1` 物化的最小证据集，仅挂载到验证器 | 无 | Harness 不可见 |
| 语义 judge | live/hidden | 固定 `mimo-v2.5-pro`；只接收有界最终答案、注册引用和独立证据 | `MIMO_JUDGE_API_KEY` | 只生成结构化 verdict/reason；Harness 不可见 |

## Backend contracts

### Role Package Runtime

- Interface：保留 `SnapshotRoleRuntime.execute(RoleToolCall, runId) -> ToolEnvelope` 和现有六个工具接口。
- 本题数据路径：结构化引用可被 `resolveTarget` 精确解析；对象读取返回节点、关系和前三条证据预览；证据审查返回该节点全部六条 EvidenceBinding、片段、来源元数据和来源资格。
- Rules：校验 package/version/snapshot/target；引用不匹配时返回生产错误；每次最多 25 个对象；本题只读。
- Effects：无岗位包、数据库或外部业务状态写入；同一 run 的重复工具调用仅命中 Runtime 内存缓存。
- Reset：每个 trial 创建新进程或新 Runtime，清空缓存并重新读取同一冻结文件。
- Evidence：`lib/agent/snapshot-runtime.ts`、`lib/agent/planner.ts`、`tests/candidate-project-agent.test.ts`，以及本轮对冻结黄金包的只读运行时探针。

### Model endpoint

- Request/response：保留仓库当前 OpenAI-compatible SSE 请求、`thinking` 配置、reasoning/text 分流和超时行为。
- Permissions：只允许模型推理，不提供岗位包之外的搜索工具；模型不得通过 Environment 读取隐藏验证证据。
- Failures：认证、限流、HTTP、SSE 解析、空响应和超时均记为 infrastructure error，不记为 Agent 失败。

## Data

### Dataset: frozen role package

- Purpose：向 Agent 提供与正式发布物完全一致的岗位、证据和引用注册数据。
- Files：`manifest.json`、`snapshot.json`、`sources.json`、`semantic-graph.json`、`work-process-forest.json`、`views.json`、`object-index.json`、`retrieval-index.json`、`validation-report.json`、`reference-migrations.json`。
- Assembly：`snapshot.json` 提供元数据；`sources.json`、`semantic-graph.json`、`work-process-forest.json` 分别映射到 Runtime 的 `sources`、`semantic`、`process`；`validation-report.json.audit` 映射为 `audit`。
- Storage：任务镜像中的只读目录；启动时校验 manifest 内所有文件哈希和 rootHash。
- Reset：重新创建容器；文件摘要必须与基线相同。

### Dataset: selected reference

- Purpose：复现用户在 Role Atlas UI 中选中相关知识节点后追问证据的生产场景，避免把检索召回能力混入本题。
- Record：上述 package/version/snapshot 与 `knowledge:llmapp:peft-lora-conditional` 的完整 `NodeReference`。
- Storage：Agent 可见的请求配置；不包含结论、评分规则或隐藏 Claim 状态。

### Dataset: verifier truth

- Purpose：独立判断最终回答是否正确处理“所有企业都独立承担 LoRA/PEFT”这一全称结论。
- Records：
  - `CLM-D01`：`disputed`、`research_inference`、`weak`，以及两条适用范围限制；
  - 六个定位片段：`SEG-GOV-GENAI-03`、`SEG-JD-CSSC-02`、`SEG-JD-TENCENT-02`、`SEG-JD-LIZHI-03`、`SEG-JD-FUDAN-03`、`SEG-TECH-PEFT-01`；
  - 对应来源的资格、独立性和 locator；
  - 冻结案例 `EVD-DISPUTED-001` 与 `QA-UNCERTAIN-001` 的人工审定边界。
- Relationships：正式职业活动与个别应用岗样本支持“某些情境会做”；另一些样本将微调列为优先项、加分项或算法岗深层职责；这些材料不能支持“所有企业、所有该岗位、独立承担”。
- Storage：验证器镜像的只读隐藏 fixture；不复制到 Harness workspace、提示词或日志。
- Reset：固定文件，无可变状态。

## Isolation

- 每个 trial 使用独立容器、Runtime、run ID、session ID 和输出目录。
- 黄金包目录只读；不挂载项目数据库，不提供 shell、文件写入、Web 搜索或生产工作区凭据。
- Harness 网络默认拒绝，仅开放生产模型 API 所需主机；Verifier judge 在独立进程使用自己的凭据。
- 使用真实 UTC 事件时间；任务判断不依赖时钟。
- 仅 Harbor job 目录可写，用于事件、最终答案和验证结果。

## Fidelity limits

- 不复现浏览器 UI、HTTP NDJSON 层、项目数据库历史、Provider 设置页和多轮恢复；本题不依赖这些行为。
- live 模型输出存在随机性；保留模型、参数、时间和运行配置，并以多次独立 trial 报告稳定性，不把模型服务故障记为能力失败。
- 仅测试一个经用户选择的争议节点，不代表已覆盖法规范围、版本冲突或单一 Issue 外推等其他证据边界。
