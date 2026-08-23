"""Unified learner-visible task queue and adaptive plan runtime.

LearningTask is the persistent coordination layer above Tutor sessions,
checkpoint learning objects and focused micro-learning runs.  It never grades
work or writes KernelState directly; authoritative evidence continues through
LearningAttempt and EvidenceEvent.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.learning import (
    AgentSession,
    LearningAttempt,
    LearningTask,
    LearningTaskPlanRevision,
    MicroLearningRun,
    ReviewSchedule,
)
from app.models.project import (
    Checkpoint,
    ConceptQuestion,
    Exercise,
    Lecture,
    Project,
    Roadmap,
)
from app.services.architecture_registry import SEMANTIC_MEMORY_KEYS, SKILLS
from app.services.learning_runtime import get_kernel_projection, record_event


PLAN_SCHEMA_VERSION = "learning-task-plan.v1"
RUNTIME_VERSION = "learning-task-runtime-v1"
ACTIVE_STATUSES = {"proposed", "queued", "active", "paused"}
QUEUE_STATUSES = {"queued", "active", "paused"}
ALLOWED_PHASE_KINDS = {"learn", "practice", "verify", "consolidate"}

PLAN_PROMPT = """你是 LearnFlow 的学习设计 Agent。请为一个原子学习任务生成可恢复、可调整的阶段计划。

任务标题：{title}
目标：{objective}
来源类型：{origin_kind}
预计时间：{estimated_minutes} 分钟
学习者偏好的技能：{preferred_skills}
学习者五核只读提示：{learner_context}
可用技能：{available_skills}
调整原因：{reason}
学习者方向：{learner_direction}

要求：
1. 只输出 JSON 对象；phases 为 2-4 个粗粒度阶段，不要拆成细碎点击步骤。
2. kind 只能是 learn、practice、verify、consolidate，每种最多一次。
3. methods 只能从可用技能 ID 中选择，按需组合，不要为了完整而全部使用。
4. verify 必须要求独立作答或可执行产物；讲解、复述和自述不能直接算掌握。
5. consolidate 表示把已产生的正式评估交给复习队列，不代表复习已经完成。
6. completion_rule 写可检查的任务内条件，不得写“模型判断已掌握”。

格式：
{{
  "summary": "计划为何这样安排",
  "estimated_minutes": 20,
  "phases": [
    {{
      "id": "learn",
      "kind": "learn",
      "title": "建立理解",
      "purpose": "本阶段目的",
      "methods": ["guided_explanation"],
      "required": true,
      "completion_rule": "学习者完成本阶段互动或打开正式讲义",
      "artifact_outputs": ["lecture"]
    }}
  ],
  "adaptation_triggers": ["学习者要求换种讲法", "验证暴露关键缺口"]
}}"""


def _clean(value: Any, limit: int = 2_000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _now() -> datetime:
    return datetime.utcnow()


def _available_plan_skills() -> set[str]:
    return {
        "guided_explanation", "socratic_dialogue", "feynman_dialogue",
        "evidence_grounded_teaching", "verified_micro_learning",
        "practice_verification", "remediation_loop", "spaced_review",
    } & set(SKILLS)


def _compact_planner_context(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Keep only registered, decision-relevant short-term fields for planning."""
    result: dict[str, dict[str, Any]] = {}
    for kernel_name, allowed_keys in SEMANTIC_MEMORY_KEYS.items():
        short = dict((projection.get(kernel_name) or {}).get("short_term") or {})
        values = {
            key: short[key]
            for key in sorted(allowed_keys)
            if key in short and short[key] not in (None, "", (), [])
        }
        if values:
            result[kernel_name] = values
    return result


