"""Validated adapter for the岗位典型工作任务转化 service.

The remote Xingchen-backed service is an artifact producer, not a LearnFlow
state authority.  This gateway only calls fixed, server-configured paths and
checks the versioned handoff contracts before returning them to the API layer.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

import httpx

from app.core.config import settings


class LearningTaskConversionError(RuntimeError):
    """Normalized failure raised by the external workflow adapter."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class LearningTaskConversionGateway:
    XINGCHEN_CREATE_URL = (
        "https://xingchen-api.xf-yun.com/workflow/v1/async/chat/completions"
    )
    XINGCHEN_RESULT_URL = (
        "https://xingchen-api.xf-yun.com/workflow/v1/async/chat/result"
    )

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        xingchen_api_key: str | None = None,
        xingchen_api_secret: str | None = None,
        xingchen_flow_id: str | None = None,
        xingchen_uid: str | None = None,
        workflow_timeout_seconds: float | None = None,
        workflow_poll_interval_seconds: float = 1.0,
    ) -> None:
        configured_base = base_url or settings.learning_task_conversion_base_url
        self.base_url = configured_base.rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.learning_task_conversion_timeout_seconds
        )
        self.transport = transport
        self.xingchen_api_key = (
            settings.xingchen_api_key
            if xingchen_api_key is None
            else xingchen_api_key
        ).strip()
        self.xingchen_api_secret = (
            settings.xingchen_api_secret
            if xingchen_api_secret is None
            else xingchen_api_secret
        ).strip()
        self.xingchen_flow_id = (
            settings.xingchen_flow_id
            if xingchen_flow_id is None
            else xingchen_flow_id
        ).strip()
        self.xingchen_uid = (
            settings.xingchen_uid if xingchen_uid is None else xingchen_uid
        ).strip() or "learnflow-wf03"
        self.workflow_timeout_seconds = (
            settings.xingchen_workflow_timeout_seconds
            if workflow_timeout_seconds is None
            else workflow_timeout_seconds
        )
        self.workflow_poll_interval_seconds = workflow_poll_interval_seconds

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, json=payload)
        except httpx.TimeoutException as exc:
            raise LearningTaskConversionError(
                "岗位典型工作任务转化服务响应超时",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise LearningTaskConversionError(
                f"岗位典型工作任务转化服务不可用: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise LearningTaskConversionError(
                f"岗位典型工作任务转化服务返回 {response.status_code}: {detail}",
                status_code=502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LearningTaskConversionError(
                "岗位典型工作任务转化服务返回了无效 JSON"
            ) from exc
        if not isinstance(data, dict):
            raise LearningTaskConversionError(
                "岗位典型工作任务转化服务返回值必须是 JSON 对象"
            )
        return data

    async def capabilities(self) -> dict[str, Any]:
        payload = await self._request(
            "GET", "/api/v1/learning-task-conversion/capabilities"
        )
        if payload.get("schema_version") != "learning-task-conversion-capabilities-v1":
            raise LearningTaskConversionError("不支持的岗位任务转化能力契约版本")
        return payload

    async def generate_from_conversation(self, query: str) -> dict[str, Any]:
        """Run the published WF03 Xingchen workflow and resolve its task bundle."""

        if not all(
            (
                self.xingchen_api_key,
                self.xingchen_api_secret,
                self.xingchen_flow_id,
            )
        ):
            raise LearningTaskConversionError(
                "尚未配置讯飞星辰工作流 API，请在后端设置 "
                "XINGCHEN_API_KEY、XINGCHEN_API_SECRET 和 XINGCHEN_FLOW_ID",
                status_code=503,
            )

        headers = {
            "Authorization": (
                f"Bearer {self.xingchen_api_key}:{self.xingchen_api_secret}"
            ),
            "Content-Type": "application/json",
        }
        request_body = {
            "flow_id": self.xingchen_flow_id,
            "uid": self.xingchen_uid,
            "chat_id": uuid.uuid4().hex[:32],
            "parameters": {"AGENT_USER_INPUT": query},
        }
        deadline = time.monotonic() + self.workflow_timeout_seconds

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                created_response = await client.post(
                    self.XINGCHEN_CREATE_URL,
                    headers=headers,
                    json=request_body,
                )
                created_response.raise_for_status()
                created = self._validate_xingchen_response(
                    created_response.json(), "创建讯飞异步工作流"
                )
                execute_id = str((created.get("data") or {}).get("execute_id") or "")
                if not execute_id:
                    raise LearningTaskConversionError(
                        "讯飞工作流响应缺少 execute_id"
                    )

                while time.monotonic() < deadline:
                    result_response = await client.post(
                        self.XINGCHEN_RESULT_URL,
                        headers=headers,
                        json={"execute_id": execute_id},
                    )
                    result_response.raise_for_status()
                    result = self._validate_xingchen_response(
                        result_response.json(), "查询讯飞异步工作流"
                    )
                    data = result.get("data") or {}
                    status = str(data.get("status") or "").lower()
                    if status == "success":
                        content = str((data.get("output") or {}).get("content") or "")
                        task_card_id = self._task_card_id_from_output(content)
                        if not task_card_id:
                            raise LearningTaskConversionError(
                                "讯飞工作流已完成，但结果中没有可打开的学习型任务网页"
                            )
                        bundle = await self.task_bundle(task_card_id)
                        return {
                            "schema_version": "learnflow-wf03-generation-v1",
                            "execute_id": execute_id,
                            "status": status,
                            "task_card_id": task_card_id,
                            "message": content,
                            "usage": data.get("usage"),
                            "bundle": bundle,
                        }
                    if status == "interrupt":
                        raise LearningTaskConversionError(
                            "讯飞工作流需要补充输入，请完善任务描述后重试",
                            status_code=409,
                        )
                    if status in {"failed", "failure", "error", "cancelled"}:
                        raise LearningTaskConversionError(
                            f"讯飞工作流执行失败: {data.get('message') or status}"
                        )
                    await asyncio.sleep(self.workflow_poll_interval_seconds)
        except LearningTaskConversionError:
            raise
        except httpx.TimeoutException as exc:
            raise LearningTaskConversionError(
                "讯飞星辰 API 响应超时", status_code=504
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LearningTaskConversionError(
                f"讯飞星辰 API 不可用: {exc}"
            ) from exc

        raise LearningTaskConversionError(
            f"讯飞工作流在 {int(self.workflow_timeout_seconds)} 秒内未完成",
            status_code=504,
        )

    async def submit_upstream_handoff(
        self,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        if handoff.get("schema_version") != "competency-graph-learning-task-handoff-v1":
            raise LearningTaskConversionError(
                "上游岗位能力图谱交接契约版本不正确",
                status_code=422,
            )
        return await self._request(
            "POST",
            "/api/v1/learning-task-conversion/upstream-handoffs",
            payload=handoff,
        )

    async def task_bundle(self, task_card_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/api/v1/learning-task-conversion/tasks/{task_card_id}/bundle",
        )
        return self._validate_bundle(payload, task_card_id)

    async def personalized_learning_handoff(
        self,
        task_card_id: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            (
                "/api/v1/learning-task-conversion/tasks/"
                f"{task_card_id}/personalized-learning.json"
            ),
        )
        if payload.get("schema_version") != "learning-task-to-personalized-learning-v1":
            raise LearningTaskConversionError("不支持的个性化学习交付契约版本")
        work_task = payload.get("work_task")
        if not isinstance(work_task, dict) or not work_task.get("task_steps"):
            raise LearningTaskConversionError("个性化学习交付缺少工作任务步骤")
        return payload

    async def submit_downstream_feedback(
        self,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            feedback.get("schema_version")
            != "personalized-learning-to-task-conversion-feedback-v1"
        ):
            raise LearningTaskConversionError(
                "下游反馈契约版本不正确",
                status_code=422,
            )
        return await self._request(
            "POST",
            "/api/v1/learning-task-conversion/downstream-feedback",
            payload=feedback,
        )

    @staticmethod
    def _validate_xingchen_response(
        payload: Any,
        operation: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise LearningTaskConversionError(f"{operation}返回了无效 JSON")
        if payload.get("code") != 0:
            raise LearningTaskConversionError(
                f"{operation}失败: {payload.get('message') or payload.get('code')}"
            )
        return payload

    @staticmethod
    def _task_card_id_from_output(content: str) -> str:
        patterns = (
            r"/tasks/(ltc_[A-Za-z0-9_-]{1,96})/(?:interactive\.html|document\.pdf|personalized-learning\.json)",
            r'"task_card_id"\s*:\s*"(ltc_[A-Za-z0-9_-]{1,96})"',
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _validate_bundle(
        payload: dict[str, Any],
        task_card_id: str,
    ) -> dict[str, Any]:
        if (
            payload.get("schema_version")
            != "learning-task-conversion-integration-bundle-v1"
        ):
            raise LearningTaskConversionError("不支持的岗位任务转化集成包版本")
        if payload.get("task_card_id") != task_card_id:
            raise LearningTaskConversionError("岗位任务转化集成包的任务 ID 不一致")

        task = payload.get("task")
        if not isinstance(task, dict):
            raise LearningTaskConversionError("岗位任务转化集成包缺少个性化学习交付")
        if task.get("schema_version") != "learning-task-to-personalized-learning-v1":
            raise LearningTaskConversionError("个性化学习交付契约版本不正确")
        work_task = task.get("work_task")
        if not isinstance(work_task, dict):
            raise LearningTaskConversionError("个性化学习交付缺少 work_task")
        steps = work_task.get("task_steps")
        if not isinstance(steps, list) or not steps:
            raise LearningTaskConversionError("个性化学习交付缺少任务步骤")

        knowledge_ids = {
            str(item.get("knowledge_id"))
            for item in work_task.get("knowledge_points", [])
            if isinstance(item, dict) and item.get("knowledge_id")
        }
        skill_ids = {
            str(item.get("skill_id"))
            for item in work_task.get("skill_points", [])
            if isinstance(item, dict) and item.get("skill_id")
        }
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise LearningTaskConversionError(f"第 {index} 个任务步骤格式错误")
            required = ("step_id", "action", "deliverable", "check")
            if any(not str(step.get(key) or "").strip() for key in required):
                raise LearningTaskConversionError(f"第 {index} 个任务步骤字段不完整")
            step_knowledge = {str(value) for value in step.get("knowledge_point_ids", [])}
            step_skills = {str(value) for value in step.get("skill_point_ids", [])}
            if not step_knowledge or not step_skills:
                raise LearningTaskConversionError(
                    f"第 {index} 个任务步骤缺少知识点或技能点映射"
                )
            if step_knowledge - knowledge_ids or step_skills - skill_ids:
                raise LearningTaskConversionError(
                    f"第 {index} 个任务步骤引用了未定义的知识点或技能点"
                )
        return payload
