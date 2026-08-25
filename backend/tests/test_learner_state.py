import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        assert accounts.status_code == 200
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


def eid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_vnext_operational_event_is_idempotent_and_zero_target(client: TestClient):
    client_event_id = eid("vnext-step")
    payload = {
        "event_type": "vnext_learning_skill_step_entered",
        "client_event_id": client_event_id,
        "payload": {"task_id": "local-1", "step_id": "anchor"},
    }
    first = client.post("/api/learner-state/events", json=payload)
    second = client.post("/api/learner-state/events", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["event_id"] == second.json()["event_id"]


def test_learning_path_self_report_updates_structure_without_mastery(client: TestClient):
    response = client.post("/api/learner-state/learning-path/status", json={
        "node_id": "machine-learning",
        "node_title": "机器学习",
        "status": "self_reported_mastered",
        "client_event_id": eid("path-status"),
    })
    assert response.status_code == 200, response.text
    snapshot = client.get("/api/learner-state/snapshot")
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()
    assert data["learning_path"]["statuses"]["machine-learning"]["status"] == "self_reported_mastered"
    knowledge = data["kernels"]["knowledge"]
    declared = knowledge["short_term"]["declared_course_exposure"]["machine-learning"]
    assert declared["self_reported_only"] is True
    assert declared["mastery_unchanged"] is True
    assert "machine-learning" not in knowledge["long_term"].get("mastery", {})


def test_personal_path_node_and_value_claim_use_formal_reducer(client: TestClient):
    node_id = f"personal-{uuid.uuid4().hex[:10]}"
    added = client.post("/api/learner-state/learning-path/personal-nodes", json={
        "node": {
            "id": node_id,
            "title": "Agent 评测工程",
            "summary": "构建可重复的 Agent 评测与轨迹分析流程。",
            "aliases": ["agent eval"],
            "domains": ["AI", "工程"],
            "stage": "advanced",
            "order": 6,
            "sourceRefs": ["https://example.com/agent-eval"],
        },
        "edges": [{
            "id": f"edge-{node_id}", "from": "agent-engineering", "to": node_id,
            "kind": "soft_prerequisite", "rationale": "先有 Agent 工程基础", "origin": "personal",
        }],
        "reason": "学习者明确希望补充这一方向",
        "client_event_id": eid("personal-node"),
    })
    assert added.status_code == 200, added.text
    assert any(item["id"] == node_id for item in added.json()["learning_path"]["personal_nodes"])

    proposal_id = f"goal-{uuid.uuid4().hex[:10]}"
    confirmed = client.post("/api/learner-state/value-claims/confirm", json={
        "proposal_id": proposal_id,
        "current_claim": "探索 Agent 与机器学习科研",
        "proposed_claim": "未来一年优先探索 Agent 评测工程，并保留机器学习科研分支。",
        "evidence_quote": "我想先做 Agent 评测工程项目，再决定是否偏科研。",
        "scope": "long_term_direction_candidate",
        "client_event_id": eid("value-claim"),
    })
    assert confirmed.status_code == 200, confirmed.text
    snapshot = client.get("/api/learner-state/snapshot").json()
    goal = snapshot["kernels"]["value"]["long_term"]["confirmed_goals"][proposal_id]
    assert goal["status"] == "confirmed"
    assert goal["evidence_quote"].startswith("我想先做")

    removed = client.delete(
        f"/api/learner-state/learning-path/personal-nodes/{node_id}",
        params={"client_event_id": eid("remove-node"), "node_title": "Agent 评测工程"},
    )
    assert removed.status_code == 200, removed.text
    assert all(item["id"] != node_id for item in removed.json()["learning_path"]["personal_nodes"])


def test_context_packet_is_answer_free_and_authoritative(client: TestClient):
    response = client.get("/api/learner-state/context", params={"query": "规划 Agent 评测工程"})
    assert response.status_code == 200, response.text
    packet = response.json()
    assert packet["manifest"]["answer_free"] is True
    assert packet["manifest"]["authority"] == "read_only_projection_from_evidence_and_memory_graph"


def test_personal_path_gateway_rejects_invalid_edges_and_cycles(client: TestClient):
    invalid_id = f"invalid-{uuid.uuid4().hex[:8]}"
    invalid = client.post("/api/learner-state/learning-path/personal-nodes", json={
        "node": {"id": invalid_id, "title": "非法关系节点"},
        "edges": [{
            "from": "machine-learning", "to": "deep-learning",
            "kind": "soft_prerequisite",
        }],
        "client_event_id": eid("invalid-edge"),
    })
    assert invalid.status_code == 422

    suffix = uuid.uuid4().hex[:8]
    first_id, second_id, third_id = (f"dag-{suffix}-{index}" for index in range(3))

    def add_node(node_id: str, edges: list[dict]):
        return client.post("/api/learner-state/learning-path/personal-nodes", json={
            "node": {"id": node_id, "title": node_id},
            "edges": edges,
            "client_event_id": eid("dag-node"),
        })

    first = add_node(first_id, [{
        "from": "machine-learning", "to": first_id, "kind": "soft_prerequisite",
    }])
    assert first.status_code == 200, first.text
    second = add_node(second_id, [{
        "from": first_id, "to": second_id, "kind": "soft_prerequisite",
    }])
    assert second.status_code == 200, second.text
    cycle = add_node(third_id, [
        {"from": second_id, "to": third_id, "kind": "soft_prerequisite"},
        {"from": third_id, "to": first_id, "kind": "soft_prerequisite"},
    ])
    assert cycle.status_code == 422
    assert "形成环" in cycle.json()["detail"]
