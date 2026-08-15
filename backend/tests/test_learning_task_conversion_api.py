from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.api import learning_task_conversion
from app.main import app


class _FakeGateway:
    async def capabilities(self):
        return {
            "schema_version": "learning-task-conversion-capabilities-v1",
            "service": "learning-task-conversion",
        }

    async def task_bundle(self, task_card_id: str):
        return {
            "schema_version": "learning-task-conversion-integration-bundle-v1",
            "task_card_id": task_card_id,
        }

    async def generate_from_conversation(self, query: str):
        return {
            "schema_version": "learnflow-wf03-generation-v1",
            "task_card_id": "ltc_generated_01",
            "query": query,
        }

    async def submit_upstream_handoff(self, handoff: dict):
        return {
            "handoff_id": "handoff_01",
            "status": "accepted",
            "packet": handoff,
        }

    async def upstream_handoff(self, handoff_id: str):
        return {
            "handoff_id": handoff_id,
            "status": "accepted",
            "packet": {"schema_version": "competency-graph-learning-task-handoff-v1"},
        }

    async def prepare_personalized_learning_launch(
        self,
        task_card_id: str,
        *,
        entry_mode: str,
        selected_knowledge_id: str | None = None,
        correlation_id: str | None = None,
    ):
        return {
            "schema_version": "learning-task-to-personalized-learning-launch-v1",
            "task_card_id": task_card_id,
            "correlation_id": correlation_id or "launch_01",
            "status": "pending_binding",
            "entry_mode": entry_mode,
            "selected_knowledge_point": selected_knowledge_id,
            "open_path": None,
        }


def _handoff() -> dict:
    return {
        "schema_version": "competency-graph-learning-task-handoff-v1",
        "upstream_task_id": "task_network_01",
        "correlation_id": "graph_01",
        "task_name": "交换机 VLAN 配置与验收",
        "task_brief": "依据网络规划创建 VLAN、配置端口并完成连通性验收记录。",
        "source_context": {"source_system": "competency-graph"},
        "knowledge_points": [
            {
                "knowledge_id": "knowledge_vlan",
                "name": "VLAN 划分",
                "description": "理解广播域和端口模式。",
            }
        ],
        "skill_points": [
            {
                "skill_id": "skill_vlan",
                "name": "配置 VLAN",
                "observable_action": "创建 VLAN 并配置端口模式。",
            }
        ],
        "relations": [
            {
                "relation_id": "relation_vlan",
                "knowledge_id": "knowledge_vlan",
                "skill_id": "skill_vlan",
                "relation_type": "required_for_step",
                "strength": "critical",
                "reason": "该知识直接支撑配置与验收动作。",
                "applies_to_steps": ["configure_vlan"],
            }
        ],
    }


def _registration(username: str) -> dict:
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "计算机基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["practice"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def test_learning_task_conversion_proxy_requires_login_and_keeps_task_id(monkeypatch):
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    with TestClient(app) as client:
        assert client.get("/api/learning-task-conversion/capabilities").status_code == 401
        username = f"conversion_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        capabilities = client.get("/api/learning-task-conversion/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["service"] == "learning-task-conversion"

        generated = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "为课程管理系统实现 REST API"},
        )
        assert generated.status_code == 200
        assert generated.json()["task_card_id"] == "ltc_generated_01"

        bundle = client.get(
            "/api/learning-task-conversion/tasks/ltc_contract_01/bundle"
        )
        assert bundle.status_code == 200
        assert bundle.json()["task_card_id"] == "ltc_contract_01"

        invalid = client.get(
            "/api/learning-task-conversion/tasks/not%20valid/bundle"
        )
        assert invalid.status_code == 422


def test_learning_task_conversion_handoff_and_launch_contracts(monkeypatch):
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    with TestClient(app) as client:
        username = f"handoff_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        accepted = client.post(
            "/api/learning-task-conversion/upstream-handoffs",
            json=_handoff(),
        )
        assert accepted.status_code == 200
        assert accepted.json()["handoff_id"] == "handoff_01"
        assert accepted.json()["learnflow_integration"]["handoff_status_path"].endswith(
            "/handoff_01"
        )

        stored = client.get(
            "/api/learning-task-conversion/upstream-handoffs/handoff_01"
        )
        assert stored.status_code == 200
        assert stored.json()["status"] == "accepted"

        invalid_handoff = _handoff()
        invalid_handoff["relations"] = []
        assert client.post(
            "/api/learning-task-conversion/upstream-handoffs",
            json=invalid_handoff,
        ).status_code == 422

        launch = client.post(
            "/api/learning-task-conversion/tasks/ltc_contract_01/downstream-launch",
            json={
                "schema_version": "personalized-learning-launch-request-v1",
                "entry_mode": "whole_task",
            },
        )
        assert launch.status_code == 200
        assert launch.json()["status"] == "pending_binding"
        assert launch.json()["open_path"] is None
