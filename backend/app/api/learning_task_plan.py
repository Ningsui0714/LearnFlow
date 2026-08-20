"""Learner-scoped API for the first, auditable Agent Plan stage."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import AgentMessage, AgentSession
from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_runtime import record_event
from app.services.learning_task_plan_gateway import (
    LearningTaskPlanError,
    LearningTaskPlanGateway,
)


router = APIRouter(
    prefix="/learning-task-conversion/plans",
    tags=["学习型工作任务 Plan"],
)


class LearningTaskPlanCreateRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    session_id: int = Field(ge=1)
    client_turn_id: str = Field(min_length=3, max_length=120)


class LearningTaskPlanConfirmRequest(BaseModel):
    expected_plan_version: int = Field(ge=1, le=1000)
    client_event_id: str | None = Field(default=None, min_length=3, max_length=160)


def _gateway() -> LearningTaskPlanGateway:
    return LearningTaskPlanGateway()


def _raise_plan_error(exc: LearningTaskPlanError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def _owned_active_session(
    db: AsyncSession,
    *,
    learner_id: int,
    session_id: int,
) -> AgentSession:
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == learner_id,
        AgentSession.status == "active",
    ))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="当前任务规划会话不存在或已结束")
    return session


async def _owned_plan_message(
    db: AsyncSession,
    *,
    learner_id: int,
    run_id: str,
) -> AgentMessage:
    messages = (await db.execute(
        select(AgentMessage)
        .join(AgentSession, AgentSession.id == AgentMessage.session_id)
        .where(
            AgentSession.learner_id == learner_id,
            AgentMessage.role == "assistant",
        )
        .order_by(AgentMessage.id.desc())
    )).scalars()
    for message in messages:
        metadata = message.meta_data or {}
        if (
            metadata.get("message_kind") == "learning_task_plan"
            and metadata.get("plan_run_id") == run_id
        ):
            return message
    # Ownership failures are deliberately indistinguishable from missing runs.
    raise HTTPException(status_code=404, detail="未找到当前学习者的任务 Plan")


def _response(run: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        **run,
        "message": message,
        "workspace_path": f"/learning-task-plans/{run['run_id']}",
    }


async def _remote_or_snapshot(message: AgentMessage) -> dict[str, Any]:
    run_id = str((message.meta_data or {}).get("plan_run_id") or "")
    try:
        return await _gateway().get(run_id)
    except LearningTaskPlanError:
        snapshot = (message.meta_data or {}).get("plan_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("run_id") == run_id:
            return snapshot
        raise


@router.post("")
async def create_learning_task_plan(
    request: LearningTaskPlanCreateRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    session = await _owned_active_session(
        db,
        learner_id=current.learner.id,
        session_id=request.session_id,
    )
    result_key = (
        f"learning-task-plan-result:{current.learner.id}:{request.client_turn_id}"
    )
    existing = (await db.execute(select(AgentMessage).where(
        AgentMessage.session_id == session.id,
        AgentMessage.idempotency_key == result_key,
    ))).scalar_one_or_none()
    if existing is not None:
        try:
            run = await _remote_or_snapshot(existing)
        except LearningTaskPlanError as exc:
            _raise_plan_error(exc)
        return _response(run, existing.content)

    try:
        run = await _gateway().create(request.query.strip())
    except LearningTaskPlanError as exc:
        _raise_plan_error(exc)

    if run["phase"] == "INTAKE":
        message = (
            "任务 Plan 已创建，但任务契约还需要补充。"
            "请在中央计划页查看阻塞项，再明确一个可执行、可验收的具体任务。"
        )
    else:
        message = (
            "任务 Plan 已创建并在中央工作区打开。"
            "请检查目标、成功条件、不确定项和工作包依赖，确认后再进入后续阶段。"
        )

    request_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="user",
        content=request.query.strip(),
        meta_data={
            "message_kind": "learning_task_plan_request",
            "client_turn_id": request.client_turn_id,
        },
        idempotency_key=(
            f"learning-task-plan-request:{current.learner.id}:{request.client_turn_id}"
        ),
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    await db.execute(request_statement)
    result_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="assistant",
        content=message,
        meta_data={
            "message_kind": "learning_task_plan",
            "client_turn_id": request.client_turn_id,
            "plan_run_id": run["run_id"],
            "plan_snapshot": run,
        },
        idempotency_key=result_key,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    inserted = await db.execute(result_statement)
    if inserted.rowcount:
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="learning_work_task_plan_created",
            source="learning_task_conversion",
            session_id=session.id,
            payload={
                "run_id": run["run_id"],
                "phase": run["phase"],
                "plan_version": run["plan"]["plan_version"],
                "schema_version": run["plan"]["schema_version"],
            },
            artifact_refs=[f"learning-task-plan:{run['run_id']}"],
            client_event_id=f"learning-task-plan:{request.client_turn_id}",
        )
    await db.commit()
    return _response(run, message)


@router.get("/{run_id}")
async def get_learning_task_plan(
    run_id: str = Path(pattern=r"^run_[A-Fa-f0-9]{16,96}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    message = await _owned_plan_message(
        db, learner_id=current.learner.id, run_id=run_id,
    )
    try:
        run = await _remote_or_snapshot(message)
    except LearningTaskPlanError as exc:
        _raise_plan_error(exc)
    return _response(run, message.content)


@router.post("/{run_id}/confirm")
async def confirm_learning_task_plan(
    request: LearningTaskPlanConfirmRequest,
    run_id: str = Path(pattern=r"^run_[A-Fa-f0-9]{16,96}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    message = await _owned_plan_message(
        db, learner_id=current.learner.id, run_id=run_id,
    )
    try:
        run = await _gateway().confirm(
            run_id,
            expected_plan_version=request.expected_plan_version,
        )
    except LearningTaskPlanError as exc:
        _raise_plan_error(exc)

    confirmed_message = (
        f"任务 Plan v{run['plan']['plan_version']} 已通过远端契约、依赖和工具权限校验。"
        "当前停在 PLAN_READY；证据探索和步骤执行将在后续阶段接入。"
    )
    message.content = confirmed_message
    message.meta_data = {
        **(message.meta_data or {}),
        "plan_snapshot": run,
        "confirmed_plan_version": run["plan"]["plan_version"],
    }
    await record_event(
        db,
        learner_id=current.learner.id,
        event_type="learning_work_task_plan_confirmed",
        source="learning_task_conversion",
        session_id=message.session_id,
        payload={
            "run_id": run_id,
            "phase": run["phase"],
            "plan_version": run["plan"]["plan_version"],
            "schema_version": run["plan"]["schema_version"],
        },
        artifact_refs=[f"learning-task-plan:{run_id}"],
        client_event_id=(
            request.client_event_id
            or f"learning-task-plan-confirm:{current.learner.id}:{run_id}:"
            f"{run['plan']['plan_version']}"
        ),
    )
    await db.commit()
    return _response(run, confirmed_message)
