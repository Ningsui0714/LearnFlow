# Teaching Delivery 与学习视频 Harness

## 目标与落层

本能力解决两个问题：教学生成失败时不能“什么都没有”；视频推荐不能只看标题和热度。它不新增主 Agent、Skill、数据库表或学习者状态。

```text
Checkpoint.learning_contract
  -> teaching_contract_gate
  -> ready | ready_with_gaps | fallback_ready
  -> Lecture（始终至少有一个答案安全小节）

既有 Source / Lecture / Practice / Assessment / LearningTask
  -> checkpoint_delivery_readiness（读取时重建）
  -> outline_only ... verification_ready

学习目标
  -> search_learning_videos（discovered）
  -> inspect_learning_video（content_inspected | metadata_only）
  -> learning_resource_curation 给出候选建议
```

## Teaching Contract v1

权威仍是 `Checkpoint.learning_contract`。新字段为：

- `schema_version`
- `objective`
- `outcomes`
- `must_preserve`
- `avoid`
- `source_refs`

旧 `exit_criteria`、`knowledge_target`、`practice_target` 等字段原样保留。门禁只把 scope 越界、答案泄露、非法来源引用和不可解析结构视为硬错误；缺少来源或保留事实只是 gap。模型最多修订一次，随后由代码生成目标、核心事实、最小示例、下一步与缺口说明。降级讲解明确 `mastery_inference=false`。

## Delivery readiness

成熟度不是学习进度。它在读取 Checkpoint 时从既有对象重建，并放进响应中的 `learning_contract.delivery_readiness`：

1. `outline_only`
2. `content_ready`
3. `guided_learning_ready`
4. `practice_ready`
5. `verification_ready`

来源、内容、任务、练习、确定性答案契约、AssessmentBlueprint 和 Rubric 均有独立 gap。删除投影或重建数据库不会损失学习事实。

## 视频 ACI 与 Harness

模型只看两个目标级接口：

- `search_learning_videos(target, goal, level, language, max_duration_minutes, platforms, max_results)`
- `inspect_learning_video(candidate_id, query, outcomes, max_segments)`

第二个接口只接受本轮搜索返回的 candidate ID。Bilibili/YouTube 搜索、元数据读取、字幕抓取和离线 seeded catalog 是 Harness 内部机制。没有字幕或 ASR 时返回 `metadata_only + asr_required`，不得把元数据相关性写成内容覆盖。字幕片段显式带开始/结束秒数，输出同时列出 outcome gap 和 answer-leak risk。

所有接口只读、无需确认、零 Kernel target。若以后接入音频 ASR，仍只能补充资源核验，不得直接生成 LearningAttempt 或掌握状态。

## 兼容与降级

- 无数据库迁移；历史 Checkpoint 在读取时规范化。
- 离线评测通过显式 fake adapter 注入固定候选；生产环境无网络时返回 empty，而不是伪造链接或把评测数据展示给学习者。
- 未配置 `YOUTUBE_API_KEY` 时 YouTube 实时搜索返回 `not_configured`；Bilibili 失败不阻断其他 provider。
- 正式学习验证仍唯一走 `LearningAttempt -> EvidenceEvent -> five_kernel_reducer`。
