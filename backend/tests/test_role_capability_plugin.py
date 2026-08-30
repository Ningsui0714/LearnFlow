import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.database import async_session
from app.core.config import settings
from app.main import app
from app.models.learning import EvidenceEvent, KernelMutation
from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginRelease,
    PluginRun,
    PluginSnapshot,
)
from app.models.project import Project
from app.models.role_capability import (
    RoleCapabilityPackage,
    RoleCapabilityRun,
    RoleCapabilitySnapshot,
)
from app.services.bundled_plugins import (
    ROLE_PLUGIN_ID,
    ROLE_PLUGIN_ROOT_HASH,
    backfill_legacy_role_plugin,
    ensure_official_role_plugin_release,
)
from app.services.plugin_host import (
    PluginHostError,
    _release_schema,
    _validate_contract_value,
    resolve_indexed_object,
    snapshot_view,
)
from app.services.role_capability_plugin import (
    apply_iteration,
    compile_role_graph,
    create_snapshot,
    explain_role_graph,
    inspect_role_graph,
)
from app.services.plugin_runner import PluginProcessBroker


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


def test_official_workflow_output_schema_resolves_packaged_object_ref(client: TestClient):
    async def load_release():
        async with async_session() as db:
            release = await ensure_official_role_plugin_release(db)
            await db.commit()
            return release

    release = asyncio.run(load_release())
    schema_path = "schemas/workflow-output.schema.json"
    schema = _release_schema(release, schema_path)
    malformed = {
        "snapshot": {
            "schema_version": "role-capability.object.v1",
            "components": {},
            "objects": [{"id": "task:missing-label", "type": "task"}],
            "validation": {"valid": True},
            "provenance": {},
        }
    }
    with pytest.raises(PluginHostError) as caught:
        _validate_contract_value(
            malformed,
            schema,
            kind="output",
            release=release,
            schema_reference=schema_path,
        )
    assert caught.value.code == "plugin_output_schema_invalid"


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
    assert body["deprecation"]["deprecated"] is True
    assert body["deprecation"]["legacy_tables"] == "frozen_read_only"
    assert body["compatibility_grant"]["implicit_from_legacy_mutation_endpoint"] is True
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
    assert iterated_body["deprecated_implicit_expected_snapshot"] is True

    stale = client.post(f"/api/role-capability/projects/{project_id}/iterate", json={
        "objective": "验证过期基线保护",
        "target_ids": [role_id],
        "operations": [{
            "op": "update_node", "target_id": role_id,
            "summary": "这个请求不应覆盖新快照",
        }],
        "expected_snapshot_id": body["snapshot"]["id"],
        "idempotency_key": f"role-stale-{uuid.uuid4().hex}",
    })
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "snapshot_conflict"

    objects = client.get(
        f"/api/projects/{project_id}/plugin-instances/{ROLE_PLUGIN_ID}/objects",
        params={"snapshot_id": iterated_body["snapshot"]["id"]},
    )
    assert objects.status_code == 200, objects.text
    assert objects.json()["objects"]
    assert all(
        item["ref"]["snapshot_root_hash"] == iterated_body["snapshot"]["root_hash"]
        for item in objects.json()["objects"]
    )

    async def inspect_events():
        async with async_session() as db:
            events = list((await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.project_id == project_id,
                EvidenceEvent.event_type.in_({
                    "plugin:role_capability_graph:package_generated",
                    "plugin:role_capability_graph:snapshot_explained",
                    "plugin:role_capability_graph:snapshot_iterated",
                }),
            ))).scalars())
            mutations = list((await db.execute(select(KernelMutation).where(
                KernelMutation.event_id.in_([item.id for item in events]),
            ))).scalars()) if events else []
            legacy_counts = {
                "packages": (await db.execute(select(func.count(RoleCapabilityPackage.id)).where(
                    RoleCapabilityPackage.project_id == project_id,
                ))).scalar_one(),
                "snapshots": (await db.execute(select(func.count(RoleCapabilitySnapshot.id)).join(
                    RoleCapabilityPackage,
                    RoleCapabilityPackage.id == RoleCapabilitySnapshot.package_id,
                ).where(RoleCapabilityPackage.project_id == project_id))).scalar_one(),
                "runs": (await db.execute(select(func.count(RoleCapabilityRun.id)).where(
                    RoleCapabilityRun.project_id == project_id,
                ))).scalar_one(),
            }
            runs = list((await db.execute(select(PluginRun).where(
                PluginRun.project_id == project_id,
            ))).scalars())
            return events, mutations, legacy_counts, runs

    events, mutations, legacy_counts, runs = asyncio.run(inspect_events())
    assert {item.event_type for item in events} == {
        "plugin:role_capability_graph:package_generated",
        "plugin:role_capability_graph:snapshot_explained",
        "plugin:role_capability_graph:snapshot_iterated",
    }
    assert mutations == []
    assert legacy_counts == {"packages": 0, "snapshots": 0, "runs": 0}
    assert all(run.execution_boundary["filesystem_isolation"] is False for run in runs)
    assert all(run.execution_boundary["network_isolation"] is False for run in runs)


