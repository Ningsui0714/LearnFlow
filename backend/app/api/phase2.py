"""
Phase 2 API routes:
- Lecture generation (SSE streaming)
- Lecture retrieval
- Q&A agent for selected text
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.database import get_db
from app.models.project import Project, Roadmap, Checkpoint, CheckpointChunk, Chunk, Lecture, Task, LectureVersion
from app.schemas.project import (
    AgentMessage, LectureAskRequest,
)
from app.services.lecture_agent import LectureAgent, QAAgent

router = APIRouter()


@router.post("/checkpoints/{checkpoint_id}/lecture/generate")
async def generate_lecture_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    req: dict = Body(default={}),
):
    """Create a background lecture-generation task (T1).

    Returns {task_id, status}. If a task is already running for this
    checkpoint, returns the existing one (frontend subscribes to it).
    mode: "fresh" (default) clears partial content; "resume" reuses saved sections.
    """
    mode = (req or {}).get("mode", "fresh")
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")

    result = await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))
    checkpoint = result.scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    from app.models.project import Project, Roadmap
    roadmap = (await db.execute(select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id))).scalar_one_or_none()
    project_id = roadmap.project_id if roadmap else None

    # Deduplicate: reuse an already-running task
    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "lecture_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        project_id=project_id,
        checkpoint_id=checkpoint_id,
        type="lecture_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id, "resume": mode == "resume"},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.task_runners import run_lecture_generation
    manager.submit(task.id, run_lecture_generation(task.id))

    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/lecture/task")
async def get_lecture_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Latest generation task for a checkpoint (used on page load / reconnect)."""
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "lecture_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    lecture = (await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )).scalar_one_or_none()
    sections = [s for s in (lecture.sections if lecture and lecture.sections else []) if s]
    return _snapshot(task, sections)


@router.get("/checkpoints/{checkpoint_id}/lecture/generate")
async def generate_lecture_stream(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Legacy direct-SSE generation endpoint (kept for compatibility; use POST + /tasks/{id}/events)."""
    from app.api.tasks import _snapshot as _unused  # noqa: F401
    try:
        # Quick API key check
        if not settings.llm_api_key or settings.llm_api_key == "***":
            async def _key_error():
                yield f"data: {json.dumps({'type': 'error', 'message': '请先配置 API Key...'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_key_error(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

        # Get checkpoint
        result = await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))
        checkpoint = result.scalar_one_or_none()
        if not checkpoint:
            raise HTTPException(404, "Checkpoint not found")

        # Get project
        r = await db.execute(select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id))
        roadmap = r.scalar_one_or_none()
        project = None
        if roadmap:
            p = await db.execute(select(Project).where(Project.id == roadmap.project_id))
            project = p.scalar_one_or_none()
        user_level = project.user_level if project else "beginner"

        # Get chunks via CP
        cc_result = await db.execute(
            select(Chunk).join(CheckpointChunk)
            .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            .order_by(Chunk.index)
        )
        chunks_raw = cc_result.scalars().all()
        chunks = [{"id": c.id, "content": c.content, "meta": c.meta_data or {}} for c in chunks_raw]

        agent = LectureAgent()

        async def event_stream():
            try:
                async for section_data in agent.generate_full_lecture(
                    checkpoint_title=checkpoint.title,
                    checkpoint_description=checkpoint.description or "",
                    user_level=user_level,
                    chunks=chunks,
                ):
                    yield f"data: {json.dumps(section_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback; traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:200]}")


@router.post("/checkpoints/{checkpoint_id}/lecture/save")
async def save_lecture(
    checkpoint_id: int,
    sections_data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Save generated lecture sections to database."""
    result = await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )
    lecture = result.scalar_one_or_none()

    sections = sections_data.get("sections", [])

    if not lecture:
        lecture = Lecture(
            checkpoint_id=checkpoint_id,
            sections=[{
                "title": s.get("title", ""),
                "content": s.get("content", ""),
                "keywords": s.get("keywords", []),
                "questions": s.get("questions", []),
            } for s in sections],
            status="published",
        )
        db.add(lecture)
    else:
        lecture.sections = [{
            "title": s.get("title", ""),
            "content": s.get("content", ""),
            "keywords": s.get("keywords", []),
            "questions": s.get("questions", []),
        } for s in sections]
        lecture.status = "published"

    # Mark checkpoint as completed
    cp_result = await db.execute(
        select(Checkpoint).where(Checkpoint.id == checkpoint_id)
    )
    cp = cp_result.scalar_one_or_none()
    if cp:
        cp.completed = True

    await db.commit()

    return {"status": "ok", "sections": len(sections)}