def _fallback_plan(
    *,
    title: str,
    objective: str,
    origin_kind: str,
    estimated_minutes: int,
    preferred_skills: list[str] | None = None,
    learner_context: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    learner_context = dict(learner_context or {})
    allowed = _available_plan_skills()
    preferred = [item for item in (preferred_skills or []) if item in allowed]
    learn_methods = preferred[:2]
    if not learn_methods:
        learn_methods = [
            "evidence_grounded_teaching" if origin_kind == "checkpoint" else "guided_explanation"
        ]
    human = dict(learner_context.get("human") or {})
    knowledge = dict(learner_context.get("knowledge") or {})
    value = dict(learner_context.get("value") or {})
    practice = dict(learner_context.get("practice") or {})
    high_load = isinstance(human.get("cognitive_load"), (int, float)) and human["cognitive_load"] >= 0.7
    knowledge_gap = _clean(knowledge.get("knowledge_gap"), 220)
    needs_scaffolding = practice.get("assistance_level") in {"guided", "high", "full"}
    current_priority = _clean(value.get("current_priority"), 220)
    phases = [
        {
            "id": "learn",
            "kind": "learn",
            "title": "分段建立可解释的理解" if high_load else "建立可解释的理解",
            "purpose": (
                f"先处理已知缺口“{knowledge_gap}”，再围绕“{objective}”形成能继续追问和练习的理解。"
                if knowledge_gap else f"围绕“{objective}”形成一份能继续追问和练习的理解。"
            ),
            "methods": learn_methods,
            "required": True,
            "status": "pending",
            "completion_rule": "完成本阶段互动，或打开并学习任务关联的正式讲义。",
            "artifact_outputs": ["lecture"] if origin_kind == "checkpoint" else [],
        },
        {
            "id": "practice",
            "kind": "practice",
            "title": "主动练习与纠错",
            "purpose": (
                "先用有限脚手架启动，再逐步撤除提示并通过独立尝试暴露缺口；答错时进入确定性纠错闭环。"
                if needs_scaffolding else
                "通过独立尝试暴露缺口；答错时进入现有确定性纠错闭环。"
            ),
            "methods": ["practice_verification", "remediation_loop"],
            "required": True,
            "status": "pending",
            "completion_rule": "至少提交一次正式练习或形成一个可检查产物。",
            "artifact_outputs": ["exercise"],
        },
        {
            "id": "verify",
            "kind": "verify",
            "title": "独立验证",
            "purpose": "用无提示作答或可执行产物检查本次目标是否真正完成。",
            "methods": ["verified_micro_learning", "practice_verification"],
            "required": True,
            "status": "pending",
            "completion_rule": "存在归属于当前学习者和任务范围的正式评估证据。",
            "artifact_outputs": ["assessment"],
        },
        {
            "id": "consolidate",
            "kind": "consolidate",
            "title": "转交复习队列",
            "purpose": "把正式评估产生的复习项交给独立复习工作台。",
            "methods": ["spaced_review"],
            "required": True,
            "status": "pending",
            "completion_rule": "已创建至少一个可解释的复习计划，或明确记录本任务无需复习项。",
            "artifact_outputs": ["review_schedule"],
        },
    ]
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "summary": (
            f"围绕当前优先事项“{current_priority}”，先学习、再练习和独立验证，最后转交复习队列；任务完成不等于稳定掌握。"
            if current_priority else
            "先学习、再练习和独立验证，最后转交复习队列；任务完成不等于稳定掌握。"
        ),
        "estimated_minutes": min(estimated_minutes, 20) if high_load else estimated_minutes,
        "phases": phases,
        "adaptation_triggers": [
            "学习者要求换一种方法",
            "正式练习暴露新的关键缺口",
            "时间预算或任务目标发生变化",
        ],
        "objective": objective,
        "title": title,
        "personalization_basis": [
            {"kernel": kernel_name, "keys": sorted(values)}
            for kernel_name, values in learner_context.items() if values
        ],
    }


def _extract_json(content: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(content[index:])
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("learning-task planner returned no JSON object")


def _validated_plan(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    allowed_skills = _available_plan_skills()
    phases: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()
    for item in list(raw.get("phases") or [])[:4]:
        if not isinstance(item, dict):
            continue
        kind = _clean(item.get("kind"), 40)
        if kind not in ALLOWED_PHASE_KINDS or kind in seen_kinds:
            continue
        methods = [
            _clean(method, 80) for method in list(item.get("methods") or [])
            if _clean(method, 80) in allowed_skills
        ][:4]
        if not methods:
            methods = next(
                (list(phase["methods"]) for phase in fallback["phases"] if phase["kind"] == kind),
                [],
            )
        phase = {
            "id": kind,
            "kind": kind,
            "title": _clean(item.get("title"), 160) or kind,
            "purpose": _clean(item.get("purpose"), 700),
            "methods": methods,
            "required": bool(item.get("required", True)),
            "status": "pending",
            "completion_rule": _clean(item.get("completion_rule"), 700),
            "artifact_outputs": [
                _clean(value, 60) for value in list(item.get("artifact_outputs") or [])
                if _clean(value, 60)
            ][:6],
        }
        phases.append(phase)
        seen_kinds.add(kind)
    if not {"learn", "verify"} <= seen_kinds:
        phases = list(fallback["phases"])
    return {
        **fallback,
        "summary": _clean(raw.get("summary"), 1_000) or fallback["summary"],
        "estimated_minutes": max(
            5, min(int(raw.get("estimated_minutes") or fallback["estimated_minutes"]), 1_440)
        ),
        "phases": phases,
        "adaptation_triggers": [
            _clean(value, 300) for value in list(raw.get("adaptation_triggers") or [])
            if _clean(value, 300)
        ][:6] or fallback["adaptation_triggers"],
    }


async def generate_learning_task_plan(
    *,
    title: str,
    objective: str,
    origin_kind: str,
    estimated_minutes: int,
    preferred_skills: list[str] | None = None,
    learner_context: dict[str, dict[str, Any]] | None = None,
    reason: str = "initial plan",
    learner_direction: str = "",
) -> dict[str, Any]:
    fallback = _fallback_plan(
        title=title,
        objective=objective,
        origin_kind=origin_kind,
        estimated_minutes=estimated_minutes,
        preferred_skills=preferred_skills,
        learner_context=learner_context,
    )
    if not settings.llm_api_key or settings.llm_api_key in {"", "***", "sk-your-key-here"}:
        return fallback
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.25,
        timeout=60,
        max_retries=0,
        max_tokens=3_500,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=PLAN_PROMPT.format(
            title=title,
            objective=objective,
            origin_kind=origin_kind,
            estimated_minutes=estimated_minutes,
            preferred_skills=preferred_skills or [],
            learner_context=json.dumps(learner_context or {}, ensure_ascii=False),
            available_skills=sorted(_available_plan_skills()),
            reason=reason,
            learner_direction=learner_direction or "未指定",
        ))])
        return _validated_plan(_extract_json(str(response.content)), fallback)
    except Exception:
        return fallback


