from __future__ import annotations

import json

import httpx
import pytest

from app.services.learning_task_direct_plan import (
    ContentModelConfig,
    LearningTaskDirectPlanGenerator,
)


def _candidate() -> dict:
    knowledge = ["需求与验收", "Unity Transform", "C#脚本生命周期"]
    skills = ["搭建场景", "编写跟随脚本", "运行测试"]
    return {
        "task_name": "Unity第三人称摄像机跟随模块开发与验收",
        "task_description": "完成跟随、旋转、避障和验收交付。",
        "task_scenario": "在Unity课程项目中交付可复用的第三人称摄像机模块。",
        "knowledge_points": knowledge,
        "skill_points": skills,
        "tools": ["Unity", "Rider", "Git"],
        "workflow_steps": [
            {
                "step_id": f"raw_{index}",
                "name": name,
                "action": f"打开Unity完成{name}，保存配置并记录结果。",
                "deliverable": f"{name}产物与截图",
                "check": f"运行场景并确认{name}结果符合要求。",
                "knowledge_points": [knowledge[(index - 1) % len(knowledge)]],
                "skill_points": [skills[(index - 1) % len(skills)]],
            }
            for index, name in enumerate(
                ["确认需求", "搭建场景", "实现跟随", "实现避障", "测试交付"],
                start=1,
            )
        ],
        "acceptance_tests": [
            {
                "test_id": "AT-01",
                "test_description": "跟随测试",
                "test_steps": "移动角色并观察摄像机。",
                "expected_result": "摄像机稳定跟随。",
            },
            {
                "test_id": "AT-02",
                "test_description": "避障测试",
                "test_steps": "在角色与摄像机之间放置障碍物。",
                "expected_result": "摄像机不穿模。",
            },
        ],
        "assessment": {
            "rubric": ["优秀：全部通过", "合格：核心通过", "待改进：存在失败项"],
            "weight_breakdown": {"实现": "60%", "测试": "40%"},
        },
        "safety_points": ["修改前备份场景", "不将密钥写入脚本"],
    }


@pytest.mark.asyncio
async def test_direct_plan_generates_candidate_then_commits_delivery():
    run_id = "run_0123456789abcdef"
    fingerprint = "a" * 32
    calls: list[str] = []

    async def plan_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        path = request.url.path
        base = {
            "run_id": run_id,
            "status": "active",
            "task_contract_json": json.dumps({
                "object": "Unity第三人称摄像机跟随模块",
                "semantic_fingerprint": fingerprint,
            }, ensure_ascii=False),
            "plan_json": json.dumps({"plan_version": 1}, ensure_ascii=False),
            "patch_plan_json": "{}",
            "delivery_json": "{}",
        }
        if path.endswith("/create"):
            return httpx.Response(200, json={**base, "phase": "CONTRACT_READY"})
        if path.endswith("/plan"):
            submitted_plan = json.loads(request.url.params["plan_json"])
            assert submitted_plan["plan_version"] == 2
            return httpx.Response(200, json={**base, "phase": "PLAN_READY"})
        if path.endswith("/evidence"):
            return httpx.Response(200, json={**base, "phase": "EVIDENCE_READY"})
        if path.endswith("/review"):
            wrapper = json.loads(request.content)
            assert wrapper["run_id"] == run_id
            submitted = json.loads(wrapper["candidates_json"])[0]
            assert submitted["task_ir_fingerprint"] == fingerprint
            assert len(submitted["workflow_steps"]) == 5
            assert all(
                step["evidence_refs"] == ["upstream_task_contract"]
                for step in submitted["workflow_steps"]
            )
            return httpx.Response(200, json={**base, "phase": "COMMIT_READY"})
        assert path.endswith("/commit")
        return httpx.Response(200, json={
            **base,
            "phase": "COMMITTED",
            "status": "completed",
            "delivery_json": json.dumps({
                "task_card_id": "ltc_direct_unseen_01",
            }),
        })

    async def content_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content)["response_format"] == {
            "type": "json_object",
        }
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                _candidate(), ensure_ascii=False,
            )}}],
        })

    generator = LearningTaskDirectPlanGenerator(
        base_url="https://plan.example",
        content_config=ContentModelConfig(
            api_base="https://model.example/chat/completions",
            api_key="test-key",
            model="test-model",
            timeout_seconds=20,
            max_tokens=5000,
            temperature=0.2,
        ),
        plan_transport=httpx.MockTransport(plan_handler),
        content_transport=httpx.MockTransport(content_handler),
    )

    result = await generator.generate("Unity第三人称摄像机跟随模块开发与验收")

    assert result["provider"] == "wf03-plan-direct-fallback"
    assert json.loads(result["content"])["task_card_id"] == "ltc_direct_unseen_01"
    assert calls == [
        "/api/v1/learning-work-task-agent/xfyun/create",
        "/api/v1/learning-work-task-agent/xfyun/plan",
        "/api/v1/learning-work-task-agent/xfyun/evidence",
        "/api/v1/learning-work-task-agent/xfyun/review",
        "/api/v1/learning-work-task-agent/xfyun/commit",
    ]


@pytest.mark.asyncio
async def test_direct_plan_retries_once_after_invalid_candidate_json():
    fingerprint = "b" * 32
    task_contract = {
        "object": "Unity第三人称摄像机跟随模块",
        "semantic_fingerprint": fingerprint,
    }
    requests: list[dict] = []

    async def content_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "{截断的JSON"}}],
            })
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                _candidate(), ensure_ascii=False,
            )}}],
        })

    generator = LearningTaskDirectPlanGenerator(
        content_config=ContentModelConfig(
            api_base="https://model.example/chat/completions",
            api_key="test-key",
            model="test-model",
            timeout_seconds=20,
            max_tokens=5000,
            temperature=0.3,
        ),
        content_transport=httpx.MockTransport(content_handler),
    )

    candidate = await generator._draft_candidate_with_retry(
        "Unity第三人称摄像机跟随模块开发与验收",
        task_contract,
    )

    assert len(candidate["workflow_steps"]) == 5
    assert len(requests) == 2
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert requests[1]["temperature"] == 0.1
    assert "上次输出未通过结构校验" in requests[1]["messages"][1]["content"]
    assert "固定输出5个步骤" in requests[1]["messages"][1]["content"]
