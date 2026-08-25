# LearnFlow vNext

这是 LearnFlow 的独立重构起点。目前只有 Chat、设置，以及支持删除对话和双栏并排的持久化多页签工作区，不连接旧后端。

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
- “发送”只保存学生输入，并明确提示 Tutor 尚未接入，不生成占位答案。
- 这个目录不读取或写入旧 LearnFlow 的数据库、五核或学习记录。
