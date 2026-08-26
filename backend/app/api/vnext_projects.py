"""vNext project workspace views and explicit project-plan application.

This module is a product runtime over the existing Project/Roadmap/Checkpoint
authority.  It deliberately does not introduce a second project model and it
never lets model output mutate learner state without an explicit user action.
"""

from __future__ import annotations

from typing import Any, Literal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import AgentSession, LearningTask
from app.models.project import Checkpoint, Chunk, ConceptQuestion, Exercise, Lecture, Project, Roadmap, Source
from app.services.auth import CurrentLearner, get_current_learner, require_owned_project
from app.services.five_kernel_context import build_five_kernel_context
from app.services.learning_runtime import record_event
from app.services.learning_tasks import ensure_all_checkpoint_learning_tasks, learning_task_view
from app.services.tutor_service import get_or_create_session


router = APIRouter(prefix="/vnext-projects", tags=["vNext Projects"])
SCHEMA_VERSION = "vnext.project.v1"


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    objective: str = Field(min_length=2, max_length=2000)
    expected_outcome: str = Field(default="", max_length=1200)
    user_level: str = Field(default="beginner", max_length=50)


class CheckpointProposal(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=255)
    objective: str = Field(min_length=2, max_length=1200)
    prerequisites: list[str] = Field(default_factory=list, max_length=8)
    success_criteria: list[str] = Field(default_factory=list, min_length=1, max_length=8)
    estimated_minutes: int = Field(default=45, ge=10, le=600)

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip()[:80] for item in value if str(item).strip()))


class RoadmapApplyRequest(BaseModel):
    project_theme: str = Field(min_length=2, max_length=255)
    rationale: str = Field(default="", max_length=1600)
    checkpoints: list[CheckpointProposal] = Field(min_length=1, max_length=16)
    client_action_id: str = Field(min_length=4, max_length=160)


class ProjectSessionCreateRequest(BaseModel):
    kind: Literal["free"] = "free"
    title: str = Field(default="项目自由对话", max_length=255)
    client_action_id: str = Field(min_length=4, max_length=160)


def _project_spec(project: Project) -> dict[str, Any]:
    raw = str(project.description or "")
    objective, _, expected = raw.partition("\n\n预期产物：")
    return {
        "id": project.id,
        "name": project.name,
        "objective": objective,
        "expected_outcome": expected,
        "user_level": project.user_level,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


async def _source_views(db: AsyncSession, project_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(Source, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.source_id == Source.id)
        .where(Source.project_id == project_id)
        .group_by(Source.id)
        .order_by(Source.created_at.desc())
    )).all()
    return [{
        "id": source.id,
        "type": source.type,
        "name": source.url,
        "url": source.url,
        "role": source.role or "main",
        "status": source.status,
        "error": source.error or "",
        "chunk_count": int(count or 0),
        "mastery_inference": False,
    } for source, count in rows]


