"""Public API for the deterministic LearnFlow plugin host."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginPublisher,
    PluginRelease,
    PluginRun,
    PluginSnapshot,
)
from app.services.auth import (
    CurrentLearner,
    get_current_learner,
    require_admin,
    require_owned_project,
)
from app.services.plugin_host import (
    PLUGIN_SURFACES_PROTOCOL,
    PluginHostError,
    available_plugin_releases,
    discover_plugin_tools,
    enable_plugin_instance,
    execute_plugin_operation,
    import_plugin_release,
    instance_view,
    object_index_view,
    plugin_surfaces,
    publisher_view,
    release_view,
    require_owned_instance,
    resolve_indexed_object,
    run_view,
    snapshot_view,
    update_plugin_instance,
    upgrade_plugin_instance,
)
from app.services.plugin_packages import MAX_ARCHIVE_BYTES


router = APIRouter(tags=["Plugin Host"])


def _raise(exc: PluginHostError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


class PublisherCreateRequest(BaseModel):
    publisher_key: str = Field(min_length=2, max_length=160, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=255)
    key_id: str = Field(min_length=2, max_length=160)
    public_key: str = Field(min_length=32, max_length=8000)
    trust_status: Literal["trusted", "untrusted"] = "trusted"


class PublisherPatchRequest(BaseModel):
    trust_status: Literal["trusted", "untrusted", "revoked"]
    reason: str = Field(default="", max_length=1000)


class ReleasePatchRequest(BaseModel):
    status: Literal["active", "deprecated", "revoked"]
    reason: str = Field(default="", max_length=1000)


class EnablePluginRequest(BaseModel):
    release_id: int = Field(gt=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    granted_host_ports: list[str] = Field(default_factory=list, max_length=32)


class UpdatePluginInstanceRequest(BaseModel):
    status: Literal["enabled", "disabled"] | None = None
    configuration: dict[str, Any] | None = None
    granted_host_ports: list[str] | None = Field(default=None, max_length=32)
    release_id: int | None = Field(default=None, gt=0)
    expected_snapshot_id: int | None = None
    upgrade_idempotency_key: str | None = Field(default=None, min_length=8, max_length=180)


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=180)
    expected_snapshot_id: int | None = None


class PluginToolCallRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: int | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=180)


@router.post("/admin/plugin-publishers")
async def create_plugin_publisher(
    data: PublisherCreateRequest,
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    duplicate = (await db.execute(select(PluginPublisher).where(
        (PluginPublisher.publisher_key == data.publisher_key)
        | (PluginPublisher.key_id == data.key_id)
    ))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(409, {"code": "publisher_conflict", "message": "publisher key or key id already exists"})
    publisher = PluginPublisher(**data.model_dump())
    db.add(publisher)
    await db.commit()
    await db.refresh(publisher)
    return {"publisher": publisher_view(publisher)}


@router.get("/admin/plugin-publishers")
async def list_plugin_publishers(
    trust_status: str | None = None,
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(PluginPublisher)
    if trust_status:
        query = query.where(PluginPublisher.trust_status == trust_status)
    rows = list((await db.execute(query.order_by(
        PluginPublisher.publisher_key,
    ))).scalars().all())
    return {"publishers": [publisher_view(item) for item in rows]}


@router.patch("/admin/plugin-publishers/{publisher_id}")
async def update_plugin_publisher(
    publisher_id: int,
    data: PublisherPatchRequest,
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    publisher = await db.get(PluginPublisher, publisher_id)
    if not publisher:
        raise HTTPException(404, {"code": "plugin_publisher_not_found", "message": "plugin publisher was not found"})
    publisher.trust_status = data.trust_status
    if data.trust_status == "revoked":
        publisher.revoked_at = datetime.utcnow()
        publisher.revoked_reason = data.reason or "revoked by operator"
    else:
        publisher.revoked_at = None
        publisher.revoked_reason = data.reason
    await db.commit()
    return {"publisher": publisher_view(publisher)}


@router.post("/admin/plugin-releases/import")
async def import_plugin_release_bundle(
    file: UploadFile = File(...),
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    raw = await file.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, {"code": "archive_too_large", "message": "plugin package exceeds archive budget"})
    try:
        release, replay = await import_plugin_release(
            db,
            raw,
            filename=(file.filename or "plugin.lfplugin").split("/")[-1].split("\\")[-1],
        )
        await db.commit()
    except PluginHostError as exc:
        await db.rollback()
        _raise(exc)
    return {"release": release_view(release), "idempotent_replay": replay}


@router.get("/admin/plugin-releases")
async def list_plugin_releases(
    plugin_id: str | None = None,
    status: str | None = None,
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(PluginRelease)
    if plugin_id:
        query = query.where(PluginRelease.plugin_id == plugin_id)
    if status:
        query = query.where(PluginRelease.status == status)
    rows = list((await db.execute(query.order_by(PluginRelease.plugin_id, PluginRelease.imported_at.desc()))).scalars().all())
    return {"releases": [release_view(item) for item in rows]}


@router.patch("/admin/plugin-releases/{release_id}")
async def update_plugin_release_status(
    release_id: int,
    data: ReleasePatchRequest,
    _admin: CurrentLearner = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    release = await db.get(PluginRelease, release_id)
    if not release:
        raise HTTPException(404, {"code": "plugin_release_not_found", "message": "plugin release was not found"})
    release.status = data.status
    if data.status == "revoked":
        release.revoked_at = datetime.utcnow()
        release.deprecated_at = release.deprecated_at or release.revoked_at
    elif data.status == "deprecated":
        release.deprecated_at = datetime.utcnow()
        release.revoked_at = None
    else:
        release.revoked_at = None
        release.deprecated_at = None
    signature = dict(release.signature or {})
    if data.reason:
        signature["operator_status_reason"] = data.reason
        release.signature = signature
    await db.commit()
    return {"release": release_view(release)}


@router.get("/projects/{project_id}/plugin-releases")
async def list_project_plugin_release_catalog(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    rows = await available_plugin_releases(db)
    return {
        "protocol": "learnflow.plugin-catalog.v1",
        "releases": [release_view(item) for item in rows],
    }


@router.get("/projects/{project_id}/plugin-instances")
async def list_project_plugin_instances(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    rows = list((await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == current.learner.id,
        PluginInstance.project_id == project_id,
    ).order_by(PluginInstance.plugin_id))).scalars().all())
    output = []
    for row in rows:
        output.append(instance_view(row, await db.get(PluginRelease, row.release_id)))
    return {"instances": output}


@router.put("/projects/{project_id}/plugin-instances/{plugin_id}")
async def put_project_plugin_instance(
    project_id: int,
    plugin_id: str,
    data: EnablePluginRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        instance, replay = await enable_plugin_instance(
            db,
            current,
            project,
            plugin_id=plugin_id,
            release_id=data.release_id,
            configuration=data.configuration,
            granted_host_ports=data.granted_host_ports,
        )
        await db.commit()
    except PluginHostError as exc:
        await db.rollback()
        _raise(exc)
    release = await db.get(PluginRelease, instance.release_id)
    return {"instance": instance_view(instance, release), "existing_instance": replay}


@router.patch("/projects/{project_id}/plugin-instances/{plugin_id}")
async def patch_project_plugin_instance(
    project_id: int,
    plugin_id: str,
    data: UpdatePluginInstanceRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
        if data.release_id is not None and data.release_id != instance.release_id:
            if instance.current_snapshot_id is not None:
                if not data.upgrade_idempotency_key or "expected_snapshot_id" not in data.model_fields_set:
                    raise PluginHostError(
                        "plugin_upgrade_contract_required",
                        "upgrade requires an idempotency key and explicit expected snapshot",
                        status_code=409,
                        details={"current_snapshot_id": instance.current_snapshot_id},
                    )
                run, replay = await upgrade_plugin_instance(
                    db,
                    current,
                    project,
                    instance,
                    target_release_id=data.release_id,
                    expected_snapshot_id=data.expected_snapshot_id,
                    idempotency_key=data.upgrade_idempotency_key,
                    configuration=data.configuration,
                    granted_host_ports=data.granted_host_ports,
                )
                await db.refresh(instance)
                if data.status is not None:
                    instance = await update_plugin_instance(
                        db, instance, current=current, project=project, status=data.status,
                    )
                    await db.commit()
                return {
                    "instance": instance_view(instance, await db.get(PluginRelease, instance.release_id)),
                    "upgrade_run": await run_view(db, run),
                    "idempotent_replay": replay,
                }
            instance, _ = await enable_plugin_instance(
                db,
                current,
                project,
                plugin_id=plugin_id,
                release_id=data.release_id,
                configuration=data.configuration if data.configuration is not None else instance.configuration,
                granted_host_ports=data.granted_host_ports if data.granted_host_ports is not None else instance.granted_host_ports,
            )
        instance = await update_plugin_instance(
            db,
            instance,
            current=current,
            project=project,
            status=data.status,
            configuration=data.configuration,
            granted_host_ports=data.granted_host_ports,
        )
        await db.commit()
    except PluginHostError as exc:
        await db.rollback()
        _raise(exc)
    return {"instance": instance_view(instance, await db.get(PluginRelease, instance.release_id))}


@router.post("/projects/{project_id}/plugin-instances/{plugin_id}/workflows/{workflow_id}/runs")
async def run_project_plugin_workflow(
    project_id: int,
    plugin_id: str,
    workflow_id: str,
    data: WorkflowRunRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
        run, replay = await execute_plugin_operation(
            db,
            current,
            project,
            instance,
            operation_id=workflow_id,
            input_data=data.input,
            idempotency_key=data.idempotency_key,
            expected_snapshot_id=data.expected_snapshot_id,
            invocation_kind="workflow",
            require_expected_snapshot=True,
            expected_snapshot_provided="expected_snapshot_id" in data.model_fields_set,
        )
    except PluginHostError as exc:
        _raise(exc)
    return {"run": await run_view(db, run), "idempotent_replay": replay}


@router.get("/plugin-runs/{run_id}")
async def get_plugin_run(
    run_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    run = (await db.execute(select(PluginRun).where(
        PluginRun.id == run_id,
        PluginRun.learner_id == current.learner.id,
    ))).scalar_one_or_none()
    if not run:
        raise HTTPException(404, {"code": "plugin_run_not_found", "message": "plugin run was not found"})
    await require_owned_project(db, current.learner.id, run.project_id)
    return {"run": await run_view(db, run)}


@router.get("/projects/{project_id}/plugin-instances/{plugin_id}/snapshots")
async def list_plugin_snapshots(
    project_id: int,
    plugin_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
    except PluginHostError as exc:
        _raise(exc)
    rows = list((await db.execute(select(PluginSnapshot).where(
        PluginSnapshot.instance_id == instance.id,
    ).order_by(PluginSnapshot.version.desc()))).scalars().all())
    return {"current_snapshot_id": instance.current_snapshot_id, "snapshots": [snapshot_view(item) for item in rows]}


async def _selected_snapshot(
    db: AsyncSession,
    instance: PluginInstance,
    snapshot_id: int | None,
) -> PluginSnapshot:
    selected_id = snapshot_id or instance.current_snapshot_id
    snapshot = await db.get(PluginSnapshot, selected_id) if selected_id else None
    if not snapshot or snapshot.instance_id != instance.id:
        raise HTTPException(404, {"code": "plugin_snapshot_not_found", "message": "plugin snapshot was not found"})
    return snapshot


@router.get("/projects/{project_id}/plugin-instances/{plugin_id}/objects")
async def list_plugin_objects(
    project_id: int,
    plugin_id: str,
    snapshot_id: int | None = None,
    object_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
    except PluginHostError as exc:
        _raise(exc)
    snapshot = await _selected_snapshot(db, instance, snapshot_id)
    query = select(PluginObjectIndex).where(PluginObjectIndex.snapshot_id == snapshot.id)
    if object_type:
        query = query.where(PluginObjectIndex.object_type == object_type)
    rows = list((await db.execute(query.order_by(PluginObjectIndex.id).offset(offset).limit(limit + 1))).scalars().all())
    return {
        "snapshot": snapshot_view(snapshot),
        "objects": [object_index_view(instance, snapshot, item) for item in rows[:limit]],
        "page": {"offset": offset, "limit": limit, "has_more": len(rows) > limit},
    }


@router.get("/projects/{project_id}/plugin-instances/{plugin_id}/objects/{object_id:path}")
async def get_plugin_object(
    project_id: int,
    plugin_id: str,
    object_id: str,
    snapshot_id: int | None = None,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
    except PluginHostError as exc:
        _raise(exc)
    snapshot = await _selected_snapshot(db, instance, snapshot_id)
    item = (await db.execute(select(PluginObjectIndex).where(
        PluginObjectIndex.snapshot_id == snapshot.id,
        PluginObjectIndex.object_id == object_id,
    ))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, {"code": "plugin_object_not_found", "message": "plugin object was not found"})
    try:
        value = resolve_indexed_object(snapshot, item)
    except PluginHostError as exc:
        _raise(exc)
    return {"snapshot": snapshot_view(snapshot), "index": object_index_view(instance, snapshot, item), "object": value}


@router.get("/projects/{project_id}/plugin-surfaces")
async def list_project_plugin_surfaces(
    project_id: int,
    slot: str | None = None,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    return {
        "schema_version": PLUGIN_SURFACES_PROTOCOL,
        "surfaces": await plugin_surfaces(db, learner_id=current.learner.id, project_id=project_id, slot=slot),
    }


@router.get("/projects/{project_id}/plugin-tools")
async def discover_project_plugin_tools(
    project_id: int,
    query: str = Query(default="", max_length=500),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    return {
        "protocol": "learnflow.plugin-tool-discovery.v1",
        "tools": await discover_plugin_tools(
            db,
            learner_id=current.learner.id,
            project_id=project_id,
            query=query,
        ),
    }


@router.post("/projects/{project_id}/plugin-tools/{qualified_tool_id}/calls")
async def call_project_plugin_tool(
    project_id: int,
    qualified_tool_id: str,
    data: PluginToolCallRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    if ":" not in qualified_tool_id:
        raise HTTPException(400, {"code": "invalid_qualified_tool_id", "message": "qualified tool id must be plugin_id:tool_id"})
    plugin_id, tool_id = qualified_tool_id.split(":", 1)
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        instance = await require_owned_instance(db, current.learner.id, project_id, plugin_id)
        pinned_snapshot = data.snapshot_id if data.snapshot_id is not None else instance.current_snapshot_id
        tool_input = {**data.input, "snapshot_id": pinned_snapshot}
        run, replay = await execute_plugin_operation(
            db,
            current,
            project,
            instance,
            operation_id=tool_id,
            input_data=tool_input,
            idempotency_key=data.idempotency_key or f"tool-call-{uuid.uuid4().hex}",
            expected_snapshot_id=pinned_snapshot,
            invocation_kind="tool",
            require_expected_snapshot=False,
            expected_snapshot_provided=True,
        )
    except PluginHostError as exc:
        _raise(exc)
    return {
        "protocol": "learnflow.plugin-tool-result.v1",
        "qualified_tool_id": qualified_tool_id,
        "snapshot_id": pinned_snapshot,
        "run": await run_view(db, run),
        "result": dict(run.result or {}),
        "idempotent_replay": replay,
    }
