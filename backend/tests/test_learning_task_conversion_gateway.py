from __future__ import annotations

import json

import httpx
import pytest

from app.services.learning_task_conversion_gateway import (
    LearningTaskConversionError,
    LearningTaskConversionGateway,
)


def _bundle(task_card_id: str = "ltc_demo") -> dict:
    return {
        "schema_version": "learning-task-conversion-integration-bundle-v1",
        "task_card_id": task_card_id,
        "status": "ready",
        "verification_status": "verified",
        "task": {
            "schema_version": "learning-task-to-personalized-learning-v1",
            "work_task": {
                "work_task_id": "task_docker_01",
                "enterprise_task_name": "Docker 容器镜像构建、运行与验收",
                "task_steps": [
                    {
                        "step_id": "step_01",
                        "action": "编写 Dockerfile 并构建镜像",
                        "deliverable": "可复现的镜像构建记录",
                        "check": "镜像标签存在且构建命令退出码为 0",
                        "knowledge_point_ids": ["knowledge_01"],
                        "skill_point_ids": ["skill_01"],
                    }
                ],
                "knowledge_points": [
                    {"knowledge_id": "knowledge_01", "name": "镜像分层"}
                ],
                "skill_points": [
                    {"skill_id": "skill_01", "name": "构建容器镜像"}
                ],
            },
        },
        "strong_relationships": [],
        "artifacts": {},
    }


@pytest.mark.asyncio
async def test_gateway_accepts_valid_learning_task_bundle():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/tasks/ltc_demo/bundle")
        return httpx.Response(200, json=_bundle())

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.task_bundle("ltc_demo")
    assert result["task"]["work_task"]["task_steps"][0]["step_id"] == "step_01"


@pytest.mark.asyncio
async def test_gateway_rejects_dangling_step_relationships():
    invalid = _bundle()
    invalid["task"]["work_task"]["task_steps"][0]["knowledge_point_ids"] = [
        "missing_knowledge"
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid)

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskConversionError, match="未定义"):
        await gateway.task_bundle("ltc_demo")


@pytest.mark.asyncio
async def test_gateway_normalizes_remote_failures():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskConversionError, match="503") as failure:
        await gateway.capabilities()
    assert failure.value.status_code == 502


@pytest.mark.asyncio
async def test_gateway_runs_xingchen_workflow_and_resolves_bundle():
    task_card_id = "ltc_generated_01"
    poll_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path.endswith("/async/chat/completions"):
            assert request.headers["Authorization"] == "Bearer key:secret"
            body = json.loads(request.content)
            assert body["parameters"]["AGENT_USER_INPUT"] == "实现 REST API"
            return httpx.Response(200, json={"code": 0, "data": {"execute_id": "exec_1"}})
        if request.url.path.endswith("/async/chat/result"):
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"code": 0, "data": {"status": "running"}})
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "status": "success",
                        "output": {
                            "content": (
                                "[打开交互式任务页](https://example.test/api/v1/"
                                f"learning-task-conversion/tasks/{task_card_id}/interactive.html)"
                            )
                        },
                    },
                },
            )
        if request.url.path.endswith(f"/tasks/{task_card_id}/bundle"):
            return httpx.Response(200, json=_bundle(task_card_id))
        raise AssertionError(f"unexpected request: {request.url}")

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
        xingchen_api_key="key",
        xingchen_api_secret="secret",
        xingchen_flow_id="flow",
        workflow_poll_interval_seconds=0,
    )
    result = await gateway.generate_from_conversation("实现 REST API")
    assert result["task_card_id"] == task_card_id
    assert result["bundle"]["schema_version"] == "learning-task-conversion-integration-bundle-v1"


@pytest.mark.asyncio
async def test_gateway_requires_server_side_xingchen_credentials():
    gateway = LearningTaskConversionGateway(
        xingchen_api_key="",
        xingchen_api_secret="",
        xingchen_flow_id="",
    )
    with pytest.raises(LearningTaskConversionError, match="尚未配置") as failure:
        await gateway.generate_from_conversation("实现 REST API")
    assert failure.value.status_code == 503


@pytest.mark.asyncio
async def test_gateway_builds_pending_downstream_launch_package():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tasks/ltc_demo/bundle"):
            return httpx.Response(200, json=_bundle())
        if request.url.path.endswith("/tasks/ltc_demo/personalized-learning.json"):
            return httpx.Response(200, json=_bundle()["task"])
        raise AssertionError(f"unexpected request: {request.url}")

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
        personalized_learning_entry_path="",
    )
    result = await gateway.prepare_personalized_learning_launch(
        "ltc_demo",
        entry_mode="whole_task",
        correlation_id="correlation_01",
    )
    assert result["status"] == "pending_binding"
    assert result["formal_release_allowed"] is True
    assert result["open_path"] is None
    assert result["handoff"]["payload"]["work_task"]["work_task_id"] == "task_docker_01"


@pytest.mark.asyncio
async def test_gateway_builds_knowledge_entry_path_and_validates_selection():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bundle"):
            return httpx.Response(200, json=_bundle())
        if request.url.path.endswith("/personalized-learning.json"):
            return httpx.Response(200, json=_bundle()["task"])
        raise AssertionError(f"unexpected request: {request.url}")

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
        personalized_learning_entry_path="/personalized-learning/start?source=task-conversion",
    )
    result = await gateway.prepare_personalized_learning_launch(
        "ltc_demo",
        entry_mode="knowledge_point",
        selected_knowledge_id="knowledge_01",
        correlation_id="correlation_02",
    )
    assert result["status"] == "ready"
    assert result["selected_knowledge_point"]["name"] == "镜像分层"
    assert "knowledge_id=knowledge_01" in result["open_path"]
    assert "source=task-conversion" in result["open_path"]

    with pytest.raises(LearningTaskConversionError, match="不属于") as failure:
        await gateway.prepare_personalized_learning_launch(
            "ltc_demo",
            entry_mode="knowledge_point",
            selected_knowledge_id="knowledge_missing",
        )
    assert failure.value.status_code == 422


@pytest.mark.asyncio
async def test_gateway_reads_upstream_handoff_by_id():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/upstream-handoffs/handoff_01")
        return httpx.Response(
            200,
            json={
                "handoff_id": "handoff_01",
                "status": "accepted",
                "packet": {"schema_version": "competency-graph-learning-task-handoff-v1"},
            },
        )

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.upstream_handoff("handoff_01")
    assert result["status"] == "accepted"
