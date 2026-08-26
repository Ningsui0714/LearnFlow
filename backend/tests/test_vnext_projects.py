import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session
from app.main import app
from app.models.learning import AgentSession, EvidenceEvent, KernelMutation, LearningTask
from app.models.project import Checkpoint, Project, Roadmap


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


def _create(client: TestClient) -> dict:
    name = f"RAG Agent 学徒项目 {uuid.uuid4().hex[:6]}"
    response = client.post("/api/vnext-projects", json={
        "name": name,
        "objective": "理解检索、上下文组装与评测，并实现一个可运行的 RAG Agent",
        "expected_outcome": "一个带离线评测的可运行仓库",
        "user_level": "intermediate",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_project_creation_is_topic_locked_and_does_not_invent_checkpoints(client: TestClient):
    workspace = _create(client)
    assert workspace["schema_version"] == "vnext.project.v1"
    assert workspace["project_tutor"]["mode"] == "learning_plan"
    assert workspace["roadmap"]["checkpoints"] == []
    assert workspace["boundaries"]["planning_requires_confirmation"] is True
    assert workspace["boundaries"]["file_generation_is_not_mastery"] is True

    mismatch = client.post(f"/api/vnext-projects/{workspace['project']['id']}/roadmap/apply", json={
        "project_theme": "无关的操作系统课程",
        "rationale": "错误主题",
        "checkpoints": [{
            "key": "start", "title": "开始", "objective": "开始",
            "success_criteria": ["完成"], "prerequisites": [], "estimated_minutes": 30,
        }],
        "client_action_id": f"mismatch-{uuid.uuid4().hex}",
    })
    assert mismatch.status_code == 422


def test_confirmed_roadmap_creates_checkpoint_sessions_and_formal_tasks(client: TestClient):
    workspace = _create(client)
    project = workspace["project"]
    response = client.post(f"/api/vnext-projects/{project['id']}/roadmap/apply", json={
        "project_theme": project["name"],
        "rationale": "先做最小检索闭环，再加入可重复的离线评测，始终服务目标仓库。",
        "checkpoints": [
            {
                "key": "retrieval-loop", "title": "最小检索闭环",
                "objective": "实现加载、切分、检索与回答的最小闭环",
                "prerequisites": [],
                "success_criteria": ["能够解释每个组件的输入输出", "仓库可以离线运行"],
                "estimated_minutes": 90,
            },
            {
                "key": "evaluation", "title": "离线评测与误差分析",
                "objective": "构建小型评测集并分析检索与回答错误",
                "prerequisites": ["retrieval-loop"],
                "success_criteria": ["评测可重复", "能区分检索错误与生成错误"],
                "estimated_minutes": 120,
            },
        ],
        "client_action_id": f"roadmap-{uuid.uuid4().hex}",
    })
    assert response.status_code == 200, response.text
    applied = response.json()
    checkpoints = applied["roadmap"]["checkpoints"]
    assert len(checkpoints) == 2
    assert checkpoints[1]["prerequisites"] == [checkpoints[0]["id"]]
    assert all(item["session_id"] for item in checkpoints)
    assert all(item["learning_task"]["origin_kind"] == "checkpoint" for item in checkpoints)
    assert all(item["learning_task"]["project_id"] == project["id"] for item in checkpoints)

    context = client.get(
        f"/api/vnext-projects/{project['id']}/agent-context",
        params={"checkpoint_id": checkpoints[0]["id"], "query": "检索闭环"},
    )
    assert context.status_code == 200, context.text
    packet = context.json()
    assert packet["project"]["name"] == project["name"]
    assert packet["checkpoint_id"] == checkpoints[0]["id"]
    assert packet["tool_policy"]["roadmap_write_requires_user_confirmation"] is True
    assert packet["five_kernel_context"]["scope"]["project_id"] == project["id"]

    free = client.post(f"/api/vnext-projects/{project['id']}/sessions", json={
        "kind": "free", "title": "项目里的架构讨论",
        "client_action_id": f"free-{uuid.uuid4().hex}",
    })
    assert free.status_code == 200, free.text
    refreshed = client.get(f"/api/vnext-projects/{project['id']}").json()
    assert any(item["session_id"] == free.json()["session_id"] for item in refreshed["free_sessions"])
    resumed_tutor = client.post("/api/agent/sessions", json={
        "session_type": "project", "project_id": project["id"], "create_new": False,
    })
    assert resumed_tutor.status_code == 200, resumed_tutor.text
    assert resumed_tutor.json()["id"] == workspace["project_tutor"]["session_id"]
    assert resumed_tutor.json()["id"] != free.json()["session_id"]

    async def inspect():
        async with async_session() as db:
            roadmap = (await db.execute(select(Roadmap).where(Roadmap.project_id == project["id"]))).scalar_one()
            checkpoint_rows = list((await db.execute(select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id))).scalars())
            task_rows = list((await db.execute(select(LearningTask).where(LearningTask.project_id == project["id"]))).scalars())
            session_rows = list((await db.execute(select(AgentSession).where(AgentSession.project_id == project["id"]))).scalars())
            event_rows = list((await db.execute(select(EvidenceEvent).where(EvidenceEvent.project_id == project["id"]))).scalars())
            mutations = list((await db.execute(select(KernelMutation).join(
                EvidenceEvent, EvidenceEvent.id == KernelMutation.event_id,
            ).where(EvidenceEvent.project_id == project["id"]))).scalars())
            return checkpoint_rows, task_rows, session_rows, event_rows, mutations

    checkpoint_rows, task_rows, session_rows, event_rows, mutations = asyncio.run(inspect())
    assert len(checkpoint_rows) == 2
    assert len(task_rows) == 2
    assert any((item.context_summary or {}).get("role") == "project_tutor" for item in session_rows)
    assert any((item.context_summary or {}).get("role") == "project_free" for item in session_rows)
    assert {item.event_type for item in event_rows} >= {"project_created", "roadmap_applied", "project_free_conversation_created"}
    assert {item.kernel_name for item in mutations} <= {"structure", "value"}


def test_roadmap_requires_forward_only_prerequisites(client: TestClient):
    workspace = _create(client)
    project = workspace["project"]
    response = client.post(f"/api/vnext-projects/{project['id']}/roadmap/apply", json={
        "project_theme": project["name"], "rationale": "非法反向边",
        "checkpoints": [
            {"key": "a", "title": "关卡 A", "objective": "A 目标", "prerequisites": ["b"], "success_criteria": ["A"], "estimated_minutes": 20},
            {"key": "b", "title": "关卡 B", "objective": "B 目标", "prerequisites": [], "success_criteria": ["B"], "estimated_minutes": 20},
        ],
        "client_action_id": f"cycle-{uuid.uuid4().hex}",
    })
    assert response.status_code == 422
    assert "DAG" in response.text
