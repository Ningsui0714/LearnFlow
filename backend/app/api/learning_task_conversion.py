"""LearnFlow-facing API for the岗位典型工作任务转化 adapter."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_task_conversion_gateway import (
    LearningTaskConversionError,
    LearningTaskConversionGateway,
)


router = APIRouter(
    prefix="/learning-task-conversion",
    tags=["岗位典型工作任务转化集成"],
)


class WF03ConversationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


def _gateway() -> LearningTaskConversionGateway:
    return LearningTaskConversionGateway()


def _raise_gateway_error(exc: LearningTaskConversionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/capabilities")
async def get_learning_task_conversion_capabilities(
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().capabilities()
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/generate")
async def generate_learning_task_from_conversation(
    request: WF03ConversationRequest,
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().generate_from_conversation(request.query.strip())
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/upstream-handoffs")
async def submit_competency_graph_handoff(
    payload: dict[str, Any] = Body(...),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().submit_upstream_handoff(payload)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/bundle")
async def get_learning_task_conversion_bundle(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().task_bundle(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/personalized-learning")
async def get_personalized_learning_handoff(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().personalized_learning_handoff(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/downstream-feedback")
async def submit_personalized_learning_feedback(
    payload: dict[str, Any] = Body(...),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().submit_downstream_feedback(payload)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