@router.get("/checkpoints/{checkpoint_id}/lecture")
async def get_lecture(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get stored lecture for a checkpoint."""
    result = await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )
    lecture = result.scalar_one_or_none()
    if not lecture:
        # Return checkpoint info even without lecture
        cp_result = await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )
        cp = cp_result.scalar_one_or_none()
        if not cp:
            raise HTTPException(404, "Checkpoint not found")
        return {
            "id": None,
            "checkpoint_id": checkpoint_id,
            "checkpoint_title": cp.title,
            "sections": [],
            "status": "none",
        }

    return {
        "id": lecture.id,
        "checkpoint_id": lecture.checkpoint_id,
        "sections": lecture.sections or [],
        "status": lecture.status,
    }


# ── T5: Lecture versioning + rollback ──

@router.get("/checkpoints/{checkpoint_id}/lecture/versions")
async def list_lecture_versions(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List snapshotted versions (newest first)."""
    rows = (await db.execute(
        select(LectureVersion)
        .where(LectureVersion.checkpoint_id == checkpoint_id)
        .order_by(LectureVersion.id.desc())
    )).scalars().all()
    return [{
        "id": v.id,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "reason": v.reason or "",
        "sections_count": len(v.sections or []),
        "preview": ((v.sections or [{}])[0].get("title", "") if v.sections else ""),
    } for v in rows]


@router.post("/checkpoints/{checkpoint_id}/lecture/rollback")
async def rollback_lecture(
    checkpoint_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Restore a previous version. Current content is snapshotted first."""
    version_id = (data or {}).get("version_id")
    if not version_id:
        raise HTTPException(400, "缺少 version_id")
    version = (await db.execute(
        select(LectureVersion).where(
            LectureVersion.id == version_id,
            LectureVersion.checkpoint_id == checkpoint_id,
        )
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found")

    lecture = (await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )).scalar_one_or_none()
    if not lecture:
        lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
        db.add(lecture)
        await db.flush()

    # Snapshot current state before replacing (safety)
    if lecture.sections:
        db.add(LectureVersion(
            checkpoint_id=checkpoint_id,
            sections=list(lecture.sections),
            reason="before_rollback",
        ))

    lecture.sections = list(version.sections or [])
    lecture.status = "published"
    await db.commit()
    return {"status": "ok", "sections": len(lecture.sections or [])}


@router.post("/checkpoints/{checkpoint_id}/ask")
async def ask_question(
    checkpoint_id: int,
    req: LectureAskRequest,
    db: AsyncSession = Depends(get_db),
):
    """Answer a question about selected lecture text."""
    result = await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )
    lecture = result.scalar_one_or_none()

    checkpoint_title = ""
    if not lecture:
        cp_result = await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )
        cp = cp_result.scalar_one_or_none()
        checkpoint_title = cp.title if cp else ""
    else:
        cp_result = await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )
        cp = cp_result.scalar_one_or_none()
        checkpoint_title = cp.title if cp else ""

    # Find the section that contains the selected text
    section_content = ""
    if lecture and lecture.sections:
        for s in lecture.sections:
            if req.selection in s.get("content", ""):
                section_content = s.get("content", "")
                break
        if not section_content and lecture.sections:
            section_content = lecture.sections[0].get("content", "")

    agent = QAAgent()
    answer = await agent.answer(
        question=req.question,
        selected_text=req.selection,
        section_content=section_content,
        checkpoint_title=checkpoint_title,
        history=[m.model_dump() for m in req.history],
    )

    return {"answer": answer}
