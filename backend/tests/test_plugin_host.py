import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.database import async_session
from app.main import app
from app.models.learning import AgentAction, EvidenceEvent, KernelMutation, UserAccount
from app.models.plugin import PluginObjectIndex, PluginRelease, PluginRun, PluginSnapshot
from app.services.plugin_host import (
    PluginWorkflowResult,
    canonical_hash,
    mark_interrupted_plugin_runs_failed,
    rebuild_snapshot_object_index,
    register_builtin_workflow,
)


PLUGIN_ID = "test_generic_plugin"


def _manifest(version: str) -> dict:
    return {
        "protocol": "learnflow.plugin-package.v1",
        "plugin_id": PLUGIN_ID,
        "version": version,
        "name": "Generic Host Test Plugin",
        "owner": "learning_design_agent",
        "scope": "project",
        "schema_version": "test-plugin.object.v1",
        "object_types": ["task"],
        "host_ports": ["project.read.v1", "action.propose.v1"],
        "workflows": [
            {"id": "generate", "mode": "write_snapshot", "host_ports": ["project.read.v1"]},
            {"id": "invalid", "mode": "write_snapshot", "host_ports": []},
            {"id": "spoof_source", "mode": "write_snapshot", "host_ports": []},
            {
                "id": "inspect",
                "mode": "read",
                "snapshot_input": "current",
                "host_ports": [],
            },
            {"id": "propose", "mode": "proposal", "host_ports": ["action.propose.v1"]},
            {"id": "upgrade", "mode": "migration", "host_ports": []},
        ],
        "tools": [{
            "id": "inspect",
            "mode": "read",
            "description": "Use when the Tutor needs a fixed test snapshot; never mutates it.",
            "workflow": "inspect",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }],
        "skills": [],
        "surfaces": [{
            "id": "test_project_panel",
            "slot": "project.context.tabs",
            "label": "Test Plugin",
            "schema": {
                "protocol": "learnflow.plugin-surface.v1",
                "id": "test_project_panel",
                "slot": "project.context.tabs",
                "body": {"type": "section", "children": [{"type": "status", "source": "instance.status"}]},
            },
        }],
        "events": [
            {"id": "package_generated", "kernel_targets": []},
            {"id": "release_upgraded", "kernel_targets": []},
        ],
        "config_schema": {
            "type": "object",
            "properties": {"max_items": {"type": "integer", "minimum": 1, "maximum": 20, "default": 7}},
            "additionalProperties": False,
        },
        "runners": {"darwin-arm64": "bin/darwin-arm64/runner"},
    }


@register_builtin_workflow(PLUGIN_ID, "generate")
async def _generate(context, input_data):
    project = await context.call_host_port("project.read.v1", {})
    value = {
        "id": "task:primary",
        "type": "task",
        "label": str(input_data.get("label") or "Primary Task"),
        "project_id": project["project"]["id"] if "project" in project else project["id"],
        "lifecycle": "active",
    }
    return PluginWorkflowResult(
        result={
            "generated": True,
            "observed_configuration": dict(input_data["plugin_configuration"]),
        },
        snapshot={
            "schema_version": "test-plugin.object.v1",
            "components": {"semantic-graph": {"nodes": [value], "edges": []}},
            "objects": [{
                "id": value["id"],
                "type": value["type"],
                "label": value["label"],
                "component": "semantic-graph",
                "json_pointer": "/nodes/0",
                "content_hash": canonical_hash(value),
                "lifecycle": "active",
                "references": [],
            }],
            "source_refs": [],
            "validation": {"valid": True, "stats": {"nodes": 1, "edges": 0}},
            "provenance": {"producer": "deterministic_test_handler"},
        },
        events=[{"id": "package_generated", "payload": {"test": True}}],
    )


@register_builtin_workflow(PLUGIN_ID, "inspect")
async def _inspect(_context, input_data):
    return {
        "result": {
            "snapshot_id": input_data["snapshot"]["id"],
            "root_hash": input_data["snapshot"]["root_hash"],
            "snapshot_ref": input_data["snapshot_ref"],
            "node_count": len(input_data["snapshot"]["components"]["semantic-graph"]["nodes"]),
        }
    }


