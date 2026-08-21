"""Deterministic session runtime for conversational learning Skills.

The runtime owns workflow position, turn budgets, pause/resume and the handoff
to the existing verified micro-learning loop.  It deliberately does not grade
answers or create mastery claims.  Model output may render the next prompt,
but state transitions are selected here.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import AgentSession, LearningSkillRun, MicroLearningRun
from app.services.architecture_registry import selectable_learning_skill
from app.services.learning_runtime import record_event


SKILL_RUNTIME_VERSION = "conversation-skill-runtime-v1"
RUNTIME_SKILL_IDS = ("socratic_dialogue", "feynman_dialogue")
ACTIVE_RUN_STATUSES = ("active", "paused", "verification")

WORKFLOWS: dict[str, dict[str, Any]] = {
    "socratic_dialogue": {
        "turn_budget": 3,
        "total_steps": 4,
        "initial_state": "eliciting_prior_model",
        "states": (
            "eliciting_prior_model",
            "testing_assumption",
            "building_explanation",
            "verification_ready",
        ),
        "labels": {
            "eliciting_prior_model": "说出当前直觉",
            "testing_assumption": "检验关键条件",
            "building_explanation": "连成完整推理",
            "verification_ready": "准备独立验证",
            "verification_in_progress": "独立验证中",
            "completed": "本轮完成",
            "paused": "已暂停",
        },
    },
    "feynman_dialogue": {
        "turn_budget": 3,
        "total_steps": 4,
        "initial_state": "awaiting_teach_back",
        "states": (
            "awaiting_teach_back",
            "locating_gap",
            "revising_explanation",
            "verification_ready",
        ),
        "labels": {
            "awaiting_teach_back": "第一次自己的话复述",
            "locating_gap": "定位一个模糊处",
            "revising_explanation": "用例子重新讲清",
            "verification_ready": "准备独立验证",
            "verification_in_progress": "独立验证中",
            "completed": "本轮完成",
            "paused": "已暂停",
        },
    },
}


def _compact_goal(value: str) -> str:
    goal = re.sub(r"\s+", " ", str(value or "")).strip()
    return goal[:300]


def _learning_goal(value: str, skill_id: str) -> str:
    """Remove method-selection language while preserving the topic request."""
    original = _compact_goal(value)
    goal = original
    if skill_id == "socratic_dialogue":
        prefixes = (
            r"^(?:请)?不要直接告诉我(?:答案)?[，,：:\s]*",
            r"^(?:请)?(?:用问题)?引导我[，,：:\s]*",
            r"^(?:我想)?自己推导[，,：:\s]*",
            r"^(?:请)?帮我(?:想清|理解)?[，,：:\s]*",
        )
    elif skill_id == "feynman_dialogue":
        prefixes = (
            r"^我想用自己的话(?:复述|讲清楚|讲清|讲)?[，,：:\s]*",
            r"^让我把?[，,：:\s]*",
            r"^我来用自己的话讲[，,：:\s]*",
            r"^检验我到底懂不懂[，,：:\s]*",
            r"^通过复述帮我查漏[，,：:\s]*",
            r"^我先回忆[，,：:\s]*",
            r"^我讲给一个新手听[，,：:\s]*",
            r"^想确认我到底懂不懂[，,：:\s]*",
        )
    else:
        prefixes = ()
    for pattern in prefixes:
        goal = re.sub(pattern, "", goal, count=1).strip()
    if skill_id == "feynman_dialogue":
        for pattern in (
            r"讲给别人听$", r"[，,]?再请你检查$", r"[，,]?你帮我找漏洞$", r"[，,]?让我先复述$",
        ):
            goal = re.sub(pattern, "", goal, count=1).strip()
    return goal[:300] if len(goal) >= 2 else original


def workflow_blueprint(skill_id: str) -> dict[str, Any] | None:
    workflow = WORKFLOWS.get(skill_id)
    if not workflow:
        return None
    return {
        "skill_id": skill_id,
        "version": SKILL_RUNTIME_VERSION,
        "turn_budget": int(workflow["turn_budget"]),
        "total_steps": int(workflow["total_steps"]),
        "states": list(workflow["states"]),
        "verification_required": True,
        "evidence_policy": "conversation_is_coaching; mastery_requires_existing_graded_attempts",
    }


def recommend_learning_skill(message: str) -> dict[str, Any] | None:
    """Recommend, but never activate, a registered learner-selectable Skill."""
    normalized = "".join(str(message or "").casefold().split())
    if len(normalized) < 4:
        return None
    # Explicit learning-process requests take precedence over topic words.
    # In particular, "不要直接告诉我" is Socratic while "直接告诉我为什么"
    # asks for an explanation even though it contains "为什么".
    rules = (
        (
            "feynman_dialogue",
            ("复述", "讲给别人", "讲给一个", "查漏", "检验我", "我到底懂", "回忆", "用自己的话"),
            "这个目标更适合先用自己的话讲一遍，再定位模糊处。",
        ),
        (
            "socratic_dialogue",
            ("不要直接告诉", "自己推导", "怎么想", "思路", "引导我", "用问题引导", "证明"),
            "这个问题适合保留你的思考过程，用连续小问题逐步推到结论。",
        ),
        (
            "guided_explanation",
            ("是什么", "解释", "讲清", "举例", "直接告诉", "没听懂", "看不懂"),
            "你现在更需要一个短而清楚的解释和最小例子。",
        ),
        (
            "socratic_dialogue",
            ("为什么", "推导", "自己想"),
            "这个问题适合保留你的思考过程，用连续小问题逐步推到结论。",
        ),
    )
    for skill_id, markers, reason in rules:
        matched = [marker for marker in markers if marker in normalized]
        if not matched:
            continue
        skill = selectable_learning_skill(skill_id)
        if not skill:
            continue
        return {
            "skill": {"id": skill.id, "name": skill.name, "description": skill.description},
            "goal": _learning_goal(message, skill_id),
            "reason": reason,
            "matched_signals": matched[:3],
            "requires_confirmation": True,
            "policy_version": "learning-skill-recommendation-v1",
        }
    return None


def _opening_prompt(skill_id: str, goal: str) -> tuple[str, str]:
    if skill_id == "socratic_dialogue":
        fallback = (
            f"我们先不急着听完整答案。针对“{goal}”，你目前觉得最关键的关系或判断是什么？"
            "先说直觉即可，我每次只追问一个问题。"
        )
        directive = (
            f"SkillRun 刚开始，目标是“{goal}”。只问一个用于暴露学习者当前直觉的问题；"
            "不要解释答案，不要连续列问题。"
        )
        return directive, fallback
    fallback = (
        f"先不看资料，把“{goal}”讲给一个完全不了解它的人听。"
        "请用 3—5 句话说明它是什么、为什么成立或怎样运作。"
    )
    directive = (
        f"SkillRun 刚开始，目标是“{goal}”。邀请学习者进行第一次自己的话复述；"
        "不要先讲答案，不要宣布掌握。"
    )
    return directive, fallback


def _next_step(skill_id: str, current_state: str, goal: str) -> dict[str, Any]:
    if skill_id == "socratic_dialogue":
        rows = {
            "eliciting_prior_model": {
                "state": "testing_assumption",
                "step_index": 2,
                "directive": (
                    f"学习者刚说出了对“{goal}”的当前直觉。先简短复述其中一个有效点，"
                    "再只问一个能检验关键条件、反例或因果方向的问题。不要给完整答案。"
                ),
                "fallback": (
                    "先抓住你刚才的判断：如果把其中一个关键条件反过来或拿掉，结论还成立吗？"
                    "请选择最关键的那个条件，并说说为什么。"
                ),
            },
            "testing_assumption": {
                "state": "building_explanation",
                "step_index": 3,
                "directive": (
                    "学习者已经检验了一个条件。指出其推理中最有价值的一步，然后只问一个问题，"
                    "让他用“因为—所以—只有当”把条件与结论连起来。"
                ),
                "fallback": "现在把前两步连起来：请用“因为……所以……；只有当……时……”重新说一遍。",
            },
            "building_explanation": {
                "state": "verification_ready",
                "step_index": 4,
                "directive": (
                    "学习者已形成一版推理。用一句话肯定具体进展，同时明确普通对话不是掌握证明；"
                    "邀请他点击独立验证，不要再新增教学问题。"
                ),
                "fallback": (
                    "你的推理框架已经连起来了。下一步需要一道不照搬当前表述的独立题，"
                    "确认你能否把这个关系迁移到新情境。"
                ),
            },
        }
    else:
        rows = {
            "awaiting_teach_back": {
                "state": "locating_gap",
                "step_index": 2,
                "directive": (
                    f"学习者刚完成对“{goal}”的第一次复述。先指出一个讲清楚的具体点，"
                    "再只定位一个最关键的含糊词、跳步或条件，并问它如何连接前后因果。"
                    "不要把复述当作掌握证据。"
                ),
                "fallback": (
                    "你已经给出了一版自己的解释。现在只挑其中最容易含糊的一个词："
                    "它具体指什么，又怎样连接前因和结果？"
                ),
            },
            "locating_gap": {
                "state": "revising_explanation",
                "step_index": 3,
                "directive": (
                    "学习者补充了一个模糊处。先指出补充后更清楚的连接，再只要求一次修订："
                    "不用术语重讲，并加入一个例子和一个边界或反例。"
                ),
                "fallback": "现在不用专业术语再讲一次，并补一个具体例子，以及一个不适用的边界或反例。",
            },
            "revising_explanation": {
                "state": "verification_ready",
                "step_index": 4,
                "directive": (
                    "学习者已完成修订复述。总结一项真实进展，并明确复述只是诊断；"
                    "邀请点击独立验证，不要宣称已经学会。"
                ),
                "fallback": (
                    "这次复述已经比第一版更可检查了，但复述仍只是诊断。"
                    "下一步用一道独立变式题验证，才能留下能力证据。"
                ),
            },
        }
    return rows.get(current_state, {
        "state": "verification_ready",
        "step_index": 4,
        "directive": "当前 SkillRun 已达到追问预算。停止追加讲解，邀请学习者进入独立验证。",
        "fallback": "这段引导已经达到本轮预算。请进入独立验证，确认能否在新情境中使用它。",
    })


async def active_skill_run(
    db: AsyncSession, session: AgentSession,
) -> LearningSkillRun | None:
    return (await db.execute(
        select(LearningSkillRun).where(
            LearningSkillRun.learner_id == session.learner_id,
            LearningSkillRun.session_id == session.id,
            LearningSkillRun.status.in_(ACTIVE_RUN_STATUSES),
        ).order_by(LearningSkillRun.updated_at.desc(), LearningSkillRun.id.desc()).limit(1)
    )).scalar_one_or_none()


async def latest_skill_run(
    db: AsyncSession, session: AgentSession,
) -> LearningSkillRun | None:
    return (await db.execute(
        select(LearningSkillRun).where(
            LearningSkillRun.learner_id == session.learner_id,
            LearningSkillRun.session_id == session.id,
            LearningSkillRun.status != "canceled",
        ).order_by(LearningSkillRun.updated_at.desc(), LearningSkillRun.id.desc()).limit(1)
    )).scalar_one_or_none()


async def _record_run_event(
    db: AsyncSession,
    run: LearningSkillRun,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    client_event_id: str,
    source: str = "skill_runtime",
) -> None:
    await record_event(
        db,
        learner_id=run.learner_id,
        session_id=run.session_id,
        event_type=event_type,
        source=source,
        payload={
            "skill_run_id": run.id,
            "skill_id": run.skill_id,
            "goal": run.goal,
            "state": run.state,
            "runtime_version": run.skill_version,
            **dict(payload or {}),
        },
        provenance={
            "skill_run_id": run.id,
            "runtime_version": run.skill_version,
            "decision_owner": "deterministic_skill_runtime",
        },
        client_event_id=client_event_id,
    )


async def create_learning_skill_run(
    db: AsyncSession,
    *,
    session: AgentSession,
    skill_id: str,
    goal: str,
    client_request_id: str,
    source: str = "user",
) -> tuple[LearningSkillRun, bool]:
    if session.session_type != "global":
        raise RuntimeError("unsupported_scope")
    if skill_id not in RUNTIME_SKILL_IDS or not selectable_learning_skill(skill_id):
        raise RuntimeError("unsupported_skill")
    normalized_goal = _learning_goal(goal, skill_id)
    if len(normalized_goal) < 2:
        raise RuntimeError("missing_goal")
    request_key = f"skill-run:{session.id}:{client_request_id}"
    existing = (await db.execute(select(LearningSkillRun).where(
        LearningSkillRun.learner_id == session.learner_id,
        LearningSkillRun.client_request_id == request_key,
    ))).scalar_one_or_none()
    if existing:
        return existing, False

    current = await active_skill_run(db, session)
    if current and current.skill_id == skill_id and current.goal == normalized_goal:
        return current, False
    if current:
        previous_state = current.state
        current.status = "paused"
        current.state = "paused"
        current.run_data = {
            **dict(current.run_data or {}),
            "resume_state": previous_state,
            "paused_reason": "skill_switched",
        }
        current.version += 1
        current.updated_at = datetime.utcnow()
        await _record_run_event(
            db, current, "learning_skill_run_paused",
            payload={"resume_state": previous_state, "reason": "skill_switched"},
            client_event_id=f"learning-skill-run:{current.id}:switched:{current.version}",
        )

    workflow = WORKFLOWS[skill_id]
    directive, fallback = _opening_prompt(skill_id, normalized_goal)
    run = LearningSkillRun(
        learner_id=session.learner_id,
        session_id=session.id,
        skill_id=skill_id,
        skill_version=SKILL_RUNTIME_VERSION,
        goal=normalized_goal,
        status="active",
        state=str(workflow["initial_state"]),
        step_index=1,
        turn_count=0,
        turn_budget=int(workflow["turn_budget"]),
        run_data={
            "responses": [],
            "next_directive": directive,
            "next_prompt": fallback,
            "verification_required": True,
            "mastery_claim": "none",
        },
        action_log=[],
        client_request_id=request_key,
        version=1,
    )
    db.add(run)
    await db.flush()
    await _record_run_event(
        db, run, "learning_skill_run_started",
        payload={"source": source, "turn_budget": run.turn_budget},
        client_event_id=f"learning-skill-run:{run.id}:started",
        source=source,
    )
    return run, True


async def pause_active_skill_run_for_selection(
    db: AsyncSession,
    *,
    session: AgentSession,
    selected_skill_id: str | None,
) -> LearningSkillRun | None:
    current = await active_skill_run(db, session)
    if not current or selected_skill_id == current.skill_id:
        return current
    previous_state = current.state
    current.status = "paused"
    current.state = "paused"
    current.run_data = {
        **dict(current.run_data or {}),
        "resume_state": previous_state,
        "paused_reason": "skill_selection_changed",
    }
    current.version += 1
    current.updated_at = datetime.utcnow()
    await _record_run_event(
        db, current, "learning_skill_run_paused",
        payload={"resume_state": previous_state, "reason": "skill_selection_changed"},
        client_event_id=f"learning-skill-run:{current.id}:selection-paused:{current.version}",
    )
    return current


async def prepare_learning_skill_turn(
    db: AsyncSession,
    *,
    session: AgentSession,
    skill_id: str,
    message: str,
    message_id: int,
    client_turn_id: str | None,
) -> tuple[LearningSkillRun, dict[str, Any]]:
    current = await active_skill_run(db, session)
    if not current or current.skill_id != skill_id:
        run, _ = await create_learning_skill_run(
            db,
            session=session,
            skill_id=skill_id,
            goal=message,
            client_request_id=client_turn_id or f"message-{message_id}",
            source="user",
        )
        data = dict(run.run_data or {})
        return run, {
            "started": True,
            "directive": data.get("next_directive", ""),
            "fallback": data.get("next_prompt", ""),
        }

    if current.status == "verification":
        return current, {
            "started": False,
            "directive": "独立验证已经创建。回答当前问题前，提醒学习者打开或继续验证附件。",
            "fallback": "独立验证已经准备好。请打开下方验证卡继续；完成后这里会自动记录本轮结果。",
        }

    if current.status == "paused":
        resume_state = str((current.run_data or {}).get("resume_state") or WORKFLOWS[skill_id]["initial_state"])
        current.status = "active"
        current.state = resume_state
        current.version += 1
        current.updated_at = datetime.utcnow()
        await _record_run_event(
            db, current, "learning_skill_run_resumed",
            payload={"resume_state": resume_state, "reason": "learner_returned"},
            client_event_id=f"learning-skill-run:{current.id}:auto-resumed:{current.version}",
        )

    turn_key = f"turn:{session.id}:{client_turn_id or message_id}"
    history = list(current.action_log or [])
    if turn_key in history:
        data = dict(current.run_data or {})
        return current, {
            "started": False,
            "directive": data.get("next_directive", ""),
            "fallback": data.get("next_prompt", ""),
        }
    if current.state in {"verification_ready", "verification_in_progress", "completed"}:
        data = dict(current.run_data or {})
        return current, {
            "started": False,
            "directive": data.get("next_directive", "停止追加教学问题，邀请学习者进入独立验证。"),
            "fallback": data.get("next_prompt", "请开始独立验证，完成后再继续讨论。"),
        }

    previous_state = current.state
    next_step = _next_step(current.skill_id, previous_state, current.goal)
    data = dict(current.run_data or {})
    responses = list(data.get("responses") or [])
    responses.append({
        "message_id": message_id,
        "text": str(message or "")[:4000],
        "state": previous_state,
        "recorded_at": datetime.utcnow().isoformat(),
    })
    current.turn_count += 1
    if current.turn_count >= current.turn_budget and next_step["state"] != "verification_ready":
        next_step = _next_step(current.skill_id, "budget_exhausted", current.goal)
    current.state = str(next_step["state"])
    current.step_index = int(next_step["step_index"])
    current.run_data = {
        **data,
        "responses": responses[-12:],
        "next_directive": next_step["directive"],
        "next_prompt": next_step["fallback"],
        "mastery_claim": "none",
    }
    current.action_log = [*history, turn_key][-80:]
    current.version += 1
    current.updated_at = datetime.utcnow()
    await _record_run_event(
        db, current, "learning_skill_run_advanced",
        payload={
            "from_state": previous_state,
            "to_state": current.state,
            "turn_count": current.turn_count,
            "message_id": message_id,
            "mastery_unchanged": True,
        },
        client_event_id=f"learning-skill-run:{current.id}:{turn_key}:advanced",
        source="user",
    )
    return current, {
        "started": False,
        "directive": next_step["directive"],
        "fallback": next_step["fallback"],
    }


async def reconcile_learning_skill_run(
    db: AsyncSession, run: LearningSkillRun,
) -> bool:
    if not run.micro_learning_run_id or run.status == "completed":
        return False
    micro = await db.get(MicroLearningRun, run.micro_learning_run_id)
    if not micro or micro.learner_id != run.learner_id or micro.status != "completed":
        return False
    run.status = "completed"
    run.state = "completed"
    run.step_index = int(WORKFLOWS[run.skill_id]["total_steps"])
    run.completed_at = run.completed_at or datetime.utcnow()
    run.run_data = {
        **dict(run.run_data or {}),
        "verified_summary": dict(micro.summary or {}),
        "mastery_claim": "not_stable_yet",
        "next_prompt": "本轮已有独立验证记录；稳定掌握仍需要后续跨时间复习。",
    }
    run.version += 1
    run.updated_at = datetime.utcnow()
    await _record_run_event(
        db, run, "learning_skill_run_completed",
        payload={
            "micro_learning_run_id": micro.id,
            "mastery_claim": "not_stable_yet",
            "review_schedule_ids": list((micro.summary or {}).get("review_schedule_ids") or []),
        },
        client_event_id=f"learning-skill-run:{run.id}:completed",
        source="runtime",
    )
    return True


async def learning_skill_run_view(
    db: AsyncSession, run: LearningSkillRun | None,
) -> dict[str, Any] | None:
    if not run:
        return None
    await reconcile_learning_skill_run(db, run)
    skill = selectable_learning_skill(run.skill_id)
    workflow = WORKFLOWS.get(run.skill_id, {})
    data = dict(run.run_data or {})
    micro = await db.get(MicroLearningRun, run.micro_learning_run_id) if run.micro_learning_run_id else None
    total_steps = int(workflow.get("total_steps") or 4)
    return {
        "id": run.id,
        "skill": {
            "id": run.skill_id,
            "name": skill.name if skill else run.skill_id,
            "description": skill.description if skill else "",
        },
        "runtime_version": run.skill_version,
        "goal": run.goal,
        "status": run.status,
        "state": run.state,
        "stage_label": dict(workflow.get("labels") or {}).get(run.state, run.state),
        "step_index": run.step_index,
        "total_steps": total_steps,
        "turn_count": run.turn_count,
        "turn_budget": run.turn_budget,
        "version": run.version,
        "next_prompt": str(data.get("next_prompt") or ""),
        "can_start_verification": run.state == "verification_ready" and not run.micro_learning_run_id,
        "can_pause": run.status in {"active", "verification"},
        "can_resume": run.status == "paused",
        "verification_required": True,
        "evidence_note": (
            "本轮已有独立验证；稳定掌握仍需跨时间复习。"
            if run.status == "completed"
            else "对话只用于引导；只有独立题、纠错和复习会形成能力证据。"
        ),
        "micro_learning_run": ({
            "id": micro.id,
            "goal": micro.goal,
            "status": micro.status,
            "state": micro.state,
            "version": micro.version,
            "summary": dict(micro.summary or {}),
        } if micro else None),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


async def latest_learning_skill_run_view(
    db: AsyncSession, session: AgentSession,
) -> dict[str, Any] | None:
    return await learning_skill_run_view(db, await latest_skill_run(db, session))


async def act_on_learning_skill_run(
    db: AsyncSession,
    *,
    run: LearningSkillRun,
    action: str,
    expected_version: int,
    client_action_id: str,
    education_stage: str = "",
    background: str = "",
) -> tuple[LearningSkillRun, MicroLearningRun | None]:
    history = list(run.action_log or [])
    action_key = f"action:{client_action_id}"
    if action_key in history:
        micro = await db.get(MicroLearningRun, run.micro_learning_run_id) if run.micro_learning_run_id else None
        return run, micro
    if run.version != expected_version:
        raise RuntimeError("version_conflict")
    micro: MicroLearningRun | None = None
    if action == "pause" and run.status in {"active", "verification"}:
        resume_state = run.state
        run.status = "paused"
        run.state = "paused"
        run.run_data = {**dict(run.run_data or {}), "resume_state": resume_state, "paused_reason": "learner"}
        event_type = "learning_skill_run_paused"
        event_payload = {"resume_state": resume_state, "reason": "learner"}
    elif action == "resume" and run.status == "paused":
        resume_state = str((run.run_data or {}).get("resume_state") or WORKFLOWS[run.skill_id]["initial_state"])
        run.status = "verification" if run.micro_learning_run_id else "active"
        run.state = "verification_in_progress" if run.micro_learning_run_id else resume_state
        event_type = "learning_skill_run_resumed"
        event_payload = {"resume_state": run.state, "reason": "learner"}
    elif action == "start_verification" and run.status == "active" and run.state == "verification_ready":
        from app.services.micro_learning import create_micro_learning_run

        micro = await create_micro_learning_run(
            db,
            learner_id=run.learner_id,
            goal=run.goal,
            source_text="",
            client_request_id=f"skill-run-{run.id}-{client_action_id}",
            education_stage=education_stage,
            background=background,
            source="skill_runtime",
        )
        run.micro_learning_run_id = micro.id
        run.status = "verification"
        run.state = "verification_in_progress"
        run.run_data = {
            **dict(run.run_data or {}),
            "next_prompt": "独立验证已经创建。完成复述、题目与必要纠错后，本轮才会结束。",
        }
        event_type = "learning_skill_verification_started"
        event_payload = {"micro_learning_run_id": micro.id}
    else:
        raise RuntimeError("invalid_state")
    run.action_log = [*history, action_key][-80:]
    run.version += 1
    run.updated_at = datetime.utcnow()
    await _record_run_event(
        db, run, event_type,
        payload=event_payload,
        client_event_id=f"learning-skill-run:{run.id}:{action_key}",
        source="user",
    )
    return run, micro
