# 风险研究与图谱修复（兼容说明）

原“继续研究”和“风险修复”已合并为一个 [岗位快照迭代 Skill](snapshot-iteration.md)。风险审计、定向研究、结构修复、内容扩展、时间刷新和工作区蒸馏现在都是同一迭代契约中的内部工作项。

旧 `/snapshots/:snapshotId/risks` 与 `/projects/:projectId/risks` 路径只用于书签兼容，并重定向到 `/snapshots/:snapshotId/iterate`。旧 `/api/risk-runs` 暂时保留给历史运行读取；新产品入口使用 `/api/snapshot-iterations`。