@register_builtin_workflow(PLUGIN_ID, "propose")
async def _propose(context, input_data):
    proposal = await context.call_host_port("action.propose.v1", {
        "capability": "plan_learning_path",
        "object_refs": [input_data["object_ref"]],
        "target": {
            "project_id": context.project_id,
            "message": "请把固定岗位任务与能力节点转换为一条候选学习路线。",
        },
        "reason": "岗位快照提供了可核验的任务与能力依据。",
    })
    return {"result": {"proposal": proposal}}


@register_builtin_workflow(PLUGIN_ID, "invalid")
async def _invalid(_context, _input_data):
    value = {
        "id": "task:rejected",
        "type": "task",
        "label": "Must never be committed",
        "lifecycle": "active",
    }
    return PluginWorkflowResult(
        result={"generated": True},
        snapshot={
            "schema_version": "test-plugin.object.v1",
            "components": {"semantic-graph": {"nodes": [value]}},
            "objects": [{
                "id": value["id"],
                "type": value["type"],
                "component": "semantic-graph",
                "json_pointer": "/nodes/0",
                "content_hash": "0" * 64,
            }],
            "validation": {"valid": True},
            "provenance": {"producer": "malformed_test_handler"},
        },
    )


@register_builtin_workflow(PLUGIN_ID, "spoof_source")
async def _spoof_source(_context, _input_data):
    value = {
        "id": "task:spoofed-source",
        "type": "task",
        "label": "Must not trust runner provenance",
        "lifecycle": "candidate",
    }
    return PluginWorkflowResult(
        result={"generated": True},
        snapshot={
            "schema_version": "test-plugin.object.v1",
            "components": {"semantic-graph": {"nodes": [value]}},
            "objects": [{
                "id": value["id"],
                "type": value["type"],
                "label": value["label"],
                "component": "semantic-graph",
                "json_pointer": "/nodes/0",
                "content_hash": canonical_hash(value),
            }],
            "source_refs": [{
                "ref": "source:999@v1",
                "source_id": 999,
                "source_version_id": 999,
                "content_hash": "9" * 64,
                "authority_tier": "fabricated",
                "status": "ready",
            }],
            "validation": {"valid": True},
            "provenance": {"producer": "untrusted_runner"},
        },
    )


@register_builtin_workflow(PLUGIN_ID, "upgrade")
async def _upgrade(_context, input_data):
    if _context.release.version == "1.5.0":
        raise RuntimeError("target migration runner failed")
    assert input_data["snapshot_ref"]["snapshot_id"] == input_data["base_snapshot_id"]
    return {
        "status": "compatible",
        "result": {"compatible": True, "base_root_hash": input_data["snapshot"]["root_hash"]},
        "events": [{"id": "release_upgraded", "payload": {"compatible": True}}],
    }


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


async def _create_release(version: str) -> int:
    async with async_session() as db:
        existing = (await db.execute(select(PluginRelease).where(
            PluginRelease.plugin_id == PLUGIN_ID,
            PluginRelease.version == version,
        ))).scalar_one_or_none()
        if existing:
            return existing.id
        release = PluginRelease(
            plugin_id=PLUGIN_ID,
            version=version,
            package_protocol="learnflow.plugin-package.v1",
            manifest=_manifest(version),
            signature={"test": True},
            root_hash=canonical_hash({"plugin": PLUGIN_ID, "version": version}),
            package_artifact_uri=f"sha256:{'0' * 64}",
            runner_artifacts={},
            trust_state="built_in",
            status="active",
        )
        db.add(release)
        await db.commit()
        await db.refresh(release)
        return release.id


def _project(client: TestClient) -> int:
    response = client.post("/api/vnext-projects", json={
        "name": f"Plugin Host {uuid.uuid4().hex[:8]}",
        "objective": "Verify the generic plugin protocol",
        "expected_outcome": "An immutable plugin snapshot",
        "user_level": "intermediate",
    })
    assert response.status_code == 200, response.text
    return response.json()["project"]["id"]


