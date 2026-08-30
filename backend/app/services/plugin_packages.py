"""Validation and signature verification for ``.lfplugin`` bundles.

Package import is intentionally separate from package execution.  A valid
signature establishes publisher identity and byte integrity only; it does not
claim that a native runner is sandboxed or safe.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass, field
from functools import total_ordering
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Mapping, Sequence
from urllib.parse import urldefrag, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


PACKAGE_PROTOCOL = "learnflow.plugin-package.v1"
SIGNATURE_PROTOCOL = "learnflow.plugin-signature.v1"
SURFACE_PROTOCOL = "learnflow.plugin-surface.v1"
SIGNATURE_FILE = "signature.json"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ENTRY_COUNT = 512
MAX_COMPRESSION_RATIO = 200

_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*$")
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*-[a-z0-9][a-z0-9_-]*$")
_DISALLOWED_CODE_SUFFIXES = {".sql", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_DISALLOWED_CACHE_SUFFIXES = {".pyc", ".pyo"}
_OWNER_AGENTS = {"tutor_agent", "learning_design_agent", "practice_agent"}
_KERNELS = {"structure", "knowledge", "human", "value", "practice"}
_HOST_PORTS = {
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
}
_SURFACE_NODE_TYPES = {
    "section",
    "text",
    "metric",
    "list",
    "table",
    "graph",
    "form",
    "input",
    "citation",
    "status",
    "action",
}
_SURFACE_NODE_KEYS = {
    "type",
    "id",
    "label",
    "text",
    "value",
    "items",
    "columns",
    "rows",
    "children",
    "fields",
    "body",
    "workflow_id",
    "workflow",
    "input",
    "title",
    "source",
    "nodes",
    "edges",
    "submit_label",
    "name",
    "required",
    "multiple",
    "requires_confirmation",
}
_FORBIDDEN_SURFACE_KEYS = {"html", "script", "style", "url", "href"}


class PluginPackageError(ValueError):
    """A stable, API-friendly package rejection."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@total_ordering
