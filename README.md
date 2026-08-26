# LearnFlow

LearnFlow 是面向计算机学习的 Tutor 工作空间。产品以连续对话为主界面，在同一学习现场连接原子学习任务、项目关卡、讲义与练习、复习、学习路径和五核学习者状态。

仓库现在只有一套产品前端：`frontend/`。原来的 vNext 已成为正式 LearnFlow，不再维护旧前端或第二套页面逻辑。

## 运行

要求 Python 3.11+、Node.js 20.19+。

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

cd ../frontend
npm install
cp .env.example .env.local
# 在 .env.local 配置 LEARNFLOW_API_KEY、模型地址和模型名称

cd ..
bash start.sh
```

- 页面：<http://127.0.0.1:4174>
- 后端：<http://127.0.0.1:8010>
- 停止：`bash start.sh stop`
- 隔离的离线验收：`bash start.sh demo`，入口为 `/review`

也可以在 `frontend/` 执行 `npm run dev`，它会检查并启动正式后端；只启动页面时使用 `npm run dev:web`。

## 目录

```text
frontend/   唯一 React + TypeScript 产品前端，以及本地 Tutor Turn Graph
backend/    FastAPI、三类 Agent 契约、学习对象、证据链与五核
desktop/    Tauri 壳与本地 FastAPI sidecar
docs/       架构、产品逻辑、运行手册与验证记录
```

运行时权威不是浏览器缓存：对话以 `AgentSession + AgentMessage` 保存，学习状态只允许通过
`EvidenceEvent -> five_kernel_reducer -> KernelMutation -> Memory Graph` 更新。五核不是五个 Agent；主责任接口仍只有 Tutor、Learning Design 和 Practice 三类。

## 验证

```bash
make verify
```

`make verify-layout` 会单独检查唯一前端边界：受 Git 管理的旧 `vnext/`、
`legacy-frontend/`、`frontend-old/`、旧 5173 运行入口或缺失的正式入口都会使检查失败。

架构权威见 [docs/ARCHITECTURE_AUTHORITY.md](docs/ARCHITECTURE_AUTHORITY.md)，Agent 工程约束见
[docs/AGENT_ARCHITECTURE_GUIDE.md](docs/AGENT_ARCHITECTURE_GUIDE.md)，一分钟产品逻辑见
[docs/product/LOGIC.md](docs/product/LOGIC.md)。仓库维护规则见 [AGENTS.md](AGENTS.md)。
