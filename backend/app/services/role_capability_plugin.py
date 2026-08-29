"""Deterministic Role Capability Graph plugin runtime.

The design is adapted from the observable invariants of the Role Atlas
reference repository, but is implemented against LearnFlow's own project,
source, Action Board and evidence contracts. Generated role artifacts are
domain objects, never learner-state or mastery evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role_capability import (
    RoleCapabilityPackage, RoleCapabilityRun, RoleCapabilitySnapshot,
)


PROTOCOL_VERSION = "learnflow.role-capability.v1"
MAX_TASKS = 12
MAX_EXPLAIN_RESULTS = 8


def _compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _slug(value: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:48]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _stable_id(kind: str, label: str) -> str:
    digest = hashlib.sha256(f"{kind}:{label.strip().lower()}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sentences(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in re.split(r"[\n。！？!?；;]+", value):
            text = re.sub(r"^[\s\-–—*•\d.、()（）]+", "", item).strip()
            if len(text) < 6 or len(text) > 180:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
    return result


def _task_label(text: str) -> str:
    text = _compact(text, 72)
    match = re.search(
        r"(?:负责|完成|开展|执行|设计|开发|分析|维护|管理|构建|优化|验证|交付|制定|协调|监控)(.{2,58})",
        text,
    )
    return _compact(match.group(0) if match else text, 72)


def _knowledge_label(task: str) -> str:
    cleaned = re.sub(
        r"^(?:负责|完成|开展|执行|设计|开发|分析|维护|管理|构建|优化|验证|交付|制定|协调|监控)",
        "", task,
    ).strip(" ：:,，")
    return _compact(f"{cleaned[:36]}的原理、约束与质量标准", 72)


def build_generation_contract(role_title: str, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "objective": f"为“{role_title}”形成可解释、可迭代的任务—能力—知识技能岗位包",
        "source_policy": [
            "只使用本次固定的项目来源版本或用户显式任务种子",
            "推断节点必须保留 inferred 认识状态，不能伪装成来源直接事实",
            "岗位包不是学习者画像，生成结果不写五核",
        ],
        "budgets": {"max_tasks": MAX_TASKS, "max_sources": 20, "max_text_chars": 24_000},
        "stop_conditions": ["没有可承担岗位事实的来源或任务种子", "协议校验失败"],
        "source_refs": source_refs,
    }


def compile_role_graph(
    *, role_title: str, role_summary: str = "", task_seeds: list[str],
    source_refs: list[dict[str, Any]], source_texts: list[Any],
) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    candidates.extend((item, "user:task-seed") for item in _sentences(task_seeds))
    for index, source_text in enumerate(source_texts):
        if isinstance(source_text, dict):
            text = str(source_text.get("text") or "")
            evidence_ref = str(source_text.get("ref") or "source:unbound")
        else:
            text = str(source_text)
            evidence_ref = str(source_refs[min(index, len(source_refs) - 1)]["ref"]) if source_refs else "source:unbound"
        candidates.extend((item, evidence_ref) for item in _sentences([text]))
    tasks: list[tuple[str, str]] = []
    seen_tasks: set[str] = set()
    for sentence, evidence_ref in candidates:
        task = _task_label(sentence)
        if not task or task in seen_tasks:
            continue
        seen_tasks.add(task)
        tasks.append((task, evidence_ref))
        if len(tasks) >= MAX_TASKS:
            break
    if not tasks:
        raise ValueError("岗位包生成至少需要一个显式任务种子或已处理的项目来源")

    role_id = _stable_id("role", role_title)
    nodes: list[dict[str, Any]] = [{
        "id": role_id, "type": "role", "label": _compact(role_title, 120),
        "summary": _compact(role_summary or f"{role_title}岗位能力边界", 360),
        "lifecycle": "accepted", "knowledge_state": "documented_norm",
        "evidence_refs": [item["ref"] for item in source_refs],
    }]
    edges: list[dict[str, Any]] = []
    for task, evidence_ref in tasks:
        task_id = _stable_id("task", task)
        capability_label = _compact(f"能够{task}", 80)
        capability_id = _stable_id("capability", capability_label)
        knowledge_label = _knowledge_label(task)
        knowledge_id = _stable_id("knowledge_skill", knowledge_label)
        state = "documented_norm" if source_refs else "inferred_pattern"
        for node_id, node_type, label, summary in (
            (task_id, "task", task, f"岗位在真实情境中需要完成：{task}"),
            (capability_id, "capability", capability_label, f"完成“{task}”所需的可观察能力。"),
            (knowledge_id, "knowledge_skill", knowledge_label, f"支撑“{task}”的知识与技能边界。"),
        ):
            if not any(item["id"] == node_id for item in nodes):
                nodes.append({
                    "id": node_id, "type": node_type, "label": label,
                    "summary": summary, "lifecycle": "candidate",
                    "knowledge_state": state, "evidence_refs": [evidence_ref],
                })
        for relation, source, target in (
            ("owns_task", role_id, task_id),
            ("requires_capability", task_id, capability_id),
            ("requires_knowledge_skill", capability_id, knowledge_id),
        ):
            edge_id = _stable_id("edge", f"{relation}:{source}:{target}")
            if not any(item["id"] == edge_id for item in edges):
                edges.append({
                    "id": edge_id, "type": relation, "source": source, "target": target,
                    "lifecycle": "candidate", "evidence_refs": [evidence_ref],
                })
    return {
        "protocol_version": PROTOCOL_VERSION,
        "role": {"id": role_id, "title": _compact(role_title, 120)},
        "nodes": nodes,
        "edges": edges,
        "views": [
            {"id": "role-overview", "label": "岗位总览", "node_types": ["role", "task", "capability"]},
            {"id": "learning-projection", "label": "学习投影", "node_types": ["task", "capability", "knowledge_skill"]},
        ],
    }


def inspect_role_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    ids = [str(item.get("id") or "") for item in nodes]
    id_set = set(ids)
    errors: list[str] = []
    warnings: list[str] = []
    if graph.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("unsupported_protocol_version")
    if len(ids) != len(id_set) or "" in id_set:
        errors.append("invalid_or_duplicate_node_id")
    dangling = [item.get("id") for item in edges if item.get("source") not in id_set or item.get("target") not in id_set]
    if dangling:
        errors.append("dangling_edge:" + ",".join(map(str, dangling[:8])))
    counts = {kind: sum(1 for item in nodes if item.get("type") == kind) for kind in ("role", "task", "capability", "knowledge_skill")}
    for kind in ("role", "task", "capability", "knowledge_skill"):
        if counts[kind] == 0:
            errors.append(f"missing_{kind}")
    unsupported = [item["id"] for item in nodes if item.get("type") != "role" and not item.get("evidence_refs")]
    if unsupported:
        warnings.append(f"nodes_without_evidence:{len(unsupported)}")
    task_targets = {item.get("target") for item in edges if item.get("type") == "owns_task"}
    uncovered_tasks = [item["id"] for item in nodes if item.get("type") == "task" and item["id"] not in task_targets]
    if uncovered_tasks:
        warnings.append(f"unreachable_tasks:{len(uncovered_tasks)}")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {"nodes": len(nodes), "edges": len(edges), **counts},
        "agent_probes": {
            "graph_traversal": not dangling and counts["task"] > 0,
            "evidence_resolution": not unsupported,
            "learning_projection": counts["capability"] > 0 and counts["knowledge_skill"] > 0,
        },
    }


def explain_role_graph(graph: dict[str, Any], query: str) -> dict[str, Any]:
    """Bounded explain-agent projection pinned to one immutable snapshot."""
    terms = [item.lower() for item in re.findall(r"[\w\u4e00-\u9fff]{2,}", query)]
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    ranked = sorted(nodes, key=lambda item: sum(term in f"{item.get('label', '')} {item.get('summary', '')}".lower() for term in terms), reverse=True)
    selected = [item for item in ranked if not terms or any(term in f"{item.get('label', '')} {item.get('summary', '')}".lower() for term in terms)][:MAX_EXPLAIN_RESULTS]
    if not selected:
        selected = ranked[:4]
    selected_ids = {item["id"] for item in selected}
    neighbor_ids = {
        endpoint for edge in edges if edge.get("source") in selected_ids or edge.get("target") in selected_ids
        for endpoint in (edge.get("source"), edge.get("target"))
    }
    context = [item for item in nodes if item.get("id") in neighbor_ids][:MAX_EXPLAIN_RESULTS]
    citations = sorted({ref for item in context for ref in item.get("evidence_refs", [])})
    return {
        "query": _compact(query, 500),
        "answer": "；".join(f"{item['label']}：{item.get('summary', '')}" for item in selected[:4]),
        "objects": context,
        "relations": [item for item in edges if item.get("source") in neighbor_ids and item.get("target") in neighbor_ids][:12],
        "citations": citations,
        "coverage": {"requested": len(terms), "returned": len(selected), "partial": len(context) >= MAX_EXPLAIN_RESULTS},
        "authority": "immutable_role_capability_snapshot",
        "mastery_unchanged": True,
    }


def build_iteration_contract(objective: str, target_ids: list[str], base_snapshot_id: int) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "base_snapshot_id": base_snapshot_id,
        "objective": _compact(objective, 600),
        "target_ids": target_ids[:40],
        "budgets": {"max_operations": 24, "max_targets": 40, "max_rounds": 1},
        "acceptance_policy": ["协议无硬错误", "至少一个语义变化", "稳定 ID 不被静默改写"],
        "stop_conditions": ["没有有效操作", "出现悬空引用", "删除岗位根节点"],
    }


def apply_iteration(graph: dict[str, Any], operations: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = deepcopy(graph)
    nodes = candidate.setdefault("nodes", [])
    edges = candidate.setdefault("edges", [])
    changes: list[dict[str, Any]] = []
    for operation in operations[:24]:
        op = str(operation.get("op") or "")
        if op == "add_node":
            node_type = str(operation.get("type") or "")
            label = _compact(operation.get("label"), 100)
            if node_type not in {"task", "capability", "knowledge_skill"} or not label:
                continue
            node_id = _stable_id(node_type, label)
            if any(item.get("id") == node_id for item in nodes):
                continue
            evidence_refs = [_compact(item, 180) for item in operation.get("evidence_refs", []) if _compact(item, 180)]
            nodes.append({
                "id": node_id, "type": node_type, "label": label,
                "summary": _compact(operation.get("summary") or label, 360),
                "lifecycle": "candidate", "knowledge_state": "inferred_pattern",
                "evidence_refs": evidence_refs or ["user:iteration-proposal"],
            })
            parent_id = _compact(operation.get("parent_id"), 180)
            relation = {"task": "owns_task", "capability": "requires_capability", "knowledge_skill": "requires_knowledge_skill"}[node_type]
            if parent_id:
                edges.append({
                    "id": _stable_id("edge", f"{relation}:{parent_id}:{node_id}"),
                    "type": relation, "source": parent_id, "target": node_id,
                    "lifecycle": "candidate", "evidence_refs": evidence_refs or ["user:iteration-proposal"],
                })
            changes.append({"op": op, "id": node_id, "label": label})
        elif op == "update_node":
            target_id = _compact(operation.get("target_id"), 180)
            target = next((item for item in nodes if item.get("id") == target_id), None)
            if not target:
                continue
            before = {"summary": target.get("summary"), "lifecycle": target.get("lifecycle")}
            if operation.get("summary"):
                target["summary"] = _compact(operation["summary"], 360)
            if target.get("type") != "role" and operation.get("lifecycle") in {"accepted", "candidate", "deprecated"}:
                target["lifecycle"] = operation["lifecycle"]
            if operation.get("evidence_refs"):
                target["evidence_refs"] = list(dict.fromkeys([*target.get("evidence_refs", []), *operation["evidence_refs"]]))[:20]
            after = {"summary": target.get("summary"), "lifecycle": target.get("lifecycle")}
            if before != after or operation.get("evidence_refs"):
                changes.append({"op": op, "id": target_id, "before": before, "after": after})
    return candidate, {"meaningful": bool(changes), "changes": changes, "change_count": len(changes)}


async def current_package(db: AsyncSession, learner_id: int, project_id: int) -> RoleCapabilityPackage | None:
    return (await db.execute(select(RoleCapabilityPackage).where(
        RoleCapabilityPackage.learner_id == learner_id,
        RoleCapabilityPackage.project_id == project_id,
    ))).scalar_one_or_none()


async def current_snapshot(db: AsyncSession, package: RoleCapabilityPackage) -> RoleCapabilitySnapshot | None:
    return await db.get(RoleCapabilitySnapshot, package.current_snapshot_id) if package.current_snapshot_id else None


async def create_snapshot(
    db: AsyncSession, package: RoleCapabilityPackage, graph: dict[str, Any],
    source_refs: list[dict[str, Any]], provenance: dict[str, Any], parent_snapshot_id: int | None = None,
) -> RoleCapabilitySnapshot:
    validation = inspect_role_graph(graph)
    if not validation["valid"]:
        raise ValueError("岗位图谱协议校验失败：" + ", ".join(validation["errors"]))
    version = int((await db.execute(select(func.max(RoleCapabilitySnapshot.version)).where(
        RoleCapabilitySnapshot.package_id == package.id,
    ))).scalar_one_or_none() or 0) + 1
    root_hash = _canonical_hash({"graph": graph, "source_refs": source_refs})
    existing = (await db.execute(select(RoleCapabilitySnapshot).where(
        RoleCapabilitySnapshot.package_id == package.id,
        RoleCapabilitySnapshot.root_hash == root_hash,
    ))).scalar_one_or_none()
    if existing:
        package.current_snapshot_id = existing.id
        return existing
    snapshot = RoleCapabilitySnapshot(
        package_id=package.id, parent_snapshot_id=parent_snapshot_id,
        version=version, snapshot_key=f"role-snapshot:{package.id}:v{version}:{root_hash[:12]}",
        root_hash=root_hash, role_title=package.role_title, graph=graph,
        source_refs=source_refs, validation=validation, provenance=provenance,
    )
    db.add(snapshot)
    await db.flush()
    package.current_snapshot_id = snapshot.id
    package.status = "ready"
    package.updated_at = datetime.utcnow()
    return snapshot


def package_view(package: RoleCapabilityPackage, snapshot: RoleCapabilitySnapshot | None, *, include_graph: bool = True) -> dict[str, Any]:
    return {
        "plugin": "role_capability_graph",
        "protocol_version": package.policy_version,
        "package": {
            "id": package.id, "project_id": package.project_id, "role_title": package.role_title,
            "status": package.status, "current_snapshot_id": package.current_snapshot_id,
        },
        "snapshot": None if not snapshot else {
            "id": snapshot.id, "snapshot_key": snapshot.snapshot_key, "version": snapshot.version,
            "root_hash": snapshot.root_hash, "status": snapshot.status,
            "graph": snapshot.graph if include_graph else {}, "source_refs": snapshot.source_refs,
            "validation": snapshot.validation, "provenance": snapshot.provenance,
            "created_at": snapshot.created_at.isoformat(),
        },
        "authority": "role artifacts are domain supply; they never mutate five-kernel learner state",
    }
