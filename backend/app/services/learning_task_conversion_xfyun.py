"""Server-owned Xingchen workflow adapter for learning-task generation.

The browser and plugin package never receive provider credentials.  This
module invokes one fixed, operator-configured Xingchen workflow, resolves its
versioned WF03 delivery bundle, and converts that bundle into the structured
candidate consumed by the generic Plugin Host.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

import httpx
from dotenv import dotenv_values
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.core.config import settings


class XingchenWorkflowConfigError(RuntimeError):
    """Raised when the feature-private Xingchen configuration is unavailable."""


class XingchenWorkflowError(RuntimeError):
    """Normalized provider or WF03 delivery failure."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class XingchenTaskStructureError(XingchenWorkflowError):
    """A provider task card or compiled plan failed a local structure gate."""

    def __init__(self, path: str, reason: str):
        self.path = str(path or "$")[:240]
        self.reason = re.sub(r"\s+", " ", str(reason or "结构不符合约束")).strip()[:500]
        super().__init__(f"{self.path}：{self.reason}")


@dataclass(frozen=True)
class XingchenWorkflowCredentials:
    app_id: str
    api_key: str
    api_secret: str
    flow_id: str
    base_url: str = "https://xingchen-api.xf-yun.com"
    timeout_seconds: float = 240.0


