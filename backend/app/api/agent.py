from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import (
    AgentSession, AgentMessage, AgentAction, LearningProjectProposal, LearningSkillRun,
)
from app.models.project import Project, Roadmap, Checkpoint, Task
from app.schemas.agent import (
    AgentSessionCreate, TutorTurnRequest, LearningEventRequest,
    ProjectProposalUpdateRequest, ProjectProposalAcceptRequest,
    LearningSkillRunCreateRequest, LearningSkillRunActionRequest,
)
from app.services.learning_runtime import (
    PUBLIC_EVENT_TYPES, record_event, get_state_summary, evaluate_checkpoint_status,
)
from app.services.tutor_service import (
    get_or_create_session, get_messages, process_turn, execute_action,
    action_card, action_result, finalize_action_for_task,
    proposal_acceptance_action, finalize_proposal_acceptance,
    get_session_state_summary, session_learning_skill,
    _select_session_learning_skill, _is_confirmation,
)
from app.services.architecture_registry import (
    chat_mode_manifest,
    selectable_learning_skill_manifest,
)
from app.services.chat_modes import chat_mode_view, enter_chat_mode
from app.services.learning_skill_runtime import (
    act_on_learning_skill_run,
    create_learning_skill_run,
    latest_learning_skill_run_view,
    learning_skill_run_view,
)
from app.services.project_proposals import (
    list_session_proposals, proposal_view, set_proposal_status,
    start_resource_search, update_project_proposal,
)
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_project,
    require_owned_checkpoint, valid_desktop_request,
)


router = APIRouter(prefix="/agent", tags=["Tutor"])
events_router = APIRouter(tags=["Learning Evidence"])


