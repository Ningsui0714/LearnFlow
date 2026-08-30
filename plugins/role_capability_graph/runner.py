#!/usr/bin/env python3
"""Portable JSON-RPC runner for the official Role Capability Graph plugin.

Only Python's standard library is used.  The host owns authorization, source
scope, model credentials, validation and snapshot commit; this process only
returns a candidate result.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import sys
from typing import Any, Iterable


PROTOCOL = "learnflow.plugin-rpc.v1"
OBJECT_SCHEMA = "role-capability.object.v1"
MAX_TASKS = 12
MAX_RESULTS = 8
_call_sequence = 0


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("host_closed_rpc_stream")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise RuntimeError("rpc_message_must_be_object")
    return value


def _host_call(port: str, input_value: dict[str, Any]) -> Any:
    global _call_sequence
    _call_sequence += 1
    call_id = f"call-{_call_sequence}"
    _emit({
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "host.call",
        "params": {"port": port, "input": input_value},
    })
    response = _read()
    if response.get("id") != call_id:
        raise RuntimeError("host_port_response_id_mismatch")
    if response.get("error"):
        error = response["error"]
        raise RuntimeError(f"host_port_error:{error.get('code')}:{error.get('message')}")
    return response.get("result")


def _compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


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
        for item in re.split(r"[\n。！？!?；;]+", str(value or "")):
            text = re.sub(r"^[\s\-–—*•\d.、()（）]+", "", item).strip()
            if not 6 <= len(text) <= 180 or text.casefold() in seen:
                continue
            seen.add(text.casefold())
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
        "",
        task,
    ).strip(" ：:,，")
    return _compact(f"{cleaned[:36]}的原理、约束与质量标准", 72)


def _source_material(input_value: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    requested = [int(item) for item in input_value.get("source_ids", []) if str(item).isdigit()][:20]
    response = _host_call(
        "source.read.v1",
        {"source_ids": requested, "max_sources": 20, "max_chunks": 24, "max_chars": 24000},
    )
    sources = list((response or {}).get("sources") or []) if isinstance(response, dict) else []
    refs: list[dict[str, Any]] = []
    texts: list[tuple[str, str]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        ref = {
            "ref": str(source.get("ref") or ""),
            "source_id": source.get("source_id"),
            "source_version_id": source.get("source_version_id"),
            "content_hash": str(source.get("content_hash") or ""),
            "authority_tier": str(source.get("authority_tier") or "learner_owned"),
            "status": str(source.get("status") or "active"),
        }
        refs.append(ref)
        fixed_ref = str(ref.get("ref") or "source:unbound")
        for chunk in list(source.get("chunks") or []):
            if isinstance(chunk, dict):
                texts.append((str(chunk.get("content") or chunk.get("text") or "")[:2000], fixed_ref))
            else:
                texts.append((str(chunk)[:2000], fixed_ref))
    return refs, texts


def _compile_graph(
    role_title: str,
    role_summary: str,
    task_seeds: list[str],
    source_refs: list[dict[str, Any]],
    source_texts: list[tuple[str, str]],
    max_tasks: int = MAX_TASKS,
) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    candidates.extend((item, "user:task-seed") for item in _sentences(task_seeds))
    for text, fixed_ref in source_texts:
        candidates.extend((item, fixed_ref) for item in _sentences([text]))
    tasks: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sentence, evidence_ref in candidates:
        label = _task_label(sentence)
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        tasks.append((label, evidence_ref))
        if len(tasks) >= max(1, min(int(max_tasks), 40)):
            break
    if not tasks:
        raise ValueError("generation_requires_source_or_explicit_task_seed")

    role_id = _stable_id("role", role_title)
    nodes: list[dict[str, Any]] = [{
        "id": role_id,
        "type": "role",
        "label": _compact(role_title, 120),
        "summary": _compact(role_summary or f"{role_title}岗位能力边界", 360),
        "lifecycle": "accepted",
        "knowledge_state": "documented_norm",
        "evidence_refs": [str(item.get("ref") or "") for item in source_refs if item.get("ref")],
    }]
    edges: list[dict[str, Any]] = []
    for task, evidence_ref in tasks:
        task_id = _stable_id("task", task)
        capability_label = _compact(f"能够{task}", 80)
        capability_id = _stable_id("capability", capability_label)
        knowledge_label = _knowledge_label(task)
        knowledge_id = _stable_id("knowledge_skill", knowledge_label)
        state = "documented_norm" if source_refs else "inferred_pattern"
        for node_id, kind, label, summary in (
            (task_id, "task", task, f"岗位在真实情境中需要完成：{task}"),
            (capability_id, "capability", capability_label, f"完成“{task}”所需的可观察能力。"),
            (knowledge_id, "knowledge_skill", knowledge_label, f"支撑“{task}”的知识与技能边界。"),
        ):
            nodes.append({
                "id": node_id,
                "type": kind,
                "label": label,
                "summary": summary,
                "lifecycle": "candidate",
                "knowledge_state": state,
                "evidence_refs": [evidence_ref],
            })
        for relation, source, target in (
            ("owns_task", role_id, task_id),
            ("requires_capability", task_id, capability_id),
            ("requires_knowledge_skill", capability_id, knowledge_id),
        ):
            edges.append({
                "id": _stable_id("edge", f"{relation}:{source}:{target}"),
                "type": relation,
                "object_type": "semantic_edge",
                "source": source,
                "target": target,
                "lifecycle": "candidate",
                "evidence_refs": [evidence_ref],
            })
    return {
        "protocol_version": "learnflow.role-capability.v1",
        "role": {"id": role_id, "title": _compact(role_title, 120)},
        "nodes": nodes,
        "edges": edges,
        "views": [
            {"id": "role-overview", "label": "岗位总览", "node_types": ["role", "task", "capability"]},
            {"id": "learning-projection", "label": "学习投影", "node_types": ["task", "capability", "knowledge_skill"]},
        ],
    }


def _inspect(
    graph: dict[str, Any],
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    ids = [str(item.get("id") or "") for item in nodes]
    id_set = set(ids)
    errors: list[str] = []
    warnings: list[str] = []
    if len(ids) != len(id_set) or "" in id_set:
        errors.append("invalid_or_duplicate_node_id")
    dangling = [item.get("id") for item in edges if item.get("source") not in id_set or item.get("target") not in id_set]
    if dangling:
        errors.append("dangling_edge:" + ",".join(map(str, dangling[:8])))
    declared_node_types = {"role", "task", "capability", "knowledge_skill"}
    invalid_types = [item.get("id") for item in nodes if item.get("type") not in declared_node_types]
    if invalid_types:
        errors.append("unsupported_node_type:" + ",".join(map(str, invalid_types[:8])))
    node_by_id = {str(item.get("id") or ""): item for item in nodes}
    relation_contracts = {
        "owns_task": ("role", "task"),
        "requires_capability": ("task", "capability"),
        "requires_knowledge_skill": ("capability", "knowledge_skill"),
    }
    invalid_relations: list[str] = []
    for edge in edges:
        source = node_by_id.get(str(edge.get("source") or ""), {})
        target = node_by_id.get(str(edge.get("target") or ""), {})
        expected = relation_contracts.get(str(edge.get("type") or ""))
        if not expected or (source.get("type"), target.get("type")) != expected:
            invalid_relations.append(str(edge.get("id") or ""))
    if invalid_relations:
        errors.append("invalid_semantic_relation:" + ",".join(invalid_relations[:8]))
    counts = {
        kind: sum(1 for item in nodes if item.get("type") == kind)
        for kind in ("role", "task", "capability", "knowledge_skill")
    }
    for kind, count in counts.items():
        if not count:
            errors.append(f"missing_{kind}")
    admitted_source_refs = {
        str(item.get("ref") or "") for item in list(source_refs or []) if isinstance(item, dict)
    }
    unsupported = [item["id"] for item in nodes if item.get("type") != "role" and not item.get("evidence_refs")]
    if unsupported:
        errors.append(f"nodes_without_evidence:{len(unsupported)}")
    unknown_evidence = sorted({
        str(ref)
        for item in [*nodes, *edges]
        for ref in list(item.get("evidence_refs") or [])
        if not str(ref).startswith("user:") and str(ref) not in admitted_source_refs
    })
    if unknown_evidence:
        errors.append("unresolved_evidence_ref:" + ",".join(unknown_evidence[:8]))
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {"nodes": len(nodes), "edges": len(edges), **counts},
        "agent_probes": {
            "graph_traversal": not dangling and counts["task"] > 0,
            "evidence_resolution": not unsupported,
            "learning_projection": counts["capability"] > 0 and counts["knowledge_skill"] > 0,
            "process_semantic_bridge": counts["task"] > 0,
        },
    }


def _snapshot(
    graph: dict[str, Any],
    source_refs: list[dict[str, Any]],
    provenance: dict[str, Any],
    *,
    include_process_view: bool = True,
) -> dict[str, Any]:
    validation = _inspect(graph, source_refs)
    if not validation["valid"]:
        raise ValueError("candidate_protocol_invalid:" + ",".join(validation["errors"]))
    tasks = [item for item in graph["nodes"] if item.get("type") == "task"]
    role_id = str(graph["role"]["id"])
    actor = {
        "id": _stable_id("actor", role_id), "type": "actor", "label": graph["role"]["title"],
        "summary": "承担岗位过程责任的角色。", "lifecycle": "accepted", "evidence_refs": [],
    }
    process_events: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    work_objects: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for order, task in enumerate(tasks, start=1):
        event_id = _stable_id("process_event", task["id"])
        scenario_id = _stable_id("scenario", task["id"])
        object_id = _stable_id("work_object", task["id"])
        process_events.append({
            "id": event_id, "type": "process_event", "label": task["label"], "order": order,
            "actor_id": actor["id"], "task_id": task["id"], "work_object_id": object_id,
            "lifecycle": task.get("lifecycle", "candidate"), "evidence_refs": task.get("evidence_refs", []),
        })
        scenarios.append({
            "id": scenario_id, "type": "scenario", "label": f"{task['label']}场景",
            "event_ids": [event_id], "lifecycle": "candidate", "evidence_refs": task.get("evidence_refs", []),
        })
        work_objects.append({
            "id": object_id, "type": "work_object", "label": f"{task['label']}输入与产物",
            "lifecycle": "candidate", "evidence_refs": task.get("evidence_refs", []),
        })
        bridges.append({
            "id": _stable_id("bridge", f"{task['id']}:{event_id}"), "type": "bridge",
            "label": "任务—过程桥", "semantic_object_id": task["id"], "process_event_id": event_id,
            "lifecycle": "candidate", "evidence_refs": task.get("evidence_refs", []),
        })
        claims.append({
            "id": _stable_id("claim", task["id"]), "type": "claim", "label": task["label"],
            "statement": task.get("summary", ""), "subject_id": task["id"],
            "lifecycle": "candidate", "evidence_refs": task.get("evidence_refs", []),
        })
    semantic_graph = deepcopy(graph)
    for edge in semantic_graph["edges"]:
        # ``type`` remains the graph relation. ``object_type`` lets the host
        # index the exact object without replacing or copying domain truth.
        edge["object_type"] = "semantic_edge"
    component_values: dict[str, Any] = {
        "evidence": {"sources": source_refs, "claims": claims},
        "semantic-graph": semantic_graph,
        "process-forest": {
            "actors": [actor], "scenarios": scenarios, "events": process_events,
            "work_objects": work_objects, "bridges": bridges,
        },
        "views": {
            "views": [
                *list(graph.get("views", [])),
                *([{
                    "id": "process-bridge",
                    "label": "岗位过程桥",
                    "node_types": ["process_event", "scenario", "work_object", "bridge"],
                }] if include_process_view else []),
            ]
        },
        "retrieval-index": {
            "entries": [
                {"object_id": item["id"], "text": _compact(f"{item.get('label', '')} {item.get('summary', '')}", 500)}
                for item in semantic_graph["nodes"]
            ]
        },
        "validation-report": validation,
        "reference-migrations": {"mappings": [], "policy": "stable_ids_are_not_silently_rewritten"},
    }
    bridge_errors = [
        item["id"] for item in bridges
        if item.get("semantic_object_id") not in {task["id"] for task in tasks}
        or item.get("process_event_id") not in {event["id"] for event in process_events}
    ]
    if len(process_events) != len(tasks) or len(bridges) != len(tasks) or bridge_errors:
        validation["valid"] = False
        validation["errors"] = [
            *list(validation.get("errors") or []),
            "invalid_process_semantic_bridge",
        ]
        raise ValueError("candidate_protocol_invalid:invalid_process_semantic_bridge")
    objects: list[dict[str, Any]] = []
    locations = (
        ("semantic-graph", "nodes", semantic_graph["nodes"]),
        ("semantic-graph", "edges", semantic_graph["edges"]),
        ("evidence", "claims", claims),
        ("process-forest", "actors", [actor]),
        ("process-forest", "scenarios", scenarios),
        ("process-forest", "events", process_events),
        ("process-forest", "work_objects", work_objects),
        ("process-forest", "bridges", bridges),
    )
    for component, collection, values in locations:
        for index, item in enumerate(values):
            objects.append({
                "id": item["id"],
                "type": str(item.get("object_type") or item["type"]),
                "label": str(item.get("label") or item.get("type") or ""),
                "component": component,
                "json_pointer": f"/{collection}/{index}",
                "content_hash": _canonical_hash(item),
                "lifecycle": str(item.get("lifecycle") or "active"),
                "references": list(
                    item.get("references")
                    or ([item.get("source"), item.get("target")] if item.get("object_type") == "semantic_edge" else [])
                ),
            })
    return {
        "schema_version": OBJECT_SCHEMA,
        "components": component_values,
        "objects": objects,
        "source_refs": source_refs,
        "validation": validation,
        "provenance": {**provenance, "mastery_unchanged": True},
    }


def _graph_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    components = dict(snapshot.get("components") or {})
    graph = components.get("semantic-graph") or snapshot.get("graph") or {}
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("snapshot_semantic_graph_missing")
    return deepcopy(graph)


def _apply_iteration(graph: dict[str, Any], operations: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = deepcopy(graph)
    nodes = candidate.setdefault("nodes", [])
    edges = candidate.setdefault("edges", [])
    changes: list[dict[str, Any]] = []
    for operation in operations[:24]:
        op = str(operation.get("op") or "")
        if op == "add_node":
            kind = str(operation.get("type") or "")
            label = _compact(operation.get("label"), 100)
            if kind not in {"task", "capability", "knowledge_skill"} or not label:
                continue
            node_id = _stable_id(kind, label)
            if any(item.get("id") == node_id for item in nodes):
                continue
            refs = [_compact(item, 180) for item in operation.get("evidence_refs", []) if _compact(item, 180)]
            nodes.append({
                "id": node_id, "type": kind, "label": label,
                "summary": _compact(operation.get("summary") or label, 360),
                "lifecycle": "candidate", "knowledge_state": "inferred_pattern",
                "evidence_refs": refs or ["user:iteration-proposal"],
            })
            parent_id = _compact(operation.get("parent_id"), 180)
            if parent_id:
                relation = {"task": "owns_task", "capability": "requires_capability", "knowledge_skill": "requires_knowledge_skill"}[kind]
                edges.append({
                    "id": _stable_id("edge", f"{relation}:{parent_id}:{node_id}"),
                    "type": relation, "object_type": "semantic_edge", "source": parent_id, "target": node_id,
                    "lifecycle": "candidate", "evidence_refs": refs or ["user:iteration-proposal"],
                })
            changes.append({"op": op, "id": node_id, "label": label})
        elif op == "update_node":
            target_id = _compact(operation.get("target_id"), 180)
            target = next((item for item in nodes if item.get("id") == target_id), None)
            if not target:
                continue
            before = _canonical_hash(target)
            if operation.get("summary"):
                target["summary"] = _compact(operation["summary"], 360)
            if target.get("type") != "role" and operation.get("lifecycle") in {"accepted", "candidate", "deprecated"}:
                target["lifecycle"] = operation["lifecycle"]
            if operation.get("evidence_refs"):
                target["evidence_refs"] = list(dict.fromkeys([*target.get("evidence_refs", []), *operation["evidence_refs"]]))[:20]
            if before != _canonical_hash(target):
                changes.append({"op": op, "id": target_id})
    return candidate, {"meaningful": bool(changes), "changes": changes, "change_count": len(changes)}


def _explain(
    graph: dict[str, Any],
    query: str,
    *,
    evidence: dict[str, Any] | None = None,
    snapshot_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    terms = [item.casefold() for item in re.findall(r"[\w\u4e00-\u9fff]{2,}", query)]
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    ranked = sorted(
        nodes,
        key=lambda item: sum(term in f"{item.get('label', '')} {item.get('summary', '')}".casefold() for term in terms),
        reverse=True,
    )
    selected = [item for item in ranked if not terms or any(term in f"{item.get('label', '')} {item.get('summary', '')}".casefold() for term in terms)][:MAX_RESULTS]
    if not selected:
        selected = ranked[:4]
    selected_ids = {item["id"] for item in selected}
    neighbor_ids = {
        endpoint
        for edge in edges
        if edge.get("source") in selected_ids or edge.get("target") in selected_ids
        for endpoint in (edge.get("source"), edge.get("target"))
    }
    context = [item for item in nodes if item.get("id") in (selected_ids | neighbor_ids)][:MAX_RESULTS]
    evidence_value = dict(evidence or {})
    sources = {
        str(item.get("ref") or ""): item
        for item in list(evidence_value.get("sources") or [])
        if isinstance(item, dict)
    }
    claims = [
        item for item in list(evidence_value.get("claims") or [])
        if isinstance(item, dict) and item.get("subject_id") in {node.get("id") for node in context}
    ]
    cited_refs = sorted({ref for item in context for ref in item.get("evidence_refs", [])})
    return {
        "query": _compact(query, 500),
        "answer": "；".join(f"{item['label']}：{item.get('summary', '')}" for item in selected[:4]),
        "objects": context,
        "relations": [item for item in edges if item.get("source") in neighbor_ids and item.get("target") in neighbor_ids][:12],
        "citations": [{
            "ref": ref,
            "source": sources.get(ref),
            "claims": [item for item in claims if ref in list(item.get("evidence_refs") or [])],
        } for ref in cited_refs],
        "snapshot_ref": snapshot_ref,
        "coverage": {"requested": len(terms), "returned": len(selected), "partial": len(context) >= MAX_RESULTS},
        "authority": "immutable_plugin_snapshot",
        "mastery_unchanged": True,
    }


def _dispatch(operation: str, input_value: dict[str, Any]) -> dict[str, Any]:
    configuration = dict(input_value.get("plugin_configuration") or {})
    max_tasks = max(1, min(int(configuration.get("max_tasks", MAX_TASKS)), 40))
    include_process_view = bool(configuration.get("include_process_view", True))
    if operation == "generate":
        project = _host_call("project.read.v1", {}) or {}
        source_refs, source_texts = _source_material(input_value)
        role_title = _compact(input_value.get("role_title"), 255)
        graph = _compile_graph(
            role_title,
            _compact(input_value.get("role_summary") or project.get("description"), 1200),
            list(input_value.get("task_seeds") or []),
            source_refs,
            source_texts,
            max_tasks,
        )
        snapshot = _snapshot(
            graph,
            source_refs,
            {"workflow": "generate", "effective_configuration": configuration},
            include_process_view=include_process_view,
        )
        return {
            "result": {"summary": f"生成 {snapshot['validation']['stats']['nodes']} 个岗位对象"},
            "snapshot": snapshot,
            "events": [{"type": "package_generated", "payload": {"mastery_unchanged": True}}],
        }
    if operation in {"read_graph", "validate"}:
        snapshot = dict(input_value.get("snapshot") or {})
        graph = _graph_from_snapshot(snapshot)
        result = {
            "graph": graph,
            "validation": _inspect(graph, list(snapshot.get("source_refs") or [])),
            "snapshot_ref": input_value.get("snapshot_ref"),
            "mastery_unchanged": True,
        }
        return {"result": result}
    if operation == "explain":
        snapshot = dict(input_value.get("snapshot") or {})
        return {
            "result": _explain(
                _graph_from_snapshot(snapshot),
                str(input_value.get("query") or ""),
                evidence=dict(snapshot.get("components", {}).get("evidence") or {}),
                snapshot_ref=dict(input_value.get("snapshot_ref") or {}),
            ),
            "events": [{"type": "snapshot_explained", "payload": {"mastery_unchanged": True}}],
        }
    if operation == "iterate":
        base = dict(input_value.get("snapshot") or {})
        operations = list(input_value.get("operations") or [])
        if not operations and _compact(input_value.get("label"), 100):
            target_ids = list(input_value.get("target_ids") or [])
            operations = [{
                "op": "add_node",
                "type": _compact(input_value.get("object_type") or "capability", 40),
                "label": _compact(input_value.get("label"), 100),
                "summary": _compact(input_value.get("summary"), 360),
                "parent_id": _compact(input_value.get("parent_id") or (target_ids[0] if target_ids else ""), 180),
                "evidence_refs": list(input_value.get("evidence_refs") or ["user:iteration-proposal"]),
            }]
        candidate, diff = _apply_iteration(_graph_from_snapshot(base), operations)
        if not diff["meaningful"]:
            return {"result": {"status": "no_change", "diff": diff, "mastery_unchanged": True}}
        snapshot = _snapshot(
            candidate,
            list(base.get("source_refs") or []),
            {
                "workflow": "iterate",
                "base_snapshot_ref": input_value.get("snapshot_ref"),
                "contract": {
                    "objective": _compact(input_value.get("objective"), 1000),
                    "target_ids": list(input_value.get("target_ids") or [])[:40],
                },
                "diff": diff,
                "effective_configuration": configuration,
            },
            include_process_view=include_process_view,
        )
        return {
            "result": {"status": "completed", "diff": diff, "validation": snapshot["validation"]},
            "snapshot": snapshot,
            "events": [{"type": "snapshot_iterated", "payload": {"diff": diff, "mastery_unchanged": True}}],
        }
    if operation == "upgrade":
        base = dict(input_value.get("snapshot") or {})
        graph = _graph_from_snapshot(base)
        snapshot = _snapshot(
            graph,
            list(base.get("source_refs") or []),
            {
                "workflow": "upgrade",
                "base_snapshot_ref": input_value.get("snapshot_ref"),
                "effective_configuration": configuration,
            },
            include_process_view=include_process_view,
        )
        return {
            "result": {"status": "compatible", "validation": snapshot["validation"]},
            "snapshot": snapshot,
            "events": [{"type": "release_upgraded", "payload": {"mastery_unchanged": True}}],
        }
    raise ValueError(f"unknown_operation:{operation}")


def main() -> int:
    try:
        request = _read()
        request_id = request.get("id")
        params = dict(request.get("params") or {})
        if request.get("jsonrpc") != "2.0" or request.get("method") != "plugin.run":
            raise ValueError("invalid_initial_request")
        if params.get("protocol") != PROTOCOL:
            raise ValueError("unsupported_rpc_protocol")
        result = _dispatch(str(params.get("operation_id") or ""), dict(params.get("input") or {}))
        _emit({"jsonrpc": "2.0", "id": request_id, "result": result})
        return 0
    except Exception as exc:
        try:
            _emit({
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32020, "message": str(exc)[:500]},
            })
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