@dataclass(frozen=True, eq=False)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = field(default_factory=tuple, compare=False)
    build: tuple[str, ...] = field(default_factory=tuple, compare=False)

    def _core(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        # Build metadata never changes SemVer precedence or equality for range
        # matching; prerelease identifiers do.
        return self._core() == other._core() and self.prerelease == other.prerelease

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self._core() != other._core():
            return self._core() < other._core()
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __hash__(self) -> int:
        return hash((*self._core(), self.prerelease))

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = _SEMVER_RE.fullmatch(str(value or ""))
        if not match:
            raise PluginPackageError("invalid_semver", f"invalid SemVer: {value!r}")
        return cls(
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            tuple((match.group("prerelease") or "").split("."))
            if match.group("prerelease")
            else (),
            tuple((match.group("build") or "").split(".")) if match.group("build") else (),
        )


_SEMVER_REQUIREMENT_RE = re.compile(r"^(<=|>=|<|>|=)?(.+)$")


def semver_satisfies(version: str, requirement: str) -> bool:
    """Evaluate the small, deterministic comparator set used by v1 manifests.

    A requirement is a whitespace-separated intersection such as
    ``>=0.1.0 <1.0.0``.  More expressive range syntaxes are intentionally not
    accepted until the package protocol versions them explicitly.
    """

    current = SemVer.parse(version)
    tokens = str(requirement or "").split()
    if not tokens:
        raise _package_error("invalid_host_compatibility", "host version range is empty")
    for token in tokens:
        match = _SEMVER_REQUIREMENT_RE.fullmatch(token)
        if not match:
            raise _package_error("invalid_host_compatibility", "host version range is invalid")
        operator = match.group(1) or "="
        target = SemVer.parse(match.group(2))
        matched = {
            "=": current == target,
            ">": current > target,
            ">=": current >= target,
            "<": current < target,
            "<=": current <= target,
        }[operator]
        if not matched:
            return False
    return True


@dataclass(frozen=True)
class TrustedPublisher:
    publisher_id: str
    key_id: str
    public_key: str | bytes
    trusted: bool = True
    revoked: bool = False


@dataclass(frozen=True)
class PackagePolicy:
    environment: str = "production"
    allow_unsigned_development: bool = False

    @property
    def is_development(self) -> bool:
        return self.environment.casefold() in {"development", "dev", "test"}


@dataclass(frozen=True)
class PackageEntry:
    path: str
    content: bytes
    sha256: str
    size: int
    executable: bool = False


@dataclass(frozen=True)
class LoadedPluginPackage:
    manifest: dict[str, Any]
    signature: dict[str, Any]
    root_hash: str
    trust_state: str
    entries: Mapping[str, PackageEntry]
    archive_sha256: str

    @property
    def plugin_id(self) -> str:
        return str(self.manifest["plugin_id"])

    @property
    def version(self) -> str:
        return str(self.manifest["version"])

    @property
    def runner_entries(self) -> dict[str, PackageEntry]:
        return {
            platform: self.entries[path]
            for platform, path in self.manifest["runners"].items()
        }


def _package_error(code: str, message: str, **details: Any) -> PluginPackageError:
    return PluginPackageError(code, message, details=details)


def _read_source(source: bytes | bytearray | memoryview | str | Path | BinaryIO) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    elif isinstance(source, (str, Path)):
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise _package_error("package_read_failed", f"cannot read plugin package: {exc}") from exc
        if size > MAX_ARCHIVE_BYTES:
            raise _package_error("archive_too_large", "plugin package exceeds archive budget", size=size)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise _package_error("package_read_failed", f"cannot read plugin package: {exc}") from exc
    else:
        data = source.read(MAX_ARCHIVE_BYTES + 1)
        if not isinstance(data, bytes):
            raise _package_error("package_read_failed", "plugin package stream must be binary")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise _package_error("archive_too_large", "plugin package exceeds archive budget", size=len(data))
    return data


def _safe_archive_path(raw: str) -> str:
    if not raw or "\\" in raw or "\x00" in raw or any(ord(char) < 32 for char in raw):
        raise _package_error("unsafe_archive_path", "archive contains an unsafe path", path=raw)
    pure = PurePosixPath(raw)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise _package_error("unsafe_archive_path", "archive path escapes package root", path=raw)
    normalized = pure.as_posix().rstrip("/")
    if not normalized or normalized.startswith("/") or ":" in pure.parts[0]:
        raise _package_error("unsafe_archive_path", "archive contains an unsafe path", path=raw)
    return normalized


def _is_symlink_or_special(info: zipfile.ZipInfo) -> tuple[bool, bool]:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    is_symlink = kind == stat.S_IFLNK
    is_special = bool(kind and kind not in {stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK})
    return is_symlink, is_special


def _read_entries(data: bytes) -> dict[str, PackageEntry]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise _package_error("invalid_archive", "plugin package is not a valid ZIP archive") from exc
    entries: dict[str, PackageEntry] = {}
    total_size = 0
    try:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRY_COUNT:
            raise _package_error("too_many_entries", "plugin package contains too many entries")
        for info in infos:
            path = _safe_archive_path(info.filename)
            if path in entries:
                raise _package_error("duplicate_entry", "plugin package contains duplicate paths", path=path)
            symlink, special = _is_symlink_or_special(info)
            if symlink or special:
                raise _package_error(
                    "unsafe_entry_type", "links and special files are not allowed", path=path
                )
            if info.flag_bits & 0x1:
                raise _package_error("encrypted_entry", "encrypted package entries are not allowed", path=path)
            if info.is_dir():
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                raise _package_error("entry_too_large", "package entry exceeds size budget", path=path)
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise _package_error(
                    "archive_expansion_too_large", "expanded plugin package exceeds size budget"
                )
            if info.file_size and info.compress_size == 0:
                raise _package_error("suspicious_compression", "invalid compression ratio", path=path)
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise _package_error("suspicious_compression", "compression ratio exceeds budget", path=path)
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                raise _package_error("entry_read_failed", "cannot verify package entry", path=path) from exc
            if len(content) != info.file_size:
                raise _package_error("entry_size_mismatch", "package entry size mismatch", path=path)
            mode = (info.external_attr >> 16) & 0xFFFF
            entries[path] = PackageEntry(
                path=path,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
                executable=bool(mode & 0o111),
            )
    finally:
        archive.close()
    return entries


def compute_package_root_hash(entries: Mapping[str, bytes | PackageEntry]) -> str:
    """Return the deterministic release hash, excluding ``signature.json``."""

    digest = hashlib.sha256()
    digest.update(f"{PACKAGE_PROTOCOL}\0".encode("ascii"))
    for path in sorted(item for item in entries if item != SIGNATURE_FILE):
        safe_path = _safe_archive_path(path)
        value = entries[path]
        content = value.content if isinstance(value, PackageEntry) else bytes(value)
        digest.update(safe_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def signature_payload(root_hash: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", root_hash):
        raise _package_error("invalid_root_hash", "package root hash must be lowercase SHA-256")
    return f"{PACKAGE_PROTOCOL}\n{root_hash}".encode("ascii")


def _json_entry(entries: Mapping[str, PackageEntry], path: str, *, required: bool = True) -> dict[str, Any]:
    entry = entries.get(path)
    if entry is None:
        if not required:
            return {}
        raise _package_error("missing_required_entry", f"plugin package is missing {path}", path=path)
    try:
        parsed = json.loads(entry.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _package_error("invalid_json", f"{path} must contain a UTF-8 JSON object", path=path) from exc
    if not isinstance(parsed, dict):
        raise _package_error("invalid_json", f"{path} must contain a JSON object", path=path)
    return parsed


def _require_object_list(manifest: Mapping[str, Any], field_name: str) -> list[dict[str, Any]]:
    value = manifest.get(field_name)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _package_error("invalid_manifest", f"manifest.{field_name} must be an object list")
    ids = [item.get("id") for item in value]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise _package_error(
            "invalid_manifest", f"manifest.{field_name} entries require unique string ids"
        )
    return value


def _validate_schema_references(
    declarations: Sequence[Mapping[str, Any]], entries: Mapping[str, PackageEntry]
) -> None:
    validated: set[str] = set()

    def validate_schema(path: str) -> None:
        if path in validated:
            return
        validated.add(path)
        document = _json_entry(entries, path)
        try:
            Draft202012Validator.check_schema(document)
        except SchemaError as exc:
            raise _package_error(
                "invalid_schema",
                "packaged JSON schema is invalid",
                path=path,
                error=str(exc)[:500],
            ) from exc

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                schema_id = value.get("$id")
                if schema_id is not None:
                    parsed_id = urlsplit(str(schema_id))
                    if (
                        not isinstance(schema_id, str)
                        or parsed_id.scheme
                        or parsed_id.netloc
                        or parsed_id.fragment
                        or str(schema_id).startswith("/")
                        or "\\" in str(schema_id)
                    ):
                        raise _package_error(
                            "unsafe_schema_reference",
                            "packaged schema $id values must remain local",
                            path=path,
                        )
                for ref_key in ("$ref", "$dynamicRef"):
                    reference = value.get(ref_key)
                    if reference is None:
                        continue
                    if not isinstance(reference, str):
                        raise _package_error(
                            "invalid_schema_reference",
                            f"{ref_key} must be a string",
                            path=path,
                        )
                    raw_target, _fragment = urldefrag(reference)
                    if not raw_target:
                        continue
                    parsed = urlsplit(raw_target)
                    target_parts = PurePosixPath(raw_target).parts
                    if (
                        parsed.scheme
                        or parsed.netloc
                        or raw_target.startswith("/")
                        or "\\" in raw_target
                        or any(part in {"", ".", ".."} for part in target_parts)
                    ):
                        raise _package_error(
                            "unsafe_schema_reference",
                            "schema references may only target packaged local schemas",
                            path=path,
                            reference=reference,
                        )
                    target = (PurePosixPath(path).parent / PurePosixPath(raw_target)).as_posix()
                    if (
                        not target.startswith("schemas/")
                        or not target.endswith(".json")
                        or target not in entries
                    ):
                        raise _package_error(
                            "invalid_schema_reference",
                            "schema reference does not resolve to a packaged JSON schema",
                            path=path,
                            reference=reference,
                        )
                    validate_schema(target)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(document)

    for declaration in declarations:
        for field_name in ("input_schema", "output_schema", "schema"):
            reference = declaration.get(field_name)
            if reference is None:
                continue
            if (
                not isinstance(reference, str)
                or not reference.startswith("schemas/")
                or not reference.endswith(".json")
                or reference not in entries
            ):
                raise _package_error(
                    "invalid_schema_reference",
                    f"{field_name} must reference a packaged JSON schema",
                    reference=reference,
                )
            validate_schema(reference)


def _reject_active_surface_content(value: Any) -> None:
    if isinstance(value, dict):
        if set(value) & _FORBIDDEN_SURFACE_KEYS:
            raise _package_error(
                "unsafe_surface", "surface definitions cannot contain active content or URLs"
            )
        for child in value.values():
            _reject_active_surface_content(child)
    elif isinstance(value, list):
        for child in value:
            _reject_active_surface_content(child)


def _validate_surface_node(node: Any, workflow_ids: set[str]) -> None:
    if not isinstance(node, dict) or node.get("type") not in _SURFACE_NODE_TYPES:
        raise _package_error("invalid_surface", "surface node type is not allowed")
    unknown_keys = sorted(set(node) - _SURFACE_NODE_KEYS)
    if unknown_keys:
        raise _package_error(
            "invalid_surface", "surface node contains unsupported fields", fields=unknown_keys
        )
    referenced_workflow = node.get("workflow_id", node.get("workflow"))
    if node["type"] in {"action", "form"} and referenced_workflow not in workflow_ids:
        raise _package_error("invalid_surface", "surface action references an undeclared workflow")
    for key in ("children", "body", "fields"):
        children = node.get(key, [])
        if children is None:
            continue
        if not isinstance(children, list):
            raise _package_error("invalid_surface", f"surface node {key} must be a list")
        for child in children:
            _validate_surface_node(child, workflow_ids)


def _validate_surfaces(
    manifest: Mapping[str, Any], entries: Mapping[str, PackageEntry], workflows: Sequence[Mapping[str, Any]]
) -> None:
    workflow_ids = {str(item["id"]) for item in workflows}
    for surface in _require_object_list(manifest, "surfaces"):
        # Installable packages have one canonical, signed surface document.
        # Accepting an additional inline body here would let import validation
        # inspect different bytes from those returned by the runtime host.
        if "schema" in surface or "body" in surface:
            raise _package_error(
                "invalid_surface",
                "installable surfaces must use only their packaged definition resource",
                surface_id=surface.get("id"),
            )
        resource = surface.get("definition", surface.get("resource"))
        if not isinstance(resource, str) or not resource.startswith("surfaces/"):
            raise _package_error("invalid_manifest", "surface.resource must point into surfaces/")
        document = _json_entry(entries, resource)
        _reject_active_surface_content(document)
        if document.get("protocol") != SURFACE_PROTOCOL:
            raise _package_error("invalid_surface", "surface protocol is unsupported", path=resource)
        if document.get("id") != surface.get("id") or document.get("slot") != surface.get("slot"):
            raise _package_error("invalid_surface", "surface identity does not match manifest", path=resource)
        raw_body = document.get("body")
        body = raw_body if isinstance(raw_body, list) else [raw_body]
        if not body or any(node is None for node in body):
            raise _package_error("invalid_surface", "surface.body must contain nodes", path=resource)
        for node in body:
            _validate_surface_node(node, workflow_ids)


def validate_manifest(manifest: Mapping[str, Any], entries: Mapping[str, PackageEntry]) -> dict[str, Any]:
    """Validate package declarations without granting any runtime authority."""

    if manifest.get("protocol") != PACKAGE_PROTOCOL:
        raise _package_error("unsupported_protocol", "unsupported plugin package protocol")
    plugin_id = manifest.get("plugin_id")
    if not isinstance(plugin_id, str) or not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise _package_error("invalid_manifest", "manifest.plugin_id is invalid")
    version = manifest.get("version")
    if not isinstance(version, str):
        raise _package_error("invalid_manifest", "manifest.version must be a string")
    SemVer.parse(version)
    if not isinstance(manifest.get("host_compatibility"), dict):
        raise _package_error("invalid_manifest", "manifest.host_compatibility must be an object")
    host_compatibility = dict(manifest["host_compatibility"])
    if not isinstance(host_compatibility.get("learnflow"), str):
        raise _package_error("invalid_host_compatibility", "manifest must declare a LearnFlow SemVer range")
    # Parse the range now so malformed releases cannot enter the catalog.  The
    # actual installed host version is checked by the deterministic importer.
    semver_satisfies("0.0.0", host_compatibility["learnflow"])
    if not isinstance(host_compatibility.get("plugin_host"), str):
        raise _package_error("invalid_host_compatibility", "manifest must declare a plugin host protocol")
    if manifest.get("owner") not in _OWNER_AGENTS:
        raise _package_error("invalid_manifest", "manifest.owner must be one of the three main agents")
    if manifest.get("scope") != "project":
        raise _package_error("invalid_manifest", "v1 plugins must use project scope")

    object_types = manifest.get("object_types")
    if (
        not isinstance(object_types, list)
        or not object_types
        or any(not isinstance(item, str) or not _PLUGIN_ID_RE.fullmatch(item) for item in object_types)
        or len(object_types) != len(set(object_types))
    ):
        raise _package_error("invalid_manifest", "manifest.object_types must contain unique stable ids")
    host_ports = manifest.get("host_ports")
    if (
        not isinstance(host_ports, list)
        or any(not isinstance(item, str) for item in host_ports)
        or len(host_ports) != len(set(host_ports))
    ):
        raise _package_error("invalid_manifest", "manifest.host_ports must be a unique string list")
    unknown_ports = sorted(set(host_ports or []) - _HOST_PORTS)
    if unknown_ports:
        raise _package_error(
            "unknown_host_port", "manifest requests unknown host ports", ports=unknown_ports
        )
    kernel_allow_list = manifest.get("kernel_allow_list")
    if kernel_allow_list is not None and (
        not isinstance(kernel_allow_list, list)
        or any(not isinstance(item, str) for item in kernel_allow_list)
        or len(kernel_allow_list) != len(set(kernel_allow_list))
        or not set(kernel_allow_list).issubset(_KERNELS)
    ):
        raise _package_error(
            "invalid_manifest",
            "manifest.kernel_allow_list must be a unique subset of the five kernels",
        )
    if "learner_context.read.v1" in host_ports and kernel_allow_list is None:
        raise _package_error(
            "invalid_manifest",
            "learner_context.read.v1 requires an explicit kernel_allow_list",
        )

    workflows = _require_object_list(manifest, "workflows")
    tools = _require_object_list(manifest, "tools")
    skills = _require_object_list(manifest, "skills")
    events = _require_object_list(manifest, "events")
    _validate_schema_references([*workflows, *tools], entries)
    workflow_ids = {str(item["id"]) for item in workflows}
    workflow_by_id = {str(item["id"]): item for item in workflows}
    for workflow in workflows:
        if str(workflow.get("mode") or "").casefold() not in {
            "read", "write", "write_snapshot", "migration", "artifact", "transaction",
        }:
            raise _package_error(
                "invalid_manifest", "plugin workflow mode is unsupported"
            )
        required_ports = workflow.get(
            "host_ports", workflow.get("required_host_ports", host_ports)
        )
        if (
            not isinstance(required_ports, list)
            or any(not isinstance(item, str) for item in required_ports)
            or len(required_ports) != len(set(required_ports))
            or not set(required_ports).issubset(set(host_ports))
        ):
            raise _package_error(
                "invalid_manifest",
                "workflow Host Ports must be a unique subset of manifest.host_ports",
            )
    if not isinstance(manifest.get("config_schema"), dict):
        raise _package_error("invalid_manifest", "manifest.config_schema must be an object")
    try:
        Draft202012Validator.check_schema(manifest["config_schema"])
    except SchemaError as exc:
        raise _package_error(
            "invalid_schema", "manifest.config_schema is not a valid JSON schema"
        ) from exc

    def reject_external_config_refs(value: Any) -> None:
        if isinstance(value, dict):
            for ref_key in ("$ref", "$dynamicRef"):
                reference = value.get(ref_key)
                if reference is not None and (
                    not isinstance(reference, str) or bool(urldefrag(reference)[0])
                ):
                    raise _package_error(
                        "unsafe_schema_reference",
                        "inline config schema may only use internal fragment references",
                    )
            for child in value.values():
                reject_external_config_refs(child)
        elif isinstance(value, list):
            for child in value:
                reject_external_config_refs(child)

    reject_external_config_refs(manifest["config_schema"])
    for tool in tools:
        if tool.get("mode") not in {"read", "proposal"}:
            raise _package_error("invalid_manifest", "plugin tools must declare read or proposal mode")
        if tool.get("workflow") not in workflow_ids:
            raise _package_error("invalid_manifest", "plugin tool references an undeclared workflow")
        if tool.get("mode") == "read":
            target_workflow = workflow_by_id[str(tool["workflow"])]
            if str(target_workflow.get("mode") or "").casefold() != "read":
                raise _package_error(
                    "invalid_manifest",
                    "read-only plugin tools must reference read-only workflows",
                )
            required_ports = target_workflow.get(
                "host_ports", target_workflow.get("required_host_ports", host_ports)
            )
            if not isinstance(required_ports, list) or {
                "action.propose.v1", "event.record.v1"
            } & set(required_ports):
                raise _package_error(
                    "invalid_manifest",
                    "read-only plugin tools cannot use proposal or event write ports",
                )
    for skill in skills:
        referenced = skill.get("workflows", [])
        if not isinstance(referenced, list) or any(item not in workflow_ids for item in referenced):
            raise _package_error("invalid_manifest", "plugin skill references undeclared workflows")
    for event in events:
        targets = event.get("kernel_targets", event.get("target_kernels", []))
        if targets not in (None, []):
            raise _package_error(
                "kernel_event_forbidden", "external plugin events cannot target learner kernels"
            )

    runners = manifest.get("runners")
    if not isinstance(runners, dict) or not runners:
        raise _package_error("invalid_manifest", "manifest.runners must map platforms to package paths")
    for platform, path in runners.items():
        expected = f"bin/{platform}/runner"
        if (
            not isinstance(platform, str)
            or not _PLATFORM_RE.fullmatch(platform)
            or not isinstance(path, str)
            or path != expected
            or path not in entries
            or not entries[path].content
        ):
            raise _package_error("invalid_runner", "runner declaration is invalid", platform=platform)

    if "README.md" not in entries or "LICENSE" not in entries:
        raise _package_error("missing_required_entry", "plugin package requires README.md and LICENSE")
    if not any(path.startswith("schemas/") and path.endswith(".json") for path in entries):
        raise _package_error("missing_required_entry", "plugin package requires JSON schemas")
    _validate_surfaces(manifest, entries, workflows)

    for path in entries:
        pure_path = PurePosixPath(path)
        if "__pycache__" in pure_path.parts or pure_path.name == ".DS_Store" or pure_path.suffix.casefold() in _DISALLOWED_CACHE_SUFFIXES:
            raise _package_error(
                "forbidden_package_content", "runtime caches cannot be shipped in plugin packages", path=path
            )
        if pure_path.suffix.casefold() in _DISALLOWED_CODE_SUFFIXES:
            raise _package_error(
                "forbidden_package_content",
                "SQL migrations and JavaScript/TypeScript injection are not allowed",
                path=path,
            )
    return dict(manifest)


def _load_public_key(value: str | bytes) -> Ed25519PublicKey:
    raw: bytes
    if isinstance(value, str):
        text = value.strip()
        if "BEGIN PUBLIC KEY" in text:
            try:
                key = serialization.load_pem_public_key(text.encode("ascii"))
            except (ValueError, TypeError, UnicodeEncodeError) as exc:
                raise _package_error("invalid_public_key", "publisher public key is invalid") from exc
            if not isinstance(key, Ed25519PublicKey):
                raise _package_error("invalid_public_key", "publisher key is not Ed25519")
            return key
        if text.startswith("ed25519:"):
            text = text.removeprefix("ed25519:")
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _package_error("invalid_public_key", "publisher public key is invalid") from exc
    else:
        raw = bytes(value)
    if len(raw) != 32:
        raise _package_error("invalid_public_key", "Ed25519 public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def _find_publisher(
    signature: Mapping[str, Any], publishers: Mapping[str, TrustedPublisher] | Sequence[TrustedPublisher]
) -> TrustedPublisher | None:
    values = publishers.values() if isinstance(publishers, Mapping) else publishers
    return next(
        (
            item
            for item in values
            if item.key_id == signature.get("key_id")
            and item.publisher_id == signature.get("publisher_id")
        ),
        None,
    )


def _verify_signature(
    signature: Mapping[str, Any],
    root_hash: str,
    policy: PackagePolicy,
    publishers: Mapping[str, TrustedPublisher] | Sequence[TrustedPublisher],
) -> str:
    if not signature:
        if policy.is_development and policy.allow_unsigned_development:
            return "untrusted_development"
        raise _package_error("signature_required", "plugin package must be signed")
    if signature.get("protocol") != SIGNATURE_PROTOCOL or signature.get("algorithm") != "ed25519":
        raise _package_error("invalid_signature", "signature protocol or algorithm is unsupported")
    if signature.get("root_hash") != root_hash:
        raise _package_error("root_hash_mismatch", "signed root hash does not match package content")
    publisher = _find_publisher(signature, publishers)
    if publisher is None:
        if policy.is_development and policy.allow_unsigned_development:
            return "untrusted_development"
        raise _package_error("publisher_not_trusted", "plugin publisher key is not installed")
    if publisher.revoked:
        raise _package_error("publisher_revoked", "plugin publisher key has been revoked")
    if not publisher.trusted:
        if policy.is_development and policy.allow_unsigned_development:
            trust_state = "untrusted_development"
        else:
            raise _package_error("publisher_not_trusted", "plugin publisher is not trusted")
    else:
        trust_state = "trusted_signed"
    encoded_signature = signature.get("signature")
    if not isinstance(encoded_signature, str):
        raise _package_error("invalid_signature", "signature bytes are missing")
    try:
        signature_bytes = base64.b64decode(encoded_signature, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _package_error("invalid_signature", "signature is not valid base64") from exc
    try:
        _load_public_key(publisher.public_key).verify(
            signature_bytes, signature_payload(root_hash)
        )
    except InvalidSignature as exc:
        raise _package_error("invalid_signature", "package signature verification failed") from exc
    return trust_state


def load_plugin_package(
    source: bytes | bytearray | memoryview | str | Path | BinaryIO,
    *,
    policy: PackagePolicy | None = None,
    publishers: Mapping[str, TrustedPublisher] | Sequence[TrustedPublisher] = (),
) -> LoadedPluginPackage:
    """Read, validate and authenticate a plugin bundle without extracting it."""

    selected_policy = policy or PackagePolicy()
    data = _read_source(source)
    entries = _read_entries(data)
    manifest = validate_manifest(_json_entry(entries, "manifest.json"), entries)
    signature = _json_entry(entries, SIGNATURE_FILE, required=False)
    root_hash = compute_package_root_hash(entries)
    trust_state = _verify_signature(signature, root_hash, selected_policy, publishers)
    return LoadedPluginPackage(
        manifest=manifest,
        signature=signature,
        root_hash=root_hash,
        trust_state=trust_state,
        entries=entries,
        archive_sha256=hashlib.sha256(data).hexdigest(),
    )


__all__ = [
    "LoadedPluginPackage",
    "PackageEntry",
    "PackagePolicy",
    "PluginPackageError",
    "SemVer",
    "TrustedPublisher",
    "compute_package_root_hash",
    "load_plugin_package",
    "signature_payload",
    "semver_satisfies",
    "validate_manifest",
]
