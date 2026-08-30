"""Built-in Agent Package for the official Role Capability Graph plugin.

The product plugin is an in-process composition of agents, skills, tools and
workflows.  It still runs behind the generic deterministic Plugin Host, but it
does not require the optional native-process adapter used by third-party
``.lfplugin`` releases.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, TYPE_CHECKING

from app.services.plugin_host import register_builtin_workflow
from app.services.role_capability_plugin import (
    apply_iteration,
    compile_role_graph,
    explain_role_graph,
    inspect_role_graph,
)

if TYPE_CHECKING:
    from app.services.plugin_host import PluginWorkflowContext


ROLE_PLUGIN_ID = "role_capability_graph"
OBJECT_SCHEMA = "role-capability.object.v1"
WORKFLOWS = ("generate", "explain", "iterate", "validate", "upgrade")


def _compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value.strip().lower()}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_material(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    refs: list[dict[str, Any]] = []
    texts: list[dict[str, str]] = []
    for source in list(payload.get("sources") or []):
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
        for chunk in list(source.get("chunks") or []):
            if isinstance(chunk, dict):
                texts.append({"ref": ref["ref"], "text": str(chunk.get("content") or chunk.get("text") or "")[:2000]})
    return refs, texts


def _snapshot_candidate(
    graph: dict[str, Any],
    source_refs: list[dict[str, Any]],
    provenance: dict[str, Any],
    *,
    include_process_view: bool,
) -> dict[str, Any]:
    validation = inspect_role_graph(graph)
    if not validation["valid"]:
        raise ValueError("candidate_protocol_invalid:" + ",".join(validation["errors"]))

    semantic_graph = deepcopy(graph)
    for edge in semantic_graph.get("edges", []):
        edge["object_type"] = "semantic_edge"
    tasks = [item for item in semantic_graph.get("nodes", []) if item.get("type") == "task"]
    role = dict(semantic_graph.get("role") or {})
    actor = {
        "id": _stable_id("actor", str(role.get("id") or role.get("title") or "role")),
        "type": "actor",
        "label": str(role.get("title") or "岗位角色"),
        "summary": "承担岗位过程责任的角色。",
        "lifecycle": "accepted",
        "evidence_refs": [],
    }
    scenarios: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    work_objects: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for order, task in enumerate(tasks, start=1):
        task_id = str(task.get("id") or "")
        event_id = _stable_id("process_event", task_id)
        work_object_id = _stable_id("work_object", task_id)
        evidence_refs = list(task.get("evidence_refs") or [])
        events.append({
            "id": event_id, "type": "process_event", "label": str(task.get("label") or ""),
            "order": order, "actor_id": actor["id"], "task_id": task_id,
            "work_object_id": work_object_id, "lifecycle": task.get("lifecycle", "candidate"),
            "evidence_refs": evidence_refs,
        })
        scenarios.append({
            "id": _stable_id("scenario", task_id), "type": "scenario",
            "label": f"{task.get('label', '')}场景", "event_ids": [event_id],
            "lifecycle": "candidate", "evidence_refs": evidence_refs,
        })
        work_objects.append({
            "id": work_object_id, "type": "work_object",
            "label": f"{task.get('label', '')}输入与产物",
            "lifecycle": "candidate", "evidence_refs": evidence_refs,
        })
        bridges.append({
            "id": _stable_id("bridge", f"{task_id}:{event_id}"), "type": "bridge",
            "label": "任务—过程桥", "semantic_object_id": task_id,
            "process_event_id": event_id, "lifecycle": "candidate",
            "evidence_refs": evidence_refs,
        })
        claims.append({
            "id": _stable_id("claim", task_id), "type": "claim",
            "label": str(task.get("label") or ""), "statement": str(task.get("summary") or ""),
            "subject_id": task_id, "lifecycle": "candidate", "evidence_refs": evidence_refs,
        })

    components: dict[str, Any] = {
        "evidence": {"sources": source_refs, "claims": claims},
        "semantic-graph": semantic_graph,
        "process-forest": {
            "actors": [actor], "scenarios": scenarios, "events": events,
            "work_objects": work_objects, "bridges": bridges,
        },
        "views": {"views": [
            *list(semantic_graph.get("views") or []),
            *([{"id": "process-bridge", "label": "岗位过程桥", "node_types": ["process_event", "scenario", "work_object", "bridge"]}] if include_process_view else []),
        ]},
        "retrieval-index": {"entries": [
            {"object_id": item["id"], "text": _compact(f"{item.get('label', '')} {item.get('summary', '')}", 500)}
            for item in semantic_graph.get("nodes", [])
        ]},
        "validation-report": validation,
        "reference-migrations": {"mappings": [], "policy": "stable_ids_are_not_silently_rewritten"},
    }
    locations = (
        ("semantic-graph", "nodes", list(semantic_graph.get("nodes") or [])),
        ("semantic-graph", "edges", list(semantic_graph.get("edges") or [])),
        ("evidence", "claims", claims),
        ("process-forest", "actors", [actor]),
        ("process-forest", "scenarios", scenarios),
        ("process-forest", "events", events),
        ("process-forest", "work_objects", work_objects),
        ("process-forest", "bridges", bridges),
    )
    objects: list[dict[str, Any]] = []
    for component, collection, values in locations:
        for index, item in enumerate(values):
            references = list(item.get("references") or [])
            if item.get("object_type") == "semantic_edge" and not references:
                references = [item.get("source"), item.get("target")]
            objects.append({
                "id": item["id"], "type": str(item.get("object_type") or item.get("type") or ""),
                "label": str(item.get("label") or item.get("type") or ""),
                "component": component, "json_pointer": f"/{collection}/{index}",
                "content_hash": _hash(item), "lifecycle": str(item.get("lifecycle") or "active"),
                "references": [item for item in references if item],
            })
    return {
        "schema_version": OBJECT_SCHEMA,
        "components": components,
        "objects": objects,
        "source_refs": source_refs,
        "validation": validation,
        "provenance": {**provenance, "agent_package": ROLE_PLUGIN_ID, "mastery_unchanged": True},
    }


def _graph_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    graph = dict(snapshot.get("components") or {}).get("semantic-graph") or snapshot.get("graph")
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("snapshot_semantic_graph_missing")
    return deepcopy(graph)


async def run_role_capability_workflow(
    context: "PluginWorkflowContext", input_value: dict[str, Any],
) -> dict[str, Any]:
    workflow = str((context.run.contract or {}).get("workflow_id") or context.run.operation_id)
    configuration = dict(input_value.get("plugin_configuration") or {})
    include_process_view = bool(configuration.get("include_process_view", True))
    if workflow == "generate":
        project = await context.call_host_port("project.read.v1", {})
        sources = await context.call_host_port("source.read.v1", {
            "source_ids": list(input_value.get("source_ids") or [])[:20],
            "max_sources": 20, "max_chunks": 24, "max_chars": 24_000,
        })
        source_refs, source_texts = _source_material(dict(sources or {}))
        graph = compile_role_graph(
            role_title=_compact(input_value.get("role_title"), 255),
            role_summary=_compact(input_value.get("role_summary") or dict(project or {}).get("description"), 1200),
            task_seeds=list(input_value.get("task_seeds") or []),
            source_refs=source_refs,
            source_texts=source_texts,
            max_tasks=max(1, min(int(configuration.get("max_tasks", 12)), 40)),
        )
        snapshot = _snapshot_candidate(
            graph, source_refs, {"workflow": "generate", "effective_configuration": configuration},
            include_process_view=include_process_view,
        )
        return {
            "result": {"summary": f"生成 {snapshot['validation']['stats']['nodes']} 个岗位对象"},
            "snapshot": snapshot,
            "events": [{"type": "package_generated", "payload": {"mastery_unchanged": True}}],
        }

    snapshot_input = dict(input_value.get("snapshot") or {})
    graph = _graph_from_snapshot(snapshot_input)
    if workflow == "validate":
        return {"result": {
            "graph": graph, "validation": inspect_role_graph(graph),
            "snapshot_ref": input_value.get("snapshot_ref"), "mastery_unchanged": True,
        }}
    if workflow == "explain":
        result = explain_role_graph(graph, str(input_value.get("query") or ""))
        result["snapshot_ref"] = input_value.get("snapshot_ref")
        return {
            "result": result,
            "events": [{"type": "snapshot_explained", "payload": {"mastery_unchanged": True}}],
        }
    if workflow == "iterate":
        operations = list(input_value.get("operations") or [])
        if not operations and _compact(input_value.get("label"), 100):
            targets = list(input_value.get("target_ids") or [])
            operations = [{
                "op": "add_node", "type": _compact(input_value.get("object_type") or "capability", 40),
                "label": _compact(input_value.get("label"), 100),
                "summary": _compact(input_value.get("summary"), 360),
                "parent_id": _compact(input_value.get("parent_id") or (targets[0] if targets else ""), 180),
                "evidence_refs": list(input_value.get("evidence_refs") or ["user:iteration-proposal"]),
            }]
        candidate, diff = apply_iteration(graph, operations)
        if not diff["meaningful"]:
            return {"result": {"status": "no_change", "diff": diff, "mastery_unchanged": True}}
        successor = _snapshot_candidate(
            candidate, list(snapshot_input.get("source_refs") or []),
            {"workflow": "iterate", "base_snapshot_ref": input_value.get("snapshot_ref"), "diff": diff, "effective_configuration": configuration},
            include_process_view=include_process_view,
        )
        return {
            "result": {"status": "completed", "diff": diff, "validation": successor["validation"]},
            "snapshot": successor,
            "events": [{"type": "snapshot_iterated", "payload": {"diff": diff, "mastery_unchanged": True}}],
        }
    if workflow == "upgrade":
        successor = _snapshot_candidate(
            graph, list(snapshot_input.get("source_refs") or []),
            {"workflow": "upgrade", "base_snapshot_ref": input_value.get("snapshot_ref"), "effective_configuration": configuration},
            include_process_view=include_process_view,
        )
        return {
            "result": {"status": "compatible", "validation": successor["validation"]},
            "snapshot": successor,
            "events": [{"type": "release_upgraded", "payload": {"mastery_unchanged": True}}],
        }
    raise ValueError(f"unknown_role_capability_workflow:{workflow}")


def register_role_capability_agent_package() -> None:
    for workflow in WORKFLOWS:
        register_builtin_workflow(ROLE_PLUGIN_ID, workflow, run_role_capability_workflow)


__all__ = ["register_role_capability_agent_package", "run_role_capability_workflow"]
