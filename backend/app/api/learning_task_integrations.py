"""Authenticated, project-scoped integration API for candidate artifacts."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.auth import CurrentLearner, get_current_learner, require_owned_project
from app.services.xingchen_learning_task_candidates import (
    LearningTaskIntegrationError,
    candidate_audit_view,
    candidate_evidence_view,
    candidate_handoff_view,
    generate_candidate,
    read_candidate_artifact,
)


router = APIRouter(
    prefix="/projects/{project_id}/integrations/xingchen/learning-task-candidates",
    tags=["Learning Task Candidate Integration"],
)


class CandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["role-learning-task-candidate-request.v1"] = Field(
        alias="schemaVersion",
    )
    request_id: str = Field(alias="requestId", min_length=8, max_length=160)
    task_title: str = Field(alias="taskTitle", min_length=2, max_length=300)
    task_description: str = Field(default="", alias="taskDescription", max_length=2000)
    upstream_task: dict[str, Any] | None = Field(default=None, alias="upstreamTask")
    source_version_ids: list[int] = Field(default_factory=list, alias="sourceVersionIds", max_length=20)
    target_step_count: int = Field(default=6, alias="targetStepCount", ge=3, le=12)
    max_source_segments: int = Field(default=16, alias="maxSourceSegments", ge=1, le=20)

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:." for char in normalized):
            raise ValueError("requestId may contain letters, digits, underscore, dash, colon and dot only")
        return normalized

    @field_validator("source_version_ids")
    @classmethod
    def unique_source_versions(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("sourceVersionIds must be positive")
        return list(dict.fromkeys(value))


def _integration_http_error(exc: LearningTaskIntegrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.payload()["error"])


@router.post("")
async def create_learning_task_candidate(
    project_id: int,
    data: CandidateCreateRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        return await generate_candidate(
            db,
            project=project,
            learner_id=current.learner.id,
            request_id=data.request_id,
            task_title=data.task_title,
            task_description=data.task_description,
            upstream_task=data.upstream_task,
            source_version_ids=data.source_version_ids,
            target_step_count=data.target_step_count,
            max_source_segments=data.max_source_segments,
        )
    except LearningTaskIntegrationError as exc:
        raise _integration_http_error(exc) from exc


async def _owned_candidate(
    db: AsyncSession,
    current: CurrentLearner,
    project_id: int,
    candidate_id: str,
) -> dict[str, Any]:
    await require_owned_project(db, current.learner.id, project_id)
    try:
        return await read_candidate_artifact(
            db,
            learner_id=current.learner.id,
            project_id=project_id,
            candidate_id=candidate_id,
        )
    except LearningTaskIntegrationError as exc:
        raise _integration_http_error(exc) from exc


@router.get("/{candidate_id}")
async def read_learning_task_candidate(
    project_id: int,
    candidate_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return await _owned_candidate(db, current, project_id, candidate_id)


@router.get("/{candidate_id}/evidence")
async def inspect_learning_task_candidate_evidence(
    project_id: int,
    candidate_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return candidate_evidence_view(await _owned_candidate(db, current, project_id, candidate_id))


@router.get("/{candidate_id}/audit")
async def audit_learning_task_candidate(
    project_id: int,
    candidate_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    try:
        return candidate_audit_view(await _owned_candidate(db, current, project_id, candidate_id))
    except LearningTaskIntegrationError as exc:
        raise _integration_http_error(exc) from exc


@router.get("/{candidate_id}/handoff")
async def prepare_learning_task_candidate_handoff(
    project_id: int,
    candidate_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    try:
        return candidate_handoff_view(await _owned_candidate(db, current, project_id, candidate_id))
    except LearningTaskIntegrationError as exc:
        raise _integration_http_error(exc) from exc
