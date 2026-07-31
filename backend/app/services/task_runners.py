"""
Task runners: long-running jobs executed by the TaskManager.

Each runner owns its own DB sessions (tasks outlive request sessions) and
updates Task progress + incremental results as it goes.
"""
from datetime import datetime

from sqlalchemy import select

from app.db.database import async_session
from app.models.project import Task, Checkpoint, Roadmap, Project, Chunk, CheckpointChunk, Lecture
from app.services.lecture_agent import LectureAgent
from app.services.task_manager import update_task


def _section_dict(title: str, content: str, keywords, questions) -> dict:
    return {
        "title": title,
        "content": content,
        "keywords": keywords or [],
        "questions": questions or [],
    }


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
        chunks = [{"id": c.id, "content": c.content, "meta": c.meta_data or {}} for c in chunks_raw]

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

    # ── Plan ──
    await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在规划大纲..."})
    try:
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
            # Fresh generation: clear stale partial content
            lecture.sections = []
            lecture.status = "draft"
            await db.commit()
        saved = list(lecture.sections or [])

    # ── Generate each section (reuse saved ones on resume) ──
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
                )
            except Exception as e:
                # One retry per section, then fail the task (partial remains)
                try:
                    content = await agent.generate_section(
                        checkpoint.title, ps, chunks,
                        section_keywords=ps.get("keywords", []),
                        brief=brief,
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

        sec = _section_dict(title, content, ps.get("keywords", []), questions)

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
        await db.commit()

    await update_task(
        task_id, status="completed",
        progress={"current": total, "total": total, "message": f"完成！共 {total} 节"},
        result={"sections_count": total},
        finished_at=datetime.utcnow(),
    )
