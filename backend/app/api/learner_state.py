from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import LearningTask, MemoryClaim, MemoryModule, MemoryNode
from app.services.auth import CurrentLearner, get_current_learner
from app.services.five_kernel_context import build_five_kernel_context
from app.services.learning_runtime import get_kernel_projection, record_event
from app.services.learning_tasks import (
    ensure_all_checkpoint_learning_tasks,
    learning_task_view,
)
from app.services.personal_concept_graph import (
    build_personal_concept_graph,
    concept_client_event_id,
    extract_self_report,
    normalize_observation,
    normalize_relation,
)
from app.services.profile import growth_projection


router = APIRouter(prefix="/learner-state", tags=["Learner State Gateway"])

PATH_STATUSES = {
    "unmarked", "exploring", "self_reported_exposed", "self_reported_mastered",
}
PATH_EDGE_KINDS = {"hard_prerequisite", "soft_prerequisite", "co_learning"}
SYNC_EVENT_TYPES = {
    "chat_mode_entered",
    "learning_action_segment_completed",
    "vnext_learning_task_created",
    "vnext_learning_task_started",
    "vnext_learning_task_phase_entered",
    "vnext_learning_skill_step_entered",
    "vnext_learning_skill_looped",
    "vnext_learning_task_learner_replied",
    "vnext_learning_support_requested",
    "vnext_learning_skill_selected",
    "vnext_learning_task_paused",
    "vnext_learning_task_resumed",
    "vnext_learning_task_completed",
    "vnext_learning_plan_started",
    "vnext_learning_plan_note_captured",
    "vnext_project_seed_ready",
    "vnext_direction_plan_ready",
    "vnext_value_claim_proposed",
    "vnext_value_claim_proposal_rejected",
    "vnext_value_claim_proposal_revision_requested",
    "vnext_learning_plan_closed",
}


