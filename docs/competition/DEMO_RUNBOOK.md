# Seeded Demo 演示脚本

## 0. 场前准备

1. 在干净终端执行 `bash start.sh demo`。
2. 确认浏览器进入启动脚本打印的 `/demo` 地址，并自动跳到“边界条件：安全平均值”练习页。
3. 确认后端 `GET /api/demo/status` 返回 `enabled: true`。
4. 确认 `GET /api/architecture/validate` 返回 `valid: true`。

## 1. 概念题闭环（约 90 秒）

1. 故意选择错误答案并提交。
2. 指出面板展示具体错误证据、误解标签和确定性策略 reason code。
3. 依次点击“换种讲法”“看步骤”或“看示例”。说明切换前的讲法会记录为对当前用户无效，而不是仅改变前端文字。
4. 点击“重做原题”，选择 `if not values:` 后提交。
5. 完成自动出现的新情境概念变式。
6. 指出“证据已回写”状态和 evidence IDs。

## 2. 代码题闭环（约 120 秒）

1. 保留 starter code 提交，展示空列表用例的除零失败。
2. 展示执行追踪、失败输入、预期与实际结果；需要时切换步骤或示例。
3. 在除法前加入：

```python
if not values:
    return 0.0
```

4. 点击“重做原题”，确认全部测试通过。
5. 在自动出现的变式中，预测新输入修复后的输出并提交。
6. 展示纠错完成和证据回写。

## 3. 架构说明（约 45 秒）

- LLM 可以渲染讲解，但 `RemediationStrategy` 按错误类型、历史无效讲法和阶段确定下一步。
- 三类主 Agent 都不能直接写五核；唯一写入链是 EvidenceEvent 到确定性 reducer。
- 星辰/Mock 工作流是可替换内容 adapter。离线 demo 不依赖它们，也不依赖外部网络。
- 注册表 API 把 Agent、kernel、capability、tool、skill、workbench 和重要事件放在同一可校验快照中。

## 4. 现场故障切换

- LLM 或网络不可用：继续使用 demo；所有闭环逻辑是本地确定性的。
- 日常数据库状态异常：停止服务后重新运行 `bash start.sh demo`，演示库与日常库隔离且 seed 幂等。
- 浏览器未跳转：手动打开启动脚本打印的前端地址并追加 `/demo`。
- 端口占用：先执行 `bash start.sh stop`，确认旧进程结束后重启。
- 需要证明版本：打开 `/api/architecture/registry`，记录 version、digest 和 validation_errors。
