"""Deprecated compatibility routes for the official role graph plugin.

The legacy URL and response shape remain available, but this module is no
longer a persistence authority. Every run and snapshot is delegated to the
generic plugin host; the v21 role tables are read-only migration sources.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.plugin import PluginInstance, PluginRelease, PluginRun, PluginSnapshot
from app.models.project import Project
from app.services.auth import CurrentLearner, get_current_learner, require_owned_project
from app.services.bundled_plugins import ROLE_PLUGIN_ID, ensure_official_role_plugin_release
from app.services.plugin_host import (
    PluginHostError,
    enable_plugin_instance,
    execute_plugin_operation,
    snapshot_view,
)


router = APIRouter(prefix="/role-capability", tags=["Role Capability Plugin (deprecated alias)"])

_DEPRECATION = {
    "deprecated": True,
    "protocol": "learnflow.compatibility-alias.v1",
    "message": "该岗位专用 API 已弃用；请求已转发到通用 LearnFlow Plugin Host。",
    "replacement": {
        "instances": "/api/projects/{project_id}/plugin-instances",
        "workflows": (
            "/api/projects/{project_id}/plugin-instances/role_capability_graph/"
            "workflows/{workflow_id}/runs"
        ),
        "objects": (
            "/api/projects/{project_id}/plugin-instances/role_capability_graph/objects"
        ),
    },
    "legacy_tables": "frozen_read_only",
}


class GenerateRolePackageRequest(BaseModel):
    role_title: str = Field(min_length=2, max_length=255)
    role_summary: str = Field(default="", max_length=1200)
    source_ids: list[int] = Field(default_factory=list, max_length=20)
    task_seeds: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=160)


class ExplainRolePackageRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    snapshot_id: int | None = None


class IterationOperation(BaseModel):
    op: Literal["add_node", "update_node"]
    type: Literal["task", "capability", "knowledge_skill"] | None = None
    label: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=500)
    target_id: str = Field(default="", max_length=180)
    parent_id: str = Field(default="", max_length=180)
    lifecycle: Literal["accepted", "candidate", "deprecated"] | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class IterateRolePackageRequest(BaseModel):
    objective: str = Field(min_length=2, max_length=1000)
    target_ids: list[str] = Field(default_factory=list, max_length=40)
    operations: list[IterationOperation] = Field(default_factory=list, max_length=24)
    idempotency_key: str = Field(min_length=8, max_length=160)
    # The old route did not carry an optimistic-concurrency token. Keeping
    # this optional preserves wire compatibility; omission pins the current
    # snapshot and is explicitly disclosed in the response.
    expected_snapshot_id: int | None = None


def _raise_plugin_error(exc: PluginHostError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


async def _role_instance(
    db: AsyncSession,
    learner_id: int,
    project_id: int,
) -> PluginInstance | None:
    return (await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == learner_id,
        PluginInstance.project_id == project_id,
        PluginInstance.plugin_id == ROLE_PLUGIN_ID,
    ))).scalar_one_or_none()


async def _idempotent_expected_snapshot(
    db: AsyncSession,
    instance: PluginInstance,
    idempotency_key: str,
    default: int | None,
) -> int | None:
    """Keep a replay bound to the exact optimistic baseline of its first run."""

    existing = (await db.execute(select(PluginRun).where(
        PluginRun.instance_id == instance.id,
        PluginRun.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    return existing.expected_snapshot_id if existing is not None else default


async def _enable_compatibility_instance(
    db: AsyncSession,
    current: CurrentLearner,
    project: Project,
) -> PluginInstance:
    """Enable the bundled release for an explicit legacy workflow request.

    Calling the old mutation endpoint is treated as the learner's explicit
    request to use the capabilities that endpoint historically required. The
    response discloses this compatibility grant so new clients can move to the
    normal instance enablement UI.
    """

    release = await ensure_official_role_plugin_release(db)
    manifest = dict(release.manifest or {})
    existing = await _role_instance(db, current.learner.id, project.id)
    generate = next(
        (
            dict(item)
            for item in list(manifest.get("workflows") or [])
            if isinstance(item, dict) and item.get("id") == "generate"
        ),
        {},
    )
    # The compatibility endpoint is explicit authorization to run its own
    # generation flow, not blanket consent for every port the release may use
    # in other workflows.
    existing_grants = list(existing.granted_host_ports or []) if existing else []
    compatibility_grants = sorted(
        set(existing_grants) | set(generate.get("host_ports") or [])
    )
    instance, _ = await enable_plugin_instance(
        db,
        current,
        project,
        plugin_id=ROLE_PLUGIN_ID,
        release_id=release.id,
        configuration=dict(existing.configuration or {}) if existing else {},
        granted_host_ports=compatibility_grants,
    )
    return instance


async def _snapshot_for_instance(
    db: AsyncSession,
    instance: PluginInstance,
    snapshot_id: int | None = None,
) -> PluginSnapshot | None:
    selected_id = snapshot_id if snapshot_id is not None else instance.current_snapshot_id
    snapshot = await db.get(PluginSnapshot, selected_id) if selected_id else None
    if snapshot is not None and snapshot.instance_id != instance.id:
        raise HTTPException(404, "指定快照不属于当前岗位插件实例")
    return snapshot


def _legacy_snapshot_payload(snapshot: PluginSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    materialized = snapshot_view(snapshot, include_component_data=True)
    components = dict(materialized.get("components") or {})
    graph = dict(components.get("semantic-graph") or {})
    return {
        "id": snapshot.id,
        "snapshot_key": (
            f"plugin-snapshot:{snapshot.instance_id}:v{snapshot.version}:"
            f"{snapshot.root_hash[:12]}"
        ),
        "version": snapshot.version,
        "root_hash": snapshot.root_hash,
        "status": "ready",
        "graph": graph,
        "source_refs": list(snapshot.source_refs or []),
        "validation": dict(snapshot.validation or {}),
        "provenance": dict(snapshot.provenance or {}),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "components": materialized.get("components"),
    }


async def _legacy_package_view(
    db: AsyncSession,
    instance: PluginInstance | None,
    snapshot: PluginSnapshot | None,
) -> dict[str, Any]:
    if instance is None:
        return {
            "plugin": ROLE_PLUGIN_ID,
            "package": None,
            "snapshot": None,
            "deprecation": _DEPRECATION,
        }
    snapshot_payload = _legacy_snapshot_payload(snapshot)
    graph = dict((snapshot_payload or {}).get("graph") or {})
    role = dict(graph.get("role") or {})
    release = await db.get(PluginRelease, instance.release_id)
    return {
        "plugin": ROLE_PLUGIN_ID,
        "protocol_version": "learnflow.role-capability.v1",
        "package_protocol": release.package_protocol if release else None,
        "package": {
            "id": instance.id,
            "project_id": instance.project_id,
            "role_title": str(role.get("title") or ""),
            "status": instance.status,
            "current_snapshot_id": instance.current_snapshot_id,
            "release_id": instance.release_id,
        },
        "snapshot": snapshot_payload,
        "authority": (
            "role artifacts are domain supply; they never mutate five-kernel learner state"
        ),
        "deprecation": _DEPRECATION,
    }


async def _view_for_run(
    db: AsyncSession,
    instance: PluginInstance,
    run: PluginRun,
) -> dict[str, Any]:
    snapshot = await _snapshot_for_instance(
        db,
        instance,
        run.result_snapshot_id or instance.current_snapshot_id,
    )
    return await _legacy_package_view(db, instance, snapshot)


@router.get("/projects/{project_id}")
async def read_role_capability_package(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    instance = await _role_instance(db, current.learner.id, project_id)
    snapshot = await _snapshot_for_instance(db, instance) if instance else None
    return await _legacy_package_view(db, instance, snapshot)


@router.post("/projects/{project_id}/generate")
async def generate_role_capability_package(
    project_id: int,
    data: GenerateRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await _enable_compatibility_instance(db, current, project)
        expected_snapshot_id = await _idempotent_expected_snapshot(
            db, instance, data.idempotency_key, instance.current_snapshot_id,
        )
        run, replay = await execute_plugin_operation(
            db,
            current,
            project,
            instance,
            operation_id="generate",
            input_data={
                "role_title": data.role_title,
                "role_summary": data.role_summary,
                "source_ids": data.source_ids,
                "task_seeds": data.task_seeds,
            },
            idempotency_key=data.idempotency_key,
            expected_snapshot_id=expected_snapshot_id,
            invocation_kind="workflow",
            require_expected_snapshot=True,
            expected_snapshot_provided=True,
        )
    except PluginHostError as exc:
        _raise_plugin_error(exc)
    response = await _view_for_run(db, instance, run)
    return {
        **response,
        "run_id": run.id,
        "contract": dict(run.contract or {}),
        "idempotent_replay": replay,
        "compatibility_grant": {
            "implicit_from_legacy_mutation_endpoint": True,
            "granted_host_ports": list(instance.granted_host_ports or []),
        },
    }


@router.post("/projects/{project_id}/explain")
async def explain_role_capability_package(
    project_id: int,
    data: ExplainRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    instance = await _role_instance(db, current.learner.id, project_id)
    if instance is None:
        raise HTTPException(404, "当前项目尚未生成岗位能力包")
    snapshot = await _snapshot_for_instance(db, instance, data.snapshot_id)
    if snapshot is None:
        raise HTTPException(409, "岗位能力包没有可解释的固定快照")
    try:
        run, replay = await execute_plugin_operation(
            db,
            current,
            project,
            instance,
            operation_id="explain",
            input_data={"query": data.query, "snapshot_id": snapshot.id},
            idempotency_key=f"legacy-explain-{uuid.uuid4().hex}",
            expected_snapshot_id=snapshot.id,
            invocation_kind="workflow",
            require_expected_snapshot=False,
            expected_snapshot_provided=True,
        )
    except PluginHostError as exc:
        _raise_plugin_error(exc)
    return {
        "snapshot": {
            "id": snapshot.id,
            "snapshot_key": (
                f"plugin-snapshot:{snapshot.instance_id}:v{snapshot.version}:"
                f"{snapshot.root_hash[:12]}"
            ),
            "root_hash": snapshot.root_hash,
        },
        "explanation": dict(run.result or {}),
        "run_id": run.id,
        "idempotent_replay": replay,
        "deprecation": _DEPRECATION,
    }


@router.post("/projects/{project_id}/iterate")
async def iterate_role_capability_package(
    project_id: int,
    data: IterateRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    instance = await _role_instance(db, current.learner.id, project_id)
    if instance is None:
        raise HTTPException(404, "当前项目尚未生成岗位能力包")
    base = await _snapshot_for_instance(db, instance)
    if base is None:
        raise HTTPException(409, "请先生成首个岗位能力快照")
    implicit_expected = "expected_snapshot_id" not in data.model_fields_set
    expected_snapshot_id = base.id if implicit_expected else data.expected_snapshot_id
    expected_snapshot_id = await _idempotent_expected_snapshot(
        db, instance, data.idempotency_key, expected_snapshot_id,
    )
    try:
        run, replay = await execute_plugin_operation(
            db,
            current,
            project,
            instance,
            operation_id="iterate",
            input_data={
                "objective": data.objective,
                "target_ids": data.target_ids,
                "operations": [item.model_dump(exclude_none=True) for item in data.operations],
            },
            idempotency_key=data.idempotency_key,
            expected_snapshot_id=expected_snapshot_id,
            invocation_kind="workflow",
            require_expected_snapshot=True,
            # The alias deterministically pins omission to the current snapshot;
            # the deprecation block below makes this compatibility behavior visible.
            expected_snapshot_provided=True,
        )
    except PluginHostError as exc:
        _raise_plugin_error(exc)
    response = await _view_for_run(db, instance, run)
    return {
        **response,
        "run_id": run.id,
        "status": run.status,
        "contract": dict(run.contract or {}),
        "inspection": dict((response.get("snapshot") or {}).get("validation") or {}),
        "diff": dict((run.result or {}).get("diff") or {}),
        "idempotent_replay": replay,
        "deprecated_implicit_expected_snapshot": implicit_expected,
    }
