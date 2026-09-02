from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import func, select

from app.db.database import async_session
from app.main import app
from app.models.learning import EvidenceEvent, KernelMutation, LearningTask
from app.models.project import Chunk, LearningTaskCandidateArtifact, Project, Source, SourceVersion
from app.services.xingchen_learning_task_candidates import (
    LearningTaskBundleGateway,
    LearningTaskIntegrationError,
    XingchenCredentials,
    XingchenWorkflowClient,
    build_source_snapshot,
    candidate_audit_view,
    generate_candidate,
    validate_candidate,
    validate_integration_bundle,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


def _create_project(client: TestClient, title: str = "企业服务部署") -> int:
    response = client.post("/api/vnext-projects", json={
        "name": f"{title}-{uuid.uuid4().hex[:6]}",
        "objective": f"完成{title}并留下可复核交付证据",
        "expected_outcome": "一个可验收的任务交付包",
        "user_level": "intermediate",
    })
    assert response.status_code == 200, response.text
    return response.json()["project"]["id"]


async def _seed_source(project_id: int, *, chunks: int = 2, text: str = "部署前核对环境") -> int:
    async with async_session() as db:
        source = Source(
            project_id=project_id, type="inline", url=f"source-{uuid.uuid4().hex}.md",
            status="processed", meta_data={},
        )
        db.add(source)
        await db.flush()
        version = SourceVersion(
            source_id=source.id, version=1, content_hash=uuid.uuid4().hex * 2,
            status="active", authority_tier="learner_owned", source_role="project_reference",
        )
        db.add(version)
        await db.flush()
        source.meta_data = {"active_source_version_id": version.id}
        for index in range(chunks):
            db.add(Chunk(
                source_id=source.id, source_version_id=version.id, index=index,
                content=f"来源片段 {index}：{text}，部署后使用独立命令检查服务状态与交付记录。",
            ))
        await db.commit()
        return version.id


def _bundle(task_card_id: str, *, citation_id: str = "", task_title: str = "Nginx 部署与验收") -> dict:
    knowledge = []
    skills = []
    steps = []
    names = ["核对环境与任务边界", "实施核心部署操作", "独立复验并归档交付"]
    for index, name in enumerate(names, start=1):
        knowledge_id = f"kp_{index}"
        skill_id = f"sp_{index}"
        knowledge.append({
            "knowledge_id": knowledge_id, "name": f"{name}知识", "scope": f"理解{name}的适用边界。",
            **({"citation_ids": [citation_id]} if citation_id else {}),
            "learning_resources": [{
                "resource_id": f"resource_{index}", "resource_name": f"{name}参考",
                "resource_type": "documentation", "resource_url": "https://example.com/guide",
            }],
        })
        skills.append({
            "skill_id": skill_id, "name": f"{name}技能", "observable_action": f"能够独立完成{name}。",
        })
        steps.append({
            "step_id": f"step_{index}", "name": name, "action": f"执行{name}并记录过程。",
            "deliverable": f"{name}记录", "check": f"使用可重复方法检查{name}结果。",
            "knowledge_point_ids": [knowledge_id], "skill_point_ids": [skill_id],
            **({"citation_ids": [citation_id]} if citation_id else {}),
        })
    return {
        "schema_version": "learning-task-conversion-integration-bundle-v1",
        "task_card_id": task_card_id,
        "verification_status": "workflow_verified",
        "task": {"work_task": {
            "enterprise_task_name": task_title,
            "teaching_task_name": f"{task_title}学习型工作任务",
            "teaching_task_description": f"完成{task_title}并提交过程记录和验收证据。",
            "work_situation": f"在隔离实训环境中完成{task_title}。",
            "tools": ["隔离测试环境", "命令行工具"],
            "safety_points": ["变更前保留可回退版本", "只在授权范围内操作"],
            "acceptance_tests": ["所有步骤产物齐全", "独立复验结果与预期一致"],
            "task_steps": steps, "knowledge_points": knowledge, "skill_points": skills,
        }},
    }


def _credentials() -> XingchenCredentials:
    return XingchenCredentials(
        app_id="test-app", api_key="test-key", api_secret="test-secret", flow_id="fixed-flow",
        base_url="https://xingchen.example", timeout_seconds=5,
    )


def _clients(bundle: dict, captured: list[dict] | None = None):
    async def provider_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        provider_input = json.loads(body["parameters"]["AGENT_USER_INPUT"])
        if captured is not None:
            captured.append(provider_input)
        return httpx.Response(200, json={
            "code": 0, "id": f"run-{len(captured or [])}",
            "choices": [{"delta": {"content": f'/tasks/{bundle["task_card_id"]} {json.dumps(bundle, ensure_ascii=False)}'}}],
        })

    async def bundle_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bundle)

    return (
        XingchenWorkflowClient(credentials=_credentials(), transport=httpx.MockTransport(provider_handler)),
        LearningTaskBundleGateway(
            base_url="https://bundle.example", transport=httpx.MockTransport(bundle_handler),
            service_token="test-bundle-token", allow_test_url=True,
        ),
    )