def default_credentials_path() -> Path:
    configured = str(settings.learning_task_xfyun_credentials_path or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / ".private" / "learning_task_conversion.xfyun.env"


def load_xingchen_credentials(
    path: str | Path | None = None,
) -> XingchenWorkflowCredentials:
    credential_path = Path(path).expanduser() if path is not None else default_credentials_path()
    if not credential_path.is_file():
        raise XingchenWorkflowConfigError(
            f"学习型任务讯飞工作流私密配置不存在: {credential_path}"
        )
    values: Mapping[str, str | None] = dotenv_values(credential_path)
    required = {
        "XFYUN_APP_ID": values.get("XFYUN_APP_ID"),
        "XFYUN_API_KEY": values.get("XFYUN_API_KEY"),
        "XFYUN_API_SECRET": values.get("XFYUN_API_SECRET"),
        "XFYUN_FLOW_ID": values.get("XFYUN_FLOW_ID"),
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise XingchenWorkflowConfigError(
            "学习型任务讯飞工作流私密配置缺少: " + ", ".join(missing)
        )
    try:
        timeout_seconds = float(values.get("XFYUN_WORKFLOW_TIMEOUT_SECONDS") or 240.0)
    except (TypeError, ValueError) as exc:
        raise XingchenWorkflowConfigError(
            "XFYUN_WORKFLOW_TIMEOUT_SECONDS 必须为数字"
        ) from exc
    return XingchenWorkflowCredentials(
        app_id=str(required["XFYUN_APP_ID"]).strip(),
        api_key=str(required["XFYUN_API_KEY"]).strip(),
        api_secret=str(required["XFYUN_API_SECRET"]).strip(),
        flow_id=str(required["XFYUN_FLOW_ID"]).strip(),
        base_url=str(
            values.get("XFYUN_WORKFLOW_BASE_URL")
            or "https://xingchen-api.xf-yun.com"
        ).rstrip("/"),
        timeout_seconds=max(1.0, min(timeout_seconds, 600.0)),
    )


class XingchenLearningTaskWorkflowClient:
    """Invoke only the published WF03 learning-task Plan workflow."""

    _CONNECT_ATTEMPTS = 3

    def __init__(
        self,
        *,
        credentials: XingchenWorkflowCredentials | None = None,
        credentials_path: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials or load_xingchen_credentials(credentials_path)
        self.transport = transport

    async def run(self, user_input: str, *, uid: str) -> dict[str, Any]:
        query = str(user_input or "").strip()
        if not query:
            raise XingchenWorkflowError("真实工作任务不能为空", status_code=422)
        payload = {
            "flow_id": self.credentials.flow_id,
            "uid": str(uid)[:40],
            "parameters": {"AGENT_USER_INPUT": query},
            "ext": {
                "bot_id": "workflow",
                "caller": "learnflow-learning-task-plugin",
            },
            "stream": False,
        }
        headers = {
            "Authorization": (
                f"Bearer {self.credentials.api_key}:{self.credentials.api_secret}"
            ),
            "Content-Type": "application/json",
        }
        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            base_url=self.credentials.base_url,
            timeout=self.credentials.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            for attempt in range(self._CONNECT_ATTEMPTS):
                try:
                    response = await client.post(
                        "/workflow/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    if attempt == self._CONNECT_ATTEMPTS - 1:
                        raise XingchenWorkflowError(
                            "讯飞星辰工作流连接失败，请检查网络后重试"
                        ) from exc
                    await asyncio.sleep(0.25 * (2 ** attempt))
                except httpx.TimeoutException as exc:
                    raise XingchenWorkflowError(
                        "讯飞星辰工作流响应超时", status_code=504
                    ) from exc
                except httpx.HTTPError as exc:
                    raise XingchenWorkflowError("讯飞星辰工作流请求失败") from exc
        if response is None:
            raise XingchenWorkflowError("讯飞星辰工作流未返回响应")
        if response.status_code >= 400:
            raise XingchenWorkflowError(
                f"讯飞星辰工作流返回 {response.status_code}: "
                f"{response.text.strip()[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise XingchenWorkflowError("讯飞星辰工作流返回了无效 JSON") from exc
        if not isinstance(data, dict):
            raise XingchenWorkflowError("讯飞星辰工作流返回值必须是 JSON 对象")
        if data.get("code") != 0:
            raise XingchenWorkflowError(
                f"讯飞星辰工作流执行失败({data.get('code')}): "
                f"{data.get('message') or '未知错误'}"
            )
        choices = data.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        delta = first.get("delta") if isinstance(first, dict) else None
        content = delta.get("content") if isinstance(delta, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise XingchenWorkflowError("讯飞星辰工作流响应缺少最终内容")
        return {
            "protocol": "learnflow.xingchen-learning-task-run.v1",
            "provider": "xunfei-xingchen",
            "app_id": self.credentials.app_id,
            "flow_id": self.credentials.flow_id,
            "run_id": str(data.get("id") or ""),
            "content": content,
            "usage": data.get("usage") or {},
        }


def task_card_id_from_content(content: str) -> str:
    patterns = (
        r"/learning-task-conversion/tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r"/learning-tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r'"task_card_id"\s*:\s*"(ltc_[A-Za-z0-9_-]{1,96})"',
    )
    for pattern in patterns:
        match = re.search(pattern, str(content or ""))
        if match:
            return match.group(1)
    return ""


def targeted_patch_from_content(content: str) -> dict[str, Any] | None:
    """Extract the workflow's structured publish-gate repair response."""

    source = str(content or "")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", source):
        try:
            value, _ = decoder.raw_decode(source[match.start():])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and value.get("schema_version")
            == "learning-work-task-targeted-patch-v1"
        ):
            return value
    return None


def _repair_workflow_input(task_title: str, patch: Mapping[str, Any]) -> str:
    def safe_line(value: Any, limit: int = 320) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    hard_errors = [
        safe_line(item) for item in list(patch.get("hard_errors") or [])
        if safe_line(item)
    ]
    required_objects: list[str] = []
    for error in hard_errors:
        required_objects.extend(
            item.strip() for item in re.findall(r"任务对象“([^”]+)”", error)
            if item.strip()
        )
    required_line = safe_line("、".join(dict.fromkeys(required_objects)) or task_title, 140)
    prompt = (
        f"真实工作任务：{safe_line(task_title, 160)}\n"
        f"固定对象锚点：{required_line}。"
        "task_name、task_description必须逐字包含该锚点；至少一个workflow_steps的name、action或deliverable也必须逐字包含。"
        "生成并发布完整学习型工作任务。每步写明动作、对象、方法、可观察产物、检查方法、知识点和技能点。"
        "完成全部内部校验并返回已发布任务卡链接。"
    )
    return prompt[:500]


def _schema_failure(
    value: Any,
    schema: Mapping[str, Any],
) -> tuple[str, str] | None:
    try:
        Draft202012Validator.check_schema(dict(schema))
        error = next(Draft202012Validator(dict(schema)).iter_errors(value), None)
    except SchemaError as exc:
        raise XingchenWorkflowError("学习型任务插件的结构契约无效") from exc
    if error is None:
        return None
    location = "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in error.absolute_path
    )
    return location, _schema_failure_reason(error)


def _schema_failure_reason(error: ValidationError) -> str:
    if error.validator == "minItems":
        return f"至少需要 {error.validator_value} 项，实际只有 {len(error.instance) if isinstance(error.instance, list) else 0} 项"
    if error.validator == "maxItems":
        return f"最多允许 {error.validator_value} 项"
    if error.validator == "required":
        missing = [
            str(item) for item in list(error.validator_value or [])
            if isinstance(error.instance, Mapping) and item not in error.instance
        ]
        return "缺少必填字段 " + "、".join(missing[:8])
    if error.validator == "type":
        return f"字段类型必须为 {error.validator_value}"
    if error.validator == "additionalProperties":
        return "包含契约未允许的额外字段"
    return re.sub(r"\s+", " ", str(error.message or "结构不符合约束")).strip()[:500]


def _schema_repair_workflow_input(task_title: str, path: str, reason: str) -> str:
    safe_path = path if re.fullmatch(r"\$(?:\.[A-Za-z0-9_-]+|\[\d+\]){0,12}", path) else "$"
    safe_reason = re.sub(r"\s+", " ", str(reason or "结构不符合约束")).strip()[:180]
    prompt = (
        f"真实工作任务：{re.sub(r'\s+', ' ', task_title).strip()[:180]}\n"
        f"结构要求：{safe_path}：{safe_reason}。"
        "生成并发布完整学习型工作任务，保留原始任务对象。"
        "每个步骤包含动作、对象、方法、可观察产物、验收依据、知识点和技能点。"
        "完成全部内部校验并返回已发布任务卡链接。"
    )
    return prompt[:500]


class LearningTaskBundleGateway:
    """Resolve and validate the fixed WF03 artifact service contract."""

    _READ_ATTEMPTS = 6
    _TRANSIENT_STATUSES = {404, 429, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = str(
            base_url or settings.learning_task_conversion_base_url
        ).rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else settings.learning_task_conversion_timeout_seconds
        )
        self.transport = transport

    async def task_bundle(self, task_card_id: str) -> dict[str, Any]:
        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            for attempt in range(self._READ_ATTEMPTS):
                try:
                    response = await client.get(
                        f"/api/v1/learning-task-conversion/tasks/{task_card_id}/bundle"
                    )
                except httpx.TimeoutException as exc:
                    if attempt == self._READ_ATTEMPTS - 1:
                        raise XingchenWorkflowError(
                            "讯飞任务包服务响应超时", status_code=504,
                        ) from exc
                except httpx.HTTPError as exc:
                    if attempt == self._READ_ATTEMPTS - 1:
                        raise XingchenWorkflowError("讯飞任务包服务连接失败") from exc
                else:
                    if response.status_code not in self._TRANSIENT_STATUSES:
                        break
                    if attempt == self._READ_ATTEMPTS - 1:
                        break
                await asyncio.sleep(0.2 * (2 ** attempt))
        if response is None:
            raise XingchenWorkflowError("讯飞任务包服务未返回响应")
        if response.status_code >= 400:
            raise XingchenWorkflowError(
                f"讯飞任务包服务返回 {response.status_code}: "
                f"{response.text.strip()[:500]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise XingchenWorkflowError("讯飞任务包服务返回了无效 JSON") from exc
        return validate_task_bundle(payload, task_card_id)


def validate_task_bundle(payload: Any, task_card_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise XingchenTaskStructureError("$", "讯飞任务包必须是 JSON 对象")
    if payload.get("schema_version") != "learning-task-conversion-integration-bundle-v1":
        raise XingchenTaskStructureError("$.schema_version", "不支持的讯飞任务包契约版本")
    if payload.get("task_card_id") != task_card_id:
        raise XingchenTaskStructureError("$.task_card_id", "讯飞任务包 ID 与工作流输出不一致")
    task = payload.get("task")
    work_task = task.get("work_task") if isinstance(task, dict) else None
    if not isinstance(work_task, dict):
        raise XingchenTaskStructureError("$.task.work_task", "缺少 work_task 对象")
    steps = work_task.get("task_steps")
    if not isinstance(steps, list) or not steps:
        raise XingchenTaskStructureError("$.task.work_task.task_steps", "缺少任务步骤")
    knowledge_ids = {
        str(item.get("knowledge_id"))
        for item in list(work_task.get("knowledge_points") or [])
        if isinstance(item, dict) and item.get("knowledge_id")
    }
    skill_ids = {
        str(item.get("skill_id"))
        for item in list(work_task.get("skill_points") or [])
        if isinstance(item, dict) and item.get("skill_id")
    }
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise XingchenTaskStructureError(f"$.task.work_task.task_steps[{index - 1}]", "步骤必须是对象")
        if any(not str(step.get(key) or "").strip() for key in ("step_id", "action", "deliverable", "check")):
            raise XingchenTaskStructureError(f"$.task.work_task.task_steps[{index - 1}]", "步骤字段不完整")
        step_knowledge = {str(value) for value in list(step.get("knowledge_point_ids") or [])}
        step_skills = {str(value) for value in list(step.get("skill_point_ids") or [])}
        if not step_knowledge or not step_skills:
            raise XingchenTaskStructureError(f"$.task.work_task.task_steps[{index - 1}]", "步骤缺少知识或技能映射")
        if step_knowledge - knowledge_ids or step_skills - skill_ids:
            raise XingchenTaskStructureError(f"$.task.work_task.task_steps[{index - 1}]", "步骤存在悬空映射")
    return payload


def _text_list(value: Any) -> list[str]:
    output: list[str] = []
    for item in list(value or []):
        if isinstance(item, dict):
            text = str(
                item.get("criterion")
                or item.get("check")
                or item.get("description")
                or item.get("name")
                or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            output.append(text)
    return output


def plan_from_task_bundle(bundle: Mapping[str, Any], fallback_title: str) -> dict[str, Any]:
    """Convert a validated WF03 delivery into the plugin's structured plan."""

    task_envelope = bundle.get("task")
    work_task = task_envelope.get("work_task") if isinstance(task_envelope, Mapping) else {}
    work_task = dict(work_task) if isinstance(work_task, Mapping) else {}
    knowledge_by_id = {
        str(item.get("knowledge_id")): dict(item)
        for item in list(work_task.get("knowledge_points") or [])
        if isinstance(item, Mapping) and item.get("knowledge_id")
    }
    skills_by_id = {
        str(item.get("skill_id")): dict(item)
        for item in list(work_task.get("skill_points") or [])
        if isinstance(item, Mapping) and item.get("skill_id")
    }
    steps: list[dict[str, Any]] = []
    for index, source in enumerate(list(work_task.get("task_steps") or []), start=1):
        if not isinstance(source, Mapping):
            continue
        knowledge_items = [
            knowledge_by_id[item_id]
            for item_id in (str(value) for value in list(source.get("knowledge_point_ids") or []))
            if item_id in knowledge_by_id
        ]
        skill_items = [
            skills_by_id[item_id]
            for item_id in (str(value) for value in list(source.get("skill_point_ids") or []))
            if item_id in skills_by_id
        ]
        first_knowledge = knowledge_items[0] if knowledge_items else {}
        first_skill = skill_items[0] if skill_items else {}
        steps.append({
            "external_id": str(source.get("step_id") or f"step_{index:02d}"),
            "title": str(source.get("name") or source.get("title") or source.get("action") or f"步骤 {index}"),
            "operation": str(source.get("action") or source.get("operation") or ""),
            "deliverable": str(source.get("deliverable") or ""),
            "acceptance": str(source.get("check") or source.get("acceptance") or ""),
            "knowledge": str(first_knowledge.get("name") or "本步骤相关知识"),
            "skill": str(first_skill.get("name") or first_skill.get("observable_action") or "本步骤实施技能"),
            "knowledge_items": knowledge_items,
            "skill_items": skill_items,
            "prerequisites": _text_list(source.get("prerequisites")),
            "safety": str(source.get("safety") or ""),
        })
    acceptance = _text_list(work_task.get("acceptance_tests"))
    if not acceptance:
        acceptance = [str(item.get("acceptance") or "") for item in steps if item.get("acceptance")]
    title = str(
        work_task.get("teaching_task_name")
        or work_task.get("enterprise_task_name")
        or fallback_title
    ).strip()
    objective = str(
        work_task.get("teaching_task_description")
        or work_task.get("enterprise_task_description")
        or f"完成“{fallback_title}”并提交可检查成果。"
    ).strip()
    return {
        "title": title,
        "context": str(
            work_task.get("work_situation")
            or work_task.get("enterprise_task_description")
            or objective
        ).strip(),
        "objective": objective,
        "tools": _text_list(work_task.get("tools")) or ["任务要求的实训工具与环境"],
        "safety": _text_list(work_task.get("safety_points")) or ["遵守任务现场与工具安全边界"],
        "acceptance": acceptance or ["各步骤产物与验收记录完整可复核"],
        "steps": steps,
    }


async def generate_xingchen_learning_task(
    task_title: str,
    *,
    uid: str,
    workflow_client: XingchenLearningTaskWorkflowClient | None = None,
    bundle_gateway: LearningTaskBundleGateway | None = None,
    plan_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    client = workflow_client or XingchenLearningTaskWorkflowClient()
    gateway = bundle_gateway or LearningTaskBundleGateway()
    run = await client.run(task_title, uid=uid)
    workflow_run_ids: list[str] = []
    repair_reasons: list[str] = []
    prior_patch: Mapping[str, Any] | None = None
    while True:
        workflow_run_ids.append(str(run.get("run_id") or ""))
        content = str(run.get("content") or "")
        task_card_id = task_card_id_from_content(content)
        patch = targeted_patch_from_content(content)
        if patch is not None:
            prior_patch = patch
        if not task_card_id:
            hard_errors = [
                str(item).strip() for item in list((patch or prior_patch or {}).get("hard_errors") or [])
                if str(item).strip()
            ]
            if patch is not None and "publish_gate" not in repair_reasons:
                repair_reasons.append("publish_gate")
                run = await client.run(
                    _repair_workflow_input(task_title, patch),
                    uid=f"{uid[:24]}-publish-repair",
                )
                continue
            if hard_errors:
                raise XingchenWorkflowError(
                    "讯飞工作流候选未通过发布门禁"
                    + ("，自动修订后仍未发布：" if "publish_gate" in repair_reasons else "：")
                    + "；".join(hard_errors[:4])
                )
            raise XingchenWorkflowError(
                "讯飞工作流已完成，但没有返回可解析的任务卡 ID"
            )

        try:
            bundle = await gateway.task_bundle(task_card_id)
            plan = plan_from_task_bundle(bundle, task_title)
            failure = _schema_failure(plan, plan_schema) if plan_schema is not None else None
            if failure is not None:
                raise XingchenTaskStructureError(*failure)
        except XingchenTaskStructureError as exc:
            if "structure_schema" not in repair_reasons:
                repair_reasons.append("structure_schema")
                run = await client.run(
                    _schema_repair_workflow_input(task_title, exc.path, exc.reason),
                    uid=f"{uid[:24]}-schema-repair",
                )
                continue
            raise XingchenWorkflowError(
                f"讯飞任务结构自动修订后仍未通过：{exc.path}：{exc.reason}"
            ) from exc

        return {
            "protocol": "learnflow.xingchen-learning-task-generation.v1",
            "provider": "xunfei-xingchen",
            "workflow_run_id": str(run.get("run_id") or ""),
            "workflow_run_ids": [item for item in workflow_run_ids if item],
            "repair_attempted": bool(repair_reasons),
            "repair_reasons": repair_reasons,
            "task_card_id": task_card_id,
            "verification_status": str(bundle.get("verification_status") or ""),
            "usage": dict(run.get("usage") or {}),
            "plan": plan,
        }


__all__ = [
    "LearningTaskBundleGateway",
    "XingchenLearningTaskWorkflowClient",
    "XingchenWorkflowConfigError",
    "XingchenWorkflowCredentials",
    "XingchenWorkflowError",
    "XingchenTaskStructureError",
    "generate_xingchen_learning_task",
    "load_xingchen_credentials",
    "plan_from_task_bundle",
    "task_card_id_from_content",
    "targeted_patch_from_content",
    "validate_task_bundle",
]
