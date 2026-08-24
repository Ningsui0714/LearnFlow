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

from app.models.learning import AgentSession, LearningSkillRun, LearningTask, MicroLearningRun
from app.services.architecture_registry import selectable_learning_skill
from app.services.learning_runtime import record_event


SKILL_RUNTIME_VERSION = "atomic-learning-skill-runtime-v2"
RUNTIME_SKILL_IDS = (
    "guided_explanation",
    "socratic_dialogue",
    "feynman_dialogue",
    "worked_example_fading",
)
ACTIVE_RUN_STATUSES = ("active", "paused", "verification")

WORKFLOWS: dict[str, dict[str, Any]] = {
    "guided_explanation": {
        "turn_budget": 3,
        "total_steps": 4,
        "initial_state": "presenting_core_model",
        "states": (
            "presenting_core_model",
            "checking_minimal_example",
            "repairing_explanation",
            "verification_ready",
        ),
        "labels": {
            "presenting_core_model": "核心模型与最小例子",
            "checking_minimal_example": "检查例子中的关键关系",
            "repairing_explanation": "修补理解并迁移表达",
            "verification_ready": "准备独立验证",
            "verification_in_progress": "独立验证中",
            "completed": "本轮完成",
            "paused": "已暂停",
        },
    },
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
    "worked_example_fading": {
        "turn_budget": 3,
        "total_steps": 4,
        "initial_state": "studying_worked_example",
        "states": (
            "studying_worked_example",
            "completing_last_step",
            "solving_faded_example",
            "verification_ready",
        ),
        "labels": {
            "studying_worked_example": "拆解完整示例",
            "completing_last_step": "补全最后一步",
            "solving_faded_example": "撤去更多支架",
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
    if skill_id == "guided_explanation":
        prefixes = (
            r"^(?:请)?(?:直接)?(?:给我)?(?:解释|讲清楚|讲清|说明)[，,：:\s]*",
            r"^(?:请)?(?:用一个)?(?:最小)?例子(?:解释|说明)?[，,：:\s]*",
        )
    elif skill_id == "socratic_dialogue":
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
    elif skill_id == "worked_example_fading":
        prefixes = (
            r"^(?:请)?(?:先)?带我做一遍[，,：:\s]*",
            r"^(?:请)?先示范(?:一遍)?再让我做[，,：:\s]*",
            r"^(?:请)?(?:用)?示例渐隐(?:来)?(?:学习|讲解)?[，,：:\s]*",
            r"^(?:请)?给我一个完整(?:例题|示例|样例代码)[，,：:\s]*",
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
            "worked_example_fading",
            ("带我做一遍", "先示范再", "示例渐隐", "渐隐示例", "完整例题", "完整示例", "样例代码再让我", "照着例子"),
            "这个目标包含可分步练习的程序或解题过程，适合先看子目标清楚的示例，再逐步撤掉提示。",
        ),
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
            "policy_version": "learning-skill-recommendation-v2",
        }
    return None


def _opening_prompt(skill_id: str, goal: str) -> tuple[str, str]:
    if skill_id == "guided_explanation":
        fallback = (
            f"先建立“{goal}”的最小模型：它解决什么问题、核心关系是什么、什么时候不适用。"
            "我会配一个最小例子；看完后请你只指出例子里哪个变化触发了结果。"
        )
        directive = (
            f"SkillRun 刚开始，目标是“{goal}”。直接给出一个分层但精炼的核心解释和一个最小例子；"
            "明确一个边界，最后只留一个检查例子关键关系的问题。不要宣布掌握。"
        )
        return directive, fallback
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
    if skill_id == "feynman_dialogue":
        fallback = (
            f"先不看资料，把“{goal}”讲给一个完全不了解它的人听。"
            "请用 3—5 句话说明它是什么、为什么成立或怎样运作。"
        )
        directive = (
            f"SkillRun 刚开始，目标是“{goal}”。邀请学习者进行第一次自己的话复述；"
            "不要先讲答案，不要宣布掌握。"
        )
        return directive, fallback
    fallback = (
        f"我们先把“{goal}”拆成几个有名称的子目标，看一遍完整示例；"
        "接着我会先拿掉最后一步，让你补全，再逐步撤掉更多提示。"
    )
    directive = (
        f"SkillRun 刚开始，目标是“{goal}”。给出一个尽可能小的完整示例，按 2—4 个功能子目标标注步骤；"
        "解释每个子目标为何存在，最后只问学习者哪一步把输入转成了目标输出。"
        "不要把照做或阅读示例当成掌握。"
    )
    return directive, fallback


def _next_step(skill_id: str, current_state: str, goal: str) -> dict[str, Any]:
    if skill_id == "guided_explanation":
        rows = {
            "presenting_core_model": {
                "state": "checking_minimal_example",
                "step_index": 2,
                "directive": (
                    f"学习者刚回应了“{goal}”的核心解释。只修正一个最关键的偏差或确认一个准确关系，"
                    "随后给一个表面不同但结构相同的最小例子，只问一个预测结果的问题。"
                ),
                "fallback": "换一个表面不同的小例子：如果只改变其中一个关键条件，你预测结果会怎样？为什么？",
            },
            "checking_minimal_example": {
                "state": "repairing_explanation",
                "step_index": 3,
                "directive": (
                    "根据学习者对新例子的判断，用两三句话修补核心模型；然后只要求他不用原句，"
                    "用“条件—机制—结果”重新解释一次。"
                ),
                "fallback": "现在不用刚才的原句，请用“条件—机制—结果”三部分把这个概念重新说一遍。",
            },
            "repairing_explanation": {
                "state": "verification_ready",
                "step_index": 4,
                "directive": (
                    "指出学习者重述中一项可检查的进展，并明确讲解和重述仍不是掌握证据；"
                    "邀请进入一道无提示的独立验证，不再追加讲解问题。"
                ),
                "fallback": "核心关系已经可以独立表述。下一步用一道不复用当前例子的题做无提示验证。",
            },
        }
    elif skill_id == "socratic_dialogue":
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
    elif skill_id == "feynman_dialogue":
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
    else:
        rows = {
            "studying_worked_example": {
                "state": "completing_last_step",
                "step_index": 2,
                "directive": (
                    f"学习者已看过“{goal}”的完整示例。换一个近似情境，保留前面子目标，"
                    "只隐藏最后一个解题或代码步骤，让学习者补全并说明该步满足哪个子目标。"
                    "不要同时挖掉多个步骤。"
                ),
                "fallback": "现在换一个近似输入，我保留前面的步骤；请只补全最后一步，并说明它完成了哪个子目标。",
            },
            "completing_last_step": {
                "state": "solving_faded_example",
                "step_index": 3,
                "directive": (
                    "先对刚补的步骤给出具体反馈。再提供一个同结构的新情境，只保留子目标标签和起始条件，"
                    "让学习者完成其余关键步骤；每次只要求一个可检查产物。"
                ),
                "fallback": "再来一个同结构的新情境：这次只保留子目标标签和起始条件，请写出其余关键步骤。",
            },
            "solving_faded_example": {
                "state": "verification_ready",
                "step_index": 4,
                "directive": (
                    "总结学习者在撤去支架后实际完成的步骤，并明确这仍属于训练；"
                    "邀请进入一个不显示子目标标签和示例的独立变式验证。"
                ),
                "fallback": "支架已经撤到只剩目标。下一步请进入无示例、无子目标提示的独立变式验证。",
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


async def _linked_learning_task(
    db: AsyncSession, run: LearningSkillRun,
) -> LearningTask | None:
    if not run.learning_task_id:
        return None
    return (await db.execute(select(LearningTask).where(
        LearningTask.id == run.learning_task_id,
        LearningTask.learner_id == run.learner_id,
    ))).scalar_one_or_none()


async def _advance_linked_task(
    db: AsyncSession,
    run: LearningSkillRun,
    *,
    action: str,
    operation_id: str,
) -> LearningTask | None:
    task = await _linked_learning_task(db, run)
    if not task:
        return None
    from app.services.learning_tasks import advance_learning_task_from_skill

    return await advance_learning_task_from_skill(
        db,
        task=task,
        skill_run_id=run.id,
        action=action,
        operation_id=operation_id,
    )


async def _ensure_atomic_learning_task(
    db: AsyncSession,
    *,
    session: AgentSession,
    run: LearningSkillRun,
    source: str,
) -> LearningTask:
    """Attach one learner-visible atomic task to the SkillRun."""
    linked = await _linked_learning_task(db, run)
    if linked:
        return linked
    existing = (await db.execute(select(LearningTask).where(
        LearningTask.learner_id == run.learner_id,
        LearningTask.session_id == session.id,
        LearningTask.objective == run.goal,
        LearningTask.status.in_({"queued", "active", "paused"}),
    ).order_by(LearningTask.id.desc()).limit(1))).scalar_one_or_none()
    if existing:
        run.learning_task_id = existing.id
        task = existing
    else:
        from app.services.learning_tasks import create_learning_task

        skill = selectable_learning_skill(run.skill_id)
        task, _ = await create_learning_task(
            db,
            learner_id=run.learner_id,
            session_id=session.id,
            title=f"{skill.name if skill else '学习方法'}：{run.goal}"[:255],
            objective=run.goal,
            client_request_id=f"skill-task:{run.id}",
            origin_kind="skill",
            created_by=source,
            status="active",
            estimated_minutes=20,
            preferred_skills=[run.skill_id],
            success_criteria=[
                "完成本方法的有界引导",
                "完成至少一次无提示独立验证",
                "把合格评估转交复习队列",
            ],
            source_refs=[{"type": "learning_skill_run", "id": run.id}],
        )
        run.learning_task_id = task.id
    if task.status == "queued":
        await _advance_linked_task(
            db, run, action="start", operation_id=f"attach-{run.id}",
        )
    elif task.status == "paused":
        await _advance_linked_task(
            db, run, action="resume", operation_id=f"attach-{run.id}",
        )
    run.run_data = {
        **dict(run.run_data or {}),
        "learning_task_id": task.id,
        "task_contract": "learn -> practice -> verify -> consolidate",
    }
    return task


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
            "learning_task_id": run.learning_task_id,
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
        if not existing.learning_task_id:
            await _ensure_atomic_learning_task(
                db, session=session, run=existing, source=source,
            )
        return existing, False

    current = await active_skill_run(db, session)
    if current and current.skill_id == skill_id and current.goal == normalized_goal:
        if not current.learning_task_id:
            await _ensure_atomic_learning_task(
                db, session=session, run=current, source=source,
            )
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
        await _advance_linked_task(
            db,
            current,
            action="pause",
            operation_id=f"skill-switched-{current.version}",
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
    await _ensure_atomic_learning_task(
        db, session=session, run=run, source=source,
    )
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
    await _advance_linked_task(
        db,
        current,
        action="pause",
        operation_id=f"selection-paused-{current.version}",
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
        await _advance_linked_task(
            db,
            current,
            action="resume",
            operation_id=f"auto-resumed-{current.version}",
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
        if current.state == "verification_ready":
            await _advance_linked_task(
                db,
                current,
                action="complete_learn",
                operation_id="verification-ready",
            )
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
    if current.state == "verification_ready":
        await _advance_linked_task(
            db,
            current,
            action="complete_learn",
            operation_id=f"turn-{current.turn_count}",
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
    task = await _linked_learning_task(db, run)
    if task:
        from app.services.learning_tasks import reconcile_learning_task

        await reconcile_learning_task(db, task)
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
    task = await _linked_learning_task(db, run)
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
        "learning_task": ({
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "current_phase_id": task.current_phase_id,
            "plan_version": task.plan_version,
            "version": task.version,
            "path": f"/tasks?task={task.id}",
        } if task else None),
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
        session = await db.get(AgentSession, run.session_id)
        if not session or session.learner_id != run.learner_id:
            raise RuntimeError("unsupported_scope")
        task = await _ensure_atomic_learning_task(
            db, session=session, run=run, source="user",
        )
        if task.status == "paused":
            await _advance_linked_task(
                db, run, action="resume", operation_id=f"verify-{client_action_id}",
            )
        await _advance_linked_task(
            db, run, action="complete_learn", operation_id="verification-handoff",
        )
        from app.services.learning_tasks import materialize_learning_task

        task = await materialize_learning_task(
            db,
            task=task,
            source_text="",
            expected_version=task.version,
            client_request_id=f"skill-run-{run.id}-{client_action_id}",
            education_stage=education_stage,
            background=background,
        )
        micro = await db.get(MicroLearningRun, task.micro_learning_run_id)
        if not micro:
            raise RuntimeError("invalid_state")
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
    if action == "pause":
        await _advance_linked_task(
            db, run, action="pause", operation_id=client_action_id,
        )
    elif action == "resume":
        await _advance_linked_task(
            db, run, action="resume", operation_id=client_action_id,
        )
    return run, micro