async def _project(project_id: int) -> Project:
    async with async_session() as db:
        project = await db.get(Project, project_id)
        assert project is not None
        return project


def test_source_versions_are_pinned_and_their_segments_really_enter_provider_input(client: TestClient):
    project_id = _create_project(client)
    version_id = asyncio.run(_seed_source(project_id, chunks=3))

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            snapshot = await build_source_snapshot(
                db, project, source_version_ids=[version_id], max_segments=2,
            )
            citation_id = snapshot.segments[0]["citationId"]
            captured: list[dict] = []
            workflow, gateway = _clients(_bundle("ltc_grounded", citation_id=citation_id), captured)
            before = {
                "events": await db.scalar(select(func.count(EvidenceEvent.id))),
                "mutations": await db.scalar(select(func.count(KernelMutation.id))),
                "tasks": await db.scalar(select(func.count(LearningTask.id))),
            }
            candidate = await generate_candidate(
                db, project=project, learner_id=project.learner_id,
                request_id=f"request-{uuid.uuid4().hex}", task_title="Nginx 部署与验收",
                task_description="部署静态站点并独立验收。", upstream_task=None,
                source_version_ids=[version_id], target_step_count=6, max_source_segments=2,
                workflow_client=workflow, bundle_gateway=gateway,
            )
            after = {
                "events": await db.scalar(select(func.count(EvidenceEvent.id))),
                "mutations": await db.scalar(select(func.count(KernelMutation.id))),
                "tasks": await db.scalar(select(func.count(LearningTask.id))),
            }
            return snapshot, captured, candidate, before, after

    snapshot, captured, candidate, before, after = asyncio.run(run())
    assert captured[0]["schema_version"] == "learnflow.xingchen-learning-task-request.v1"
    assert captured[0]["source_snapshot"]["root_hash"] == snapshot.root_hash
    assert captured[0]["source_segments"][0]["text"].startswith("来源片段")
    assert captured[0]["source_segments"][0]["citationId"] == candidate["citations"][0]["citationId"]
    assert candidate["groundingStatus"] == "grounded"
    assert candidate["coverage"]["source"]["truncated"] is True
    assert candidate["coverage"]["source"]["omittedSegmentCount"] == 1
    assert candidate["sourceBindings"][0]["sourceVersionId"] == version_id
    assert candidate["lifecycle"] == "candidate"
    assert candidate["confirmationStatus"] == "unconfirmed"
    assert candidate["rootHash"] == candidate["sourceSnapshot"]["rootHash"]
    assert candidate["validation"]["kernelWrites"] == 0
    assert before == after
    serialized = json.dumps(candidate)
    assert "test-key" not in serialized and "test-secret" not in serialized and "test-app" not in serialized


def test_different_selected_source_versions_change_the_actual_provider_request(client: TestClient):
    project_id = _create_project(client)
    linux_version = asyncio.run(_seed_source(project_id, chunks=1, text="Linux 服务必须使用 systemd 启动"))
    container_version = asyncio.run(_seed_source(project_id, chunks=1, text="容器服务必须通过健康检查端点验收"))
    captured: list[dict] = []
    workflow, gateway = _clients(_bundle("ltc_source_diff"), captured)

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            for source_version_id in (linux_version, container_version):
                await generate_candidate(
                    db, project=project, learner_id=project.learner_id,
                    request_id=f"request-{uuid.uuid4().hex}", task_title="部署服务并验收",
                    task_description="", upstream_task=None,
                    source_version_ids=[source_version_id], target_step_count=6, max_source_segments=8,
                    workflow_client=workflow, bundle_gateway=gateway,
                )

    asyncio.run(run())
    assert len(captured) == 2
    assert captured[0]["source_segments"][0]["sourceVersionId"] == linux_version
    assert captured[1]["source_segments"][0]["sourceVersionId"] == container_version
    assert captured[0]["source_segments"][0]["text"] != captured[1]["source_segments"][0]["text"]
    assert captured[0]["source_snapshot"]["root_hash"] != captured[1]["source_snapshot"]["root_hash"]


