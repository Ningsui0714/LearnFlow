# 知行课径 · 目录导览

> 本文件是工作区布局速览。交接与细则见 `docs/知行课径新对话项目对接文档_20260825.md`（比旧版对接文档更新）；权威规则见根目录 `AGENTS.md` 与 `CLAUDE.md`。

## 顶层布局

- **backend/**：API 服务（`server.py`）、领域逻辑（`domain.py`）、讲解/路径/目标/检索等模块、SQLite 运行数据与全部后端测试。
  - `backend/data/`：能力图谱、知识条目、题库、错误卡（`knowledge_seed.py`、`diagnosis_bank.py`、`error_cards.py`、`goal_graph.py`、`capability_catalog.py`）。
  - `backend/learner_discovery/`：学习者状态发现（五核事件流）子系统。
  - `backend/local_explanation_engine.py`：本地讲解引擎（大纲先行 + 分节生成、check 块结构化自测）。
  - `backend/.env`：本地私密配置，**不得读取/输出/提交**。
- **frontend/**：新版三栏学习工作台 `agent-v2.html`（默认入口）、兼容 Agent 页面 `agent.html`（`/legacy`）、旧学习中心 `index.html`、通用 `app.js`/`api.js`、`styles.css`、固定第三方依赖 `vendor/`。
- **docs/**：过程设计、专项说明与**历次交接文档**（通常不提交 git）。
- **workflows/current/**：当前有效的讯飞星辰工作流资产（YAML + 每份一份 `debug-data/` 调试 JSON）。
- **workflow-nodes/**：工作流自定义节点源码。
- **prototype/**：独立 HTML 原型与 UI 样板，非正式页面入口。
  - `agent-ui.html`（旧原型）、`loop-sample.html`（学习闭环高保真样板）、`ui-directions.html`（UI 方向稿，被 loop-sample 引用）。
- **tools/**：构建、校验、迁移与演示工具（`builders-and-validators/`、`gen_workflows.py` 等）。
- **references/**：比赛原始 PDF 与渲染页，只读。
- **demo-output/**、**eval-output/**：演示与评估产物。
- **data/**：本地运行数据（gitignore 不上传）。
- **_archive/**：历史归档，只读。
- 根目录中文 `.md`：项目文档库（比赛方案、产品构想、评审、实现记录等；多数被 `.gitignore` 排除，不提交）。
- `学习路径生成相关源码_20260823.zip` + 同名解压目录：WF04 错题优先个性化出题的交付包副本（权威版本已合入 main）。

## 版本控制注意

- `docs/`、`references/`、`_archive/`、`tools/`、`workflow-nodes/`、`workflows/history/`、测试与日志产物被 `.gitignore` 排除。
- 根目录 `*.md` 默认忽略，仅保留 `比赛方案`、`项目介绍`、`知识库`、`DIRECTORY_GUIDE.md`、`AGENTS.md`。
- 开始任务前先 `git status --short`，保护用户未提交改动。

## 启动系统

PowerShell：

```powershell
Set-Location -LiteralPath "D:\jbgs\2"
.\启动系统.ps1
```

然后打开 http://127.0.0.1:4173/ 。默认显示新版三栏学习工作台；旧 Agent 页面可通过 http://127.0.0.1:4173/legacy 打开。

## 识别图片

遇到图片不要用 Read 工具，改用：`node vision.cjs "<图片路径>" "用中文描述这张图片"`。