def test_official_agent_package_runs_when_native_plugin_execution_is_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "plugin_execution_mode", "disabled")

    async def reject_native_runner(*_args, **_kwargs):
        raise AssertionError("official Agent Package must not start the native runner")

    monkeypatch.setattr(PluginProcessBroker, "run", reject_native_runner)
    created = client.post("/api/vnext-projects", json={
        "name": f"内置岗位包 {uuid.uuid4().hex[:6]}",
        "objective": "验证官方插件默认可运行",
        "expected_outcome": "形成岗位快照",
        "user_level": "intermediate",
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["project"]["id"]
    generated = client.post(f"/api/role-capability/projects/{project_id}/generate", json={
        "role_title": "大模型应用工程师",
        "task_seeds": ["设计并验证 Agent 工具契约"],
        "source_ids": [],
        "idempotency_key": f"builtin-agent-package-{uuid.uuid4().hex}",
    })
    assert generated.status_code == 200, generated.text

    async def load_run():
        async with async_session() as db:
            return await db.get(PluginRun, generated.json()["run_id"])

    run = asyncio.run(load_run())
    assert run is not None
    assert run.execution_boundary["adapter"] == "builtin_agent_package"
    assert run.execution_boundary["operator_process_opt_in_required"] is False
    assert run.execution_boundary["in_process"] is True


def test_bundled_release_is_installed_and_legacy_rows_migrate_idempotently(
    client: TestClient,
):
    created = client.post("/api/vnext-projects", json={
        "name": f"岗位旧数据迁移 {uuid.uuid4().hex[:6]}",
        "objective": "验证 v21 到 v22 的只读迁移",
        "expected_outcome": "通用快照和可重建对象索引",
        "user_level": "intermediate",
    })
    assert created.status_code == 200, created.text
    project_id = created.json()["project"]["id"]

    async def migrate_and_inspect():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            assert project is not None
            release = await ensure_official_role_plugin_release(db)
            assert release.root_hash == ROLE_PLUGIN_ROOT_HASH
            assert release.trust_state == "built_in"
            assert release.runner_artifacts["runners"] == {}
            assert release.runner_artifacts["builtin_agent_package"].endswith(
                "role_capability_agent_package"
            )

            package = RoleCapabilityPackage(
                learner_id=project.learner_id,
                project_id=project.id,
                role_title="遗留 Agent 工程师",
                status="ready",
            )
            db.add(package)
            await db.flush()
            graph = compile_role_graph(
                role_title=package.role_title,
                role_summary="迁移前的岗位图谱",
                task_seeds=["设计工具协议", "验证回答质量"],
                source_refs=[],
                source_texts=[],
            )
            legacy = await create_snapshot(
                db,
                package,
                graph,
                [],
                {"source": "migration_test", "mastery_unchanged": True},
            )
            legacy_run = RoleCapabilityRun(
                learner_id=project.learner_id,
                project_id=project.id,
                package_id=package.id,
                kind="generate",
                status="completed",
                idempotency_key=f"legacy-migration-{uuid.uuid4().hex}",
                request={"role_title": package.role_title},
                contract={"protocol_version": "learnflow.role-capability.v1"},
                inspection=dict(legacy.validation or {}),
                result_snapshot_id=legacy.id,
                summary="遗留生成运行",
            )
            db.add(legacy_run)
            await db.commit()

            first = await backfill_legacy_role_plugin(db, release)
            await db.commit()
            await db.refresh(package)
            instance = (await db.execute(select(PluginInstance).where(
                PluginInstance.project_id == project.id,
                PluginInstance.plugin_id == ROLE_PLUGIN_ID,
            ))).scalar_one()
            migrated = await db.get(PluginSnapshot, instance.current_snapshot_id)
            assert migrated is not None
            edge_index = (await db.execute(select(PluginObjectIndex).where(
                PluginObjectIndex.snapshot_id == migrated.id,
                PluginObjectIndex.object_type == "semantic_edge",
            ).limit(1))).scalar_one()
            resolved_edge = resolve_indexed_object(migrated, edge_index)
            materialized = snapshot_view(migrated, include_component_data=True)
            migration_map = materialized["components"]["reference-migrations"]

            second = await backfill_legacy_role_plugin(db, release)
            await db.commit()
            migrated_count = (await db.execute(select(func.count(PluginSnapshot.id)).where(
                PluginSnapshot.instance_id == instance.id,
            ))).scalar_one()
            migrated_legacy_run = (await db.execute(select(PluginRun).where(
                PluginRun.instance_id == instance.id,
                PluginRun.idempotency_key == f"migration:v22:role-run:{legacy_run.id}",
            ))).scalar_one()
            return {
                "first": first,
                "second": second,
                "package_status": package.status,
                "instance_status": instance.status,
                "legacy": legacy,
                "migrated": migrated,
                "edge_index": edge_index,
                "resolved_edge": resolved_edge,
                "migration_map": migration_map,
                "migrated_count": migrated_count,
                "migrated_legacy_run": migrated_legacy_run,
            }

    result = asyncio.run(migrate_and_inspect())
    assert result["first"]["instances"] == 1
    assert result["first"]["snapshots"] == 1
    assert result["first"]["runs"] == 2
    assert result["second"]["skipped"] == 1
    assert result["migrated_count"] == 1
    assert result["package_status"] == "frozen_read_only"
    assert result["instance_status"] == "disabled"
    assert result["migrated"].parent_snapshot_id is None
    assert result["migrated_legacy_run"].result_snapshot_id == result["migrated"].id
    assert result["migrated_legacy_run"].operation_id == "generate"
    assert result["migration_map"]["legacy_snapshot_id"] == result["legacy"].id
    assert result["migration_map"]["legacy_root_hash"] == result["legacy"].root_hash
    assert result["migrated"].root_hash == result["legacy"].root_hash
    assert result["migrated"].validation["snapshot_root_protocol"] == "legacy-role-root-v1"
    assert len(result["migrated"].validation["component_root_hash"]) == 64
    assert result["edge_index"].component == "semantic-graph"
    assert result["resolved_edge"]["object_type"] == "semantic_edge"
    assert result["resolved_edge"]["type"] in {
        "owns_task", "requires_capability", "requires_knowledge_skill",
    }
