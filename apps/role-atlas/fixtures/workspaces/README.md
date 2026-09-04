# 真实工作区测试夹具

这些文件用于验证适配器和岗位快照实例化，不是岗位事实库。

- `langgraph-pr-8053.json`：公开 GitHub Issue → PR → Commit → Review → CI → Merge 工作链。来源为 [Issue #8038](https://github.com/langchain-ai/langgraph/issues/8038) 和 [PR #8053](https://github.com/langchain-ai/langgraph/pull/8053)，仓库采用 MIT License。夹具只保存公开元数据和中文摘要，不复制完整讨论或代码。

真实性规则：

- 该夹具标记为 `real_work_activity`，可以证明这一公开开发案例中发生过的活动。
- 它不能单独证明所有“大模型应用工程师”都承担相同工作；岗位共性必须由公开岗位、标准或多个独立工作区交叉验证。
- 自动测试中若加入密钥、邮箱或本机路径，安全扫描应遮蔽敏感片段，同时保留仍有岗位理解价值的事件链。
