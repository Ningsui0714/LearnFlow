# Role Atlas 子应用边界

本目录是岗位图谱生产产品 Role Atlas，并托管 Graph Hub 发现入口。同仓管理不使它成为第二套 LearnFlow 学习前端。

- 从本目录执行 Node/npm 命令，保持自己的 package-lock、React 和构建依赖，不与根 frontend 混装。
- 岗位快照、迭代、审核和发布由本应用的 Role Package 协议、测试及 docs 维护；不得直接读写 LearnFlow 五核和学习状态数据库。
- 与学习端交接仍使用主体绑定且固定版本的岗位包接口。新增 LearnFlow 能力或事件必须按根 AGENTS.md 更新架构权威，不能借同仓绕过。
- 不提交环境密钥、.wrangler、数据库、node_modules、输出目录；public/data 中已审查的只读发布数据是源码资产。
- 修改后执行 npm test、npm run typecheck、npm run build，同时验证相关 LearnFlow 契约。
- 不设置独立远端或嵌套 .git；提交和推送使用 LearnFlow 根仓库。原外部工作副本不自动双向同步。
