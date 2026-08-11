from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import async_session
from app.main import app
from app.models.learning import AgentSession, EvidenceEvent, KernelMutation, LearningAttempt
from app.models.project import Checkpoint, Exercise, Project, Roadmap, WorkspaceOperation


DESKTOP_TOKEN = "workspace-test-token"
DESKTOP_HEADERS = {"X-LearnFlow-Desktop-Token": DESKTOP_TOKEN}


def registration(username: str):
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "Python 基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["explanation", "practice", "project"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def enable_desktop(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_token", DESKTOP_TOKEN)


def create_project(client: TestClient, name: str = "Local Workspace") -> dict:
    response = client.post("/api/projects", json={
        "name": name,
        "description": "desktop test",
        "user_level": "beginner",
    })
    assert response.status_code == 200
    return response.json()


def link_workspace(client: TestClient, project_id: int, root: Path, request_id: str = "link-1"):
    return client.post(
        f"/api/projects/{project_id}/workspace/link",
        headers=DESKTOP_HEADERS,
        json={
            "root_path": str(root),
            "platform": "test",
            "create": False,
            "client_request_id": request_id,
        },
    )


def test_browser_mode_hides_local_filesystem_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    monkeypatch.setattr(settings, "desktop_token", "")
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_browser_hidden"))
        assert registered.status_code == 200
        assert "desktop_auth_token" not in registered.json()
        project = create_project(client)
        response = link_workspace(client, project["id"], tmp_path)
        assert response.status_code == 404
        assert not (tmp_path / ".learnflow").exists()


def test_desktop_bearer_requires_the_per_launch_token(monkeypatch):
    enable_desktop(monkeypatch)
    with TestClient(app) as login_client, TestClient(app) as bearer_client:
        registered = login_client.post(
            "/api/auth/register",
            headers=DESKTOP_HEADERS,
            json=registration("workspace_desktop_bearer"),
        )
        assert registered.status_code == 200
        auth_token = registered.json()["desktop_auth_token"]
        bearer_headers = {
            **DESKTOP_HEADERS,
            "Authorization": f"Bearer {auth_token}",
        }
        assert bearer_client.get("/api/projects", headers=bearer_headers).status_code == 200
        assert bearer_client.get(
            "/api/projects", headers={"Authorization": f"Bearer {auth_token}"},
        ).status_code == 401


def test_link_tree_text_write_hash_and_zero_kernel_mutations(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('old')\n", encoding="utf-8")
    (root / "asset.bin").write_bytes(b"\x00\x01")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_writer"))
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        project = create_project(client)
        project_id = project["id"]
        linked = link_workspace(client, project_id, root)
        assert linked.status_code == 200, linked.text
        assert (root / ".learnflow" / "project.lfproject").exists()

        tree = client.get(
            f"/api/projects/{project_id}/workspace/tree", headers=DESKTOP_HEADERS,
        )
        assert tree.status_code == 200
        by_name = {item["name"]: item for item in tree.json()["nodes"]}
        assert by_name["main.py"]["kind"] == "workspace_text"
        assert by_name["asset.bin"]["kind"] == "workspace_binary"
        assert ".learnflow" not in by_name

        current = client.get(
            f"/api/projects/{project_id}/workspace/files/main.py", headers=DESKTOP_HEADERS,
        )
        assert current.status_code == 200
        base_hash = current.json()["sha256"]
        saved = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "print('new')\n",
                "base_hash": base_hash,
                "idempotency_key": "save-main-1",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "applied"
        assert (root / "main.py").read_text(encoding="utf-8") == "print('new')\n"
        repeated = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "should not replace\n",
                "base_hash": base_hash,
                "idempotency_key": "save-main-1",
            },
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == saved.json()["id"]

        (root / "main.py").write_text("external edit\n", encoding="utf-8")
        stale = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "stale proposal\n",
                "base_hash": saved.json()["result"]["sha256"],
                "idempotency_key": "save-main-stale",
            },
        )
        assert stale.status_code == 409

        async def operational_evidence():
            async with async_session() as db:
                event_ids = list((await db.execute(select(EvidenceEvent.id).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type.in_(["workspace_linked", "workspace_change_applied"]),
                ))).scalars().all())
                mutation_count = await db.scalar(select(func.count(KernelMutation.id)).where(
                    KernelMutation.event_id.in_(event_ids),
                )) if event_ids else 0
                return len(event_ids), mutation_count or 0

        event_count, mutation_count = asyncio.run(operational_evidence())
        assert event_count == 2
        assert mutation_count == 0


