# LearnFlow vNext

这是 LearnFlow 的独立重构前端。它保留 Chat、多页签与并排工作区，并通过受限正式网关接入学习任务队列、学习路径和五核画像；浏览器本地状态只负责工作区与离线恢复，不再充当学习者状态权威。

先阅读 [LOGIC.md](./LOGIC.md)，产品逻辑变化应先在其中收紧。

## 本地运行

```bash
npm install
cp .env.example .env.local
# 编辑 .env.local，填写 LEARNFLOW_API_KEY
npm run dev
```

`npm run dev` 会统一启动 vNext 页面和正式后端，并在页面开放前检查五核后端是否健康。停止该命令时，由它启动的进程会一起退出；已经健康运行的外部后端只会被复用，不会被误停。默认页面地址：`http://localhost:4174`。

只调试页面、且已经单独启动正式后端时，可以使用：

```bash
npm run dev:web
```

正式后端默认地址为 `http://127.0.0.1:8010`，可用 `VNEXT_BACKEND_URL` 覆盖（旧的 `LEARNFLOW_FORMAL_BACKEND_URL` 仍兼容）。开发环境会复用后端登录会话；没有会话时可使用后端开发账号自动建立隔离学习者身份。

## 当前边界

- 对话、纸张和工作区保存在浏览器 `localStorage`；任务、路径事件和五核记忆以正式后端为权威。
- API Key 只保存在被 Git 忽略的 `vnext/.env.local`，页面不会读取或返回 Key。
- 模型请求经过本地 `/api/tutor` 代理；支持 Chat Completions 和 Responses endpoint，不要求供应商开放浏览器 CORS。
- 对话内容支持安全的 Markdown、GFM 和 KaTeX 数学公式渲染，不执行模型返回的原始 HTML。
- 修改 `.env.local` 后需要重启 vNext 服务。
- 没有配置或调用失败时显示真实原因，不生成占位答案。
- 正式学习者写入只通过 `/api/learner-state/*` 的 allow-list 事件网关，统一进入 `EvidenceEvent -> five_kernel_reducer -> Memory Graph`；vNext 不直接写数据库或 KernelState。
- 联网讲解使用分层的计算机知识来源和可检查的检索计划；设计与可选搜索后端见 [COMPUTER_KNOWLEDGE_SEARCH.md](./COMPUTER_KNOWLEDGE_SEARCH.md)。
- 四种基础 Skill 的步骤仍由对话内本地运行时编排，但正式 Learning Task 生命周期进入全局任务队列；Skill 导航和任务完成都不等于掌握。活动位置、证据边界与研究依据见 [LEARNING_TASK_DESIGN.md](./LEARNING_TASK_DESIGN.md)。
- 学习路径状态与个人节点写入 Structure；“自报学过”最多在 Knowledge 留下接触记录，绝不升级 mastery。
- 五核画像支持归档/恢复记忆，以及确认、纠正、撤回 Claim；原始事件和历史版本保持只追加、可审计。
