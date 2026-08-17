"""Feature-scoped adapter for launching personalized learning from WF03.

The downstream endpoint is deliberately loaded from ``backend/.private`` so
the browser never receives service configuration and unrelated LearnFlow
features cannot depend on this integration accidentally.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit

import httpx
from dotenv import dotenv_values


class PersonalizedLearningHandoffConfigError(RuntimeError):
    """Raised when the feature-local downstream configuration is missing."""


class PersonalizedLearningHandoffError(RuntimeError):
    """Normalized downstream import failure."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PersonalizedLearningHandoffConfig:
    import_url: str
    timeout_seconds: float = 20.0


def default_config_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / ".private" / "personalized_learning.env"


def load_personalized_learning_handoff_config(
    path: str | Path | None = None,
) -> PersonalizedLearningHandoffConfig:
    config_path = Path(path) if path is not None else default_config_path()
    if not config_path.is_file():
        raise PersonalizedLearningHandoffConfigError(
            f"个性化学习交接私密配置不存在: {config_path}"
        )
    values: Mapping[str, str | None] = dotenv_values(config_path)
    import_url = str(values.get("PERSONALIZED_LEARNING_IMPORT_URL") or "").strip()
    parsed = urlsplit(import_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PersonalizedLearningHandoffConfigError(
            "PERSONALIZED_LEARNING_IMPORT_URL 必须是完整的 HTTP(S) 地址"
        )
    try:
        timeout_seconds = float(
            values.get("PERSONALIZED_LEARNING_TIMEOUT_SECONDS") or 20.0
        )
    except (TypeError, ValueError) as exc:
        raise PersonalizedLearningHandoffConfigError(
            "PERSONALIZED_LEARNING_TIMEOUT_SECONDS 必须为数字"
        ) from exc
    return PersonalizedLearningHandoffConfig(
        import_url=import_url,
        timeout_seconds=max(1.0, min(timeout_seconds, 120.0)),
    )


class PersonalizedLearningHandoffClient:
    """Import one verified knowledge-scoped handoff into personalized learning."""

    def __init__(
        self,
        *,
        config: PersonalizedLearningHandoffConfig | None = None,
        config_path: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or load_personalized_learning_handoff_config(config_path)
        self.transport = transport

    async def import_entry(
        self,
        *,
        learner_id: int,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "student_id": f"LEARNFLOW-{learner_id}",
            "handoff": handoff,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                # Local integration endpoints must not be routed through the
                # macOS system HTTP proxy (common in development machines).
                trust_env=False,
            ) as client:
                response = await client.post(self.config.import_url, json=payload)
        except httpx.TimeoutException as exc:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务响应超时，请稍后重试",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise PersonalizedLearningHandoffError(
                f"个性化学习服务不可用: {exc}",
                status_code=503,
            ) from exc

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            detail = str(
                body.get("user_message")
                or body.get("detail")
                or response.text
                or "下游导入失败"
            ).strip()[:500]
            raise PersonalizedLearningHandoffError(
                f"个性化学习服务拒绝了交接（{response.status_code}）：{detail}",
                status_code=502,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了无效 JSON"
            ) from exc
        if not isinstance(result, dict):
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回值必须是 JSON 对象"
            )
        redirect_path = str(result.get("redirect_url") or "").strip()
        if not redirect_path:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务没有返回可打开的项目地址"
            )
        redirect_url = urljoin(self.config.import_url, redirect_path)
        redirect_parts = urlsplit(redirect_url)
        import_parts = urlsplit(self.config.import_url)
        if (
            redirect_parts.scheme not in {"http", "https"}
            or redirect_parts.netloc != import_parts.netloc
        ):
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了不受信任的跳转地址"
            )
        return {
            "status": "ok",
            "entry_id": str(result.get("entry_id") or handoff.get("entry_id") or ""),
            "project_id": str(result.get("project_id") or ""),
            "knowledge_point_id": str(result.get("knowledge_point_id") or ""),
            "redirect_url": redirect_url,
            "created": bool(result.get("created")),
        }
