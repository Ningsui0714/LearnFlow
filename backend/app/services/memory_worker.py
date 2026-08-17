"""Persistent single-process worker for validated memory consolidation."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import async_session
from app.models.learning import (
    EvidenceEvent,
    MemoryClaim,
    MemoryEdge,
    MemoryFact,
    MemoryModule,
    MemoryNode,
    MemorySynthesisRun,
)
from app.services.memory_graph import (
    MODULE_VERSION_POLICY,
    _add_edge,
    _bounded_evidence_ids,
    current_memory_module,
    input_fingerprint,
    maybe_queue_synthesis,
    module_evidence_fact_ids,
    rebuild_kernel_long_term_from_modules,
)
from app.services.five_kernel_context import (
    MEMORY_SCHEMA_VERSION,
    memory_salience,
    refresh_kernel_head,
    subject_parts,
)


class SynthesisClaimDraft(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    predicate: str = Field(min_length=1, max_length=255)
    value: Any = None
    evidence_fact_ids: list[int] = Field(min_length=1)


class SynthesisDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=1200)
    claims: list[SynthesisClaimDraft] = Field(min_length=1, max_length=8)


def _deterministic_draft(
    kernel_name: str,
    subject_key: str,
    rows: list[tuple[MemoryNode, MemoryFact, EvidenceEvent]],
) -> SynthesisDraft:
    facts = [node for node, _, _ in rows]
    detail = "；".join(node.text for node in facts)
    summary = f"{subject_key} 的{kernel_name}动作已形成稳定片段：{detail}"
    if len(summary) > 1200:
        summary = summary[:1199] + "…"
    return SynthesisDraft(
        summary=summary,
        claims=[SynthesisClaimDraft(
            text=detail[:800],
            predicate=f"{kernel_name}.synthesis",
            value={"fact_count": len(facts), "subject": subject_key},
            evidence_fact_ids=[node.id for node in facts],
        )],
    )


async def _model_draft(
    kernel_name: str,
    subject_key: str,
    rows: list[tuple[MemoryNode, MemoryFact, EvidenceEvent]],
) -> tuple[SynthesisDraft, str, dict]:
    if not settings.llm_api_key:
        return _deterministic_draft(kernel_name, subject_key, rows), "deterministic", {}

    from langchain_openai import ChatOpenAI

    candidates = [{
        "fact_id": node.id,
        "text": node.text,
        "predicate": fact.predicate,
        "evidence_grade": fact.evidence_grade,
        "event_type": event.event_type,
        "occurred_at": node.occurred_at.isoformat(),
    } for node, fact, event in rows]
    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0,
        timeout=45,
        max_retries=1,
    )
    structured = llm.with_structured_output(SynthesisDraft, include_raw=True)
    prompt = (
        "你是 LearnFlow 五核记忆合成器。只总结给定的同一维度事实，不补充外部知识。"
        "每条 claim 必须引用至少一个候选 fact_id，且不得引用列表外 ID。"
        "知识维度中，exposure_only 或 self_reported 不能被表述成已掌握。"
        "保持可证伪、简洁，保留冲突，不要强行求一致。\n"
        f"维度: {kernel_name}\n主题: {subject_key}\n"
        f"候选事实: {json.dumps(candidates, ensure_ascii=False)}"
    )
    result = await structured.ainvoke(prompt)
    parsed = result.get("parsed") if isinstance(result, dict) else result
    if not isinstance(parsed, SynthesisDraft):
        parsed = SynthesisDraft.model_validate(parsed)
    usage = {}
    raw = result.get("raw") if isinstance(result, dict) else None
    if raw is not None:
        usage = dict(getattr(raw, "usage_metadata", None) or {})
    return parsed, settings.llm_model, usage


def _validate_draft(
    run: MemorySynthesisRun,
    draft: SynthesisDraft,
    rows: list[tuple[MemoryNode, MemoryFact, EvidenceEvent]],
) -> list[str]:
    errors: list[str] = []
    allowed = {node.id for node, _, _ in rows}
    facts = {node.id: fact for node, fact, _ in rows}
    if not draft.claims:
        errors.append("module_has_no_claims")
    for index, claim in enumerate(draft.claims):
        refs = set(claim.evidence_fact_ids)
        if not refs:
            errors.append(f"claim_{index}_has_no_evidence")
        if not refs.issubset(allowed):
            errors.append(f"claim_{index}_references_outside_whitelist")
        mastery_language = "掌握" in claim.text or "master" in claim.predicate.casefold()
        if run.kernel_name == "knowledge" and mastery_language:
            verified = {fact.source_event_id for fact_id, fact in facts.items()
                        if fact_id in refs and fact.evidence_grade == "verified"}
            if len(verified) < 2:
                errors.append(f"claim_{index}_insufficient_mastery_evidence")
    return errors


async def recover_interrupted_runs() -> int:
    async with async_session() as db:
        runs = (await db.execute(select(MemorySynthesisRun).where(
            MemorySynthesisRun.status == "running",
        ))).scalars().all()
        for run in runs:
            facts = (await db.execute(select(MemoryFact).where(
                MemoryFact.reservation_run_id == run.id,
            ))).scalars().all()
            for fact in facts:
                fact.consumption_status = "eligible"
                fact.reservation_run_id = None
            run.status = "queued"
            run.started_at = None
            run.due_at = datetime.utcnow()
        await db.commit()
        return len(runs)


async def reconcile_eligible_synthesis_runs() -> int:
    """Rebuild missing queues for historical eligible Fact groups.

    Facts are the source projection, so this scan is safe to repeat on every
    worker start. ``maybe_queue_synthesis`` re-applies the deterministic
    per-kernel threshold and fingerprint rules; no Module or Claim is created
    here directly.
    """
    async with async_session() as db:
        groups = list((await db.execute(
            select(
                MemoryNode.learner_id,
                MemoryNode.kernel_name,
                MemoryNode.subject_key,
            )
            .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
            .where(
                MemoryNode.node_type == "fact",
                MemoryFact.consumption_status == "eligible",
            )
            .distinct()
            .order_by(
                MemoryNode.learner_id.asc(),
                MemoryNode.kernel_name.asc(),
                MemoryNode.subject_key.asc(),
            )
        )).all())
        actionable: set[int] = set()
        for learner_id, kernel_name, subject_key in groups:
            trigger_event = (await db.execute(
                select(EvidenceEvent)
                .join(MemoryFact, MemoryFact.source_event_id == EvidenceEvent.id)
                .join(MemoryNode, MemoryNode.id == MemoryFact.node_id)
                .where(
                    MemoryNode.learner_id == learner_id,
                    MemoryNode.kernel_name == kernel_name,
                    MemoryNode.subject_key == subject_key,
                    MemoryFact.consumption_status == "eligible",
                )
                .order_by(EvidenceEvent.occurred_at.desc(), EvidenceEvent.id.desc())
                .limit(1)
            )).scalar_one_or_none()
            if trigger_event is None:
                continue
            run = await maybe_queue_synthesis(
                db,
                int(learner_id),
                str(kernel_name),
                str(subject_key),
                trigger_event=trigger_event,
            )
            if run is not None and run.status == "queued":
                actionable.add(int(run.id))
        await db.commit()
        return len(actionable)


async def _release_run(db: AsyncSession, run: MemorySynthesisRun, error: str) -> None:
    facts = (await db.execute(select(MemoryFact).where(
        MemoryFact.reservation_run_id == run.id,
    ))).scalars().all()
    for fact in facts:
        fact.consumption_status = "eligible"
        fact.reservation_run_id = None
    run.status = "failed"
    run.validation_errors = list(run.validation_errors or []) + [error]
    run.finished_at = datetime.utcnow()
    await db.commit()


async def process_synthesis_run(run_id: int) -> MemorySynthesisRun | None:
    """Reserve, synthesize and atomically commit one queued run."""
    async with async_session() as db:
        run = await db.get(MemorySynthesisRun, run_id)
        if not run or run.status != "queued" or run.due_at > datetime.utcnow():
            return run
        candidate_ids = [int(item) for item in (run.candidate_fact_ids or [])]
        delta_rows = (await db.execute(
            select(MemoryNode, MemoryFact, EvidenceEvent)
            .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
            .join(EvidenceEvent, EvidenceEvent.id == MemoryFact.source_event_id)
            .where(
                MemoryNode.id.in_(candidate_ids),
                MemoryNode.learner_id == run.learner_id,
                MemoryNode.kernel_name == run.kernel_name,
                MemoryNode.subject_key == run.subject_key,
                MemoryFact.consumption_status == "eligible",
            )
            .order_by(MemoryNode.occurred_at.asc(), MemoryNode.id.asc())
        )).all()
        if len(delta_rows) != len(candidate_ids):
            run.status = "stale"
            run.validation_errors = ["candidate_fact_unavailable"]
            run.finished_at = datetime.utcnow()
            await db.commit()
            return run
        current = await current_memory_module(
            db, run.learner_id, run.kernel_name, run.subject_key,
        )
        base_node, base_module = current if current else (None, None)
        base_fact_ids = await module_evidence_fact_ids(db, base_module) if base_module else []
        evidence_ids = _bounded_evidence_ids(base_fact_ids, candidate_ids)
        fingerprint = input_fingerprint(run.kernel_name, run.subject_key, evidence_ids)
        duplicate = (await db.execute(select(MemorySynthesisRun.id).where(
            MemorySynthesisRun.learner_id == run.learner_id,
            MemorySynthesisRun.input_fingerprint == fingerprint,
            MemorySynthesisRun.id != run.id,
        ))).scalar_one_or_none()
        if duplicate:
            run.status = "stale"
            run.validation_errors = ["version_input_already_synthesized"]
            run.finished_at = datetime.utcnow()
            await db.commit()
            return run
        run.base_module_node_id = base_node.id if base_node else None
        run.target_module_version = int(base_module.version or 1) + 1 if base_module else 1
        run.evidence_fact_ids = evidence_ids
        run.input_fingerprint = fingerprint
        run.prompt_version = "memory-synthesis-v2"
        rows = (await db.execute(
            select(MemoryNode, MemoryFact, EvidenceEvent)
            .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
            .join(EvidenceEvent, EvidenceEvent.id == MemoryFact.source_event_id)
            .where(
                MemoryNode.id.in_(evidence_ids),
                MemoryNode.learner_id == run.learner_id,
                MemoryNode.kernel_name == run.kernel_name,
                MemoryNode.subject_key == run.subject_key,
                MemoryFact.consumption_status.in_(["eligible", "consumed"]),
            )
            .order_by(MemoryNode.occurred_at.asc(), MemoryNode.id.asc())
        )).all()
        if len(rows) != len(evidence_ids):
            run.status = "stale"
            run.validation_errors = ["version_evidence_unavailable"]
            run.finished_at = datetime.utcnow()
            await db.commit()
            return run
        for _, fact, _ in delta_rows:
            fact.consumption_status = "reserved"
            fact.reservation_run_id = run.id
        run.status = "running"
        run.started_at = datetime.utcnow()
        run.attempt_count = (run.attempt_count or 0) + 1
        await db.commit()

    try:
        draft, model_name, usage = await _model_draft(run.kernel_name, run.subject_key, rows)
    except Exception as exc:
        # Consolidation must remain available offline and during provider
        # outages. The deterministic draft uses the exact same evidence
        # whitelist and still passes the validator below.
        draft = _deterministic_draft(run.kernel_name, run.subject_key, rows)
        model_name = "deterministic-fallback"
        usage = {"fallback_reason": type(exc).__name__}

    async with async_session() as db:
        run = await db.get(MemorySynthesisRun, run_id)
        if not run or run.status != "running":
            return run
        evidence_ids = [int(item) for item in (run.evidence_fact_ids or [])]
        rows = (await db.execute(
            select(MemoryNode, MemoryFact, EvidenceEvent)
            .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
            .join(EvidenceEvent, EvidenceEvent.id == MemoryFact.source_event_id)
            .where(
                MemoryNode.id.in_(evidence_ids),
                MemoryNode.learner_id == run.learner_id,
                MemoryNode.kernel_name == run.kernel_name,
                MemoryNode.subject_key == run.subject_key,
                MemoryFact.consumption_status.in_(["reserved", "consumed"]),
            )
            .order_by(MemoryNode.occurred_at.asc(), MemoryNode.id.asc())
        )).all()
        if len(rows) != len(evidence_ids):
            await _release_run(db, run, "version_evidence_changed")
            return run
        errors = _validate_draft(run, draft, rows)
        if errors:
            run.raw_output = draft.model_dump(mode="json")
            run.validation_errors = errors
            await _release_run(db, run, "validation_rejected")
            return run

        fact_nodes = [node for node, _, _ in rows]
        time_start = min(node.occurred_at for node in fact_nodes)
        time_end = max(node.occurred_at for node in fact_nodes)
        confidence = round(sum(node.confidence or 0 for node in fact_nodes) / len(fact_nodes), 3)
        project_ids = {fact.project_id for _, fact, _ in rows if fact.project_id is not None}
        checkpoint_ids = {fact.checkpoint_id for _, fact, _ in rows if fact.checkpoint_id is not None}
        session_ids = {fact.session_id for _, fact, _ in rows if fact.session_id is not None}
        subject_type, subject_id = subject_parts(run.subject_key)
        project_id = next(iter(project_ids)) if len(project_ids) == 1 else None
        checkpoint_id = next(iter(checkpoint_ids)) if len(checkpoint_ids) == 1 else None
        session_id = next(iter(session_ids)) if len(session_ids) == 1 else None
        relation = "SUPERSEDES" if run.trigger_reason == "correction" else "REFINES"
        previous_modules = (await db.execute(
            select(MemoryNode)
            .join(MemoryModule, MemoryModule.node_id == MemoryNode.id)
            .where(
                MemoryNode.learner_id == run.learner_id,
                MemoryNode.kernel_name == run.kernel_name,
                MemoryNode.subject_key == run.subject_key,
                MemoryNode.id == run.base_module_node_id,
            )
        )).scalars().all()
        for previous in previous_modules:
            previous.status = "superseded" if relation == "SUPERSEDES" else "refined"
            old_claims = (await db.execute(
                select(MemoryNode)
                .join(MemoryClaim, MemoryClaim.node_id == MemoryNode.id)
                .where(MemoryClaim.module_node_id == previous.id)
            )).scalars().all()
            for old_claim in old_claims:
                old_claim.status = previous.status
        await db.flush()
        module_node = MemoryNode(
            learner_id=run.learner_id,
            node_type="module",
            kernel_name=run.kernel_name,
            memory_kind="topic_summary",
            subject_key=run.subject_key,
            subject_type=subject_type,
            subject_id=subject_id,
            project_id=project_id,
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            text=draft.summary,
            payload={
                "trigger_reason": run.trigger_reason,
                "project_id": project_id,
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "module_version": run.target_module_version,
                "parent_module_node_id": run.base_module_node_id,
                "evidence_fact_ids": evidence_ids,
                "delta_fact_ids": [int(item) for item in (run.candidate_fact_ids or [])],
                "policy_version": MODULE_VERSION_POLICY,
            },
            confidence=confidence,
            salience=memory_salience(
                memory_kind="topic_summary", evidence_grade="observed",
                scope="long_term", confidence=confidence,
            ),
            schema_version=MEMORY_SCHEMA_VERSION,
            status="active",
            valid_from=time_start,
            occurred_at=time_end,
        )
        db.add(module_node)
        await db.flush()
        module_type = (
            "correction" if run.trigger_reason == "correction"
            else "confirmation" if run.trigger_reason == "confirmation"
            else "synthesis"
        )
        revision_kind = (
            "correction" if run.trigger_reason == "correction"
            else "confirmation" if run.trigger_reason == "confirmation"
            else "initial" if run.base_module_node_id is None
            else "refinement"
        )
        db.add(MemoryModule(
            node_id=module_node.id,
            synthesis_run_id=run.id,
            module_type=module_type,
            summary=draft.summary,
            time_start=time_start,
            time_end=time_end,
            input_fingerprint=run.input_fingerprint,
            immutable=True,
            version=run.target_module_version,
            parent_module_node_id=run.base_module_node_id,
            revision_kind=revision_kind,
            evidence_fact_ids=evidence_ids,
            delta_fact_ids=[int(item) for item in (run.candidate_fact_ids or [])],
            policy_version=MODULE_VERSION_POLICY,
        ))
        await db.flush()

        allowed_rows = {node.id: (node, fact, event) for node, fact, event in rows}
        for ordinal, claim in enumerate(draft.claims):
            claim_rows = [allowed_rows[item] for item in claim.evidence_fact_ids]
            claim_confidence = min(item[0].confidence or 0 for item in claim_rows)
            verified = all(item[1].evidence_grade == "verified" for item in claim_rows)
            claim_node = MemoryNode(
                learner_id=run.learner_id,
                node_type="claim",
                kernel_name=run.kernel_name,
                memory_kind="semantic_claim",
                subject_key=run.subject_key,
                subject_type=subject_type,
                subject_id=subject_id,
                project_id=project_id,
                checkpoint_id=checkpoint_id,
                session_id=session_id,
                text=claim.text,
                payload={
                    "project_id": project_id,
                    "checkpoint_id": checkpoint_id,
                    "session_id": session_id,
                    "evidence_fact_ids": claim.evidence_fact_ids,
                    "module_version": run.target_module_version,
                },
                confidence=claim_confidence,
                salience=memory_salience(
                    memory_kind="semantic_claim",
                    evidence_grade="verified" if verified else "observed",
                    scope="long_term", confidence=claim_confidence,
                ),
                schema_version=MEMORY_SCHEMA_VERSION,
                status="active",
                valid_from=time_start,
                occurred_at=time_end,
            )
            db.add(claim_node)
            await db.flush()
            db.add(MemoryClaim(
                node_id=claim_node.id,
                module_node_id=module_node.id,
                claim_ordinal=ordinal,
                predicate=claim.predicate,
                value=claim.value,
                verification_status="verified" if verified else "supported",
            ))
            await db.flush()
            for fact_id in claim.evidence_fact_ids:
                await _add_edge(
                    db, learner_id=run.learner_id, source_node_id=fact_id,
                    target_node_id=claim_node.id, relation_type="SUPPORTS",
                    origin="synthesis", confidence=claim_confidence,
                )

        delta_ids = {int(item) for item in (run.candidate_fact_ids or [])}
        for node, fact, _ in rows:
            await _add_edge(
                db, learner_id=run.learner_id, source_node_id=node.id,
                target_node_id=module_node.id, relation_type="CONSOLIDATED_INTO",
                origin="synthesis", confidence=node.confidence or 0,
            )
            if node.id in delta_ids:
                fact.consumption_status = "consumed"
                fact.consumed_by_module_id = module_node.id
                fact.reservation_run_id = None

        for previous in previous_modules:
            await _add_edge(
                db, learner_id=run.learner_id, source_node_id=module_node.id,
                target_node_id=previous.id, relation_type=relation,
                origin="post_synthesis", confidence=confidence,
            )

        run.status = "completed"
        run.model_name = model_name
        run.raw_output = draft.model_dump(mode="json")
        run.validation_errors = []
        run.usage = usage
        run.finished_at = datetime.utcnow()
        await rebuild_kernel_long_term_from_modules(db, run.learner_id)
        await refresh_kernel_head(db, run.learner_id, run.kernel_name)
        await db.commit()
        return run


async def process_due_runs(limit: int = 4) -> int:
    async with async_session() as db:
        run_ids = list((await db.execute(select(MemorySynthesisRun.id).where(
            MemorySynthesisRun.status == "queued",
            MemorySynthesisRun.due_at <= datetime.utcnow(),
        ).order_by(MemorySynthesisRun.due_at.asc(), MemorySynthesisRun.id.asc()).limit(limit))).scalars().all())
    for run_id in run_ids:
        await process_synthesis_run(run_id)
    return len(run_ids)


async def memory_worker_loop(stop_event: asyncio.Event) -> None:
    await recover_interrupted_runs()
    if not settings.memory_auto_synthesis_enabled:
        await stop_event.wait()
        return
    await reconcile_eligible_synthesis_runs()
    while not stop_event.is_set():
        try:
            processed = await process_due_runs()
            timeout = 0.25 if processed else 1.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[memory-worker] {type(exc).__name__}: {exc}")
            timeout = 2.0
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
