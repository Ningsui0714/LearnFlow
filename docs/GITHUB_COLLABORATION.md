# LearnFlow GitHub 协作准则

> 适用对象：LearnFlow 全体组员及其 Codex
>
> 权威关系：本文负责 GitHub 协作流程；仓库内 Agent 必须同时遵守根目录 `AGENTS.md`。架构与五核语义仍以 `architecture_registry.py` 及架构文档为准。

## 1. 不可协商的底线

1. **禁止直接在 `main` 开发或推送。** 所有变更通过功能分支和 PR 进入 `main`。
2. **禁止 force push、`git reset --hard` 和覆盖他人历史。** 发布过的共享分支不得未经负责人同意改写历史。
3. **禁止未经授权提交、推送、合并、删除、迁移数据或修改 GitHub 设置。** Codex 必须获得人的明确授权。
4. **禁止把密钥、`.env`、token、日常/比赛数据库、缓存、权重、虚拟环境或日志提交到 Git。**
5. **禁止在模块内私建第四个主 Agent、第二套五核或绕过 EvidenceEvent 的写入通道。**
6. **禁止一个 PR 混入无关重构、格式化或他人未完成的工作。**

Codex 发现任何一条可能被违反时，必须停止扩大修改，先向负责人说明冲突。

## 2. 任务和责任人

每个功能、修复或跨模块重构必须有 Issue，或者有维护者给出的等价书面任务。任务至少写清：

- 目标与用户价值；
- 输入、输出和影响范围；
- 验收标准；
- 明确的非目标与禁止事项；
- 是否影响 Agent、五核、事件、API、数据库、外部网络或 LLM。

一个分支只有一名主责人或一个明确的协作小组。开工前在 Issue 声明负责人、分支名和预计修改的共享热点文件。

## 3. 分支模型

默认分支格式：

```text
codex/<type>-<issue>-<short-name>
```

`type` 使用 `feat`、`fix`、`docs`、`refactor`、`test` 或 `chore`。例如：

```text
codex/feat-12-learner-state-discovery
codex/fix-27-project-confirmation
```

规则：

- 一个分支只解决一个主要任务。
- 新任务从最新 `origin/main` 建立分支。
- 不在他人的远程分支直接开发；需要协作时，先在 Issue/PR 留言获得负责人同意。
- 已发布的共享分支要同步 `main` 时，优先普通 merge；如需 rebase，必须先与分支负责人确认。

## 4. Codex 开工协议

组员向自己的 Codex 发出任务时，必须包含或要求它提取以下信息：

```text
任务/Issue：
目标：
验收标准：
允许修改：
禁止修改：
预计分支：
是否允许 commit/push/PR：
是否影响共享契约：
```

Codex 必须在修改前执行：

```bash
git status -sb
git remote -v
git diff --check
```

并且：

1. 完整阅读根目录 `AGENTS.md` 与本文档。
2. 标记已有未提交改动；这些改动默认属于用户或其他组员。
3. 只读取与任务直接相关的文档和代码，但所选中的规则文档必须完整读完。
4. 只修改任务范围内的文件，不删除或重置无关改动。
5. 未经人的明确授权，只停留在本地工作树。

## 5. 架构分工与共享热点

### 工作线 A：主架构、三类 Agent 与五核

负责 Agent 契约、五核短期键、EvidenceEvent、reducer、Memory Graph、scope/ownership、幂等与证据等级。

### 工作线 B：工具、产品技能、工作台与重要事件

负责 Action Board handler、来源、RAG、生成器、执行器、外部 adapter、页面与 demo 资产。

以下是共享热点，修改前必须在 Issue/PR 声明，且 PR 必须有 `Contract impact`：

- `backend/app/services/architecture_registry.py`
- `backend/app/services/learning_runtime.py`
- `backend/app/services/memory_graph.py`
- `backend/app/models/learning.py`
- `backend/app/api/architecture.py`
- `backend/app/services/action_board.py`
- `docs/ARCHITECTURE_AUTHORITY.md`
- `docs/AGENT_ARCHITECTURE_GUIDE.md`
- 任何 Agent handoff、EvidenceEvent、RemediationStrategy 或五核 schema/状态机

修改共享契约必须同时更新注册表、实现、测试和文档，并请架构维护者审查。

