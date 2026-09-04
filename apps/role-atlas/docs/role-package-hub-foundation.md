# 岗位图谱 Hub：纯文件基础合同

第一阶段不依赖网站、对象存储或在线身份系统。Hub 是一个可搬运目录：内容寻址岗位包位于
`objects/sha256/`，审核状态位于 `submissions/`，面向消费者的投影是 `catalog.json`。

## 权威边界

- 冷启动 workflow 与迭代 skill 只产生候选快照/岗位包，不能批准自己。
- 冷启动与迭代只在 role-agent 生产侧提供；LearnFlow 不暴露这两项能力。
- Hub 的确定性状态机负责 `submit -> review -> publish`。
- 公共包必须经过 policy 中独立 reviewer 审核；提交者不能审核自己的包。
- 用户私有包通过结构与哈希校验后可立即供本人使用，但不会向其他用户开放。
- `official` 只表示维护主体在 policy 的官方名单中，不跳过公共审核。
- LearnFlow 仍会独立校验岗位包，目录记录不能替代内容校验。

## 目录协议

```text
hub/
  hub-policy.json
  catalog.json
  objects/sha256/<rootHash>.role-package.json
  submissions/<submissionId>.json
```

`catalog.json` 使用 `role-package-hub-catalog.v1`。后续 HTTP 网关应原样返回目录和对象字节，
并用认证主体替代 CLI 中的 subject 参数；不应另造一套发布或审核状态机。

Hub 内部总目录不是分发物。`export-view` 生成主体作用域视图，只复制公共包与该主体自己的私有包；无主体时
生成纯公共视图。纯文件阶段的 subject 由本机维护者提供，只有本地管理权限，不等同于线上认证。

## 本地流程

```bash
npx tsx scripts/role-package-hub.ts init --hub ./hub --official official:role-atlas --reviewers reviewer:one
npx tsx scripts/role-package-hub.ts submit --hub ./hub --file ./role.role-package.json --owner user:alice --maintainer Alice --channel community --visibility public
npx tsx scripts/role-package-hub.ts review --hub ./hub --submission <id> --reviewer reviewer:one --decision approve
npx tsx scripts/role-package-hub.ts publish --hub ./hub --submission <id> --actor user:alice
npx tsx scripts/role-package-hub.ts export-view --hub ./hub --out ./hub-view --actor user:alice
```

当前纯文件阶段把 Hub 目录本身视为受信分发边界，尚未提供签名、在线认证、恶意内容沙箱或审核 UI。
