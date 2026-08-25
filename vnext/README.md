# LearnFlow vNext

这是 LearnFlow 的独立重构起点。目前只有 Chat、设置、自由态、简单讲解态，以及支持删除对话和双栏并排的持久化多页签工作区，不连接旧后端。

先阅读 [LOGIC.md](./LOGIC.md)，产品逻辑变化应先在其中收紧。

## 本地运行

```bash
npm install
cp .env.example .env.local
# 编辑 .env.local，填写 LEARNFLOW_API_KEY
npm run dev
```

默认地址：`http://localhost:4174`

## 当前边界

- 对话和工作区仅保存在浏览器 `localStorage`。
- API Key 只保存在被 Git 忽略的 `vnext/.env.local`，页面不会读取或返回 Key。
- 模型请求经过本地 `/api/tutor` 代理；支持 Chat Completions 和 Responses endpoint，不要求供应商开放浏览器 CORS。
- 对话内容支持安全的 Markdown、GFM 和 KaTeX 数学公式渲染，不执行模型返回的原始 HTML。
- 修改 `.env.local` 后需要重启 vNext 服务。
- 没有配置或调用失败时显示真实原因，不生成占位答案。
- 这个目录不读取或写入旧 LearnFlow 的数据库、五核或学习记录。
