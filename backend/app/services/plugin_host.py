"""Deterministic host for project-scoped LearnFlow plugins.

The host owns scope, grants, idempotency, immutable snapshots and event
admission.  A plugin handler receives no ORM session directly; it can only use
the explicitly granted :class:`PluginWorkflowContext.call_host_port` method.
Native process isolation is deliberately not claimed here.  The process broker
must report its real execution boundary on every run.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import platform
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import async_session
from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginPublisher,
    PluginRelease,
    PluginRun,
    PluginRunEvent,
    PluginSnapshot,
)
from app.models.project import Project
from app.services.auth import CurrentLearner
from app.services.architecture_registry import validate_plugin_manifest_projection
from app.services.learning_runtime import record_event
from app.services.plugin_artifacts import (
    PluginArtifactError,
    PluginArtifactStore,
    canonical_json_bytes,
)
from app.services.plugin_packages import (
    PackagePolicy,
    PluginPackageError,
    TrustedPublisher,
    load_plugin_package,
    semver_satisfies,
)
from app.services.plugin_host_ports import (
    PluginHostPortContext,
    PluginHostPortError,
    call_plugin_host_port,
)
from app.services.plugin_runner import (
    PluginProcessBroker,
    PluginRunnerConfig,
    PluginRunnerError,
)


PLUGIN_HOST_PROTOCOL = "learnflow.plugin-host.v1"
PLUGIN_OBJECT_REF_PROTOCOL = "learnflow.plugin-object-ref.v1"
PLUGIN_SURFACES_PROTOCOL = "learnflow.plugin-surfaces.v1"
MAX_HOST_PORT_CALLS = 32
MAX_HOST_PORT_RESULT_BYTES = 256 * 1024
MAX_TOOL_RESULT_BYTES = 1024 * 1024

HOST_PORT_POLICIES: dict[str, str] = {
    "project.read.v1": "read",
    "source.read.v1": "read_untrusted",
    "knowledge_baseline.read.v1": "read",
    "roadmap.read.v1": "read",
    "checkpoint.read.v1": "read",
    "learning_task.read.v1": "read_answer_safe",
    "learning_file.read.v1": "read_answer_safe",
    "learner_context.read.v1": "read_scoped",
    "artifact.resolve.v1": "read",
    "model.generate_structured.v1": "host_mediated",
    "action.propose.v1": "proposal_only",
    "event.record.v1": "zero_kernel_event_only",
}


class PluginHostError(RuntimeError):
    """Stable error returned by the service and translated by the API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _error(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    **details: Any,
) -> PluginHostError:
    return PluginHostError(code, message, status_code=status_code, details=details)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json_size(value: Any) -> int:
    try:
        return len(canonical_json_bytes(value))
    except (TypeError, ValueError) as exc:
        raise _error("invalid_json", "plugin input or output is not canonical JSON") from exc


def _bounded(value: Any, *, budget: int, label: str) -> Any:
    size = _json_size(value)
    if size > budget:
        raise _error(
            "result_too_large",
            f"{label} exceeds the host byte budget",
            status_code=413,
            size=size,
            budget=budget,
        )
    return value


def _audit_payload(value: Any) -> dict[str, Any]:
    size = _json_size(value)
    if size <= 16 * 1024:
        return {"value": value, "bytes": size, "truncated": False}
    return {
        "sha256": canonical_hash(value),
        "bytes": size,
        "truncated": True,
        "reason": "plugin_run_event_payload_budget",
    }


