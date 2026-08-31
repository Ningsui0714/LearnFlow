import asyncio
from types import SimpleNamespace

from app.services.learning_task_agent_package import run_learning_task_workflow


class FakeContext:
    def __init__(self, workflow: str):
        self.run = SimpleNamespace(contract={"workflow_id": workflow}, operation_id=workflow)
        self.project_id = 7

    async def call_host_port(self, port: str, _input: dict):
        if port == "project.read.v1":
            return {"id": 7, "name": "计算机网络实训", "description": "完成可验收的网络配置任务"}
        if port == "source.read.v1":
            return {"sources": []}
        if port == "model.generate_structured.v1":
            raise RuntimeError("offline test provider")
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