async def _file_views(db: AsyncSession, project_id: int) -> dict[str, list[dict[str, Any]]]:
    checkpoint_rows = (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .where(Roadmap.project_id == project_id, Checkpoint.archived.is_(False))
    )).scalars().all()
    checkpoint_map = {item.id: item for item in checkpoint_rows}
    ids = list(checkpoint_map)
    if not ids:
        return {"lectures": [], "practices": []}
    lectures = (await db.execute(select(Lecture).where(Lecture.checkpoint_id.in_(ids)))).scalars().all()
    exercises = (await db.execute(select(Exercise).where(Exercise.checkpoint_id.in_(ids)))).scalars().all()
    questions = (await db.execute(select(ConceptQuestion).where(ConceptQuestion.checkpoint_id.in_(ids)))).scalars().all()
    grouped_questions: dict[int, list[ConceptQuestion]] = {}
    for item in questions:
        grouped_questions.setdefault(item.checkpoint_id, []).append(item)
    lecture_refs = [{
        "kind": "lecture", "ref": str(item.id), "id": item.id,
        "title": checkpoint_map[item.checkpoint_id].title,
        "logical_filename": f"{checkpoint_map[item.checkpoint_id].order:02d}-{checkpoint_map[item.checkpoint_id].title}.lflecture",
        "project_id": project_id, "checkpoint_id": item.checkpoint_id,
        "version": int(item.version or 1), "status": item.status,
        "path": f"/files/lecture/{item.id}",
    } for item in lectures]
    practice_refs = [{
        "kind": "practice", "practice_kind": "exercise", "ref": f"exercise-{item.id}",
        "id": item.id, "title": item.title, "project_id": project_id,
        "checkpoint_id": item.checkpoint_id,
        "logical_filename": f"{checkpoint_map[item.checkpoint_id].order:02d}-{checkpoint_map[item.checkpoint_id].title}-{item.order:02d}.lfexercise",
        "path": f"/files/practice/exercise-{item.id}",
    } for item in exercises]
    practice_refs.extend({
        "kind": "practice", "practice_kind": "concept_question_set",
        "ref": f"questions-{checkpoint_id}", "title": f"{checkpoint_map[checkpoint_id].title} · 概念验证",
        "project_id": project_id, "checkpoint_id": checkpoint_id,
        "logical_filename": f"{checkpoint_map[checkpoint_id].order:02d}-{checkpoint_map[checkpoint_id].title}-概念验证.lfexercise",
        "path": f"/files/practice/questions-{checkpoint_id}", "question_count": len(items),
    } for checkpoint_id, items in grouped_questions.items())
    return {"lectures": lecture_refs, "practices": practice_refs}


def _query_terms(value: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() or '\u4e00' <= char <= '\u9fff' else " " for char in value)
    words = [item for item in cleaned.split() if len(item) > 1]
    cjk = [cleaned[index:index + 2] for index in range(max(0, len(cleaned) - 1))
           if all('\u4e00' <= char <= '\u9fff' for char in cleaned[index:index + 2])]
    return list(dict.fromkeys(words + cjk))[:24]


async def _project_source_excerpts(db: AsyncSession, project_id: int, query: str) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(Chunk, Source).join(Source, Source.id == Chunk.source_id).where(
            Source.project_id == project_id, Source.status == "processed",
        ).order_by(Chunk.source_id, Chunk.index).limit(240)
    )).all()
    terms = _query_terms(query)
    ranked: list[tuple[int, Chunk, Source]] = []
    for chunk, source in rows:
        lowered = (chunk.content or "").lower()
        score = sum(1 for term in terms if term in lowered)
        if score or not terms:
            ranked.append((score, chunk, source))
    ranked.sort(key=lambda item: (-item[0], item[2].id, item[1].index))
    return [{
        "source_id": source.id, "source_name": source.url, "chunk_id": chunk.id,
        "excerpt": (chunk.content or "")[:1800], "relevance_score": score,
        "provenance": {"source_type": source.type, "chunk_index": chunk.index},
        "untrusted": True, "mastery_inference": False,
    } for score, chunk, source in ranked[:8]]


async def _learning_file_previews(db: AsyncSession, project_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(Checkpoint).join(Roadmap).where(Roadmap.project_id == project_id)
    )).scalars().all()
    checkpoint_map = {item.id: item for item in rows}
    ids = list(checkpoint_map)
    if not ids:
        return []
    lectures = (await db.execute(select(Lecture).where(Lecture.checkpoint_id.in_(ids)))).scalars().all()
    exercises = (await db.execute(select(Exercise).where(Exercise.checkpoint_id.in_(ids)))).scalars().all()
    previews = [{
        "kind": "lecture", "ref": str(item.id), "checkpoint_id": item.checkpoint_id,
        "title": checkpoint_map[item.checkpoint_id].title,
        "content": [{"title": str(section.get("title") or "")[:160],
                     "content": str(section.get("content") or "")[:2400]}
                    for section in list(item.sections or [])[:4] if isinstance(section, dict)],
        "answers_hidden": True, "mastery_inference": False,
    } for item in lectures]
    previews.extend({
        "kind": "practice", "ref": f"exercise-{item.id}", "checkpoint_id": item.checkpoint_id,
        "title": item.title, "description": (item.description or "")[:1800],
        "starter_code": (item.starter_code or "")[:2400], "hints": list(item.hints or [])[:4],
        "answers_hidden": True, "mastery_inference": False,
    } for item in exercises)
    return previews[:16]


