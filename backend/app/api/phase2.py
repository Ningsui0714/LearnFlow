"""
Phase 2 API routes:
- Lecture generation (SSE streaming)
- Lecture retrieval
- Q&A agent for selected text
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.database import get_db
from app.models.project import Project, Roadmap, Checkpoint, CheckpointChunk, Chunk, Lecture
from app.schemas.project import (
    AgentMessage, LectureAskRequest,
)
from app.services.lecture_agent import LectureAgent, QAAgent

router = APIRouter()


@router.get("/checkpoints/{checkpoint_id}/lecture/generate")
async def generate_lecture_stream(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Generate lecture for a checkpoint, streaming via SSE."""
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
