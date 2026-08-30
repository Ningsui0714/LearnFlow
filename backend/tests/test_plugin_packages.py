import base64
import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.db.database import Base
from app.models.plugin import (
    PluginInstance,
    PluginObjectIndex,
    PluginPublisher,
    PluginRelease,
    PluginRun,
    PluginRunEvent,
    PluginSnapshot,
)
from app.services.plugin_artifacts import PluginArtifactError, PluginArtifactStore
from app.services.plugin_packages import (
    PackagePolicy,
    PluginPackageError,
    TrustedPublisher,
    compute_package_root_hash,
    load_plugin_package,
    semver_satisfies,
    signature_payload,
)


def manifest() -> dict:
    return {
        "protocol": "learnflow.plugin-package.v1",
        "plugin_id": "role_capability_graph",
        "version": "1.0.0",
        "host_compatibility": {
            "learnflow": ">=0.1.0 <1.0.0",
            "plugin_host": "learnflow.plugin-host.v1",
        },
        "owner": "learning_design_agent",
        "scope": "project",
        "schema_version": "role-capability.object.v1",
        "object_types": ["role", "task", "capability"],
        "kernel_allow_list": [],
        "host_ports": ["project.read.v1", "event.record.v1"],
        "workflows": [
            {
                "id": "generate",
                "mode": "write_snapshot",
                "host_ports": ["project.read.v1", "event.record.v1"],
                "input_schema": "schemas/workflow-input.schema.json",
                "output_schema": "schemas/workflow-output.schema.json",
            },
            {"id": "explain", "mode": "read", "host_ports": []},
        ],
        "tools": [{"id": "explain", "mode": "read", "workflow": "explain"}],
        "skills": [{"id": "role_capability_graphing"}],
        "surfaces": [
            {
                "id": "role_capability_project",
                "slot": "project.context.tabs",
                "label": "岗位图谱",
                "definition": "surfaces/project.json",
            }
        ],
        "events": [{"id": "package_generated", "kernel_targets": []}],
        "config_schema": {"type": "object", "additionalProperties": False},
        "runners": {"linux-x86_64": "bin/linux-x86_64/runner"},
    }


def package_files() -> dict[str, bytes]:
    surface = {
        "protocol": "learnflow.plugin-surface.v1",
        "id": "role_capability_project",
        "slot": "project.context.tabs",
        "label": "岗位图谱",
        "body": {
            "type": "section",
            "title": "岗位能力图谱",
            "children": [
                {"type": "status", "source": "instance.status", "label": "状态"},
                {
                    "type": "form",
                    "workflow": "generate",
                    "children": [{"type": "input", "name": "role_title"}],
                },
                {"type": "action", "workflow": "generate", "label": "生成"},
            ],
        },
    }
    return {
        "manifest.json": json.dumps(manifest(), ensure_ascii=False).encode(),
        "README.md": b"# role graph\n",
        "LICENSE": b"MIT\n",
        "schemas/workflow-input.schema.json": b'{"type":"object"}',
        "schemas/workflow-output.schema.json": b'{"type":"object"}',
        "surfaces/project.json": json.dumps(surface, ensure_ascii=False).encode(),
        "bin/linux-x86_64/runner": b"#!/bin/sh\nexit 0\n",
    }


def signed_archive(
    *,
    files: dict[str, bytes] | None = None,
    private_key: Ed25519PrivateKey | None = None,
) -> tuple[bytes, TrustedPublisher, Ed25519PrivateKey]:
    selected_files = dict(files or package_files())
    key = private_key or Ed25519PrivateKey.generate()
    root_hash = compute_package_root_hash(selected_files)
    signature = {
        "protocol": "learnflow.plugin-signature.v1",
        "algorithm": "ed25519",
        "publisher_id": "learnflow.official",
        "key_id": "official-2026",
        "root_hash": root_hash,
        "signature": base64.b64encode(key.sign(signature_payload(root_hash))).decode(),
    }
    selected_files["signature.json"] = json.dumps(signature).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in selected_files.items():
            info = zipfile.ZipInfo(path)
            if path.endswith("/runner"):
                info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, content)
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    publisher = TrustedPublisher(
        publisher_id="learnflow.official",
        key_id="official-2026",
        public_key=base64.b64encode(public_bytes).decode(),
    )
    return output.getvalue(), publisher, key


