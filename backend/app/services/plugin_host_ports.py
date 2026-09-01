"""Deterministic, project-scoped Host Ports for external LearnFlow plugins.

The port layer is the only view of LearnFlow objects a plugin process can
receive.  It never exposes ORM instances, sessions, credentials or arbitrary
filesystem paths.  Every response is bounded and answer-safe where relevant.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.learning import AgentAction, LearningTask
from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginPublisher,
    PluginRelease,
    PluginSnapshot,
)
from app.models.project import (
    Checkpoint,
    Chunk,
    DomainKnowledgePacket,
    Exercise,
    Lecture,
    Project,
    Roadmap,
    Source,
    SourceVersion,
)
from app.services.action_board import ACTION_BOARD, PLUGIN_PROPOSABLE_CAPABILITIES
from app.services.five_kernel_context import (
    CONTEXT_POLICIES,
    ContextPolicy,
    build_five_kernel_context,
)
from app.services.learning_runtime import record_event
from app.services.plugin_artifacts import PluginArtifactStore


HOST_PORT_IDS = (
    "project.read.v1",
    "source.read.v1",
    "knowledge_baseline.read.v1",
    "roadmap.read.v1",
    "checkpoint.read.v1",
    "learning_task.read.v1",
    "learning_file.read.v1",
    "learner_context.read.v1",
    "artifact.resolve.v1",
    "model.generate_structured.v1",
    "action.propose.v1",
    "event.record.v1",
)
KERNEL_IDS = ("structure", "knowledge", "human", "value", "practice")
MAX_PORT_RESULT_BYTES = 256 * 1024
MAX_MODEL_PROMPT_CHARS = 20_000
MAX_MODEL_OUTPUT_CHARS = 32_000


def _schema_constrained_prompt(prompt: str, schema: Mapping[str, Any]) -> str:
    """Make the Host Port's validation contract visible to JSON-only models.

    OpenAI-compatible providers commonly support ``json_object`` without
    supporting server-side JSON Schema enforcement.  Supplying the exact
    schema in the prompt keeps those providers on the same strict contract as
    the post-generation validator instead of needlessly falling back after a
    structurally useful response.
    """

    schema_text = json.dumps(
        dict(schema), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )
    return (
        f"{prompt}\n\n"
        "严格只返回一个符合下列 JSON Schema 的 JSON 对象；"
        "不得把字符串数组改成对象数组，不得增加未声明字段。\n"
        f"JSON Schema:\n{schema_text}"
    )[:MAX_MODEL_PROMPT_CHARS]


class PluginHostPortError(ValueError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class PluginHostPortContext:
    db: AsyncSession
    learner_id: int
    project_id: int
    instance: PluginInstance
    manifest: Mapping[str, Any]
    release_id: int
    base_release_id: int
    authorized_host_ports: frozenset[str]
    run_id: int | None = None
    artifact_store: PluginArtifactStore | None = None


def _error(code: str, message: str, **details: Any) -> PluginHostPortError:
    return PluginHostPortError(code, message, details=details)


def _int(value: Any, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    parsed = max(minimum, parsed)
    return min(parsed, maximum) if maximum is not None else parsed


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _bounded(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise _error("host_port_result_invalid", "Host Port result is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_PORT_RESULT_BYTES:
        raise _error("host_port_result_too_large", "Host Port result exceeds the RPC message budget")
    return value


async def _declared_and_granted(context: PluginHostPortContext, port: str) -> None:
    if port not in HOST_PORT_IDS:
        raise _error("unknown_host_port", "Host Port is not registered", port=port)
    await context.db.refresh(
        context.instance,
        attribute_names=["status", "release_id", "granted_host_ports"],
    )
    if context.instance.status != "enabled":
        raise _error("plugin_instance_disabled", "plugin instance was disabled while the run was active")
    if int(context.instance.release_id) != int(context.base_release_id):
        raise _error(
            "plugin_release_changed",
            "plugin instance release changed while the run was active",
            expected=context.base_release_id,
            current=context.instance.release_id,
        )
    release = await context.db.get(PluginRelease, context.release_id)
    if (
        not release
        or release.status != "active"
        or release.revoked_at is not None
        or release.trust_state not in {"trusted_signed", "untrusted_development", "built_in"}
    ):
        raise _error("plugin_release_unavailable", "plugin release is no longer runnable")
    if release.publisher_id is not None and release.trust_state != "built_in":
        publisher = await context.db.get(PluginPublisher, release.publisher_id)
        if (
            not publisher
            or publisher.trust_status == "revoked"
            or publisher.revoked_at is not None
            or (release.trust_state == "trusted_signed" and publisher.trust_status != "trusted")
        ):
            raise _error("plugin_publisher_revoked", "plugin publisher is no longer trusted")
    declared = set(context.manifest.get("host_ports") or [])
    granted = set(context.authorized_host_ports)
    if port not in declared:
        raise _error("host_port_not_declared", "plugin did not declare this Host Port", port=port)
    if port not in granted:
        raise _error("host_port_not_granted", "project instance did not authorize this Host Port", port=port)


async def _project(context: PluginHostPortContext) -> Project:
    project = await context.db.get(Project, context.project_id)
    if not project or project.learner_id != context.learner_id:
        raise _error("project_scope_mismatch", "plugin project scope is not owned by the learner")
    if context.instance.project_id != project.id or context.instance.learner_id != context.learner_id:
        raise _error("instance_scope_mismatch", "plugin instance is outside the requested project scope")
    return project


async def _project_read(context: PluginHostPortContext, _input: Mapping[str, Any]) -> dict[str, Any]:
    project = await _project(context)
    return {
        "protocol": "learnflow.project-port.v1",
        "id": project.id,
        "learner_id": context.learner_id,
        "name": project.name,
        "description": project.description,
        "project_kind": project.project_kind,
        "visibility": project.visibility,
        "ownership_scope": {"learner_id": context.learner_id, "project_id": project.id},
        "updated_at": _iso(project.updated_at),
    }


async def _active_source_version(db: AsyncSession, source: Source) -> SourceVersion | None:
    active_id = _int(dict(source.meta_data or {}).get("active_source_version_id"))
    version = await db.get(SourceVersion, active_id) if active_id else None
    if version and version.source_id == source.id:
        return version
    return (await db.execute(select(SourceVersion).where(
        SourceVersion.source_id == source.id,
    ).order_by(SourceVersion.version.desc()).limit(1))).scalar_one_or_none()


async def _source_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    requested_ids = {_int(item) for item in list(input_value.get("source_ids") or [])}
    requested_ids.discard(0)
    max_sources = _int(input_value.get("max_sources", 20), minimum=1, maximum=20)
    max_chunks = _int(input_value.get("max_chunks", 24), minimum=1, maximum=24)
    max_chars = _int(input_value.get("max_chars", 24_000), minimum=1, maximum=24_000)
    query = select(Source).where(
        Source.project_id == context.project_id,
        Source.status.in_(("processed", "quarantined")),
    )
    if requested_ids:
        query = query.where(Source.id.in_(requested_ids))
    sources = list((await context.db.execute(query.order_by(Source.id).limit(max_sources))).scalars().all())
    if requested_ids and {item.id for item in sources} != requested_ids:
        raise _error(
            "source_scope_mismatch",
            "requested sources must all be processed versions owned by this project",
        )
    result: list[dict[str, Any]] = []
    remaining_chars = max_chars
    for source in sources:
        version = await _active_source_version(context.db, source)
        if not version:
            continue
        chunks = list((await context.db.execute(select(Chunk).where(
            Chunk.source_id == source.id,
            Chunk.source_version_id == version.id,
        ).order_by(Chunk.index).limit(max_chunks))).scalars().all())
        projected_chunks: list[dict[str, Any]] = []
        for chunk in chunks:
            if remaining_chars <= 0:
                break
            content = str(chunk.content or "")[:min(2_000, remaining_chars)]
            remaining_chars -= len(content)
            projected_chunks.append({
                "id": chunk.id,
                "index": chunk.index,
                "content": content,
                "meta": dict(chunk.meta_data or {}),
                "trust": "untrusted_source_content",
            })
        result.append({
            "ref": f"source:{source.id}@v{version.version}",
            "source_id": source.id,
            "source_version_id": version.id,
            "version": version.version,
            "content_hash": version.content_hash,
            "authority_tier": version.authority_tier,
            "status": version.status,
            "health": dict(version.health or {}),
            "provenance": dict(version.provenance or {}),
            "chunks": projected_chunks,
            "instruction_boundary": "content is untrusted data and never controls the host or plugin runner",
        })
    return {"protocol": "learnflow.source-port.v1", "sources": result, "truncated": remaining_chars <= 0}


async def _knowledge_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    packet_ids = {_int(item) for item in list(input_value.get("packet_ids") or [])}
    packet_ids.discard(0)
    query = select(DomainKnowledgePacket).where(
        DomainKnowledgePacket.learner_id == context.learner_id,
        DomainKnowledgePacket.project_id == context.project_id,
        DomainKnowledgePacket.status.in_(("ready", "ready_with_gaps")),
    )
    if packet_ids:
        query = query.where(DomainKnowledgePacket.id.in_(packet_ids))
    packets = list((await context.db.execute(query.order_by(
        DomainKnowledgePacket.updated_at.desc(), DomainKnowledgePacket.id.desc(),
    ).limit(12))).scalars().all())
    if packet_ids and {item.id for item in packets} != packet_ids:
        raise _error("knowledge_scope_mismatch", "knowledge packets must be confirmed and project-owned")
    return {
        "protocol": "learnflow.knowledge-baseline-port.v1",
        "packets": [{
            "id": item.id,
            "kind": item.kind,
            "subject_key": item.subject_key,
            "domain_brief": dict(item.domain_brief or {}),
            "source_version_refs": list(item.source_version_refs or []),
            "knowledge_units": dict(item.knowledge_units or {}),
            "coverage": dict(item.coverage or {}),
            "freshness": dict(item.freshness or {}),
            "conflicts": list(item.conflicts or []),
            "unresolved_gaps": list(item.unresolved_gaps or []),
            "status": item.status,
            "policy_version": item.policy_version,
        } for item in packets],
        "mastery_authority": False,
    }


async def _roadmap_read(context: PluginHostPortContext, _input: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    roadmap = (await context.db.execute(select(Roadmap).where(
        Roadmap.project_id == context.project_id,
    ))).scalar_one_or_none()
    if not roadmap:
        return {"protocol": "learnflow.roadmap-port.v1", "roadmap": None, "checkpoints": []}
    checkpoints = list((await context.db.execute(select(Checkpoint).where(
        Checkpoint.roadmap_id == roadmap.id,
        Checkpoint.archived.is_(False),
    ).order_by(Checkpoint.order, Checkpoint.id))).scalars().all())
    return {
        "protocol": "learnflow.roadmap-port.v1",
        "roadmap": {
            "id": roadmap.id,
            "revision": _iso(roadmap.updated_at),
            "definition": dict(roadmap.raw_json or {}),
        },
        "checkpoints": [_checkpoint_projection(item) for item in checkpoints],
        "write_boundary": "read_only; changes require action.propose.v1",
    }


def _checkpoint_projection(item: Checkpoint) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "order": item.order,
        "prerequisites": list(item.prerequisites or []),
        "learning_status": item.learning_status,
        "learning_contract": dict(item.learning_contract or {}),
        "brief": dict(item.brief or {}),
        "archived": bool(item.archived),
    }


async def _checkpoint_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    ids = {_int(item) for item in list(input_value.get("checkpoint_ids") or [])}
    ids.discard(0)
    query = select(Checkpoint).join(Roadmap, Roadmap.id == Checkpoint.roadmap_id).where(
        Roadmap.project_id == context.project_id,
    )
    if ids:
        query = query.where(Checkpoint.id.in_(ids))
    checkpoints = list((await context.db.execute(query.order_by(Checkpoint.order).limit(80))).scalars().all())
    if ids and {item.id for item in checkpoints} != ids:
        raise _error("checkpoint_scope_mismatch", "checkpoint does not belong to the plugin project")
    return {"protocol": "learnflow.checkpoint-port.v1", "checkpoints": [_checkpoint_projection(item) for item in checkpoints]}


async def _learning_task_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    ids = {_int(item) for item in list(input_value.get("task_ids") or [])}
    ids.discard(0)
    query = select(LearningTask).where(
        LearningTask.learner_id == context.learner_id,
        LearningTask.project_id == context.project_id,
    )
    if ids:
        query = query.where(LearningTask.id.in_(ids))
    tasks = list((await context.db.execute(query.order_by(
        LearningTask.queue_position, LearningTask.id,
    ).limit(80))).scalars().all())
    if ids and {item.id for item in tasks} != ids:
        raise _error("learning_task_scope_mismatch", "learning task does not belong to the plugin project")
    return {
        "protocol": "learnflow.learning-task-port.v1",
        "tasks": [{
            "id": item.id,
            "checkpoint_id": item.checkpoint_id,
            "title": item.title,
            "objective": item.objective,
            "status": item.status,
            "priority": item.priority,
            "source_refs": list(item.source_refs or []),
            "success_criteria": list(item.success_criteria or []),
            "plan": dict(item.plan or {}),
            "plan_version": item.plan_version,
            "artifact_refs": list(item.artifact_refs or []),
            "version": item.version,
        } for item in tasks],
        "write_boundary": "read_only; changes require action.propose.v1",
    }


async def _learning_file_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    checkpoint_ids = {_int(item) for item in list(input_value.get("checkpoint_ids") or [])}
    checkpoint_ids.discard(0)
    query = select(Checkpoint).join(Roadmap, Roadmap.id == Checkpoint.roadmap_id).where(
        Roadmap.project_id == context.project_id,
    )
    if checkpoint_ids:
        query = query.where(Checkpoint.id.in_(checkpoint_ids))
    checkpoints = list((await context.db.execute(query.limit(40))).scalars().all())
    ids = [item.id for item in checkpoints]
    lectures = list((await context.db.execute(select(Lecture).where(
        Lecture.checkpoint_id.in_(ids or [-1]),
        Lecture.status == "published",
    ))).scalars().all())
    exercises = list((await context.db.execute(select(Exercise).where(
        Exercise.checkpoint_id.in_(ids or [-1]),
    ).order_by(Exercise.checkpoint_id, Exercise.order).limit(120))).scalars().all())
    return {
        "protocol": "learnflow.learning-file-port.v1",
        "lectures": [{
            "id": item.id,
            "checkpoint_id": item.checkpoint_id,
            "version": item.version,
            "sections": list(item.sections or []),
            "concept_graph": dict(item.concept_graph or {}),
        } for item in lectures],
        "exercises": [{
            "id": item.id,
            "checkpoint_id": item.checkpoint_id,
            "title": item.title,
            "description": item.description,
            "starter_code": item.starter_code,
            "hints_available": len(item.hints or []),
            "requirements": list(item.requirements or []),
            "assessment_targets": list(dict(item.assessment_meta or {}).get("targets") or []),
        } for item in exercises],
        "answer_safe": True,
        "excluded_fields": ["solution", "test_cases", "judge_config", "answers", "expected_output"],
    }


async def _learner_context_read(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    manifest_allow = tuple(context.manifest.get("kernel_allow_list") or ())
    requested = tuple(input_value.get("kernels") or manifest_allow)
    if set(requested) - set(manifest_allow) or set(manifest_allow) - set(KERNEL_IDS):
        raise _error("kernel_scope_forbidden", "learner context exceeds the manifest kernel allow-list")
    if not requested:
        return {
            "protocol": "learnflow.learner-context-port.v1",
            "context": {"kernel_heads": {}, "items": []},
            "kernel_allow_list": [],
        }
    base = CONTEXT_POLICIES["learning_design"]
    policy = ContextPolicy(
        id=f"plugin:{context.instance.plugin_id}",
        head_kernels=requested,
        deep_kernels=requested,
        max_items=min(base.max_items, _int(input_value.get("max_items", base.max_items), minimum=1, maximum=12)),
        max_paths=base.max_paths,
        token_budget=min(base.token_budget, _int(input_value.get("token_budget", base.token_budget), minimum=256, maximum=2800)),
        scope_mode="project",
        relations=base.relations,
    )
    packet = await build_five_kernel_context(
        context.db,
        learner_id=context.learner_id,
        policy=policy,
        project_id=context.project_id,
        query=str(input_value.get("query") or "")[:1000],
    )
    return {
        "protocol": "learnflow.learner-context-port.v1",
        "context": packet,
        "kernel_allow_list": list(requested),
        "write_boundary": "no Kernel write interface exists",
    }


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer in {"", "/"}:
        return value
    current = value
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise _error("artifact_pointer_invalid", "plugin object pointer is invalid") from exc
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise _error("artifact_pointer_invalid", "plugin object pointer is invalid")
    return current


async def _resolve_plugin_ref(context: PluginHostPortContext, ref: Mapping[str, Any]) -> dict[str, Any]:
    if ref.get("protocol") != "learnflow.plugin-object-ref.v1":
        raise _error("artifact_ref_invalid", "unsupported plugin object reference")
    instance_id = _int(ref.get("instance_id"))
    snapshot_id = _int(ref.get("snapshot_id"))
    instance = await context.db.get(PluginInstance, instance_id)
    snapshot = await context.db.get(PluginSnapshot, snapshot_id)
    if (
        not instance
        or not snapshot
        or instance.learner_id != context.learner_id
        or instance.project_id != context.project_id
        or snapshot.instance_id != instance.id
        or instance.plugin_id != ref.get("plugin_id")
        or snapshot.root_hash != ref.get("snapshot_root_hash")
    ):
        raise _error("plugin_object_scope_mismatch", "plugin object reference is outside project scope")
    index = (await context.db.execute(select(PluginObjectIndex).where(
        PluginObjectIndex.snapshot_id == snapshot.id,
        PluginObjectIndex.object_id == str(ref.get("object_id") or ""),
    ))).scalar_one_or_none()
    if (
        not index
        or index.object_type != ref.get("object_type")
        or index.schema_version != ref.get("schema_version")
        or index.content_hash != ref.get("content_hash")
    ):
        raise _error("plugin_object_ref_stale", "plugin object reference does not match its fixed index")
    descriptor = next(
        (item for item in list(snapshot.components or []) if item.get("name") == index.component),
        None,
    )
    if not descriptor:
        raise _error("plugin_component_missing", "snapshot component cannot be resolved")
    store = context.artifact_store or PluginArtifactStore(settings.plugin_artifact_dir)
    try:
        component = json.loads(store.read(str(descriptor.get("uri") or "")).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("plugin_component_invalid", "snapshot component is not valid JSON") from exc
    return {
        "protocol": "learnflow.artifact-resolve-port.v1",
        "ref": dict(ref),
        "object": _json_pointer(component, index.json_pointer),
    }


async def _artifact_resolve(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    ref = input_value.get("ref")
    if not isinstance(ref, dict):
        raise _error("artifact_ref_invalid", "artifact ref must be a typed object")
    if ref.get("protocol") == "learnflow.plugin-object-ref.v1":
        return await _resolve_plugin_ref(context, ref)
    artifact_type = str(ref.get("artifact_type") or "")
    artifact_id = _int(ref.get("artifact_id"))
    if artifact_type == "lecture":
        lecture = await context.db.get(Lecture, artifact_id)
        checkpoint = await context.db.get(Checkpoint, lecture.checkpoint_id) if lecture else None
        roadmap = await context.db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        if not lecture or not roadmap or roadmap.project_id != context.project_id:
            raise _error("artifact_scope_mismatch", "lecture artifact is outside project scope")
        return {
            "protocol": "learnflow.artifact-resolve-port.v1",
            "ref": dict(ref),
            "artifact": {"id": lecture.id, "type": "lecture", "version": lecture.version, "sections": list(lecture.sections or [])},
            "answer_safe": True,
        }
    if artifact_type == "exercise":
        exercise = await context.db.get(Exercise, artifact_id)
        checkpoint = await context.db.get(Checkpoint, exercise.checkpoint_id) if exercise else None
        roadmap = await context.db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        if not exercise or not roadmap or roadmap.project_id != context.project_id:
            raise _error("artifact_scope_mismatch", "exercise artifact is outside project scope")
        return {
            "protocol": "learnflow.artifact-resolve-port.v1",
            "ref": dict(ref),
            "artifact": {
                "id": exercise.id, "type": "exercise", "title": exercise.title,
                "description": exercise.description, "starter_code": exercise.starter_code,
                "hints_available": len(exercise.hints or []),
            },
            "answer_safe": True,
        }
    raise _error("artifact_ref_unsupported", "core artifact reference type is not supported")


def _validate_structured(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    def reject_external_refs(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("$ref", "$dynamicRef"):
                ref = node.get(key)
                if ref is not None and (not isinstance(ref, str) or not ref.startswith("#")):
                    raise _error(
                        "model_schema_reference_forbidden",
                        "structured model schemas may only use document-local references",
                    )
            for child in node.values():
                reject_external_refs(child)
        elif isinstance(node, list):
            for child in node:
                reject_external_refs(child)

    reject_external_refs(schema)
    try:
        Draft202012Validator.check_schema(dict(schema))
        error = next(Draft202012Validator(dict(schema)).iter_errors(value), None)
    except SchemaError as exc:
        raise _error("model_schema_invalid", "structured model schema is invalid") from exc
    if error is not None:
        location = "$" + "".join(
            f"[{item}]" if isinstance(item, int) else f".{item}"
            for item in error.absolute_path
        )
        raise _error(
            "model_output_schema_invalid",
            f"model output does not match schema at {location}",
            validation_message=str(error.message)[:500],
        )


async def _model_generate(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    prompt = str(input_value.get("prompt") or "")[:MAX_MODEL_PROMPT_CHARS]
    schema = input_value.get("schema")
    if not prompt or not isinstance(schema, dict):
        raise _error("model_request_invalid", "structured model port requires a prompt and JSON schema")
    provider = str(input_value.get("provider") or "").strip()
    if provider == "xingchen_learning_task":
        if context.instance.plugin_id != "learning_task_conversion":
            raise _error(
                "model_provider_forbidden",
                "the Xingchen learning-task workflow is restricted to its owning plugin",
            )
        task_title = str(input_value.get("task_title") or "").strip()[:500]
        if not task_title:
            raise _error(
                "model_request_invalid",
                "the Xingchen learning-task workflow requires task_title",
            )
        from app.services.learning_task_conversion_xfyun import (
            XingchenWorkflowConfigError,
            XingchenWorkflowError,
            generate_xingchen_learning_task,
        )

        try:
            generated = await generate_xingchen_learning_task(
                task_title,
                uid=(
                    f"learnflow-lt-{context.learner_id}-{context.project_id}-"
                    f"{context.run_id or 0}"
                ),
                plan_schema=schema,
            )
        except (XingchenWorkflowConfigError, XingchenWorkflowError) as exc:
            raise _error(
                "xingchen_workflow_failed",
                str(exc),
                provider="xunfei-xingchen",
                retryable=True,
            ) from exc
        value = generated["plan"]
        _validate_structured(value, schema)
        return {
            "protocol": "learnflow.model-structured-port.v1",
            "value": value,
            "model": "xunfei-xingchen-workflow",
            "provider": "xunfei-xingchen",
            "provider_provenance": {
                "workflow_run_id": generated["workflow_run_id"],
                "workflow_run_ids": generated["workflow_run_ids"],
                "repair_attempted": generated["repair_attempted"],
                "repair_reasons": generated["repair_reasons"],
                "task_card_id": generated["task_card_id"],
                "verification_status": generated["verification_status"],
            },
            "usage": generated["usage"],
            "credential_exposed": False,
            "audited": True,
        }
    if not settings.llm_api_key or settings.llm_api_key in {"", "***", "sk-your-key-here"}:
        raise _error("model_unavailable", "host model provider is not configured")
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.1,
        timeout=min(180.0, max(1.0, settings.learning_task_plan_model_budget_seconds)),
        max_retries=0,
        max_tokens=4_000,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    try:
        response = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content=_schema_constrained_prompt(prompt, schema))]),
            timeout=min(180.0, max(1.0, settings.learning_task_plan_model_budget_seconds)),
        )
        raw = str(response.content or "")[:MAX_MODEL_OUTPUT_CHARS]
        value = json.loads(raw)
        _validate_structured(value, schema)
    except PluginHostPortError:
        raise
    except Exception as exc:
        raise _error("model_generation_failed", "host model generation failed", error=type(exc).__name__) from exc
    return {
        "protocol": "learnflow.model-structured-port.v1",
        "value": value,
        "model": settings.llm_model,
        "credential_exposed": False,
        "audited": True,
    }


async def _action_propose(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    capability = str(input_value.get("capability") or "")
    if capability not in PLUGIN_PROPOSABLE_CAPABILITIES:
        raise _error(
            "action_capability_forbidden",
            "plugin proposal is not admitted to the core confirmation pipeline",
            allowed=sorted(PLUGIN_PROPOSABLE_CAPABILITIES),
        )
    spec = ACTION_BOARD[capability]
    refs = input_value.get("object_refs") or []
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, dict) for ref in refs):
        raise _error("action_ref_invalid", "plugin action proposals require fixed object references from this instance")
    for ref in refs:
        if _int(ref.get("instance_id")) != context.instance.id:
            raise _error(
                "plugin_object_scope_mismatch",
                "proposal references must belong to the calling plugin instance",
            )
        await _resolve_plugin_ref(context, ref)
    if spec.side_effect == "none":
        raise _error("action_proposal_unnecessary", "read-only core capabilities do not need a side-effect proposal")
    target = dict(input_value.get("target") or {})
    reason = str(input_value.get("reason") or "")[:1000]
    canonical = json.dumps(
        {"capability": capability, "object_refs": refs, "target": target},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    action_key = (
        f"plugin-proposal:{context.instance.id}:{context.run_id or 0}:"
        f"{hashlib.sha256(canonical).hexdigest()[:32]}"
    )
    existing = (await context.db.execute(select(AgentAction).where(
        AgentAction.idempotency_key == action_key,
    ))).scalar_one_or_none()
    if existing:
        return {
            "protocol": "learnflow.action-proposal.v1",
            "status": existing.status,
            "action_id": existing.id,
            "session_id": existing.session_id,
            "capability": existing.capability,
            "confirmation_url": f"/api/agent/actions/{existing.id}/confirm",
            "idempotent_replay": True,
        }
    from app.services.tutor_service import get_or_create_session

    session = await get_or_create_session(
        context.db,
        learner_id=context.learner_id,
        session_type="project",
        project_id=context.project_id,
    )
    proposal = {
        "protocol": "learnflow.action-proposal.v1",
        "status": "pending_confirmation",
        "capability": capability,
        "project_id": context.project_id,
        "plugin_id": context.instance.plugin_id,
        "plugin_instance_id": context.instance.id,
        "object_refs": refs,
        "target": target,
        "reason": reason,
        "side_effect": spec.side_effect,
        "confirmation_policy": "explicit_or_click",
        "evidence_target": dict(spec.evidence_target or {}),
        "mastery_unchanged_until_core_event": True,
    }
    action = AgentAction(
        session_id=session.id,
        learner_id=context.learner_id,
        project_id=context.project_id,
        capability=capability,
        status="pending_confirmation",
        side_effect=spec.side_effect,
        confirmation_policy="explicit_or_click",
        target={
            **target,
            "reason": reason,
            "plugin_proposal": {
                "plugin_id": context.instance.plugin_id,
                "plugin_instance_id": context.instance.id,
                "plugin_run_id": context.run_id,
                "object_refs": refs,
            },
        },
        evidence_target=dict(spec.evidence_target or {}),
        next_affordances=list(spec.next_affordances),
        idempotency_key=action_key,
    )
    context.db.add(action)
    await context.db.flush()
    session.pending_action_id = action.id
    event = await record_event(
        context.db,
        learner_id=context.learner_id,
        project_id=context.project_id,
        event_type="plugin_action_proposed",
        source="plugin_host",
        payload={
            **proposal,
            "plugin_run_id": context.run_id,
            "mastery_unchanged": True,
        },
        provenance={
            "plugin_id": context.instance.plugin_id,
            "release_id": context.instance.release_id,
            "kernel_targets": [],
        },
    )
    return {
        **proposal,
        "action_id": action.id,
        "session_id": session.id,
        "confirmation_url": f"/api/agent/actions/{action.id}/confirm",
        "evidence_event_id": event.id,
        "idempotent_replay": False,
    }


async def _event_record(context: PluginHostPortContext, input_value: Mapping[str, Any]) -> dict[str, Any]:
    await _project(context)
    event_id = str(input_value.get("event_id") or "")
    declared = {
        str(item.get("id") or ""): item
        for item in list(context.manifest.get("events") or [])
        if isinstance(item, dict)
    }
    contract = declared.get(event_id)
    if not contract:
        raise _error("plugin_event_undeclared", "plugin event is not declared in the release manifest")
    if contract.get("kernel_targets", contract.get("target_kernels", [])) not in (None, []):
        raise _error("plugin_event_kernel_target_forbidden", "external plugin events cannot target learner kernels")
    plugin_id = str(context.instance.plugin_id)
    event_type = f"plugin:{plugin_id}:{event_id}"
    plugin_key = str(input_value.get("client_event_id") or "")[:80]
    client_event_id = (
        f"plugin-instance:{context.instance.id}:run:{context.run_id or 0}:event:{event_id}:"
        f"{plugin_key or hashlib.sha256(json.dumps(dict(input_value.get('payload') or {}), sort_keys=True).encode()).hexdigest()[:16]}"
    )[:160]
    event = await record_event(
        context.db,
        learner_id=context.learner_id,
        project_id=context.project_id,
        event_type=event_type,
        source="plugin_host",
        payload={
            **dict(input_value.get("payload") or {}),
            "plugin_id": plugin_id,
            "plugin_instance_id": context.instance.id,
            "plugin_run_id": context.run_id,
            "mastery_unchanged": True,
        },
        provenance={
            "dynamic_plugin_event": True,
            "manifest_event_id": event_id,
            "release_id": context.instance.release_id,
            "kernel_targets": [],
        },
        client_event_id=client_event_id,
    )
    return {
        "protocol": "learnflow.event-record-port.v1",
        "event_id": event.id,
        "event_type": event_type,
        "kernel_targets": [],
    }


_PORT_HANDLERS = {
    "project.read.v1": _project_read,
    "source.read.v1": _source_read,
    "knowledge_baseline.read.v1": _knowledge_read,
    "roadmap.read.v1": _roadmap_read,
    "checkpoint.read.v1": _checkpoint_read,
    "learning_task.read.v1": _learning_task_read,
    "learning_file.read.v1": _learning_file_read,
    "learner_context.read.v1": _learner_context_read,
    "artifact.resolve.v1": _artifact_resolve,
    "model.generate_structured.v1": _model_generate,
    "action.propose.v1": _action_propose,
    "event.record.v1": _event_record,
}


async def call_plugin_host_port(
    context: PluginHostPortContext,
    port: str,
    input_value: Mapping[str, Any] | None = None,
) -> Any:
    """Authorize and dispatch one bounded Host Port call."""

    await _declared_and_granted(context, port)
    result = await _PORT_HANDLERS[port](context, dict(input_value or {}))
    return _bounded(result)


__all__ = [
    "HOST_PORT_IDS",
    "PluginHostPortContext",
    "PluginHostPortError",
    "call_plugin_host_port",
]
