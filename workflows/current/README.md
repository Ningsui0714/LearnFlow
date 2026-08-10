# workflows/current 工作流清单与版本锁定（2026-08-05）

## 版本锁定结论

**v5 是唯一正式契约**，v4 文件仅为历史参考，不再用于新开发与联调。

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `学习阶段个性化讲解工作流_v5.yml` | ✅ 正式 | 8 类 content_blocks（connection/concept/steps/example/pitfall/workplace/check/notice），校验已放宽纯 items/steps 块 |
| `自定义621d71_v5.yml` | ✅ 正式（统一发布版） | 统一"学习/换种讲法/测验纠错"入口，支持追问恢复（resume_token + clarification_reply）；输入为 unified scene contract：`scene` + `workflow_mode` + `event_type` 自动路由 |
| `测验后个性化纠错讲解工作流_v5.yml` | ✅ 正式 | 纠错流程（717 行，子流程/精简定义） |
| `学生画像分析工作流.yml` | ✅ 正式 | 画像分析 |
| `个性化推荐工作流.yml` / `目标与路径规划工作流.yml` | ✅ 正式 | 推荐与目标规划 |
| `连续学习个性化讲解工作流_v4.yml` | ⛔ 历史 | v4 11 类 BLOCK_TYPES，已被 v5 取代 |
| `测验后个性化错误讲解工作流_v4.yml` | ⛔ 历史 | v4 纠错，已被 v5 取代 |

## 对接约束（后端 ↔ 工作流）

- 后端 `_learning_workflow_payload` / `_remediation_workflow_payload` 传 unified scene contract（context 含 `scene`/`workflow_mode`/`event_type`/`route_type`），621d71 据此路由。
- content_blocks 类型以 v5 8 类为准，v4 别名由前端渲染器兼容（`items`/`steps` 均渲染为步骤列表）。
- SSE 讲解流：`GET /api/explanations/{id}/stream`，事件 `status/section/done/error`（回放式，非实时生成）。

## resume 令牌（已知风险）

- 621d71 的 resume_token 为 **zlib+base64 自包含**格式（无签名、无过期）。
- 后端已做**身份绑定校验**（`_inspect_workflow_resume_token`：内嵌 student_id/session_id 与请求不符 → 403 INVALID_RESUME_TOKEN）。
- **完整性保护（HMAC）需在工作流侧实现**：在 `_encode_resume` 中追加带密钥的签名段，密钥由后端/平台下发。改完需重新发布星辰平台并同步 `backend/.env` 的 Flow ID。
