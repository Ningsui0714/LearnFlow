"""Installation and one-way migration for repository-bundled LearnFlow plugins."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginPublisher,
    PluginRelease,
    PluginRun,
    PluginSnapshot,
)
from app.models.role_capability import (
    RoleCapabilityPackage,
    RoleCapabilityRun,
    RoleCapabilitySnapshot,
)
from app.services.plugin_artifacts import canonical_json_bytes
from app.services.plugin_host import artifact_store, canonical_hash
from app.services.role_capability_plugin import inspect_role_graph
from app.services.role_capability_agent_package import register_role_capability_agent_package
from app.services.learning_task_agent_package import register_learning_task_agent_package


OFFICIAL_PUBLISHER_KEY = "learnflow_official"
OFFICIAL_PUBLISHER_KEY_ID = "learnflow-official-ed25519-v1"
OFFICIAL_PUBLISHER_PUBLIC_KEY = "Tv+le588HF2hbtVX2OTMUkalAV/6+KLpOg+ieB45+WU="
ROLE_PLUGIN_ID = "role_capability_graph"
ROLE_PLUGIN_VERSION = "1.0.0"
ROLE_PLUGIN_ROOT_HASH = "8385913204acc20d6cdfa246bf0e2fc7a0be94df1cf4e5708a39a5ce46af592f"
ROLE_OBJECT_SCHEMA = "role-capability.object.v1"
LEARNING_TASK_PLUGIN_ID = "learning_task_conversion"
LEARNING_TASK_PLUGIN_VERSION = "1.0.0"
LEARNING_TASK_PLUGIN_ROOT_HASH = "7fb7133fdfd9abeb4afc5898def672c4b720d3fda71b4b46f1038de7f495a8e6"


# Official product plugins are Agent Packages linked directly into LearnFlow.
# The signed bundle remains useful as immutable release metadata and as an
# exportable third-party distribution artifact, but normal product execution
# never depends on the optional native-process runner.
register_role_capability_agent_package()
register_learning_task_agent_package()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def bundled_role_plugin_path() -> Path:
    return _repository_root() / "plugins" / "dist" / f"{ROLE_PLUGIN_ID}-{ROLE_PLUGIN_VERSION}.lfplugin"


async def ensure_official_role_plugin_release(db: AsyncSession) -> PluginRelease:
    """Install the repository-owned Agent Package without requiring a ZIP runner."""

    publisher = (await db.execute(select(PluginPublisher).where(
        PluginPublisher.publisher_key == OFFICIAL_PUBLISHER_KEY,
    ))).scalar_one_or_none()
    if publisher:
        if (
            publisher.key_id != OFFICIAL_PUBLISHER_KEY_ID
            or publisher.public_key != OFFICIAL_PUBLISHER_PUBLIC_KEY
        ):
            raise RuntimeError("installed LearnFlow official publisher key conflicts with the bundled key")
    else:
        publisher = PluginPublisher(
            publisher_key=OFFICIAL_PUBLISHER_KEY,
            display_name="LearnFlow Official",
            key_id=OFFICIAL_PUBLISHER_KEY_ID,
            public_key=OFFICIAL_PUBLISHER_PUBLIC_KEY,
            trust_status="trusted",
        )
        db.add(publisher)
        await db.flush()

    existing = (await db.execute(select(PluginRelease).where(
        PluginRelease.plugin_id == ROLE_PLUGIN_ID,
        PluginRelease.version == ROLE_PLUGIN_VERSION,
    ))).scalar_one_or_none()
    if existing:
        if existing.root_hash != ROLE_PLUGIN_ROOT_HASH:
            raise RuntimeError("bundled role plugin version has conflicting content")
        # v22 initially installed the official product plugin through its
        # optional signed export bundle.  Preserve the release/root identity
        # while correcting its runtime classification in place.
        existing.trust_state = "built_in"
        return existing

    package_root = _repository_root() / "plugins" / ROLE_PLUGIN_ID
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"built-in role Agent Package is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("plugin_id") != ROLE_PLUGIN_ID or manifest.get("version") != ROLE_PLUGIN_VERSION:
        raise RuntimeError("built-in role Agent Package manifest conflicts with the architecture contract")

    store = artifact_store()
    manifest_artifact = store.put_json(manifest, name="manifest.json")
    resources: dict[str, Any] = {}
    for directory in ("schemas", "surfaces"):
        for path in sorted((package_root / directory).rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(package_root).as_posix()
            resources[relative] = store.put_bytes(
                path.read_bytes(),
                media_type="application/json" if path.suffix == ".json" else "application/octet-stream",
                name=relative,
            ).to_dict()
    release = PluginRelease(
        publisher_id=publisher.id,
        plugin_id=ROLE_PLUGIN_ID,
        version=ROLE_PLUGIN_VERSION,
        package_protocol=str(manifest.get("protocol") or "learnflow.plugin-package.v1"),
        manifest=manifest,
        signature={"kind": "repository_built_in", "optional_export_root_hash": ROLE_PLUGIN_ROOT_HASH},
        root_hash=ROLE_PLUGIN_ROOT_HASH,
        package_artifact_uri=manifest_artifact.uri,
        runner_artifacts={
            "builtin_agent_package": "app.services.role_capability_agent_package",
            "resources": resources,
            "runners": {},
        },
        trust_state="built_in",
        status="active",
    )
    db.add(release)
    await db.flush()
    return release


async def ensure_official_learning_task_plugin_release(db: AsyncSession) -> PluginRelease:
    """Install the official learning-task Agent Package as a built-in release."""

    publisher = (await db.execute(select(PluginPublisher).where(
        PluginPublisher.publisher_key == OFFICIAL_PUBLISHER_KEY,
    ))).scalar_one_or_none()
    if not publisher:
        publisher = PluginPublisher(
            publisher_key=OFFICIAL_PUBLISHER_KEY,
            display_name="LearnFlow Official",
            key_id=OFFICIAL_PUBLISHER_KEY_ID,
            public_key=OFFICIAL_PUBLISHER_PUBLIC_KEY,
            trust_status="trusted",
        )
        db.add(publisher)
        await db.flush()

    existing = (await db.execute(select(PluginRelease).where(
        PluginRelease.plugin_id == LEARNING_TASK_PLUGIN_ID,
        PluginRelease.version == LEARNING_TASK_PLUGIN_VERSION,
    ))).scalar_one_or_none()
    if existing:
        if existing.root_hash != LEARNING_TASK_PLUGIN_ROOT_HASH:
            raise RuntimeError("bundled learning-task plugin version has conflicting content")
        existing.trust_state = "built_in"
        return existing

    package_root = _repository_root() / "plugins" / LEARNING_TASK_PLUGIN_ID
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"built-in learning-task Agent Package is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("plugin_id") != LEARNING_TASK_PLUGIN_ID
        or manifest.get("version") != LEARNING_TASK_PLUGIN_VERSION
    ):
        raise RuntimeError("built-in learning-task manifest conflicts with the architecture contract")

    store = artifact_store()
    manifest_artifact = store.put_json(manifest, name="manifest.json")
    resources: dict[str, Any] = {}
    for directory in ("schemas", "surfaces"):
        for path in sorted((package_root / directory).rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(package_root).as_posix()
            resources[relative] = store.put_bytes(
                path.read_bytes(),
                media_type="application/json" if path.suffix == ".json" else "application/octet-stream",
                name=relative,
            ).to_dict()
    release = PluginRelease(
        publisher_id=publisher.id,
        plugin_id=LEARNING_TASK_PLUGIN_ID,
        version=LEARNING_TASK_PLUGIN_VERSION,
        package_protocol=str(manifest.get("protocol") or "learnflow.plugin-package.v1"),
        manifest=manifest,
        signature={"kind": "repository_built_in"},
        root_hash=LEARNING_TASK_PLUGIN_ROOT_HASH,
        package_artifact_uri=manifest_artifact.uri,
        runner_artifacts={
            "builtin_agent_package": "app.services.learning_task_agent_package",
            "resources": resources,
            "runners": {},
        },
        trust_state="built_in",
        status="active",
    )
    db.add(release)
    await db.flush()
    return release


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def _legacy_candidate(snapshot: RoleCapabilitySnapshot) -> dict[str, Any]:
    graph = json.loads(json.dumps(dict(snapshot.graph or {}), ensure_ascii=False))
    graph["edges"] = [
        {**dict(item), "object_type": "semantic_edge"}
        for item in list(graph.get("edges") or [])
        if isinstance(item, dict)
    ]
    nodes = [dict(item) for item in list(graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item) for item in list(graph.get("edges") or []) if isinstance(item, dict)]
    role = next((item for item in nodes if item.get("type") == "role"), None)
    actor = {
        "id": _stable_id("actor", str((role or {}).get("id") or snapshot.role_title)),
        "type": "actor",
        "label": str((role or {}).get("label") or snapshot.role_title),
        "summary": "承担岗位过程责任的角色。",
        "lifecycle": "accepted",
        "evidence_refs": list((role or {}).get("evidence_refs") or []),
    }
    events: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    work_objects: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for order, task in enumerate((item for item in nodes if item.get("type") == "task"), start=1):
        event_id = _stable_id("process_event", str(task.get("id")))
        object_id = _stable_id("work_object", str(task.get("id")))
        evidence_refs = list(task.get("evidence_refs") or [])
        events.append({
            "id": event_id,
            "type": "process_event",
            "label": str(task.get("label") or ""),
            "order": order,
            "actor_id": actor["id"],
            "task_id": task.get("id"),
            "work_object_id": object_id,
            "lifecycle": str(task.get("lifecycle") or "candidate"),
            "evidence_refs": evidence_refs,
        })
        scenarios.append({
            "id": _stable_id("scenario", str(task.get("id"))),
            "type": "scenario",
            "label": f"{task.get('label', '')}场景",
            "event_ids": [event_id],
            "lifecycle": "candidate",
            "evidence_refs": evidence_refs,
        })
        work_objects.append({
            "id": object_id,
            "type": "work_object",
            "label": f"{task.get('label', '')}输入与产物",
            "lifecycle": "candidate",
            "evidence_refs": evidence_refs,
        })
        bridges.append({
            "id": _stable_id("bridge", f"{task.get('id')}:{event_id}"),
            "type": "bridge",
            "label": "任务—过程桥",
            "semantic_object_id": task.get("id"),
            "process_event_id": event_id,
            "lifecycle": "candidate",
            "evidence_refs": evidence_refs,
        })
        claims.append({
            "id": _stable_id("claim", str(task.get("id"))),
            "type": "claim",
            "label": str(task.get("label") or ""),
            "statement": str(task.get("summary") or ""),
            "subject_id": task.get("id"),
            "lifecycle": "candidate",
            "evidence_refs": evidence_refs,
        })
    validation = inspect_role_graph(graph)
    validation = {
        **validation,
        "migration": {
            "protocol": "learnflow.role-capability-migration.v1",
            "legacy_snapshot_id": snapshot.id,
            "legacy_root_hash": snapshot.root_hash,
            "stable_object_ids_preserved": True,
        },
    }
    components: dict[str, Any] = {
        "evidence": {"sources": list(snapshot.source_refs or []), "claims": claims},
        "semantic-graph": graph,
        "process-forest": {
            "actors": [actor],
            "scenarios": scenarios,
            "events": events,
            "work_objects": work_objects,
            "bridges": bridges,
        },
        "views": {"views": list(graph.get("views") or [])},
        "retrieval-index": {
            "entries": [
                {
                    "object_id": item.get("id"),
                    "text": f"{item.get('label', '')} {item.get('summary', '')}"[:500],
                }
                for item in nodes
            ]
        },
        "validation-report": validation,
        "reference-migrations": {
            "protocol": "learnflow.plugin-reference-migration.v1",
            "legacy_snapshot_id": snapshot.id,
            "legacy_snapshot_key": snapshot.snapshot_key,
            "legacy_root_hash": snapshot.root_hash,
            "stable_object_ids": [item.get("id") for item in nodes + edges],
        },
    }
    locations = (
        ("semantic-graph", "nodes", nodes),
        # The locator must hash and resolve the exact object stored at the JSON
        # pointer.  Semantic edges keep their domain relation in ``type`` and
        # expose the index type separately through ``object_type``.
        ("semantic-graph", "edges", edges),
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
            object_type = str(item.get("object_type") or item.get("type") or "")
            references = list(item.get("references") or [])
            if object_type == "semantic_edge" and not references:
                references = [item.get("source"), item.get("target")]
            objects.append({
                "id": str(item.get("id") or ""),
                "type": object_type,
                "label": str(
                    item.get("label")
                    or (item.get("type") if object_type == "semantic_edge" else "")
                    or ""
                ),
                "component": component,
                "json_pointer": f"/{collection}/{index}",
                "content_hash": canonical_hash(item),
                "lifecycle": str(item.get("lifecycle") or "active"),
                "references": references,
            })
    return {
        "schema_version": ROLE_OBJECT_SCHEMA,
        "components": components,
        "objects": objects,
        "source_refs": list(snapshot.source_refs or []),
        "validation": validation,
        "provenance": {
            **dict(snapshot.provenance or {}),
            "migration": "v22-generic-plugin-host",
            "legacy_snapshot_id": snapshot.id,
            "legacy_root_hash": snapshot.root_hash,
            "mastery_unchanged": True,
        },
    }


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    for token in pointer.lstrip("/").split("/") if pointer else ():
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


async def backfill_legacy_role_plugin(
    db: AsyncSession,
    release: PluginRelease,
) -> dict[str, int]:
    """Convert legacy role rows once; old tables remain read-only thereafter."""

    counts = {
        "instances": 0,
        "snapshots": 0,
        "objects": 0,
        "runs": 0,
        "skipped": 0,
    }
    packages = list((await db.execute(select(RoleCapabilityPackage).order_by(
        RoleCapabilityPackage.id,
    ))).scalars().all())
    store = artifact_store()
    for package in packages:
        instance = (await db.execute(select(PluginInstance).where(
            PluginInstance.learner_id == package.learner_id,
            PluginInstance.project_id == package.project_id,
            PluginInstance.plugin_id == ROLE_PLUGIN_ID,
        ))).scalar_one_or_none()
        if not instance:
            instance = PluginInstance(
                learner_id=package.learner_id,
                project_id=package.project_id,
                plugin_id=ROLE_PLUGIN_ID,
                release_id=release.id,
                status="disabled",
                # Migration metadata belongs to snapshot/run provenance, not
                # the release-validated instance configuration schema.
                configuration={},
                granted_host_ports=[],
                disabled_at=datetime.utcnow(),
            )
            db.add(instance)
            await db.flush()
            counts["instances"] += 1
        # The old tables become compatibility input only even when a previous
        # retry already created the generic rows.
        package.status = "frozen_read_only"
        existing_rows = list((await db.execute(select(PluginSnapshot).where(
            PluginSnapshot.instance_id == instance.id,
        ))).scalars().all())
        legacy_rows = list((await db.execute(select(RoleCapabilitySnapshot).where(
            RoleCapabilitySnapshot.package_id == package.id,
        ).order_by(RoleCapabilitySnapshot.version, RoleCapabilitySnapshot.id))).scalars().all())
        snapshot_map = {
            int(row.provenance["legacy_snapshot_id"]): row.id
            for row in existing_rows
            if isinstance(row.provenance, dict)
            and isinstance(row.provenance.get("legacy_snapshot_id"), int)
        }
        if existing_rows:
            counts["skipped"] += 1
        else:
            parent_id: int | None = None
            mapped_current: int | None = None
            for legacy in legacy_rows:
                candidate = _legacy_candidate(legacy)
                commit = store.commit_components(candidate["components"])
                migrated = PluginSnapshot(
                    instance_id=instance.id,
                    release_id=release.id,
                    parent_snapshot_id=parent_id,
                    version=legacy.version,
                    schema_version=ROLE_OBJECT_SCHEMA,
                    # Preserve the identity embedded in legacy fixed
                    # references.  The generic component rewrite is proven
                    # separately and remains independently rebuildable.
                    root_hash=legacy.root_hash,
                    components=commit.to_manifest(),
                    source_refs=candidate["source_refs"],
                    validation={
                        **candidate["validation"],
                        "snapshot_root_protocol": "legacy-role-root-v1",
                        "component_root_hash": commit.root_hash,
                    },
                    provenance=candidate["provenance"],
                    created_at=legacy.created_at,
                )
                db.add(migrated)
                await db.flush()
                snapshot_map[legacy.id] = migrated.id
                for descriptor in candidate["objects"]:
                    actual = _pointer(
                        candidate["components"][descriptor["component"]],
                        descriptor["json_pointer"],
                    )
                    content_hash = canonical_hash(actual)
                    if content_hash != descriptor["content_hash"]:
                        raise RuntimeError("legacy plugin migration object hash mismatch")
                    db.add(PluginObjectIndex(
                        snapshot_id=migrated.id,
                        plugin_id=ROLE_PLUGIN_ID,
                        object_type=descriptor["type"],
                        object_id=descriptor["id"],
                        label=descriptor["label"][:500],
                        schema_version=ROLE_OBJECT_SCHEMA,
                        component=descriptor["component"],
                        json_pointer=descriptor["json_pointer"],
                        content_hash=content_hash,
                        lifecycle=descriptor["lifecycle"][:30],
                        references=descriptor["references"],
                    ))
                    counts["objects"] += 1
                await db.flush()
                parent_id = migrated.id
                counts["snapshots"] += 1
                if legacy.id == package.current_snapshot_id:
                    mapped_current = migrated.id
            instance.current_snapshot_id = mapped_current or parent_id

        # Preserve each legacy workflow audit row without ever making it a
        # second snapshot authority. Snapshot foreign keys are translated
        # through the explicit v21 -> v22 mapping above.
        legacy_runs = list((await db.execute(select(RoleCapabilityRun).where(
            RoleCapabilityRun.package_id == package.id,
        ).order_by(RoleCapabilityRun.id))).scalars().all())
        for legacy_run in legacy_runs:
            migration_key = f"migration:v22:role-run:{legacy_run.id}"
            existing_run = (await db.execute(select(PluginRun).where(
                PluginRun.instance_id == instance.id,
                PluginRun.idempotency_key == migration_key,
            ))).scalar_one_or_none()
            if existing_run:
                continue
            legacy_base_id = int(dict(legacy_run.contract or {}).get("base_snapshot_id") or 0)
            legacy_status = str(legacy_run.status or "failed")
            migrated_status = (
                legacy_status
                if legacy_status in {"completed", "no_change", "failed"}
                else "failed"
            )
            migrated_error = dict(legacy_run.error or {})
            if migrated_status == "failed" and not migrated_error:
                migrated_error = {
                    "code": "legacy_run_interrupted",
                    "message": "未完成的 v21 运行在只读迁移时关闭",
                }
            run_request = {
                "migration": "v22-generic-plugin-host",
                "legacy_run_id": legacy_run.id,
                "legacy_request": dict(legacy_run.request or {}),
            }
            db.add(PluginRun(
                learner_id=package.learner_id,
                project_id=package.project_id,
                instance_id=instance.id,
                release_id=release.id,
                invocation_kind="workflow",
                operation_id=str(legacy_run.kind or "legacy_run"),
                status=migrated_status,
                idempotency_key=migration_key,
                request_hash=hashlib.sha256(canonical_json_bytes(run_request)).hexdigest(),
                request=run_request,
                contract={
                    **dict(legacy_run.contract or {}),
                    "authority": "generic_plugin_host_audit",
                    "legacy_tables": "read_only",
                },
                expected_snapshot_id=snapshot_map.get(legacy_base_id),
                result_snapshot_id=snapshot_map.get(legacy_run.result_snapshot_id),
                result={
                    "legacy_summary": legacy_run.summary,
                    "inspection": dict(legacy_run.inspection or {}),
                    "diff": dict(legacy_run.diff or {}),
                    "mastery_unchanged": True,
                },
                execution_boundary={
                    "adapter": "deterministic_migration",
                    "native_process": False,
                    "filesystem_isolation": False,
                    "network_isolation": False,
                    "secrets_isolation": False,
                },
                error=migrated_error,
                created_at=legacy_run.created_at,
                started_at=legacy_run.created_at,
                finished_at=legacy_run.finished_at or datetime.utcnow(),
            ))
            counts["runs"] += 1
        if legacy_rows:
            run_request = {
                "migration": "v22-generic-plugin-host",
                "legacy_package_id": package.id,
                "legacy_snapshot_ids": [item.id for item in legacy_rows],
            }
            migration_key = f"migration:v22:role-package:{package.id}"
            existing_migration = (await db.execute(select(PluginRun).where(
                PluginRun.instance_id == instance.id,
                PluginRun.idempotency_key == migration_key,
            ))).scalar_one_or_none()
            if not existing_migration:
                db.add(PluginRun(
                    learner_id=package.learner_id,
                    project_id=package.project_id,
                    instance_id=instance.id,
                    release_id=release.id,
                    invocation_kind="migration",
                    operation_id="legacy_import",
                    status="completed",
                    idempotency_key=migration_key,
                    request_hash=hashlib.sha256(canonical_json_bytes(run_request)).hexdigest(),
                    request=run_request,
                    contract={
                        "authority": "generic_plugin_snapshot",
                        "legacy_tables": "read_only",
                    },
                    expected_snapshot_id=None,
                    result_snapshot_id=instance.current_snapshot_id,
                    result={
                        "migrated_snapshots": len(legacy_rows),
                        "mastery_unchanged": True,
                    },
                    execution_boundary={
                        "adapter": "deterministic_migration",
                        "native_process": False,
                        "filesystem_isolation": False,
                        "network_isolation": False,
                        "secrets_isolation": False,
                    },
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                ))
                counts["runs"] += 1
    await db.flush()
    return counts


async def install_and_migrate_bundled_plugins(db: AsyncSession) -> dict[str, Any]:
    release = await ensure_official_role_plugin_release(db)
    learning_task_release = await ensure_official_learning_task_plugin_release(db)
    counts = await backfill_legacy_role_plugin(db, release)
    return {
        "release_id": release.id,
        "learning_task_release_id": learning_task_release.id,
        "role_capability": counts,
    }


__all__ = [
    "OFFICIAL_PUBLISHER_KEY",
    "OFFICIAL_PUBLISHER_KEY_ID",
    "OFFICIAL_PUBLISHER_PUBLIC_KEY",
    "ROLE_PLUGIN_ID",
    "ROLE_PLUGIN_ROOT_HASH",
    "ROLE_PLUGIN_VERSION",
    "LEARNING_TASK_PLUGIN_ID",
    "LEARNING_TASK_PLUGIN_ROOT_HASH",
    "LEARNING_TASK_PLUGIN_VERSION",
    "backfill_legacy_role_plugin",
    "bundled_role_plugin_path",
    "ensure_official_role_plugin_release",
    "ensure_official_learning_task_plugin_release",
    "install_and_migrate_bundled_plugins",
]
