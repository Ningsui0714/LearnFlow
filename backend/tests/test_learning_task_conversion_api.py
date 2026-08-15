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