## 6. 重叠修改协议

两名组员或两个 Codex 预计修改同一个文件时：

1. 立即在 Issue/PR 声明文件、函数和预计完成时间。
2. 确定一名主责人；另一方通过提交小而独立的 commit、patch 或评审意见协作。
3. 不同时重写同一个函数，不通过“谁先 push 谁赢”解决冲突。
4. 若发现未知改动，立即停止编辑重叠区域，先联系负责人。
5. 合并冲突后重新执行受影响测试，不得只保证文本冲突消失。

## 7. Commit 与暂存区

- Commit 使用 Conventional Commits：`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`。
- Commit 应小而完整；同一个 commit 的代码、测试与必要文档应能一起评审。
- 工作树混合时，必须使用显式路径 `git add file1 file2`，不得默认 `git add -A`。
- 提交前必须执行 `git diff --check`、`git diff --cached` 和 `git status -sb`。
- 不得用 `--no-verify` 绕过仓库检查。

## 8. 验证门禁

最小检查：

```bash
git diff --check
```

修改后端：

```bash
cd backend
venv/bin/python -m pytest -q
```

修改前端：

```bash
cd frontend
npm run build
```

修改架构注册表：

```bash
cd backend
venv/bin/python -m pytest tests/test_architecture_registry.py -q
```

修改比赛/demo：

```bash
bash start.sh demo
```

如环境无法执行某项检查，PR 必须写明“未执行”和原因，不得声称通过。

## 9. Draft PR 契约

分支首次发布后建立 Draft PR。PR 必须使用仓库模板并填写：

- `What`：改了什么；
- `Why`：根因和用户价值；
- `Contract impact`：Agent、五核、事件、API、DB 或注册表影响；无则写 `None`；
- `Evidence`：实际执行的测试及结果；
- `Demo`：独立复现步骤；
- `Risks and rollback`：风险、兼容性与回滚方式。

涉及 UI 提供截图或录屏；涉及 API/schema 提供请求响应样例；涉及迁移提供升级和回退说明。

## 10. Review 与合并

1. 作者不能只依赖自己的 Codex 自审；至少一名其他组员或独立 Codex 任务检查 diff。
2. 共享契约变更必须由架构维护者批准。
3. 前端、工具、技能或工作台变更由对应维护者审查；涉及五核写入时追加架构审查。
4. 所有适用检查必须通过，所有可操作 review thread 必须解决。
5. 默认使用 Squash Merge；合并后删除功能分支。
6. `main` 必须始终可运行、可测试、可启动 seeded demo。

## 11. GitHub 仓库建议设置

维护者应在 GitHub 为 `main` 开启分支保护：

- Require a pull request before merging。
- Require at least 1 approval。
- Dismiss stale approvals when new commits are pushed。
- Require conversation resolution before merging。
- Require applicable status checks after CI 工作流程建立。
- Block force pushes and deletions。
- 只允许维护者执行合并。

## 12. 给组员 Codex 的首条消息

新任务可以直接将下面这段交给组员的 Codex：

```text
你正在 LearnFlow 协作仓库工作。开始前必须完整阅读根目录 AGENTS.md 和
docs/GITHUB_COLLABORATION.md，执行 git status -sb，并把已有改动视为他人所有。
一项任务使用一个 codex/<type>-<issue>-<name> 分支，禁止直接修改 main、force push、
reset --hard、覆盖无关改动，也不得在没有明确授权时 commit、push 或建 PR。
涉及三类 Agent、五核、EvidenceEvent、Action Board 或 RemediationStrategy 时，
先阅读架构权威文档和注册表；任何共享契约变更必须同步更新注册表、实现、测试和文档。
只实现 Issue 范围，执行适用测试，并在 PR 中如实填写 Contract impact、Evidence、
Demo 和 Risks and rollback。发现冲突、未知改动或需要扩权时，立即停止并向负责人报告。
```

## 13. 完成定义

只有同时满足以下条件，任务才能从 Draft 转为 Ready for review：

- 实现与 Issue 验收标准一致，无未授权扩展；
- 代码、测试、文档与注册表无漂移；
- 适用检查已实际执行并记录结果；
- 无秘密、本地数据、无关修改或他人工作损失；
- PR 信息足以让未参与开发的组员或 Codex 独立复现和评审。
