from __future__ import annotations

import json

import httpx
import pytest

from app.services.learning_task_conversion_xfyun import (
    LearningTaskBundleGateway,
    XingchenLearningTaskWorkflowClient,
    XingchenWorkflowCredentials,
    XingchenWorkflowError,
    generate_xingchen_learning_task,
    targeted_patch_from_content,
    validate_task_bundle,
)


def _bundle(task_card_id: str = "ltc_generated_01") -> dict:
    return {
        "schema_version": "learning-task-conversion-integration-bundle-v1",
        "task_card_id": task_card_id,
        "verification_status": "verified",
        "task": {
            "schema_version": "learning-task-to-personalized-learning-v1",
            "work_task": {
                "work_task_id": "task_nginx_01",
                "enterprise_task_name": "Nginx 静态网站部署与验收",
                "teaching_task_name": "Nginx 静态网站部署学习型工作任务",
                "teaching_task_description": "完成部署、HTTPS、日志和验收。",
                "work_situation": "在 Ubuntu 服务器实训环境中完成网站交付。",
                "tools": ["Ubuntu 服务器", "Nginx"],
                "safety_points": ["变更前备份配置"],
                "acceptance_tests": ["HTTPS 可访问", "日志可追溯"],
                "task_steps": [
                    {
                        "step_id": f"step_{index:02d}",
                        "name": name,
                        "action": f"完成{name}。",
                        "deliverable": f"{name}记录",
                        "check": f"检查{name}结果。",
                        "knowledge_point_ids": [f"kp_{index:02d}"],
                        "skill_point_ids": [f"sp_{index:02d}"],
                    }
                    for index, name in enumerate((
                        "核对环境", "安装服务", "部署站点",
                        "配置 HTTPS", "检查日志", "完成验收",
                    ), start=1)
                ],
                "knowledge_points": [
                    {
                        "knowledge_id": f"kp_{index:02d}",
                        "name": f"{name}知识",
                        "scope": f"理解{name}的对象和边界。",
                        "learning_resources": [{
                            "resource_id": f"res_{index:02d}",
                            "resource_name": f"{name}教程",
                            "resource_type": "video_search",
                            "platform": "bilibili",
                            "resource_url": "https://search.bilibili.com/all?keyword=nginx",
                        }],
                    }
                    for index, name in enumerate((
                        "环境", "安装", "部署", "HTTPS", "日志", "验收",
                    ), start=1)
                ],
                "skill_points": [
                    {
                        "skill_id": f"sp_{index:02d}",
                        "name": f"{name}技能",
                        "observable_action": f"能够完成{name}。",
                    }
                    for index, name in enumerate((
                        "环境核对", "服务安装", "站点部署",
                        "HTTPS 配置", "日志检查", "交付验收",
                    ), start=1)
                ],
            },
        },
        "strong_relationships": [],
        "artifacts": {},
    }


def _credentials() -> XingchenWorkflowCredentials:
    return XingchenWorkflowCredentials(
        app_id="app",
        api_key="key",
        api_secret="secret",
        flow_id="flow",
        base_url="https://xingchen.example",
        timeout_seconds=5,
    )


def _minimum_five_step_schema() -> dict:
    return {
        "type": "object",
        "required": ["steps"],
        "properties": {
            "steps": {"type": "array", "minItems": 5},
        },
    }


@pytest.mark.asyncio
async def test_xingchen_client_invokes_fixed_workflow_without_exposing_credentials():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/workflow/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer key:secret"
        body = json.loads(request.content)
        assert body["flow_id"] == "flow"
        assert body["parameters"] == {"AGENT_USER_INPUT": "部署 Nginx"}
        return httpx.Response(200, json={
            "code": 0,
            "id": "run_01",
            "choices": [{"delta": {"content": (
                "/api/v1/learning-task-conversion/tasks/"
                "ltc_generated_01/interactive.html"
            )}}],
            "usage": {"total_tokens": 123},
        })

    result = await XingchenLearningTaskWorkflowClient(
        credentials=_credentials(),
        transport=httpx.MockTransport(handler),
    ).run("部署 Nginx", uid="learner-1")

    assert result["provider"] == "xunfei-xingchen"
    assert result["run_id"] == "run_01"
    assert "api_key" not in result
    assert "api_secret" not in result