def test_loads_trusted_signed_package_and_preserves_signed_manifest():
    archive, publisher, _ = signed_archive()

    loaded = load_plugin_package(archive, publishers=[publisher])

    assert loaded.plugin_id == "role_capability_graph"
    assert loaded.version == "1.0.0"
    assert loaded.trust_state == "trusted_signed"
    assert loaded.manifest == manifest()
    assert loaded.runner_entries["linux-x86_64"].executable is True
    assert loaded.root_hash == loaded.signature["root_hash"]
    assert loaded.archive_sha256 == hashlib.sha256(archive).hexdigest()


def test_semver_host_compatibility_is_a_deterministic_intersection():
    assert semver_satisfies("0.1.0", ">=0.1.0 <1.0.0") is True
    assert semver_satisfies("1.0.0", ">=0.1.0 <1.0.0") is False
    assert semver_satisfies("1.0.0-alpha", ">=1.0.0") is False
    assert semver_satisfies("1.0.0-alpha.2", ">1.0.0-alpha.1 <1.0.0") is True
    assert semver_satisfies("1.0.0+build.7", "=1.0.0") is True
    with pytest.raises(PluginPackageError) as caught:
        semver_satisfies("0.1.0", "^0.1.0")
    assert caught.value.code == "invalid_semver"


def test_official_role_capability_bundle_verifies_with_published_key():
    repository = Path(__file__).resolve().parents[2]
    publisher_data = json.loads(
        (repository / "plugins/publishers/learnflow_official.json").read_text(encoding="utf-8")
    )
    loaded = load_plugin_package(
        repository / "plugins/dist/role_capability_graph-1.0.0.lfplugin",
        publishers=[
            TrustedPublisher(
                publisher_id=publisher_data["publisher_key"],
                key_id=publisher_data["key_id"],
                public_key=publisher_data["public_key"],
                trusted=publisher_data["trust_status"] == "trusted",
            )
        ],
    )
    assert loaded.plugin_id == "role_capability_graph"
    assert loaded.trust_state == "trusted_signed"
    assert sorted(loaded.runner_entries) == ["darwin-arm64", "linux-arm64", "linux-x86_64"]


def test_signature_cannot_be_replayed_after_entry_tampering():
    archive, publisher, _ = signed_archive()
    source = zipfile.ZipFile(io.BytesIO(archive))
    files = {info.filename: source.read(info) for info in source.infolist()}
    files["README.md"] = b"tampered"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as rewritten:
        for path, content in files.items():
            rewritten.writestr(path, content)

    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(output.getvalue(), publishers=[publisher])

    assert caught.value.code == "root_hash_mismatch"


def test_production_rejects_unsigned_and_development_requires_explicit_exception():
    files = package_files()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)

    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(output.getvalue())
    assert caught.value.code == "signature_required"

    loaded = load_plugin_package(
        output.getvalue(),
        policy=PackagePolicy(environment="development", allow_unsigned_development=True),
    )
    assert loaded.trust_state == "untrusted_development"


def test_revoked_publisher_is_rejected_even_in_development():
    archive, publisher, _ = signed_archive()
    revoked = TrustedPublisher(
        publisher_id=publisher.publisher_id,
        key_id=publisher.key_id,
        public_key=publisher.public_key,
        trusted=True,
        revoked=True,
    )
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(
            archive,
            publishers=[revoked],
            policy=PackagePolicy(environment="development", allow_unsigned_development=True),
        )
    assert caught.value.code == "publisher_revoked"


def test_learner_context_requires_explicit_valid_kernel_allow_list():
    files = package_files()
    package_manifest = json.loads(files["manifest.json"])
    package_manifest["host_ports"].append("learner_context.read.v1")
    package_manifest.pop("kernel_allow_list")
    files["manifest.json"] = json.dumps(package_manifest).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "invalid_manifest"

    package_manifest["kernel_allow_list"] = ["knowledge", "personality"]
    files["manifest.json"] = json.dumps(package_manifest).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "invalid_manifest"