async def _next_queue_position(db: AsyncSession, learner_id: int) -> int:
    value = (await db.execute(select(func.max(LearningTask.queue_position)).where(
        LearningTask.learner_id == learner_id,
        LearningTask.status.in_(ACTIVE_STATUSES),
    ))).scalar_one_or_none()
    return int(value or 0) + 1000


async def _validate_scope(
    db: AsyncSession,
    *,
    learner_id: int,
    session_id: int | None,
    project_id: int | None,
    checkpoint_id: int | None,
) -> tuple[AgentSession | None, Project | None, Checkpoint | None]:
    session = None
    project = None
    checkpoint = None
    if session_id:
        session = (await db.execute(select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.learner_id == learner_id,
        ))).scalar_one_or_none()
        if not session:
            raise RuntimeError("invalid_scope")
    if project_id:
        project = (await db.execute(select(Project).where(
            Project.id == project_id,
            Project.learner_id == learner_id,
        ))).scalar_one_or_none()
        if not project:
            raise RuntimeError("invalid_scope")
    if checkpoint_id:
        checkpoint = (await db.execute(
            select(Checkpoint)
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .join(Project, Project.id == Roadmap.project_id)
            .where(Checkpoint.id == checkpoint_id, Project.learner_id == learner_id)
        )).scalar_one_or_none()
        if not checkpoint:
            raise RuntimeError("invalid_scope")
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
        resolved_project_id = roadmap.project_id if roadmap else None
        if project_id and resolved_project_id != project_id:
            raise RuntimeError("invalid_scope")
        if not project:
            project = await db.get(Project, resolved_project_id)
            project_id = resolved_project_id
    if session:
        if project_id and session.project_id not in {None, project_id}:
            raise RuntimeError("invalid_scope")
        if checkpoint_id and session.checkpoint_id not in {None, checkpoint_id}:
            raise RuntimeError("invalid_scope")
    return session, project, checkpoint


