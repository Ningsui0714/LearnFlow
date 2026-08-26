"""Read-only project-source knowledge-domain projections.

These projections describe what processed sources contain.  They are context
for route and content decisions, never learner-state or mastery evidence.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.project import Source


def repository_knowledge_domains(sources: list[Source]) -> list[dict[str, Any]]:
    """Return the legacy grouped domain shape used by the roadmap planner."""
    result: list[dict[str, Any]] = []
    for source in sources:
        meta = source.meta_data or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        analysis = dict(meta.get("repo_analysis") or {})
        seen: set[str] = set()
        domains: list[dict[str, str]] = []

        def add(label: object, evidence: str) -> None:
            value = " ".join(str(label or "").split())[:160]
            key = value.casefold()
            if value and key not in seen and len(domains) < 12:
                seen.add(key)
                domains.append({"label": value, "evidence": evidence})

        for item in analysis.get("readme_toc") or []:
            if isinstance(item, dict):
                add(item.get("title"), "README 目录")
        for group in analysis.get("dir_groups") or []:
            if isinstance(group, dict) and group.get("is_chapter"):
                add(group.get("name") or group.get("dir"), "章节目录")
        if not domains:
            for path in (analysis.get("file_summaries") or {}).keys():
                add(path, "文件摘要路径")

        if domains:
            result.append({
                "source_id": source.id,
                "role": source.role or "main",
                "type": source.type,
                "structure_logic": analysis.get("structure_logic", "mixed"),
                "domains": domains,
            })
    return result


def flatten_repository_knowledge_domains(sources: list[Source]) -> list[dict[str, Any]]:
    """Return the bounded ACI shape consumed by the vNext Tutor runtime."""
    flattened: list[dict[str, Any]] = []
    for source in repository_knowledge_domains(sources):
        for index, domain in enumerate(source["domains"]):
            label = str(domain["label"])
            flattened.append({
                "id": f"project-source:{source['source_id']}:domain:{index + 1}",
                "title": label,
                "summary": (
                    f"由来源 {source['source_id']} 的{domain['evidence']}支持；"
                    f"来源角色 {source['role']}，结构 {source['structure_logic']}。"
                ),
                "labels": [label, str(source["type"]), str(source["role"])],
                "source_ids": [str(source["source_id"])],
            })
    return flattened[:30]