@pytest.mark.asyncio
async def test_xingchen_generation_resolves_validated_bundle_and_preserves_step_mapping():
    async def workflow_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": 0,
            "id": "run_02",
            "choices": [{"delta": {"content": (
                "/api/v1/learning-task-conversion/tasks/"
                "ltc_generated_01/interactive.html"
            )}}],
        })

    async def bundle_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/tasks/ltc_generated_01/bundle")
        return httpx.Response(200, json=_bundle())

    generated = await generate_xingchen_learning_task(
        "部署 Nginx",
        uid="learner-2",
        workflow_client=XingchenLearningTaskWorkflowClient(
            credentials=_credentials(),
            transport=httpx.MockTransport(workflow_handler),
        ),
        bundle_gateway=LearningTaskBundleGateway(
            base_url="https://conversion.example",
            transport=httpx.MockTransport(bundle_handler),
        ),
    )

    assert generated["provider"] == "xunfei-xingchen"
    assert generated["task_card_id"] == "ltc_generated_01"
    assert generated["verification_status"] == "verified"
    assert len(generated["plan"]["steps"]) == 6
    first = generated["plan"]["steps"][0]
    assert first["title"] == "核对环境"
    assert first["knowledge_items"][0]["knowledge_id"] == "kp_01"
    assert first["skill_items"][0]["skill_id"] == "sp_01"


def test_bundle_validation_rejects_dangling_provider_mappings():
    invalid = _bundle()
    invalid["task"]["work_task"]["task_steps"][0]["knowledge_point_ids"] = [
        "missing_knowledge"
    ]
    with pytest.raises(XingchenWorkflowError, match="悬空映射"):
        validate_task_bundle(invalid, "ltc_generated_01")


def _targeted_patch_content() -> str:
    return """## 岗位典型工作任务转化结果
{
  "schema_version": "learning-work-task-targeted-patch-v1",
  "hard_errors": ["候选内容没有保留任务对象“Windows可执行软件包”或其允许别名"],
  "targets": [
    {
      "step_id": "step_01",
      "reason_codes": ["ACTION_NOT_SPECIFIC", "DELIVERABLE_NOT_OBSERVABLE"],
      "instruction": "仅修复该步骤的动作、产物、检查点或映射缺口。"
    }
  ]
}
"""


def test_targeted_patch_is_extracted_from_markdown_workflow_content():
    patch = targeted_patch_from_content(_targeted_patch_content())
    assert patch is not None
    assert patch["schema_version"] == "learning-work-task-targeted-patch-v1"
    assert patch["targets"][0]["reason_codes"] == [
        "ACTION_NOT_SPECIFIC", "DELIVERABLE_NOT_OBSERVABLE",
    ]


@pytest.mark.asyncio
async def test_xingchen_generation_automatically_repairs_publish_gate_patch_once():
    class SequencedWorkflowClient:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        async def run(self, user_input: str, *, uid: str) -> dict:
            self.calls.append((user_input, uid))
            if len(self.calls) == 1:
                return {
                    "run_id": "run_initial",
                    "content": _targeted_patch_content(),
                    "usage": {"total_tokens": 80},
                }
            return {
                "run_id": "run_repair",
                "content": (
                    "/api/v1/learning-task-conversion/tasks/"
                    "ltc_generated_01/interactive.html"
                ),
                "usage": {"total_tokens": 120},
            }

    async def bundle_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_bundle())

    client = SequencedWorkflowClient()
    generated = await generate_xingchen_learning_task(
        "windows可执行软件的打包",
        uid="learner-repair",
        workflow_client=client,  # type: ignore[arg-type]
        bundle_gateway=LearningTaskBundleGateway(
            base_url="https://conversion.example",
            transport=httpx.MockTransport(bundle_handler),
        ),
    )

    assert len(client.calls) == 2
    assert "请重新完整生成并发布" in client.calls[1][0]
    assert "Windows可执行软件包" in client.calls[1][0]
    assert "ACTION_NOT_SPECIFIC" in client.calls[1][0]
    assert generated["repair_attempted"] is True
    assert generated["workflow_run_id"] == "run_repair"
    assert generated["workflow_run_ids"] == ["run_initial", "run_repair"]
    assert generated["task_card_id"] == "ltc_generated_01"