def test_request_id_is_idempotent_and_conflicts_on_different_input(client: TestClient):
    project_id = _create_project(client)
    request_id = f"request-{uuid.uuid4().hex}"
    captured: list[dict] = []
    workflow, gateway = _clients(_bundle("ltc_idempotent"), captured)

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            kwargs = dict(
                db=db, project=project, learner_id=project.learner_id, request_id=request_id,
                task_title="发布 Python 服务", task_description="", upstream_task=None,
                source_version_ids=[], target_step_count=6, max_source_segments=8,
                workflow_client=workflow, bundle_gateway=gateway,
            )
            first = await generate_candidate(**kwargs)
            second = await generate_candidate(**kwargs)
            with pytest.raises(LearningTaskIntegrationError) as conflict:
                await generate_candidate(**{**kwargs, "task_title": "不同任务"})
            return first, second, conflict.value

    first, second, conflict = asyncio.run(run())
    assert first["candidateId"] == second["candidateId"]
    assert len(captured) == 1
    assert conflict.status_code == 409
    assert conflict.code == "idempotency_conflict"


def test_no_sources_is_explicitly_ungrounded_and_never_invents_citations(client: TestClient):
    project_id = _create_project(client)
    workflow, gateway = _clients(_bundle("ltc_ungrounded"))

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            return await generate_candidate(
                db, project=project, learner_id=project.learner_id,
                request_id=f"request-{uuid.uuid4().hex}", task_title="Nginx 部署与验收",
                task_description="", upstream_task=None, source_version_ids=[],
                target_step_count=6, max_source_segments=8,
                workflow_client=workflow, bundle_gateway=gateway,
            )

    candidate = asyncio.run(run())
    assert candidate["groundingStatus"] == "ungrounded"
    assert candidate["citations"] == []
    assert any(item["code"] == "ungrounded" for item in candidate["warnings"])


def test_sources_received_but_not_cited_remain_unverified_instead_of_grounded(client: TestClient):
    project_id = _create_project(client)
    version_id = asyncio.run(_seed_source(project_id, chunks=1))
    captured: list[dict] = []
    workflow, gateway = _clients(_bundle("ltc_uncited_source"), captured)

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            return await generate_candidate(
                db, project=project, learner_id=project.learner_id,
                request_id=f"request-{uuid.uuid4().hex}", task_title="Nginx 部署与验收",
                task_description="", upstream_task=None, source_version_ids=[version_id],
                target_step_count=6, max_source_segments=8,
                workflow_client=workflow, bundle_gateway=gateway,
            )

    candidate = asyncio.run(run())
    assert captured[0]["source_segments"]
    assert candidate["groundingStatus"] == "source_supplied_unverified"
    assert candidate["citations"] == []
    assert any(
        item["code"] == "sources_supplied_without_citation_binding"
        for item in candidate["warnings"]
    )


def test_foreign_source_version_is_rejected_before_provider_call(client: TestClient):
    first_project = _create_project(client, "来源项目")
    second_project = _create_project(client, "目标项目")
    foreign_version = asyncio.run(_seed_source(first_project))

    async def run():
        async with async_session() as db:
            project = await db.get(Project, second_project)
            with pytest.raises(LearningTaskIntegrationError) as caught:
                await build_source_snapshot(
                    db, project, source_version_ids=[foreign_version], max_segments=8,
                )
            return caught.value

    error = asyncio.run(run())
    assert error.status_code == 422
    assert error.code == "source_version_unavailable"


def test_invalid_bundle_reports_precise_paths_and_repair_can_return_a_full_candidate(client: TestClient):
    invalid = _bundle("ltc_invalid")
    invalid["task"]["work_task"]["task_steps"] = invalid["task"]["work_task"]["task_steps"][:1]
    with pytest.raises(LearningTaskIntegrationError) as direct:
        validate_integration_bundle(invalid, "ltc_invalid")
    assert direct.value.status_code == 422
    assert direct.value.diagnostics["issues"][0]["path"] == "$.task.work_task.task_steps"

    project_id = _create_project(client)
    calls: list[dict] = []
    valid = _bundle("ltc_repaired")

    class RepairingWorkflow:
        async def run(self, provider_input, *, uid):
            calls.append(dict(provider_input))
            bundle = invalid if len(calls) == 1 else valid
            return {
                "runId": f"run-{len(calls)}", "workflowId": "fixed-flow",
                "content": json.dumps(bundle, ensure_ascii=False), "usage": {},
            }

    _unused, gateway = _clients(valid)

    async def run():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            return await generate_candidate(
                db, project=project, learner_id=project.learner_id,
                request_id=f"request-{uuid.uuid4().hex}", task_title="Nginx 部署与验收",
                task_description="", upstream_task=None, source_version_ids=[],
                target_step_count=6, max_source_segments=8,
                workflow_client=RepairingWorkflow(), bundle_gateway=gateway,
            )

    candidate = asyncio.run(run())
    assert len(calls) == 2
    assert calls[1]["repair"]["errorCode"] == "bundle_contract_invalid"
    assert calls[1]["repair"]["issues"][0]["path"] == "$.task.work_task.task_steps"
    assert candidate["validation"]["valid"] is True