async def _append_revision(
    db: AsyncSession,
    task: LearningTask,
    *,
    source: str,
    reason: str,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> LearningTaskPlanRevision:
    revision = LearningTaskPlanRevision(
        learning_task_id=task.id,
        version=task.plan_version,
        source=source,
        reason=reason,
        plan=dict(task.plan or {}),
        evidence_refs=list(evidence_refs or []),
    )
    db.add(revision)
    await db.flush()
    return revision


async def _record_task_event(
    db: AsyncSession,
    task: LearningTask,
    event_type: str,
    *,
    source: str,
    suffix: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await record_event(
        db,
        learner_id=task.learner_id,
        project_id=task.project_id,
        checkpoint_id=task.checkpoint_id,
        session_id=task.session_id,
        event_type=event_type,
        source=source,
        payload={
            "learning_task_id": task.id,
            "runtime_version": RUNTIME_VERSION,
            **dict(payload or {}),
        },
        client_event_id=f"learning-task:{task.id}:{suffix}",
    )


async def create_learning_task(
    db: AsyncSession,
    *,
    learner_id: int,
    title: str,
    objective: str,
    client_request_id: str,
    origin_kind: str = "manual",
    created_by: str = "user",
    status: str = "queued",
    session_id: int | None = None,
    project_id: int | None = None,
    checkpoint_id: int | None = None,
    micro_learning_run_id: int | None = None,
    priority: int = 0,
    estimated_minutes: int = 20,
    due_at: datetime | None = None,
    preferred_skills: list[str] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    success_criteria: list[str] | None = None,
) -> tuple[LearningTask, bool]:
    existing = (await db.execute(select(LearningTask).where(
        LearningTask.learner_id == learner_id,
        LearningTask.client_request_id == client_request_id,
    ))).scalar_one_or_none()
    if existing:
        return existing, False
    _, project, checkpoint = await _validate_scope(
        db,
        learner_id=learner_id,
        session_id=session_id,
        project_id=project_id,
        checkpoint_id=checkpoint_id,
    )
    if checkpoint and not project_id:
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
        project_id = roadmap.project_id if roadmap else None
    learner_context = _compact_planner_context(
        await get_kernel_projection(db, learner_id)
    )
    plan = await generate_learning_task_plan(
        title=_clean(title, 255),
        objective=_clean(objective, 2_000),
        origin_kind=origin_kind,
        estimated_minutes=estimated_minutes,
        preferred_skills=preferred_skills,
        learner_context=learner_context,
    )
    now = _now()
    task = LearningTask(
        learner_id=learner_id,
        session_id=session_id,
        project_id=project_id,
        checkpoint_id=checkpoint_id,
        micro_learning_run_id=micro_learning_run_id,
        origin_kind=origin_kind,
        created_by=created_by,
        title=_clean(title, 255),
        objective=_clean(objective, 2_000),
        status=status,
        priority=priority,
        queue_position=await _next_queue_position(db, learner_id),
        estimated_minutes=int(plan.get("estimated_minutes") or estimated_minutes),
        due_at=due_at,
        source_refs=list(source_refs or []),
        success_criteria=[_clean(item, 500) for item in list(success_criteria or []) if _clean(item, 500)],
        plan=plan,
        current_phase_id=(
            str((plan.get("phases") or [{}])[0].get("id") or "")
            if status == "active" else ""
        ),
        plan_version=1,
        execution_state={"evidence_refs": [], "completed_phase_ids": []},
        artifact_refs=[],
        review_handoff={},
        action_log=[],
        client_request_id=client_request_id,
        accepted_at=now if status != "proposed" else None,
        started_at=now if status == "active" else None,
    )
    db.add(task)
    await db.flush()
    await _append_revision(db, task, source="learning_design", reason="initial plan")
    await _record_task_event(
        db, task, "learning_task_created", source=created_by,
        suffix="created",
        payload={"origin_kind": origin_kind, "status": status, "plan_version": 1},
    )
    if status != "proposed":
        await _record_task_event(
            db, task, "learning_task_accepted", source=created_by,
            suffix="accepted",
            payload={"origin_kind": origin_kind},
        )
    if status == "active":
        await _record_task_event(
            db, task, "learning_task_started", source=created_by,
            suffix="started",
        )
    return task, True


async def load_owned_learning_task(
    db: AsyncSession, learner_id: int, task_id: int,
) -> LearningTask | None:
    return (await db.execute(select(LearningTask).where(
        LearningTask.id == task_id,
        LearningTask.learner_id == learner_id,
    ))).scalar_one_or_none()


async def ensure_checkpoint_learning_task(
    db: AsyncSession,
    *,
    learner_id: int,
    checkpoint: Checkpoint,
    session_id: int | None = None,
) -> LearningTask:
    existing = (await db.execute(select(LearningTask).where(
        LearningTask.learner_id == learner_id,
        LearningTask.checkpoint_id == checkpoint.id,
    ))).scalar_one_or_none()
    if existing:
        if session_id and not existing.session_id:
            existing.session_id = session_id
        return existing
    roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
    if not roadmap:
        raise RuntimeError("invalid_scope")
    contract = dict(checkpoint.learning_contract or {})
    criteria = [str(item) for item in list(contract.get("exit_criteria") or [])]
    task, _ = await create_learning_task(
        db,
        learner_id=learner_id,
        title=checkpoint.title,
        objective=checkpoint.description or f"完成关卡：{checkpoint.title}",
        client_request_id=f"checkpoint:{checkpoint.id}",
        origin_kind="checkpoint",
        created_by="system",
        status="completed" if checkpoint.learning_status == "completed" else "queued",
        session_id=session_id,
        project_id=roadmap.project_id,
        checkpoint_id=checkpoint.id,
        estimated_minutes=30,
        success_criteria=criteria,
        source_refs=[{"type": "checkpoint", "id": checkpoint.id}],
    )
    if task.status == "completed":
        now = _now()
        task.completed_at = now
        plan = dict(task.plan or {})
        plan["phases"] = [{**phase, "status": "completed"} for phase in plan.get("phases", [])]
        task.plan = plan
    return task


async def ensure_all_checkpoint_learning_tasks(
    db: AsyncSession,
    *,
    learner_id: int,
    project_id: int | None = None,
) -> int:
    query = (
        select(Checkpoint, Roadmap.project_id)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Project.learner_id == learner_id,
            Checkpoint.archived.is_(False),
        )
    )
    if project_id:
        query = query.where(Project.id == project_id)
    rows = (await db.execute(query.order_by(Project.id, Checkpoint.order))).all()
    created = 0
    from app.services.tutor_service import get_or_create_session
    for checkpoint, resolved_project_id in rows:
        session = await get_or_create_session(
            db,
            learner_id=learner_id,
            session_type="checkpoint",
            project_id=resolved_project_id,
            checkpoint_id=checkpoint.id,
        )
        before = (await db.execute(select(LearningTask.id).where(
            LearningTask.learner_id == learner_id,
            LearningTask.checkpoint_id == checkpoint.id,
        ))).scalar_one_or_none()
        await ensure_checkpoint_learning_task(
            db, learner_id=learner_id, checkpoint=checkpoint, session_id=session.id,
        )
        created += int(before is None)
    return created


async def attach_micro_learning_task(
    db: AsyncSession,
    *,
    run: MicroLearningRun,
) -> LearningTask:
    checkpoint = await db.get(Checkpoint, run.checkpoint_id)
    if not checkpoint:
        raise RuntimeError("invalid_scope")
    task = await ensure_checkpoint_learning_task(
        db,
        learner_id=run.learner_id,
        checkpoint=checkpoint,
        session_id=run.session_id,
    )
    changed = False
    for field, value in (
        ("micro_learning_run_id", run.id),
        ("origin_kind", "micro_learning"),
        ("title", run.goal[:255]),
        ("objective", run.goal),
    ):
        if getattr(task, field) != value:
            setattr(task, field, value)
            changed = True
    if run.status == "completed":
        if task.status != "completed":
            task.status = "completed"
            task.completed_at = run.completed_at or _now()
            changed = True
            await _record_task_event(
                db,
                task,
                "learning_task_completed",
                source="micro_learning",
                suffix=f"completed:micro:{run.id}",
                payload={"completion_kind": "operational", "mastery_claimed": False},
            )
    elif task.status in {"queued", "paused"}:
        task.status = "active"
        task.started_at = task.started_at or _now()
        changed = True
        await _record_task_event(
            db,
            task,
            "learning_task_started",
            source="micro_learning",
            suffix=f"started:micro:{run.id}",
        )
    if changed:
        task.version += 1
    return task


async def backfill_learning_tasks(db: AsyncSession) -> dict[str, int]:
    learners = list((await db.execute(select(Project.learner_id).distinct())).scalars().all())
    checkpoint_count = 0
    for learner_id in learners:
        checkpoint_count += await ensure_all_checkpoint_learning_tasks(
            db, learner_id=learner_id,
        )
    runs = list((await db.execute(select(MicroLearningRun))).scalars().all())
    for run in runs:
        project = await db.get(Project, run.project_id)
        if project:
            project.project_kind = "task_artifact"
            project.visibility = "internal"
        await attach_micro_learning_task(db, run=run)
    return {"checkpoint_tasks_created": checkpoint_count, "micro_runs_linked": len(runs)}


async def _valid_evidence_refs(
    db: AsyncSession,
    task: LearningTask,
    refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attempt_ids = {
        int(item["id"]) for item in refs
        if isinstance(item, dict)
        and item.get("type") == "learning_attempt"
        and str(item.get("id", "")).isdigit()
    }
    if not attempt_ids:
        return []
    query = select(LearningAttempt).where(
        LearningAttempt.id.in_(attempt_ids),
        LearningAttempt.learner_id == task.learner_id,
        LearningAttempt.evaluated_at.is_not(None),
    )
    if task.checkpoint_id:
        query = query.where(LearningAttempt.checkpoint_id == task.checkpoint_id)
    rows = list((await db.execute(query)).scalars().all())
    return [
        {
            "type": "learning_attempt",
            "id": row.id,
            "attempt_role": row.attempt_role,
            "assistance_level": row.assistance_level,
        }
        for row in rows
    ]


async def _verification_refs(db: AsyncSession, task: LearningTask) -> list[dict[str, Any]]:
    existing = list((task.execution_state or {}).get("evidence_refs") or [])
    validated = await _valid_evidence_refs(db, task, existing)
    if task.checkpoint_id:
        rows = list((await db.execute(select(LearningAttempt).where(
            LearningAttempt.learner_id == task.learner_id,
            LearningAttempt.checkpoint_id == task.checkpoint_id,
            LearningAttempt.evaluated_at.is_not(None),
        ).order_by(LearningAttempt.id.desc()).limit(20))).scalars().all())
        known = {item["id"] for item in validated}
        validated.extend({
            "type": "learning_attempt",
            "id": row.id,
            "attempt_role": row.attempt_role,
            "assistance_level": row.assistance_level,
        } for row in rows if row.id not in known)
    return validated


def _phase_map(task: LearningTask) -> dict[str, dict[str, Any]]:
    return {
        str(phase.get("id")): dict(phase)
        for phase in list((task.plan or {}).get("phases") or [])
        if isinstance(phase, dict) and phase.get("id")
    }


def _set_phase_status(task: LearningTask, phase_id: str, status: str) -> None:
    plan = dict(task.plan or {})
    phases = []
    for phase in list(plan.get("phases") or []):
        row = dict(phase)
        if row.get("id") == phase_id:
            row["status"] = status
            if status == "completed":
                row["completed_at"] = _now().isoformat()
        phases.append(row)
    plan["phases"] = phases
    task.plan = plan
    task.current_phase_id = next(
        (str(item.get("id")) for item in phases if item.get("status") != "completed"),
        "",
    )


async def _review_schedule_refs(db: AsyncSession, task: LearningTask) -> list[dict[str, Any]]:
    if not task.checkpoint_id:
        return []
    schedules = list((await db.execute(select(ReviewSchedule).where(
        ReviewSchedule.learner_id == task.learner_id,
        ReviewSchedule.checkpoint_id == task.checkpoint_id,
    ).order_by(ReviewSchedule.id))).scalars().all())
    return [
        {"type": "review_schedule", "id": row.id, "due_at": row.due_at.isoformat()}
        for row in schedules
    ]


async def reconcile_learning_task(db: AsyncSession, task: LearningTask) -> bool:
    changed = False
    if task.micro_learning_run_id:
        run = await db.get(MicroLearningRun, task.micro_learning_run_id)
        if run and run.learner_id == task.learner_id and run.status == "completed":
            for phase_id in _phase_map(task):
                if _phase_map(task)[phase_id].get("status") != "completed":
                    _set_phase_status(task, phase_id, "completed")
                    changed = True
            if task.status != "completed":
                task.status = "completed"
                task.completed_at = run.completed_at or _now()
                await _record_task_event(
                    db, task, "learning_task_completed", source="micro_learning",
                    suffix="completed", payload={"mastery_unchanged": True},
                )
                changed = True
    if task.checkpoint_id:
        checkpoint = await db.get(Checkpoint, task.checkpoint_id)
        if checkpoint and checkpoint.learning_status == "completed" and task.status != "completed":
            for phase_id in _phase_map(task):
                _set_phase_status(task, phase_id, "completed")
            task.status = "completed"
            task.completed_at = _now()
            await _record_task_event(
                db, task, "learning_task_completed", source="checkpoint_runtime",
                suffix="completed", payload={"mastery_unchanged": True},
            )
            changed = True
    review_refs = await _review_schedule_refs(db, task)
    if review_refs:
        task.review_handoff = {"status": "scheduled", "items": review_refs}
        phase = _phase_map(task).get("consolidate")
        if phase and phase.get("status") != "completed":
            _set_phase_status(task, "consolidate", "completed")
            changed = True
    if changed:
        task.version += 1
    return changed


async def _artifact_refs(db: AsyncSession, task: LearningTask) -> list[dict[str, Any]]:
    if not task.checkpoint_id:
        return list(task.artifact_refs or [])
    checkpoint = await db.get(Checkpoint, task.checkpoint_id)
    if not checkpoint:
        return list(task.artifact_refs or [])
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint.id,
    ).order_by(Lecture.version.desc(), Lecture.id.desc()).limit(1))).scalar_one_or_none()
    exercises = list((await db.execute(select(Exercise).where(
        Exercise.checkpoint_id == checkpoint.id,
    ).order_by(Exercise.order, Exercise.id))).scalars().all())
    questions = list((await db.execute(select(ConceptQuestion.id).where(
        ConceptQuestion.checkpoint_id == checkpoint.id,
    ).order_by(ConceptQuestion.order, ConceptQuestion.id))).scalars().all())
    project_id = task.project_id
    prefix = f"{str(checkpoint.order).zfill(2)}-{checkpoint.title}"
    refs: list[dict[str, Any]] = []
    if lecture:
        refs.append({
            "type": "managed_lecture",
            "id": lecture.id,
            "logical_filename": f"{prefix}.lflecture",
            "path": f"/projects/{project_id}/checkpoints/{checkpoint.id}",
        })
    for exercise in exercises:
        refs.append({
            "type": "managed_exercise",
            "id": exercise.id,
            "logical_filename": f"{prefix}-{str(exercise.order).zfill(2)}.lfexercise",
            "path": f"/projects/{project_id}/checkpoints/{checkpoint.id}/exercises?exercise={exercise.id}",
        })
    if questions:
        refs.append({
            "type": "concept_question_set",
            "ids": questions,
            "logical_filename": f"{prefix}-概念验证.lfexercise",
            "path": f"/projects/{project_id}/checkpoints/{checkpoint.id}/exercises",
        })
    return refs


