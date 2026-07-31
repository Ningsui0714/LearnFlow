"""
Task runners: long-running jobs executed by the TaskManager.

Each runner owns its own DB sessions (tasks outlive request sessions) and
updates Task progress + incremental results as it goes.
"""
from datetime import datetime
import asyncio
import os

from sqlalchemy import select

from app.db.database import async_session
from app.models.project import Task, Checkpoint, Roadmap, Project, Chunk, CheckpointChunk, Lecture, LectureVersion
from app.services.lecture_agent import LectureAgent
from app.services.task_manager import update_task


def _section_dict(title: str, content: str, keywords, questions) -> dict:
    return {
        "title": title,
        "content": content,
        "keywords": keywords or [],
        "questions": questions or [],
    }


# ── T6: image path rewrite + matplotlib rendering ──

def _rewrite_image_paths(content: str, source_file: str, source_id: int) -> str:
    """Rewrite relative image refs to absolute /api/sources/{id}/files/... URLs."""
    import re as _re
    md_dir = os.path.dirname(source_file or "")

    def _resolve(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith(("http://", "https://", "data:", "/api/", "blob:")):
            return raw
        raw = raw.split("#")[0].split("?")[0]
        resolved = os.path.normpath(os.path.join(md_dir, raw)).replace(os.sep, "/")
        return f"/api/sources/{source_id}/files/{resolved}"

    def _fix_md(m):
        return f"![{m.group(1)}]({_resolve(m.group(2))})"

    def _fix_html(m):
        return f'{m.group(1)}{_resolve(m.group(2))}{m.group(3)}'

    content = _re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _fix_md, content)
    content = _re.sub(r'(<img[^>]*src=")([^"]+)(")', _fix_html, content)
    return content


def _render_matplotlib_block(code: str, persist_dir: str, idx: int) -> str:
    """Execute a matplotlib code block → save png → return absolute URL (or '')."""
    import subprocess as _sp
    import sys as _sys
    import tempfile as _tf
    import time as _time
    gen_dir = os.path.join(persist_dir, "generated")
    os.makedirs(gen_dir, exist_ok=True)
    out_name = f"fig_{int(_time.time() * 1000)}_{idx}.png"
    out_path = os.path.join(gen_dir, out_name)
    script = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        f"{code}\n"
        f"plt.savefig({out_path!r}, dpi=120, bbox_inches='tight')\n"
    )
    with _tf.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        fpath = f.name
    try:
        # Run with the venv python (has matplotlib), not system python3
        venv_python = _sys.executable
        proc = _sp.run([venv_python, fpath], capture_output=True, text=True, timeout=45)
        if proc.returncode != 0 or not os.path.exists(out_path):
            print(f"[matplotlib] render failed: {proc.stderr[-200:]}")
            return ""
        return f"/api/sources/{os.path.basename(persist_dir)}/files/generated/{out_name}"
    except Exception as e:
        print(f"[matplotlib] render error: {type(e).__name__}: {str(e)[:150]}")
        return ""
    finally:
        try:
            os.unlink(fpath)
        except OSError:
            pass


def _postprocess_section(content: str, source_file: str, source_id: int, persist_dir: str) -> str:
    """Rewrite image paths + render matplotlib blocks (T6)."""
    import re as _re
    if not content:
        return content

    # Render matplotlib blocks → replace with image reference
    def _fix_mpl(m):
        url = _render_matplotlib_block(m.group(1), persist_dir, 0)
        if url:
            return f"\n![示意图]({url})\n"
        return "\n*（示意图渲染失败）*\n"

    content = _re.sub(r"```matplotlib\s*\n(.*?)```", _fix_mpl, content, flags=_re.DOTALL)
    content = _rewrite_image_paths(content, source_file, source_id)
    return content


async def _load_lecture_context(checkpoint_id: int):
    """Load checkpoint + project level + scope chunks for a checkpoint."""
    async with async_session() as db:
        checkpoint = (await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id)
        )).scalar_one_or_none()
        project = None
        user_level = "beginner"
        if roadmap:
            project = (await db.execute(
                select(Project).where(Project.id == roadmap.project_id)
            )).scalar_one_or_none()
            if project:
                user_level = project.user_level or "beginner"

        chunks_raw = (await db.execute(
            select(Chunk).join(CheckpointChunk)
            .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            .order_by(Chunk.index)
        )).scalars().all()
        chunks = [{"id": c.id, "source_id": c.source_id, "content": c.content, "meta": c.meta_data or {}} for c in chunks_raw]

        return checkpoint, user_level, chunks, (checkpoint.brief or {})