def test_agent_diff_requires_checkpoint_scope_and_explicit_confirmation(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    target = root / "lesson.py"
    target.write_text("value = 1\n", encoding="utf-8")
    (root / ".env.development").write_text("TOKEN=secret\n", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_agent_scope"))
        learner_id = registered.json()["learner_id"]
        project = create_project(client)
        project_id = project["id"]
        assert link_workspace(client, project_id, root).status_code == 200

        current = client.get(
            f"/api/projects/{project_id}/workspace/files/lesson.py", headers=DESKTOP_HEADERS,
        ).json()
        missing_scope = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "write",
                "target_path": "lesson.py",
                "content": "value = 2\n",
                "base_hash": current["sha256"],
                "idempotency_key": "agent-missing-scope",
            },
        )
        assert missing_scope.status_code == 400

        async def create_scope():
            async with async_session() as db:
                roadmap = Roadmap(project_id=project_id, raw_json={})
                db.add(roadmap)
                await db.flush()
                checkpoint = Checkpoint(
                    roadmap_id=roadmap.id,
                    title="Checkpoint",
                    order=1,
                    brief={},
                )
                db.add(checkpoint)
                await db.flush()
                session = AgentSession(
                    learner_id=learner_id,
                    session_type="checkpoint",
                    project_id=project_id,
                    checkpoint_id=checkpoint.id,
                    title="Checkpoint Tutor",
                )
                db.add(session)
                await db.commit()
                return checkpoint.id, session.id

        checkpoint_id, session_id = asyncio.run(create_scope())
        agent_read = client.get(
            f"/api/projects/{project_id}/workspace/agent-files/lesson.py",
            headers=DESKTOP_HEADERS,
            params={"checkpoint_id": checkpoint_id, "session_id": session_id},
        )
        assert agent_read.status_code == 200
        assert agent_read.json()["content"] == "value = 1\n"
        secret_read = client.get(
            f"/api/projects/{project_id}/workspace/agent-files/.env.development",
            headers=DESKTOP_HEADERS,
            params={"checkpoint_id": checkpoint_id, "session_id": session_id},
        )
        assert secret_read.status_code == 403
        secret_denied = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "create",
                "target_path": ".env.development",
                "content": "TOKEN=secret\n",
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "idempotency_key": "agent-secret-denied",
            },
        )
        assert secret_denied.status_code == 403
        proposed = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "write",
                "target_path": "lesson.py",
                "content": "value = 2\n",
                "base_hash": current["sha256"],
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "idempotency_key": "agent-write-1",
            },
        )
        assert proposed.status_code == 200, proposed.text
        proposal = proposed.json()
        assert proposal["status"] == "proposed"
        assert "-value = 1" in proposal["result"]["diff"]
        assert target.read_text(encoding="utf-8") == "value = 1\n"

        confirmed = client.post(
            f"/api/projects/{project_id}/workspace/operations/{proposal['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "applied"
        assert target.read_text(encoding="utf-8") == "value = 2\n"
        repeated = client.post(
            f"/api/projects/{project_id}/workspace/operations/{proposal['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == proposal["id"]


def test_traversal_links_protected_paths_delete_restore_and_user_isolation(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    (root / "delete-me.txt").write_text("recover me", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "outside-link.txt").symlink_to(outside)

    with TestClient(app) as alice, TestClient(app) as bob:
        alice.post("/api/auth/register", json=registration("workspace_owner_alice"))
        bob.post("/api/auth/register", json=registration("workspace_owner_bob"))
        project = create_project(alice, "Alice Workspace")
        project_id = project["id"]
        assert link_workspace(alice, project_id, root).status_code == 200

        assert bob.get(
            f"/api/projects/{project_id}/workspace/tree", headers=DESKTOP_HEADERS,
        ).status_code == 404
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/%2E%2E%2Foutside.txt",
            headers=DESKTOP_HEADERS,
        ).status_code in {400, 404}
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/.learnflow/project.lfproject",
            headers=DESKTOP_HEADERS,
        ).status_code == 403
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/outside-link.txt",
            headers=DESKTOP_HEADERS,
        ).status_code == 403

        current = alice.get(
            f"/api/projects/{project_id}/workspace/files/delete-me.txt", headers=DESKTOP_HEADERS,
        ).json()
        proposed = alice.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user",
                "operation": "delete",
                "target_path": "delete-me.txt",
                "base_hash": current["sha256"],
                "idempotency_key": "delete-1",
            },
        )
        assert proposed.status_code == 200
        assert (root / "delete-me.txt").exists()
        deleted = alice.post(
            f"/api/projects/{project_id}/workspace/operations/{proposed.json()['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert deleted.status_code == 200
        assert not (root / "delete-me.txt").exists()
        trash_path = root / deleted.json()["result"]["trash_path"]
        assert trash_path.exists()

        restore = alice.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user",
                "operation": "restore",
                "target_path": "delete-me.txt",
                "source_operation_id": deleted.json()["id"],
                "idempotency_key": "restore-1",
            },
        )
        assert restore.status_code == 200, restore.text
        restored = alice.post(
            f"/api/projects/{project_id}/workspace/operations/{restore.json()['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert restored.status_code == 200, restored.text
        assert (root / "delete-me.txt").read_text(encoding="utf-8") == "recover me"
        delete_history = alice.get(
            f"/api/projects/{project_id}/workspace/operations",
            params={"operation": "delete", "status": "applied"},
            headers=DESKTOP_HEADERS,
        )
        assert delete_history.status_code == 200
        assert delete_history.json()["operations"][0]["result"]["restorable"] is False

        async def operation_count():
            async with async_session() as db:
                return await db.scalar(select(func.count(WorkspaceOperation.id)).where(
                    WorkspaceOperation.project_id == project_id,
                ))

        assert asyncio.run(operation_count()) == 2


def test_python_runtime_and_bound_formal_submission_are_separate_evidence_paths(
    tmp_path, monkeypatch,
):
    enable_desktop(monkeypatch)
    root = tmp_path / "runtime-project"
    root.mkdir()
    script = root / "answer.py"
    script.write_text("import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else 2)\n", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_runtime_user"))
        learner_id = registered.json()["learner_id"]
        project = create_project(client, "Runtime Project")
        project_id = project["id"]
        assert link_workspace(client, project_id, root).status_code == 200

        configured = client.put(
            f"/api/projects/{project_id}/workspace/runtime/config",
            headers=DESKTOP_HEADERS,
            json={"interpreter_path": sys.executable},
        )
        assert configured.status_code == 200, configured.text
        assert configured.json()["configured"] is True
        assert "Python" in configured.json()["version"]

        syntax = client.post(
            f"/api/projects/{project_id}/workspace/runs",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user", "mode": "syntax", "path": "answer.py", "args": [],
                "confirmed": True, "idempotency_key": "syntax-answer-1",
            },
        )
        assert syntax.status_code == 200, syntax.text
        assert syntax.json()["status"] == "applied"
        assert syntax.json()["result"]["passed"] is True

        async def seed_exercise_scope():
            async with async_session() as db:
                roadmap = Roadmap(project_id=project_id, raw_json={})
                db.add(roadmap)
                await db.flush()
                checkpoint = Checkpoint(roadmap_id=roadmap.id, title="Runtime", order=1, brief={})
                db.add(checkpoint)
                await db.flush()
                exercise = Exercise(
                    checkpoint_id=checkpoint.id,
                    title="Bound answer",
                    starter_code="print(0)",
                    test_cases=[{"input": "", "expected": "2"}],
                    order=1,
                )
                session = AgentSession(
                    learner_id=learner_id, session_type="checkpoint",
                    project_id=project_id, checkpoint_id=checkpoint.id,
                    title="Checkpoint Tutor",
                )
                db.add_all([exercise, session])
                await db.commit()
                return checkpoint.id, exercise.id, session.id

        checkpoint_id, exercise_id, session_id = asyncio.run(seed_exercise_scope())
        proposed = client.post(
            f"/api/projects/{project_id}/workspace/runs",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent", "mode": "run", "path": "answer.py",
                "args": ["$(touch should-not-exist)"], "confirmed": True,
                "checkpoint_id": checkpoint_id, "session_id": session_id,
                "idempotency_key": "agent-run-answer-1",
            },
        )
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["status"] == "proposed"
        plan = proposed.json()["result"]["plan"]
        assert plan["script"] == "answer.py"
        assert plan["working_directory"] == str(root.resolve())
        assert plan["args"] == ["$(touch should-not-exist)"]
        assert "command" not in plan
        confirmed = client.post(
            f"/api/projects/{project_id}/workspace/operations/{proposed.json()['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert confirmed.status_code == 200, confirmed.text
        assert "$(touch should-not-exist)" in confirmed.json()["result"]["stdout"]
        assert not (root / "should-not-exist").exists()

        binding = client.put(
            f"/api/exercises/{exercise_id}/workspace-bindings",
            headers=DESKTOP_HEADERS,
            json={"path": "answer.py"},
        )
        assert binding.status_code == 200, binding.text
        assert binding.json()["bindings"][0]["path"] == "answer.py"

        script.write_text("print(2)\n", encoding="utf-8")
        submission_id = "formal-bound-submit-1"
        submitted = client.post(
            f"/api/exercises/{exercise_id}/submit",
            headers=DESKTOP_HEADERS,
            json={
                "code": "print(0)", "files": [], "client_submission_id": submission_id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["passed"] == 1
        replay = client.post(
            f"/api/exercises/{exercise_id}/submit",
            headers=DESKTOP_HEADERS,
            json={
                "code": "print(999)", "files": [], "client_submission_id": submission_id,
            },
        )
        assert replay.status_code == 200
        assert replay.json()["idempotent_replay"] is True
        assert replay.json()["attempt_id"] == submitted.json()["attempt_id"]
        monkeypatch.setattr(settings, "desktop_mode", False)
        monkeypatch.setattr(settings, "desktop_token", "")
        hidden_in_browser = client.post(
            f"/api/exercises/{exercise_id}/submit",
            json={
                "code": "print(2)", "files": [],
                "client_submission_id": "browser-must-not-read-binding",
            },
        )
        assert hidden_in_browser.status_code == 404
        enable_desktop(monkeypatch)

        async def verify_ledgers():
            async with async_session() as db:
                attempt = await db.get(LearningAttempt, submitted.json()["attempt_id"])
                binding_snapshot = (attempt.submission or {})["workspace_bindings"][0]
                run_events = list((await db.execute(select(EvidenceEvent).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type == "workspace_file_run",
                ))).scalars().all())
                run_event_ids = [item.id for item in run_events]
                run_mutations = list((await db.execute(select(KernelMutation).where(
                    KernelMutation.event_id.in_(run_event_ids),
                ))).scalars().all()) if run_event_ids else []
                assessment_events = list((await db.execute(select(EvidenceEvent).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type == "exercise_attempt_evaluated",
                    EvidenceEvent.payload["attempt_id"].as_integer() == attempt.id,
                ))).scalars().all())
                return binding_snapshot, len(run_events), len(run_mutations), len(assessment_events)

        snapshot, run_count, run_mutations, assessment_count = asyncio.run(verify_ledgers())
        assert snapshot["relative_path"] == "answer.py"
        assert snapshot["content"] == "print(2)\n"
        assert len(snapshot["sha256"]) == 64
        assert run_count == 2
        assert run_mutations == 0
        assert assessment_count == 1
