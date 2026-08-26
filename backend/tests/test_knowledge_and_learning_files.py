from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.database import async_session
from app.main import app
from app.models.learning import EvidenceEvent, KernelMutation


def _register(client: TestClient) -> int:
    suffix = uuid.uuid4().hex[:10]
    response = client.post("/api/auth/register", json={
        "username": f"file-system-{suffix}",
        "password": "learnflow-pass-123",
        "display_name": "File System Learner",
        "education_stage": "undergraduate",
        "background": "Python 基础",
        "focus_areas": ["机器学习"],
        "weekly_hours": 6,
        "preferred_modes": ["explanation", "practice"],
        "career_goal": "",
        "career_goal_status": "exploring",
    })
    assert response.status_code == 200, response.text
    return response.json()["learner_id"]


def test_personal_source_library_is_context_not_mastery(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "source_uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "source_cache_dir", str(tmp_path / "cache"))
    with TestClient(app) as client:
        learner_id = _register(client)
        linked = client.post("/api/knowledge-library/sources/url", json={
            "url": "https://docs.python.org/3/tutorial/",
        })
        assert linked.status_code == 200, linked.text
        assert linked.json()["type"] == "url"
        assert linked.json()["url"] == "https://docs.python.org/3/tutorial/"
        uploaded = client.post("/api/knowledge-library/sources/upload", files={
            "file": ("kernel-notes.md", "# Kernel Methods\n\n## RBF kernel\nA kernel computes an inner product in an implicit feature space.\n核方法通过核函数表达隐式特征空间中的内积。\n".encode(), "text/markdown"),
        })
        assert uploaded.status_code == 200, uploaded.text
        source_id = uploaded.json()["id"]
        processed = client.post(f"/api/knowledge-library/sources/{source_id}/process")
        assert processed.status_code == 200, processed.text
        source = processed.json()["source"]
        assert source["chunk_count"] > 0
        assert {item["label"] for item in source["knowledge_domains"]} >= {"Kernel Methods", "RBF kernel"}

        context = client.get("/api/knowledge-library/context", params={"query": "RBF kernel"})
        assert context.status_code == 200, context.text
        assert context.json()["excerpts"]
        assert context.json()["mastery_inference"] is False
        assert "不可信" in context.json()["trust_boundary"]
        chinese_context = client.get("/api/knowledge-library/context", params={"query": "请解释隐式特征空间"})
        assert chinese_context.status_code == 200, chinese_context.text
        assert chinese_context.json()["excerpts"][0]["relevance_score"] > 0

        unrelated = client.post("/api/knowledge-library/sources/upload", files={
            "file": ("network-notes.md", b"# TCP\n\n## Congestion control\nTCP adapts its congestion window after loss.\n", "text/markdown"),
        })
        assert unrelated.status_code == 200, unrelated.text
        unrelated_id = unrelated.json()["id"]
        assert client.post(f"/api/knowledge-library/sources/{unrelated_id}/process").status_code == 200
        attached_context = client.get("/api/knowledge-library/context", params={
            "query": "value function",
            "source_ids": str(source_id),
        })
        assert attached_context.status_code == 200, attached_context.text
        assert attached_context.json()["selection_mode"] == "conversation_attachments"
        assert attached_context.json()["selected_source_ids"] == [source_id]
        assert all(item["source_id"] == source_id for item in attached_context.json()["excerpts"])

        async def mutation_count() -> int:
            async with async_session() as db:
                event_ids = list((await db.execute(select(EvidenceEvent.id).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type.in_({"knowledge_source_added", "knowledge_source_processed"}),
                ))).scalars().all())
                return len(list((await db.execute(select(KernelMutation.id).where(
                    KernelMutation.event_id.in_(event_ids),
                ))).scalars().all())) if event_ids else 0

        assert asyncio.run(mutation_count()) == 0


def test_task_files_are_persisted_answer_safe_and_audited():
    with TestClient(app) as client:
        learner_id = _register(client)
        created = client.post("/api/learning-tasks", json={
            "title": "理解朴素贝叶斯",
            "objective": "能够解释条件独立假设并完成一道独立验证题",
            "estimated_minutes": 25,
            "client_request_id": f"task-{uuid.uuid4().hex}",
        })
        assert created.status_code == 200, created.text
        task = created.json()
        generated = client.post(f"/api/learning-files/tasks/{task['id']}/generate", json={
            "source_text": "朴素贝叶斯使用贝叶斯公式，并对给定类别下的特征作条件独立假设。",
            "expected_version": task["version"],
            "client_request_id": f"files-{uuid.uuid4().hex}",
        })
        assert generated.status_code == 200, generated.text
        body = generated.json()
        lecture_ref = next(item for item in body["artifact_refs"] if item["type"] == "managed_lecture")
        questions_ref = next(item for item in body["artifact_refs"] if item["type"] == "concept_question_set")

        library = client.get("/api/learning-files")
        assert library.status_code == 200, library.text
        assert any(item["id"] == lecture_ref["id"] for item in library.json()["lectures"])
        assert any(item["checkpoint_id"] == body["checkpoint_id"] for item in library.json()["practices"])

        lecture = client.get(f"/api/learning-files/lecture/{lecture_ref['id']}")
        assert lecture.status_code == 200
        assert lecture.json()["sections"]
        assert lecture.json()["mastery_inference"] is False
        practice = client.get(f"/api/learning-files/practice/questions-{body['checkpoint_id']}")
        assert practice.status_code == 200
        assert practice.json()["answers_hidden"] is True
        assert practice.json()["questions"]
        assert "answer_indexes" not in practice.json()["questions"][0]

        opened = client.post(f"/api/learning-files/lecture/{lecture_ref['id']}/opened", json={"conversation_id": "chat-test"})
        attached = client.post(f"/api/learning-files/practice/questions-{body['checkpoint_id']}/attached", json={"conversation_id": "chat-test", "sheet_id": "sheet-test"})
        assert opened.status_code == attached.status_code == 200
        assert opened.json()["mastery_unchanged"] is True

        async def access_mutations() -> int:
            async with async_session() as db:
                event_ids = list((await db.execute(select(EvidenceEvent.id).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type.in_({"learning_file_generated", "learning_file_opened", "learning_file_attached_to_chat"}),
                ))).scalars().all())
                return len(list((await db.execute(select(KernelMutation.id).where(
                    KernelMutation.event_id.in_(event_ids),
                ))).scalars().all())) if event_ids else 0

        assert asyncio.run(access_mutations()) == 0
