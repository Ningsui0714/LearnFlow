#!/usr/bin/env python3
"""Build a deterministic, signed LearnFlow ``.lfplugin`` ZIP archive."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PACKAGE_PROTOCOL = "learnflow.plugin-package.v1"
SIGNATURE_PROTOCOL = "learnflow.plugin-signature.v1"
ALLOWED_ROOT_FILES = {"manifest.json", "signature.json", "README.md", "LICENSE", "runner.py"}
ALLOWED_PREFIXES = ("bin/", "schemas/", "surfaces/", "assets/")


def package_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"plugin packages cannot contain links or special files: {path}")
        relative = path.relative_to(root).as_posix()
        pure = PurePosixPath(relative)
        if any(part in {"", ".", "..", "__pycache__"} for part in pure.parts) or relative.endswith((".pyc", ".pyo")):
            continue
        if relative not in ALLOWED_ROOT_FILES and not relative.startswith(ALLOWED_PREFIXES):
            raise ValueError(f"unexpected package source entry: {relative}")
        result[relative] = path.read_bytes()
    return result


def root_hash(entries: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{PACKAGE_PROTOCOL}\0".encode("ascii"))
    for path in sorted(item for item in entries if item != "signature.json"):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(entries[path]).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_private_key(path: Path) -> Ed25519PrivateKey:
    raw = path.read_bytes()
    try:
        candidate = serialization.load_pem_private_key(raw, password=None)
    except ValueError:
        decoded = base64.b64decode(raw.strip(), validate=True)
        candidate = Ed25519PrivateKey.from_private_bytes(decoded)
    if not isinstance(candidate, Ed25519PrivateKey):
        raise ValueError("signing key must be Ed25519")
    return candidate


def signature_document(
    digest: str,
    *,
    existing: bytes | None,
    private_key_path: Path | None,
    publisher_id: str,
    key_id: str,
) -> bytes:
    if private_key_path:
        key = load_private_key(private_key_path)
        signature = key.sign(f"{PACKAGE_PROTOCOL}\n{digest}".encode("ascii"))
        value = {
            "protocol": SIGNATURE_PROTOCOL,
            "algorithm": "ed25519",
            "publisher_id": publisher_id,
            "key_id": key_id,
            "root_hash": digest,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if not existing:
        raise ValueError("signature.json is missing; pass --private-key to sign")
    value = json.loads(existing.decode("utf-8"))
    if value.get("protocol") != SIGNATURE_PROTOCOL or value.get("root_hash") != digest:
        raise ValueError("signature.json does not match the current package root")
    return existing


def zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    executable = path.startswith("bin/") and path.endswith("/runner")
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--publisher-id", default="learnflow_official")
    parser.add_argument("--key-id", default="learnflow-official-ed25519-v1")
    parser.add_argument("--write-signature", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    entries = package_files(source)
    digest = root_hash(entries)
    signature = signature_document(
        digest,
        existing=entries.get("signature.json"),
        private_key_path=args.private_key,
        publisher_id=args.publisher_id,
        key_id=args.key_id,
    )
    entries["signature.json"] = signature
    if args.write_signature:
        (source / "signature.json").write_bytes(signature)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w") as archive:
            for path in sorted(entries):
                archive.writestr(zip_info(path), entries[path])
        os.replace(temp_path, output)
    finally:
        temp_path.unlink(missing_ok=True)
    print(json.dumps({"output": str(output), "root_hash": digest, "entries": len(entries)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