def test_read_tool_cannot_alias_a_write_workflow_or_write_host_port():
    files = package_files()
    package_manifest = json.loads(files["manifest.json"])
    package_manifest["tools"][0]["workflow"] = "generate"
    files["manifest.json"] = json.dumps(package_manifest).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "invalid_manifest"

    package_manifest["tools"][0]["workflow"] = "explain"
    package_manifest["workflows"][1]["host_ports"] = ["event.record.v1"]
    files["manifest.json"] = json.dumps(package_manifest).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "invalid_manifest"

@pytest.mark.parametrize("unsafe_path", ["../escape", "/absolute", "safe\\..\\escape"])
def test_zip_path_traversal_is_rejected(unsafe_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(unsafe_path, b"bad")
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(
            output.getvalue(),
            policy=PackagePolicy(environment="development", allow_unsigned_development=True),
        )
    assert caught.value.code == "unsafe_archive_path"


def test_zip_symlink_and_active_surface_content_are_rejected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("manifest.json")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"target")
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(
            output.getvalue(),
            policy=PackagePolicy(environment="development", allow_unsigned_development=True),
        )
    assert caught.value.code == "unsafe_entry_type"

    files = package_files()
    surface = json.loads(files["surfaces/project.json"])
    surface["body"]["children"].append({"type": "text", "html": "<script>x</script>"})
    files["surfaces/project.json"] = json.dumps(surface).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "unsafe_surface"


def test_surface_manifest_cannot_hide_an_unvalidated_inline_definition():
    files = package_files()
    package_manifest = json.loads(files["manifest.json"])
    package_manifest["surfaces"][0]["schema"] = {
        "protocol": "learnflow.plugin-surface.v1",
        "id": "role_capability_project",
        "slot": "project.context.tabs",
        "body": {"type": "text", "html": "<script>unsafe()</script>"},
    }
    files["manifest.json"] = json.dumps(package_manifest).encode()
    archive, publisher, _ = signed_archive(files=files)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(archive, publishers=[publisher])
    assert caught.value.code == "invalid_surface"


def test_invalid_signature_bytes_and_missing_required_package_parts_are_rejected():
    archive, publisher, _ = signed_archive()
    source = zipfile.ZipFile(io.BytesIO(archive))
    files = {info.filename: source.read(info) for info in source.infolist()}
    signature = json.loads(files["signature.json"])
    signature["signature"] = base64.b64encode(b"x" * 64).decode()
    files["signature.json"] = json.dumps(signature).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as rewritten:
        for path, content in files.items():
            rewritten.writestr(path, content)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(output.getvalue(), publishers=[publisher])
    assert caught.value.code == "invalid_signature"

    for missing in (
        "README.md",
        "LICENSE",
        "schemas/workflow-input.schema.json",
        "bin/linux-x86_64/runner",
    ):
        incomplete = package_files()
        incomplete.pop(missing)
        candidate, trusted, _ = signed_archive(files=incomplete)
        with pytest.raises(PluginPackageError) as caught:
            load_plugin_package(candidate, publishers=[trusted])
        assert caught.value.code in {
            "missing_required_entry",
            "invalid_schema_reference",
            "invalid_runner",
        }


