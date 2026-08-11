# LearnFlow 桌面工作区与安全边界

本文是 Tauri 2 桌面工作区的安全契约。桌面工作区扩展文件操作能力，但不改变三类主 Agent、五核、学习对象权威或正式判题链。

## 1. 信任模型

- 浏览器部署的 `DESKTOP_MODE` 必须保持 `false`，本地文件接口对浏览器返回 404。
- Tauri 每次启动生成新的高熵桌面令牌，并在随机 loopback 端口启动 FastAPI sidecar。
- 每个文件请求同时校验登录会话、项目 `learner_id` 归属和 `X-LearnFlow-Desktop-Token`。
- 浏览器继续使用 HTTP-only cookie。由于 Tauri WebView 与 loopback sidecar 可能跨站，只有桌面令牌校验成功的登录/注册请求才会额外返回桌面 Bearer；Bearer 仅保存在该窗口的 `sessionStorage`，服务端接受它时仍要求本次启动令牌。
- WebView 只有目录选择能力，没有 `$HOME/**` 或任意文件系统权限。真正的项目根约束由 FastAPI 再次执行。
- sidecar 只允许绑定 `127.0.0.1`、`::1` 或 `localhost`；桌面令牌不得写入仓库、日志或数据库。

桌面 Python 运行属于“可信本地执行”，不是容器级代码沙箱。解释器运行能力将在独立阶段接入，默认不安装依赖，也不通过 shell 拼接命令。

## 2. 权威数据

每个 `ProjectWorkspace` 只关联一个真实本地目录。普通文件以磁盘为权威；讲义、练习和判题规则仍以数据库为权威。

```text
<ProjectRoot>/
  用户文件
  .learnflow/
    project.lfproject
    checkpoints/cp-<id>/
      lectures/lecture-<id>.lflecture
      exercises/exercise-<id>.lfexercise
    history/
    trash/
```

`.lflecture` 与 `.lfexercise` 只保存 schema、对象 ID、摘要、版本和摘要 hash。它们不能代替数据库正文，也不能通过普通文件 API 读取或改写。

## 3. 路径约束

文件服务在每次访问时执行以下检查：

1. 路径必须是相对于已登记项目根的 UTF-8 逻辑路径。
2. 拒绝绝对路径、盘符、NUL、`.`、`..` 和越界后的真实路径。
3. 从根到目标的每一层都拒绝符号链接；Windows 同时拒绝 junction/reparse point。
4. `.learnflow` 与 `.git` 对普通文件 API 始终受保护。
5. Agent 额外禁止 `.env`、凭据、私钥和常见密钥后缀。
6. 文本编辑只接受 UTF-8，单文件上限 2 MB；大型或二进制文件只返回元数据。

目录关联时会验证既有 `project.lfproject`。同一目录不能登记给两个 LearnFlow 项目，也不能覆盖属于另一项目的 marker。

## 4. 写入与恢复

- 人工编辑保存时必须携带所读版本的 SHA-256；文件已变化时返回冲突，不覆盖新内容。
- Agent 提案必须绑定当前学习者、项目、关卡和 Tutor session，保存统一 diff 后等待用户明确确认。
- 删除、重命名和移动均使用 `WorkspaceOperation`；删除进入 `.learnflow/trash/op-<id>/`，不做永久删除。
- 覆盖前的内容进入 `.learnflow/history/op-<id>/`；同一幂等键或同一确认重复调用只应用一次。
- 提案默认 30 分钟过期；基础 hash 变化后状态变为 `stale`，必须重新读取和提案。

桌面 Explorer 将数据库权威的“关卡资料”和磁盘权威的“项目文件”分成两个逻辑组，不展示 `.learnflow`。普通文本由 Monaco 打开，可使用多标签、最多三个编辑组和 `⌘S/Ctrl+S`；二进制或大型文件只显示大小与 hash。创建、重命名、移动、删除、恢复及 Finder/Explorer 定位都经同一受控 API。

文件系统与 SQLite 无法形成跨介质原子事务，因此磁盘变更先产生回滚快照，再登记 applied 状态和事件。异常操作保留 `failed/stale` 记录，不能伪装成功。

## 5. 五核与证据

`workspace_linked` 和 `workspace_change_applied` 是 `kernel_targets=()` 的操作事件。它们用于审计，不产生 `KernelMutation`，也不能证明学习者掌握了知识或具备独立实践能力。

只有用户将普通文件显式绑定练习并正式提交后，判题结果才可进入 `LearningAttempt/EvidenceEvent`。打开、编辑、保存、运行成功都不是掌握证据。

## 6. 验收命令

```bash
cd backend
venv/bin/python -m pytest tests/test_workspace.py tests/test_architecture_registry.py -q

cd ../frontend
npm run build
```

桌面内部包还需在 macOS 和 Windows 分别验证目录关联、重启恢复、diff 确认、删除恢复和 sidecar 随机端口。签名和商店凭据不属于本轮仓库内容。