async def _workspace_view(db: AsyncSession, learner_id: int, project: Project) -> dict[str, Any]:
    await ensure_all_checkpoint_learning_tasks(db, learner_id=learner_id, project_id=project.id)
    project_sessions = list((await db.execute(select(AgentSession).where(
        AgentSession.learner_id == learner_id,
        AgentSession.project_id == project.id,
        AgentSession.session_type == "project",
        AgentSession.status == "active",
    ).order_by(AgentSession.created_at))).scalars().all())
    tutor = next((item for item in project_sessions if
                  (item.context_summary or {}).get("role") == "project_tutor"), None)
    if tutor is None:
        tutor = AgentSession(
            learner_id=learner_id, session_type="project", project_id=project.id,
            title=f"{project.name} · 项目 Tutor", status="active",
            context_summary={"role": "project_tutor", "project_theme": project.name},
        )
        db.add(tutor)
        await db.flush()
    roadmap = (await db.execute(select(Roadmap).where(Roadmap.project_id == project.id))).scalar_one_or_none()
    checkpoints = []
    if roadmap:
        rows = (await db.execute(select(Checkpoint).where(
            Checkpoint.roadmap_id == roadmap.id, Checkpoint.archived.is_(False),
        ).order_by(Checkpoint.order))).scalars().all()
        for checkpoint in rows:
            session = await get_or_create_session(
                db, learner_id=learner_id, session_type="checkpoint",
                project_id=project.id, checkpoint_id=checkpoint.id,
            )
            task = (await db.execute(select(LearningTask).where(
                LearningTask.learner_id == learner_id,
                LearningTask.checkpoint_id == checkpoint.id,
            ))).scalar_one_or_none()
            checkpoints.append({
                "id": checkpoint.id, "key": f"checkpoint-{checkpoint.order}",
                "title": checkpoint.title, "objective": checkpoint.description or "",
                "order": checkpoint.order, "prerequisites": list(checkpoint.prerequisites or []),
                "learning_status": checkpoint.learning_status or "not_started",
                "learning_contract": dict(checkpoint.learning_contract or {}),
                "session_id": session.id,
                "learning_task": await learning_task_view(db, task) if task else None,
            })
    free_sessions = [item for item in project_sessions if
                     (item.context_summary or {}).get("role") == "project_free"]
    return {
        "schema_version": SCHEMA_VERSION,
        "project": _project_spec(project),
        "project_tutor": {"session_id": tutor.id, "title": tutor.title, "mode": "learning_plan"},
        "roadmap": {"id": roadmap.id if roadmap else None, "checkpoints": checkpoints},
        "sources": await _source_views(db, project.id),
        "files": await _file_views(db, project.id),
        "free_sessions": [{"session_id": item.id, "title": item.title} for item in free_sessions],
        "boundaries": {
            "planning_requires_confirmation": True,
            "source_content_is_untrusted": True,
            "file_generation_is_not_mastery": True,
            "checkpoint_completion_is_not_mastery": True,
        },
    }


