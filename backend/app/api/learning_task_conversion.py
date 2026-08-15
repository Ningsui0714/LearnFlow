"""LearnFlow-facing API for the岗位典型工作任务转化 adapter."""
from __future__ import annotations

from typing import Any, Literal

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


class CompetencyKnowledgePoint(BaseModel):
    knowledge_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)


class CompetencySkillPoint(BaseModel):
    skill_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    observable_action: str = Field(min_length=1, max_length=1000)


class CompetencyRelation(BaseModel):
    relation_id: str = Field(min_length=1, max_length=100)
    knowledge_id: str = Field(min_length=1, max_length=100)
    skill_id: str = Field(min_length=1, max_length=100)
    relation_type: Literal[
        "prerequisite",
        "required_for_step",
        "enables",
        "verifies",
        "safety_constraint",
    ]
    strength: Literal["critical", "high", "medium", "low"]
    reason: str = Field(min_length=4, max_length=1000)
    applies_to_steps: list[str] = Field(default_factory=list)


class CompetencyGraphHandoffRequest(BaseModel):
    schema_version: Literal["competency-graph-learning-task-handoff-v1"]
    upstream_task_id: str = Field(min_length=1, max_length=100)
    correlation_id: str = Field(min_length=1, max_length=100)
    task_name: str = Field(min_length=2, max_length=300)
    task_brief: str = Field(min_length=10, max_length=3000)
    source_context: dict[str, Any] = Field(default_factory=dict)
    knowledge_points: list[CompetencyKnowledgePoint] = Field(min_length=1, max_length=30)
    skill_points: list[CompetencySkillPoint] = Field(min_length=1, max_length=30)
    relations: list[CompetencyRelation] = Field(min_length=1, max_length=100)


class PersonalizedLearningLaunchRequest(BaseModel):
    schema_version: Literal["personalized-learning-launch-request-v1"] = (
        "personalized-learning-launch-request-v1"
    )
    entry_mode: Literal["whole_task", "knowledge_point"] = "whole_task"
    selected_knowledge_id: str | None = Field(default=None, min_length=1, max_length=100)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=100)


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
    payload: CompetencyGraphHandoffRequest,
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        accepted = await _gateway().submit_upstream_handoff(payload.model_dump())
        handoff_id = str(accepted.get("handoff_id") or "")
        return {
            **accepted,
            "learnflow_integration": {
                "schema_version": "learnflow-upstream-handoff-acceptance-v1",
                "handoff_status_path": (
                    f"/api/learning-task-conversion/upstream-handoffs/{handoff_id}"
                    if handoff_id
                    else None
                ),
                "generation_binding_status": "pending_xingchen_handoff_parameter",
            },
        }
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/upstream-handoffs/{handoff_id}")
async def get_competency_graph_handoff(
    handoff_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().upstream_handoff(handoff_id)
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


@router.post("/tasks/{task_card_id}/downstream-launch")
async def prepare_personalized_learning_launch(
    request: PersonalizedLearningLaunchRequest,
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().prepare_personalized_learning_launch(
            task_card_id,
            entry_mode=request.entry_mode,
            selected_knowledge_id=request.selected_knowledge_id,
            correlation_id=request.correlation_id,
        )
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