def test_validator_rejects_dangling_dependencies_cycles_bad_urls_and_missing_safety():
    candidate = {
        "schemaVersion": "role-learning-task-candidate.v1", "candidateId": "ltc_validator",
        "groundingStatus": "ungrounded", "citations": [],
        "sourceSnapshot": {"rootHash": "a" * 64},
        "task": {
            "title": "高压电池包安装", "workContext": "在高压工位安装电池包", "learningObjective": "完成安装",
            "safetyRequirements": [],
            "steps": [
                {"id": "a", "title": "A", "action": "操作 A", "deliverables": ["A"], "successCriteria": ["A"], "prerequisiteStepIds": ["c"], "resources": []},
                {"id": "b", "title": "B", "action": "操作 B", "deliverables": ["B"], "successCriteria": ["B"], "prerequisiteStepIds": ["a"], "resources": [{"url": "javascript:alert(1)"}]},
                {"id": "c", "title": "C", "action": "操作 C", "deliverables": ["C"], "successCriteria": ["C"], "prerequisiteStepIds": ["b"], "resources": []},
            ],
        },
        "mappings": {"knowledgeTargets": [], "skillTargets": [], "capabilityTargets": []},
        "coverage": {"task": {"truncated": False, "omittedStepCount": 0}},
        "provenance": {"requestedTaskTitle": "高压电池包安装"},
    }
    with pytest.raises(LearningTaskIntegrationError) as caught:
        validate_candidate(candidate)
    issues = caught.value.diagnostics["issues"]
    assert any("安全" in item["reason"] for item in issues)
    assert any("成环" in item["reason"] for item in issues)
    assert any("URL" in item["reason"] for item in issues)

    structurally_invalid = deepcopy(candidate)
    structurally_invalid["task"]["safetyRequirements"] = ["只在断电隔离且授权的工位操作"]
    structurally_invalid["task"]["steps"][0]["prerequisiteStepIds"] = []
    structurally_invalid["task"]["steps"][1]["prerequisiteStepIds"] = []
    structurally_invalid["task"]["steps"][2]["prerequisiteStepIds"] = []
    structurally_invalid["task"]["steps"][2]["id"] = "b"
    structurally_invalid["task"]["steps"][0]["citationIds"] = ["citation_missing"]
    structurally_invalid["mappings"]["knowledgeTargets"] = [{
        "id": "knowledge_1", "derivedFromObjectIds": ["missing_step"],
        "citationIds": ["citation_missing"], "derivationKind": "direct_fact",
    }]
    structurally_invalid["validation"] = {"valid": True, "issues": []}
    with pytest.raises(LearningTaskIntegrationError) as refreshed:
        candidate_audit_view(structurally_invalid)
    refreshed_issues = refreshed.value.diagnostics["issues"]
    assert any("ID 必须唯一" in item["reason"] for item in refreshed_issues)
    assert any("映射必须指向" in item["reason"] for item in refreshed_issues)
    assert any("citationId" in item["reason"] for item in refreshed_issues)


def test_provider_failures_are_classified_without_returning_credentials():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"code": 429, "message": "limit"})

    client = XingchenWorkflowClient(
        credentials=_credentials(), transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskIntegrationError) as caught:
        asyncio.run(client.run({"schema_version": "test"}, uid="learner"))
    error = caught.value
    assert error.status_code == 429
    assert error.code == "provider_rate_limited"
    assert error.stage == "provider"
    assert error.retryable is True
    assert "test-key" not in json.dumps(error.payload())