@pytest.mark.asyncio
async def test_xingchen_generation_surfaces_publish_gate_reason_after_failed_repair():
    class RejectedWorkflowClient:
        async def run(self, _user_input: str, *, uid: str) -> dict:
            return {
                "run_id": f"run_{uid}",
                "content": _targeted_patch_content(),
                "usage": {},
            }

    with pytest.raises(
        XingchenWorkflowError,
        match="Windows可执行软件包",
    ):
        await generate_xingchen_learning_task(
            "windows可执行软件的打包",
            uid="learner-rejected",
            workflow_client=RejectedWorkflowClient(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_xingchen_generation_retries_when_compiled_plan_fails_step_schema():
    class SequencedWorkflowClient:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        async def run(self, user_input: str, *, uid: str) -> dict:
            self.calls.append((user_input, uid))
            task_card_id = "ltc_short" if len(self.calls) == 1 else "ltc_repaired"
            return {
                "run_id": f"run_{len(self.calls)}",
                "content": (
                    "/api/v1/learning-task-conversion/tasks/"
                    f"{task_card_id}/interactive.html"
                ),
                "usage": {},
            }

    async def bundle_handler(request: httpx.Request) -> httpx.Response:
        task_card_id = request.url.path.split("/tasks/", 1)[1].split("/", 1)[0]
        bundle = _bundle(task_card_id)
        if task_card_id == "ltc_short":
            bundle["task"]["work_task"]["task_steps"] = bundle["task"]["work_task"]["task_steps"][:4]
        return httpx.Response(200, json=bundle)

    client = SequencedWorkflowClient()
    generated = await generate_xingchen_learning_task(
        "配置企业园区交换机 VLAN",
        uid="learner-schema-repair",
        workflow_client=client,  # type: ignore[arg-type]
        bundle_gateway=LearningTaskBundleGateway(
            base_url="https://conversion.example",
            transport=httpx.MockTransport(bundle_handler),
        ),
        plan_schema=_minimum_five_step_schema(),
    )

    assert len(client.calls) == 2
    assert "$.steps" in client.calls[1][0]
    assert "至少需要 5 项" in client.calls[1][0]
    assert generated["repair_attempted"] is True
    assert generated["repair_reasons"] == ["structure_schema"]
    assert generated["workflow_run_ids"] == ["run_1", "run_2"]
    assert generated["task_card_id"] == "ltc_repaired"


@pytest.mark.asyncio
async def test_xingchen_generation_surfaces_exact_schema_path_after_failed_structure_repair():
    class AlwaysShortWorkflowClient:
        def __init__(self):
            self.calls = 0

        async def run(self, _user_input: str, *, uid: str) -> dict:
            self.calls += 1
            return {
                "run_id": f"run_{self.calls}",
                "content": (
                    "/api/v1/learning-task-conversion/tasks/"
                    f"ltc_short_{self.calls}/interactive.html"
                ),
                "usage": {},
            }

    async def bundle_handler(request: httpx.Request) -> httpx.Response:
        task_card_id = request.url.path.split("/tasks/", 1)[1].split("/", 1)[0]
        bundle = _bundle(task_card_id)
        bundle["task"]["work_task"]["task_steps"] = bundle["task"]["work_task"]["task_steps"][:4]
        return httpx.Response(200, json=bundle)

    with pytest.raises(
        XingchenWorkflowError,
        match=r"讯飞任务结构自动修订后仍未通过：\$\.steps：至少需要 5 项，实际只有 4 项",
    ):
        await generate_xingchen_learning_task(
            "配置企业园区交换机 VLAN",
            uid="learner-schema-rejected",
            workflow_client=AlwaysShortWorkflowClient(),  # type: ignore[arg-type]
            bundle_gateway=LearningTaskBundleGateway(
                base_url="https://conversion.example",
                transport=httpx.MockTransport(bundle_handler),
            ),
            plan_schema=_minimum_five_step_schema(),
        )
