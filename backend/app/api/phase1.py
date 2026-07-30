"""
API routes for Phase 1 features:
- Source processing
- Roadmap agent chat
"""
from fastapi import APIRouter, Depends, HTTPException
import json
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.database import get_db
from app.models.project import Project, Source, Chunk, Roadmap, Checkpoint, CheckpointChunk
from app.schemas.project import (
    AgentChatRequest, AgentChatResponse,
)
from app.services.chunker import SourceProcessor
from app.services.roadmap_agent import RoadmapAgent

router = APIRouter()
chunker = SourceProcessor()


# ── Source Processing ──

@router.post("/projects/{project_id}/sources/{source_id}/process")
async def process_source(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Fetch and chunk a source."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    # Update status
    source.status = "processing"
    await db.commit()

    try:
        # Process the source (now returns {chunks, source_meta})
        result_data = await chunker.process_source(source.type, source.url)
        chunks_data = result_data["chunks"]
        source_meta = result_data.get("source_meta", {})

        # Store directory structure/toc as source metadata
        if source_meta:
            try:
                source.meta_data = {**(source.meta_data or {}), "repo_analysis": source_meta}
            except AttributeError:
                pass  # meta_data column may not exist on old DB

        # Delete previous chunks for this source
        old = await db.execute(select(Chunk).where(Chunk.source_id == source.id))
        for c in old.scalars().all():
            await db.delete(c)

        # Insert new chunks with rich metadata
        for cd in chunks_data:
            chunk = Chunk(
                source_id=source.id,
                index=cd["index"],
                content=cd["content"],
                tokens=cd["tokens"],
                meta_data=cd.get("meta", {}),
            )
            db.add(chunk)

        source.status = "processed"
        await db.commit()
        return {"status": "ok", "chunk_count": len(chunks_data)}

    except Exception as e:
        source.status = "failed"
        source.error = str(e)
        await db.commit()
        raise HTTPException(500, f"Source processing failed: {str(e)}")


# ── Process All Sources ──

@router.post("/projects/{project_id}/sources/process-all")
async def process_all_sources(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Process all pending sources for a project."""
    result = await db.execute(
        select(Source).where(
            Source.project_id == project_id,
            Source.status.in_(["pending", "failed"])
        )
    )
    sources = result.scalars().all()
    if not sources:
        return {"status": "ok", "processed": 0, "message": "No sources to process"}

    count = 0
    errors = []
    for source in sources:
        try:
            source.status = "processing"
            await db.commit()

            # New: returns {chunks, source_meta}
            result_data = await chunker.process_source(source.type, source.url)
            chunks_data = result_data["chunks"]
            source_meta = result_data.get("source_meta", {})
            if source_meta:
                try:
                    source.meta_data = {**(source.meta_data or {}), "repo_analysis": source_meta}
                except AttributeError:
                    pass

            old = await db.execute(select(Chunk).where(Chunk.source_id == source.id))
            for c in old.scalars().all():
                await db.delete(c)

            for cd in chunks_data:
                chunk = Chunk(
                    source_id=source.id,
                    index=cd["index"],
                    content=cd["content"],
                    tokens=cd["tokens"],
                    meta_data=cd.get("meta", {}),
                )
                db.add(chunk)

            source.status = "processed"
            await db.commit()
            count += 1

        except Exception as e:
            source.status = "failed"
            source.error = str(e)
            await db.commit()
            errors.append({"source_id": source.id, "error": str(e)})

    return {"status": "ok", "processed": count, "errors": errors}


# ── Roadmap Agent Chat ──

@router.post("/projects/{project_id}/roadmap/chat", response_model=AgentChatResponse)
async def roadmap_chat(
    project_id: int,
    req: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat with the roadmap planning agent."""
    # Get project info
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    # Get chunks
    chunk_result = await db.execute(
        select(Chunk)
        .join(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.id, Chunk.index)
    )
    chunks = chunk_result.scalars().all()
    chunks_data = [
        {
            "id": c.id,
            "source_id": c.source_id,
            "index": c.index,
            "content": c.content[:500],
            "meta": c.meta_data or {},
        }
        for c in chunks
    ]

    # Get source metadata for directory structure
    src_result = await db.execute(
        select(Source).where(Source.project_id == project_id)
    )
    sources = src_result.scalars().all()
    dir_info = None
    for s in sources:
        if s.meta_data:
            try:
                meta = json.loads(s.meta_data) if isinstance(s.meta_data, str) else s.meta_data
            except Exception:
                meta = s.meta_data
            if meta and isinstance(meta, dict) and meta.get("repo_analysis"):
                dir_info = meta
                break

    # Get existing roadmap (or create placeholder on first chat)
    existing_roadmap = None
    r_result = await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )
    roadmap = r_result.scalar_one_or_none()
    if roadmap:
        existing_roadmap = roadmap.raw_json
    else:
        # Create roadmap placeholder immediately to store conversation
        roadmap = Roadmap(project_id=project_id, raw_json={"checkpoints": []}, conversation_history=[])
        db.add(roadmap)
        await db.commit()
        await db.refresh(roadmap)

    # Check if LLM is configured
    if not settings.llm_api_key or settings.llm_api_key in ("", "sk-your-key-here"):
        raise HTTPException(
            400,
            "请先配置 API Key: 复制 .env.example 为 .env，并填入 LLM_API_KEY"
        )

    # Run agent
    try:
        agent = RoadmapAgent()
        result = await agent.chat(
            message=req.message,
            history=[m.model_dump() for m in req.history],
            topic=project.name,
            chunks=chunks_data,
            existing_roadmap=existing_roadmap,
            dir_info=dir_info,
        )
    except Exception as e:
        raise HTTPException(502, f"AI Agent error: {str(e)}")

    # Save conversation history
    if roadmap:
        history = roadmap.conversation_history or []
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": result["message"]})
        # Keep last 50 messages
        roadmap.conversation_history = history[-50:]
        await db.commit()

    # If roadmap was updated, save it
    if result["updated_roadmap"]:
        if not roadmap:
            roadmap = Roadmap(project_id=project_id, raw_json=result["updated_roadmap"])
            db.add(roadmap)
        else:
            roadmap.raw_json = result["updated_roadmap"]
            from datetime import datetime
            roadmap.updated_at = datetime.utcnow()

        await db.commit()

        # Also create/update checkpoint records
        await _sync_checkpoints(db, project_id, result["updated_roadmap"])

    return AgentChatResponse(
        message=result["message"],
        updated_roadmap=result["updated_roadmap"],
    )


@router.get("/projects/{project_id}/roadmap/history")
async def get_roadmap_history(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the persistent conversation history for a project's roadmap."""
    result = await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )
    roadmap = result.scalar_one_or_none()
    if not roadmap:
        return {"history": []}
    return {"history": roadmap.conversation_history or []}


async def _sync_checkpoints(db: AsyncSession, project_id: int, roadmap_data: dict):
    """Sync checkpoint records from roadmap JSON to DB."""
    r_result = await db.execute(select(Roadmap).where(Roadmap.project_id == project_id))
    roadmap = r_result.scalar_one_or_none()
    if not roadmap:
        return

    # Get existing checkpoints
    cp_result = await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
    )
    existing = {cp.order: cp for cp in cp_result.scalars().all()}

    seen_orders = set()
    for node in roadmap_data.get("checkpoints", []):
        order = node["order"]
        seen_orders.add(order)

        # Clear chunk assignments
        # (will reassign below)
        if order in existing:
            cp = existing[order]
            cp.title = node.get("title", cp.title)
            cp.description = node.get("description", cp.description)
            cp.prerequisites = node.get("prerequisites", [])
        else:
            cp = Checkpoint(
                roadmap_id=roadmap.id,
                title=node.get("title", ""),
                description=node.get("description", ""),
                order=order,
                prerequisites=node.get("prerequisites", []),
                completed=False,
            )
            db.add(cp)
            await db.flush()

        # Assign chunks — parse IDs (LLM may output "chunk-36" strings or 36 integers)
        raw_ids = node.get("chunk_ids", [])
        chunk_ids = []
        for cid in raw_ids:
            if isinstance(cid, str):
                # Strip "chunk-" prefix and parse as int
                cid = cid.replace("chunk-", "").replace("chunk", "").strip()
            try:
                chunk_ids.append(int(cid))
            except (ValueError, TypeError):
                pass
        # Remove old assignments
        old_cc = await db.execute(
            select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
        )
        for cc in old_cc.scalars().all():
            await db.delete(cc)
        # Add new assignments
        for cid in chunk_ids:
            cc = CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid)
            db.add(cc)

    # Remove checkpoints that are no longer in the roadmap
    for order, cp in existing.items():
        if order not in seen_orders and not cp.completed:
            await db.delete(cp)

    await db.commit()
