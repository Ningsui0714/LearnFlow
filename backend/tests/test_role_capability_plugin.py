import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session
from app.main import app
from app.models.learning import EvidenceEvent, KernelMutation
from app.services.role_capability_plugin import (
    apply_iteration, compile_role_graph, explain_role_graph, inspect_role_graph,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


def test_compiler_builds_stable_evidence_bound_role_graph():
    inputs = dict(
        role_title="LLM 应用工程师",
        role_summary="构建可验证的智能应用",
        task_seeds=["设计 Agent 工具契约", "验证检索与回答质量"],
        source_refs=[{"ref": "source:7@v1"}],
        source_texts=[],
    )
    first = compile_role_graph(**inputs)
    second = compile_role_graph(**inputs)
    assert first == second
    validation = inspect_role_graph(first)
    assert validation["valid"] is True
    assert validation["stats"]["task"] == 2
    assert all(node["evidence_refs"] for node in first["nodes"] if node["type"] != "role")


def test_compiler_keeps_each_source_sentence_bound_to_its_own_version_ref():
    graph = compile_role_graph(
        role_title="复合岗位", role_summary="", task_seeds=[],
        source_refs=[{"ref": "source:1@v2"}, {"ref": "source:2@v4"}],
        source_texts=[
            {"ref": "source:1@v2", "text": "负责设计检索系统"},
            {"ref": "source:2@v4", "text": "监控线上质量与成本"},
        ],
    )
    tasks = {node["label"]: node for node in graph["nodes"] if node["type"] == "task"}
    assert tasks["负责设计检索系统"]["evidence_refs"] == ["source:1@v2"]
    assert tasks["监控线上质量与成本"]["evidence_refs"] == ["source:2@v4"]


def test_explain_agent_is_bounded_and_iteration_rejects_dangling_parent():
    graph = compile_role_graph(
        role_title="Agent 工程师", role_summary="",
        task_seeds=["设计工具协议", "构建评测集"], source_refs=[], source_texts=[],
    )
    explanation = explain_role_graph(graph, "工具协议需要什么能力")
    assert explanation["authority"] == "immutable_role_capability_snapshot"
    assert len(explanation["objects"]) <= 8
    assert explanation["mastery_unchanged"] is True
    candidate, diff = apply_iteration(graph, [{
        "op": "add_node", "type": "capability", "label": "诊断工具失败",
        "parent_id": "task:missing",
    }])
    assert diff["meaningful"] is True
    assert inspect_role_graph(candidate)["valid"] is False


def test_project_plugin_generation_explanation_iteration_and_idempotency(client: TestClient):
    created = client.post("/api/vnext-projects", json={
        "name": f"岗位能力图谱 {uuid.uuid4().hex[:6]}",
        "objective": "理解 LLM 应用工程师岗位并形成学习路线",
        "expected_outcome": "一份有来源边界的岗位包",
        "user_level": "intermediate",
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["project"]["id"]
    key = f"role-generate-{uuid.uuid4().hex}"
    payload = {
        "role_title": "LLM 应用工程师",
        "role_summary": "构建、评测和维护智能应用",
        "task_seeds": ["设计 Agent 工具契约", "构建离线评测集"],
        "source_ids": [],
        "idempotency_key": key,
    }
    generated = client.post(f"/api/role-capability/projects/{project_id}/generate", json=payload)
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["snapshot"]["validation"]["valid"] is True
    assert body["authority"].endswith("never mutate five-kernel learner state")
    replay = client.post(f"/api/role-capability/projects/{project_id}/generate", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["snapshot"]["id"] == body["snapshot"]["id"]

    explained = client.post(f"/api/role-capability/projects/{project_id}/explain", json={
        "query": "工具契约为什么重要",
    })
    assert explained.status_code == 200, explained.text
    assert explained.json()["snapshot"]["root_hash"] == body["snapshot"]["root_hash"]
    assert explained.json()["explanation"]["mastery_unchanged"] is True

    role_id = next(node["id"] for node in body["snapshot"]["graph"]["nodes"] if node["type"] == "role")
    iterated = client.post(f"/api/role-capability/projects/{project_id}/iterate", json={
        "objective": "补充生产监控任务",
        "target_ids": [role_id],
        "operations": [{
            "op": "add_node", "type": "task", "label": "监控线上 Agent 质量与成本",
            "summary": "持续监控失败样本、延迟和成本", "parent_id": role_id,
            "evidence_refs": ["user:explicit-iteration"],
        }],
        "idempotency_key": f"role-iterate-{uuid.uuid4().hex}",
    })
    assert iterated.status_code == 200, iterated.text
    iterated_body = iterated.json()
    assert iterated_body["snapshot"]["version"] == body["snapshot"]["version"] + 1
    assert iterated_body["diff"]["change_count"] == 1
    assert iterated_body["snapshot"]["root_hash"] != body["snapshot"]["root_hash"]

    async def inspect_events():
        async with async_session() as db:
            events = list((await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.project_id == project_id,
                EvidenceEvent.event_type.in_({"role_capability_package_generated", "role_capability_snapshot_iterated"}),
            ))).scalars())
            mutations = list((await db.execute(select(KernelMutation).where(
                KernelMutation.event_id.in_([item.id for item in events]),
            ))).scalars()) if events else []
            return events, mutations

    events, mutations = asyncio.run(inspect_events())
    assert {item.event_type for item in events} == {
        "role_capability_package_generated", "role_capability_snapshot_iterated",
    }
    assert mutations == []
