from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Integer
from typing import List

from app.db.database import get_db
from app.models.project import Project, Source, Chunk, Roadmap, Checkpoint, CheckpointChunk
from app.schemas.project import (
    ProjectCreate, ProjectOut, ProjectDetail,
    SourceCreate, SourceOut, ChunkOut,
    RoadmapOut, RoadmapNode,
)
from app.services.auth import CurrentLearner, get_current_learner, require_owned_project

router = APIRouter()


# ── Project CRUD ──

@router.post("/projects", response_model=ProjectDetail)
async def create_project(
    data: ProjectCreate,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    from app.services.learning_runtime import record_event
    project = Project(
        learner_id=current.learner.id,
        name=data.name,
        description=data.description,
        user_level=data.user_level,
    )
    db.add(project)
    await db.flush()
    await record_event(
        db, event_type="project_created", source="ui",
        learner_id=current.learner.id,
        project_id=project.id,
        payload={"project_id": project.id, "name": project.name,
                 "description": project.description or ""},
        provenance={"endpoint": "POST /api/projects"},
        client_event_id=f"project:{project.id}:created",
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", response_model=List[ProjectOut])
async def list_projects(
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.learner_id == current.learner.id).order_by(Project.created_at.desc())
    )
    projects_list = result.scalars().all()
    out = []
    for p in projects_list:
        src_count = await db.scalar(
            select(func.count(Source.id)).where(Source.project_id == p.id)
        )
        cp_result = await db.execute(
            select(
                func.count(Checkpoint.id),
                func.sum((Checkpoint.learning_status == "completed").cast(Integer)),
                func.sum((Checkpoint.learning_status == "verification_due").cast(Integer)),
            )
            .select_from(Roadmap)
            .outerjoin(Checkpoint, Checkpoint.roadmap_id == Roadmap.id)
            .where(Roadmap.project_id == p.id)
        )
        cp_row = cp_result.one()
        out.append(ProjectOut(
            id=p.id, name=p.name, description=p.description,
            user_level=p.user_level, created_at=p.created_at,
            source_count=src_count or 0,
            checkpoint_count=cp_row[0] or 0,
            completed_count=cp_row[1] or 0,
            verification_due_count=cp_row[2] or 0,
        ))
    return out


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return await require_owned_project(db, current.learner.id, project_id)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and all related data."""
    # Also clear embedding cache for this project's chunks
    from app.services.embedding import load_cache, save_cache
    project = await require_owned_project(db, current.learner.id, project_id)
    
    # Get chunk IDs before deletion
    chunk_ids = []
    from app.models.project import Source, Chunk
    srcs = await db.execute(select(Chunk.id).join(Source).where(Source.project_id == project_id))
    chunk_ids = [r[0] for r in srcs.all()]
    
    # Delete project (cascades to sources, chunks, roadmap, checkpoints, etc.)
    await db.delete(project)
    await db.commit()
    
    # Clean up embedding cache
    try:
        cache = load_cache()
        for cid in chunk_ids:
            cache.pop(f"chunk-{cid}", None)
        save_cache(cache)
    except Exception:
        pass
    
    return {"status": "ok", "deleted": project.name, "chunks_cleaned": len(chunk_ids)}


# ── Sources ──

@router.post("/projects/{project_id}/sources", response_model=SourceOut)
async def add_source(
    project_id: int,
    data: SourceCreate,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)

    source = Source(project_id=project_id, type=data.type, url=data.url)
    db.add(source)
    await db.flush()
    from app.services.learning_runtime import record_event
    await record_event(
        db, event_type="source_added", source="ui", project_id=project_id,
        learner_id=current.learner.id,
        payload={"source_id": source.id, "url": source.url, "type": source.type},
        provenance={"endpoint": "POST /api/projects/{id}/sources"},
        client_event_id=f"source:{source.id}:added",
    )
    await db.commit()
    await db.refresh(source)
    return SourceOut(id=source.id, project_id=source.project_id, type=source.type,
                     url=source.url, status=source.status, error=source.error,
                     chunk_count=0, created_at=source.created_at)


@router.get("/projects/{project_id}/sources", response_model=List[SourceOut])
async def list_sources(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    result = await db.execute(
        select(Source, func.count(Chunk.id).label("chunk_count"))
        .outerjoin(Chunk, Chunk.source_id == Source.id)
        .where(Source.project_id == project_id)
        .group_by(Source.id)
        .order_by(Source.created_at.desc())
    )
    rows = result.all()
    return [
        SourceOut(id=s.id, project_id=s.project_id, type=s.type, url=s.url,
                  status=s.status, error=s.error, chunk_count=cc or 0, created_at=s.created_at)
        for s, cc in rows
    ]


# ── Chunks ──

@router.get("/projects/{project_id}/chunks", response_model=List[ChunkOut])
async def list_chunks(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    result = await db.execute(
        select(Chunk)
        .join(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.id, Chunk.index)
    )
    chunks = result.scalars().all()
    return [ChunkOut(id=c.id, source_id=c.source_id, index=c.index,
                     content=c.content, tokens=c.tokens, metadata=c.meta_data or {})
            for c in chunks]


# ── Roadmap ──

@router.get("/projects/{project_id}/roadmap")
async def get_roadmap(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_project(db, current.learner.id, project_id)
    result = await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )
    roadmap = result.scalar_one_or_none()
    if not roadmap:
        return {"id": None, "project_id": project_id, "checkpoints": []}

    cp_result = await db.execute(
        select(Checkpoint)
        .where(Checkpoint.roadmap_id == roadmap.id)
        .order_by(Checkpoint.order)
    )
    checkpoints = cp_result.scalars().all()

    nodes = []
    for cp in checkpoints:
        ccr = await db.execute(
            select(CheckpointChunk.chunk_id)
            .where(CheckpointChunk.checkpoint_id == cp.id)
        )
        raw_ids = [r[0] for r in ccr.all()]
        chunk_ids = []
        for cid in raw_ids:
            try:
                chunk_ids.append(int(str(cid).replace("chunk-", "").replace("chunk", "").strip()))
            except (ValueError, TypeError):
                pass
        nodes.append(RoadmapNode(
            id=cp.id, title=cp.title, description=cp.description or "",
            order=cp.order, prerequisites=cp.prerequisites or [],
            completed=(cp.learning_status == "completed"), chunk_ids=chunk_ids, brief=cp.brief or {},
            archived=cp.archived or False, progress=cp.progress or {},
            learning_status=cp.learning_status or "not_started",
            learning_contract=cp.learning_contract or {},
        ))

    return RoadmapOut(id=roadmap.id, project_id=project_id, checkpoints=nodes)