def _artifact_root() -> Path:
    configured = str(getattr(settings, "plugin_artifact_dir", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "plugin-artifacts"


def artifact_store() -> PluginArtifactStore:
    return PluginArtifactStore(_artifact_root())


def _manifest_items(manifest: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    raw = manifest.get(key, [])
    if isinstance(raw, dict):
        return [dict(value, id=item_id) for item_id, value in raw.items() if isinstance(value, dict)]
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _manifest_item(manifest: Mapping[str, Any], key: str, item_id: str) -> dict[str, Any] | None:
    return next((item for item in _manifest_items(manifest, key) if item.get("id") == item_id), None)


def declared_host_ports(manifest: Mapping[str, Any]) -> set[str]:
    raw = manifest.get("host_ports", [])
    return {str(item) for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()


def validate_host_port_grants(
    manifest: Mapping[str, Any], granted: Iterable[str],
) -> list[str]:
    requested = declared_host_ports(manifest)
    normalized = list(dict.fromkeys(str(item) for item in granted))
    invalid = sorted(set(normalized) - set(HOST_PORT_POLICIES))
    undeclared = sorted(set(normalized) - requested)
    if invalid:
        raise _error("unknown_host_port", "instance grants unknown Host Ports", ports=invalid)
    if undeclared:
        raise _error("undeclared_host_port", "instance cannot grant ports absent from its manifest", ports=undeclared)
    return normalized


def _schema_error_message(error: Any) -> str:
    path = "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in list(getattr(error, "absolute_path", ()) or ())
    )
    return f"{path}: {str(getattr(error, 'message', error))[:500]}"


def _validate_json_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    code: str,
    message: str,
    status_code: int,
    registry: Registry | None = None,
    base_uri: str | None = None,
) -> None:
    try:
        Draft202012Validator.check_schema(dict(schema))
        kwargs: dict[str, Any] = {}
        if registry is not None:
            kwargs["registry"] = registry
            if base_uri:
                kwargs["_resolver"] = registry.resolver(base_uri)
        validator = Draft202012Validator(dict(schema), **kwargs)
        errors = sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(
                ("index", str(part)) if isinstance(part, int) else ("field", str(part))
                for part in item.absolute_path
            ),
        )
    except SchemaError as exc:
        raise _error(
            "plugin_schema_invalid",
            "plugin release contains an invalid JSON schema",
            status_code=409,
            validation_message=str(exc)[:500],
        ) from exc
    except Exception as exc:
        raise _error(
            "plugin_schema_unresolvable",
            "plugin JSON schema could not be resolved from packaged resources",
            status_code=409,
            error=type(exc).__name__,
        ) from exc
    if errors:
        raise _error(
            code,
            message,
            status_code=status_code,
            validation_message=_schema_error_message(errors[0]),
        )


def _apply_schema_defaults(value: Any, schema: Mapping[str, Any]) -> Any:
    """Materialize JSON Schema defaults into a copied configuration value.

    Defaults are annotations rather than validation behavior.  The host makes
    their application explicit and deterministic so every runner observes the
    same effective configuration.
    """

    normalized = copy.deepcopy(value)
    if isinstance(normalized, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if not isinstance(child_schema, dict):
                    continue
                if key not in normalized and "default" in child_schema:
                    normalized[key] = copy.deepcopy(child_schema["default"])
                if key in normalized:
                    normalized[key] = _apply_schema_defaults(normalized[key], child_schema)
    elif isinstance(normalized, list) and isinstance(schema.get("items"), dict):
        normalized = [_apply_schema_defaults(item, schema["items"]) for item in normalized]
    return normalized


def validate_configuration(manifest: Mapping[str, Any], configuration: Mapping[str, Any]) -> dict[str, Any]:
    schema = manifest.get("config_schema")
    if isinstance(schema, dict):
        normalized = _apply_schema_defaults(dict(configuration), schema)
        _validate_json_schema(
            normalized,
            schema,
            code="plugin_configuration_invalid",
            message="plugin configuration does not satisfy its JSON schema",
            status_code=400,
        )
        return normalized
    return dict(configuration)


def _validate_contract_value(
    value: Any,
    schema: Mapping[str, Any],
    *,
    kind: str,
    release: PluginRelease | None = None,
    schema_reference: Any = None,
) -> None:
    if not schema:
        return
    registry: Registry | None = None
    base_uri: str | None = None
    if release is not None and isinstance(schema_reference, str):
        registry = _release_schema_registry(release)
        base_uri = _release_schema_base(release) + schema_reference
    _validate_json_schema(
        value,
        schema,
        code=f"plugin_{kind}_schema_invalid",
        message=f"plugin {kind} does not satisfy its declared JSON schema",
        status_code=400 if kind == "input" else 502,
        registry=registry,
        base_uri=base_uri,
    )


def workflow_is_write(workflow: Mapping[str, Any]) -> bool:
    return str(workflow.get("mode") or "").casefold() in {
        "write", "write_snapshot", "migration", "artifact", "transaction",
    }


def workflow_required_ports(
    manifest: Mapping[str, Any], workflow: Mapping[str, Any],
) -> set[str]:
    raw = workflow.get("host_ports", workflow.get("required_host_ports"))
    if raw is None:
        return declared_host_ports(manifest)
    return {str(item) for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()


def execution_boundary(*, adapter: str) -> dict[str, Any]:
    built_in = adapter == "builtin_agent_package"
    return {
        "protocol": PLUGIN_HOST_PROTOCOL,
        "adapter": adapter,
        "execution_mode": adapter,
        "filesystem_isolation": False,
        "network_isolation": False,
        "secrets_isolation": False,
        "cpu_isolation": False,
        "memory_isolation": False,
        "native_process_is_sandbox": False,
        "in_process": built_in,
        "operator_process_opt_in_required": not built_in,
        "descendant_cleanup_guaranteed": built_in or platform.system().casefold() != "windows",
        "process_tree_boundary": (
            "learnflow_application_process"
            if built_in
            else (
                "posix_process_group"
                if platform.system().casefold() != "windows"
                else "windows_best_effort_process_group"
            )
        ),
        "host_port_call_limit": MAX_HOST_PORT_CALLS,
        "single_rpc_byte_limit": 256 * 1024,
        "total_output_byte_limit": MAX_TOOL_RESULT_BYTES,
        "disclosure": (
            "LearnFlow 内置 Agent Package；不启动外部插件进程"
            if built_in
            else "受信本机进程；签名不代表主机隔离"
        ),
    }


@dataclass
class PluginWorkflowResult:
    result: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"


HostPortHandler = Callable[["PluginWorkflowContext", dict[str, Any]], Any]
WorkflowHandler = Callable[["PluginWorkflowContext", dict[str, Any]], Any]
RunnerHook = Callable[["PluginWorkflowContext", str, dict[str, Any]], Any]

_HOST_PORT_HANDLERS: dict[str, HostPortHandler] = {}
_BUILTIN_WORKFLOWS: dict[tuple[str, str], WorkflowHandler] = {}
_EXTERNAL_RUNNER_HOOK: RunnerHook | None = None


def register_host_port(port_id: str, handler: HostPortHandler) -> None:
    if port_id not in HOST_PORT_POLICIES:
        raise ValueError(f"unknown Host Port: {port_id}")
    _HOST_PORT_HANDLERS[port_id] = handler


def register_builtin_workflow(
    plugin_id: str,
    workflow_id: str,
    handler: WorkflowHandler | None = None,
):
    """Register a repository-owned implementation without coupling the host to it."""

    def install(candidate: WorkflowHandler) -> WorkflowHandler:
        _BUILTIN_WORKFLOWS[(plugin_id, workflow_id)] = candidate
        return candidate

    return install(handler) if handler is not None else install


def register_external_runner_hook(hook: RunnerHook | None) -> None:
    global _EXTERNAL_RUNNER_HOOK
    _EXTERNAL_RUNNER_HOOK = hook


def _runtime_platform() -> str:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    os_name = {"darwin": "darwin", "linux": "linux", "windows": "windows"}.get(system, system)
    arch = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine, machine)
    return f"{os_name}-{arch}"


async def _default_external_runner(
    context: "PluginWorkflowContext",
    operation_id: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    platform_id = _runtime_platform()
    runner_map = dict((context.release.runner_artifacts or {}).get("runners") or {})
    descriptor = runner_map.get(platform_id)
    if not isinstance(descriptor, dict) or not descriptor.get("uri"):
        raise _error(
            "plugin_platform_unsupported",
            "plugin release has no runner for this host platform",
            status_code=409,
            platform=platform_id,
        )
    try:
        store = artifact_store()
        resources = dict((context.release.runner_artifacts or {}).get("resources") or {})
        runner_declarations = dict(context.manifest.get("runners") or {})
        runner_package_path = str(runner_declarations.get(platform_id) or "")
        package_entries = dict(resources)
        for declared_platform, package_path in runner_declarations.items():
            runner_descriptor = runner_map.get(declared_platform)
            if isinstance(runner_descriptor, dict):
                package_entries[str(package_path)] = runner_descriptor
        with tempfile.TemporaryDirectory(prefix="learnflow-plugin-package-") as temp_dir:
            materialized = store.materialize_package(
                package_entries,
                temp_dir,
                executable_paths=set(str(item) for item in runner_declarations.values()),
            )
            runner_path = materialized[runner_package_path]
            result = await PluginProcessBroker(PluginRunnerConfig.from_settings(settings)).run(
                runner_path,
                operation_id,
                input_data,
                declared_host_ports=sorted(declared_host_ports(context.manifest)),
                granted_host_ports=sorted(context.authorized_host_ports),
                host_port_handler=lambda port_id, payload: context.call_host_port(port_id, payload),
                trust_state=context.release.trust_state,
            )
    except (PluginRunnerError, PluginArtifactError) as exc:
        if isinstance(exc, PluginRunnerError):
            context.run.execution_boundary = dict(exc.boundary)
            raise _error(exc.code, exc.message, status_code=503, **exc.details) from exc
        raise _error(exc.code, exc.message, status_code=409) from exc
    context.run.execution_boundary = dict(result.execution_boundary)
    raw = result.result if isinstance(result.result, dict) else {"result": {"value": result.result}}
    combined = dict(raw)
    combined["events"] = [*list(combined.get("events") or []), *list(result.events)]
    return combined


register_external_runner_hook(_default_external_runner)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass
class PluginWorkflowContext:
    """Narrow runtime context.  Plugin handlers never receive ``db`` directly."""

    _db: AsyncSession
    current: CurrentLearner
    project: Project
    instance: PluginInstance
    release: PluginRelease
    run: PluginRun
    manifest: dict[str, Any]
    authorized_host_ports: frozenset[str]
    host_port_calls: int = 0
    host_reads: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def learner_id(self) -> int:
        return int(self.current.learner.id)

    @property
    def project_id(self) -> int:
        return int(self.project.id)

    async def call_host_port(self, port_id: str, input_data: dict[str, Any] | None = None) -> Any:
        if port_id not in self.authorized_host_ports:
            raise _error("host_port_not_granted", "workflow attempted an unauthorized Host Port", status_code=403, port_id=port_id)
        if self.host_port_calls >= MAX_HOST_PORT_CALLS:
            raise _error("host_port_budget_exhausted", "workflow exceeded its Host Port call budget", status_code=409)
        handler = _HOST_PORT_HANDLERS.get(port_id)
        if handler is None:
            raise _error("host_port_unavailable", "Host Port has no installed adapter", status_code=503, port_id=port_id)
        payload = dict(input_data or {})
        self.host_port_calls += 1
        await append_run_event(
            self._db, self.run, "host_port_request", "plugin_to_host",
            {"port_id": port_id, "request": _audit_payload(payload)},
        )
        result = await _maybe_await(handler(self, payload))
        _bounded(result, budget=MAX_HOST_PORT_RESULT_BYTES, label=f"Host Port {port_id} result")
        self._capture_host_read(port_id, result)
        await append_run_event(
            self._db, self.run, "host_port_result", "host_to_plugin",
            {"port_id": port_id, "result": _audit_payload(result)},
        )
        return result

    def _capture_host_read(self, port_id: str, result: Any) -> None:
        """Keep host-owned provenance for immutable inputs actually observed."""

        captured: list[dict[str, Any]] = []
        if port_id == "source.read.v1" and isinstance(result, dict):
            for source in list(result.get("sources") or []):
                if isinstance(source, dict):
                    captured.append({
                        "ref": str(source.get("ref") or ""),
                        "source_id": source.get("source_id"),
                        "source_version_id": source.get("source_version_id"),
                        "content_hash": str(source.get("content_hash") or ""),
                        "authority_tier": str(source.get("authority_tier") or ""),
                        "status": str(source.get("status") or ""),
                    })
        elif port_id == "knowledge_baseline.read.v1" and isinstance(result, dict):
            for packet in list(result.get("packets") or []):
                if isinstance(packet, dict):
                    captured.append({
                        "packet_id": packet.get("id"),
                        "policy_version": packet.get("policy_version"),
                        "source_version_refs": list(packet.get("source_version_refs") or []),
                    })
        elif port_id == "artifact.resolve.v1" and isinstance(result, dict):
            ref = result.get("ref")
            if isinstance(ref, dict):
                captured.append(dict(ref))
        if not captured:
            return
        bucket = self.host_reads.setdefault(port_id, [])
        known = {canonical_hash(item) for item in bucket}
        for item in captured:
            digest = canonical_hash(item)
            if digest not in known:
                bucket.append(item)
                known.add(digest)


async def append_run_event(
    db: AsyncSession,
    run: PluginRun,
    event_type: str,
    direction: str,
    payload: Mapping[str, Any] | None = None,
) -> PluginRunEvent:
    sequence = int((await db.execute(select(func.max(PluginRunEvent.sequence)).where(
        PluginRunEvent.run_id == run.id,
    ))).scalar_one_or_none() or 0) + 1
    event = PluginRunEvent(
        run_id=run.id,
        sequence=sequence,
        event_type=event_type,
        direction=direction,
        payload=dict(payload or {}),
    )
    db.add(event)
    await db.flush()
    return event


async def require_owned_instance(
    db: AsyncSession,
    learner_id: int,
    project_id: int,
    plugin_id: str,
) -> PluginInstance:
    instance = (await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == learner_id,
        PluginInstance.project_id == project_id,
        PluginInstance.plugin_id == plugin_id,
    ))).scalar_one_or_none()
    if not instance:
        raise _error("plugin_instance_not_found", "project plugin instance was not found", status_code=404)
    return instance


async def _require_release_runnable(db: AsyncSession, release: PluginRelease) -> None:
    if release.status != "active" or release.revoked_at is not None:
        raise _error("plugin_release_unavailable", "plugin release is revoked or inactive", status_code=409)
    if release.trust_state not in {"trusted_signed", "untrusted_development", "built_in"}:
        raise _error("plugin_release_untrusted", "plugin release is not runnable", status_code=403)
    if release.publisher_id is not None and release.trust_state != "built_in":
        publisher = await db.get(PluginPublisher, release.publisher_id)
        if not publisher or publisher.trust_status == "revoked" or publisher.revoked_at is not None:
            raise _error("plugin_publisher_revoked", "plugin publisher is no longer trusted", status_code=403)
        if release.trust_state == "trusted_signed" and publisher.trust_status != "trusted":
            raise _error("plugin_publisher_untrusted", "signed production releases require a trusted publisher", status_code=403)


def publisher_view(row: PluginPublisher) -> dict[str, Any]:
    return {
        "id": row.id,
        "publisher_key": row.publisher_key,
        "display_name": row.display_name,
        "key_id": row.key_id,
        "trust_status": row.trust_status,
        "revoked_reason": row.revoked_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def release_view(row: PluginRelease) -> dict[str, Any]:
    manifest = dict(row.manifest or {})
    workflow_ids = {
        str(item.get("id") or "") for item in _manifest_items(manifest, "workflows")
    }
    built_in = bool(workflow_ids) and all(
        (row.plugin_id, workflow_id) in _BUILTIN_WORKFLOWS
        for workflow_id in workflow_ids
    )
    return {
        "id": row.id,
        "plugin_id": row.plugin_id,
        "version": row.version,
        "package_protocol": row.package_protocol,
        "root_hash": row.root_hash,
        "trust_state": row.trust_state,
        "status": row.status,
        "publisher_id": row.publisher_id,
        "name": manifest.get("name", row.plugin_id),
        "description": manifest.get("description", ""),
        "owner": manifest.get("owner"),
        "host_ports": sorted(declared_host_ports(manifest)),
        "config_schema": dict(manifest.get("config_schema") or {}),
        "workflows": _manifest_items(manifest, "workflows"),
        "tools": _manifest_items(manifest, "tools"),
        "execution_boundary": execution_boundary(
            adapter="builtin_agent_package"
            if built_in or row.trust_state == "built_in"
            else "trusted_signed_process"
        ),
        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "deprecated_at": row.deprecated_at.isoformat() if row.deprecated_at else None,
    }


async def available_plugin_releases(db: AsyncSession) -> list[PluginRelease]:
    """Return only operator-installed releases that a project may enable."""

    rows = list((await db.execute(select(PluginRelease).where(
        PluginRelease.status == "active",
        PluginRelease.revoked_at.is_(None),
    ).order_by(PluginRelease.plugin_id, PluginRelease.imported_at.desc()))).scalars().all())
    output: list[PluginRelease] = []
    for row in rows:
        try:
            await _require_release_runnable(db, row)
        except PluginHostError:
            continue
        output.append(row)
    return output


def instance_view(row: PluginInstance, release: PluginRelease | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "plugin_id": row.plugin_id,
        "project_id": row.project_id,
        "learner_id": row.learner_id,
        "status": row.status,
        "release_id": row.release_id,
        "release": release_view(release) if release is not None else None,
        "configuration": dict(row.configuration or {}),
        "granted_host_ports": list(row.granted_host_ports or []),
        "current_snapshot_id": row.current_snapshot_id,
        "disabled_at": row.disabled_at.isoformat() if row.disabled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def object_ref(
    instance: PluginInstance,
    snapshot: PluginSnapshot,
    item: PluginObjectIndex,
) -> dict[str, Any]:
    return {
        "protocol": PLUGIN_OBJECT_REF_PROTOCOL,
        "plugin_id": instance.plugin_id,
        "instance_id": instance.id,
        "snapshot_id": snapshot.id,
        "snapshot_root_hash": snapshot.root_hash,
        "object_type": item.object_type,
        "object_id": item.object_id,
        "schema_version": item.schema_version,
        "content_hash": item.content_hash,
    }


def object_index_view(
    instance: PluginInstance,
    snapshot: PluginSnapshot,
    item: PluginObjectIndex,
) -> dict[str, Any]:
    return {
        "ref": object_ref(instance, snapshot, item),
        "label": item.label,
        "lifecycle": item.lifecycle,
        "references": list(item.references or []),
        "locator": {"component": item.component, "json_pointer": item.json_pointer},
    }


def _components_by_name(snapshot: PluginSnapshot) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): dict(item)
        for item in list(snapshot.components or [])
        if isinstance(item, dict) and item.get("name")
    }


def _read_json_component(snapshot: PluginSnapshot, component_name: str) -> Any:
    descriptor = _components_by_name(snapshot).get(component_name)
    if not descriptor or not descriptor.get("uri"):
        raise _error("snapshot_component_not_found", "snapshot component does not exist", status_code=404)
    try:
        return json.loads(artifact_store().read(str(descriptor["uri"])).decode("utf-8"))
    except (PluginArtifactError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("snapshot_component_invalid", "snapshot component cannot be resolved", status_code=409) from exc


def _release_schema(release: PluginRelease, declaration: Any) -> dict[str, Any]:
    if isinstance(declaration, dict):
        return dict(declaration)
    if not isinstance(declaration, str) or not declaration:
        return {}
    descriptor = dict((release.runner_artifacts or {}).get("resources") or {}).get(declaration)
    if not isinstance(descriptor, dict) or not descriptor.get("uri"):
        raise _error(
            "plugin_schema_missing",
            "declared plugin schema is missing from release resources",
            status_code=409,
            schema=declaration,
        )
    try:
        value = json.loads(artifact_store().read(str(descriptor["uri"])).decode("utf-8"))
    except (PluginArtifactError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(
            "plugin_schema_invalid",
            "declared plugin schema cannot be read from release resources",
            status_code=409,
            schema=declaration,
        ) from exc
    if not isinstance(value, dict):
        raise _error(
            "plugin_schema_invalid",
            "declared plugin schema must be a JSON object",
            status_code=409,
            schema=declaration,
        )
    return dict(value)


def _release_schema_base(release: PluginRelease) -> str:
    return f"https://schemas.learnflow.invalid/{release.root_hash}/"


def _release_schema_registry(release: PluginRelease) -> Registry:
    """Build an offline-only registry for schemas stored in this release."""

    registry: Registry = Registry()
    resources = dict((release.runner_artifacts or {}).get("resources") or {})
    for path, descriptor in resources.items():
        if not str(path).startswith("schemas/") or not str(path).endswith(".json"):
            continue
        if not isinstance(descriptor, dict) or not descriptor.get("uri"):
            raise _error(
                "plugin_schema_missing",
                "packaged schema descriptor is missing",
                status_code=409,
                schema=path,
            )
        try:
            document = json.loads(
                artifact_store().read(str(descriptor["uri"])).decode("utf-8")
            )
            if not isinstance(document, dict):
                raise ValueError("schema must be an object")
            resource = Resource.from_contents(
                document,
                default_specification=DRAFT202012,
            )
        except (PluginArtifactError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise _error(
                "plugin_schema_invalid",
                "packaged schema cannot be loaded",
                status_code=409,
                schema=path,
            ) from exc
        registry = registry.with_resource(
            _release_schema_base(release) + str(path),
            resource,
        )
    return registry


def _json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise _error("invalid_json_pointer", "object index contains an invalid JSON pointer", status_code=409)
    current = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(token)] if isinstance(current, list) else current[token]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise _error("object_locator_invalid", "object index no longer resolves inside its snapshot", status_code=409) from exc
    return current


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _decode_candidate_json(value: Any) -> Any | None:
    """Decode JSON-like component input; opaque components are not indexed."""

    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return json.loads(bytes(value).decode("utf-8"))
        if isinstance(value, str):
            return json.loads(value)
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _derive_object_locators(
    components: Mapping[str, Any],
    *,
    declared_types: set[str],
    schema_version: str,
) -> list[dict[str, Any]]:
    """Derive the complete rebuildable object index from component truth.

    Plugins may provide locators as a candidate contract, but they do not
    decide which domain objects become visible.  Every JSON object carrying a
    declared ``type``/``object_type`` and stable identity is indexed by this
    deterministic traversal.
    """

    derived: list[dict[str, Any]] = []
    seen: dict[str, tuple[str, str]] = {}

    def visit(component: str, value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            object_id = str(value.get("id") or value.get("object_id") or "")
            object_type = str(value.get("object_type") or value.get("type") or "")
            if object_id and object_type in declared_types:
                if object_id in seen:
                    previous_component, previous_pointer = seen[object_id]
                    raise _error(
                        "duplicate_plugin_object_id",
                        "plugin object ids must be unique across snapshot components",
                        status_code=409,
                        object_id=object_id,
                        first={"component": previous_component, "json_pointer": previous_pointer},
                        duplicate={"component": component, "json_pointer": pointer},
                    )
                seen[object_id] = (component, pointer)
                if value.get("references") is not None:
                    references = value.get("references")
                elif object_type == "semantic_edge":
                    references = [item for item in (value.get("source"), value.get("target")) if item]
                else:
                    references = value.get("evidence_refs") or []
                if not isinstance(references, list):
                    raise _error(
                        "invalid_plugin_object_references",
                        "plugin object references must be a JSON array",
                        status_code=409,
                        object_id=object_id,
                    )
                derived.append({
                    "id": object_id,
                    "type": object_type,
                    "label": str(value.get("label") or value.get("title") or value.get("name") or ""),
                    "schema_version": str(value.get("schema_version") or schema_version),
                    "component": component,
                    "json_pointer": pointer,
                    "content_hash": canonical_hash(value),
                    "lifecycle": str(value.get("lifecycle") or "active"),
                    "references": list(references),
                })
            for key, child in value.items():
                visit(component, child, f"{pointer}/{_json_pointer_token(str(key))}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(component, child, f"{pointer}/{index}")

    for component in sorted(str(item) for item in components):
        decoded = _decode_candidate_json(components[component])
        if isinstance(decoded, (dict, list)):
            visit(component, decoded, "")
    return derived


def resolve_indexed_object(snapshot: PluginSnapshot, item: PluginObjectIndex) -> Any:
    value = _json_pointer(_read_json_component(snapshot, item.component), item.json_pointer)
    if canonical_hash(value) != item.content_hash:
        raise _error("object_content_hash_mismatch", "resolved plugin object does not match its immutable reference", status_code=409)
    return value


def snapshot_view(snapshot: PluginSnapshot, *, include_component_data: bool = False) -> dict[str, Any]:
    components: Any = list(snapshot.components or [])
    if include_component_data:
        materialized: dict[str, Any] = {}
        used = 0
        for name, descriptor in _components_by_name(snapshot).items():
            if not str(descriptor.get("media_type", "")).startswith("application/json"):
                continue
            try:
                data = artifact_store().read(str(descriptor["uri"]))
                if used + len(data) > MAX_TOOL_RESULT_BYTES:
                    continue
                materialized[name] = json.loads(data.decode("utf-8"))
                used += len(data)
            except (PluginArtifactError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
                continue
        components = materialized
    return {
        "id": snapshot.id,
        "instance_id": snapshot.instance_id,
        "release_id": snapshot.release_id,
        "parent_snapshot_id": snapshot.parent_snapshot_id,
        "version": snapshot.version,
        "schema_version": snapshot.schema_version,
        "root_hash": snapshot.root_hash,
        "components": components,
        "source_refs": list(snapshot.source_refs or []),
        "validation": dict(snapshot.validation or {}),
        "provenance": dict(snapshot.provenance or {}),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def materialize_snapshot_input(snapshot: PluginSnapshot) -> dict[str, Any]:
    """Return the exact immutable snapshot projection passed to one runner."""

    components: dict[str, Any] = {}
    total = 0
    store = artifact_store()
    for name, descriptor in _components_by_name(snapshot).items():
        uri = str(descriptor.get("uri") or "")
        try:
            raw = store.read(uri)
        except PluginArtifactError as exc:
            raise _error(exc.code, exc.message, status_code=409) from exc
        total += len(raw)
        if total > MAX_TOOL_RESULT_BYTES:
            raise _error("snapshot_projection_too_large", "fixed snapshot exceeds the runner input budget", status_code=413)
        if str(descriptor.get("media_type") or "").startswith("application/json"):
            try:
                components[name] = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _error("snapshot_component_invalid", "JSON snapshot component cannot be decoded", status_code=409, component=name) from exc
        else:
            components[name] = {"artifact": dict(descriptor), "inline": False}
    return {
        "id": snapshot.id,
        "instance_id": snapshot.instance_id,
        "release_id": snapshot.release_id,
        "parent_snapshot_id": snapshot.parent_snapshot_id,
        "version": snapshot.version,
        "schema_version": snapshot.schema_version,
        "root_hash": snapshot.root_hash,
        "components": components,
        "source_refs": list(snapshot.source_refs or []),
        "validation": dict(snapshot.validation or {}),
        "provenance": dict(snapshot.provenance or {}),
    }


async def run_view(db: AsyncSession, run: PluginRun) -> dict[str, Any]:
    events = list((await db.execute(select(PluginRunEvent).where(
        PluginRunEvent.run_id == run.id,
    ).order_by(PluginRunEvent.sequence))).scalars().all())
    return {
        "id": run.id,
        "learner_id": run.learner_id,
        "project_id": run.project_id,
        "instance_id": run.instance_id,
        "release_id": run.release_id,
        "invocation_kind": run.invocation_kind,
        "operation_id": run.operation_id,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "request_hash": run.request_hash,
        "expected_snapshot_id": run.expected_snapshot_id,
        "result_snapshot_id": run.result_snapshot_id,
        "result": dict(run.result or {}),
        "contract": dict(run.contract or {}),
        "execution_boundary": dict(run.execution_boundary or {}),
        "error": dict(run.error or {}),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "events": [
            {
                "sequence": item.sequence,
                "event_type": item.event_type,
                "direction": item.direction,
                "payload": item.payload,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in events
        ],
    }


async def import_plugin_release(
    db: AsyncSession,
    package_bytes: bytes,
    *,
    filename: str = "plugin.lfplugin",
) -> tuple[PluginRelease, bool]:
    publishers = list((await db.execute(select(PluginPublisher))).scalars().all())
    trusted = [
        TrustedPublisher(
            publisher_id=item.publisher_key,
            key_id=item.key_id,
            public_key=item.public_key,
            trusted=item.trust_status == "trusted",
            revoked=item.revoked_at is not None or item.trust_status == "revoked",
        )
        for item in publishers
    ]
    environment = str(getattr(settings, "plugin_environment", "") or "").strip() or (
        "development" if settings.dev_test_login_enabled else "production"
    )
    policy = PackagePolicy(
        environment=environment,
        allow_unsigned_development=bool(getattr(settings, "plugin_allow_unsigned_dev", False)),
    )
    try:
        loaded = load_plugin_package(package_bytes, policy=policy, publishers=trusted)
    except PluginPackageError as exc:
        raise _error(exc.code, exc.message, status_code=400, **exc.details) from exc

    projection_issues = validate_plugin_manifest_projection(loaded.manifest)
    if projection_issues:
        raise _error(
            "plugin_registry_projection_invalid",
            "plugin manifest cannot contribute a safe namespaced registry projection",
            status_code=409,
            issues=projection_issues,
        )

    compatibility = dict(loaded.manifest.get("host_compatibility") or {})
    if compatibility.get("plugin_host") != PLUGIN_HOST_PROTOCOL:
        raise _error(
            "plugin_host_incompatible",
            "plugin release targets a different host protocol",
            status_code=409,
            required=compatibility.get("plugin_host"),
            current=PLUGIN_HOST_PROTOCOL,
        )
    try:
        compatible = semver_satisfies(settings.app_version, str(compatibility.get("learnflow") or ""))
    except PluginPackageError as exc:
        raise _error(exc.code, exc.message, status_code=400, **exc.details) from exc
    if not compatible:
        raise _error(
            "learnflow_version_incompatible",
            "plugin release is not compatible with this LearnFlow version",
            status_code=409,
            required=compatibility.get("learnflow"),
            current=settings.app_version,
        )

    existing = (await db.execute(select(PluginRelease).where(
        PluginRelease.plugin_id == loaded.plugin_id,
        PluginRelease.version == loaded.version,
    ))).scalar_one_or_none()
    if existing:
        if existing.root_hash != loaded.root_hash:
            raise _error("release_version_conflict", "plugin version already exists with different content", status_code=409)
        return existing, True

    store = artifact_store()
    archive = store.put_bytes(package_bytes, media_type="application/vnd.learnflow.plugin+zip", name=filename)
    runner_descriptors: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    runner_paths = set(dict(loaded.manifest.get("runners") or {}).values())
    for path, entry in loaded.entries.items():
        if path in {"manifest.json", "signature.json"}:
            continue
        descriptor = store.put_bytes(
            entry.content,
            media_type="application/json" if path.endswith(".json") else "application/octet-stream",
            name=path,
            expected_sha256=entry.sha256,
        ).to_dict()
        if path in runner_paths:
            platform = next(key for key, value in loaded.manifest["runners"].items() if value == path)
            runner_descriptors[platform] = descriptor
        else:
            resources[path] = descriptor
    publisher = next((item for item in publishers if item.publisher_key == loaded.signature.get("publisher_id") and item.key_id == loaded.signature.get("key_id")), None)
    release = PluginRelease(
        publisher_id=publisher.id if publisher else None,
        plugin_id=loaded.plugin_id,
        version=loaded.version,
        package_protocol=str(loaded.manifest.get("protocol")),
        manifest=dict(loaded.manifest),
        signature=dict(loaded.signature),
        root_hash=loaded.root_hash,
        package_artifact_uri=archive.uri,
        runner_artifacts={
            "archive": archive.to_dict(),
            "archive_sha256": loaded.archive_sha256,
            "runners": runner_descriptors,
            "resources": resources,
        },
        trust_state=loaded.trust_state,
        status="active",
    )
    db.add(release)
    await db.flush()
    return release, False


async def enable_plugin_instance(
    db: AsyncSession,
    current: CurrentLearner,
    project: Project,
    *,
    plugin_id: str,
    release_id: int,
    configuration: Mapping[str, Any] | None = None,
    granted_host_ports: Iterable[str] = (),
) -> tuple[PluginInstance, bool]:
    release = await db.get(PluginRelease, release_id)
    if not release or release.plugin_id != plugin_id:
        raise _error("plugin_release_not_found", "release does not belong to the requested plugin", status_code=404)
    await _require_release_runnable(db, release)
    grants = validate_host_port_grants(release.manifest or {}, granted_host_ports)
    normalized_configuration = validate_configuration(release.manifest or {}, configuration or {})
    existing = (await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == current.learner.id,
        PluginInstance.project_id == project.id,
        PluginInstance.plugin_id == plugin_id,
    ))).scalar_one_or_none()
    if existing:
        if existing.release_id != release.id and existing.current_snapshot_id is not None:
            raise _error("plugin_upgrade_required", "an instance with snapshots must use the upgrade workflow", status_code=409)
        existing.release_id = release.id
        existing.configuration = normalized_configuration
        existing.granted_host_ports = grants
        existing.status = "enabled"
        existing.disabled_at = None
        await db.flush()
        await record_event(
            db,
            learner_id=current.learner.id,
            project_id=project.id,
            event_type="plugin_instance_enabled",
            source="plugin_host",
            payload={
                "plugin_id": plugin_id,
                "plugin_instance_id": existing.id,
                "release_id": release.id,
                "mastery_unchanged": True,
            },
            provenance={"host_protocol": PLUGIN_HOST_PROTOCOL, "kernel_targets": []},
            client_event_id=f"plugin-instance:{existing.id}:release:{release.id}:enabled",
        )
        return existing, True
    instance = PluginInstance(
        learner_id=current.learner.id,
        project_id=project.id,
        plugin_id=plugin_id,
        release_id=release.id,
        status="enabled",
        configuration=normalized_configuration,
        granted_host_ports=grants,
    )
    db.add(instance)
    await db.flush()
    await record_event(
        db,
        learner_id=current.learner.id,
        project_id=project.id,
        event_type="plugin_instance_enabled",
        source="plugin_host",
        payload={
            "plugin_id": plugin_id,
            "plugin_instance_id": instance.id,
            "release_id": release.id,
            "mastery_unchanged": True,
        },
        provenance={"host_protocol": PLUGIN_HOST_PROTOCOL, "kernel_targets": []},
        client_event_id=f"plugin-instance:{instance.id}:release:{release.id}:enabled",
    )
    return instance, False


async def update_plugin_instance(
    db: AsyncSession,
    instance: PluginInstance,
    *,
    current: CurrentLearner | None = None,
    project: Project | None = None,
    status: str | None = None,
    configuration: Mapping[str, Any] | None = None,
    granted_host_ports: Iterable[str] | None = None,
) -> PluginInstance:
    release = await db.get(PluginRelease, instance.release_id)
    if not release:
        raise _error("plugin_release_not_found", "pinned plugin release is missing", status_code=409)
    previous_status = instance.status
    if status is not None:
        if status not in {"enabled", "disabled"}:
            raise _error("invalid_instance_status", "plugin instance status must be enabled or disabled")
        instance.status = status
        instance.disabled_at = datetime.utcnow() if status == "disabled" else None
    if configuration is not None:
        instance.configuration = validate_configuration(release.manifest or {}, configuration)
    if granted_host_ports is not None:
        instance.granted_host_ports = validate_host_port_grants(release.manifest or {}, granted_host_ports)
    await db.flush()
    if (
        status is not None
        and status != previous_status
        and current is not None
        and project is not None
    ):
        await record_event(
            db,
            learner_id=current.learner.id,
            project_id=project.id,
            event_type=(
                "plugin_instance_disabled" if status == "disabled"
                else "plugin_instance_enabled"
            ),
            source="plugin_host",
            payload={
                "plugin_id": instance.plugin_id,
                "plugin_instance_id": instance.id,
                "release_id": instance.release_id,
                "mastery_unchanged": True,
            },
            provenance={"host_protocol": PLUGIN_HOST_PROTOCOL, "kernel_targets": []},
            client_event_id=(
                f"plugin-instance:{instance.id}:{status}:"
                f"{instance.updated_at.isoformat() if instance.updated_at else instance.release_id}"
            ),
        )
    return instance


def _normalize_result(raw: Any) -> PluginWorkflowResult:
    if isinstance(raw, PluginWorkflowResult):
        return raw
    if not isinstance(raw, dict):
        raise _error("invalid_plugin_result", "plugin handler must return a JSON object", status_code=502)
    if any(key in raw for key in ("result", "snapshot", "events")):
        result_payload = dict(raw.get("result") or {})
        return PluginWorkflowResult(
            result=result_payload,
            snapshot=dict(raw["snapshot"]) if isinstance(raw.get("snapshot"), dict) else None,
            events=[dict(item) for item in raw.get("events", []) if isinstance(item, dict)],
            status=str(raw.get("status") or result_payload.get("status") or "completed"),
        )
    return PluginWorkflowResult(result=dict(raw))


async def _create_snapshot(
    db: AsyncSession,
    instance: PluginInstance,
    release: PluginRelease,
    run: PluginRun,
    candidate: Mapping[str, Any],
    *,
    host_reads: Mapping[str, list[dict[str, Any]]] | None = None,
    effective_configuration: Mapping[str, Any] | None = None,
) -> PluginSnapshot:
    schema_version = str(candidate.get("schema_version") or release.manifest.get("schema_version") or "")
    if not schema_version:
        raise _error("snapshot_schema_missing", "plugin snapshot requires a schema version", status_code=502)
    plugin_validation = dict(candidate.get("validation") or {})
    if plugin_validation.get("valid") is False or plugin_validation.get("errors"):
        raise _error("snapshot_validation_failed", "plugin candidate reported validation failures", status_code=409, errors=plugin_validation.get("errors", []))
    raw_components = candidate.get("components")
    objects = candidate.get("objects")
    if not isinstance(raw_components, dict) or not isinstance(objects, list):
        raise _error("invalid_snapshot_candidate", "snapshot components must be an object and objects must be a list", status_code=502)
    declared_types = {str(item) for item in release.manifest.get("object_types", []) if isinstance(item, str)}
    normalized_objects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in objects:
        if not isinstance(raw, dict):
            raise _error("invalid_plugin_object_locator", "snapshot object locators must be JSON objects", status_code=502)
        object_id = str(raw.get("id") or raw.get("object_id") or "")
        object_type = str(raw.get("object_type") or raw.get("type") or "")
        component = str(raw.get("component") or "")
        pointer = str(raw.get("json_pointer") or "")
        content_hash = str(raw.get("content_hash") or "")
        if (
            not object_id
            or object_id in seen_ids
            or object_type not in declared_types
            or not component
            or (pointer != "" and not pointer.startswith("/"))
            or not re.fullmatch(r"[0-9a-f]{64}", content_hash)
        ):
            raise _error("invalid_plugin_object_locator", "plugin object identity, locator or hash is invalid", status_code=409, object_id=object_id, object_type=object_type)
        seen_ids.add(object_id)
        normalized_objects.append({**dict(raw), "id": object_id, "type": object_type, "component": component, "json_pointer": pointer, "content_hash": content_hash})

    # The plugin locator list is only a candidate contract.  The host scans
    # every JSON component and derives the complete index so an object cannot
    # be hidden or redirected by omitting/changing a locator.
    validated_objects = _derive_object_locators(
        raw_components,
        declared_types=declared_types,
        schema_version=schema_version,
    )
    candidate_by_id = {item["id"]: item for item in normalized_objects}
    derived_by_id = {item["id"]: item for item in validated_objects}
    if set(candidate_by_id) != set(derived_by_id):
        raise _error(
            "plugin_object_index_incomplete",
            "plugin locator set must exactly match the objects derived from component truth",
            status_code=409,
            missing=sorted(set(derived_by_id) - set(candidate_by_id)),
            extra=sorted(set(candidate_by_id) - set(derived_by_id)),
        )
    for object_id, derived in derived_by_id.items():
        candidate_locator = candidate_by_id[object_id]
        if any(
            candidate_locator[field] != derived[field]
            for field in ("type", "component", "json_pointer", "content_hash")
        ) or (
            candidate_locator.get("schema_version") is not None
            and str(candidate_locator["schema_version"]) != derived["schema_version"]
        ):
            raise _error(
                "plugin_object_locator_mismatch",
                "plugin locator identity or content hash does not match host-derived truth",
                status_code=409,
                object_id=object_id,
            )
    try:
        commit = artifact_store().commit_components(raw_components)
    except PluginArtifactError as exc:
        raise _error(exc.code, exc.message, status_code=409) from exc
    claimed_hash = str(candidate.get("root_hash") or "")
    if claimed_hash and claimed_hash != commit.root_hash:
        raise _error("snapshot_root_hash_mismatch", "plugin-provided root hash does not match host materialization", status_code=409)

    await db.refresh(instance, attribute_names=["current_snapshot_id"])
    current_id = instance.current_snapshot_id
    if run.expected_snapshot_id != current_id:
        raise _error("snapshot_conflict", "current plugin snapshot changed while the workflow was running", status_code=409, expected=run.expected_snapshot_id, current=current_id)
    parent_snapshot = await db.get(PluginSnapshot, current_id) if current_id else None

    def normalize_source_refs(values: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        known: set[str] = set()
        for raw in list(values or []):
            if not isinstance(raw, dict):
                raise _error(
                    "snapshot_source_ref_invalid",
                    "snapshot source references must be fixed JSON objects",
                    status_code=409,
                )
            item = {
                "ref": str(raw.get("ref") or ""),
                "source_id": raw.get("source_id"),
                "source_version_id": raw.get("source_version_id"),
                "content_hash": str(raw.get("content_hash") or ""),
                "authority_tier": str(raw.get("authority_tier") or ""),
                "status": str(raw.get("status") or ""),
            }
            if not item["ref"]:
                raise _error(
                    "snapshot_source_ref_invalid",
                    "snapshot source references require a fixed ref",
                    status_code=409,
                )
            digest = canonical_hash(item)
            if digest not in known:
                normalized.append(item)
                known.add(digest)
        return normalized

    admitted_refs = normalize_source_refs(parent_snapshot.source_refs if parent_snapshot else [])
    admitted_hashes = {canonical_hash(item) for item in admitted_refs}
    for item in normalize_source_refs(dict(host_reads or {}).get("source.read.v1", [])):
        digest = canonical_hash(item)
        if digest not in admitted_hashes:
            admitted_refs.append(item)
            admitted_hashes.add(digest)
    claimed_refs = normalize_source_refs(candidate.get("source_refs") or [])
    claimed_hashes = {canonical_hash(item) for item in claimed_refs}
    if claimed_hashes != admitted_hashes:
        raise _error(
            "snapshot_source_ref_unverified",
            "snapshot source references must exactly match fixed sources read by the host or inherited from the base snapshot",
            status_code=409,
            missing=sorted(admitted_hashes - claimed_hashes),
            unverified=sorted(claimed_hashes - admitted_hashes),
        )

    plugin_provenance = dict(candidate.get("provenance") or {})
    component_manifest = commit.to_manifest()
    snapshot_root_hash = canonical_hash({
        "protocol": "learnflow.plugin-snapshot-envelope.v1",
        "plugin_id": instance.plugin_id,
        "release_root_hash": release.root_hash,
        "schema_version": schema_version,
        "component_root_hash": commit.root_hash,
        "components": component_manifest,
        "source_refs": admitted_refs,
        "configuration": dict(effective_configuration or {}),
        "validation": plugin_validation,
        "plugin_provenance": plugin_provenance,
    })
    existing = (await db.execute(select(PluginSnapshot).where(
        PluginSnapshot.instance_id == instance.id,
        PluginSnapshot.root_hash == snapshot_root_hash,
    ))).scalar_one_or_none()
    if existing:
        if existing.id != current_id:
            raise _error(
                "snapshot_history_rewind_forbidden",
                "a write workflow cannot move the instance back to an older snapshot root",
                status_code=409,
                existing_snapshot_id=existing.id,
                current_snapshot_id=current_id,
            )
        return existing
    version = int((await db.execute(select(func.max(PluginSnapshot.version)).where(
        PluginSnapshot.instance_id == instance.id,
    ))).scalar_one_or_none() or 0) + 1
    snapshot = PluginSnapshot(
        instance_id=instance.id,
        release_id=release.id,
        parent_snapshot_id=current_id,
        version=version,
        schema_version=schema_version,
        root_hash=snapshot_root_hash,
        components=component_manifest,
        source_refs=admitted_refs,
        validation=plugin_validation,
        provenance={
            "plugin": plugin_provenance,
            "host": {
                "run_id": run.id,
                "plugin_id": instance.plugin_id,
                "release_id": release.id,
                "release_root_hash": release.root_hash,
                "component_root_hash": commit.root_hash,
                "host_protocol": PLUGIN_HOST_PROTOCOL,
                "configuration": dict(effective_configuration or {}),
                "reads": dict(host_reads or {}),
            },
        },
    )
    db.add(snapshot)
    await db.flush()
    for item in validated_objects:
        db.add(PluginObjectIndex(
            snapshot_id=snapshot.id,
            plugin_id=instance.plugin_id,
            object_type=item["type"],
            object_id=item["id"],
            label=str(item.get("label") or "")[:500],
            schema_version=str(item.get("schema_version") or schema_version),
            component=item["component"],
            json_pointer=item["json_pointer"],
            content_hash=item["content_hash"],
            lifecycle=str(item.get("lifecycle") or "active")[:30],
            references=list(item.get("references") or []),
        ))
    await db.flush()
    snapshot.validation = {
        **plugin_validation,
        "valid": True,
        "host_checks": [
            "components_content_addressed",
            "root_hash_recomputed",
            "object_locators_resolved",
            "object_identity_and_content_hash_verified",
            "object_types_declared",
            "source_refs_derived_from_host_reads",
            "snapshot_envelope_hash_recomputed",
        ],
        "component_root_hash": commit.root_hash,
        "snapshot_root_hash": snapshot_root_hash,
        "plugin_report": plugin_validation,
    }
    instance.current_snapshot_id = snapshot.id
    return snapshot


async def rebuild_snapshot_object_index(
    db: AsyncSession,
    snapshot: PluginSnapshot,
) -> int:
    """Rebuild locator rows solely from immutable snapshot components.

    This maintenance operation never edits component bytes or moves an
    instance pointer.  It is safe to replay after index loss or corruption.
    """

    release = await db.get(PluginRelease, snapshot.release_id)
    if not release:
        raise _error(
            "plugin_release_not_found",
            "snapshot release is missing; object index cannot be rebuilt",
            status_code=409,
        )
    component_values: dict[str, bytes] = {}
    store = artifact_store()
    for name, descriptor in _components_by_name(snapshot).items():
        try:
            component_values[name] = store.read(str(descriptor.get("uri") or ""))
        except PluginArtifactError as exc:
            raise _error(exc.code, exc.message, status_code=409) from exc
    locators = _derive_object_locators(
        component_values,
        declared_types={
            str(item)
            for item in list((release.manifest or {}).get("object_types") or [])
            if isinstance(item, str)
        },
        schema_version=snapshot.schema_version,
    )
    async with db.begin_nested():
        await db.execute(delete(PluginObjectIndex).where(
            PluginObjectIndex.snapshot_id == snapshot.id,
        ))
        for item in locators:
            db.add(PluginObjectIndex(
                snapshot_id=snapshot.id,
                plugin_id=release.plugin_id,
                object_type=item["type"],
                object_id=item["id"],
                label=str(item.get("label") or "")[:500],
                schema_version=str(item.get("schema_version") or snapshot.schema_version),
                component=item["component"],
                json_pointer=item["json_pointer"],
                content_hash=item["content_hash"],
                lifecycle=str(item.get("lifecycle") or "active")[:30],
                references=list(item.get("references") or []),
            ))
        await db.flush()
    return len(locators)


async def _emit_plugin_events(
    db: AsyncSession,
    context: PluginWorkflowContext,
    events: list[dict[str, Any]],
) -> None:
    declarations = {str(item.get("id")): item for item in _manifest_items(context.manifest, "events")}
    for offset, event in enumerate(events):
        event_id = str(event.get("id") or event.get("event_type") or event.get("type") or "")
        declaration = declarations.get(event_id)
        targets = declaration.get("kernel_targets", declaration.get("target_kernels", [])) if declaration else None
        if not declaration or targets not in (None, []):
            raise _error("plugin_event_forbidden", "plugin emitted an undeclared or kernel-targeted event", status_code=409, event_id=event_id)
        await record_event(
            db,
            learner_id=context.learner_id,
            project_id=context.project_id,
            event_type=f"plugin:{context.instance.plugin_id}:{event_id}",
            source="plugin_host",
            payload={**dict(event.get("payload") or {}), "plugin_id": context.instance.plugin_id, "run_id": context.run.id, "mastery_unchanged": True},
            provenance={"release_id": context.release.id, "plugin_root_hash": context.release.root_hash, "host_protocol": PLUGIN_HOST_PROTOCOL},
            client_event_id=f"plugin-run:{context.run.id}:event:{offset}:{event_id}",
        )


async def execute_plugin_operation(
    db: AsyncSession,
    current: CurrentLearner,
    project: Project,
    instance: PluginInstance,
    *,
    operation_id: str,
    input_data: Mapping[str, Any],
    idempotency_key: str,
    expected_snapshot_id: int | None,
    invocation_kind: str = "workflow",
    require_expected_snapshot: bool = True,
    expected_snapshot_provided: bool = True,
    release_override: PluginRelease | None = None,
    granted_ports_override: Iterable[str] | None = None,
    switch_release_on_success: bool = False,
    configuration_on_success: Mapping[str, Any] | None = None,
) -> tuple[PluginRun, bool]:
    if instance.status != "enabled":
        raise _error("plugin_instance_disabled", "plugin instance is disabled", status_code=409)
    release = release_override or await db.get(PluginRelease, instance.release_id)
    if not release:
        raise _error("plugin_release_not_found", "pinned plugin release is missing", status_code=409)
    if release.plugin_id != instance.plugin_id:
        raise _error("plugin_release_scope_mismatch", "release belongs to another plugin", status_code=409)
    await _require_release_runnable(db, release)
    manifest = dict(release.manifest or {})
    operation = _manifest_item(manifest, "workflows", operation_id)
    declared_input_schema: dict[str, Any] = {}
    declared_output_schema: dict[str, Any] = {}
    input_schema_declaration: Any = None
    output_schema_declaration: Any = None
    if invocation_kind == "tool":
        tool = _manifest_item(manifest, "tools", operation_id)
        if not tool or tool.get("mode") != "read":
            raise _error("plugin_tool_not_found", "only declared read-only plugin tools may be called", status_code=404)
        operation = _manifest_item(manifest, "workflows", str(tool.get("workflow") or tool.get("workflow_id") or ""))
        input_schema_declaration = tool.get("input_schema")
        output_schema_declaration = tool.get("output_schema")
        declared_input_schema = _release_schema(release, input_schema_declaration)
        declared_output_schema = _release_schema(release, output_schema_declaration)
        workflow_id = str(operation.get("id")) if operation else ""
        operation_key = f"tool:{operation_id}"
    else:
        workflow_id = operation_id
        operation_key = operation_id
    if not operation:
        raise _error("plugin_operation_not_found", "plugin operation is not declared", status_code=404)
    if invocation_kind == "tool" and (
        str(operation.get("mode") or "").casefold() != "read"
        or workflow_is_write(operation)
        or {"action.propose.v1", "event.record.v1"}
        & workflow_required_ports(manifest, operation)
    ):
        raise _error(
            "plugin_tool_not_read_only",
            "Tutor plugin tools may only target genuinely read-only workflows",
            status_code=409,
        )
    if not declared_input_schema:
        input_schema_declaration = operation.get("input_schema")
        declared_input_schema = _release_schema(release, input_schema_declaration)
    if not declared_output_schema:
        output_schema_declaration = operation.get("output_schema")
        declared_output_schema = _release_schema(release, output_schema_declaration)
    effective_input = dict(input_data)
    reserved_input_keys = {"snapshot", "snapshot_ref", "plugin_configuration"}
    if reserved_input_keys & set(effective_input):
        raise _error(
            "reserved_plugin_input",
            "snapshot, snapshot_ref and plugin_configuration are host-owned workflow inputs",
            status_code=409,
            fields=sorted(reserved_input_keys & set(effective_input)),
        )
    _validate_contract_value(
        effective_input,
        declared_input_schema,
        kind="input",
        release=release,
        schema_reference=input_schema_declaration,
    )
    write_operation = workflow_is_write(operation)
    required_ports = workflow_required_ports(manifest, operation)
    granted = set(
        validate_host_port_grants(manifest, granted_ports_override)
        if granted_ports_override is not None
        else list(instance.granted_host_ports or [])
    )
    missing = sorted(required_ports - granted)
    if missing:
        raise _error("host_port_grant_required", "workflow requires Host Ports not granted to this instance", status_code=403, ports=missing)
    effective_configuration = validate_configuration(
        manifest,
        dict(configuration_on_success)
        if configuration_on_success is not None
        else dict(instance.configuration or {}),
    )
    persisted_input = dict(effective_input)
    request = {
        "operation": operation_key,
        "workflow": workflow_id,
        "input": persisted_input,
        "expected_snapshot_id": expected_snapshot_id,
        "release_id": release.id,
        "base_release_id": instance.release_id,
        "granted_host_ports": sorted(granted),
        "configuration": effective_configuration,
    }
    request_hash = canonical_hash(request)
    existing = (await db.execute(select(PluginRun).where(
        PluginRun.instance_id == instance.id,
        PluginRun.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise _error("idempotency_conflict", "idempotency key is already bound to a different request", status_code=409)
        return existing, True
    if write_operation and require_expected_snapshot and not expected_snapshot_provided:
        raise _error("expected_snapshot_required", "write workflow must explicitly submit expected_snapshot_id", status_code=409, current=instance.current_snapshot_id)
    if write_operation and require_expected_snapshot and expected_snapshot_id != instance.current_snapshot_id:
        raise _error("snapshot_conflict", "write workflow expected snapshot is stale or missing", status_code=409, expected=expected_snapshot_id, current=instance.current_snapshot_id)
    snapshot_input = str(operation.get("snapshot_input") or "").strip().casefold()
    inject_snapshot = snapshot_input == "current" or workflow_id in {
        "explain", "iterate", "validate", "upgrade",
    } or (
        invocation_kind == "tool" and str(operation.get("mode") or "") == "read"
    )
    if inject_snapshot:
        requested_snapshot_id = effective_input.get("snapshot_id")
        pinned_snapshot_id = (
            int(requested_snapshot_id)
            if isinstance(requested_snapshot_id, int) and not isinstance(requested_snapshot_id, bool)
            else expected_snapshot_id if expected_snapshot_id is not None else instance.current_snapshot_id
        )
        pinned_snapshot = await db.get(PluginSnapshot, pinned_snapshot_id) if pinned_snapshot_id else None
        if not pinned_snapshot or pinned_snapshot.instance_id != instance.id:
            raise _error("plugin_snapshot_not_found", "operation requires a snapshot owned by this instance", status_code=404)
        effective_input["snapshot"] = materialize_snapshot_input(pinned_snapshot)
        effective_input["snapshot_ref"] = {
            "plugin_id": instance.plugin_id,
            "instance_id": instance.id,
            "snapshot_id": pinned_snapshot.id,
            "snapshot_root_hash": pinned_snapshot.root_hash,
            "schema_version": pinned_snapshot.schema_version,
        }
    # The configuration is injected only after validating caller input.  It
    # therefore cannot be forged by the caller and does not require plugin
    # workflow schemas to expose this host-owned runtime envelope.
    effective_input["plugin_configuration"] = effective_configuration

    adapter = (
        "builtin_agent_package"
        if (instance.plugin_id, workflow_id) in _BUILTIN_WORKFLOWS
        else "trusted_signed_process"
    )
    run = PluginRun(
        learner_id=current.learner.id,
        project_id=project.id,
        instance_id=instance.id,
        release_id=release.id,
        invocation_kind=invocation_kind,
        operation_id=operation_id,
        status="running",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        request=request,
        contract={
            "host_protocol": PLUGIN_HOST_PROTOCOL,
            "plugin_id": instance.plugin_id,
            "workflow_id": workflow_id,
            "mode": operation.get("mode"),
            "required_host_ports": sorted(required_ports),
            "write_snapshot": write_operation,
        },
        expected_snapshot_id=expected_snapshot_id,
        execution_boundary=execution_boundary(adapter=adapter),
        started_at=datetime.utcnow(),
    )
    db.add(run)
    try:
        await db.flush()
        await append_run_event(
            db,
            run,
            "run_started",
            "host",
            {"request_hash": request_hash, "adapter": adapter},
        )
        # Reserve the instance-scoped idempotency key before invoking an
        # external process. Concurrent callers can now replay this durable
        # running record instead of starting a second side-effecting run.
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        concurrent = (await db.execute(select(PluginRun).where(
            PluginRun.instance_id == instance.id,
            PluginRun.idempotency_key == idempotency_key,
        ))).scalar_one_or_none()
        if concurrent and concurrent.request_hash == request_hash:
            return concurrent, True
        raise _error(
            "idempotency_conflict",
            "idempotency key was claimed concurrently by a different request",
            status_code=409,
        ) from exc
    context = PluginWorkflowContext(
        _db=db,
        current=current,
        project=project,
        instance=instance,
        release=release,
        run=run,
        manifest=manifest,
        authorized_host_ports=frozenset(required_ports),
    )
    # Keep the durable run-start audit outside the savepoint, while treating
    # every plugin-controlled side effect as one atomic unit.  A rejected
    # result may therefore retain a failed PluginRun, but can never retain a
    # partial snapshot, object index, proposal, or EvidenceEvent.
    operation_savepoint = await db.begin_nested()
    try:
        handler = _BUILTIN_WORKFLOWS.get((instance.plugin_id, workflow_id))
        if handler is not None:
            raw = await _maybe_await(handler(context, dict(effective_input)))
        elif _EXTERNAL_RUNNER_HOOK is not None:
            raw = await _maybe_await(_EXTERNAL_RUNNER_HOOK(context, workflow_id, dict(effective_input)))
        else:
            raise _error("plugin_runner_unavailable", "plugin has no built-in handler and native runner is unavailable", status_code=503)
        if isinstance(raw, dict):
            _validate_contract_value(
                raw,
                declared_output_schema,
                kind="output",
                release=release,
                schema_reference=output_schema_declaration,
            )
        result = _normalize_result(raw)
        _bounded(result.result, budget=MAX_TOOL_RESULT_BYTES, label="plugin result")
        if write_operation and result.snapshot is None and result.status not in {"no_change", "compatible"}:
            raise _error("snapshot_candidate_missing", "write workflow completed without a validated snapshot candidate", status_code=502)
        snapshot_committed = False
        if result.snapshot is not None:
            snapshot = await _create_snapshot(
                db,
                instance,
                release,
                run,
                result.snapshot,
                host_reads=context.host_reads,
                effective_configuration=effective_configuration,
            )
            run.result_snapshot_id = snapshot.id
            snapshot_committed = snapshot.id != run.expected_snapshot_id
            if not snapshot_committed and result.status == "completed":
                result.status = "no_change"
                result.result = {
                    **result.result,
                    "host_no_change_reason": "candidate_matches_current_snapshot_root",
                }
        await _emit_plugin_events(db, context, result.events)
        if switch_release_on_success:
            instance.release_id = release.id
            instance.granted_host_ports = sorted(granted)
            if configuration_on_success is not None:
                instance.configuration = dict(configuration_on_success)
        run.status = result.status if result.status in {"completed", "no_change", "compatible"} else "completed"
        run.result = result.result
        run.finished_at = datetime.utcnow()
        if snapshot_committed:
            await record_event(
                db,
                learner_id=context.learner_id,
                project_id=context.project_id,
                event_type="plugin_snapshot_committed",
                source="plugin_host",
                payload={
                    "plugin_id": instance.plugin_id,
                    "plugin_instance_id": instance.id,
                    "run_id": run.id,
                    "snapshot_id": run.result_snapshot_id,
                    "parent_snapshot_id": run.expected_snapshot_id,
                    "mastery_unchanged": True,
                },
                provenance={"release_id": release.id, "host_protocol": PLUGIN_HOST_PROTOCOL},
                client_event_id=f"plugin-run:{run.id}:snapshot-committed",
            )
        await record_event(
            db,
            learner_id=context.learner_id,
            project_id=context.project_id,
            event_type="plugin_workflow_completed",
            source="plugin_host",
            payload={
                "plugin_id": instance.plugin_id,
                "plugin_instance_id": instance.id,
                "run_id": run.id,
                "workflow_id": workflow_id,
                "status": run.status,
                "mastery_unchanged": True,
            },
            provenance={"release_id": release.id, "host_protocol": PLUGIN_HOST_PROTOCOL},
            client_event_id=f"plugin-run:{run.id}:workflow-completed",
        )
        if switch_release_on_success:
            await record_event(
                db,
                learner_id=context.learner_id,
                project_id=context.project_id,
                event_type="plugin_release_upgraded",
                source="plugin_host",
                payload={
                    "plugin_id": instance.plugin_id,
                    "plugin_instance_id": instance.id,
                    "release_id": release.id,
                    "run_id": run.id,
                    "mastery_unchanged": True,
                },
                provenance={"host_protocol": PLUGIN_HOST_PROTOCOL, "kernel_targets": []},
                client_event_id=f"plugin-run:{run.id}:release-upgraded",
            )
        await append_run_event(db, run, "run_completed", "host", {"status": run.status, "result_snapshot_id": run.result_snapshot_id, "host_port_calls": context.host_port_calls})
        await operation_savepoint.commit()
    except asyncio.CancelledError:
        if operation_savepoint.is_active:
            await operation_savepoint.rollback()
        await db.refresh(run)
        await db.refresh(instance)
        run.status = "failed"
        run.error = {
            "code": "plugin_run_cancelled",
            "message": "plugin workflow was cancelled; no candidate snapshot or proposal was committed",
            "details": {},
        }
        run.finished_at = datetime.utcnow()
        await append_run_event(db, run, "run_cancelled", "host", run.error)
        await db.commit()
        raise
    except Exception as exc:
        if operation_savepoint.is_active:
            await operation_savepoint.rollback()
        await db.refresh(run)
        await db.refresh(instance)
        if isinstance(exc, IntegrityError):
            error = _error(
                "snapshot_conflict",
                "plugin state changed concurrently while committing the workflow",
                status_code=409,
                expected=expected_snapshot_id,
                current=instance.current_snapshot_id,
            )
        elif isinstance(exc, PluginHostError):
            error = exc
        else:
            error = _error("plugin_execution_failed", str(exc) or exc.__class__.__name__, status_code=502)
        run.status = "failed"
        run.error = error.detail()
        run.finished_at = datetime.utcnow()
        await append_run_event(db, run, "run_failed", "host", run.error)
        await db.commit()
        raise error from exc
    await db.commit()
    return run, False


async def mark_interrupted_plugin_runs_failed() -> None:
    """Fail native/plugin runs that cannot be resumed after a host restart."""

    async with async_session() as db:
        runs = list((await db.execute(select(PluginRun).where(
            PluginRun.status == "running",
        ).order_by(PluginRun.id))).scalars().all())
        for run in runs:
            run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.error = {
                "code": "plugin_host_restarted",
                "message": "LearnFlow restarted before this isolated plugin run completed; retry with a new idempotency key.",
                "details": {"retryable": True},
            }
            await append_run_event(db, run, "run_interrupted", "host", run.error)
        await db.commit()


async def upgrade_plugin_instance(
    db: AsyncSession,
    current: CurrentLearner,
    project: Project,
    instance: PluginInstance,
    *,
    target_release_id: int,
    expected_snapshot_id: int | None,
    idempotency_key: str,
    configuration: Mapping[str, Any] | None = None,
    granted_host_ports: Iterable[str] | None = None,
) -> tuple[PluginRun, bool]:
    """Run the target release's migration workflow and switch only on success."""

    target = await db.get(PluginRelease, target_release_id)
    if not target or target.plugin_id != instance.plugin_id:
        raise _error("plugin_release_not_found", "target release does not belong to this plugin", status_code=404)
    upgrade_workflow = _manifest_item(target.manifest or {}, "workflows", "upgrade")
    if not upgrade_workflow:
        raise _error("plugin_upgrade_unsupported", "target release does not declare an upgrade workflow", status_code=409)
    desired_grants = list(granted_host_ports) if granted_host_ports is not None else list(instance.granted_host_ports or [])
    desired_configuration = validate_configuration(
        target.manifest or {},
        dict(configuration) if configuration is not None else dict(instance.configuration or {}),
    )
    upgrade_context = {
        "from_release_id": instance.release_id,
        "to_release_id": target.id,
        "base_snapshot_id": instance.current_snapshot_id,
        "configuration": desired_configuration,
    }
    upgrade_schema = _release_schema(target, upgrade_workflow.get("input_schema"))
    if upgrade_schema.get("additionalProperties") is False:
        allowed = set(dict(upgrade_schema.get("properties") or {}))
        upgrade_context = {
            key: value for key, value in upgrade_context.items() if key in allowed
        }
    run, replay = await execute_plugin_operation(
        db,
        current,
        project,
        instance,
        operation_id="upgrade",
        input_data=upgrade_context,
        idempotency_key=idempotency_key,
        expected_snapshot_id=expected_snapshot_id,
        invocation_kind="workflow",
        require_expected_snapshot=True,
        release_override=target,
        granted_ports_override=desired_grants,
        switch_release_on_success=True,
        configuration_on_success=desired_configuration,
    )
    return run, replay


async def plugin_surfaces(
    db: AsyncSession,
    *,
    learner_id: int,
    project_id: int,
    slot: str | None = None,
) -> list[dict[str, Any]]:
    instances = list((await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == learner_id,
        PluginInstance.project_id == project_id,
        PluginInstance.status == "enabled",
    ).order_by(PluginInstance.plugin_id))).scalars().all())
    output: list[dict[str, Any]] = []
    store = artifact_store()
    for instance in instances:
        release = await db.get(PluginRelease, instance.release_id)
        if not release:
            continue
        try:
            await _require_release_runnable(db, release)
        except PluginHostError:
            continue
        resources = dict((release.runner_artifacts or {}).get("resources") or {})
        snapshot = await db.get(PluginSnapshot, instance.current_snapshot_id) if instance.current_snapshot_id else None
        for item in _manifest_items(release.manifest or {}, "surfaces"):
            if slot and item.get("slot") != slot:
                continue
            definition = str(item.get("definition") or item.get("resource") or "")
            schema = None
            if definition:
                descriptor = resources.get(definition)
                try:
                    schema = json.loads(store.read(str(descriptor["uri"])).decode("utf-8")) if descriptor else None
                except (PluginArtifactError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
                    schema = None
            elif release.trust_state == "built_in":
                # Repository-owned test/built-in releases may be constructed
                # directly without a package artifact. Imported packages are
                # required to use the signed resource above.
                schema = item.get("schema") or item.get("body")
            if not isinstance(schema, dict):
                continue
            workflow_ids = [str(row.get("id")) for row in _manifest_items(release.manifest or {}, "workflows")]
            output.append({
                "plugin_id": instance.plugin_id,
                "instance_id": instance.id,
                "surface_id": str(item.get("id")),
                "title": str(item.get("label") or schema.get("label") or item.get("id")),
                "slot": str(item.get("slot") or schema.get("slot") or ""),
                "schema": schema,
                "workflows": workflow_ids,
                "data": {
                    "instance": instance_view(instance, release),
                    "snapshot": snapshot_view(snapshot, include_component_data=True) if snapshot else None,
                },
            })
    return output


async def discover_plugin_tools(
    db: AsyncSession,
    *,
    learner_id: int,
    project_id: int,
    query: str = "",
) -> list[dict[str, Any]]:
    instances = list((await db.execute(select(PluginInstance).where(
        PluginInstance.learner_id == learner_id,
        PluginInstance.project_id == project_id,
        PluginInstance.status == "enabled",
    ).order_by(PluginInstance.plugin_id))).scalars().all())
    tools: list[dict[str, Any]] = []
    terms = [
        item.casefold()
        for item in re.findall(r"[a-zA-Z0-9_.-]{2,}|[\u4e00-\u9fff]{2,8}", str(query or ""))
    ][:20]
    for instance in instances:
        release = await db.get(PluginRelease, instance.release_id)
        if not release or release.status != "active":
            continue
        try:
            await _require_release_runnable(db, release)
        except PluginHostError:
            continue
        for tool in _manifest_items(release.manifest or {}, "tools"):
            if tool.get("mode") != "read":
                continue
            workflow = _manifest_item(
                release.manifest or {}, "workflows", str(tool.get("workflow") or "")
            )
            if (
                not workflow
                or str(workflow.get("mode") or "").casefold() != "read"
                or workflow_is_write(workflow)
                or {"action.propose.v1", "event.record.v1"}
                & workflow_required_ports(release.manifest or {}, workflow)
                or not workflow_required_ports(release.manifest or {}, workflow).issubset(
                    set(instance.granted_host_ports or [])
                )
                or instance.current_snapshot_id is None
            ):
                continue
            search_text = " ".join((
                instance.plugin_id,
                str(tool.get("id") or ""),
                str(tool.get("name") or ""),
                str(tool.get("description") or ""),
            )).casefold()
            tools.append({
                "qualified_tool_id": f"{instance.plugin_id}:{tool['id']}",
                "plugin_id": instance.plugin_id,
                "instance_id": instance.id,
                "tool_id": tool["id"],
                "name": tool.get("name", tool["id"]),
                "description": tool.get("description", ""),
                "mode": "read",
                "input_schema": _release_schema(release, tool.get("input_schema")),
                "output_schema": _release_schema(release, tool.get("output_schema")),
                "snapshot_pinned": bool(instance.current_snapshot_id),
                "current_snapshot_id": instance.current_snapshot_id,
                "match_score": sum(1 for term in terms if term in search_text),
            })
    return sorted(
        tools,
        key=lambda item: (-int(item.get("match_score") or 0), item["qualified_tool_id"]),
    )


def _strict_port_adapter(port_id: str) -> HostPortHandler:
    async def call(context: PluginWorkflowContext, input_data: dict[str, Any]) -> Any:
        try:
            return await call_plugin_host_port(
                PluginHostPortContext(
                    db=context._db,
                    learner_id=context.learner_id,
                    project_id=context.project_id,
                    instance=context.instance,
                    manifest=context.manifest,
                    release_id=context.release.id,
                    base_release_id=context.run.request.get("base_release_id", context.instance.release_id),
                    authorized_host_ports=context.authorized_host_ports,
                    run_id=context.run.id,
                    artifact_store=artifact_store(),
                ),
                port_id,
                input_data,
            )
        except PluginHostPortError as exc:
            raise _error(exc.code, exc.message, status_code=403, **exc.details) from exc

    return call


for _port_id in HOST_PORT_POLICIES:
    register_host_port(_port_id, _strict_port_adapter(_port_id))


__all__ = [
    "HOST_PORT_POLICIES",
    "PLUGIN_HOST_PROTOCOL",
    "PLUGIN_OBJECT_REF_PROTOCOL",
    "PLUGIN_SURFACES_PROTOCOL",
    "PluginHostError",
    "PluginWorkflowContext",
    "PluginWorkflowResult",
    "append_run_event",
    "artifact_store",
    "available_plugin_releases",
    "canonical_hash",
    "declared_host_ports",
    "discover_plugin_tools",
    "enable_plugin_instance",
    "execute_plugin_operation",
    "import_plugin_release",
    "instance_view",
    "mark_interrupted_plugin_runs_failed",
    "object_index_view",
    "object_ref",
    "plugin_surfaces",
    "publisher_view",
    "register_builtin_workflow",
    "register_external_runner_hook",
    "register_host_port",
    "release_view",
    "rebuild_snapshot_object_index",
    "require_owned_instance",
    "resolve_indexed_object",
    "run_view",
    "snapshot_view",
    "update_plugin_instance",
    "upgrade_plugin_instance",
    "validate_host_port_grants",
    "validate_configuration",
    "workflow_is_write",
]
