from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.project import Chunk, Source, SourceVersion
from app.models.role_capability import RoleCapabilityPackage, RoleCapabilityRun, RoleCapabilitySnapshot
from app.services.auth import CurrentLearner, get_current_learner, require_owned_project
from app.services.learning_runtime import record_event
from app.services.role_capability_plugin import (
    apply_iteration, build_generation_contract, build_iteration_contract,
    compile_role_graph, create_snapshot, current_package, current_snapshot,
    explain_role_graph, inspect_role_graph, package_view,
)


router = APIRouter(prefix="/role-capability", tags=["Role Capability Plugin"])


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


async def _owned_package(db: AsyncSession, learner_id: int, project_id: int) -> RoleCapabilityPackage:
    package = await current_package(db, learner_id, project_id)
    if not package:
        raise HTTPException(404, "当前项目尚未生成岗位能力包")
    return package


async def _existing_run(db: AsyncSession, learner_id: int, key: str) -> RoleCapabilityRun | None:
    return (await db.execute(select(RoleCapabilityRun).where(
        RoleCapabilityRun.learner_id == learner_id,
        RoleCapabilityRun.idempotency_key == key,
    ))).scalar_one_or_none()


async def _source_inputs(
    db: AsyncSession, project_id: int, requested_ids: list[int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    query = select(Source).where(Source.project_id == project_id, Source.status == "processed")
    if requested_ids:
        query = query.where(Source.id.in_(requested_ids))
    sources = list((await db.execute(query.order_by(Source.id))).scalars().all())
    if requested_ids and {item.id for item in sources} != set(requested_ids):
        raise HTTPException(400, "岗位包只能引用当前项目中已处理且归属正确的来源")
    refs: list[dict[str, Any]] = []
    texts: list[dict[str, str]] = []
    for source in sources[:20]:
        active_id = int(dict(source.meta_data or {}).get("active_source_version_id") or 0)
        version = await db.get(SourceVersion, active_id) if active_id else None
        if not version:
            version = (await db.execute(select(SourceVersion).where(
                SourceVersion.source_id == source.id,
            ).order_by(SourceVersion.version.desc()).limit(1))).scalar_one_or_none()
        ref = f"source:{source.id}@v{version.version if version else 0}"
        refs.append({
            "ref": ref, "source_id": source.id,
            "source_version_id": version.id if version else None,
            "content_hash": version.content_hash if version else "",
            "authority_tier": version.authority_tier if version else "learner_owned",
            "status": version.status if version else source.status,
        })
        chunks = list((await db.execute(select(Chunk).where(
            Chunk.source_id == source.id,
            *([Chunk.source_version_id == version.id] if version else []),
        ).order_by(Chunk.index).limit(24))).scalars().all())
        texts.extend({"ref": ref, "text": item.content[:2000]} for item in chunks)
    return refs, texts


@router.get("/projects/{project_id}")
async def read_role_capability_package(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    package = await current_package(db, current.learner.id, project_id)
    if not package:
        return {"plugin": "role_capability_graph", "package": None, "snapshot": None}
    return package_view(package, await current_snapshot(db, package))


@router.post("/projects/{project_id}/generate")
async def generate_role_capability_package(
    project_id: int,
    data: GenerateRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    existing_run = await _existing_run(db, current.learner.id, data.idempotency_key)
    if existing_run:
        if existing_run.project_id != project_id:
            raise HTTPException(409, "幂等键已绑定到其他项目，不能跨 scope 重放")
        package = await db.get(RoleCapabilityPackage, existing_run.package_id)
        return {**package_view(package, await current_snapshot(db, package)), "run_id": existing_run.id, "idempotent_replay": True}
    source_refs, source_texts = await _source_inputs(db, project_id, data.source_ids)
    package = await current_package(db, current.learner.id, project_id)
    if not package:
        package = RoleCapabilityPackage(
            learner_id=current.learner.id, project_id=project_id,
            role_title=data.role_title.strip(),
        )
        db.add(package)
        await db.flush()
    else:
        package.role_title = data.role_title.strip()
    contract = build_generation_contract(package.role_title, source_refs)
    run = RoleCapabilityRun(
        learner_id=current.learner.id, project_id=project_id, package_id=package.id,
        kind="generate", idempotency_key=data.idempotency_key,
        request=data.model_dump(), contract=contract,
    )
    db.add(run)
    await db.flush()
    try:
        graph = compile_role_graph(
            role_title=package.role_title,
            role_summary=data.role_summary or project.description,
            task_seeds=data.task_seeds, source_refs=source_refs, source_texts=source_texts,
        )
        previous = await current_snapshot(db, package)
        snapshot = await create_snapshot(
            db, package, graph, source_refs,
            {"run_id": run.id, "kind": "generate", "contract": contract, "mastery_unchanged": True},
            previous.id if previous else None,
        )
        run.status = "completed"
        run.result_snapshot_id = snapshot.id
        run.inspection = snapshot.validation
        run.summary = f"生成 {snapshot.validation['stats']['nodes']} 个岗位对象与 {snapshot.validation['stats']['edges']} 条关系"
        run.finished_at = datetime.utcnow()
        await record_event(
            db, learner_id=current.learner.id, project_id=project_id,
            event_type="role_capability_package_generated", source="role_capability_plugin",
            payload={"package_id": package.id, "snapshot_id": snapshot.id, "root_hash": snapshot.root_hash, "mastery_unchanged": True},
            provenance={"run_id": run.id, "protocol_version": package.policy_version},
            client_event_id=f"role-capability:{data.idempotency_key}:generated",
        )
        await db.commit()
        return {**package_view(package, snapshot), "run_id": run.id, "contract": contract}
    except ValueError as exc:
        run.status = "failed"
        run.error = {"message": str(exc)}
        run.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/explain")
async def explain_role_capability_package(
    project_id: int,
    data: ExplainRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    package = await _owned_package(db, current.learner.id, project_id)
    snapshot = await current_snapshot(db, package)
    if not snapshot:
        raise HTTPException(409, "岗位能力包没有可解释的固定快照")
    if data.snapshot_id and data.snapshot_id != snapshot.id:
        candidate = (await db.execute(select(RoleCapabilitySnapshot).where(
            RoleCapabilitySnapshot.id == data.snapshot_id,
            RoleCapabilitySnapshot.package_id == package.id,
        ))).scalar_one_or_none()
        if not candidate:
            raise HTTPException(404, "指定快照不属于当前岗位包")
        snapshot = candidate
    return {
        "snapshot": {"id": snapshot.id, "snapshot_key": snapshot.snapshot_key, "root_hash": snapshot.root_hash},
        "explanation": explain_role_graph(snapshot.graph, data.query),
    }


@router.post("/projects/{project_id}/iterate")
async def iterate_role_capability_package(
    project_id: int,
    data: IterateRolePackageRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    existing_run = await _existing_run(db, current.learner.id, data.idempotency_key)
    if existing_run:
        if existing_run.project_id != project_id:
            raise HTTPException(409, "幂等键已绑定到其他项目，不能跨 scope 重放")
        package = await db.get(RoleCapabilityPackage, existing_run.package_id)
        return {**package_view(package, await current_snapshot(db, package)), "run_id": existing_run.id, "idempotent_replay": True}
    package = await _owned_package(db, current.learner.id, project_id)
    base = await current_snapshot(db, package)
    if not base:
        raise HTTPException(409, "请先生成首个岗位能力快照")
    contract = build_iteration_contract(data.objective, data.target_ids, base.id)
    run = RoleCapabilityRun(
        learner_id=current.learner.id, project_id=project_id, package_id=package.id,
        kind="iterate", idempotency_key=data.idempotency_key,
        request=data.model_dump(), contract=contract,
    )
    db.add(run)
    await db.flush()
    before = inspect_role_graph(base.graph)
    candidate, diff = apply_iteration(base.graph, [item.model_dump(exclude_none=True) for item in data.operations])
    after = inspect_role_graph(candidate)
    run.inspection = {"before": before, "after": after}
    run.diff = diff
    if not diff["meaningful"]:
        run.status = "no_change"
        run.summary = "没有满足合同的有效图谱变更；保留当前快照"
        run.finished_at = datetime.utcnow()
        await db.commit()
        return {**package_view(package, base), "run_id": run.id, "status": "no_change", "contract": contract, "inspection": run.inspection, "diff": diff}
    if not after["valid"]:
        run.status = "failed"
        run.error = {"message": "candidate_protocol_invalid", "errors": after["errors"]}
        run.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(409, {"message": "候选图谱未通过协议校验", "errors": after["errors"]})
    snapshot = await create_snapshot(
        db, package, candidate, list(base.source_refs or []),
        {"run_id": run.id, "kind": "iterate", "contract": contract, "diff": diff, "mastery_unchanged": True},
        base.id,
    )
    run.status = "completed"
    run.result_snapshot_id = snapshot.id
    run.summary = f"形成 v{snapshot.version}：{diff['change_count']} 项有意义变化"
    run.finished_at = datetime.utcnow()
    await record_event(
        db, learner_id=current.learner.id, project_id=project_id,
        event_type="role_capability_snapshot_iterated", source="role_capability_plugin",
        payload={"package_id": package.id, "base_snapshot_id": base.id, "snapshot_id": snapshot.id, "diff": diff, "mastery_unchanged": True},
        provenance={"run_id": run.id, "protocol_version": package.policy_version},
        client_event_id=f"role-capability:{data.idempotency_key}:iterated",
    )
    await db.commit()
    return {**package_view(package, snapshot), "run_id": run.id, "status": "completed", "contract": contract, "inspection": run.inspection, "diff": diff}
