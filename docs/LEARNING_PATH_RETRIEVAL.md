# 学习路径检索与个人节点提案

## 目标

学习路径检索要回答“目标在图中的哪个节点”，不能替代路线规划，更不能推断掌握。运行顺序固定为：

```text
自然语言目标
  -> 精确读取（ID / 标题 / 别名）
  -> 未命中才做模糊检索
  -> resolved：读取邻接关系并规划
     ambiguous：请学习者选择
     not_found：联网研究图谱缺口
  -> 有来源且无重复节点：个人节点 proposal
  -> 学习者确认：正式事件网关写入个人覆盖层
```

## 三个模型可见工具

| 工具 | 输入 | 输出 | 硬边界 |
|---|---|---|---|
| `lookup_learning_path_node` | 原始目标、候选上限 | 精确候选与匹配原因 | 只比较稳定 ID、标题、别名；不自行模糊匹配 |
| `search_learning_path_graph` | 精确未命中的目标、候选上限 | 候选、分数分解、`resolved/ambiguous/not_found` | 确定性排序；歧义不得生成路线 |
| `propose_personal_path_node` | graph gap、外部来源 URL | 可检查节点提案 | 必须有来源、重复检查和显式确认；不写图或五核 |

旧 `read_learning_path` / `vnext_learning_path_graph_reader` 只保留为兼容调度器，不进入模型 tools
列表。Agent Runtime 在执行任何模型工具调用前还会检查当前 mode/scope 的工具 allow-list。

## 模糊检索策略

实现位于 `frontend/src/learning-path-retrieval.ts`。查询先做 Unicode NFKC、大小写、常见繁简字和
Agent 术语归一化，然后分别计算：

- 词法身份与包含关系；
- Damerau-Levenshtein 与双字组 Dice 拼写相似度；
- 领域与摘要 token 重叠；
- 三路独立排名的 reciprocal-rank-style 融合。

原始异构分数不会直接互比。最终决策还使用头部差距、短词宽泛歧义和复合主题惩罚：例如
“安全”必须保留多个候选；“量子机器学习”不能只因为包含“机器学习”就被判定为同一节点。
阈值属于版本化策略 `vnext-learning-path-retrieval-v2`，修改时必须增加行为测试。

## 状态与证据边界

- 检索结果是 Structure 参考，不是正式路线，也不是 Knowledge mastery。
- 个人节点 proposal 固定 `confirmationRequired=true`、`masteryUnchanged=true`。
- 正式加入继续走 `vnext_personal_path_node_added -> five_kernel_reducer`；提案阶段无事件写入。
- 自报“学过/掌握”最多形成带来源的 exposure，不能自动提升验证等级。
- 搜索片段是不可信外部内容，只作为节点关系和命名的 provenance。

## 最小验收矩阵

| 场景 | 预期工具链 | 禁止结果 |
|---|---|---|
| `machine-learning` / `机器学习` / 已登记别名 | exact | 额外 fuzzy 或联网 |
| `操作系統原里` | exact miss -> fuzzy resolved | 直接 graph gap |
| `安全` | exact miss -> fuzzy ambiguous | 自动选网络安全 |
| `量子机器学习` | exact miss -> fuzzy not_found -> search -> proposal | 折叠为机器学习；直接写图 |
| 模型请求旧 `read_learning_path` | runtime blocked | 绕过当前工具目录 |
| proposal 无来源 | rejected | 无 provenance 的个人节点 |

前端行为测试位于 `frontend/server/learning-path-graph.test.ts` 与
`frontend/server/agent-runtime.test.ts`；注册漂移由
`backend/tests/test_architecture_registry.py` 检查。