def _message_out(message: AgentMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "meta_data": message.meta_data or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def _owned_session(
    db: AsyncSession, learner_id: int, session_id: int,
) -> AgentSession:
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Tutor session not found")
    return session


async def _owned_proposal(
    db: AsyncSession, learner_id: int, proposal_id: int,
) -> LearningProjectProposal:
    proposal = (await db.execute(select(LearningProjectProposal).where(
        LearningProjectProposal.id == proposal_id,
        LearningProjectProposal.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not proposal:
        raise HTTPException(404, "Project proposal not found")
    return proposal


async def _owned_action(
    db: AsyncSession, learner_id: int, action_id: int,
) -> AgentAction:
    action = (await db.execute(select(AgentAction).where(
        AgentAction.id == action_id,
        AgentAction.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not action:
        raise HTTPException(404, "Action not found")
    return action


async def _session_payload(db: AsyncSession, session: AgentSession) -> dict:
    messages = await get_messages(db, session.id)
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    proposals = await list_session_proposals(db, session.id)
    skill_run = await latest_learning_skill_run_view(db, session)
    from app.services.learning_tasks import learning_task_view
    from app.models.learning import LearningTask
    learning_tasks = list((await db.execute(select(LearningTask).where(
        LearningTask.learner_id == session.learner_id,
        LearningTask.session_id == session.id,
        LearningTask.status.in_({"proposed", "queued", "active", "paused"}),
    ).order_by(LearningTask.queue_position, LearningTask.id))).scalars().all())
    latest_assistant = next((item for item in reversed(messages) if item.role == "assistant"), None)
    skill_recommendation = (
        dict((latest_assistant.meta_data or {}).get("skill_recommendation") or {}) or None
        if latest_assistant else None
    )
    learning_task_views = [await learning_task_view(db, item) for item in learning_tasks]
    current_mode = chat_mode_view(session)
    running_skill = str((skill_run or {}).get("status") or "completed") in {"active", "verification"}
    running_task = any(item.status == "active" for item in learning_tasks)
    if (
        current_mode["id"] == "free"
        and current_mode["status"] == "active"
        and (running_skill or running_task)
    ):
        current_mode = await enter_chat_mode(
            db,
            session,
            mode_id="learn",
            goal=str((skill_run or {}).get("goal") or next(
                (item.objective for item in learning_tasks if item.status == "active"),
                "继续当前原子学习任务",
            )),
            reason="恢复仍在进行的原子学习任务",
            entry_message_id=latest_assistant.id if latest_assistant else session.id,
            learning_task_id=next(
                (item.id for item in learning_tasks if item.status == "active"),
                None,
            ),
        )
    elif (
        current_mode["id"] == "learn"
        and current_mode["status"] == "active"
        and not running_task
        and not running_skill
    ):
        current_mode = await enter_chat_mode(
            db,
            session,
            mode_id="free",
            goal="",
            reason="原子学习任务与学习方法运行均已结束",
            entry_message_id=latest_assistant.id if latest_assistant else session.id,
        )
    state_summary = await get_session_state_summary(db, session)
    await db.commit()
    return {
        "id": session.id,
        "title": session.title,
        "session_type": session.session_type,
        "project_id": session.project_id,
        "checkpoint_id": session.checkpoint_id,
        "messages": [_message_out(m) for m in messages],
        "state_summary": state_summary,
        "action_card": action_card(pending),
        "project_proposals": [proposal_view(item) for item in proposals],
        "chat_mode": current_mode,
        "active_skill": session_learning_skill(session),
        "active_skill_run": skill_run,
        "skill_recommendation": skill_recommendation,
        "learning_tasks": learning_task_views,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


@router.get("/skills")
async def list_learning_skills(
    current: CurrentLearner = Depends(get_current_learner),
):
    del current
    return selectable_learning_skill_manifest()


@router.get("/modes")
async def list_chat_modes(
    current: CurrentLearner = Depends(get_current_learner),
):
    del current
    return chat_mode_manifest()


@router.get("/sessions")
async def list_sessions(
    session_type: str | None = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if session_type not in {None, "global", "project", "checkpoint"}:
        raise HTTPException(400, "Unsupported Tutor session type")
    query = select(AgentSession).where(
        AgentSession.learner_id == current.learner.id,
        AgentSession.status == "active",
    )
    if session_type:
        query = query.where(AgentSession.session_type == session_type)
    sessions = (await db.execute(
        query.order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
        .limit(max(1, min(limit, 100)))
    )).scalars().all()
    result = []
    for session in sessions:
        last_message = (await db.execute(
            select(AgentMessage).where(AgentMessage.session_id == session.id)
            .order_by(AgentMessage.id.desc()).limit(1)
        )).scalar_one_or_none()
        result.append({
            "id": session.id,
            "title": session.title,
            "session_type": session.session_type,
            "project_id": session.project_id,
            "checkpoint_id": session.checkpoint_id,
            "chat_mode": chat_mode_view(session),
            "active_skill": session_learning_skill(session),
            "last_message": last_message.content[:120] if last_message else "",
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        })
    return result


def _skill_run_error(error: RuntimeError) -> HTTPException:
    message = str(error)
    if message == "version_conflict":
        return HTTPException(409, "学习方法状态已更新，请刷新后重试")
    if message == "invalid_state":
        return HTTPException(409, "当前步骤不能执行这个操作")
    if message == "unsupported_scope":
        return HTTPException(400, "对话内学习方法目前只在独立学习对话中运行")
    if message == "unsupported_skill":
        return HTTPException(400, "这个学习方法当前没有可恢复工作流")
    if message == "missing_goal":
        return HTTPException(400, "请先给出一个具体学习目标")
    return HTTPException(400, "无法更新学习方法")


@router.post("/sessions/{session_id}/skill-runs")
async def start_learning_skill_run(
    session_id: int,
    request: LearningSkillRunCreateRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    active_skill, changed = _select_session_learning_skill(
        session, request.skill_id, request.goal,
    )
    try:
        run, created = await create_learning_skill_run(
            db,
            session=session,
            skill_id=request.skill_id,
            goal=request.goal,
            client_request_id=request.client_request_id,
            source="user",
        )
    except RuntimeError as error:
        raise _skill_run_error(error) from error
    if changed:
        await record_event(
            db,
            learner_id=session.learner_id,
            session_id=session.id,
            event_type="learning_skill_selected",
            source="user",
            payload={
                "skill_id": active_skill["id"] if active_skill else "adaptive",
                "skill_name": active_skill["name"] if active_skill else "自动选择",
            },
            provenance={"skill_run_id": run.id, "interaction": "recommendation_accepted"},
            client_event_id=f"learning-skill-run:{run.id}:selected",
        )
    await enter_chat_mode(
        db,
        session,
        mode_id="learn",
        goal=request.goal,
        reason="学习者显式启动了运行型学习方法",
        entry_message_id=run.id,
        learning_task_id=run.learning_task_id,
    )
    if session.title in {"学习 Tutor", "新对话"}:
        session.title = request.goal[:36] + ("…" if len(request.goal) > 36 else "")
    view = await learning_skill_run_view(db, run)
    message = str((view or {}).get("next_prompt") or "学习方法已经开始。")
    if created:
        stored = AgentMessage(
            session_id=session.id,
            role="assistant",
            content=message,
            meta_data={"learning_skill": active_skill, "learning_skill_run": view},
            idempotency_key=f"learning-skill-run:{run.id}:opening-message",
        )
        db.add(stored)
    await db.commit()
    return {
        "session_id": session.id,
        "session_title": session.title,
        "chat_mode": chat_mode_view(session),
        "active_skill": active_skill,
        "active_skill_run": await learning_skill_run_view(db, run),
        "chat_mode": chat_mode_view(session),
        "message": message,
        "created": created,
    }


@router.post("/sessions/{session_id}/skill-runs/{run_id}/actions")
async def update_learning_skill_run(
    session_id: int,
    run_id: int,
    request: LearningSkillRunActionRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    run = (await db.execute(select(LearningSkillRun).where(
        LearningSkillRun.id == run_id,
        LearningSkillRun.learner_id == current.learner.id,
        LearningSkillRun.session_id == session.id,
    ))).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "学习方法记录不存在")
    try:
        run, micro = await act_on_learning_skill_run(
            db,
            run=run,
            action=request.action,
            expected_version=request.expected_version,
            client_action_id=request.client_action_id,
            education_stage=current.profile.education_stage or "",
            background=current.profile.background or "",
        )
    except RuntimeError as error:
        raise _skill_run_error(error) from error
    await db.commit()
    micro_view = None
    if micro:
        from app.services.micro_learning import run_view
        micro_view = await run_view(db, micro)
    return {
        "session_id": session.id,
        "chat_mode": chat_mode_view(session),
        "active_skill": session_learning_skill(session),
        "active_skill_run": await learning_skill_run_view(db, run),
        "learning_run": micro_view,
    }


@router.post("/sessions")
async def create_or_resume_session(
    data: AgentSessionCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    project_id = data.project_id
    session_type = data.session_type
    if project_id is not None:
        await require_owned_project(db, current.learner.id, project_id)
    if data.checkpoint_id is not None:
        checkpoint = await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
        if not roadmap:
            raise HTTPException(404, "Checkpoint roadmap not found")
        if project_id is not None and project_id != roadmap.project_id:
            raise HTTPException(400, "Checkpoint does not belong to project")
        project_id = roadmap.project_id
        session_type = "checkpoint"
    elif session_type == "checkpoint":
        raise HTTPException(400, "checkpoint session requires checkpoint_id")
    session = await get_or_create_session(
        db,
        learner_id=current.learner.id,
        session_type="project" if project_id and session_type == "global" else session_type,
        project_id=project_id,
        checkpoint_id=data.checkpoint_id,
        create_new=data.create_new,
    )
    await db.commit()
    return await _session_payload(db, session)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    return await _session_payload(db, session)


@router.post("/sessions/{session_id}/turns")
async def tutor_turn(
    session_id: int,
    data: TutorTurnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    if (
        pending and pending.capability == "delegate_local_agent_task"
        and (data.selected_action_id == pending.id or _is_confirmation(data.message))
        and not valid_desktop_request(request)
    ):
        raise HTTPException(404, "Local Agent Broker is unavailable")
    if session.session_type == "checkpoint":
        if data.project_id is not None and data.project_id != session.project_id:
            raise HTTPException(409, "Checkpoint Tutor project scope is immutable")
        if data.checkpoint_id is not None and data.checkpoint_id != session.checkpoint_id:
            raise HTTPException(409, "Checkpoint Tutor scope is immutable")
    if data.project_id is not None:
        await require_owned_project(db, current.learner.id, data.project_id)
    if data.checkpoint_id is not None:
        await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
    try:
        return await process_turn(
            db, session,
            message=data.message,
            project_id=data.project_id,
            checkpoint_id=data.checkpoint_id,
            selected_action_id=data.selected_action_id,
            selected_skill_id=data.selected_skill_id,
            client_turn_id=data.client_turn_id,
            context=data.context,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/project-proposals/{proposal_id}")
async def get_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    return proposal_view(proposal)


@router.get("/projects/{project_id}/accepted-proposal")
async def get_accepted_project_proposal(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_project(db, current.learner.id, project_id)
    proposal = (await db.execute(
        select(LearningProjectProposal)
        .where(
            LearningProjectProposal.accepted_project_id == project_id,
            LearningProjectProposal.learner_id == current.learner.id,
            LearningProjectProposal.status == "accepted",
        )
        .order_by(LearningProjectProposal.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return proposal_view(proposal) if proposal else None


@router.patch("/project-proposals/{proposal_id}")
async def patch_project_proposal(
    proposal_id: int,
    data: ProjectProposalUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await update_project_proposal(
            db, proposal,
            patch=data.patch,
            lock_fields=data.lock_fields,
            unlock_fields=data.unlock_fields,
            client_event_id=data.client_event_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/accept")
async def accept_project_proposal(
    proposal_id: int,
    data: ProjectProposalAcceptRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    if proposal.status not in {"draft", "ready", "accepted"}:
        raise HTTPException(400, "这个项目提案当前不能创建")
    was_accepted = proposal.status == "accepted"
    try:
        action = await proposal_acceptance_action(db, proposal)
        action.target = {**dict(action.target or {}), "accept_client_event_id": data.client_event_id}
        message = await execute_action(db, action)
        await finalize_proposal_acceptance(db, proposal, action)
    except Exception as exc:
        action = await db.get(AgentAction, proposal.accepted_action_id) if proposal.accepted_action_id else None
        if action:
            action.status = "failed"
            action.error = {"message": str(exc)[:500]}
            action.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(400, str(exc)) from exc
    if not was_accepted:
        db.add(AgentMessage(
            session_id=proposal.session_id,
            role="assistant",
            content=message,
            meta_data={"action_id": action.id, "proposal_id": proposal.id},
        ))
    await db.commit()
    session = await _owned_session(db, current.learner.id, proposal.session_id)
    await enter_chat_mode(
        db,
        session,
        mode_id="free",
        goal="",
        reason="项目提案已经接受并完成规划交接",
        entry_message_id=action.id,
        project_proposal_id=proposal.id,
    )
    proposals = await list_session_proposals(db, proposal.session_id)
    await db.commit()
    return {
        "session_id": proposal.session_id,
        "chat_mode": chat_mode_view(session),
        "message": message,
        "executed_action": action_result(action),
        "action_card": None,
        "project_proposals": [proposal_view(item) for item in proposals],
        "proposal_update": proposal_view(proposal),
        "state_summary": await get_session_state_summary(db, session),
    }


@router.post("/project-proposals/{proposal_id}/dismiss")
async def dismiss_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await set_proposal_status(db, proposal, "dismissed")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session = await _owned_session(db, current.learner.id, proposal.session_id)
    await enter_chat_mode(
        db,
        session,
        mode_id="free",
        goal="",
        reason="学习者暂不继续当前项目提案",
        entry_message_id=proposal.id,
        project_proposal_id=proposal.id,
    )
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/reopen")
async def reopen_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await set_proposal_status(db, proposal, "ready")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/refresh-sources")
async def refresh_project_proposal_sources(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    await start_resource_search(db, proposal, force=True)
    return proposal_view(proposal)


@router.get("/actions/{action_id}")
async def get_action(
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    task = None
    if action.task_id:
        task = (await db.execute(select(Task).where(
            Task.id == action.task_id,
            Task.learner_id == current.learner.id,
        ))).scalar_one_or_none()
        if task and task.status in {"completed", "failed", "canceled"} and action.status == "running":
            await finalize_action_for_task(task)
            await db.refresh(action)
    result = action_result(action)
    if task:
        result["task"] = {
            "id": task.id,
            "status": task.status,
            "progress": task.progress or {},
            "error": task.error or {},
        }
    return result


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    if action.capability == "delegate_local_agent_task" and not valid_desktop_request(request):
        raise HTTPException(404, "Local Agent Broker is unavailable")
    if action.status not in {"pending_confirmation", "needs_input"}:
        return action_result(action)
    if action.status == "needs_input":
        raise HTTPException(400, "这个行动还缺少必要信息")
    action.status = "ready"
    try:
        message = await execute_action(db, action)
    except Exception as exc:
        action.status = "failed"
        action.error = {"message": str(exc)[:500]}
        action.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(400, str(exc))
    session = await _owned_session(db, current.learner.id, action.session_id)
    active_skill = session_learning_skill(session)
    db.add(AgentMessage(
        session_id=action.session_id,
        role="assistant",
        content=message,
        meta_data={
            "action_id": action.id,
            "learning_skill": active_skill,
            "local_agent_run_id": (
                ((action.result or {}).get("local_agent_run") or {}).get("id")
            ),
        },
    ))
    await db.commit()
    return {
        "session_id": session.id,
        "session_title": session.title,
        "active_skill": active_skill,
        "active_skill_run": await latest_learning_skill_run_view(db, session),
        "skill_recommendation": None,
        "message": message,
        "executed_action": action_result(action),
        "state_summary": await get_session_state_summary(db, session),
    }


@router.post("/actions/{action_id}/cancel")
async def cancel_action(
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    if action.status in {"completed", "failed", "canceled"}:
        return action_result(action)
    action.status = "canceled"
    action.finished_at = datetime.utcnow()
    session = await _owned_session(db, current.learner.id, action.session_id)
    if session and session.pending_action_id == action.id:
        session.pending_action_id = None
    if action.task_id:
        from app.services.task_manager import manager
        manager.cancel(action.task_id)
    await db.commit()
    return action_result(action)


@events_router.post("/learning-events")
async def create_learning_event(
    data: LearningEventRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if data.event_type not in PUBLIC_EVENT_TYPES:
        raise HTTPException(400, "Unsupported learning event type")
    if data.project_id is not None:
        await require_owned_project(db, current.learner.id, data.project_id)
    if data.checkpoint_id is not None:
        await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
    if data.session_id is not None:
        await _owned_session(db, current.learner.id, data.session_id)
    event = await record_event(
        db,
        event_type=data.event_type,
        source="ui",
        learner_id=current.learner.id,
        project_id=data.project_id,
        checkpoint_id=data.checkpoint_id,
        session_id=data.session_id,
        payload=data.payload,
        confidence=0.8 if data.event_type in {"lecture_viewed", "learning_feedback"} else 1.0,
        provenance={"client": "frontend"},
        client_event_id=data.client_event_id,
    )
    if data.checkpoint_id:
        await evaluate_checkpoint_status(
            db, data.checkpoint_id, learner_id=current.learner.id,
        )
    await db.commit()
    return {"id": event.id, "state_summary": await get_state_summary(
        db, data.project_id, data.checkpoint_id,
        learner_id=current.learner.id,
    )}