@pytest.mark.parametrize((
    "upstream_status", "expected_status", "expected_code", "retryable", "who_fixes",
), [
    (401, 503, "provider_authorization_failed", False, "operator"),
    (502, 502, "provider_unavailable", True, "provider"),
    (504, 504, "provider_unavailable", True, "provider"),
])
def test_provider_statuses_keep_auth_unavailable_and_timeout_semantics_distinct(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
    retryable: bool,
    who_fixes: str,
):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"message": "provider failure"})

    client = XingchenWorkflowClient(
        credentials=_credentials(), transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskIntegrationError) as caught:
        asyncio.run(client.run({"schema_version": "test"}, uid="learner"))
    error = caught.value
    assert error.status_code == expected_status
    assert error.code == expected_code
    assert error.stage == "provider"
    assert error.retryable is retryable
    assert error.who_fixes == who_fixes
    assert "test-secret" not in json.dumps(error.payload())


def test_provider_transport_timeout_is_504_and_retryable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = XingchenWorkflowClient(
        credentials=_credentials(), transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskIntegrationError) as caught:
        asyncio.run(client.run({"schema_version": "test"}, uid="learner"))
    assert caught.value.status_code == 504
    assert caught.value.code == "provider_timeout"
    assert caught.value.retryable is True


def test_bundle_service_rejects_bare_public_ip():
    with pytest.raises(LearningTaskIntegrationError) as caught:
        LearningTaskBundleGateway(base_url="https://82.156.199.145")
    assert caught.value.status_code == 503
    assert caught.value.code == "integration_config_invalid"


def test_bundle_service_requires_and_sends_server_to_server_authentication():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-bundle-token"
        return httpx.Response(200, json=_bundle("ltc_authenticated_bundle"))

    gateway = LearningTaskBundleGateway(
        base_url="https://bundle.example",
        service_token="test-bundle-token",
        transport=httpx.MockTransport(handler),
        allow_test_url=True,
    )
    bundle = asyncio.run(gateway.read("ltc_authenticated_bundle"))
    assert bundle["task_card_id"] == "ltc_authenticated_bundle"


def test_candidate_read_api_is_project_and_account_scoped(client: TestClient):
    project_id = _create_project(client)
    workflow, gateway = _clients(_bundle("ltc_api_scope"))

    async def seed():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            return await generate_candidate(
                db, project=project, learner_id=project.learner_id,
                request_id=f"request-{uuid.uuid4().hex}", task_title="Nginx 部署与验收",
                task_description="", upstream_task=None, source_version_ids=[],
                target_step_count=6, max_source_segments=8,
                workflow_client=workflow, bundle_gateway=gateway,
            )

    candidate = asyncio.run(seed())
    base = f"/api/projects/{project_id}/integrations/xingchen/learning-task-candidates/{candidate['candidateId']}"
    assert client.get(base).status_code == 200
    assert client.get(f"{base}/evidence").json()["masteryInference"] is False
    assert client.get(f"{base}/audit").json()["kernelWrites"] == 0
    handoff = client.get(f"{base}/handoff").json()
    assert handoff["schemaVersion"] == "learnflow.personalized-learning-handoff.v1"
    assert handoff["taskSteps"] == candidate["task"]["steps"]
    assert handoff["returnContract"]["kernelWritesBeforeConfirmation"] == 0
    assert handoff["requiresUserConfirmation"] is True
    assert handoff["formalLearningTaskCreated"] is False

    with TestClient(app) as outsider:
        registered = outsider.post("/api/auth/register", json={
            "username": f"candidate_outsider_{uuid.uuid4().hex[:8]}",
            "password": "learnflow-pass-123",
            "display_name": "Candidate outsider",
            "education_stage": "undergraduate",
            "background": "用于验证候选对象的账号隔离",
            "focus_areas": ["系统集成"],
            "weekly_hours": 4,
            "preferred_modes": ["project"],
            "career_goal": "",
            "career_goal_status": "exploring",
        })
        assert registered.status_code == 200, registered.text
        assert outsider.get(base).status_code == 404


def test_candidate_table_contains_only_candidate_artifacts(client: TestClient):
    async def inspect():
        async with async_session() as db:
            rows = (await db.execute(select(LearningTaskCandidateArtifact))).scalars().all()
            assert rows
            assert all((row.candidate_json or {}).get("lifecycle") == "candidate" for row in rows)
            assert all((row.candidate_json or {}).get("confirmationStatus") == "unconfirmed" for row in rows)
            assert all((row.candidate_json or {}).get("provenance", {}).get("kernelTargets") == [] for row in rows)

    asyncio.run(inspect())
