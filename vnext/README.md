# LearnFlow vNext

这是 LearnFlow 的独立重构起点。目前只有 Chat、设置、自由态、简单讲解态，以及支持删除对话和双栏并排的持久化多页签工作区，不连接旧后端。

先阅读 [LOGIC.md](./LOGIC.md)，产品逻辑变化应先在其中收紧。

## 本地运行

```bash
npm install
npm run dev
```

默认地址：`http://localhost:4174`

## 当前边界

- 对话和工作区仅保存在浏览器 `localStorage`。
- API Key 只保留在当前页面内存中，刷新即清空。
- 模型请求由浏览器直接发往设置中的 OpenAI 兼容地址；支持 Chat Completions 和 Responses endpoint。
- 远程模型服务必须允许浏览器跨域请求；后续接入正式后端时再把请求移到服务端代理。
- 没有配置或调用失败时显示真实原因，不生成占位答案。
- 这个目录不读取或写入旧 LearnFlow 的数据库、五核或学习记录。
