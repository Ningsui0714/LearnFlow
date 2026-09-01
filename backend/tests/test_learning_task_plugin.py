import asyncio
from types import SimpleNamespace

import pytest

from app.services.learning_task_agent_package import run_learning_task_workflow


class FakeContext:
    def __init__(self, workflow: str):
        self.run = SimpleNamespace(contract={"workflow_id": workflow}, operation_id=workflow)
        self.project_id = 7

    async def call_host_port(self, port: str, input_value: dict):
        if port == "project.read.v1":
            return {"id": 7, "name": "计算机网络实训", "description": "完成可验收的网络配置任务"}
        if port == "source.read.v1":
            return {"sources": []}
        if port == "model.generate_structured.v1":
            assert input_value["provider"] == "xingchen_learning_task"
            titles = [
                "核对拓扑与业务边界", "编制实施规划", "完成核心配置",
                "处理依赖与异常", "执行验收测试", "归档配置与交付",
            ]
            return {
                "provider": "xunfei-xingchen",
                "model": "xunfei-xingchen-workflow",
                "provider_provenance": {
                    "workflow_run_id": "run_test_01",
                    "task_card_id": "ltc_test_01",
                    "verification_status": "verified",
                },
                "value": {
                    "title": f"{input_value['task_title']}学习型工作任务",
                    "context": "在实训环境中完成真实工作任务。",
                    "objective": "提交可检查产物和验收记录。",
                    "tools": ["实训工具"],
                    "safety": ["遵守操作边界"],
                    "acceptance": ["全部步骤可复核"],
                    "steps": [
                        {
                            "external_id": f"xf_step_{index:02d}",
                            "title": title,
                            "operation": f"完成{title}的具体操作。",
                            "deliverable": f"{title}产物",
                            "acceptance": f"{title}结果可检查",
                            "knowledge": f"{title}知识",
                            "skill": f"{title}技能",
                            "knowledge_items": [{
                                "knowledge_id": f"xf_kp_{index:02d}",
                                "name": f"{title}知识",
                                "scope": f"理解{title}的状态和边界。",
                                "learning_resources": [],
                            }],
                            "skill_items": [{
                                "skill_id": f"xf_sp_{index:02d}",
                                "name": f"{title}技能",
                                "observable_action": f"能够完成{title}。",
                            }],
                            "prerequisites": [],
                            "safety": "按安全规范操作。",
                        }
                        for index, title in enumerate(titles, start=1)
                    ],
                },
            }
        raise AssertionError(port)


def test_learning_task_package_generates_step_level_snapshot_and_handoff():
    generated = asyncio.run(run_learning_task_workflow(
        FakeContext("generate"),
        {
            "task_title": "配置交换机 VLAN 与 Trunk 并验收连通性",
            "plugin_configuration": {"target_steps": 6, "allow_model_fallback": True},
        },
    ))
    snapshot = generated["snapshot"]
    task_document = snapshot["components"]["task-document"]
    steps = task_document["steps"]
    assert len(steps) == 6
    assert steps[0]["title"] == "核对拓扑与业务边界"
    assert all(step["deliverable"] and step["acceptance"] for step in steps)
    assert snapshot["validation"]["stats"]["relations"] == 12
    assert snapshot["provenance"]["kernel_targets"] == []
    assert snapshot["provenance"]["provider"] == "xunfei-xingchen"
    assert snapshot["provenance"]["fallback_used"] is False
    assert snapshot["provenance"]["provider_provenance"]["task_card_id"] == "ltc_test_01"
    assert "WF03" not in str(snapshot)

    snapshot_input = {
        **snapshot,
        "id": 31,
        "root_hash": "a" * 64,
        "version": 1,
    }
    knowledge_id = snapshot["components"]["knowledge-map"]["knowledge_points"][0]["id"]
    handoff = asyncio.run(run_learning_task_workflow(
        FakeContext("handoff"),
        {"snapshot": snapshot_input, "knowledge_id": knowledge_id},
    ))
    package = handoff["result"]["handoff"]
    assert package["protocol"] == "learnflow.personalized-learning-handoff.v1"
    assert package["knowledge"]["id"] == knowledge_id
    assert package["steps"]
    assert package["kernel_targets"] == []


def test_learning_task_package_reorders_steps_and_records_review_note():
    generated = asyncio.run(run_learning_task_workflow(
        FakeContext("generate"),
        {
            "task_title": "实现 Unity 摄像机跟随与遮挡处理",
            "plugin_configuration": {"target_steps": 6, "allow_model_fallback": True},
        },
    ))
    snapshot = {
        **generated["snapshot"],
        "id": 44,
        "root_hash": "b" * 64,
        "version": 1,
    }
    steps = snapshot["components"]["task-document"]["steps"]
    order = [item["id"] for item in reversed(steps)]
    revised = asyncio.run(run_learning_task_workflow(
        FakeContext("revise"),
        {
            "snapshot": snapshot,
            "snapshot_ref": {"snapshot_id": 44},
            "target_id": order[0],
            "step_order": order,
            "note": "把遮挡验证提前到首步复核。",
        },
    ))
    successor = revised["snapshot"]
    revised_steps = successor["components"]["task-document"]["steps"]
    assert [item["id"] for item in revised_steps] == order
    assert [item["order"] for item in revised_steps] == list(range(1, 7))
    notes = successor["components"]["review-notes"]["notes"]
    assert notes[-1]["note"] == "把遮挡验证提前到首步复核。"
    assert notes[-1]["target_id"] == order[0]


def test_learning_task_package_never_silently_falls_back_when_xingchen_fails():
    class FailingContext(FakeContext):
        async def call_host_port(self, port: str, input_value: dict):
            if port == "model.generate_structured.v1":
                raise RuntimeError("xingchen unavailable")
            return await super().call_host_port(port, input_value)

    with pytest.raises(RuntimeError, match="xingchen unavailable"):
        asyncio.run(run_learning_task_workflow(
            FailingContext("generate"),
            {
                "task_title": "全新任务",
                "plugin_configuration": {
                    "target_steps": 6,
                    "allow_model_fallback": True,
                },
            },
        ))
