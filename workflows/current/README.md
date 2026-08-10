# workflows/current 工作流清单与版本锁定（2026-08-05）

## 版本锁定结论

**仅保留当前接入 API（已配置 Flow ID / 有调用方）的工作流 4 个**。已删除：v4 历史版本（`连续学习个性化讲解工作流_v4.yml`、`测验后个性化错误讲解工作流_v4.yml`）、`history/` 目录（v2/v3），以及未接入 API 的工作流（`个性化推荐工作流.yml`、`目标与路径规划工作流.yml`、`对话问答工作流.yml`、`测评出题工作流.yml`——无 Flow ID 配置、无 `/api/workflows/*` 路由、无调用方与运行记录，后端 `invoke_*` 为预留实现，未配置时返回本地 mock）。

| 文件 | 状态 | 对应配置 |
| --- | --- | --- |
| `自定义621d71_v5.yml` | ✅ 在用（统一发布版） | 总回退 `XINGCHEN_FLOW_ID`；统一"学习/换种讲法/测验纠错"入口，支持追问恢复（resume_token + clarification_reply）；输入为 unified scene contract：`scene` + `workflow_mode` + `event_type` 自动路由 |
| `学习阶段个性化讲解工作流_v5.yml` | ✅ 在用 | `XINGCHEN_LEARNING_FLOW_ID`；8 类 content_blocks（connection/concept/steps/example/pitfall/workplace/check/notice），校验已放宽纯 items/steps 块 |
| `测验后个性化纠错讲解工作流_v5.yml` | ✅ 在用 | `XINGCHEN_REMEDIATION_FLOW_ID`；纠错流程（717 行，子流程/精简定义） |
| `学生画像分析工作流.yml` | ✅ 在用 | `XINGCHEN_PROFILE_FLOW_ID`；画像分析 |

## 对接约束（后端 ↔ 工作流）

- 后端 `_learning_workflow_payload` / `_remediation_workflow_payload` 传 unified scene contract（context 含 `scene`/`workflow_mode`/`event_type`/`route_type`），621d71 据此路由。
- content_blocks 类型以 v5 8 类为准，v4 别名由前端渲染器兼容（`items`/`steps` 均渲染为步骤列表）。
- SSE 讲解流：`GET /api/explanations/{id}/stream`，事件 `status/section/done/error`（回放式，非实时生成）。

## resume 令牌（已知风险）

- 621d71 的 resume_token 为 **zlib+base64 自包含**格式（无签名、无过期）。
- 后端已做**身份绑定校验**（`_inspect_workflow_resume_token`：内嵌 student_id/session_id 与请求不符 → 403 INVALID_RESUME_TOKEN）。
- **完整性保护（HMAC）需在工作流侧实现**：在 `_encode_resume` 中追加带密钥的签名段，密钥由后端/平台下发。改完需重新发布星辰平台并同步 `backend/.env` 的 Flow ID。
