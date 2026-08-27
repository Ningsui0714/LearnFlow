"""Rebuild checkpoint delivery readiness from existing authoritative objects."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import AssessmentBlueprint, AssessmentRubric, LearningTask
from app.models.project import Checkpoint, CheckpointChunk, Chunk, ConceptQuestion, Exercise, Lecture, Source


DELIVERY_READINESS_POLICY = "checkpoint-delivery-readiness.v1"
LEVELS = (
    "outline_only",
    "content_ready",
    "guided_learning_ready",
    "practice_ready",
    "verification_ready",
)


def project_delivery_readiness(snapshot: dict[str, Any]) -> dict[str, Any]:
    source_ready = bool(snapshot.get("processed_source_chunks"))
    content_ready = bool(snapshot.get("published_lecture_sections"))
    task_ready = bool(snapshot.get("learning_task_count"))
    question_count = int(snapshot.get("concept_question_count") or 0)
    exercise_count = int(snapshot.get("exercise_count") or 0)
    practice_ready = question_count + exercise_count > 0
    blueprint_ready = bool(snapshot.get("active_blueprint_count"))
    rubric_ready = bool(snapshot.get("active_rubric_count"))
    deterministic_answer = bool(snapshot.get("deterministic_answer_count"))
    guided_ready = content_ready and task_ready
    practice_stage_ready = guided_ready and practice_ready
    verification_ready = practice_stage_ready and deterministic_answer and blueprint_ready and rubric_ready

    if verification_ready:
        overall = "verification_ready"
    elif practice_stage_ready:
        overall = "practice_ready"
    elif guided_ready:
        overall = "guided_learning_ready"
    elif content_ready:
        overall = "content_ready"
    else:
        overall = "outline_only"

    gaps: list[str] = []
    if not source_ready:
        gaps.append("缺少当前关卡可定位的已处理来源")
    if not content_ready:
        gaps.append("缺少已发布且非空的讲义")
    if not task_ready:
        gaps.append("缺少绑定当前关卡的 LearningTask")
    if not practice_ready:
        gaps.append("缺少正式概念题或实践任务")
    if practice_ready and not deterministic_answer:
        gaps.append("练习缺少可确定性判定的答案或测试契约")
    if not blueprint_ready:
        gaps.append("缺少有效 AssessmentBlueprint")
    if not rubric_ready:
        gaps.append("缺少有效 AssessmentRubric")

    return {
        "policy_version": DELIVERY_READINESS_POLICY,
        "overall": overall,
        "sources": "ready" if source_ready else "gap",
        "content": "ready" if content_ready else "gap",
        "guided_learning": "ready" if guided_ready else "gap",
        "practice": "ready" if practice_ready else "gap",
        "verification": "ready" if verification_ready else "gap",
        "gaps": gaps,
        "mastery_inference": False,
    }


async def checkpoint_delivery_readiness(
    db: AsyncSession,
    checkpoint: Checkpoint,
    *,
    learner_id: int,
) -> dict[str, Any]:
    processed_source_chunks = int((await db.scalar(
        select(func.count(CheckpointChunk.id))
        .join(Chunk, Chunk.id == CheckpointChunk.chunk_id)
        .join(Source, Source.id == Chunk.source_id)
        .where(CheckpointChunk.checkpoint_id == checkpoint.id, Source.status == "processed")
    )) or 0)
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint.id,
    ))).scalar_one_or_none()
    questions = list((await db.execute(select(ConceptQuestion).where(
        ConceptQuestion.checkpoint_id == checkpoint.id,
    ))).scalars().all())
    exercises = list((await db.execute(select(Exercise).where(
        Exercise.checkpoint_id == checkpoint.id,
    ))).scalars().all())
    blueprint_ids = list((await db.execute(select(AssessmentBlueprint.id).where(
        AssessmentBlueprint.learner_id == learner_id,
        AssessmentBlueprint.checkpoint_id == checkpoint.id,
        AssessmentBlueprint.status.in_(["draft", "active", "published"]),
    ))).scalars().all())
    rubric_count = 0
    if blueprint_ids:
        rubric_count = int((await db.scalar(select(func.count(AssessmentRubric.id)).where(
            AssessmentRubric.blueprint_id.in_(blueprint_ids),
            AssessmentRubric.status.in_(["draft", "active", "published"]),
        ))) or 0)
    task_count = int((await db.scalar(select(func.count(LearningTask.id)).where(
        LearningTask.learner_id == learner_id,
        LearningTask.checkpoint_id == checkpoint.id,
        LearningTask.status.notin_(["canceled"]),
    ))) or 0)
    deterministic_answers = sum(
        1 for item in questions
        if list(item.answer_indexes or []) or bool(str(item.expected_output or "").strip())
    ) + sum(
        1 for item in exercises
        if list(item.test_cases or []) or bool(dict(item.judge_config or {}))
    )
    return project_delivery_readiness({
        "processed_source_chunks": processed_source_chunks,
        "published_lecture_sections": len(lecture.sections or []) if lecture and lecture.status == "published" else 0,
        "learning_task_count": task_count,
        "concept_question_count": len(questions),
        "exercise_count": len(exercises),
        "deterministic_answer_count": deterministic_answers,
        "active_blueprint_count": len(blueprint_ids),
        "active_rubric_count": rubric_count,
    })
