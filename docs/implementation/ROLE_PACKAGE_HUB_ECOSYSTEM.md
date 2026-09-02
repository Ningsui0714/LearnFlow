# 岗位图谱 Hub 生态合同

## 分层结论

岗位图谱生产、治理和消费分为三个责任层：

1. role-agent 的冷启动 workflow 与迭代 skill 形成有来源、可校验的候选快照和岗位包；模型不能批准自己的产物。这两项能力不在 LearnFlow 提供。
2. Hub 用确定性 `submit -> review -> publish` 状态机冻结版本、执行所有权和独立审核门，并产生内容寻址目录。
3. LearnFlow 只读取目录中对当前主体可见的已发布条目，再独立校验 bundle 后安装到岗位插件；安装不产生学习证据。

## 第一阶段：纯文件 Hub

```text
hub/
  hub-policy.json
  catalog.json
  objects/sha256/<rootHash>.role-package.json
  submissions/<submissionId>.json
```

公共官方包和社区包都必须由 policy 中的独立 reviewer 批准，维护者不能审核自己的提交。用户私有包通过岗位包
校验后可供同一 `ownerSubjectId` 使用，但不会向其他主体开放。LearnFlow 需要显式传入当前主体才能看到私有条目；
公共条目必须携带 `review=approved`。

Hub 内部目录不得直接分发。role-agent 必须先按认证主体导出作用域视图：公共视图只含公共已审核包，个人视图再
加入该主体自己的私有包，并且只复制视图中引用的内容对象。LearnFlow 的 `--catalog` 应指向这种分发视图；自身
的主体过滤只是纵深防御，不能替代 Hub 侧访问控制。

Hub 目录使用 `role-package-hub-catalog.v1`，岗位包继续使用 `static-role-package@3.0.0`。目录 hash 保护目录投影
完整性；岗位包自身的组件 hash、root hash、snapshot 身份和不可变版本冲突仍由 LearnFlow 独立验证。

## LearnFlow 导入

```bash
cd frontend
npm run role:import-hub -- \
  --catalog /path/to/hub/catalog.json \
  --package role-package:example \
  --actor-subject user:alice \
  --dry-run
```

导入是维护期命令，不是 Tutor Tool、插件 Renderer 动作或学习状态写入。成功安装后，岗位插件按既有目录发现机制
消费新包，不需要在宿主增加岗位 ID 分支。

LearnFlow 岗位插件只负责解释已安装包。其唯一研究型入口是固定节点的有界风险研究：读取快照内两跳邻域、关系、
证据限制、生命周期和事理风险。它不联网、不补证据、不创建候选 patch；发现的缺口若要修复，必须回到 role-agent
发起迭代并重新经过 Hub 审核发布。

## 后续网关

在线 Hub 只应把当前合同搬到认证后的 HTTP/对象存储边界：认证服务端注入 subject，服务端过滤私有目录，下载
仍返回原始内容寻址 bundle。需要补充制品签名、恶意内容扫描、审核 UI、申诉/撤回、配额和审计日志；不应重新
实现另一套候选、审核或发布语义。
