# 大模型应用工程师黄金岗位包研究底稿

本目录保存 `role:llm-app-engineer` 黄金岗位包 1.0.0 的人工审视研究资产。最终静态包由这些输入确定性编译产生，研究底稿与发布产物分离，避免把搜索摘要或模型生成直接写成已接受岗位事实。

## 研究顺序

1. `sources/source-register.json`：先判断来源资格、独立性、时效和适用范围。
2. `segments/evidence-segments.json`：记录可定位片段；`close_paraphrase` 与 `research_note` 不冒充原文引语。
3. `claims/claims.json`：区分直接事实、跨来源归纳、研究推断、争议和拒绝结论。
4. `boundary/boundary-matrix.json`：记录岗位名、正式职业锚点、相邻岗位与重新审查条件。
5. `task-barrier/task-barrier.json`：先冻结典型工作任务，再继续能力和知识技能。
6. `task-barrier/capability-model.json`：从任务反推能力、能力单元、知识点、技能点及前置关系。
7. `task-barrier/process-forest.json`：以任务稳定 ID 连接真实工作情境的事件、分支、异常和验收。
8. `review-decisions/decisions.json`：保留用户确认和研究判断，不静默改名、拆岗或改锚。

## 证据纪律

- `confidence` 是现有协议的兼容字段，仅按 strong / moderate / weak 映射到三个固定档位，不是统计概率。
- 99 个片段中，进入 Claim 的片段支撑已接受、争议或拒绝结论；未进入 Claim 的片段保留为发现上下文，不自动进入图谱事实。
- 企业 JD 只能说明该企业、该职位、该时间的明示要求；跨岗位结论必须由独立样本和更高等级来源共同支持。
- 公开 Issue 是真实技术事件线索，但通常是环境和版本特定的有限证据，不能外推发生频率。
- 当前没有企业内部完整工作事件，事理森林属于 `documented_norm` 或 `inferred_pattern`，不得描述为某家企业的流程实录。

## 构建与校验

```bash
npx tsx scripts/build-golden-role-package.ts
npx tsx scripts/build-golden-role-package.ts --check
npx tsx scripts/validate-golden-role-package.ts
```

构建器只生成静态岗位包组件和哈希，不执行冷启动、迭代或 Agent 编排。