def test_archive_entry_count_and_compression_budgets_are_enforced():
    too_many = io.BytesIO()
    with zipfile.ZipFile(too_many, "w") as archive:
        for index in range(513):
            archive.writestr(f"assets/{index}.txt", b"x")
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(
            too_many.getvalue(),
            policy=PackagePolicy(environment="development", allow_unsigned_development=True),
        )
    assert caught.value.code == "too_many_entries"

    compressed = io.BytesIO()
    with zipfile.ZipFile(compressed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("assets/compression-bomb.txt", b"a" * 1_000_000)
    with pytest.raises(PluginPackageError) as caught:
        load_plugin_package(
            compressed.getvalue(),
            policy=PackagePolicy(environment="development", allow_unsigned_development=True),
        )
    assert caught.value.code == "suspicious_compression"


def test_plugin_models_expose_six_layer_contract_tables():
    expected = {
        "plugin_publishers": PluginPublisher,
        "plugin_releases": PluginRelease,
        "plugin_instances": PluginInstance,
        "plugin_snapshots": PluginSnapshot,
        "plugin_object_index": PluginObjectIndex,
        "plugin_runs": PluginRun,
        "plugin_run_events": PluginRunEvent,
    }
    for table_name, model in expected.items():
        assert model.__table__ is Base.metadata.tables[table_name]
    assert {column.name for column in PluginInstance.__table__.columns} >= {
        "learner_id",
        "project_id",
        "release_id",
        "configuration",
        "granted_host_ports",
        "current_snapshot_id",
    }
    assert {column.name for column in PluginSnapshot.__table__.columns} >= {
        "parent_snapshot_id",
        "root_hash",
        "components",
        "validation",
        "provenance",
    }


def test_content_addressed_store_is_canonical_atomic_and_rebuildable(tmp_path):
    store = PluginArtifactStore(tmp_path / "cas")
    first = store.put_json({"b": 2, "a": 1}, name="graph/data.json")
    second = store.put_bytes(b'{"a":1,"b":2}', media_type="application/json")
    assert first.uri == second.uri
    assert store.read(first.uri) == b'{"a":1,"b":2}'
    assert store.resolve(first.uri).is_file()

    one = store.commit_components({"views/list.json": {"items": [1]}, "graph.json": {"nodes": []}})
    two = store.commit_components({"graph.json": {"nodes": []}, "views/list.json": {"items": [1]}})
    assert one.root_hash == two.root_hash
    assert one.to_manifest() == two.to_manifest()


def test_content_store_detects_hash_mismatch_and_only_collects_unreferenced(tmp_path):
    store = PluginArtifactStore(tmp_path / "cas")
    keep = store.put_bytes(b"keep")
    remove = store.put_bytes(b"remove")
    with pytest.raises(PluginArtifactError) as caught:
        store.put_bytes(b"content", expected_sha256="0" * 64)
    assert caught.value.code == "artifact_hash_mismatch"

    removed = store.collect_orphans(
        {keep.sha256}, older_than_seconds=0, now=store.resolve(remove.uri).stat().st_mtime + 1
    )
    assert removed == [remove.sha256]
    assert store.exists(keep.uri)
    assert not store.exists(remove.uri)


def test_content_store_materializes_verified_runner_without_overwrite(tmp_path):
    store = PluginArtifactStore(tmp_path / "cas")
    runner = store.put_bytes(b"#!/bin/sh\nexit 0\n")
    destination = tmp_path / "runtime" / "runner"
    destination.parent.mkdir()
    assert store.materialize_executable(runner.uri, destination) == destination
    assert destination.read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert destination.stat().st_mode & 0o777 == 0o500
    with pytest.raises(PluginArtifactError) as caught:
        store.materialize_executable(runner.uri, destination)
    assert caught.value.code == "materialization_target_exists"


def test_content_store_safely_materializes_complete_package(tmp_path):
    store = PluginArtifactStore(tmp_path / "cas")
    manifest = store.put_bytes(b"{}")
    runner = store.put_bytes(b"#!/bin/sh\n")
    destination = tmp_path / "package"
    destination.mkdir()
    paths = store.materialize_package(
        {
            "manifest.json": manifest.to_dict(),
            "bin/linux-x86_64/runner": runner.uri,
        },
        destination,
        executable_paths={"bin/linux-x86_64/runner"},
    )
    assert paths["manifest.json"].stat().st_mode & 0o777 == 0o400
    assert paths["bin/linux-x86_64/runner"].stat().st_mode & 0o777 == 0o500
    assert paths["bin/linux-x86_64/runner"].read_bytes() == b"#!/bin/sh\n"

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "existing").write_text("keep")
    with pytest.raises(PluginArtifactError) as caught:
        store.materialize_package({"manifest.json": manifest.uri}, occupied)
    assert caught.value.code == "materialization_target_not_empty"

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(PluginArtifactError) as caught:
        store.materialize_package({"../escape": manifest.uri}, empty)
    assert caught.value.code == "invalid_component_name"