def _navigation(task: LearningTask) -> dict[str, Any]:
    if task.micro_learning_run_id:
        return {"kind": "focused_learning", "path": f"/learn/{task.micro_learning_run_id}"}
    if task.checkpoint_id and task.project_id:
        return {
            "kind": "checkpoint",
            "path": f"/projects/{task.project_id}/checkpoints/{task.checkpoint_id}",
        }
    if task.session_id:
        return {"kind": "conversation", "path": f"/agent/{task.session_id}"}
    return {"kind": "task", "path": f"/tasks?task={task.id}"}


def _available_actions(task: LearningTask) -> list[str]:
    if task.status == "proposed":
        return ["accept", "cancel"]
    if task.status == "queued":
        return ["start", "cancel"]
    if task.status == "active":
        return ["complete_phase", "pause", "complete_task", "cancel"]
    if task.status == "paused":
        return ["resume", "cancel"]
    if task.status == "canceled":
        return ["reopen"]
    return []


async def learning_task_view(db: AsyncSession, task: LearningTask) -> dict[str, Any]:
    await reconcile_learning_task(db, task)
    revisions = list((await db.execute(select(LearningTaskPlanRevision).where(
        LearningTaskPlanRevision.learning_task_id == task.id,
    ).order_by(LearningTaskPlanRevision.version.desc()).limit(12))).scalars().all())
    return {
        "id": task.id,
        "title": task.title,
        "objective": task.objective,
        "status": task.status,
        "origin_kind": task.origin_kind,
        "created_by": task.created_by,
        "session_id": task.session_id,
        "project_id": task.project_id,
        "checkpoint_id": task.checkpoint_id,
        "micro_learning_run_id": task.micro_learning_run_id,
        "priority": task.priority,
        "queue_position": task.queue_position,
        "estimated_minutes": task.estimated_minutes,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "source_refs": list(task.source_refs or []),
        "success_criteria": list(task.success_criteria or []),
        "plan": dict(task.plan or {}),
        "current_phase_id": task.current_phase_id,
        "plan_version": task.plan_version,
        "execution_state": dict(task.execution_state or {}),
        "artifact_refs": await _artifact_refs(db, task),
        "review_handoff": dict(task.review_handoff or {}),
        "navigation": _navigation(task),
        "available_actions": _available_actions(task),
        "version": task.version,
        "accepted_at": task.accepted_at.isoformat() if task.accepted_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "plan_history": [
            {
                "id": item.id,
                "version": item.version,
                "source": item.source,
                "reason": item.reason,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in revisions
        ],
        "evidence_notice": "学习任务完成是流程里程碑，不等于稳定掌握；掌握只由正式证据链决定。",
    }


def _already_logged(task: LearningTask, client_action_id: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("client_action_id") == client_action_id
        for item in list(task.action_log or [])
    )


def _log_action(task: LearningTask, client_action_id: str, action: str, **extra: Any) -> None:
    task.action_log = [
        *list(task.action_log or []),
        {
            "client_action_id": client_action_id,
            "action": action,
            "at": _now().isoformat(),
            **extra,
        },
    ][-200:]


async def act_on_learning_task(
    db: AsyncSession,
    *,
    task: LearningTask,
    action: str,
    expected_version: int,
    client_action_id: str,
    phase_id: str = "",
    evidence_refs: list[dict[str, Any]] | None = None,
) -> LearningTask:
    if _already_logged(task, client_action_id):
        return task
    if task.version != expected_version:
        raise RuntimeError("version_conflict")
    now = _now()
    event_type = ""
    if action == "accept" and task.status == "proposed":
        task.status = "queued"
        task.accepted_at = now
        event_type = "learning_task_accepted"
    elif action == "start" and task.status == "queued":
        task.status = "active"
        task.started_at = task.started_at or now
        task.current_phase_id = next(iter(_phase_map(task)), "")
        event_type = "learning_task_started"
    elif action == "pause" and task.status == "active":
        task.status = "paused"
        event_type = "learning_task_paused"
    elif action == "resume" and task.status == "paused":
        task.status = "active"
        event_type = "learning_task_resumed"
    elif action == "cancel" and task.status in ACTIVE_STATUSES:
        task.status = "canceled"
        task.canceled_at = now
        event_type = "learning_task_canceled"
    elif action == "reopen" and task.status == "canceled":
        task.status = "queued"
        task.canceled_at = None
        event_type = "learning_task_resumed"
    elif action == "complete_phase" and task.status == "active":
        phase = _phase_map(task).get(phase_id)
        if not phase or phase.get("status") == "completed":
            raise RuntimeError("invalid_state")
        valid_refs = await _valid_evidence_refs(db, task, list(evidence_refs or []))
        if phase.get("kind") == "verify":
            valid_refs = valid_refs or await _verification_refs(db, task)
            if not valid_refs:
                raise RuntimeError("verification_required")
        if phase.get("kind") == "consolidate":
            review_refs = await _review_schedule_refs(db, task)
            if not review_refs:
                raise RuntimeError("review_handoff_required")
            task.review_handoff = {"status": "scheduled", "items": review_refs}
        state = dict(task.execution_state or {})
        state["evidence_refs"] = [
            *list(state.get("evidence_refs") or []), *valid_refs,
        ][-100:]
        completed_ids = list(dict.fromkeys([
            *list(state.get("completed_phase_ids") or []), phase_id,
        ]))
        state["completed_phase_ids"] = completed_ids
        task.execution_state = state
        _set_phase_status(task, phase_id, "completed")
        event_type = "learning_task_phase_completed"
    elif action == "complete_task" and task.status == "active":
        phases = list(_phase_map(task).values())
        if any(phase.get("required", True) and phase.get("status") != "completed" for phase in phases):
            raise RuntimeError("incomplete_plan")
        if any(phase.get("kind") == "verify" for phase in phases):
            if not await _verification_refs(db, task):
                raise RuntimeError("verification_required")
        task.status = "completed"
        task.completed_at = now
        event_type = "learning_task_completed"
    else:
        raise RuntimeError("invalid_state")
    _log_action(task, client_action_id, action, phase_id=phase_id)
    task.version += 1
    await _record_task_event(
        db, task, event_type, source="user",
        suffix=f"action:{client_action_id}",
        payload={"action": action, "phase_id": phase_id, "mastery_unchanged": True},
    )
    return task


async def replan_learning_task(
    db: AsyncSession,
    *,
    task: LearningTask,
    reason: str,
    learner_direction: str,
    preferred_skills: list[str],
    expected_version: int,
    client_request_id: str,
) -> LearningTask:
    if _already_logged(task, client_request_id):
        return task
    if task.version != expected_version:
        raise RuntimeError("version_conflict")
    if task.status in {"completed", "canceled"}:
        raise RuntimeError("invalid_state")
    previous = _phase_map(task)
    learner_context = _compact_planner_context(
        await get_kernel_projection(db, task.learner_id)
    )
    plan = await generate_learning_task_plan(
        title=task.title,
        objective=task.objective,
        origin_kind=task.origin_kind,
        estimated_minutes=task.estimated_minutes,
        preferred_skills=preferred_skills,
        learner_context=learner_context,
        reason=reason,
        learner_direction=learner_direction,
    )
    phases = []
    for phase in list(plan.get("phases") or []):
        row = dict(phase)
        old = previous.get(str(row.get("id")))
        if old and old.get("status") == "completed":
            row["status"] = "completed"
            row["completed_at"] = old.get("completed_at")
        phases.append(row)
    plan["phases"] = phases
    task.plan = plan
    task.plan_version += 1
    task.estimated_minutes = int(plan.get("estimated_minutes") or task.estimated_minutes)
    task.current_phase_id = next(
        (str(item.get("id")) for item in phases if item.get("status") != "completed"), "",
    )
    task.version += 1
    _log_action(task, client_request_id, "replan", reason=reason)
    await _append_revision(
        db, task, source="learning_design", reason=reason,
        evidence_refs=list((task.execution_state or {}).get("evidence_refs") or []),
    )
    await _record_task_event(
        db, task, "learning_task_replanned", source="learning_design",
        suffix=f"replan:{client_request_id}",
        payload={"plan_version": task.plan_version, "reason": _clean(reason, 500)},
    )
    return task


async def materialize_learning_task(
    db: AsyncSession,
    *,
    task: LearningTask,
    source_text: str,
    expected_version: int,
    client_request_id: str,
    education_stage: str = "",
    background: str = "",
) -> LearningTask:
    if _already_logged(task, client_request_id):
        return task
    if task.version != expected_version:
        raise RuntimeError("version_conflict")
    if task.micro_learning_run_id:
        return task
    if task.status not in {"queued", "active", "paused"}:
        raise RuntimeError("invalid_state")
    from app.services.micro_learning import create_micro_learning_run
    run = await create_micro_learning_run(
        db,
        learner_id=task.learner_id,
        goal=task.objective,
        source_text=source_text,
        client_request_id=client_request_id,
        education_stage=education_stage,
        background=background,
        source="learning_task",
        attach_learning_task=False,
    )
    was_active = task.status == "active"
    task.micro_learning_run_id = run.id
    task.project_id = run.project_id
    task.checkpoint_id = run.checkpoint_id
    task.session_id = run.session_id
    task.status = "active"
    task.started_at = task.started_at or _now()
    task.version += 1
    _log_action(task, client_request_id, "materialize", micro_learning_run_id=run.id)
    await _record_task_event(
        db, task, "learning_task_materialized", source="learning_task",
        suffix=f"materialized:{client_request_id}",
        payload={"micro_learning_run_id": run.id},
    )
    if not was_active:
        await _record_task_event(
            db, task, "learning_task_started", source="learning_task",
            suffix=f"started:materialized:{client_request_id}",
        )
    return task


async def reorder_learning_tasks(
    db: AsyncSession,
    *,
    learner_id: int,
    task_ids: list[int],
    client_request_id: str,
) -> list[LearningTask]:
    if len(set(task_ids)) != len(task_ids):
        raise RuntimeError("invalid_order")
    rows = list((await db.execute(select(LearningTask).where(
        LearningTask.learner_id == learner_id,
        LearningTask.id.in_(task_ids),
        LearningTask.status.in_(QUEUE_STATUSES),
    ))).scalars().all())
    if len(rows) != len(task_ids):
        raise RuntimeError("invalid_order")
    by_id = {item.id: item for item in rows}
    if all(_already_logged(item, client_request_id) for item in rows):
        return [by_id[task_id] for task_id in task_ids]
    for index, task_id in enumerate(task_ids, start=1):
        task = by_id[task_id]
        task.queue_position = index * 1000
        task.version += 1
        _log_action(task, client_request_id, "reorder", queue_position=task.queue_position)
    return [by_id[task_id] for task_id in task_ids]


async def create_recommended_learning_task(
    db: AsyncSession,
    *,
    session: AgentSession,
    opportunity: dict[str, Any],
    user_message_id: int,
    user_message: str,
) -> LearningTask | None:
    if not opportunity.get("should_propose"):
        return None
    title = _clean(opportunity.get("title"), 255)
    objective = _clean(opportunity.get("objective"), 2_000)
    if len(title) < 2 or len(objective) < 2:
        return None
    compact_message = "".join(str(user_message or "").lower().split())
    explicit_markers = (
        "加入学习任务", "加入任务", "放进学习任务", "带我学", "教我学",
        "帮我弄懂", "帮我搞懂", "我想学会", "我想弄懂", "开始学习",
        "带我完成", "完成这道题", "学习闭环",
    )
    explicitly_requested = (
        opportunity.get("consent_basis") == "explicit_user_request"
        and any(marker in compact_message for marker in explicit_markers)
    )
    existing_query = select(LearningTask).where(
        LearningTask.learner_id == session.learner_id,
        LearningTask.session_id == session.id,
        LearningTask.status.in_(ACTIVE_STATUSES),
    )
    if session.checkpoint_id:
        existing_query = existing_query.where(
            LearningTask.checkpoint_id == session.checkpoint_id,
        )
    existing = (await db.execute(existing_query.order_by(
        LearningTask.priority.desc(),
        LearningTask.queue_position,
        LearningTask.id,
    ).limit(1))).scalar_one_or_none()
    if existing:
        if not explicitly_requested:
            return existing if existing.status == "proposed" else None
        previous_status = existing.status
        if existing.status == "proposed":
            existing.accepted_at = existing.accepted_at or _now()
            await _record_task_event(
                db, existing, "learning_task_accepted", source="user",
                suffix=f"accepted:tutor-turn:{user_message_id}",
            )
        if existing.status != "active":
            existing.status = "active"
            existing.started_at = existing.started_at or _now()
            existing.current_phase_id = next(iter(_phase_map(existing)), "")
            await _record_task_event(
                db,
                existing,
                "learning_task_resumed" if previous_status == "paused" else "learning_task_started",
                source="user",
                suffix=f"activated:tutor-turn:{user_message_id}",
            )
            existing.version += 1
        return existing
    task, _ = await create_learning_task(
        db,
        learner_id=session.learner_id,
        session_id=session.id,
        project_id=session.project_id,
        checkpoint_id=session.checkpoint_id,
        title=title,
        objective=objective,
        client_request_id=f"tutor-learning-task:{session.id}:{user_message_id}",
        origin_kind="conversation" if explicitly_requested else "recommendation",
        created_by="user" if explicitly_requested else "tutor",
        status="active" if explicitly_requested else "proposed",
        priority=int(opportunity.get("priority") or 0),
        estimated_minutes=int(opportunity.get("estimated_minutes") or 20),
        preferred_skills=list(opportunity.get("suggested_skills") or []),
        success_criteria=list(opportunity.get("success_criteria") or []),
    )
    return task