def test_instance_configuration_grants_snapshot_objects_tools_and_surfaces(client: TestClient):
    project_id = _project(client)
    release_id = asyncio.run(_create_release("1.0.0"))

    invalid = client.put(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_id,
        "configuration": {"max_items": 0},
        "granted_host_ports": ["project.read.v1", "action.propose.v1"],
    })
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "plugin_configuration_invalid"

    enabled = client.put(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_id,
        "configuration": {"max_items": 5},
        "granted_host_ports": ["project.read.v1", "action.propose.v1"],
    })
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["instance"]["current_snapshot_id"] is None

    key = f"generate-{uuid.uuid4().hex}"
    missing_expected = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={"input": {"label": "Build contracts"}, "idempotency_key": key},
    )
    assert missing_expected.status_code == 409
    assert missing_expected.json()["detail"]["code"] == "expected_snapshot_required"

    generated = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={"input": {"label": "Build contracts"}, "idempotency_key": key, "expected_snapshot_id": None},
    )
    assert generated.status_code == 200, generated.text
    run = generated.json()["run"]
    snapshot_id = run["result_snapshot_id"]
    assert snapshot_id
    assert run["execution_boundary"]["filesystem_isolation"] is False
    assert run["execution_boundary"]["cpu_isolation"] is False
    assert run["result"]["observed_configuration"] == {"max_items": 5}

    inspected = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/inspect/runs",
        json={"input": {}, "idempotency_key": f"inspect-workflow-{uuid.uuid4().hex}"},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["run"]["result"]["snapshot_id"] == snapshot_id
    assert inspected.json()["run"]["result"]["node_count"] == 1

    replay = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={"input": {"label": "Build contracts"}, "idempotency_key": key, "expected_snapshot_id": None},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["run"]["result_snapshot_id"] == snapshot_id

    objects = client.get(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/objects")
    assert objects.status_code == 200, objects.text
    ref = objects.json()["objects"][0]["ref"]
    assert ref["object_id"] == "task:primary"
    assert objects.json()["objects"][0]["locator"] == {"component": "semantic-graph", "json_pointer": "/nodes/0"}
    resolved = client.get(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/objects/task:primary")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["object"]["label"] == "Build contracts"
    assert canonical_hash(resolved.json()["object"]) == ref["content_hash"]

    proposed = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/propose/runs",
        json={
            "input": {"object_ref": ref},
            "idempotency_key": f"proposal-{uuid.uuid4().hex}",
            "expected_snapshot_id": snapshot_id,
        },
    )
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["run"]["result"]["proposal"]
    assert proposal["status"] == "pending_confirmation"
    assert proposal["confirmation_url"] == f"/api/agent/actions/{proposal['action_id']}/confirm"
    action_card = client.get(f"/api/agent/actions/{proposal['action_id']}")
    assert action_card.status_code == 200
    assert action_card.json()["requires_confirmation"] is True

    async def inspect_proposal_action():
        async with async_session() as db:
            return await db.get(AgentAction, proposal["action_id"])

    action = asyncio.run(inspect_proposal_action())
    assert action is not None
    assert action.target["plugin_proposal"]["object_refs"] == [ref]
    assert action.capability == "plan_learning_path"

    other_project_id = _project(client)
    other_enabled = client.put(
        f"/api/projects/{other_project_id}/plugin-instances/{PLUGIN_ID}",
        json={
            "release_id": release_id,
            "configuration": {"max_items": 5},
            "granted_host_ports": ["action.propose.v1"],
        },
    )
    assert other_enabled.status_code == 200, other_enabled.text
    cross_project = client.post(
        f"/api/projects/{other_project_id}/plugin-instances/{PLUGIN_ID}/workflows/propose/runs",
        json={
            "input": {"object_ref": ref},
            "idempotency_key": f"cross-project-{uuid.uuid4().hex}",
            "expected_snapshot_id": None,
        },
    )
    assert cross_project.status_code == 403
    assert cross_project.json()["detail"]["code"] == "plugin_object_scope_mismatch"

    async def rebuild_index():
        async with async_session() as db:
            snapshot = await db.get(PluginSnapshot, snapshot_id)
            assert snapshot is not None
            await db.execute(delete(PluginObjectIndex).where(
                PluginObjectIndex.snapshot_id == snapshot_id,
            ))
            await db.commit()
            rebuilt = await rebuild_snapshot_object_index(db, snapshot)
            await db.commit()
            rows = list((await db.execute(select(PluginObjectIndex).where(
                PluginObjectIndex.snapshot_id == snapshot_id,
            ))).scalars().all())
            return rebuilt, rows

    rebuilt, rebuilt_rows = asyncio.run(rebuild_index())
    assert rebuilt == len(rebuilt_rows) == 1
    assert rebuilt_rows[0].object_id == ref["object_id"]
    assert rebuilt_rows[0].content_hash == ref["content_hash"]

    rejected = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/invalid/runs",
        json={
            "input": {},
            "idempotency_key": f"invalid-{uuid.uuid4().hex}",
            "expected_snapshot_id": snapshot_id,
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "plugin_object_locator_mismatch"
    snapshot_page = client.get(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/snapshots"
    ).json()
    assert snapshot_page["current_snapshot_id"] == snapshot_id
    assert [item["id"] for item in snapshot_page["snapshots"]] == [snapshot_id]

    async def rejected_runs():
        async with async_session() as db:
            return list((await db.execute(select(PluginRun).where(
                PluginRun.project_id == project_id,
                PluginRun.operation_id == "invalid",
            ))).scalars().all())

    assert [item.status for item in asyncio.run(rejected_runs())] == ["failed"]

    spoofed = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/spoof_source/runs",
        json={
            "input": {},
            "idempotency_key": f"spoof-{uuid.uuid4().hex}",
            "expected_snapshot_id": snapshot_id,
        },
    )
    assert spoofed.status_code == 409
    assert spoofed.json()["detail"]["code"] == "snapshot_source_ref_unverified"

    discovered = client.get(f"/api/projects/{project_id}/plugin-tools")
    assert discovered.status_code == 200
    assert [item["qualified_tool_id"] for item in discovered.json()["tools"]] == [f"{PLUGIN_ID}:inspect"]
    called = client.post(
        f"/api/projects/{project_id}/plugin-tools/{PLUGIN_ID}:inspect/calls",
        json={"input": {}, "snapshot_id": snapshot_id, "idempotency_key": f"inspect-{uuid.uuid4().hex}"},
    )
    assert called.status_code == 200, called.text
    assert called.json()["result"]["snapshot_id"] == snapshot_id
    assert called.json()["result"]["node_count"] == 1

    surfaces = client.get(f"/api/projects/{project_id}/plugin-surfaces?slot=project.context.tabs")
    assert surfaces.status_code == 200
    surface = surfaces.json()["surfaces"][0]
    assert surface["data"]["instance"]["status"] == "enabled"
    assert surface["data"]["snapshot"]["components"]["semantic-graph"]["nodes"][0]["id"] == "task:primary"

    conflict = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={"input": {"label": "Different"}, "idempotency_key": key, "expected_snapshot_id": snapshot_id},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_project_catalog_and_interrupted_run_recovery(client: TestClient):
    project_id = _project(client)
    release_id = asyncio.run(_create_release("3.0.0"))
    catalog = client.get(f"/api/projects/{project_id}/plugin-releases")
    assert catalog.status_code == 200, catalog.text
    entry = next(item for item in catalog.json()["releases"] if item["id"] == release_id)
    assert entry["config_schema"]["properties"]["max_items"]["default"] == 7
    assert entry["execution_boundary"]["filesystem_isolation"] is False
    assert "package_artifact_uri" not in entry
    assert "signature" not in entry
    architecture = client.get("/api/architecture/registry")
    assert architecture.status_code == 200, architecture.text
    projection = next(
        item for item in architecture.json()["dynamic_plugin_releases"]
        if item["release_id"] == release_id
    )
    assert projection["namespace"] == f"plugin:{PLUGIN_ID}"

    enabled = client.put(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_id,
        "configuration": {},
        "granted_host_ports": ["project.read.v1"],
    })
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["instance"]["configuration"] == {"max_items": 7}
    instance_id = enabled.json()["instance"]["id"]

    async def seed_and_recover():
        async with async_session() as db:
            row = PluginRun(
                learner_id=enabled.json()["instance"]["learner_id"],
                project_id=project_id,
                instance_id=instance_id,
                release_id=release_id,
                invocation_kind="workflow",
                operation_id="generate",
                status="running",
                idempotency_key=f"interrupted-{uuid.uuid4().hex}",
                request_hash="0" * 64,
                request={},
                contract={},
                execution_boundary={},
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            run_id = row.id
        await mark_interrupted_plugin_runs_failed()
        async with async_session() as db:
            return await db.get(PluginRun, run_id)

    recovered = asyncio.run(seed_and_recover())
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.error["code"] == "plugin_host_restarted"


def test_snapshot_envelope_versions_configuration_even_when_components_match(client: TestClient):
    project_id = _project(client)
    release_id = asyncio.run(_create_release("3.1.0"))
    enabled = client.put(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_id,
        "configuration": {"max_items": 5},
        "granted_host_ports": ["project.read.v1"],
    })
    assert enabled.status_code == 200, enabled.text
    first = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={
            "input": {"label": "Stable components"},
            "idempotency_key": f"envelope-a-{uuid.uuid4().hex}",
            "expected_snapshot_id": None,
        },
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["run"]["result_snapshot_id"]
    updated = client.patch(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "configuration": {"max_items": 6},
    })
    assert updated.status_code == 200, updated.text
    second = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={
            "input": {"label": "Stable components"},
            "idempotency_key": f"envelope-b-{uuid.uuid4().hex}",
            "expected_snapshot_id": first_id,
        },
    )
    assert second.status_code == 200, second.text
    second_id = second.json()["run"]["result_snapshot_id"]
    assert second_id != first_id

    async def snapshot_envelopes():
        async with async_session() as db:
            return await db.get(PluginSnapshot, first_id), await db.get(PluginSnapshot, second_id)

    old, new = asyncio.run(snapshot_envelopes())
    assert old is not None and new is not None
    assert old.validation["component_root_hash"] == new.validation["component_root_hash"]
    assert old.root_hash != new.root_hash
    assert old.provenance["host"]["configuration"] == {"max_items": 5}
    assert new.provenance["host"]["configuration"] == {"max_items": 6}