class LearnerEventRequest(BaseModel):
    event_type: str = Field(min_length=2, max_length=80)
    client_event_id: str = Field(min_length=4, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("event_type")
    @classmethod
    def registered_vnext_event(cls, value: str) -> str:
        if value not in SYNC_EVENT_TYPES:
            raise ValueError("该事件不能通过 vNext 同步入口写入")
        return value


class PathStatusRequest(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    node_title: str = Field(default="", max_length=200)
    status: Literal[
        "unmarked", "exploring", "self_reported_exposed", "self_reported_mastered",
    ]
    client_event_id: str = Field(min_length=4, max_length=160)


class PersonalPathNodeRequest(BaseModel):
    node: dict[str, Any]
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    reason: str = Field(default="", max_length=500)
    client_event_id: str = Field(min_length=4, max_length=160)

    @field_validator("node")
    @classmethod
    def valid_personal_node(cls, node: dict[str, Any]) -> dict[str, Any]:
        node_id = str(node.get("id") or "").strip()
        title = str(node.get("title") or "").strip()
        if not node_id or not title:
            raise ValueError("个人节点必须包含 id 与 title")
        return {
            "id": node_id[:160],
            "title": title[:200],
            "summary": str(node.get("summary") or "")[:1000],
            "aliases": [str(item)[:80] for item in list(node.get("aliases") or [])[:8]],
            "domains": [str(item)[:60] for item in list(node.get("domains") or [])[:8]],
            "stage": str(node.get("stage") or "advanced")[:40],
            "order": max(0, min(int(node.get("order") or 6), 20)),
            "origin": "personal",
            "sourceRefs": [str(item)[:500] for item in list(node.get("sourceRefs") or [])[:8]],
        }


class ValueClaimConfirmationRequest(BaseModel):
    proposal_id: str = Field(min_length=2, max_length=160)
    current_claim: str = Field(default="", max_length=1000)
    proposed_claim: str = Field(min_length=2, max_length=1000)
    evidence_quote: str = Field(min_length=1, max_length=500)
    scope: str = Field(default="long_term_direction_candidate", max_length=80)
    client_event_id: str = Field(min_length=4, max_length=160)


class ConceptStatementRequest(BaseModel):
    raw_text: str = Field(min_length=2, max_length=12000)
    concepts: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    relations: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    source_tag: str = Field(default="user_self_input", min_length=2, max_length=60)
    client_event_id: str = Field(min_length=4, max_length=120)


def _path_overlay(projection: dict[str, Any]) -> dict[str, Any]:
    structure = dict((projection.get("structure") or {}).get("long_term") or {})
    statuses = dict(structure.get("learning_path_statuses") or {})
    raw_nodes = dict(structure.get("personal_learning_path_nodes") or {})
    nodes = [
        value for value in raw_nodes.values()
        if isinstance(value, dict) and value.get("status", "active") == "active"
    ]
    return {
        "version": 1,
        "statuses": statuses,
        "personal_nodes": nodes,
        "event_backed": True,
        "knowledge_mastery_inference": False,
    }


def _validated_personal_edges(
    node_id: str,
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not edges:
        raise HTTPException(422, "个人节点必须至少连接一个已有节点")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(edges):
        source = str(raw.get("from") or "").strip()
        target = str(raw.get("to") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if not source or not target or source == target:
            raise HTTPException(422, "个人节点关系必须包含不同的起点与终点")
        if node_id not in {source, target}:
            raise HTTPException(422, "个人节点关系必须连接当前个人节点")
        if kind not in PATH_EDGE_KINDS:
            raise HTTPException(422, "个人节点关系类型不受支持")
        normalized.append({
            "id": str(raw.get("id") or f"personal-edge:{node_id}:{index}")[:200],
            "from": source[:160],
            "to": target[:160],
            "kind": kind,
            "rationale": str(raw.get("rationale") or "")[:500],
            "origin": "personal",
        })
    return normalized


def _path_edges_have_cycle(edges: list[dict[str, Any]]) -> bool:
    adjacency: dict[str, set[str]] = {}
    indegree: dict[str, int] = {}
    for edge in edges:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, set())
        adjacency.setdefault(target, set())
        indegree.setdefault(source, 0)
        if target in adjacency[source]:
            continue
        adjacency[source].add(target)
        indegree[target] = indegree.get(target, 0) + 1
    queue = [node for node in adjacency if indegree.get(node, 0) == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return visited != len(adjacency)


async def _memory_modules(db: AsyncSession, learner_id: int) -> list[dict[str, Any]]:
    rows = list((await db.execute(
        select(MemoryNode, MemoryModule)
        .join(MemoryModule, MemoryModule.node_id == MemoryNode.id)
        .where(
            MemoryNode.learner_id == learner_id,
            MemoryNode.node_type == "module",
            MemoryNode.status == "active",
        )
        .order_by(MemoryNode.kernel_name, MemoryNode.subject_key, MemoryModule.version.desc())
    )).all())
    modules: list[dict[str, Any]] = []
    for node, module in rows:
        claim_rows = list((await db.execute(
            select(MemoryNode, MemoryClaim)
            .join(MemoryClaim, MemoryClaim.node_id == MemoryNode.id)
            .where(
                MemoryClaim.module_node_id == node.id,
                MemoryNode.learner_id == learner_id,
                MemoryNode.status.in_(["active", "challenged"]),
            )
            .order_by(MemoryClaim.claim_ordinal)
        )).all())
        modules.append({
            "id": node.id,
            "kernel": node.kernel_name,
            "subject_key": node.subject_key,
            "title": node.subject_key,
            "summary": module.summary,
            "version": int(module.version or 1),
            "revision_kind": module.revision_kind,
            "evidence_fact_ids": list(module.evidence_fact_ids or []),
            "claims": [{
                "id": claim_node.id,
                "text": claim_node.text,
                "status": claim_node.status,
                "confidence": float(claim_node.confidence or 0),
                "predicate": claim.predicate,
                "verification_status": claim.verification_status,
            } for claim_node, claim in claim_rows],
        })
    return modules


@router.get("/snapshot")
async def get_learner_state_snapshot(
    include_terminal_tasks: bool = Query(default=False),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await ensure_all_checkpoint_learning_tasks(db, learner_id=current.learner.id)
    projection = await get_kernel_projection(db, current.learner.id)
    task_query = select(LearningTask).where(LearningTask.learner_id == current.learner.id)
    if not include_terminal_tasks:
        task_query = task_query.where(LearningTask.status.in_({"proposed", "queued", "active", "paused"}))
    tasks = list((await db.execute(task_query.order_by(
        LearningTask.priority.desc(), LearningTask.queue_position, LearningTask.created_at,
    ).limit(100))).scalars().all())
    task_views = [await learning_task_view(db, task) for task in tasks]
    growth = await growth_projection(db, current.learner.id)
    modules = await _memory_modules(db, current.learner.id)
    concept_graph = await build_personal_concept_graph(db, current.learner.id)
    await db.commit()
    return {
        "authority": "EvidenceEvent -> five_kernel_reducer -> Memory Graph",
        "learner": {
            "id": current.learner.id,
            "display_name": current.learner.display_name,
            "education_stage": current.profile.education_stage,
        },
        "profile": {
            "background": current.profile.background,
            "focus_areas": list(current.profile.focus_areas or []),
            "weekly_hours": current.profile.weekly_hours,
            "preferred_modes": list(current.profile.preferred_modes or []),
            "career_goal": current.profile.career_goal,
            "career_goal_status": current.profile.career_goal_status,
        },
        "kernels": projection,
        "growth": growth,
        "modules": modules,
        "concept_graph": concept_graph,
        "learning_path": _path_overlay(projection),
        "learning_tasks": task_views,
    }


@router.get("/context")
async def get_learner_context(
    query: str = Query(default="", max_length=2000),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    packet = await build_five_kernel_context(
        db,
        learner_id=current.learner.id,
        policy="global_tutor",
        query=query,
    )
    return packet


@router.get("/concept-graph")
async def get_personal_concept_graph(
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return await build_personal_concept_graph(db, current.learner.id)


@router.post("/concept-graph/statements")
async def record_concept_statement(
    request: ConceptStatementRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    extracted_concepts, extracted_relations = extract_self_report(request.raw_text)
    concept_inputs = request.concepts or extracted_concepts
    relation_inputs = request.relations or extracted_relations
    if not concept_inputs and not relation_inputs:
        raise HTTPException(
            422,
            "没有识别到明确的概念自述。请使用“我学过 / 我不懂 / 我混淆”等表达，或提交已核对的概念条目。",
        )
    try:
        concepts = [normalize_observation(item) for item in concept_inputs]
        relations = [normalize_relation(item) for item in relation_inputs]
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    statement_event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="learner_concept_statement_recorded",
        source="user",
        payload={
            "raw_text": request.raw_text,
            "source_tag": request.source_tag,
            "verification": "unverified",
            "mastery_inference": False,
            "extracted_concept_count": len(concepts),
            "extracted_relation_count": len(relations),
        },
        confidence=1.0,
        provenance={"self_report": True, "explicit_click": True, "mastery_unchanged": True},
        client_event_id=concept_client_event_id(request.client_event_id, "statement"),
    )

    knowledge_event_ids: list[int] = []
    for index, concept in enumerate(concepts):
        event = await record_event(
            db,
            learner_id=current.learner.id,
            event_type="learner_concept_observation_recorded",
            source="user",
            payload={
                "statement_event_id": statement_event.id,
                "raw_text": request.raw_text,
                "source_tag": request.source_tag,
                "verification": "unverified",
                "mastery_inference": False,
                "memory_subject_key": f"concept:{concept['concept_key']}",
                "concept_key": concept["concept_key"],
                "concept_name": concept["name"],
                "concept_aliases": concept["aliases"],
                "concept_origin": concept["origin"],
                "official_node_id": concept["official_node_id"],
                "observation_type": concept["observation_type"],
                "statement": concept["statement"],
                "question_ref": concept["question_ref"],
            },
            confidence=1.0,
            provenance={"self_report": True, "explicit_click": True, "mastery_unchanged": True},
            client_event_id=concept_client_event_id(
                request.client_event_id, "knowledge", index, concept["concept_key"],
            ),
        )
        knowledge_event_ids.append(event.id)

    structure_event_ids: list[int] = []
    for index, relation in enumerate(relations):
        event = await record_event(
            db,
            learner_id=current.learner.id,
            event_type="learner_concept_relation_recorded",
            source="user",
            payload={
                "statement_event_id": statement_event.id,
                "raw_text": request.raw_text,
                "source_tag": request.source_tag,
                "verification": "unverified",
                "mastery_inference": False,
                "memory_subject_key": f"concept:{relation['target']['concept_key']}",
                "concept_key": relation["target"]["concept_key"],
                "concept_name": relation["target"]["name"],
                "official_node_id": relation["target"].get("official_node_id"),
                "source_anchor": relation["source"],
                "target_anchor": relation["target"],
                "relation_type": relation["relation_type"],
                "rationale": relation["rationale"],
            },
            confidence=1.0,
            provenance={"self_report": True, "explicit_click": True, "mastery_unchanged": True},
            client_event_id=concept_client_event_id(
                request.client_event_id, "structure", index, relation["relation_type"],
                relation["source"]["concept_key"], relation["target"]["concept_key"],
            ),
        )
        structure_event_ids.append(event.id)

    graph = await build_personal_concept_graph(db, current.learner.id)
    await db.commit()
    return {
        "statement_event_id": statement_event.id,
        "knowledge_event_ids": knowledge_event_ids,
        "structure_event_ids": structure_event_ids,
        "extracted": {"concepts": concepts, "relations": relations},
        "concept_graph": graph,
    }


@router.post("/events")
async def sync_learner_event(
    request: LearnerEventRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type=request.event_type,
        source="vnext",
        payload=request.payload,
        occurred_at=request.occurred_at,
        confidence=1.0,
        provenance={"vnext_sync": True},
        client_event_id=request.client_event_id,
    )
    await db.commit()
    return {"event_id": event.id, "learner_seq": event.learner_seq}


@router.post("/learning-path/status")
async def set_learning_path_status(
    request: PathStatusRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="vnext_learning_path_node_status_set",
        source="user",
        payload={
            "node_id": request.node_id,
            "node_title": request.node_title,
            "status": request.status,
            "memory_subject_key": f"course:{request.node_id}",
        },
        confidence=1.0,
        provenance={"self_report": True, "explicit_click": True, "mastery_unchanged": True},
        client_event_id=request.client_event_id,
    )
    projection = await get_kernel_projection(db, current.learner.id)
    await db.commit()
    return {"event_id": event.id, "learning_path": _path_overlay(projection)}


@router.post("/learning-path/personal-nodes")
async def add_personal_learning_path_node(
    request: PersonalPathNodeRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    node_id = str(request.node["id"])
    projection = await get_kernel_projection(db, current.learner.id)
    current_nodes = dict((projection.get("structure") or {}).get("long_term") or {}).get(
        "personal_learning_path_nodes", {},
    )
    if node_id in current_nodes and current_nodes[node_id].get("status", "active") == "active":
        raise HTTPException(409, "个人学习路径节点已存在")
    edges = _validated_personal_edges(node_id, request.edges)
    active_edges = [
        edge
        for node in current_nodes.values()
        if isinstance(node, dict) and node.get("status", "active") == "active"
        for edge in list(node.get("edges") or [])
        if isinstance(edge, dict)
    ]
    if _path_edges_have_cycle([*active_edges, *edges]):
        raise HTTPException(422, "个人节点关系会在学习路径中形成环")
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="vnext_personal_path_node_added",
        source="user",
        payload={
            "node": request.node,
            "edges": edges,
            "reason": request.reason,
            "memory_subject_key": f"course:{node_id}",
        },
        confidence=1.0,
        provenance={"explicit_click": True, "learner_confirmed": True},
        client_event_id=request.client_event_id,
    )
    projection = await get_kernel_projection(db, current.learner.id)
    await db.commit()
    return {"event_id": event.id, "learning_path": _path_overlay(projection)}


@router.delete("/learning-path/personal-nodes/{node_id}")
async def remove_personal_learning_path_node(
    node_id: str,
    client_event_id: str = Query(min_length=4, max_length=160),
    node_title: str = Query(default="", max_length=200),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    projection = await get_kernel_projection(db, current.learner.id)
    current_nodes = dict((projection.get("structure") or {}).get("long_term") or {}).get(
        "personal_learning_path_nodes", {},
    )
    if node_id not in current_nodes or current_nodes[node_id].get("status", "active") != "active":
        raise HTTPException(404, "个人学习路径节点不存在")
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="vnext_personal_path_node_removed",
        source="user",
        payload={
            "node_id": node_id,
            "node_title": node_title or current_nodes[node_id].get("title", node_id),
            "memory_subject_key": f"course:{node_id}",
        },
        confidence=1.0,
        provenance={"explicit_click": True, "learner_confirmed": True},
        client_event_id=client_event_id,
    )
    updated = await get_kernel_projection(db, current.learner.id)
    await db.commit()
    return {"event_id": event.id, "learning_path": _path_overlay(updated)}


@router.post("/value-claims/confirm")
async def confirm_value_claim(
    request: ValueClaimConfirmationRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="vnext_value_claim_proposal_accepted",
        source="user",
        payload={
            "proposal_id": request.proposal_id,
            "current_claim": request.current_claim,
            "proposed_claim": request.proposed_claim,
            "evidence_quote": request.evidence_quote,
            "scope": request.scope,
            "memory_subject_key": f"goal:{request.proposal_id}",
        },
        confidence=1.0,
        provenance={"explicit_click": True, "learner_confirmed": True},
        client_event_id=request.client_event_id,
    )
    await db.commit()
    return {"event_id": event.id, "status": "confirmed"}
