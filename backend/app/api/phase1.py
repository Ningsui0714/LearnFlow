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


# ── L1: File Summaries (batch LLM, cached) ──

@router.post("/projects/{project_id}/sources/{source_id}/analyze")
async def analyze_source_structure(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Backfill L0 structure confidence + logic type from existing repo analysis
    (no LLM, no re-chunking — safe for already-processed sources).
    """
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    meta = dict(source.meta_data or {})
    ra = dict(meta.get("repo_analysis") or {})
    if not ra.get("dir_groups"):
        raise HTTPException(400, "该来源没有目录结构，无法分析（请先重新处理来源）")

    confidence = chunker.compute_structure_confidence(ra.get("readme_toc", []), ra.get("dir_groups", []))
    logic = chunker.detect_structure_logic(ra.get("dir_groups", []), ra.get("readme_toc", []))
    ra["structure_confidence"] = confidence
    ra["structure_logic"] = logic
    # CRITICAL: JSON columns are compared with == at flush time. If we mutate
    # the loaded dict in place, the "new" value equals the original → no UPDATE.
    # Always copy on read, then assign a fresh dict.
    source.meta_data = {**meta, "repo_analysis": ra}
    await db.commit()

    return {"status": "ok", "structure_confidence": confidence, "structure_logic": logic}


@router.post("/projects/{project_id}/sources/{source_id}/summarize")
async def summarize_source_files(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate one-line summaries per file (L1 of repo understanding).
    Cached in source.meta_data.repo_analysis.file_summaries; idempotent.
    """
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    meta = dict(source.meta_data or {})
    repo_analysis = dict(meta.get("repo_analysis") or {})
    cached = repo_analysis.get("file_summaries")
    if cached:
        return {"status": "ok", "cached": True, "files_count": len(cached), "summaries": cached}

    if source.type != "github" or not repo_analysis.get("dir_groups"):
        raise HTTPException(400, "该来源没有目录结构，无法生成文件摘要（仅支持 GitHub 仓库）")

    # Group chunks by file
    chunk_result = await db.execute(
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.index)
    )
    chunks = chunk_result.scalars().all()
    by_file = {}
    for c in chunks:
        fp = (c.meta_data or {}).get("file", "") or f"chunk-{c.id}"
        by_file.setdefault(fp, []).append(c)

    if not by_file:
        raise HTTPException(400, "该来源没有可读取的切片")

    # API key check
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.2,
        timeout=60,
        max_retries=0,
    )

    import re as _re, json as _json
    files = sorted(by_file.keys())
    summaries = {}
    BATCH = 40
    for i in range(0, len(files), BATCH):
        batch = files[i:i + BATCH]
        lines = []
        for fp in batch:
            cs = by_file[fp]
            preview = cs[0].content[:150].replace("\n", " ")
            lines.append(f"- {fp} ({len(cs)} 块): {preview}")
        prompt = (
            "你是仓库结构分析器。下面是仓库中一批文件的路径与内容预览。\n"
            "请为每个文件生成一句话中文摘要，说明它在学习资料中的作用。\n"
            f"共 {len(batch)} 个文件：\n" + "\n".join(lines) + "\n\n"
            "输出 JSON：{\"文件路径\": \"一句话摘要\", ...}。只输出 JSON，不要多余文字。"
        )
        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            content = resp.content
            m = _re.search(r"```json\s*(.*?)\s*```", content, _re.DOTALL)
            if m:
                data = _json.loads(m.group(1))
                for k, v in data.items():
                    summaries[k] = str(v)[:120]
            else:
                # Fallback: try to find a bare JSON object
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end > start:
                    data = _json.loads(content[start:end + 1])
                    for k, v in data.items():
                        summaries[k] = str(v)[:120]
        except Exception as e:
            print(f"[Summarize] batch {i // BATCH} failed: {e}")

    if not summaries:
        raise HTTPException(502, "文件摘要生成失败，请重试或检查 LLM 配置")

    repo_analysis["file_summaries"] = summaries
    # CRITICAL: JSON columns are compared with == at flush time. If we mutate
    # the loaded dict in place, the "new" value equals the original → no UPDATE.
    # Always copy on read, then assign a fresh dict.
    source.meta_data = {**meta, "repo_analysis": repo_analysis}
    await db.commit()

    return {"status": "ok", "cached": False, "files_count": len(summaries), "summaries": summaries}


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

    # Get chunks (full content — tools read on demand, no truncation)
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
            "content": c.content,
            "meta": c.meta_data or {},
        }
        for c in chunks
    ]

    # Source metadata (repo analysis + file summaries) for L0/L1 tools
    src_result = await db.execute(
        select(Source).where(Source.project_id == project_id)
    )
    sources = src_result.scalars().all()
    sources_info = []
    for s in sources:
        meta = s.meta_data or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        sources_info.append({
            "source_id": s.id,
            "type": s.type,
            "url": s.url,
            "repo_analysis": meta.get("repo_analysis") or {},
        })

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

    # Merge real completed status from DB into the roadmap nodes (by order)
    if existing_roadmap and roadmap:
        cp_rows = (await db.execute(
            select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
        )).scalars().all()
        completed_by_order = {cp.order: cp.completed for cp in cp_rows}
        for node in existing_roadmap.get("checkpoints", []):
            node["completed"] = completed_by_order.get(node.get("order"), False)

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
            sources_info=sources_info,
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
    """Sync checkpoint records from roadmap JSON to DB (T2).

    Chunk assignment is scope-based: the agent's "files" decide which chunks
    belong to a checkpoint (deterministic, by file ownership); the agent's
    chunk_ids become "seed_chunks" that boost retrieval downstream. Each
    checkpoint also gets a CheckpointBrief (handoff contract).
    """
    r_result = await db.execute(select(Roadmap).where(Roadmap.project_id == project_id))
    roadmap = r_result.scalar_one_or_none()
    if not roadmap:
        return

    # Load project chunks grouped by file (for scope assignment + briefs)
    all_chunks = (await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id)
    )).scalars().all()
    chunks_by_id = {c.id: c for c in all_chunks}
    chunks_by_file = {}
    for c in all_chunks:
        fp = (c.meta_data or {}).get("file", "")
        if fp:
            chunks_by_file.setdefault(fp, []).append(c)

    # Source-level structure info for briefs
    sources = (await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.id)
    )).scalars().all()
    structure_logic, structure_confidence = "mixed", "low"
    for s in sources:
        meta = s.meta_data or {}
        ra = meta.get("repo_analysis") or {}
        if ra.get("structure_logic"):
            structure_logic = ra["structure_logic"]
            structure_confidence = (ra.get("structure_confidence") or {}).get("level", "low")
            break
    main_source_id = sources[0].id if sources else None

    # Get existing checkpoints
    cp_result = await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
    )
    existing = {cp.order: cp for cp in cp_result.scalars().all()}

    def _parse_ids(raw_ids) -> list:
        ids = []
        for cid in raw_ids or []:
            if isinstance(cid, str):
                cid = cid.replace("chunk-", "").replace("chunk", "").strip()
            try:
                ids.append(int(cid))
            except (ValueError, TypeError):
                pass
        return ids

    seen_orders = set()
    for node in roadmap_data.get("checkpoints", []):
        order = node["order"]
        seen_orders.add(order)

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

        # ── Scope-based chunk assignment ──
        seed_ids = _parse_ids(node.get("chunk_ids"))
        files = [f for f in (node.get("files") or []) if isinstance(f, str) and f in chunks_by_file]
        scope_ids = []
        if files:
            for f in files:
                scope_ids += [c.id for c in chunks_by_file[f]]
            scope_ids = list(dict.fromkeys(scope_ids))
        if not scope_ids:
            # Fallback: seed chunks only
            scope_ids = [i for i in seed_ids if i in chunks_by_id]

        # Remove old assignments, add scope assignments
        old_cc = await db.execute(
            select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
        )
        for cc in old_cc.scalars().all():
            await db.delete(cc)
        for cid in scope_ids:
            db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid))

        # ── CheckpointBrief (handoff contract for downstream agents) ──
        seeds_in_scope = [i for i in seed_ids if i in scope_ids]
        mapping_conf = (
            "high"
            if files and seed_ids and len(seeds_in_scope) == len(seed_ids)
            else "medium"
        )
        cp.brief = {
            "version": 1,
            "checkpoint_id": cp.id,
            "order": order,
            "title": node.get("title", ""),
            "objective": node.get("description", ""),
            "prerequisites": node.get("prerequisites", []),
            "scope": {
                "main_source_id": main_source_id,
                "files": files,
                "structure_logic": structure_logic,
                "structure_confidence": structure_confidence,
            },
            "seed_chunks": seed_ids,
            "chunk_mapping_confidence": mapping_conf,
            "key_concepts": node.get("key_concepts", []),
            "retrieval_policy": {
                "boost_chunk_ids": seed_ids,
                "boost_weight": 1.5,
                "restrict_to_scope": bool(files),
                "allow_fallback_global": True,
            },
            "practice_plan": {"concept": True, "code": True},
        }

    # Remove checkpoints that are no longer in the roadmap (completed are kept)
    for order, cp in existing.items():
        if order not in seen_orders and not cp.completed:
            await db.delete(cp)

    await db.commit()
