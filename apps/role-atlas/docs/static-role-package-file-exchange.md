# Static Role Package 文件交换合同

当前阶段使用纯文件连接 role-agent 与 LearnFlow，不依赖任一方数据库，也不要求 HTTP 网关。

## 权威格式

- 领域包协议：`static-role-package`，`protocolVersion: 3.0.0`。
- 传输文件：一个 canonical JSON `StaticRolePackageBundle`，包含 `manifest` 与 `components`。
- 身份固定为 `packageId + packageVersion + snapshotId + rootHash`。
- 导出器只接受已经展开、通过组件哈希与 root hash 校验的版本目录。
- 导出器拒绝覆盖已有文件；重复发布必须显式选择新路径。

## 导出

```bash
npx tsx scripts/export-role-package-file.ts \
  --source packages/golden/llm-app-engineer/1.0.0 \
  --out /tmp/llm-app-engineer-1.0.0.role-package.json
```

该命令不读取数据库、不改变 Release/Registry，也不批准 candidate。它只是把一个已经发布的不可变版本目录
封装成 LearnFlow 可验证的文件。

## 后续网关

网站部署后，网关只能传输同一 bundle 字节和媒体类型，不能重新解释、改写或重新计算领域事实。接收端仍须独立
校验组件哈希、root hash、路径安全和版本冲突。文件合同因此是网关的基础，而不是临时旁路。
