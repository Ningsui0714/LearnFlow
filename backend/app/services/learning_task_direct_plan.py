"""Direct, auditable Plan fallback for learning-work-task generation.

Xingchen remains the primary workflow entry.  When a published Xingchen tool
version is temporarily unavailable, this adapter executes the same deployed
WF03 contract -> Plan -> evidence -> candidate -> Critic -> commit endpoints
directly.  The content model is allowed to draft only the candidate object;
identity locking, evidence checkpoints, review gates, versioning and artifact
publication remain owned by the deployed Plan service.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


class LearningTaskDirectPlanError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ContentModelConfig:
    api_base: str
    api_key: str
    model: str
    timeout_seconds: float
    max_tokens: int
    temperature: float


def _dotenv_values(path: Path) -> dict[str, str]:
    """Read the small ignored integration env without mutating process env."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _content_model_config() -> ContentModelConfig:
    # Local competition runs already keep their content-provider credentials
    # in this ignored WF04 integration file.  Environment variables always win
    # in deployments; reading the sibling file only preserves the existing
    # single-machine setup and never sends the credential to the browser.
    repo_root = Path(__file__).resolve().parents[3]
    local_values = _dotenv_values(repo_root / "integrations/wf04/backend/.env")

    def value(name: str, default: str) -> str:
        return str(os.getenv(name) or local_values.get(name) or default).strip()

    try:
        timeout_seconds = float(value("CONTENT_LLM_TIMEOUT", "90"))
        configured_max_tokens = int(value("CONTENT_LLM_MAX_TOKENS", "5200"))
        temperature = float(value("CONTENT_LLM_TEMPERATURE", "0.25"))
    except ValueError as exc:
        raise LearningTaskDirectPlanError("内容模型数值配置无效", status_code=500) from exc
    return ContentModelConfig(
        api_base=value(
            "CONTENT_LLM_API_BASE",
            "https://api.deepseek.com/chat/completions",
        ),
        api_key=value("CONTENT_LLM_API_KEY", ""),
        model=value("CONTENT_LLM_MODEL", "deepseek-v4-flash"),
        timeout_seconds=max(10.0, min(timeout_seconds, 180.0)),
        # Structured candidates include task metadata, 5-8 step records,
        # mappings and acceptance tests.  Reasoning-capable providers may count
        # hidden reasoning in this same budget, so 4200 can still truncate the
        # visible JSON.  Keep enough room for a complete compact candidate.
        max_tokens=max(7200, min(configured_max_tokens, 10000)),
        temperature=max(0.0, min(temperature, 0.8)),
    )


def _json_document(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.S | re.I)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(stripped)
    brace = stripped.find("{")
    if brace >= 0:
        candidates.append(stripped[brace:])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate)
            except (TypeError, ValueError):
                continue
        if isinstance(value, dict):
            return value
    raise LearningTaskDirectPlanError("内容模型未返回合法的任务候选 JSON")


def _string_list(value: Any, *, field: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list):
        raise LearningTaskDirectPlanError(f"任务候选字段 {field} 必须是数组")
    result = [str(item).strip() for item in value if str(item).strip()]
    if len(result) < minimum:
        raise LearningTaskDirectPlanError(f"任务候选字段 {field} 内容不足")
    return result