def test_publisher_revocation_is_admin_only_and_does_not_disable_built_in_packages(client: TestClient):
    project_id = _project(client)
    catalog = client.get(f"/api/projects/{project_id}/plugin-releases").json()["releases"]
    official = next(item for item in catalog if item["plugin_id"] == "role_capability_graph")
    assert official["execution_boundary"]["adapter"] == "builtin_agent_package"
    assert official["execution_boundary"]["operator_process_opt_in_required"] is False
    enabled = client.put(
        f"/api/projects/{project_id}/plugin-instances/role_capability_graph",
        json={
            "release_id": official["id"],
            "configuration": {},
            "granted_host_ports": ["project.read.v1", "source.read.v1"],
        },
    )
    assert enabled.status_code == 200, enabled.text
    assert client.get("/api/admin/plugin-publishers").status_code == 403

    async def set_legacy_role(role: str):
        async with async_session() as db:
            account = (await db.execute(select(UserAccount).where(
                UserAccount.username_normalized == "legacy-demo",
            ))).scalar_one()
            account.role = role
            await db.commit()

    asyncio.run(set_legacy_role("admin"))
    publishers = client.get("/api/admin/plugin-publishers")
    assert publishers.status_code == 200, publishers.text
    publisher = next(
        item for item in publishers.json()["publishers"]
        if item["publisher_key"] == "learnflow_official"
    )
    try:
        revoked = client.patch(
            f"/api/admin/plugin-publishers/{publisher['id']}",
            json={"trust_status": "revoked", "reason": "security drill"},
        )
        assert revoked.status_code == 200, revoked.text
        asyncio.run(set_legacy_role("user"))
        visible = client.get(f"/api/projects/{project_id}/plugin-releases")
        built_in = next(
            item for item in visible.json()["releases"]
            if item["plugin_id"] == "role_capability_graph"
        )
        assert built_in["trust_state"] == "built_in"
        generated = client.post(
            f"/api/projects/{project_id}/plugin-instances/role_capability_graph/workflows/generate/runs",
            json={
                "input": {"role_title": "安全工程师", "task_seeds": ["审计插件权限"]},
                "idempotency_key": f"revoked-{uuid.uuid4().hex}",
                "expected_snapshot_id": None,
            },
        )
        assert generated.status_code == 200, generated.text
        assert generated.json()["run"]["execution_boundary"]["adapter"] == "builtin_agent_package"
        assert client.get(f"/api/projects/{project_id}/plugin-surfaces").json()["surfaces"]
    finally:
        asyncio.run(set_legacy_role("admin"))
        restored = client.patch(
            f"/api/admin/plugin-publishers/{publisher['id']}",
            json={"trust_status": "trusted", "reason": "security drill complete"},
        )
        assert restored.status_code == 200, restored.text
        asyncio.run(set_legacy_role("user"))