async def run_lecture_generation(task_id: int):
    """
    Lecture generation job:
    plan → per-section generate → save each section to Lecture immediately
    (incremental persistence). Supports resume: sections whose title matches
    the saved ones are reused instead of regenerated.
    """
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    checkpoint_id = (task.payload or {}).get("checkpoint_id")
    resume = bool((task.payload or {}).get("resume"))
    if not checkpoint_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 checkpoint_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    checkpoint, user_level, chunks, brief = await _load_lecture_context(checkpoint_id)

    # T6: derive repo-file cache dir from the main source
    from app.core.config import settings as _settings
    main_source_id = (brief or {}).get("scope", {}).get("main_source_id")
    if not main_source_id and chunks:
        main_source_id = chunks[0].get("source_id")
    persist_dir = os.path.join(_settings.repo_files_dir, str(main_source_id)) if main_source_id else ""

    if not chunks:
        await update_task(
            task_id, status="failed",
            error={"code": "retrieval_empty",
                   "message": "该关卡没有关联的参考资料切片",
                   "guidance": "请确认来源已处理完成、路线规划已分配切片",
                   "retryable": True},
            finished_at=datetime.utcnow())
        return

    agent = LectureAgent()

    # ── Plan (T4: structure-aware when brief has scope files) ──
    await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在规划大纲..."})
    try:
        skeleton = []
        scope_files = (brief or {}).get("scope", {}).get("files") or []
        if scope_files:
            skeleton = agent.build_structure_skeleton(brief, chunks)
        if skeleton:
            plan_sections = await agent.plan_lecture_structured(
                checkpoint.title, checkpoint.description or "", user_level,
                brief, chunks, skeleton,
            )
        else:
            plan_sections = await agent.plan_lecture(
                checkpoint.title, checkpoint.description or "", user_level, chunks, brief=brief
            )
    except Exception as e:
        from app.services.task_manager import classify_error
        err = classify_error(e)
        await update_task(task_id, status="failed", error=err, finished_at=datetime.utcnow())
        return
    total = len(plan_sections)
    if total == 0:
        plan_sections = [{"title": checkpoint.title, "keywords": [], "goal": checkpoint.description or ""}]
        total = 1

    # ── Load existing lecture (for resume / incremental append) ──
    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if not lecture:
            lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
            db.add(lecture)
            await db.commit()
            await db.refresh(lecture)
        if not resume:
            # T5: snapshot the published lecture before it gets overwritten
            if lecture.status == "published" and lecture.sections:
                db.add(LectureVersion(
                    checkpoint_id=checkpoint_id,
                    sections=list(lecture.sections),
                    reason="regenerate_before",
                ))
            # Fresh generation: clear stale partial content
            lecture.sections = []
            lecture.status = "draft"
            await db.commit()
        saved = list(lecture.sections or [])

    # ── Generate each section (reuse saved ones on resume) ──
    cited_all = []
    for i, ps in enumerate(plan_sections):
        title = ps.get("title", f"第{i+1}节")

        # Reuse on resume when the saved section matches this plan position
        if resume and i < len(saved) and saved[i].get("title") == title:
            content = saved[i].get("content", "")
            questions = saved[i].get("questions", [])
        else:
            try:
                content = await agent.generate_section(
                    checkpoint.title, ps, chunks,
                    section_keywords=ps.get("keywords", []),
                    brief=brief,
                    section_chunk_ids=ps.get("chunk_ids"),
                )
            except Exception as e:
                # One retry per section, then fail the task (partial remains)
                try:
                    content = await agent.generate_section(
                        checkpoint.title, ps, chunks,
                        section_keywords=ps.get("keywords", []),
                        brief=brief,
                        section_chunk_ids=ps.get("chunk_ids"),
                    )
                except Exception as e2:
                    from app.services.task_manager import classify_error
                    err = classify_error(e2)
                    await update_task(
                        task_id, status="failed", error=err,
                        progress={"current": i, "total": total,
                                  "message": f"第{i+1}节生成失败，已保留前 {i} 节"},
                        finished_at=datetime.utcnow())
                    return
            questions = agent._extract_questions(content)
            # T6: rewrite image paths + render matplotlib blocks
            content = _postprocess_section(
                content, ps.get("source_file", ""), main_source_id or 0, persist_dir)
            questions = agent._extract_questions(content)

        cited_all.extend(agent._extract_cited_chunks(content))
        sec = _section_dict(title, content, ps.get("keywords", []), questions)
        sec["source_file"] = ps.get("source_file", "")
        sec["source_heading"] = ps.get("source_heading", "")
        sec["cited_chunks"] = agent._extract_cited_chunks(content)

        # Incremental save: replace section at index (fresh) or append
        async with async_session() as db:
            lecture = (await db.execute(
                select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
            )).scalar_one_or_none()
            if lecture is None:
                lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
                db.add(lecture)
            sections = list(lecture.sections or [])
            while len(sections) <= i:
                sections.append(None)
            sections[i] = sec
            lecture.sections = sections
            lecture.status = "draft"
            await db.commit()

        await update_task(task_id, progress={
            "current": i + 1, "total": total,
            "message": f"生成中... {i+1}/{total}",
        })

    # ── Finalize ──
    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if lecture:
            lecture.status = "published"
        checkpoint = (await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if checkpoint:
            checkpoint.completed = True

        # T3 write-back: citation feedback → brief retrieval policy
        if checkpoint and checkpoint.brief:
            cp_chunks = (await db.execute(
                select(Chunk.id).join(CheckpointChunk)
                .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            )).scalars().all()
            scope_ids = set(cp_chunks)
            cited = set(cited_all)
            cited_in_scope = sorted(cited & scope_ids)
            new_brief = dict(checkpoint.brief)
            rp = dict(new_brief.get("retrieval_policy") or {})
            old_boost = set(rp.get("boost_chunk_ids") or [])
            rp["boost_chunk_ids"] = sorted(old_boost | set(cited_in_scope))
            new_brief["retrieval_policy"] = rp
            stats = dict(new_brief.get("retrieval_stats") or {})
            new_brief["retrieval_stats"] = {
                "version": stats.get("version", 0) + 1,
                "cited_chunks": sorted(cited),
                "cited_in_scope": cited_in_scope,
                "cited_out_of_scope": sorted(cited - scope_ids),
                "sections_count": len(plan_sections),
            }
            checkpoint.brief = new_brief
        await db.commit()

    await update_task(
        task_id, status="completed",
        progress={"current": total, "total": total, "message": f"完成！共 {total} 节"},
        result={"sections_count": total},
        finished_at=datetime.utcnow(),
    )


# ── T6: image captioning (Moonshot vision) → image chunks ──

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _scan_images(persist_dir: str) -> List[str]:
    """List image files (repo-relative paths), skipping generated/ and SVG
    (Moonshot vision rejects SVG; they are still served/rendered in lectures)."""
    out = []
    for root, dirs, files in os.walk(persist_dir):
        if os.path.basename(root) == "generated":
            continue
        rel_dir = os.path.relpath(root, persist_dir)
        for fn in files:
            ext = f".{fn.split('.')[-1].lower()}" if "." in fn else ""
            if ext in _IMAGE_EXTS:
                rel = os.path.join(rel_dir, fn) if rel_dir != "." else fn
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _map_images_to_md(persist_dir: str) -> dict:
    """Map image path → first referencing md file (relative to repo root)."""
    import re as _re
    mapping = {}
    for root, dirs, files in os.walk(persist_dir):
        dirs[:] = [d for d in dirs if d != "generated"]
        for fn in files:
            if not fn.endswith((".md", ".rst")):
                continue
            md_path = os.path.join(root, fn)
            rel_md = os.path.relpath(md_path, persist_dir).replace(os.sep, "/")
            try:
                with open(md_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            md_dir = os.path.dirname(rel_md)
            for m in _re.finditer(r"!\[.*?\]\(\s*(.*?)\s*\)", content):
                raw = m.group(1).strip()
                if raw.startswith(("http://", "https://", "data:")):
                    continue
                resolved = os.path.normpath(os.path.join(md_dir, raw)).replace(os.sep, "/")
                mapping.setdefault(resolved, rel_md)
    return mapping


async def run_image_captioning(task_id: int):
    """Caption all repo images → upsert as image chunks (caption-as-text RAG)."""
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    source_id = (task.payload or {}).get("source_id")
    if not source_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 source_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    from app.core.config import settings as _settings
    persist_dir = os.path.join(_settings.repo_files_dir, str(source_id))
    images = _scan_images(persist_dir)
    limit = (task.payload or {}).get("limit")
    if limit:
        images = images[: int(limit)]
    total = len(images)
    if total == 0:
        await update_task(task_id, status="completed",
                          progress={"current": 0, "total": 0, "message": "没有发现图片文件"},
                          result={"captioned": 0, "images": 0}, finished_at=datetime.utcnow())
        return

    md_map = _map_images_to_md(persist_dir)
    project_id = (task.payload or {}).get("project_id")

    # Precompute checkpoint → scope files (to auto-link image chunks)
    cp_scope = {}  # cp_id -> set(files)
    if project_id:
        async with async_session() as db:
            cps = (await db.execute(
                select(Checkpoint).join(Roadmap).where(Roadmap.project_id == project_id)
            )).scalars().all()
            for cp in cps:
                files = set(((cp.brief or {}).get("scope") or {}).get("files") or [])
                if files:
                    cp_scope[cp.id] = files

    from app.services import vision
    from sqlalchemy import func as _func
    async with async_session() as db:
        next_index = (await db.execute(
            select(_func.max(Chunk.index)).where(Chunk.source_id == source_id)
        )).scalar() or 0

    captioned = failed = 0
    sem = asyncio.Semaphore(3)  # 轻并发，highspeed 模型无压力

    async def _caption_one(rel: str) -> str:
        async with sem:
            return await asyncio.to_thread(
                vision.caption_image, os.path.join(persist_dir, rel))

    for i, rel in enumerate(images):
        await update_task(task_id, progress={
            "current": i, "total": total, "message": f"理解图片 {i + 1}/{total}: {rel[-40:]}",
        })
        try:
            caption = await _caption_one(rel)
        except Exception as e:
            failed += 1
            print(f"[caption] {rel} failed: {type(e).__name__}: {str(e)[:120]}")
            continue

        ref_md = md_map.get(rel, "")
        content = f"【图片】{rel}: {caption}"
        meta = {
            "type": "image",
            "source_type": "github",
            "file": ref_md or rel,
            "image_path": rel,
            "caption": caption,
            "headings": [],
            "heading_chain": [],
            "caption_model": _settings.vision_model,
        }
        async with async_session() as db:
            existing = (await db.execute(
                select(Chunk).where(
                    Chunk.source_id == source_id,
                    Chunk.meta_data["image_path"].as_string() == rel,
                )
            )).scalars().all()
            if existing:
                chunk = existing[0]
                chunk.content = content
                chunk.meta_data = meta
            else:
                next_index += 1
                chunk = Chunk(
                    source_id=source_id,
                    index=next_index,
                    content=content,
                    tokens=len(content) // 4,
                    meta_data=meta,
                )
                db.add(chunk)
                await db.flush()

            # Auto-link to checkpoints whose scope includes the referencing md file
            if ref_md and cp_scope:
                for cp_id, files in cp_scope.items():
                    if ref_md in files:
                        exists = (await db.execute(
                            select(CheckpointChunk).where(
                                CheckpointChunk.checkpoint_id == cp_id,
                                CheckpointChunk.chunk_id == chunk.id,
                            )
                        )).scalar_one_or_none()
                        if not exists:
                            db.add(CheckpointChunk(checkpoint_id=cp_id, chunk_id=chunk.id))
            await db.commit()
        captioned += 1

    await update_task(
        task_id, status="completed",
        progress={"current": total, "total": total, "message": f"完成：{captioned} 张图片已生成描述"},
        result={"captioned": captioned, "failed": failed, "images": total},
        finished_at=datetime.utcnow(),
    )