def _normalize_candidate(
    candidate: dict[str, Any],
    task_contract: dict[str, Any],
) -> dict[str, Any]:
    required_text = ("task_name", "task_description", "task_scenario")
    for field in required_text:
        if not str(candidate.get(field) or "").strip():
            raise LearningTaskDirectPlanError(f"任务候选缺少 {field}")

    task_object = str(task_contract.get("object") or "").strip()
    task_name = str(candidate["task_name"]).strip()
    if task_object and task_object not in task_name:
        task_name = f"{task_object}{task_name}"

    knowledge_points = _string_list(
        candidate.get("knowledge_points"), field="knowledge_points", minimum=3,
    )
    skill_points = _string_list(
        candidate.get("skill_points"), field="skill_points", minimum=3,
    )
    tools = _string_list(candidate.get("tools"), field="tools")

    raw_steps = candidate.get("workflow_steps")
    if not isinstance(raw_steps, list) or not 5 <= len(raw_steps) <= 8:
        raise LearningTaskDirectPlanError("任务候选必须包含 5 至 8 个真实作业步骤")
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise LearningTaskDirectPlanError("任务候选步骤必须是 JSON 对象")
        step: dict[str, Any] = {
            "step_id": f"step_{index:02d}",
            "name": str(raw_step.get("name") or "").strip(),
            "action": str(raw_step.get("action") or "").strip(),
            "deliverable": str(raw_step.get("deliverable") or "").strip(),
            "check": str(raw_step.get("check") or "").strip(),
            "knowledge_points": _string_list(
                raw_step.get("knowledge_points"),
                field=f"workflow_steps[{index}].knowledge_points",
            ),
            "skill_points": _string_list(
                raw_step.get("skill_points"),
                field=f"workflow_steps[{index}].skill_points",
            ),
            "evidence_refs": ["upstream_task_contract"],
        }
        for field in ("name", "action", "deliverable", "check"):
            if not step[field]:
                raise LearningTaskDirectPlanError(
                    f"任务候选第 {index} 步缺少 {field}"
                )
        steps.append(step)

    acceptance_tests = candidate.get("acceptance_tests")
    if not isinstance(acceptance_tests, list) or len(acceptance_tests) < 2:
        raise LearningTaskDirectPlanError("任务候选缺少可核验的总体验收测试")
    safety_points = _string_list(
        candidate.get("safety_points"), field="safety_points", minimum=2,
    )
    assessment = candidate.get("assessment")
    if not isinstance(assessment, dict) or not assessment:
        raise LearningTaskDirectPlanError("任务候选缺少 assessment")

    return {
        "task_name": task_name,
        "task_description": str(candidate["task_description"]).strip(),
        "task_scenario": str(candidate["task_scenario"]).strip(),
        "knowledge_points": knowledge_points,
        "skill_points": skill_points,
        "tools": tools,
        "workflow_steps": steps,
        "acceptance_tests": acceptance_tests,
        "assessment": assessment,
        "safety_points": safety_points,
        # This fallback has only the confirmed upstream task contract.  It does
        # not present model recall as an independently verified web source.
        "sources": ["upstream_task_contract"],
        "task_ir_fingerprint": str(
            task_contract.get("semantic_fingerprint") or ""
        ),
    }


