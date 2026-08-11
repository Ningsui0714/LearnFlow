# 五核可检查记忆图谱

## 数据分层

1. `EvidenceEvent` 是不可变动作账本，`occurred_at` 表示动作发生时间，`created_at` 表示系统记录时间，`learner_seq` 是学习者内单调序号。
2. `MemoryFact` 是由一次 `KernelMutation` 展开的原子事实。唯一键 `(source_mutation_id, fact_ordinal)` 保证重放幂等。
3. `MemoryModule` 只消费同一学习者、同一核、同一主题的事实。模块内容不可变，且不会再次成为合成输入。
4. `MemoryClaim` 是模块内可单独检查的声明。非历史导入声明必须由 `SUPPORTS` 边直接回到事实。
5. `MemoryEdge` 只保存高价值稀疏关系。跨核关系可以存在，但 `CONSOLIDATED_INTO` 两端必须同核。

`KernelState` 继续作为兼容投影。其短期区会附加 `memory_graph_recent_facts`，长期区会附加 `memory_graph_claims`。

## 写入与合成

事件写入请求不调用 LLM。归约器写入 `KernelMutation` 后同步生成事实和确定性边，并按五核规则创建 `MemorySynthesisRun`。

worker 的状态顺序为：

```text
queued -> running/reserved -> completed/consumed
                           -> failed/eligible
```

合成器只能引用运行记录中的候选 fact ID。越界引用、跨核候选和证据不足的知识掌握声明会整批拒绝。进程中断时，启动恢复会释放 reservation 并把运行重新排队。

自动合成默认关闭：

```env
MEMORY_AUTO_SYNTHESIS_ENABLED=false
```

在带标签轨迹的语义质量评测通过后，将其设为 `true` 并重启后端。未配置 LLM key 时，worker 使用确定性合成器，便于本地验证完整事务链路。

## API

- `GET /api/memory/graph`：按时间、核、节点类型、状态、项目和主题过滤，最多 300 节点。
- `GET /api/memory/timeline`：按发生时间分页读取节点。
- `GET /api/memory/nodes/{id}`：读取节点、邻居、原始动作、证据事实和合成审计。
- `GET /api/memory/consolidations`：读取持久化合成运行。
- `POST /api/memory/claims/{id}/feedback`：追加确认、纠正或撤回事件。

所有查询和反馈都使用当前登录学习者的 `learner_id`，不会接受客户端传入的学习者身份。

## 迁移与评测

v5 启动迁移会先创建 SQLite 一致性备份，然后回填双时间字段、mutation facts 和 `legacy_import` 模块。历史值无法精确定位事实时保持 `legacy/unverified`。

运行结构评测：

```bash
cd backend
./venv/bin/python scripts/evaluate_memory_graph.py
```

脚本对照字段覆盖、单体摘要和五核事实图，并检查声明证据覆盖、跨核输入、重复消费、模块不可变、纠错历史、幂等键、序号唯一性及 300 节点查询 p95。

