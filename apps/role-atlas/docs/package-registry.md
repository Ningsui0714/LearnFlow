# 岗位包注册中心协议 v1.0

状态：`implemented`（2026-08-22）

Package Registry 不是文件列表，也不是另一个事实层。它是静态岗位快照及其发布包的身份、治理、发现和解析平面；岗位事实仍在不可变 Static Role Package 中。

## 核心对象

```text
RoleIdentity 1 ─── n PackageLine 1 ─── n PackageRelease
     │                  │                       │
岗位身份/别名       维护与托管政策          确切版本/快照/制品
```

### RoleIdentity

- 稳定岗位身份、规范名称与别名；
- 行业、地区、学段和适用人群；
- 身份状态与替代关系。

### PackageLine

- `packageId` 与协议兼容范围；
- 维护组织、维护类型、维护策略和更新节奏；
- 托管类型（bundled / hosted / remote）；
- 可见范围和证据公开策略；
- 来源许可；
- 当前推荐 Release 指针；
- active / deprecated / disputed / superseded 状态。

维护和托管被刻意分开：一个包可以由来源组织维护、由 Role Atlas 托管；也可以由社区维护、仅登记远程制品。

### PackageRelease

- SemVer、确切 `snapshotId` 和 `snapshotAsOf` 时间边界；
- Static Role Package `rootHash`、校验报告哈希、协议版本和 PackageLine 兼容范围；
- preparing 状态（compiling / validating）、ready、published、failed、deprecated；
- 源 ProjectVersion、发布时间和废弃信息。

## 推荐版与历史版

`PackageLine.recommendedReleaseId` 是一个可原子切换的分发指针，不等于 Project HEAD，也不改变任何静态岗位快照。项目的 `currentReleaseId` 是工作台默认使用的发布版；二者在发布事务中一起移动。

解析顺序：

1. 项目内引用使用 `projectId + versionId` 精确解析；
2. 发布引用使用 `snapshotId + packageVersion` 精确解析；
3. 只给 `snapshotId` 时优先最近可用的已发布/可用制品；
4. 历史节点引用始终携带完整包坐标，不跟随推荐指针。

## Static Role Package v3

编译制品包含九个确定性组件：

- `snapshot.json`
- `sources.json`
- `semantic-graph.json`
- `work-process-forest.json`
- `views.json`
- `object-index.json`
- `retrieval-index.json`
- `validation-report.json`
- `reference-migrations.json`

Manifest 保存每个组件 SHA-256 与整体 root hash。导入支持规范 JSON 和 ZIP；导入前检查路径安全、协议、组件哈希、引用完整性和公开证据政策。相同 `packageId + version` 内容不同会拒绝，相同制品重复导入保持幂等。

编译器只产生 v3。历史 v2 制品可在导入边界通过校验并归一为 v3 内部岗位包；重新发布时一定编译为 v3，不延续旧三包身份。

## 治理边界

- 协议、哈希、引用与隐私泄露属于硬错误，会阻止 `ready`；
- 语义重合、覆盖不足、证据弱和时效风险属于警告，不以“质量门”丢弃岗位快照；
- `disputed` 表示存在明确争议，不等于技术校验失败；
- `deprecated` 和 `superseded` 保留历史解析，不执行物理删除；
- 首期 Registry 是单实例 D1 注册中心，远程联邦、签名信任链和自动同步留待 Hub 阶段。