def test_upgrade_is_atomic_disable_hides_capabilities_and_events_are_zero_kernel(client: TestClient):
    project_id = _project(client)
    release_v1 = asyncio.run(_create_release("1.0.1"))
    release_failing = asyncio.run(_create_release("1.5.0"))
    release_v2 = asyncio.run(_create_release("2.0.0"))
    enabled = client.put(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_v1,
        "configuration": {"max_items": 4},
        "granted_host_ports": ["project.read.v1"],
    })
    assert enabled.status_code == 200
    generated = client.post(
        f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}/workflows/generate/runs",
        json={"input": {"label": "Upgrade base"}, "idempotency_key": f"generate-{uuid.uuid4().hex}", "expected_snapshot_id": None},
    )
    assert generated.status_code == 200, generated.text
    snapshot_id = generated.json()["run"]["result_snapshot_id"]

    stale = client.patch(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_v2,
        "expected_snapshot_id": snapshot_id + 999,
        "upgrade_idempotency_key": f"upgrade-{uuid.uuid4().hex}",
    })
    assert stale.status_code == 409
    instances = client.get(f"/api/projects/{project_id}/plugin-instances").json()["instances"]
    assert instances[0]["release_id"] == release_v1

    failed_upgrade = client.patch(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_failing,
        "configuration": {"max_items": 9},
        "expected_snapshot_id": snapshot_id,
        "upgrade_idempotency_key": f"upgrade-fail-{uuid.uuid4().hex}",
    })
    assert failed_upgrade.status_code == 502
    unchanged = client.get(f"/api/projects/{project_id}/plugin-instances").json()["instances"][0]
    assert unchanged["release_id"] == release_v1
    assert unchanged["current_snapshot_id"] == snapshot_id
    assert unchanged["configuration"] == {"max_items": 4}

    upgraded = client.patch(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={
        "release_id": release_v2,
        "expected_snapshot_id": snapshot_id,
        "upgrade_idempotency_key": f"upgrade-{uuid.uuid4().hex}",
    })
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["instance"]["release_id"] == release_v2
    assert upgraded.json()["upgrade_run"]["status"] == "compatible"

    disabled = client.patch(f"/api/projects/{project_id}/plugin-instances/{PLUGIN_ID}", json={"status": "disabled"})
    assert disabled.status_code == 200
    assert client.get(f"/api/projects/{project_id}/plugin-tools").json()["tools"] == []
    assert client.get(f"/api/projects/{project_id}/plugin-surfaces").json()["surfaces"] == []

    async def inspect_evidence():
        async with async_session() as db:
            events = list((await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.project_id == project_id,
                EvidenceEvent.event_type.in_({
                    f"plugin:{PLUGIN_ID}:package_generated",
                    f"plugin:{PLUGIN_ID}:release_upgraded",
                }),
            ))).scalars().all())
            mutations = list((await db.execute(select(KernelMutation).where(
                KernelMutation.event_id.in_([item.id for item in events] or [-1]),
            ))).scalars().all())
            runs = list((await db.execute(select(PluginRun).where(PluginRun.project_id == project_id))).scalars().all())
            return events, mutations, runs

    events, mutations, runs = asyncio.run(inspect_evidence())
    assert {item.event_type for item in events} == {
        f"plugin:{PLUGIN_ID}:package_generated",
        f"plugin:{PLUGIN_ID}:release_upgraded",
    }
    assert mutations == []
    assert {item.status for item in runs} == {"completed", "compatible", "failed"}