@router.get("")
async def list_vnext_projects(
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    projects = (await db.execute(select(Project).where(
        Project.learner_id == current.learner.id,
        Project.visibility == "visible",
        Project.project_kind == "apprenticeship",
    ).order_by(Project.updated_at.desc()))).scalars().all()
    return {"schema_version": SCHEMA_VERSION, "projects": [_project_spec(item) for item in projects]}


@router.post("")
async def create_vnext_project(
    data: ProjectCreateRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    description = data.objective.strip()
    if data.expected_outcome.strip():
        description += f"\n\n预期产物：{data.expected_outcome.strip()}"
    project = Project(
        learner_id=current.learner.id, name=data.name.strip(), description=description,
        user_level=data.user_level, project_kind="apprenticeship", visibility="visible",
    )
    db.add(project)
    await db.flush()
    await record_event(
        db, learner_id=current.learner.id, project_id=project.id,
        event_type="project_created", source="ui",
        payload={"project_id": project.id, "name": project.name,
                 "description": data.objective.strip(),
                 "learning_goal": data.objective.strip(), "expected_outcome": data.expected_outcome.strip()},
        provenance={"endpoint": "POST /api/vnext-projects", "explicit_click": True},
        client_event_id=f"vnext-project:{project.id}:created",
    )
    view = await _workspace_view(db, current.learner.id, project)
    await db.commit()
    return view


@router.get("/{project_id}")
async def get_vnext_project(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    view = await _workspace_view(db, current.learner.id, project)
    await db.commit()
    return view


@router.post("/{project_id}/roadmap/apply")
async def apply_vnext_roadmap(
    project_id: int,
    data: RoadmapApplyRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    if data.project_theme.strip().casefold() != project.name.strip().casefold():
        raise HTTPException(422, "规划主题必须与当前项目完全一致")
    existing = (await db.execute(select(Roadmap).where(Roadmap.project_id == project.id))).scalar_one_or_none()
    if existing and (await db.scalar(select(func.count(Checkpoint.id)).where(Checkpoint.roadmap_id == existing.id))):
        raise HTTPException(409, "项目已有正式关卡；路线修订必须通过后续的版本化修订流程")
    keys = [item.key for item in data.checkpoints]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, "关卡 key 不能重复")
    seen_keys: set[str] = set()
    for item in data.checkpoints:
        if any(key not in keys for key in item.prerequisites):
            raise HTTPException(422, f"关卡 {item.title} 引用了不存在的前置关卡")
        if any(key not in seen_keys for key in item.prerequisites):
            raise HTTPException(422, f"关卡 {item.title} 的前置必须出现在它之前，确保路线为 DAG")
        seen_keys.add(item.key)
    roadmap = existing or Roadmap(project_id=project.id, raw_json={}, conversation_history=[])
    if not existing:
        db.add(roadmap)
        await db.flush()
    key_to_id: dict[str, int] = {}
    checkpoint_rows: list[tuple[Checkpoint, CheckpointProposal]] = []
    for order, item in enumerate(data.checkpoints, start=1):
        checkpoint = Checkpoint(
            roadmap_id=roadmap.id, title=item.title.strip(), description=item.objective.strip(),
            order=order, prerequisites=[], learning_status="not_started",
            learning_contract={
                "project_theme": project.name,
                "exit_criteria": list(item.success_criteria),
                "estimated_minutes": item.estimated_minutes,
                "knowledge_target": {"checkpoint_key": item.key},
                "practice_target": {"requires_generation": True},
            },
            brief={"project_theme": project.name, "checkpoint_key": item.key,
                   "objective": item.objective, "source_scope": "project"},
        )
        db.add(checkpoint)
        await db.flush()
        key_to_id[item.key] = checkpoint.id
        checkpoint_rows.append((checkpoint, item))
    raw_checkpoints = []
    for checkpoint, item in checkpoint_rows:
        checkpoint.prerequisites = [key_to_id[key] for key in item.prerequisites]
        raw_checkpoints.append({
            "id": checkpoint.id, "key": item.key, "title": item.title,
            "objective": item.objective, "order": checkpoint.order,
            "prerequisites": checkpoint.prerequisites,
            "success_criteria": item.success_criteria,
            "estimated_minutes": item.estimated_minutes,
        })
    roadmap.raw_json = {
        "schema_version": SCHEMA_VERSION, "project_theme": project.name,
        "rationale": data.rationale, "checkpoints": raw_checkpoints,
    }
    await ensure_all_checkpoint_learning_tasks(db, learner_id=current.learner.id, project_id=project.id)
    await record_event(
        db, learner_id=current.learner.id, project_id=project.id,
        event_type="roadmap_applied", source="ui",
        payload={"project_id": project.id, "project_theme": project.name,
                 "roadmap_id": roadmap.id, "rationale": data.rationale,
                 "checkpoints": raw_checkpoints, "mastery_unchanged": True},
        provenance={"endpoint": "POST /api/vnext-projects/{id}/roadmap/apply",
                    "explicit_click": True, "proposal_origin": "tutor_tool"},
        client_event_id=data.client_action_id,
    )
    view = await _workspace_view(db, current.learner.id, project)
    await db.commit()
    return view


@router.post("/{project_id}/sessions")
async def create_project_free_session(
    project_id: int,
    data: ProjectSessionCreateRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    session = AgentSession(
        learner_id=current.learner.id, session_type="project", project_id=project.id,
        title=data.title.strip() or f"{project.name} · 自由对话", status="active",
        context_summary={"project_theme": project.name, "role": "project_free"},
    )
    db.add(session)
    await db.flush()
    await record_event(
        db, learner_id=current.learner.id, project_id=project.id, session_id=session.id,
        event_type="project_free_conversation_created", source="ui",
        payload={"project_id": project.id, "session_id": session.id, "mastery_unchanged": True},
        provenance={"endpoint": "POST /api/vnext-projects/{id}/sessions", "explicit_click": True},
        client_event_id=data.client_action_id,
    )
    await db.commit()
    return {"session_id": session.id, "title": session.title, "project_id": project.id, "mode": "free"}


@router.delete("/{project_id}/sources/{source_id}")
async def remove_project_source(
    project_id: int,
    source_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    source = (await db.execute(select(Source).where(
        Source.id == source_id, Source.project_id == project_id,
    ))).scalar_one_or_none()
    if not source:
        raise HTTPException(404, "项目来源不存在")
    stored_path = str(((source.meta_data or {}).get("upload") or {}).get("stored_path") or "")
    await db.delete(source)
    await record_event(
        db, learner_id=current.learner.id, project_id=project_id,
        event_type="project_source_removed", source="ui",
        payload={"source_id": source_id, "source_type": source.type, "mastery_unchanged": True},
        provenance={"endpoint": "DELETE /api/vnext-projects/{id}/sources/{source_id}", "explicit_click": True},
        client_event_id=f"vnext-project:{project_id}:source:{source_id}:removed",
    )
    await db.commit()
    if stored_path:
        path = Path(stored_path)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return {"status": "removed", "source_id": source_id, "mastery_unchanged": True}


@router.get("/{project_id}/agent-context")
async def get_project_agent_context(
    project_id: int,
    checkpoint_id: int | None = None,
    query: str = "",
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    if checkpoint_id is not None:
        owned = (await db.execute(select(Checkpoint.id).join(Roadmap).where(
            Checkpoint.id == checkpoint_id, Roadmap.project_id == project.id,
        ))).scalar_one_or_none()
        if not owned:
            raise HTTPException(404, "关卡不属于当前项目")
    context = await build_five_kernel_context(
        db, learner_id=current.learner.id,
        policy="checkpoint_tutor" if checkpoint_id else "project_tutor",
        project_id=project.id, checkpoint_id=checkpoint_id,
        query=query or project.name,
    )
    sources = await _source_views(db, project.id)
    files = await _file_views(db, project.id)
    roadmap = (await db.execute(select(Roadmap).where(Roadmap.project_id == project.id))).scalar_one_or_none()
    checkpoints = list((roadmap.raw_json or {}).get("checkpoints") or []) if roadmap else []
    tasks = list((await db.execute(select(LearningTask).where(
        LearningTask.learner_id == current.learner.id,
        LearningTask.project_id == project.id,
    ).order_by(LearningTask.queue_position, LearningTask.id))).scalars().all())
    return {
        "schema_version": SCHEMA_VERSION,
        "project": _project_spec(project), "checkpoint_id": checkpoint_id,
        "roadmap": {"id": roadmap.id if roadmap else None, "checkpoints": checkpoints},
        "learning_tasks": [await learning_task_view(db, task) for task in tasks],
        "sources": sources, "learning_files": files,
        "source_excerpts": await _project_source_excerpts(db, project.id, query or project.name),
        "learning_file_previews": await _learning_file_previews(db, project.id),
        "five_kernel_context": context,
        "tool_policy": {
            "read_scope": "current_project_only", "source_content_untrusted": True,
            "roadmap_write_requires_user_confirmation": True,
            "learning_file_generation_requires_user_confirmation": True,
            "generated_content_never_implies_mastery": True,
        },
    }