class LearningTaskDirectPlanGenerator:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        content_config: ContentModelConfig | None = None,
        plan_transport: httpx.AsyncBaseTransport | None = None,
        content_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or settings.learning_task_conversion_base_url
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or max(
            settings.learning_task_conversion_timeout_seconds, 90.0,
        )
        self.content_config = content_config
        self.plan_transport = plan_transport
        self.content_transport = content_transport

    async def _post_plan(
        self,
        path: str,
        *,
        params: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.plan_transport,
            ) as client:
                response = await client.post(path, params=params, json=body)
        except httpx.HTTPError as exc:
            raise LearningTaskDirectPlanError(f"任务 Plan 服务不可用: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            status = response.status_code if response.status_code in {404, 409, 422} else 502
            raise LearningTaskDirectPlanError(
                f"任务 Plan 服务返回 {response.status_code}: {detail}",
                status_code=status,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise LearningTaskDirectPlanError("任务 Plan 服务返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise LearningTaskDirectPlanError("任务 Plan 服务返回值必须是 JSON 对象")
        return payload

    async def _draft_candidate(
        self,
        user_input: str,
        task_contract: dict[str, Any],
        *,
        repair_plan: dict[str, Any] | None = None,
        retry_hint: str = "",
        json_mode: bool = True,
    ) -> dict[str, Any]:
        config = self.content_config or _content_model_config()
        if not config.api_key:
            raise LearningTaskDirectPlanError(
                "内容模型未配置，无法为新任务生成候选步骤",
                status_code=503,
            )
        repair_instruction = ""
        if repair_plan:
            repair_instruction = (
                "\n这是 Critic 返回的定向修订要求。只修复涉及字段，保持任务对象与已正确步骤：\n"
                + json.dumps(repair_plan, ensure_ascii=False)
            )
        retry_instruction = ""
        if retry_hint:
            retry_instruction = (
                "\n上次输出未通过结构校验："
                f"{retry_hint[:240]}。请从头输出一个完整 JSON 对象，"
                "不要截断。为了保证完整性：固定输出5个步骤；任务简介和情境各不超过80字；"
                "每步action不超过100字，deliverable和check各不超过50字；"
                "知识点与技能点各3至5项；总体验收固定2项。逐项补齐所有字段。"
            )
        schema_example = {
            "task_name": "必须含契约中的任务对象",
            "task_description": "可执行任务简介",
            "task_scenario": "计算机专业实训或软件项目工作情境",
            "knowledge_points": ["知识点1", "知识点2", "知识点3"],
            "skill_points": ["技能点1", "技能点2", "技能点3"],
            "tools": ["软件或工具"],
            "workflow_steps": [{
                "step_id": "step_01",
                "name": "真实作业步骤名",
                "action": "明确到界面、文件、命令、参数或操作对象的动作",
                "deliverable": "可保存、截图、运行或检查的步骤产物",
                "check": "可观察、可记录或可测量的通过条件",
                "knowledge_points": ["本步骤真正使用的知识点"],
                "skill_points": ["本步骤可观察的技能点"],
                "evidence_refs": ["upstream_task_contract"],
            }],
            "acceptance_tests": [{
                "test_id": "AT-01",
                "test_description": "验收项",
                "test_steps": "具体测试动作",
                "expected_result": "可判定结果",
            }],
            "assessment": {
                "rubric": ["优秀：...", "合格：...", "待改进：..."],
                "weight_breakdown": {"实现": "60%", "测试与交付": "40%"},
            },
            "safety_points": ["数据、权限、环境或操作安全边界", "失败时停止条件"],
            "sources": ["upstream_task_contract"],
        }
        prompt = (
            "你是面向计算机专业群的学习型工作任务候选规划器。"
            "根据已锁定的任务契约，生成一项真实、连续、可执行、可验收的工作任务。"
            "不得改题，不得把步骤写成教材章节，不得使用工业机器人场景。"
            "必须生成5到8个有先后依赖的实际作业步骤；每步动作至少包含两个具体操作，"
            "同时给出可留存产物、可核验检查点、直接相关知识点和可观察技能点。"
            "若输入属于软件开发，应覆盖需求/环境、实现、调试、测试与版本交付，但按该任务真实流程命名。"
            "只返回一个JSON对象，不要Markdown，不要解释，也不要虚构已核验的网页来源。\n"
            f"用户任务：{user_input}\n"
            f"任务契约：{json.dumps(task_contract, ensure_ascii=False)}\n"
            f"严格输出结构：{json.dumps(schema_example, ensure_ascii=False)}"
            f"{repair_instruction}"
            f"{retry_instruction}"
        )
        body = {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "只输出严格JSON。所有内容必须保持任务契约中的对象、动作与交付边界。",
                },
                {"role": "user", "content": prompt},
            ],
            # A failed structured-output attempt is retried deterministically.
            "temperature": 0.1 if retry_hint else config.temperature,
            "max_tokens": config.max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(
                timeout=config.timeout_seconds,
                transport=self.content_transport,
            ) as client:
                response = await client.post(
                    config.api_base,
                    json=body,
                    headers={"Authorization": f"Bearer {config.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise LearningTaskDirectPlanError(f"内容模型服务不可用: {exc}") from exc
        if response.status_code >= 400:
            raise LearningTaskDirectPlanError(
                f"内容模型请求失败（HTTP {response.status_code}）"
            )
        try:
            result = response.json()
            choices = result.get("choices") if isinstance(result, dict) else None
            choice = choices[0]
            content = choice["message"]["content"]
            finish_reason = str(choice.get("finish_reason") or "")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LearningTaskDirectPlanError("内容模型响应缺少候选正文") from exc
        if finish_reason == "length":
            raise LearningTaskDirectPlanError("内容模型任务候选因长度限制被截断")
        return _normalize_candidate(_json_document(str(content)), task_contract)

    @staticmethod
    def _retryable_candidate_error(exc: LearningTaskDirectPlanError) -> bool:
        message = str(exc)
        return any(marker in message for marker in (
            "未返回合法的任务候选 JSON",
            "任务候选因长度限制被截断",
            "响应缺少候选正文",
            "任务候选字段",
            "任务候选缺少",
            "任务候选必须",
            "任务候选步骤必须",
            "任务候选第",
        ))

    async def _draft_candidate_with_retry(
        self,
        user_input: str,
        task_contract: dict[str, Any],
        *,
        repair_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Draft once, then make one low-temperature structured retry.

        JSON-mode incompatibility is also retried once without the optional
        response_format field, while retaining the strict JSON-only prompt.
        Network, authentication and quota failures are surfaced immediately.
        """

        try:
            return await self._draft_candidate(
                user_input,
                task_contract,
                repair_plan=repair_plan,
            )
        except LearningTaskDirectPlanError as exc:
            json_mode_unsupported = "请求失败（HTTP 400）" in str(exc)
            if not json_mode_unsupported and not self._retryable_candidate_error(exc):
                raise
            return await self._draft_candidate(
                user_input,
                task_contract,
                repair_plan=repair_plan,
                retry_hint=str(exc),
                json_mode=not json_mode_unsupported,
            )

    @staticmethod
    def _field(payload: dict[str, Any], name: str, default: Any) -> Any:
        value = payload.get(name)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return default
        return value if value is not None else default

    async def generate(self, user_input: str) -> dict[str, Any]:
        created = await self._post_plan(
            "/api/v1/learning-work-task-agent/xfyun/create",
            params={"user_query": user_input},
        )
        run_id = str(created.get("run_id") or "")
        if not run_id:
            raise LearningTaskDirectPlanError("任务 Plan 创建结果缺少 run_id")
        task_contract = self._field(created, "task_contract_json", {})
        plan = self._field(created, "plan_json", {})
        if not isinstance(task_contract, dict) or not isinstance(plan, dict):
            raise LearningTaskDirectPlanError("任务 Plan 契约或计划格式无效")

        # The create checkpoint owns v1.  Confirming the visible Plan is a new
        # versioned checkpoint, matching LearningTaskPlanGateway.confirm().
        confirmed_plan = dict(plan)
        try:
            confirmed_plan["plan_version"] = int(plan.get("plan_version") or 1) + 1
        except (TypeError, ValueError) as exc:
            raise LearningTaskDirectPlanError("Plan 版本号无效") from exc

        await self._post_plan(
            "/api/v1/learning-work-task-agent/xfyun/plan",
            params={
                "run_id": run_id,
                "plan_json": json.dumps(confirmed_plan, ensure_ascii=False),
            },
        )
        await self._post_plan(
            "/api/v1/learning-work-task-agent/xfyun/evidence",
            params={
                "run_id": run_id,
                "evidence_units_json": json.dumps([], ensure_ascii=False),
                "coverage_summary": (
                    "用户任务契约已锁定；候选中的具体步骤必须可执行、可观察、可验收。"
                ),
            },
        )

        candidate = await self._draft_candidate_with_retry(user_input, task_contract)
        reviewed = await self._post_plan(
            "/api/v1/learning-work-task-agent/xfyun/review",
            params={"run_id": run_id},
            # The Xfyun-compatible endpoint accepts the potentially large
            # candidate through a scalar wrapper.  Sending the candidate dict
            # itself makes the endpoint see an empty candidates_json value and
            # silently substitute its deterministic placeholder candidate.
            body={
                "run_id": run_id,
                "candidates_json": json.dumps([candidate], ensure_ascii=False),
            },
        )
        if reviewed.get("phase") == "PATCH_REQUIRED":
            patch_plan = self._field(reviewed, "patch_plan_json", {})
            candidate = await self._draft_candidate_with_retry(
                user_input,
                task_contract,
                repair_plan=patch_plan if isinstance(patch_plan, dict) else {},
            )
            reviewed = await self._post_plan(
                "/api/v1/learning-work-task-agent/xfyun/review",
                params={"run_id": run_id},
                body={
                    "run_id": run_id,
                    "candidates_json": json.dumps(
                        [candidate], ensure_ascii=False,
                    ),
                },
            )
        if reviewed.get("phase") != "COMMIT_READY":
            patch_plan = self._field(reviewed, "patch_plan_json", {})
            raise LearningTaskDirectPlanError(
                "新任务候选仍未通过 Plan Critic："
                + json.dumps(patch_plan, ensure_ascii=False)[:400],
                status_code=422,
            )

        committed = await self._post_plan(
            "/api/v1/learning-work-task-agent/xfyun/commit",
            params={"run_id": run_id},
        )
        if committed.get("phase") != "COMMITTED":
            raise LearningTaskDirectPlanError("任务 Plan 未完成提交")
        delivery = self._field(committed, "delivery_json", {})
        if not isinstance(delivery, dict):
            raise LearningTaskDirectPlanError("任务 Plan 交付包格式无效")
        task_card_id = str(delivery.get("task_card_id") or "")
        if not re.fullmatch(r"ltc_[A-Za-z0-9_-]{1,96}", task_card_id):
            raise LearningTaskDirectPlanError("任务 Plan 交付包缺少任务 ID")
        return {
            "schema_version": "learning-task-conversion-direct-plan-run-v1",
            "provider": "wf03-plan-direct-fallback",
            "run_id": run_id,
            "content": json.dumps(
                {"task_card_id": task_card_id}, ensure_ascii=False,
            ),
            "usage": {},
            "fallback": True,
        }
