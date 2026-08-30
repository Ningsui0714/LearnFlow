"""Content-addressed storage for immutable plugin package and snapshot bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ARTIFACT_URI_PROTOCOL = "sha256"
MAX_COMPONENT_BYTES = 64 * 1024 * 1024
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PluginArtifactError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ArtifactDescriptor:
    uri: str
    sha256: str
    size: int
    media_type: str = "application/octet-stream"
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComponentInput:
    content: bytes
    media_type: str = "application/octet-stream"


@dataclass(frozen=True)
class ArtifactCommit:
    root_hash: str
    components: tuple[ArtifactDescriptor, ...]

    def to_manifest(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.components]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _component_name(value: str) -> str:
    if not value or "\\" in value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise PluginArtifactError("invalid_component_name", "component name is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginArtifactError("invalid_component_name", "component name escapes its snapshot")
    normalized = path.as_posix()
    if len(normalized.encode("utf-8")) > 512:
        raise PluginArtifactError("invalid_component_name", "component name is too long")
    return normalized


def _coerce_component(value: Any) -> ComponentInput:
    if isinstance(value, ComponentInput):
        result = value
    elif isinstance(value, bytes):
        result = ComponentInput(value)
    elif isinstance(value, str):
        result = ComponentInput(value.encode("utf-8"), "text/plain; charset=utf-8")
    else:
        result = ComponentInput(canonical_json_bytes(value), "application/json")
    if len(result.content) > MAX_COMPONENT_BYTES:
        raise PluginArtifactError("component_too_large", "plugin component exceeds size budget")
    return result


class PluginArtifactStore:
    """A small filesystem CAS; callers own database transactions and refs."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.objects_dir = self.root / "objects"
        self.temp_dir = self.root / ".tmp"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def uri_for(digest: str) -> str:
        if not _HASH_RE.fullmatch(digest):
            raise PluginArtifactError("invalid_artifact_hash", "artifact hash must be lowercase SHA-256")
        return f"{ARTIFACT_URI_PROTOCOL}:{digest}"

    @staticmethod
    def hash_from_uri(uri: str) -> str:
        prefix = f"{ARTIFACT_URI_PROTOCOL}:"
        if not isinstance(uri, str) or not uri.startswith(prefix):
            raise PluginArtifactError("invalid_artifact_uri", "unsupported artifact URI")
        digest = uri[len(prefix) :]
        if not _HASH_RE.fullmatch(digest):
            raise PluginArtifactError("invalid_artifact_uri", "artifact URI hash is invalid")
        return digest

    def _path_for_hash(self, digest: str) -> Path:
        self.uri_for(digest)
        return self.objects_dir / digest[:2] / digest[2:4] / digest

    def resolve(self, uri: str, *, require_exists: bool = True) -> Path:
        path = self._path_for_hash(self.hash_from_uri(uri))
        if require_exists and (not path.is_file() or path.is_symlink()):
            raise PluginArtifactError("artifact_not_found", "plugin artifact does not exist")
        return path

    def exists(self, uri: str) -> bool:
        try:
            path = self.resolve(uri, require_exists=False)
        except PluginArtifactError:
            return False
        return path.is_file() and not path.is_symlink()

    def put_bytes(
        self,
        content: bytes | bytearray | memoryview,
        *,
        media_type: str = "application/octet-stream",
        name: str = "",
        expected_sha256: str | None = None,
    ) -> ArtifactDescriptor:
        data = bytes(content)
        if len(data) > MAX_COMPONENT_BYTES:
            raise PluginArtifactError("artifact_too_large", "plugin artifact exceeds size budget")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise PluginArtifactError("artifact_hash_mismatch", "plugin artifact hash does not match")
        target = self._path_for_hash(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or target.stat().st_size != len(data) or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise PluginArtifactError("artifact_collision", "content-addressed artifact is corrupt")
        else:
            fd, raw_temp_path = tempfile.mkstemp(prefix=f"{digest}.", dir=self.temp_dir)
            temp_path = Path(raw_temp_path)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, target)
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return ArtifactDescriptor(
            uri=self.uri_for(digest),
            sha256=digest,
            size=len(data),
            media_type=str(media_type or "application/octet-stream"),
            name=_component_name(name) if name else "",
        )

    def put_json(self, value: Any, *, name: str = "") -> ArtifactDescriptor:
        return self.put_bytes(canonical_json_bytes(value), media_type="application/json", name=name)

    def read(self, uri: str, *, verify: bool = True) -> bytes:
        path = self.resolve(uri)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PluginArtifactError("artifact_read_failed", "cannot read plugin artifact") from exc
        if verify and hashlib.sha256(data).hexdigest() != self.hash_from_uri(uri):
            raise PluginArtifactError("artifact_hash_mismatch", "stored plugin artifact is corrupt")
        return data

    def materialize_executable(self, uri: str, destination: str | Path) -> Path:
        """Materialize a verified runner blob without following or replacing links."""

        target = Path(destination)
        if target.exists() or target.is_symlink():
            raise PluginArtifactError(
                "materialization_target_exists", "artifact materialization target already exists"
            )
        if not target.parent.is_dir() or target.parent.is_symlink():
            raise PluginArtifactError(
                "invalid_materialization_target", "runner destination parent must be a real directory"
            )
        return self._atomic_materialize(self.read(uri, verify=True), target, mode=0o500)

    @staticmethod
    def _atomic_materialize(data: bytes, target: Path, *, mode: int) -> Path:
        fd, raw_temp_path = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temp_path = Path(raw_temp_path)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.chmod(mode)
            if target.exists() or target.is_symlink():
                raise PluginArtifactError(
                    "materialization_target_exists", "artifact materialization target already exists"
                )
            os.replace(temp_path, target)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return target

    def materialize_package(
        self,
        entries: Mapping[str, str | Mapping[str, Any]],
        destination_dir: str | Path,
        *,
        executable_paths: set[str] | None = None,
    ) -> dict[str, Path]:
        """Safely expand CAS descriptors into an already-created empty temp dir."""

        root = Path(destination_dir)
        if not root.is_dir() or root.is_symlink():
            raise PluginArtifactError(
                "invalid_materialization_target", "package destination must be a real directory"
            )
        if any(root.iterdir()):
            raise PluginArtifactError(
                "materialization_target_not_empty", "package destination must be empty"
            )
        executable = {_component_name(path) for path in (executable_paths or set())}
        normalized: list[tuple[str, str]] = []
        for raw_path, raw_descriptor in entries.items():
            path = _component_name(str(raw_path))
            uri = (
                raw_descriptor
                if isinstance(raw_descriptor, str)
                else raw_descriptor.get("uri")
            )
            if not isinstance(uri, str):
                raise PluginArtifactError(
                    "invalid_artifact_descriptor", "package entry is missing an artifact URI"
                )
            self.hash_from_uri(uri)
            normalized.append((path, uri))
        if len(normalized) != len({path for path, _ in normalized}):
            raise PluginArtifactError(
                "duplicate_component", "package materialization paths must be unique"
            )
        path_set = {path for path, _ in normalized}
        for path in path_set:
            parents = PurePosixPath(path).parents
            if any(parent.as_posix() in path_set for parent in parents if parent.as_posix() != "."):
                raise PluginArtifactError(
                    "conflicting_package_paths", "package file paths conflict with directories"
                )

        output: dict[str, Path] = {}
        root_resolved = root.resolve()
        for path, uri in sorted(normalized):
            target = root.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.parent.is_symlink() or root_resolved not in target.resolve(strict=False).parents:
                raise PluginArtifactError(
                    "invalid_materialization_target", "package entry escapes destination"
                )
            output[path] = self._atomic_materialize(
                self.read(uri, verify=True),
                target,
                mode=0o500 if path in executable else 0o400,
            )
        return output

    def commit_components(self, components: Mapping[str, Any]) -> ArtifactCommit:
        """Validate all candidate components, then atomically install each CAS blob."""

        prepared: list[tuple[str, ComponentInput]] = []
        for raw_name, raw_value in components.items():
            prepared.append((_component_name(str(raw_name)), _coerce_component(raw_value)))
        if not prepared:
            raise PluginArtifactError("empty_snapshot", "a plugin snapshot needs at least one component")
        names = [name for name, _ in prepared]
        if len(names) != len(set(names)):
            raise PluginArtifactError("duplicate_component", "plugin snapshot component names must be unique")

        descriptors = tuple(
            self.put_bytes(value.content, media_type=value.media_type, name=name)
            for name, value in sorted(prepared, key=lambda item: item[0])
        )
        digest = hashlib.sha256()
        digest.update(b"learnflow.plugin-snapshot.v1\0")
        for descriptor in descriptors:
            digest.update(descriptor.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(descriptor.sha256.encode("ascii"))
            digest.update(b"\n")
        return ArtifactCommit(root_hash=digest.hexdigest(), components=descriptors)

    def collect_orphans(
        self,
        referenced_hashes: set[str],
        *,
        older_than_seconds: float = 24 * 60 * 60,
        now: float | None = None,
    ) -> list[str]:
        """Delete only unreferenced regular CAS files older than the grace period."""

        invalid = sorted(value for value in referenced_hashes if not _HASH_RE.fullmatch(value))
        if invalid:
            raise PluginArtifactError("invalid_artifact_hash", "referenced artifact hash is invalid")
        cutoff = (time.time() if now is None else now) - max(0.0, older_than_seconds)
        removed: list[str] = []
        if not self.objects_dir.exists():
            return removed
        for path in self.objects_dir.glob("*/*/*"):
            if path.is_symlink() or not path.is_file() or not _HASH_RE.fullmatch(path.name):
                continue
            if path.name in referenced_hashes or path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed.append(path.name)
        return sorted(removed)


__all__ = [
    "ArtifactCommit",
    "ArtifactDescriptor",
    "ComponentInput",
    "PluginArtifactError",
    "PluginArtifactStore",
    "canonical_json_bytes",
]
