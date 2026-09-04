from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import override

from harbor.agents.installed.langgraph import LangGraph


class RoleAtlasLangGraphAgent(LangGraph):
    """Stage and run the production Role Atlas graph without verifier assets."""

    _STAGED_PATHS = (
        "lib",
        "packages/golden/llm-app-engineer/1.0.0",
        "evals/harbor_agents/role-atlas-evidence-agent.ts",
        "evals/harbor_agents/langgraph.role-atlas.json",
        "package.json",
        "package-lock.json",
        "tsconfig.json",
    )

    def __init__(self, project_path: str | Path | None = None, **kwargs):
        source_root = Path(project_path or Path.cwd()).expanduser().resolve()
        super().__init__(
            project_path=source_root,
            config="evals/harbor_agents/langgraph.role-atlas.json",
            node_version=22,
            node_install_command="npm ci",
            version="1.0.0",
            **kwargs,
        )

    @staticmethod
    @override
    def name() -> str:
        return "role-atlas-langgraph"

    def _base_revision(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    @override
    def _staged_project_dir(self) -> Path:
        target = self.logs_dir / "langgraph_project"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

        for relative in self._STAGED_PATHS:
            source = self.project_path / relative
            if not source.exists():
                raise FileNotFoundError(f"Required Role Atlas Harness source is missing: {source}")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                )
            else:
                shutil.copy2(source, destination)

        files = []
        for source in sorted(path for path in target.rglob("*") if path.is_file()):
            content = source.read_bytes()
            files.append(
                {
                    "path": source.relative_to(target).as_posix(),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                }
            )
        manifest_core = {
            "schemaVersion": "1.0",
            "baseRevision": self._base_revision(),
            "files": files,
        }
        encoded = json.dumps(
            manifest_core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        manifest = {
            **manifest_core,
            "sourceDigest": hashlib.sha256(encoded).hexdigest(),
        }
        (target / "role-atlas-source-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return target
