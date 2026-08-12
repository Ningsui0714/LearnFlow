from __future__ import annotations

import argparse
import base64
import hmac
import html
import ipaddress
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ElementTree
import zlib
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from backend.domain import LearningDomainStore, StudentModelCache
except ModuleNotFoundError:
    from domain import LearningDomainStore, StudentModelCache

try:
    from backend.goal_engine import (
        build_learning_path,
        path_for_learning_goal,
        resolve_learning_goal,
    )
except ModuleNotFoundError:
    from goal_engine import build_learning_path, path_for_learning_goal, resolve_learning_goal

try:
    from backend.data.diagnosis_bank import (
        DIAGNOSIS_BANK,
        DIAGNOSIS_GOALS,
        select_diagnosis_questions,
        bank_question_by_id,
        bank_questions,
        check_bank_answer,
    )
except ModuleNotFoundError:
    from data.diagnosis_bank import (
        DIAGNOSIS_BANK,
        DIAGNOSIS_GOALS,
        select_diagnosis_questions,
        bank_question_by_id,
        bank_questions,
        check_bank_answer,
    )

try:
    from backend.data.goal_graph import (
        GOALS as GOAL_GRAPH_GOALS,
        KNOWLEDGE_POINTS as GRAPH_KNOWLEDGE_POINTS,
    )
except ModuleNotFoundError:
    from data.goal_graph import (
        GOALS as GOAL_GRAPH_GOALS,
        KNOWLEDGE_POINTS as GRAPH_KNOWLEDGE_POINTS,
    )

try:
    from backend.data.error_cards import default_error_card_for, error_cards_for
except ModuleNotFoundError:
    from data.error_cards import default_error_card_for, error_cards_for
try:
    from backend.learner_discovery.session import DiscoveryError, DiscoveryService
except ModuleNotFoundError:
    from learner_discovery.session import DiscoveryError, DiscoveryService


ROOT = PROJECT_ROOT
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_DATABASE = ROOT / "backend" / "data" / "learning_app.db"
MAX_BODY_BYTES = 2 * 1024 * 1024


def load_environment_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_json_object(value: Any) -> dict[str, Any] | None:
    objects = parse_json_objects(value)
    return objects[0] if objects else None


def parse_json_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, str):
        return []
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else stripped
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", stripped):
        try:
            parsed, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# 理解检查服务端判题：答案由服务端持有，客户端只提交 selected_answer。
# 与 frontend/app.js stageChecks 的题目/选项顺序保持一致（Java 面向对象实训）。
CHECK_ANSWER_REGISTRY = {
    "KN_JAVA_CLASS": "b",
    "KN_JAVA_ENCAPSULATION": "b",
    "KN_JAVA_INHERITANCE": "b",
    "KN_JAVA_POLYMORPHISM": "b",
    "KN_JAVA_COLLECTION": "b",
    "KN_JAVA_EXCEPTION": "b",
    "KN_JAVA_IO": "b",
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class GatewayError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    xingchen_mode: str
    api_url: str
    api_key: str
    api_secret: str
    auth_header: str
    auth_scheme: str
    flow_id: str
    input_key: str
    request_style: str
    request_timeout: float
    seed_demo: bool
    profile_flow_id: str = ""
    learning_flow_id: str = ""
    remediation_flow_id: str = ""
    goal_flow_id: str = ""
    recommend_flow_id: str = ""
    chat_flow_id: str = ""
    quiz_flow_id: str = ""
    video_search_mode: str = "off"
    video_search_url: str = "https://www.bing.com/search?format=rss&q={query}"
    video_search_timeout: float = 12
    video_search_max_results: int = 4
    video_search_cache_seconds: int = 3600
    # 空值表示跟随 VIDEO_SEARCH_MODE；off 关闭；bing_rss 开启文档检索
    doc_search_mode: str = ""
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    )
    api_token: str = ""

    @classmethod
    def from_env(cls, host: str | None = None, port: int | None = None) -> "Settings":
        resolved_host = host or os.getenv("APP_HOST", "127.0.0.1")
        resolved_port = port or int(os.getenv("APP_PORT", "4173"))
        default_origins = (
            f"http://127.0.0.1:{resolved_port},"
            f"http://localhost:{resolved_port}"
        )
        allowed_origins = tuple(
            origin.strip()
            for origin in os.getenv("APP_ALLOWED_ORIGINS", default_origins).split(",")
            if origin.strip()
        )
        return cls(
            host=resolved_host,
            port=resolved_port,
            database_path=Path(os.getenv("APP_DATABASE", str(DEFAULT_DATABASE))),
            xingchen_mode=os.getenv("XINGCHEN_MODE", "mock").strip().lower(),
            api_url=os.getenv(
                "XINGCHEN_API_URL",
                "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            ).strip(),
            api_key=os.getenv("XINGCHEN_API_KEY", "").strip(),
            api_secret=os.getenv("XINGCHEN_API_SECRET", "").strip(),
            auth_header=os.getenv("XINGCHEN_AUTH_HEADER", "Authorization").strip(),
            auth_scheme=os.getenv("XINGCHEN_AUTH_SCHEME", "Bearer").strip(),
            flow_id=os.getenv("XINGCHEN_FLOW_ID", "").strip(),
            input_key=(
                os.getenv("XINGCHEN_INPUT_KEY", "AGENT_USER_INPUT").strip()
                or "AGENT_USER_INPUT"
            ),
            request_style=os.getenv("XINGCHEN_REQUEST_STYLE", "workflow_v1").strip().lower(),
            request_timeout=float(os.getenv("XINGCHEN_TIMEOUT", "60")),
            seed_demo=os.getenv("APP_SEED_DEMO", "1").strip().lower() not in {"0", "false", "no"},
            profile_flow_id=os.getenv("XINGCHEN_PROFILE_FLOW_ID", "").strip(),
            learning_flow_id=os.getenv("XINGCHEN_LEARNING_FLOW_ID", "").strip(),
            remediation_flow_id=os.getenv("XINGCHEN_REMEDIATION_FLOW_ID", "").strip(),
            goal_flow_id=os.getenv("XINGCHEN_GOAL_FLOW_ID", "").strip(),
            recommend_flow_id=os.getenv("XINGCHEN_RECOMMEND_FLOW_ID", "").strip(),
            chat_flow_id=os.getenv("XINGCHEN_CHAT_FLOW_ID", "").strip(),
            quiz_flow_id=os.getenv("XINGCHEN_QUIZ_FLOW_ID", "").strip(),
            video_search_mode=os.getenv("VIDEO_SEARCH_MODE", "off").strip().lower(),
            video_search_url=os.getenv(
                "VIDEO_SEARCH_URL",
                "https://www.bing.com/search?format=rss&q={query}",
            ).strip(),
            video_search_timeout=float(os.getenv("VIDEO_SEARCH_TIMEOUT", "12")),
            video_search_max_results=max(1, int(os.getenv("VIDEO_SEARCH_MAX_RESULTS", "4"))),
            video_search_cache_seconds=max(0, int(os.getenv("VIDEO_SEARCH_CACHE_SECONDS", "3600"))),
            doc_search_mode=os.getenv("DOC_SEARCH_MODE", "").strip().lower(),
            allowed_origins=allowed_origins,
            api_token=os.getenv("APP_API_TOKEN", "").strip(),
        )


class StateStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS student_state (
                    student_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS upstream_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    student_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    goal_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_student
                    ON projects(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS project_messages (
                    message_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_project_messages_conversation
                    ON project_messages(project_id, student_id, created_at ASC);
                CREATE TABLE IF NOT EXISTS agent_goal_drafts (
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, session_id)
                );
                CREATE TABLE IF NOT EXISTS assessment_runs (
                    assessment_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    assessment_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    stakes TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    blueprint_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assessment_runs_project
                    ON assessment_runs(project_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS assessment_evidence (
                    event_id TEXT PRIMARY KEY,
                    assessment_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    evidence_role TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assessment_evidence_project
                    ON assessment_evidence(project_id, created_at DESC);
                """
            )
            connection.commit()

    def get_student_state(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT state_json FROM student_state WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["state_json"])
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def save_student_state(self, student_id: str, state: dict[str, Any]) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO student_state(student_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (student_id, json_text(state), utc_now()),
            )
            connection.commit()

    # ---------- 项目（agent 形态：每个学习目标一个项目）----------

    def list_projects(self, student_id: str) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT project_id, student_id, goal_id, goal_name, status,
                       state_json, created_at, updated_at
                FROM projects WHERE student_id = ?
                ORDER BY updated_at DESC
                """,
                (student_id,),
            ).fetchall()
        projects = []
        for row in rows:
            project = dict(row)
            try:
                project["state"] = json.loads(project.pop("state_json"))
            except json.JSONDecodeError:
                project["state"] = {}
            projects.append(project)
        return projects

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT project_id, student_id, goal_id, goal_name, status,
                       state_json, created_at, updated_at
                FROM projects WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        if not row:
            return None
        project = dict(row)
        try:
            project["state"] = json.loads(project.pop("state_json"))
        except json.JSONDecodeError:
            project["state"] = {}
        return project

    def create_project(
        self,
        student_id: str,
        goal_id: str,
        goal_name: str,
        status: str,
        state: dict[str, Any],
    ) -> str:
        project_id = f"PROJ-{uuid.uuid4().hex[:12]}"
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, student_id, goal_id, goal_name, status,
                    state_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    student_id,
                    goal_id,
                    goal_name,
                    status,
                    json_text(state),
                    utc_now(),
                    utc_now(),
                ),
            )
            connection.commit()
        return project_id

    def save_project_state(
        self,
        project_id: str,
        state: dict[str, Any],
        status: str | None = None,
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            if status is not None:
                connection.execute(
                    """
                    UPDATE projects SET state_json = ?, status = ?, updated_at = ?
                    WHERE project_id = ?
                    """,
                    (json_text(state), status, utc_now(), project_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE projects SET state_json = ?, updated_at = ?
                    WHERE project_id = ?
                    """,
                    (json_text(state), utc_now(), project_id),
                )
            connection.commit()

    def add_project_message(
        self,
        project_id: str,
        student_id: str,
        role: str,
        content: str,
        action: str = "",
    ) -> str:
        message_id = f"MSG-{uuid.uuid4().hex[:12].upper()}"
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO project_messages(
                    message_id, project_id, student_id, role, content, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    project_id,
                    student_id,
                    role,
                    content[:8000],
                    action[:80],
                    utc_now(),
                ),
            )
            connection.commit()
        return message_id

    def list_project_messages(
        self, project_id: str, student_id: str, limit: int = 80
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT message_id, project_id, student_id, role, content, action, created_at
                FROM (
                    SELECT rowid AS ordinal, message_id, project_id, student_id,
                           role, content, action, created_at
                    FROM project_messages
                    WHERE project_id = ? AND student_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, ordinal ASC
                """,
                (project_id, student_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_agent_goal_draft(self, student_id: str, session_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT draft_json FROM agent_goal_drafts
                WHERE student_id = ? AND session_id = ?
                """,
                (student_id, session_id),
            ).fetchone()
        if not row:
            return {}
        try:
            draft = json.loads(row["draft_json"])
        except json.JSONDecodeError:
            return {}
        return draft if isinstance(draft, dict) else {}

    def save_agent_goal_draft(
        self, student_id: str, session_id: str, draft: dict[str, Any]
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO agent_goal_drafts(student_id, session_id, draft_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(student_id, session_id) DO UPDATE SET
                    draft_json = excluded.draft_json,
                    updated_at = excluded.updated_at
                """,
                (student_id, session_id, json_text(draft), utc_now()),
            )
            connection.commit()

    def delete_agent_goal_draft(self, student_id: str, session_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM agent_goal_drafts WHERE student_id = ? AND session_id = ?",
                (student_id, session_id),
            )
            connection.commit()

    # ---------- 统一测评与证据账本 ----------

    def create_assessment_run(
        self,
        project_id: str,
        student_id: str,
        assessment_type: str,
        title: str,
        stakes: str,
        provider: str,
        blueprint: dict[str, Any],
    ) -> str:
        assessment_id = f"ASSESS-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO assessment_runs(
                    assessment_id, project_id, student_id, assessment_type,
                    title, stakes, status, provider, blueprint_json,
                    result_json, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, '{}', ?, '')
                """,
                (
                    assessment_id,
                    project_id,
                    student_id,
                    assessment_type,
                    title,
                    stakes,
                    provider,
                    json_text(blueprint),
                    now,
                ),
            )
            connection.commit()
        return assessment_id

    def complete_assessment_run(
        self, assessment_id: str, result: dict[str, Any]
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE assessment_runs
                SET status = 'completed', result_json = ?, completed_at = ?
                WHERE assessment_id = ?
                """,
                (json_text(result), utc_now(), assessment_id),
            )
            connection.commit()

    def record_assessment_evidence(
        self,
        assessment_id: str,
        project_id: str,
        student_id: str,
        question_id: str,
        knowledge_point_id: str,
        event_type: str,
        evidence_role: str,
        confidence: float,
        payload: dict[str, Any],
    ) -> str:
        event_id = f"AEV-{uuid.uuid4().hex[:12].upper()}"
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO assessment_evidence(
                    event_id, assessment_id, project_id, student_id,
                    question_id, knowledge_point_id, event_type,
                    evidence_role, confidence, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    assessment_id,
                    project_id,
                    student_id,
                    question_id,
                    knowledge_point_id,
                    event_type,
                    evidence_role,
                    max(0.0, min(float(confidence), 1.0)),
                    json_text(payload),
                    utc_now(),
                ),
            )
            connection.commit()
        return event_id

    @staticmethod
    def _decode_json_object(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def list_assessment_runs(
        self, project_id: str, student_id: str
    ) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM assessment_runs
                WHERE project_id = ? AND student_id = ?
                ORDER BY started_at DESC
                """,
                (project_id, student_id),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["blueprint"] = self._decode_json_object(item.pop("blueprint_json"))
            item["result"] = self._decode_json_object(item.pop("result_json"))
            result.append(item)
        return result

    def list_assessment_evidence(
        self,
        project_id: str,
        student_id: str,
        assessment_id: str = "",
    ) -> list[dict[str, Any]]:
        query = """
            SELECT * FROM assessment_evidence
            WHERE project_id = ? AND student_id = ?
        """
        params: list[Any] = [project_id, student_id]
        if assessment_id:
            query += " AND assessment_id = ?"
            params.append(assessment_id)
        query += " ORDER BY created_at ASC"
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = self._decode_json_object(item.pop("payload_json"))
            result.append(item)
        return result

    def record_upstream(self, payload: dict[str, Any]) -> tuple[str, bool]:
        event_id = str(payload.get("event_id") or uuid.uuid4())
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO upstream_events(
                    event_id, student_id, session_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    str(payload.get("student_id", "")),
                    str(payload.get("session_id", "")),
                    json_text(payload),
                    utc_now(),
                ),
            )
            connection.commit()
        return event_id, cursor.rowcount > 0

    def record_run(
        self,
        student_id: str,
        workflow: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs(
                    run_id, student_id, workflow, request_json, response_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    student_id,
                    workflow,
                    json_text(request_payload),
                    json_text(response_payload),
                    str(response_payload.get("status", "unknown")),
                    utc_now(),
                ),
            )
            connection.commit()
        return run_id


class KnowledgeCache:
    """Thread-safe in-memory cache for knowledge retrieval results."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._items: dict[str, tuple[float, str]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires_at, text = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            return text

    def set(self, key: str, kb_text: str) -> None:
        text = str(kb_text).strip()
        if not key or not text:
            return
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl_seconds, text)


class StrategyEngine:
    """Deterministic strategy decisions shared by mock and remote workflows."""

    LEARNING_CANDIDATES = {
        "code": [
            "execution_trace",
            "worked_example",
            "step_by_step",
            "analogy",
            "comparison",
        ],
        "conceptual": [
            "worked_example",
            "analogy",
            "comparison",
            "execution_trace",
            "step_by_step",
        ],
    }

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def decide_learning_strategy(
        cls,
        learner_action: str,
        knowledge_type: str,
        mastery: float,
        ineffective_modes: list[Any],
        student_model: dict[str, Any],
    ) -> dict[str, Any]:
        kind = "code" if str(knowledge_type).lower() == "code" else "conceptual"
        candidates = list(cls.LEARNING_CANDIDATES[kind])
        blocked = {str(mode) for mode in ineffective_modes if str(mode)}
        usable = [mode for mode in candidates if mode not in blocked] or candidates
        effective = as_dict(student_model.get("effective_modes"))
        candidate_order = {mode: index for index, mode in enumerate(candidates)}
        usable.sort(
            key=lambda mode: (
                -cls._number(effective.get(mode), 0.0),
                candidate_order.get(mode, len(candidates)),
            )
        )

        action = str(learner_action or "first")
        if action == "alternative":
            preferred = usable[1] if len(usable) > 1 else usable[0]
        elif action == "example":
            preferred = "worked_example" if "worked_example" in usable else usable[0]
        elif action == "steps":
            preferred = next(
                (mode for mode in usable if mode in {"step_by_step", "execution_trace"}),
                usable[0],
            )
        else:
            preferred = usable[0]

        pace = max(0.5, min(cls._number(student_model.get("pace_factor"), 1.0), 1.5))
        mastery_value = max(0.0, min(cls._number(mastery), 100.0))
        if mastery_value < 35 * pace:
            depth = "foundational"
        elif mastery_value < 75 * pace:
            depth = "guided"
        else:
            depth = "concise"
        strategy_map = {
            "first": "concept_to_example",
            "continue": "resume_scaffold",
            "alternative": "alternative_representation",
            "example": "worked_example",
            "steps": "step_by_step",
            "check_answer": "concept_check_feedback",
        }
        return {
            "strategy_code": strategy_map.get(action, "concept_to_example"),
            "preferred_representation": preferred,
            "explanation_depth": depth,
            "avoid_repeating_strategies": sorted(blocked),
            "student_pace_hint": pace,
            "misconception_tags": [
                str(item)
                for item in as_list(student_model.get("misconception_tags"))
                if str(item)
            ],
        }

    @classmethod
    def decide_remediation_strategy(
        cls,
        evaluation_status: str,
        error_type: str,
        mastery: float,
        repeat_count: int,
        wrong_streak: int,
        correct_streak: int,
        prerequisite_gap: list[Any],
        student_model: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = as_dict(student_model.get("strategy_defaults"))
        threshold = max(1, int(cls._number(defaults.get("same_error_threshold"), 2)))
        ineffective = [
            str(item)
            for item in as_list(student_model.get("ineffective_modes"))
            if str(item)
        ]
        mastery_value = max(0.0, min(cls._number(mastery), 100.0))
        pace = max(0.5, min(cls._number(student_model.get("pace_factor"), 1.0), 1.5))

        if prerequisite_gap:
            code, representation, depth = "prerequisite_repair", "step_by_step", "foundational"
        elif correct_streak >= 2 and mastery_value >= 80:
            code, representation, depth = "advance_challenge", "comparison", "concise"
        elif repeat_count >= threshold:
            code = "alternative_representation"
            effective = as_dict(student_model.get("effective_modes"))
            candidates = [
                mode
                for mode in ("execution_trace", "comparison", "step_by_step", "worked_example")
                if mode not in ineffective
            ] or ["execution_trace"]
            representation = max(
                candidates,
                key=lambda mode: cls._number(effective.get(mode), 0.0),
            )
            depth = "foundational" if mastery_value < 40 or wrong_streak >= 2 else "guided"
        elif str(error_type) in {
            "procedure_error",
            "operation_error",
            "code_logic_error",
            "calculation",
        }:
            code, representation = "trace_and_debug", "execution_trace"
            depth = "foundational" if mastery_value < 40 or wrong_streak >= 2 else "guided"
        elif mastery_value >= 70 or str(evaluation_status).lower() == "correct":
            code, representation, depth = "consolidate_transfer", "comparison", "concise"
        else:
            code, representation = "targeted_explanation", "worked_example"
            depth = "foundational" if mastery_value < 35 * pace else "guided"

        return {
            "strategy_code": code,
            "preferred_representation": representation,
            "explanation_depth": depth,
            "avoid_repeating_strategies": ineffective,
            "student_pace_hint": pace,
            "misconception_tags": [
                str(item)
                for item in as_list(student_model.get("misconception_tags"))
                if str(item)
            ],
            "prerequisite_gap": [
                item for item in prerequisite_gap if isinstance(item, (str, dict))
            ],
        }


class VideoSearchGateway:
    VIDEO_DOMAIN_NAMES = {
        "bilibili.com": "哔哩哔哩",
        "icourse163.org": "中国大学 MOOC",
        "xuetangx.com": "学堂在线",
        "smartedu.cn": "国家智慧教育公共服务平台",
        "mooc1.cn": "超星学习通",
        "youtube.com": "YouTube",
        "youtu.be": "YouTube",
    }
    # 联网文档白名单（与方案 B 知识依据白名单一致）：只允许官方/权威域名进入文档板块
    DOC_DOMAIN_SUFFIXES = (
        "docs.python.org",
        "python.org",
        "learn.microsoft.com",
        "developer.mozilla.org",
        "w3.org",
        "ietf.org",
        "rfc-editor.org",
        "openstd.samr.gov.cn",
        "gov.cn",
        "moe.gov.cn",
        "mohrss.gov.cn",
        "xfyun.cn",
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def enabled(self) -> bool:
        return self.settings.video_search_mode == "bilibili" or (
            self.settings.video_search_mode == "bing_rss"
            and bool(self.settings.video_search_url)
        )

    @property
    def doc_enabled(self) -> bool:
        mode = self.settings.doc_search_mode
        # 空值跟随视频检索开关；off 显式关闭；bing_rss 显式开启
        return (
            mode == "bing_rss" or (not mode and self.settings.video_search_mode == "bing_rss")
        ) and bool(self.settings.video_search_url)

    def should_search(self, workflow: str, payload: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if workflow == "review":
            return not bool(payload.get("resume_token"))
        event_type = str(payload.get("event_type", "initialize_learning"))
        return event_type in {
            "initialize_learning",
            "continue_learning",
            "switch_explanation",
            "request_video",
            "request_text",
            "show_example",
            "show_steps",
            "not_understood",
            "check_feedback",
        }

    def search(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = self._build_query(workflow, payload)
        if not query:
            return {
                "status": "skipped",
                "provider": "bing_rss",
                "query": "",
                "searched_at": utc_now(),
                "results": [],
            }
        now = time.monotonic()
        cache_key = f"{self.settings.video_search_mode}:{query}"
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] >= now:
                return dict(cached[1])
        if self.settings.video_search_mode == "bilibili":
            result = self._search_bilibili(query)
        else:
            result = self._search_bing_rss(query, kind="video")
        with self._lock:
            self._cache[cache_key] = (
                now + self.settings.video_search_cache_seconds,
                result,
            )
        return dict(result)

    def _search_bilibili(self, query: str, limit: int = 4) -> dict[str, Any]:
        """B 站站内视频搜索：解析 search.bilibili.com 结果页，提取真实 BV 号与标题。

        B 站官方搜索 API 匿名请求被风控（412/空 result），但网页搜索页可匿名访问；
        解析结果均为真实可核验的视频链接（verification_state=whitelisted 由调用方标注）。
        """
        url = "https://search.bilibili.com/all?keyword=" + quote_plus(query)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.bilibili.com/",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.video_search_timeout,
            ) as response:
                body = response.read(4 * 1024 * 1024)
            text = body.decode("utf-8", "ignore")
        except urllib.error.URLError as error:
            return {
                "status": "search_failed",
                "provider": "bilibili",
                "query": query,
                "searched_at": utc_now(),
                "results": [],
                "error": f"搜索页请求失败：{error.reason if error.reason else error}",
            }
        except (OSError, http.client.HTTPException) as error:
            # 超时（socket.timeout 属 OSError）与连接中断（IncompleteRead）也要归入 search_failed，
            # 否则会冒泡成 500
            return {
                "status": "search_failed",
                "provider": "bilibili",
                "query": query,
                "searched_at": utc_now(),
                "results": [],
                "error": f"搜索页请求失败：{error}",
            }
        results: list[dict[str, Any]] = []
        by_bv: dict[str, str] = {}
        for match in re.finditer(
            r'href="//www\.bilibili\.com/video/(BV[a-zA-Z0-9]+)/?"[^>]*>(.*?)</a>',
            text,
            re.S,
        ):
            bv, title_html = match.group(1), match.group(2)
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            if not title or len(title) > 120:
                continue
            # 封面卡片的文本是“播放量+时长”（如 7202105:49 或 10.6万83302:51:32），
            # 不是视频标题，跳过纯数字/时长元数据
            if re.fullmatch(r"[\d.\s万:]+", title):
                continue
            # 检索词命中其他语言/非教学主题时过滤，避免把 C#、Python、游戏等内容
            # 当作 Java 学习资源（演示内容准确性红线）
            if not self._bilibili_title_relevant(title):
                continue
            if bv not in by_bv:
                by_bv[bv] = title
        for bv, title in list(by_bv.items())[:limit]:
            results.append(
                {
                    "type": "video",
                    "title": title,
                    "url": f"https://www.bilibili.com/video/{bv}",
                    "embed_url": (
                        f"https://player.bilibili.com/player.html?bvid={bv}"
                        "&page=1&high_quality=1&danmaku=0"
                    ),
                    "source": "哔哩哔哩",
                    "source_domain": "bilibili.com",
                    "snippet": "B 站教学视频（联网检索）",
                    # 仅从搜索页正则提取，未经内容核验；不得标为 whitelisted 以免误导前端展示
                    "verification_state": "web_sourced",
                }
            )
        return {
            "status": "ok" if results else "no_results",
            "provider": "bilibili",
            "query": query,
            "searched_at": utc_now(),
            "results": results,
        }

    def _bilibili_title_relevant(self, title: str) -> bool:
        """B 站检索结果标题相关性过滤：排除明确属于其他语言或非 Java 教学主题的视频。"""
        lowered = title.lower()
        non_java_markers = (
            "c#", "c sharp", "python", "javascript", "typescript", "golang", "go语言",
            "rust", "c++", "c语言", "php", "swift", "kotlin", "ruby", "matlab",
            "段位", "战力", "裂项", "二项式", "数列", "导数", "概率", "物理", "化学",
            "生物", "历史", "地理", "王者荣耀", "英雄联盟", "原神", "永劫", "我的世界",
        )
        return not any(marker in lowered for marker in non_java_markers)

    def search_documents(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = self._build_doc_query(workflow, payload)
        if not query:
            return {
                "status": "skipped",
                "provider": "bing_rss",
                "query": "",
                "searched_at": utc_now(),
                "results": [],
            }
        cache_key = "doc:" + query
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] >= now:
                return dict(cached[1])
        result = self._search_bing_rss(query, kind="document")
        with self._lock:
            self._cache[cache_key] = (
                now + self.settings.video_search_cache_seconds,
                result,
            )
        return dict(result)

    def search_general_documents(self, query: str) -> dict[str, Any]:
        """Search the public web without treating arbitrary domains as verified authorities."""
        normalized_query = re.sub(r"\s+", " ", str(query or "")).strip()
        if not normalized_query:
            return {
                "status": "skipped",
                "provider": "bing_rss",
                "query": "",
                "searched_at": utc_now(),
                "results": [],
            }
        cache_key = "general-doc:" + normalized_query
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] >= now:
                return dict(cached[1])
        result = self._search_bing_rss(normalized_query, kind="general_document")
        with self._lock:
            self._cache[cache_key] = (
                now + self.settings.video_search_cache_seconds,
                result,
            )
        return dict(result)

    def _build_query(self, workflow: str, payload: dict[str, Any]) -> str:
        target = as_dict(payload.get("current_knowledge_point"))
        if workflow == "review":
            error_points = as_list(as_dict(payload.get("validated_evaluation")).get("error_points"))
            if error_points and isinstance(error_points[0], dict):
                target = error_points[0]
        if not target:
            weak_points = as_list(as_dict(payload.get("diagnostic_result")).get("weak_points"))
            if weak_points and isinstance(weak_points[0], dict):
                target = weak_points[0]
        knowledge_name = str(
            target.get("knowledge_point_name", target.get("knowledge_point_id", ""))
        ).strip()
        goal_name = str(as_dict(payload.get("learning_goal")).get("goal_name", "")).strip()
        question_text = str(as_dict(payload.get("question_snapshot")).get("question_text", "")).strip()
        focus = " ".join(value for value in (knowledge_name, goal_name, question_text[:80]) if value)
        if not focus:
            return ""
        domain_query = " OR ".join(f"site:{domain}" for domain in self.VIDEO_DOMAIN_NAMES)
        if self.settings.video_search_mode == "bilibili":
            # B 站站内搜索对长 query 返回为空，只用知识点名（goal/题干会拉长 query）
            # 追加 Java 限定，避免“继承/多态”等词命中的游戏、其他语言视频进入资源列表
            return f"{knowledge_name} Java 教学"
        return f"{focus} 教学 视频 ({domain_query})"

    def _build_doc_query(self, workflow: str, payload: dict[str, Any]) -> str:
        target = as_dict(payload.get("current_knowledge_point"))
        if workflow == "review":
            error_points = as_list(as_dict(payload.get("validated_evaluation")).get("error_points"))
            if error_points and isinstance(error_points[0], dict):
                target = error_points[0]
        if not target:
            weak_points = as_list(as_dict(payload.get("diagnostic_result")).get("weak_points"))
            if weak_points and isinstance(weak_points[0], dict):
                target = weak_points[0]
        knowledge_name = str(
            target.get("knowledge_point_name", target.get("knowledge_point_id", ""))
        ).strip()
        goal_name = str(as_dict(payload.get("learning_goal")).get("goal_name", "")).strip()
        question_text = str(as_dict(payload.get("question_snapshot")).get("question_text", "")).strip()
        focus = " ".join(value for value in (knowledge_name, goal_name, question_text[:80]) if value)
        if not focus:
            return ""
        domain_query = " OR ".join(f"site:{suffix}" for suffix in self.DOC_DOMAIN_SUFFIXES)
        return f"{focus} 官方文档 标准 ({domain_query})"

    def _search_bing_rss(self, query: str, kind: str = "video") -> dict[str, Any]:
        endpoint = self.settings.video_search_url.format(query=quote_plus(query))
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "Mozilla/5.0 PersonalizedLearningResourceBot/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.video_search_timeout,
            ) as response:
                body = response.read(2 * 1024 * 1024)
            root = ElementTree.fromstring(body)
        except (urllib.error.URLError, ElementTree.ParseError, ValueError) as error:
            return {
                "status": "search_failed",
                "provider": "bing_rss",
                "query": query,
                "searched_at": utc_now(),
                "results": [],
                "error": str(error)[:300],
            }

        domain_map = self.VIDEO_DOMAIN_NAMES if kind == "video" else self._doc_domain_map()
        results: list[dict[str, Any]] = []
        for item in root.findall(".//item"):
            title = self._plain_text(item.findtext("title"))
            url = str(item.findtext("link") or "").strip()
            description = self._plain_text(item.findtext("description"))
            host = (urlparse(url).hostname or "").lower()
            domain = (
                host
                if kind == "general_document" and self._is_public_web_result(url, host)
                else self._allowed_domain(host, domain_map)
            )
            if not title or not url or not domain:
                continue
            source = domain_map.get(domain, host)
            if kind == "video":
                resource = {
                    "type": "video",
                    "title": title,
                    "url": url,
                    "source": source,
                    "source_domain": host,
                    "snippet": description,
                    "content": description,
                    "provider": "Bing RSS",
                    "verification_state": (
                        "web_sourced" if kind == "general_document" else "whitelisted"
                    ),
                }
                embed_url = self._embed_url(url)
                if embed_url:
                    resource["embed_url"] = embed_url
            else:
                resource = {
                    "type": "document",
                    "title": title,
                    "url": url,
                    "source": source,
                    "source_domain": host,
                    "snippet": description,
                    "content": description,
                    "provider": "Bing RSS",
                    "verification_state": (
                        "web_sourced" if kind == "general_document" else "whitelisted"
                    ),
                }
            results.append(resource)
            if len(results) >= self.settings.video_search_max_results:
                break
        return {
            "status": "ok" if results else "no_results",
            "provider": "bing_rss",
            "query": query,
            "searched_at": utc_now(),
            "results": results,
        }

    @staticmethod
    def _is_public_web_result(url: str, host: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not host or host == "localhost":
            return False
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        )

    def _doc_domain_map(self) -> dict[str, str]:
        return {suffix: suffix for suffix in self.DOC_DOMAIN_SUFFIXES}

    def _allowed_domain(self, host: str, domain_map: dict[str, str] | None = None) -> str:
        domain_map = domain_map if domain_map is not None else self.VIDEO_DOMAIN_NAMES
        for domain in domain_map:
            if host == domain or host.endswith("." + domain):
                return domain
        return ""

    def _plain_text(self, value: Any) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
        return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()

    def _embed_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "bilibili.com" or host.endswith(".bilibili.com"):
            match = re.search(r"/video/(BV[A-Za-z0-9]+|av\d+)", parsed.path, flags=re.I)
            if match:
                identifier = match.group(1)
                key = "bvid" if identifier.lower().startswith("bv") else "aid"
                value = identifier if key == "bvid" else identifier[2:]
                return f"https://player.bilibili.com/player.html?{key}={value}&high_quality=1"
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
            return f"https://www.youtube-nocookie.com/embed/{video_id}" if video_id else ""
        if host == "youtube.com" or host.endswith(".youtube.com"):
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if not video_id and parsed.path.startswith("/shorts/"):
                video_id = parsed.path.split("/")[2]
            return f"https://www.youtube-nocookie.com/embed/{video_id}" if video_id else ""
        return ""




class XingchenGateway:
    STOP_REPLIES = {
        "不知道",
        "不清楚",
        "没有",
        "没法提供",
        "无法提供",
        "不能提供",
        "结束",
        "停止",
        "取消",
        "算了",
        "退出",
    }

    def __init__(self, settings: Settings, token_store: LearningDomainStore | None = None):
        self.settings = settings
        self.token_store = token_store
        self._resume_contexts: dict[
            str, tuple[float, str, str, dict[str, Any]]
        ] = {}
        self._resume_lock = threading.RLock()

    @property
    def mode(self) -> str:
        return self.settings.xingchen_mode

    def invoke(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        if workflow == "profile":
            return self.invoke_profile_workflow(payload)
        if workflow == "learning":
            return self.invoke_learning_workflow(payload)
        if workflow in {"review", "remediation"}:
            return self.invoke_remediation_workflow(payload)
        raise GatewayError(f"未知工作流类型：{workflow}")

    def invoke_profile_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_profile(payload)
        self._require_remote_mode()
        return self._invoke_remote(
            "profile", payload, self.settings.profile_flow_id or self.settings.flow_id
        )

    def invoke_learning_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_learning(payload)
        self._require_remote_mode()
        return self._invoke_remote(
            "learning", payload, self.settings.learning_flow_id or self.settings.flow_id
        )

    def invoke_remediation_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_review(payload)
        self._require_remote_mode()
        return self._invoke_remote(
            "remediation", payload, self.settings.remediation_flow_id or self.settings.flow_id
        )

    def invoke_goal_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return {"status": "ok", "workflow_mode": "goal_planning", **payload}
        self._require_remote_mode()
        return self._invoke_remote(
            "goal_planning", payload, self.settings.goal_flow_id or self.settings.flow_id
        )

    def invoke_recommend_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return {"status": "ok", "workflow_mode": "recommend", "recommendations": []}
        self._require_remote_mode()
        return self._invoke_remote(
            "recommend", payload, self.settings.recommend_flow_id or self.settings.flow_id
        )

    def invoke_chat_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return {"status": "ok", "workflow_mode": "chat"}
        self._require_remote_mode()
        return self._invoke_remote(
            "chat", payload, self.settings.chat_flow_id or self.settings.flow_id
        )

    def invoke_quiz_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_quiz(payload)
        self._require_remote_mode()
        return self._invoke_remote(
            "quiz", payload, self.settings.quiz_flow_id or self.settings.flow_id
        )

    def _require_remote_mode(self) -> None:
        if self.mode != "remote":
            raise GatewayError("XINGCHEN_MODE 只能是 mock 或 remote")

    def remote_ready(self) -> bool:
        if self.mode == "mock":
            return True
        credentials = bool(self.settings.api_key and self.settings.api_secret)
        if not credentials or not self.settings.api_url:
            return False
        if self.settings.request_style == "direct":
            return True
        split_flows = bool(
            self.settings.profile_flow_id
            and self.settings.learning_flow_id
            and self.settings.remediation_flow_id
        )
        return bool(self.settings.flow_id or split_flows)

    def _invoke_remote(
        self, workflow: str, payload: dict[str, Any], flow_id: str
    ) -> dict[str, Any]:
        endpoint = self.settings.api_url
        if not endpoint:
            raise GatewayError("未配置星辰调用地址")
        if not self.settings.api_key:
            raise GatewayError("未配置 XINGCHEN_API_KEY")
        if not self.settings.api_secret:
            raise GatewayError("未配置 XINGCHEN_API_SECRET")

        if self.settings.request_style == "direct":
            request_body = payload
        else:
            if not flow_id:
                variable_name = {
                    "profile": "XINGCHEN_PROFILE_FLOW_ID",
                    "learning": "XINGCHEN_LEARNING_FLOW_ID",
                    "remediation": "XINGCHEN_REMEDIATION_FLOW_ID",
                }.get(workflow, "XINGCHEN_FLOW_ID")
                raise GatewayError(f"未配置工作流 ID：{variable_name}")
            request_body = {
                "flow_id": flow_id,
                "uid": str(payload.get("student_id", "anonymous")),
                "parameters": {
                    self.settings.input_key: json_text(payload),
                },
                "stream": False,
            }

        authorization = f"{self.settings.api_key}:{self.settings.api_secret}"
        if self.settings.auth_scheme:
            authorization = f"{self.settings.auth_scheme} {authorization}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json, text/event-stream",
                self.settings.auth_header: authorization,
            },
            method="POST",
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.request_timeout) as response:
                    response_text = response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:1000]
                raise GatewayError(f"星辰接口返回 HTTP {error.code}: {detail}") from error
            except urllib.error.URLError as error:
                raise GatewayError(f"无法连接星辰接口: {error.reason}") from error

            remote_payload = self._parse_remote_response(response_text)
            response_code = remote_payload.get("code")
            if response_code is not None and int(response_code) != 0:
                raise GatewayError(
                    f"星辰工作流执行失败（{response_code}）：{remote_payload.get('message', '未知错误')}"
                )
            result = self._extract_result(remote_payload)
            if result:
                return result

        raise GatewayError("星辰响应未返回可识别的结果包，已自动重试一次")

    def _parse_remote_response(self, response_text: str) -> dict[str, Any]:
        parsed = parse_json_object(response_text)
        if parsed:
            return parsed
        events: list[dict[str, Any]] = []
        for line in response_text.splitlines():
            if not line.startswith("data:"):
                continue
            event_text = line[5:].strip()
            if not event_text or event_text == "[DONE]":
                continue
            event = parse_json_object(event_text)
            if event:
                events.append(event)
        if not events:
            raise GatewayError("星辰接口返回了无法解析的内容")
        return events[-1]

    def _extract_result(self, payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            for key in ("final_result_json", "result_json"):
                if key in payload:
                    for parsed in reversed(parse_json_objects(payload[key])):
                        result = self._extract_result(parsed)
                        if result:
                            return result
            # The unified v5 Flow keeps the primary result slot empty and
            # routes knowledge_unavailable / fallback outcomes into
            # fallback_result_json. Without this, those responses degrade
            # into a misleading gateway 502.
            if payload.get("fallback_result_json"):
                for parsed in reversed(parse_json_objects(payload["fallback_result_json"])):
                    result = self._extract_result(parsed)
                    if result:
                        return result
            if (
                "student_model" in payload
                and "strategy_defaults" in payload
            ):
                return payload
            if "status" in payload and any(
                key in payload
                for key in (
                    "content_blocks",
                    "personalized_explanation",
                    "resume_token",
                    "student_model",
                    "user_message",
                    "knowledge_gap",
                    "workflow_mode",
                    "learning_path",
                    "learning_goal",
                    "recommendations",
                    "questions",
                    "message",
                    "answer",
                )
            ):
                return payload
            for key in ("data", "result", "output", "choices", "delta", "message", "content"):
                if key in payload:
                    result = self._extract_result(payload[key])
                    if result:
                        return result
        elif isinstance(payload, list):
            for item in reversed(payload):
                result = self._extract_result(item)
                if result:
                    return result
        else:
            # Some Flow responses prepend progress text or contain an
            # intermediate JSON object before the final result package.
            for parsed in reversed(parse_json_objects(payload)):
                result = self._extract_result(parsed)
                if result:
                    return result
        return None

    def _encode_resume_token(
        self, context: dict[str, Any], student_id: str, session_id: str
    ) -> str:
        if self.token_store:
            return self.token_store.create_resume_token(context, student_id, session_id)
        token = "resume." + uuid.uuid4().hex + uuid.uuid4().hex
        with self._resume_lock:
            self._resume_contexts[token] = (
                time.monotonic() + 900,
                student_id,
                session_id,
                dict(context),
            )
        return token

    def _decode_resume_token(
        self, token: str, student_id: str, session_id: str
    ) -> dict[str, Any]:
        if self.token_store:
            return self.token_store.consume_resume_token(token, student_id, session_id)
        with self._resume_lock:
            stored = self._resume_contexts.get(token)
            if not stored:
                return {}
            if stored[0] <= time.monotonic():
                self._resume_contexts.pop(token, None)
                return {}
            if stored[1] != student_id or stored[2] != session_id:
                return {}
            self._resume_contexts.pop(token, None)
        return dict(stored[3])

    def _mock_quiz(self, payload: dict[str, Any]) -> dict[str, Any]:
        """mock 出题：从本地题库按目标取样，薄弱点知识点优先。

        remote 模式下该职责由星辰"测评出题工作流"承担（大模型按薄弱点
        动态生成）；mock 用本地题库模拟"生成 → 校验 → 入库"链路的入口，
        保证演示路径与 remote 一致（校验/入库在本地 LearningApplication）。
        """
        goal = str(payload.get("goal") or "daily").strip()
        weak_points = [
            item for item in as_list(payload.get("weak_points")) if isinstance(item, dict)
        ]
        weak_ids = {
            str(item.get("knowledge_point_id"))
            for item in weak_points
            if str(item.get("knowledge_point_id", "")).strip()
        }
        picked = select_diagnosis_questions(goal)
        # 薄弱点知识点优先，其余保持原顺序（取样集合不变，仅调整顺序）
        picked.sort(key=lambda item: 0 if item["knowledge_point_id"] in weak_ids else 1)
        questions = [
            {
                "question_id": item["id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "title": item["title"],
                "options": item["options"],
                "answer": item["answer"],
                "explanation": item["explanation"],
                "difficulty": item["difficulty"],
                "source": "本地题库（mock 出题，平台工作流接入后由大模型生成）",
            }
            for item in picked
        ]
        return {
            "status": "ok",
            "workflow_mode": "quiz",
            "provider": "mock_bank",
            "goal": goal,
            "questions": questions,
        }

    def _mock_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        history = as_dict(payload.get("teaching_history"))
        events = [
            event
            for event in as_list(history.get("events"))
            if isinstance(event, dict)
        ]
        mode_stats: dict[str, dict[str, int]] = {}
        misconception_counts: dict[str, int] = {}
        for event in events:
            mode = str(
                event.get("teaching_mode") or event.get("explanation_mode") or ""
            ).strip()
            effect = str(event.get("effect", "")).strip()
            if mode:
                stats = mode_stats.setdefault(mode, {"passed": 0, "not_understood": 0, "total": 0})
                stats["total"] += 1
                if effect == "passed":
                    stats["passed"] += 1
                elif effect in {"not_understood", "ineffective"}:
                    stats["not_understood"] += 1
            tag = str(event.get("misconception_tag", "")).strip()
            if tag:
                misconception_counts[tag] = misconception_counts.get(tag, 0) + 1

        effective_modes: dict[str, float] = {}
        ineffective_modes: list[str] = []
        for mode, stats in mode_stats.items():
            if stats["total"] < 2:
                continue
            pass_rate = stats["passed"] / stats["total"]
            ineffective_rate = stats["not_understood"] / stats["total"]
            effective_modes[mode] = round(pass_rate, 2)
            if ineffective_rate >= 0.6:
                ineffective_modes.append(mode)
        strongest_mode = max(effective_modes, key=effective_modes.get) if effective_modes else ""
        learning_style = {
            "execution_trace": "procedural_learner",
            "worked_example": "example_driven",
            "video_interactive": "visual_preferred",
        }.get(strongest_mode, "balanced")
        profile = {
            "learning_style": learning_style,
            "learning_style_confidence": 0.7 if effective_modes else 0.4,
            "effective_modes": effective_modes,
            "ineffective_modes": ineffective_modes,
            "misconception_tags": [
                tag for tag, count in misconception_counts.items() if count >= 2
            ],
            "pace_factor": 1.0,
            "strengths": [],
            "weaknesses": [],
            "attention_pattern": "sustained",
            "scaffold_preference": "moderate",
        }
        defaults = {
            "learning_preferred_mode": strongest_mode or "interactive_document",
            "learning_fallback_mode": "worked_example",
            "remediation_preferred_mode": "trace_and_debug",
            "same_error_threshold": 2,
            "prerequisite_check_before_new_topic": False,
            "understanding_check_difficulty": "same",
        }
        path_items = [
            item
            for item in as_list(
                as_dict(as_dict(payload.get("knowledge_state")).get("learning_path")).get("items")
            )
            if isinstance(item, dict)
        ]
        mastery_values = [int(item.get("mastery", 0) or 0) for item in path_items]
        average_mastery = (
            round(sum(mastery_values) / len(mastery_values)) if mastery_values else 0
        )
        code_items = [
            item for item in path_items if str(item.get("knowledge_type", "")) == "code"
        ]
        concept_items = [
            item for item in path_items if str(item.get("knowledge_type", "")) != "code"
        ]
        code_average = (
            round(sum(int(item.get("mastery", 0) or 0) for item in code_items) / len(code_items))
            if code_items
            else average_mastery
        )
        concept_average = (
            round(
                sum(int(item.get("mastery", 0) or 0) for item in concept_items) / len(concept_items)
            )
            if concept_items
            else average_mastery
        )
        ability_scores = {
            "理解能力": round(0.5 * concept_average + 0.25 * code_average + 15),
            "应用能力": round(0.5 * code_average + 0.3 * concept_average + 8),
            "推理能力": round(0.45 * code_average + 0.25 * concept_average + 12),
            "表达能力": round(0.35 * concept_average + 0.2 * code_average + 18),
            "复盘能力": round(0.4 * concept_average + 0.25 * code_average + 16),
            "迁移能力": round(0.35 * (code_average + concept_average) / 2 + 12),
        }
        score_confidence = 0.7 if effective_modes else 0.4
        ability_scores = {
            name: {
                "score": max(0, min(100, score)),
                "confidence": score_confidence,
            }
            for name, score in ability_scores.items()
        }
        style_distributions = {
            "balanced": {"visual": 0.25, "auditory": 0.25, "kinesthetic": 0.25, "reading": 0.25},
            "visual_preferred": {"visual": 0.45, "auditory": 0.15, "kinesthetic": 0.2, "reading": 0.2},
            "procedural_learner": {"visual": 0.2, "auditory": 0.15, "kinesthetic": 0.45, "reading": 0.2},
            "example_driven": {"visual": 0.3, "auditory": 0.15, "kinesthetic": 0.2, "reading": 0.35},
        }
        return {
            "status": "ok",
            "student_model": profile,
            "ability_scores": ability_scores,
            "learning_style_distribution": style_distributions.get(
                learning_style, style_distributions["balanced"]
            ),
            "strategy_defaults": defaults,
            "generated_at": utc_now(),
            "based_on_event_count": int(payload.get("event_count", 0) or 0),
        }

    def _mock_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = payload
        payload = as_dict(request_payload.get("context")) or request_payload
        strategy = as_dict(request_payload.get("strategy"))
        student_profile = as_dict(request_payload.get("student_profile"))
        if payload.get("resume_token"):
            reply = str(payload.get("clarification_reply", "")).strip()
            normalized_reply = reply.replace("。", "").replace("！", "").replace("!", "")
            student_id = str(payload.get("student_id", "")).strip()
            session_id = str(payload.get("session_id", "")).strip()
            context = self._decode_resume_token(
                str(payload.get("resume_token")), student_id, session_id
            )
            if not context:
                return {
                    "status": "fatal_internal",
                    "workflow_mode": "review",
                    "error_code": "INVALID_RESUME_TOKEN",
                    "user_message": "恢复令牌已经失效，请重新提交测验结果。",
                }
            if any(stop_reply in normalized_reply for stop_reply in self.STOP_REPLIES):
                return {
                    "status": "ended_by_user",
                    "workflow_mode": "review",
                    "user_message": "你暂时无法提供缺失信息，本次题目讲解已经结束。",
                }
            missing_field = str(context.pop("_missing_field", ""))
            if missing_field == "question_snapshot.question_text":
                context.setdefault("question_snapshot", {})["question_text"] = reply
            elif missing_field == "current_attempt.student_answer":
                context.setdefault("current_attempt", {})["student_answer"] = reply
            payload = context

        question = as_dict(payload.get("question_snapshot"))
        attempt = as_dict(payload.get("current_attempt"))
        missing_field = ""
        clarification_question = ""
        if not str(question.get("question_text", "")).strip():
            missing_field = "question_snapshot.question_text"
            clarification_question = "请补充本次题目或实训任务的完整描述。若确实无法提供，可以结束本次讲解。"
        elif not str(attempt.get("student_answer", "")).strip():
            missing_field = "current_attempt.student_answer"
            clarification_question = "请补充你当时提交的答案、代码、操作步骤或故障现象。若确实无法提供，可以结束本次讲解。"
        if missing_field:
            pending_context = dict(payload)
            pending_context["_missing_field"] = missing_field
            return {
                "status": "needs_clarification",
                "workflow_mode": "review",
                "missing_fields": [missing_field],
                "clarification_question": clarification_question,
                "user_message": clarification_question,
                "resume_token": self._encode_resume_token(
                    pending_context,
                    str(payload.get("student_id", "")).strip(),
                    str(payload.get("session_id", "")).strip(),
                ),
            }

        evaluation = as_dict(payload.get("validated_evaluation"))
        error_points = [item for item in as_list(evaluation.get("error_points")) if isinstance(item, dict)]
        target = error_points[0] if error_points else {
            "error_id": "UNKNOWN_ERROR",
            "knowledge_point_id": "KN_UNKNOWN",
            "knowledge_point_name": "待确认知识点",
            "student_evidence": str(attempt.get("student_answer", "")),
            "expected_behavior": "按照任务要求完成操作",
            "diagnosis": "当前答案与预期要求不一致",
            "root_cause": "关键步骤或概念尚未掌握",
        }
        knowledge_name = str(target.get("knowledge_point_name", "当前知识点"))
        evidence = str(target.get("student_evidence", "当前作答中存在错误"))
        expected = str(target.get("expected_behavior", "按照正确步骤完成"))
        root_cause = str(target.get("root_cause", target.get("diagnosis", "概念理解不完整")))
        is_re_explain = str(payload.get("scene", "")) == "re_explain"
        explanation_steps = (
            [
                {"title": "先重建判断规则", "content": f"先不看原答案，只保留规则：{expected}"},
                {"title": "再代入错误证据", "content": f"回到你的作答可以看到：{evidence}"},
                {"title": "最后做一次反例检查", "content": f"若继续沿用原做法，会重复出现：{root_cause}"},
            ]
            if is_re_explain
            else [
                {"title": "先定位错误证据", "content": evidence},
                {"title": "再对照正确要求", "content": expected},
                {"title": "最后修正原因", "content": root_cause},
            ]
        )
        requested_delivery = str(payload.get("requested_delivery_mode", "")).strip()
        delivery_mode = "video_interactive" if requested_delivery == "video" else "interactive_document"
        strategy_code = str(strategy.get("strategy_code", "")).strip()
        if not strategy_code:
            strategy_code = "rule_reconstruction" if is_re_explain else "evidence_contrast_explanation"
        return {
            "status": "ok",
            "workflow_mode": "review",
            "question_snapshot": question,
            "current_attempt": attempt,
            "validated_evaluation": evaluation,
            "target_error": target,
            "personalized_explanation": (
                f"你在“{knowledge_name}”上的问题已经定位。{evidence}。"
                f"正确要求是：{expected}。这次错误的主要原因是：{root_cause}。"
            ),
            "explanation_steps": explanation_steps,
            "teaching_strategy": {
                **strategy,
                "strategy_code": strategy_code,
                "delivery_mode": delivery_mode,
                "reason": (
                    "避开上一轮证据对照方式，改为规则重建和反例检查。"
                    if is_re_explain
                    else "先展示用户自己的错误证据，再与正确要求进行最小对照。"
                ),
            },
            "retry_guidance": f"重做时先检查“{expected}”，再提交答案。",
            "variant_practice_request": {
                "knowledge_point_id": str(target.get("knowledge_point_id", "")),
                "difficulty": "same",
            },
            "next_action": "retry_original",
            "student_profile_snapshot": student_profile,
            "resources": [],
        }

    def _kb_entry(self, knowledge_id: str, category: str) -> dict[str, Any] | None:
        """从课程知识库检索某知识点、某类别的真实条目；无库或未命中返回 None（调用方回落模板）。"""
        store = self.token_store
        if store is None:
            return None
        try:
            items = store.search_knowledge(
                knowledge_point_id=knowledge_id, category=category, limit=1
            )
        except Exception:
            return None
        return items[0] if items else None

    @staticmethod
    def _kb_source(entry: dict[str, Any] | None) -> str:
        """知识条目的溯源串（教材来源 + 定位），用于教学包 source 字段。"""
        if not entry:
            return "课程知识库"
        source = str(entry.get("source", "")).strip()
        locator = str(entry.get("locator", "")).strip()
        return " · ".join(part for part in (source, locator) if part) or "课程知识库"

    @staticmethod
    def _kb_steps_items(entry: dict[str, Any]) -> list[str]:
        """把知识库步骤条目的“1) …；2) …”拆成步骤列表。"""
        content = str(entry.get("content", "")).strip()
        items: list[str] = []
        for part in re.split(r"[；;]", content):
            part = re.sub(r"^\s*\d+[).、]\s*", "", part).strip()
            if part:
                items.append(part)
        return items or [content]

    def _mock_learning(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = payload
        payload = as_dict(request_payload.get("context")) or request_payload
        strategy = as_dict(request_payload.get("strategy"))
        student_profile = as_dict(request_payload.get("student_profile"))
        event_type = str(payload.get("event_type", "initialize_learning"))
        diagnostic = as_dict(payload.get("diagnostic_result"))
        weak_points = [item for item in as_list(diagnostic.get("weak_points")) if isinstance(item, dict)]
        weak_points.sort(
            key=lambda item: (
                int(item.get("recommended_order", 999) or 999),
                -int(item.get("priority", 0) or 0),
            )
        )
        persisted_path = as_dict(payload.get("learning_path")) or as_dict(
            as_dict(payload.get("learning_state")).get("learning_path")
        )
        persisted_items = [
            dict(item)
            for item in as_list(persisted_path.get("items"))
            if isinstance(item, dict)
        ]
        target = as_dict(payload.get("current_knowledge_point")) or (weak_points[0] if weak_points else {})
        target_id = str(target.get("knowledge_point_id", ""))
        persisted_target = next(
            (
                item
                for item in persisted_items
                if str(item.get("knowledge_point_id", "")) == target_id
            ),
            {},
        )
        if persisted_target:
            target = {**persisted_target, **target}
        if not target:
            return {
                "status": "fatal_internal",
                "workflow_mode": "learning",
                "error_code": "MISSING_UPSTREAM_TARGET",
                "user_message": "上游尚未提供薄弱知识点，无法开始个性化学习。",
            }

        history = as_dict(payload.get("teaching_history"))
        history_events = [item for item in as_list(history.get("events")) if isinstance(item, dict)]
        previous_mode = str(payload.get("previous_mode", ""))
        if not previous_mode and history_events:
            previous_mode = str(history_events[-1].get("teaching_mode", ""))
        mode = str(strategy.get("preferred_representation", "")).strip() or "interactive_document"
        if event_type == "request_video":
            mode = "video_interactive"
        elif event_type == "request_text":
            mode = "interactive_document"
        elif event_type == "show_example":
            mode = "worked_example"
        elif event_type == "show_steps":
            mode = "step_by_step"
        elif event_type == "switch_explanation":
            mode = "worked_example" if previous_mode not in {"worked_example", "text"} else "execution_trace"
        elif event_type == "check_feedback":
            check_result = as_dict(payload.get("check_result"))
            mode = "interactive_document" if str(check_result.get("status")) == "correct" else "execution_trace"

        knowledge_id = str(target.get("knowledge_point_id", "KN_JAVA_ENCAPSULATION"))
        knowledge_name = str(target.get("knowledge_point_name", "封装与访问控制"))
        mastery = int(target.get("mastery", 42) or 42)
        objective = f"能够说明“{knowledge_name}”的核心规则，并在实训任务中正确应用。"
        goal_driven = bool(payload.get("goal_driven"))
        mode_reason = {
            "video_interactive": "用户主动请求视频，通过可视化过程降低抽象理解负担。",
            "worked_example": "上一种讲法没有生效，改用完整案例逐步推演。",
            "execution_trace": "阶段反馈显示仍未掌握，改为观察数据逐步变化的执行轨迹。",
            "step_by_step": "将复杂过程拆成单一动作，完成一步后再进入下一步。",
            "interactive_document": "当前掌握度较低，先用可交互图文建立稳定概念。",
        }.get(mode, "根据本轮策略和学生画像选择当前讲解方式。")
        # 优先从课程知识库检索该知识点的真实条目填充教学包，检索不到才回落通用模板，
        # 保证 mock 模式下讲解内容也是可溯源的真实知识而非占位话术。
        kb_concept = self._kb_entry(knowledge_id, "concept")
        kb_steps = self._kb_entry(knowledge_id, "steps")
        kb_example = self._kb_entry(knowledge_id, "example")
        kb_warning = self._kb_entry(knowledge_id, "warning")
        kb_workplace = self._kb_entry(knowledge_id, "workplace")
        kb_standard = self._kb_entry(knowledge_id, "standard")
        kb_safety = self._kb_entry(knowledge_id, "safety")
        fallback_steps_items = [
            "先标记任务中真正有效的数据",
            "再从同一有效集合完成计算或判断",
            "最后用边界数据检查结果是否稳定",
        ]
        blocks = [
            {
                "type": "weakness_connection",
                "title": "为什么先学这一点",
                "content": (
                    str(target.get("weakness_evidence", "")).strip()
                    or (
                        "该节点是学习目标路径的起点，先掌握它再进入依赖它的后续节点。"
                        if goal_driven
                        else "诊断结果显示该知识点掌握度偏低。"
                    )
                ),
                "source": "学习目标图谱" if goal_driven else "上游诊断结果",
            },
            {
                "type": "concept",
                "title": str(kb_concept.get("title", "核心规则")) if kb_concept else "核心规则",
                "content": (
                    str(kb_concept.get("content", "")).strip()
                    if kb_concept
                    else f"处理“{knowledge_name}”时，应先明确参与处理的数据范围，再让后续步骤使用同一套规则。"
                ),
                "source": self._kb_source(kb_concept),
            },
        ]
        if kb_workplace:
            blocks.append(
                {
                    "type": "workplace",
                    "title": str(kb_workplace.get("title", "岗位场景")),
                    "content": str(kb_workplace.get("content", "")).strip(),
                    "source": self._kb_source(kb_workplace),
                }
            )
        if mode == "worked_example":
            example_block: dict[str, Any] = {
                "type": "example",
                "title": str(kb_example.get("title", "换一个完整案例")) if kb_example else "换一个完整案例",
                "source": self._kb_source(kb_example),
            }
            if kb_example:
                example_block["content"] = str(kb_example.get("content", "")).strip()
            else:
                example_block["items"] = fallback_steps_items
            blocks.append(example_block)
        else:
            blocks.append(
                {
                    "type": "steps",
                    "title": str(kb_steps.get("title", "本轮讲解步骤")) if kb_steps else "本轮讲解步骤",
                    "items": self._kb_steps_items(kb_steps) if kb_steps else fallback_steps_items,
                    "source": self._kb_source(kb_steps),
                }
            )
        if kb_warning:
            blocks.append(
                {
                    "type": "warning",
                    "title": str(kb_warning.get("title", "常见误区")),
                    "content": str(kb_warning.get("content", "")).strip(),
                    "source": self._kb_source(kb_warning),
                }
            )
        if kb_standard:
            blocks.append(
                {
                    "type": "standard",
                    "title": str(kb_standard.get("title", "标准要求")),
                    "content": str(kb_standard.get("content", "")).strip(),
                    "source": self._kb_source(kb_standard),
                }
            )
        if kb_safety:
            blocks.append(
                {
                    "type": "safety",
                    "title": str(kb_safety.get("title", "安全要点")),
                    "content": str(kb_safety.get("content", "")).strip(),
                    "source": self._kb_source(kb_safety),
                }
            )
        path_items = persisted_items
        if not path_items:
            for index, item in enumerate(weak_points or [target], start=1):
                item_id = str(item.get("knowledge_point_id", ""))
                if item_id == knowledge_id:
                    status = "current"
                elif int(item.get("mastery", 0) or 0) >= 80:
                    status = "completed"
                else:
                    status = "pending"
                path_items.append(
                    {
                        "knowledge_point_id": item_id,
                        "knowledge_point_name": str(item.get("knowledge_point_name", f"学习节点 {index}")),
                        "knowledge_type": str(item.get("knowledge_type", "conceptual")),
                        "mastery": int(item.get("mastery", 0) or 0),
                        "recommended_order": index,
                        "status": status,
                    }
                )
        progress = 0
        if path_items:
            try:
                progress = int(persisted_path.get("progress")) if persisted_items else 0
            except (TypeError, ValueError):
                progress = 0
            if not persisted_items or "progress" not in persisted_path:
                completed = sum(1 for item in path_items if item["status"] == "completed")
                progress = round((completed + 0.4) / len(path_items) * 100)
        return {
            "status": "ok",
            "workflow_mode": "learning",
            "event_type": event_type,
            "lesson_id": f"{payload.get('lesson_run_id', 'LESSON')}-{knowledge_id}",
            "knowledge_point_id": knowledge_id,
            "lesson_title": knowledge_name,
            "lesson_objective": objective,
            "teaching_plan": {
                "depth": str(strategy.get("explanation_depth")) or (
                    "guided" if mastery < 60 else "concise"
                ),
                "primary_mode": mode,
                "alternative_modes": ["video_interactive", "interactive_document", "worked_example"],
                "reason": mode_reason,
            },
            "learning_strategy": strategy,
            "student_profile_snapshot": student_profile,
            "content_blocks": blocks,
            "resources": [
                {
                    "type": "interactive_document",
                    "title": f"{knowledge_name}互动学习卡",
                    "source": "课程资源库",
                    "description": "与本节内容同步的概念、案例和步骤卡。",
                }
            ],
            "resource_gap": "视频地址需要在知识库或联网搜索节点中配置。" if mode == "video_interactive" else "",
            "check_request": {
                "knowledge_point_id": knowledge_id,
                "check_type": "short_scenario",
                "difficulty": "same",
                "focus": f"判断一个新场景是否正确应用了“{knowledge_name}”。",
            },
            "path_update": {
                "current_status": "ready_for_check",
                "progress": progress,
            },
            "learning_path": {"items": path_items, "progress": progress},
            "actions": [
                "not_understood",
                "show_example",
                "show_steps",
                "switch_explanation",
                "request_video",
                "request_text",
                "start_check",
            ],
            "sources": ["课程知识库", "错误诊断卡"],
        }


class LearningApplication:
    def __init__(
        self,
        settings: Settings,
        store: StateStore,
        gateway: XingchenGateway,
        video_search: VideoSearchGateway,
        domain: LearningDomainStore,
        student_models: StudentModelCache,
        knowledge_cache: KnowledgeCache,
    ):
        self.settings = settings
        self.store = store
        self.gateway = gateway
        self.video_search = video_search
        self.domain = domain
        self.student_models = student_models
        self.knowledge_cache = knowledge_cache
        self.discovery = DiscoveryService(settings.database_path)
        self._profile_refreshing: set[str] = set()
        self._profile_refresh_lock = threading.RLock()
        self._video_cache: dict[str, dict[str, Any]] = {}
        self._video_cache_ttl = 3600

    @staticmethod
    def _default_student_model() -> dict[str, Any]:
        return {
            "learning_style": "balanced",
            "learning_style_confidence": 0.0,
            "effective_modes": {},
            "ineffective_modes": [],
            "misconception_tags": [],
            "pace_factor": 1.0,
            "strengths": [],
            "weaknesses": [],
            "attention_pattern": "unknown",
            "scaffold_preference": "moderate",
            "ability_scores": {},
            "learning_style_distribution": {},
        }

    def _student_model(self, student_id: str) -> dict[str, Any]:
        cached = self.student_models.get_model(student_id) or {}
        model = {
            **self._default_student_model(),
            **as_dict(cached.get("student_model")),
        }
        model["strategy_defaults"] = as_dict(cached.get("strategy_defaults"))
        return model

    def _profile_payload(
        self, student_id: str, state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        current_state = state if state is not None else self.store.get_student_state(student_id)
        records = self.domain.records(student_id)
        return {
            "student_id": student_id,
            "event_count": self.student_models.event_count(student_id),
            "teaching_history": as_dict(current_state.get("teaching_history")),
            "knowledge_state": {
                "learning_path": as_dict(current_state.get("learning_path")),
                "current_knowledge_point": as_dict(
                    current_state.get("current_knowledge_point")
                ),
            },
            "practice_results": as_list(records.get("attempts")),
            "resource_preferences": as_dict(current_state.get("resource_preferences")),
        }

    def _refresh_profile(self, student_id: str) -> dict[str, Any]:
        payload = self._profile_payload(student_id)
        result = self.gateway.invoke_profile_workflow(payload)
        model = as_dict(result.get("student_model"))
        strategy = as_dict(result.get("strategy_defaults"))
        if not model:
            raise GatewayError("学生画像工作流未返回 student_model")
        for key in ("ability_scores", "learning_style_distribution"):
            value = result.get(key)
            if isinstance(value, dict) and value:
                model[key] = value
        based_on_count = int(
            result.get("based_on_event_count", payload.get("event_count", 0)) or 0
        )
        self.student_models.save_model(
            student_id,
            model,
            strategy,
            based_on_event_count=based_on_count,
        )
        normalized = {
            "status": "ok",
            "student_id": student_id,
            "student_model": model,
            "strategy_defaults": strategy,
            "generated_at": result.get("generated_at") or utc_now(),
            "based_on_event_count": based_on_count,
        }
        self.store.record_run(student_id, "profile", payload, normalized)
        return normalized

    def _trigger_profile_refresh(self, student_id: str, force: bool = False) -> bool:
        if not force and not self.student_models.should_refresh(student_id):
            return False
        with self._profile_refresh_lock:
            if student_id in self._profile_refreshing:
                return False
            self._profile_refreshing.add(student_id)

        def refresh() -> None:
            try:
                self._refresh_profile(student_id)
            except Exception as error:
                print(f"学生画像异步刷新失败（{student_id}）：{error}")
            finally:
                with self._profile_refresh_lock:
                    self._profile_refreshing.discard(student_id)

        threading.Thread(
            target=refresh,
            name=f"profile-refresh-{student_id}",
            daemon=True,
        ).start()
        return True

    def refresh_profile(self, student_id: str) -> dict[str, Any]:
        student_id = str(student_id).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        return self._refresh_profile(student_id)

    def profile_status(self, student_id: str) -> dict[str, Any]:
        student_id = str(student_id).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        return {"status": "ok", "student_id": student_id, **self.student_models.status(student_id)}

    @staticmethod
    def _inspect_workflow_resume_token(token: Any) -> dict[str, Any] | None:
        """解析远程工作流（自定义621d71_v5）的 zlib+base64 自包含令牌。

        返回令牌内嵌的 data（含 student_id/session_id），无法解码时返回 None。
        仅作身份绑定校验用；令牌无签名，完整性保护需工作流侧加 HMAC（见契约文档）。
        """
        text = str(token or "").strip()
        if not text:
            return None
        try:
            text += "=" * (-len(text) % 4)
            packed = base64.urlsafe_b64decode(text.encode("ascii"))
            payload = json.loads(zlib.decompress(packed).decode("utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                return payload["data"]
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return None

    @staticmethod
    def _knowledge_point(context: dict[str, Any], workflow: str) -> dict[str, Any]:
        if workflow == "learning":
            return as_dict(context.get("current_knowledge_point")) or as_dict(
                context.get("learning_target")
            )
        evaluation = as_dict(context.get("validated_evaluation"))
        errors = [
            item
            for item in as_list(evaluation.get("error_points"))
            if isinstance(item, dict)
        ]
        return errors[0] if errors else as_dict(context.get("target_error"))

    def _retrieve_knowledge_text(
        self, context: dict[str, Any], workflow: str, action: str = ""
    ) -> str:
        explicit = context.get("kb_text")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        for key in ("knowledge_context", "knowledge_base_context", "retrieval_context"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict) and value:
                return json_text(value)

        kb_text = self._retrieve_from_knowledge_base(context, workflow, action)
        if kb_text:
            return kb_text

        target = self._knowledge_point(context, workflow)
        name = str(
            target.get("knowledge_point_name")
            or target.get("topic")
            or target.get("knowledge_point_id")
            or "当前知识点"
        )
        evidence_parts = [
            str(target.get(key, "")).strip()
            for key in (
                "expected_behavior",
                "diagnosis",
                "root_cause",
                "weakness_evidence",
            )
        ]
        evidence_parts = [part for part in evidence_parts if part]
        if evidence_parts:
            return f"知识点：{name}。\n" + "\n".join(evidence_parts)
        return (
            f"知识点：{name}。当前未提供独立知识库正文；"
            "只能使用输入上下文中已经明确的事实，不得补充未经依据支持的专业结论。"
        )

    def _knowledge_text(
        self, context: dict[str, Any], workflow: str, action: str
    ) -> str:
        target = self._knowledge_point(context, workflow)
        knowledge_id = str(target.get("knowledge_point_id") or "unknown")
        key = f"{knowledge_id}:{action}"
        cached = self.knowledge_cache.get(key)
        if cached is not None:
            return cached
        text = self._retrieve_knowledge_text(context, workflow, action)
        self.knowledge_cache.set(key, text)
        return text

    def _retrieve_from_knowledge_base(
        self, context: dict[str, Any], workflow: str, action: str
    ) -> str:
        try:
            total = self.domain.knowledge_count()
        except Exception:
            total = 0
        if not total:
            return ""
        target = self._knowledge_point(context, workflow)
        knowledge_id = str(target.get("knowledge_point_id") or "")
        query = str(
            target.get("knowledge_point_name")
            or target.get("topic")
            or target.get("title")
            or ""
        ).strip()
        items = self.domain.search_knowledge(
            query=query, knowledge_point_id=knowledge_id, action=action, limit=6
        )
        if not items and knowledge_id:
            items = self.domain.search_knowledge(query=query, action=action, limit=6)
        if not items and query:
            items = self.domain.search_knowledge(
                query=query, knowledge_point_id=knowledge_id, limit=6
            )
        if not items:
            return ""
        context["kb_hits"] = items
        return "\n\n".join(self._format_kb_entry(item) for item in items)

    @staticmethod
    def _format_kb_entry(item: dict[str, Any]) -> str:
        source_line = f"来源：{item.get('source')}"
        document_id = str(item.get("document_id") or "")
        locator = str(item.get("locator") or "")
        if document_id:
            source_line += f"（{document_id}）"
        if locator:
            source_line += f"，{locator}"
        return "\n".join(
            part
            for part in (
                f"【{item.get('title')}】",
                str(item.get("content") or ""),
                source_line,
            )
            if part
        )

    def _merge_kb_sources(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> None:
        hits = [
            item for item in as_list(context.get("kb_hits")) if isinstance(item, dict)
        ]
        if not hits:
            return
        existing = as_list(result.get("sources"))
        merged = list(existing)
        seen = {
            (str(source.get("title", "")) if isinstance(source, dict) else str(source))
            for source in existing
        }
        for item in hits:
            title = str(item.get("source") or "知识库")
            if title in seen:
                continue
            seen.add(title)
            merged.append({
                "type": str(item.get("source_type") or "document"),
                "title": title,
                "document_id": str(item.get("document_id") or ""),
                "locator": str(item.get("locator") or ""),
                "quote": str(item.get("content") or "")[:280],
                "url": "",
                "verification_state": (
                    "verified" if str(item.get("source_type")) == "standard" else "provided"
                ),
            })
        result["sources"] = merged

    def _merge_web_sources(self, result: dict[str, Any]) -> None:
        # 方案 B：联网结果由工作流内「联网结果规范化」节点返回 web_search_context_json
        parsed = parse_json_object(str(result.get("web_search_context_json") or ""))
        web_results = [
            item
            for item in as_list(as_dict(parsed).get("results"))
            if isinstance(item, dict) and str(item.get("type", "")) != "video"
        ]
        if not web_results:
            return
        existing = as_list(result.get("sources"))
        seen = {
            str(source.get("title", ""))
            for source in existing
            if isinstance(source, dict)
        }
        merged = list(existing)
        for item in web_results:
            title = str(item.get("title") or "")
            if not title or title in seen:
                continue
            seen.add(title)
            merged.append({
                "type": "web",
                "title": title,
                "source": str(
                    item.get("source") or item.get("source_domain") or "联网检索"
                ),
                "url": str(item.get("url") or ""),
                "quote": str(item.get("snippet") or item.get("content") or "")[:280],
                "locator": str(item.get("source_domain") or ""),
                "verification_state": "whitelisted",
            })
        result["sources"] = merged
        # 工作流联网结果同时进入「文档板块」资源列表，前端内联展示
        resources = [item for item in as_list(result.get("resources")) if isinstance(item, dict)]
        existing_urls = {str(item.get("url", "")) for item in resources if item.get("url")}
        for item in web_results:
            url = str(item.get("url") or "")
            if not url or url in existing_urls:
                continue
            resources.append(
                {
                    "type": "document",
                    "title": str(item.get("title") or "联网官方文档"),
                    "url": url,
                    "source": str(item.get("source") or item.get("source_domain") or "联网检索"),
                    "source_domain": str(item.get("source_domain") or ""),
                    "provider": "星辰聚合搜索",
                    "description": str(item.get("snippet") or item.get("content") or "")[:320],
                    "reason": "工作流联网依据复检通过的白名单资料",
                }
            )
            existing_urls.add(url)
        result["resources"] = resources

    @staticmethod
    def _detect_follow_up_action(question: str, selection: str = "") -> str:
        text = f"{question} {selection}"
        if any(key in text for key in ("易错", "注意", "危险", "安全", "错误", "报警", "故障")):
            return "warning"
        if any(key in text for key in ("例子", "案例", "举例", "怎么用", "岗位", "应用")):
            return "example"
        if any(key in text for key in ("步骤", "怎么操作", "如何", "流程", "拆解")):
            return "steps"
        return "concept"

    def _learning_workflow_payload(
        self, context: dict[str, Any]
    ) -> dict[str, Any]:
        student_id = str(context.get("student_id", ""))
        student_model = self._student_model(student_id)
        learning_state = as_dict(context.get("learning_state"))
        ineffective = list(as_list(student_model.get("ineffective_modes")))
        ineffective.extend(as_list(learning_state.get("ineffective_modes")))
        target = self._knowledge_point(context, "learning")
        action = str(context.get("learner_action") or "first")
        strategy = StrategyEngine.decide_learning_strategy(
            action,
            str(target.get("knowledge_type") or "conceptual"),
            target.get("mastery", as_dict(context.get("knowledge_state")).get("mastery", 0)),
            ineffective,
            student_model,
        )
        return {
            "student_id": student_id,
            "session_id": str(context.get("session_id", "")),
            "context": context,
            "strategy": strategy,
            "student_profile": student_model,
            "kb_text": self._knowledge_text(context, "learning", action),
        }

    def _remediation_workflow_payload(
        self, context: dict[str, Any]
    ) -> dict[str, Any]:
        student_id = str(context.get("student_id", ""))
        student_model = self._student_model(student_id)
        evaluation = as_dict(context.get("validated_evaluation"))
        target = self._knowledge_point(context, "remediation")
        knowledge_state = as_dict(context.get("knowledge_state"))
        mastery = target.get("mastery", knowledge_state.get("mastery", 0))
        strategy = StrategyEngine.decide_remediation_strategy(
            str(evaluation.get("evaluation_status", "")),
            str(target.get("error_type", "")),
            mastery,
            int(target.get("same_error_count", target.get("repeat_count", 0)) or 0),
            int(target.get("wrong_streak", knowledge_state.get("wrong_streak", 0)) or 0),
            int(target.get("correct_streak", knowledge_state.get("correct_streak", 0)) or 0),
            as_list(target.get("prerequisite_gap"))
            or as_list(context.get("prerequisite_gap")),
            student_model,
        )
        return {
            "student_id": student_id,
            "session_id": str(context.get("session_id", "")),
            "context": context,
            "strategy": strategy,
            "student_profile": student_model,
            "kb_text": self._knowledge_text(context, "remediation", "review"),
        }

    def _attach_video_search(self, workflow: str, context: dict[str, Any]) -> None:
        existing = as_dict(context.get("web_search_context"))
        if as_list(existing.get("results")):
            return
        if not self.video_search.should_search(workflow, context):
            return
        # 同知识点 1 小时内复用上次搜索结果，保证视频资源稳定可复现
        target = self._knowledge_point(context, workflow)
        cache_key = f"{workflow}:{target.get('knowledge_point_id', '')}"
        cached = self._video_cache.get(cache_key)
        if cached:
            age = (time.time() - float(cached.get("_searched_ts", 0))) if cached.get("_searched_ts") else self._video_cache_ttl + 1
            if age <= self._video_cache_ttl:
                context["web_search_context"] = {
                    "status": str(cached.get("status") or "ok"),
                    "provider": "bilibili",
                    "query": str(cached.get("query") or ""),
                    "searched_at": str(cached.get("searched_at") or utc_now()),
                    "results": as_list(cached.get("results")),
                }
                return
        video_result = self.video_search.search(workflow, context)
        combined_results = list(as_list(video_result.get("results")))
        combined_status = str(video_result.get("status") or "no_results")
        if self.video_search.doc_enabled:
            doc_result = self.video_search.search_documents(workflow, context)
            combined_results.extend(as_list(doc_result.get("results")))
            if as_list(doc_result.get("results")):
                combined_status = "ok"
            elif combined_status not in {"ok", "skipped"}:
                combined_status = str(doc_result.get("status") or combined_status)
        context["web_search_context"] = {
            "status": combined_status,
            "provider": "bing_rss",
            "query": str(video_result.get("query") or ""),
            "searched_at": utc_now(),
            "results": combined_results,
        }
        # 缓存结果（含时间戳，供 TTL 判断）
        if cache_key:
            self._video_cache[cache_key] = {
                **context["web_search_context"],
                "_searched_ts": time.time(),
            }

    @staticmethod
    def _knowledge_keywords(knowledge_name: str) -> list[str]:
        """把知识点名拆成检索关键词：按常见连接词切分并去重（小写）。

        「封装与访问控制」→ ["封装", "访问控制"]；「类与对象」→ ["类", "对象"]。
        短词（<2 字符）忽略；无有效词时返回空列表（不启用过滤）。
        """
        name = str(knowledge_name or "").strip().lower()
        if not name:
            return []
        parts = re.split(r"与|和|及|、|，|,| ", name)
        keywords = [p.strip() for p in parts if len(p.strip()) >= 2]
        seen: set[str] = set()
        result: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result

    def _merge_video_resources(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        search_context = as_dict(context.get("web_search_context"))
        search_results = [
            item
            for item in as_list(search_context.get("results"))
            if isinstance(item, dict)
            and str(item.get("type", "")) == "video"
            and str(item.get("url", "")).startswith(("https://", "http://"))
        ]
        # 按当前知识点相关性排序：标题/简介命中知识点关键词的视频排前，
        # 前端只展示第一个，从而避免"视频与该章节教学内容不符"。
        knowledge_name = str(
            as_dict(context.get("current_knowledge_point")).get("knowledge_point_name", "")
        ).strip()
        keywords = self._knowledge_keywords(knowledge_name)
        if keywords:
            def relevance(item: dict[str, Any]) -> int:
                text = " ".join(
                    str(item.get(key) or "") for key in ("title", "snippet", "content")
                ).lower()
                return 0 if any(kw in text for kw in keywords) else 1
            search_results.sort(key=relevance)
        resources = [item for item in as_list(result.get("resources")) if isinstance(item, dict)]
        existing_urls = {str(item.get("url", "")) for item in resources if item.get("url")}
        for item in search_results:
            url = str(item.get("url", ""))
            if url in existing_urls:
                for resource in resources:
                    if str(resource.get("url", "")) != url:
                        continue
                    for key in ("source", "source_domain", "embed_url", "provider"):
                        if item.get(key) and not resource.get(key):
                            resource[key] = item[key]
                continue
            description = str(item.get("snippet", item.get("content", ""))).strip()
            resources.append(
                {
                    "type": "video",
                    "title": str(item.get("title", "联网教学视频")),
                    "url": url,
                    "embed_url": str(item.get("embed_url", "")),
                    "source": str(item.get("source", item.get("source_domain", "联网搜索"))),
                    "source_domain": str(item.get("source_domain", "")),
                    "provider": str(item.get("provider", search_context.get("provider", "联网搜索"))),
                    "description": description[:240],
                    "segment": str(item.get("segment", "请从视频简介和章节定位相关片段")),
                    "reason": str(item.get("reason", "与当前薄弱知识点相关，由联网搜索返回")),
                }
            )
            existing_urls.add(url)
        # 合并后统一按知识点相关性重排 video 资源（工作流自带/缓存 + 联网合并），
        # 保证前端展示的第一个视频与当前章节内容相关。
        if keywords and resources:
            video_items = [
                item for item in resources if str(item.get("type", "")) == "video"
            ]
            if video_items and len(video_items) > 1:
                def merged_relevance(item: dict[str, Any]) -> int:
                    text = " ".join(
                        str(item.get(key) or "") for key in ("title", "description")
                    ).lower()
                    return 0 if any(kw in text for kw in keywords) else 1
                video_items.sort(key=merged_relevance)
                # 保持非 video 资源相对顺序，video 整体重排后放回原位
                non_video = [
                    item for item in resources if str(item.get("type", "")) != "video"
                ]
                resources = non_video + video_items
        result["resources"] = resources
        if search_results:
            result["resource_gap"] = ""
            sources = [
                item
                for item in as_list(result.get("sources"))
                if isinstance(item, dict)
            ]
            seen = {str(item.get("title", "")) for item in sources}
            for item in search_results:
                title = str(
                    item.get("source") or item.get("source_domain") or ""
                ).strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                sources.append({
                    "type": "web",
                    "title": title,
                    "source": title,
                    "url": str(item.get("url") or ""),
                    "quote": str(item.get("content") or item.get("snippet") or "")[:280],
                    "locator": str(item.get("source_domain") or ""),
                    "verification_state": "whitelisted",
                })
            result["sources"] = sources
        elif self.video_search.should_search(str(result.get("workflow_mode", "learning")), context):
            status = str(search_context.get("status", ""))
            if status == "search_failed":
                result.setdefault("resource_gap", "联网视频检索暂时失败，请稍后重试。")
            elif status == "no_results":
                result.setdefault("resource_gap", "本轮联网检索未找到带明确来源的相关视频。")

    def _merge_document_resources(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        search_context = as_dict(context.get("web_search_context"))
        search_results = [
            item
            for item in as_list(search_context.get("results"))
            if isinstance(item, dict)
            and str(item.get("type", "")) == "document"
            and str(item.get("url", "")).startswith(("https://", "http://"))
        ]
        if not search_results:
            return
        resources = [item for item in as_list(result.get("resources")) if isinstance(item, dict)]
        existing_urls = {str(item.get("url", "")) for item in resources if item.get("url")}
        for item in search_results:
            url = str(item.get("url", ""))
            if url in existing_urls:
                continue
            description = str(item.get("snippet", item.get("content", ""))).strip()
            resources.append(
                {
                    "type": "document",
                    "title": str(item.get("title", "联网官方文档")),
                    "url": url,
                    "source": str(item.get("source", item.get("source_domain", "联网检索"))),
                    "source_domain": str(item.get("source_domain", "")),
                    "provider": str(item.get("provider", search_context.get("provider", "联网搜索"))),
                    "description": description[:320],
                    "reason": str(item.get("reason", "与当前知识点相关，来自白名单官方文档")),
                }
            )
            existing_urls.add(url)
        result["resources"] = resources
        if search_results:
            result["resource_gap"] = ""
            sources = [
                item
                for item in as_list(result.get("sources"))
                if isinstance(item, dict)
            ]
            seen = {str(item.get("title", "")) for item in sources}
            for item in search_results:
                title = str(
                    item.get("source") or item.get("source_domain") or ""
                ).strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                sources.append({
                    "type": "web",
                    "title": title,
                    "source": title,
                    "url": str(item.get("url") or ""),
                    "quote": str(item.get("content") or item.get("snippet") or "")[:280],
                    "locator": str(item.get("source_domain") or ""),
                    "verification_state": "whitelisted",
                })
            result["sources"] = sources

    def _apply_check_feedback(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            str(context.get("event_type", "")) != "check_feedback"
            or result.get("status") != "ok"
        ):
            return {}
        check_result = as_dict(context.get("check_result"))
        # 只信服务端判定；客户端 passed 字段一律忽略（P1-3）
        passed = str(check_result.get("status", "")).lower() == "correct"
        path = as_dict(result.get("learning_path")) or as_dict(context.get("learning_path"))
        items = [dict(item) for item in as_list(path.get("items")) if isinstance(item, dict)]
        target_id = str(result.get("knowledge_point_id", ""))
        if not target_id:
            target_id = str(as_dict(context.get("current_knowledge_point")).get("knowledge_point_id", ""))
        next_item: dict[str, Any] = {}
        target_item = next(
            (
                item
                for item in items
                if str(item.get("knowledge_point_id", "")) == target_id
            ),
            {},
        )
        if target_item:
            try:
                current_mastery = int(target_item.get("mastery", 0) or 0)
            except (TypeError, ValueError):
                current_mastery = 0
            target_item["mastery"] = max(
                0,
                min(100, current_mastery + (20 if passed else -10)),
            )
        if passed:
            if target_item:
                target_item["status"] = "completed"
            next_item = next(
                (
                    item
                    for item in items
                    if str(item.get("status", "")) not in {"mastered", "completed"}
                    and str(item.get("knowledge_point_id", "")) != target_id
                ),
                {},
            )
            if next_item:
                for item in items:
                    if item is not next_item and str(item.get("status", "")) == "current":
                        item["status"] = "pending"
                next_item["status"] = "current"
        completed = sum(
            1 for item in items if str(item.get("status", "")) in {"mastered", "completed"}
        )
        progress = round(completed / len(items) * 100) if items else 0
        if not passed:
            existing_progress = as_dict(result.get("path_update")).get("progress")
            try:
                progress = int(existing_progress)
            except (TypeError, ValueError):
                pass
        result["learning_path"] = {**path, "items": items, "progress": progress}
        result["path_update"] = {
            **as_dict(result.get("path_update")),
            "current_status": (
                "completed_all"
                if passed and items and completed == len(items)
                else "completed"
                if passed
                else "needs_reteaching"
            ),
            "progress": progress,
            "next_knowledge_point_id": str(next_item.get("knowledge_point_id", "")),
        }
        result["check_feedback"] = {
            "passed": passed,
            "status": "correct" if passed else "not_understood",
            "selected_answer": incoming.get("selected_answer"),
        }
        return next_item

    def _adjust_path_mastery(
        self,
        student_id: str,
        knowledge_point_id: str,
        delta: int,
    ) -> dict[str, Any]:
        """按知识点调整持久化学习路径中的掌握度并保存（题库/阶段检查共用）。"""
        if not student_id or not knowledge_point_id:
            return {}
        state = self.store.get_student_state(student_id) or {}
        path = as_dict(state.get("learning_path"))
        items = [dict(item) for item in as_list(path.get("items")) if isinstance(item, dict)]
        target = next(
            (
                item
                for item in items
                if str(item.get("knowledge_point_id", "")) == knowledge_point_id
            ),
            {},
        )
        if not target:
            return {}
        try:
            current = int(target.get("mastery", 0) or 0)
        except (TypeError, ValueError):
            current = 0
        target["mastery"] = max(0, min(100, current + delta))
        state["learning_path"] = {**path, "items": items}
        state["updated_at"] = utc_now()
        self.store.save_student_state(student_id, state)
        return {"knowledge_point_id": knowledge_point_id, "mastery": target["mastery"]}

    def submit_bank_answer(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """题库作答：判题 + 落库（attempts）+ 更新掌握度（E-2）。"""
        student_id = str(incoming.get("student_id", "")).strip()
        question_id = str(incoming.get("question_id", "")).strip()
        answer = str(incoming.get("answer", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        question = bank_question_by_id(question_id)
        if not question:
            raise ApiError(404, "UNKNOWN_QUESTION", f"未知题目：{question_id}")
        recorded = self.domain.record_choice_attempt(
            student_id=student_id,
            source_question_id=question_id,
            mode="bank",
            knowledge_point_id=str(question.get("knowledge_point_id", "")),
            knowledge_point_name=str(question.get("knowledge_point_name", "")),
            title=str(question.get("title", "")),
            prompt=str(question.get("title", "")),
            options=as_dict(question.get("options")),
            expected=str(question.get("answer", "")),
            selected=answer,
            explanation=str(question.get("explanation", "")),
        )
        correct = bool(recorded.get("correct"))
        mastery_update = self._adjust_path_mastery(
            student_id,
            str(question.get("knowledge_point_id", "")),
            20 if correct else -10,
        )
        return {
            "status": "ok",
            "correct": correct,
            "question_id": question_id,
            "knowledge_point_id": question.get("knowledge_point_id", ""),
            "knowledge_point_name": question.get("knowledge_point_name", ""),
            "explanation": question.get("explanation", ""),
            "correct_answer": question.get("answer", ""),
            "attempt_id": recorded.get("attempt_id", ""),
            "mastery_update": mastery_update,
        }

    # ---------- 诊断（目标 → 测评 → 归因薄弱点）----------

    GOAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "competition",
            ("大赛", "比赛", "国赛", "世赛", "世界职业院校", "技能大赛", "竞赛", "备赛", "赛项"),
        ),
        ("certification", ("1+x", "认证", "证书", "考证", "考级")),
        ("daily", ("日常", "提升", "岗位", "查漏", "补缺", "自学", "就业", "面试", "工作")),
    )

    GOAL_META: dict[str, dict[str, str]] = {
        "competition": {
            "goal_id": "GOAL-JAVA-COMPETITION",
            "goal_type": "competition",
            "goal_name": "备战世界职业院校技能大赛",
        },
        "certification": {
            "goal_id": "GOAL-JAVA-CERT",
            "goal_type": "certification",
            "goal_name": "1+X Java 应用开发认证",
        },
        "daily": {
            "goal_id": "GOAL-JAVA-DAILY",
            "goal_type": "daily",
            "goal_name": "日常技能提升",
        },
    }

    def analyze_goal(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """目标意图解析：用户输入自由文本，识别为具体学习目标。

        mock 模式用本地关键词规则；remote 模式优先消费星辰目标工作流返回，
        解析失败回落关键词规则；均未命中时返回澄清提示（matched=false）。
        """
        text = str(incoming.get("text", "")).strip()
        if not text:
            raise ApiError(400, "MISSING_GOAL_TEXT", "请先输入你的学习目标")
        if len(text) < 2:
            return {
                "status": "ok",
                "matched": False,
                "confidence": 0.0,
                "clarification": (
                    f"“{text}”太简短，无法判断目标。"
                    "可以输入如“想考 1+X Java 应用开发认证”或“备战世界职业院校技能大赛”。"
                ),
            }
        if self.gateway.mode == "remote":
            try:
                remote_result = self.gateway.invoke_goal_workflow({"text": text})
                parsed = self._parse_goal_workflow_result(remote_result)
                if parsed:
                    return parsed
            except Exception:
                pass  # 联调异常回落本地规则，保证演示可用
        keyword_match = self._match_goal_keywords(text)
        if keyword_match.get("matched"):
            return keyword_match
        open_goal = self._open_goal_analysis(text)
        if open_goal.get("matched"):
            return {
                "status": "ok",
                "matched": True,
                "goal": open_goal["goal"],
                "diagnosis_goal": "custom",
                "confidence": 0.72,
                "keywords_hit": [],
            }
        return {
            "status": "ok",
            "matched": False,
            "confidence": 0.0,
            "clarification": open_goal.get("clarification", "请补充更具体的学习目标。"),
            "missing_fields": open_goal.get("missing_fields", []),
            "reason": open_goal.get("reason", "goal_unclear"),
        }

    @staticmethod
    def _parse_goal_workflow_result(result: dict[str, Any]) -> dict[str, Any] | None:
        """防御性解析星辰目标工作流返回；结构未联调定稿，字段缺失返回 None。"""
        raw = str(
            result.get("goal_type")
            or result.get("diagnosis_goal")
            or result.get("goal")
            or ""
        ).strip().lower()
        if raw in LearningApplication.GOAL_META:
            return {
                "status": "ok",
                "matched": True,
                "goal": dict(LearningApplication.GOAL_META[raw]),
                "diagnosis_goal": raw,
                "confidence": round(float(result.get("confidence", 0.9) or 0.9), 2),
                "keywords_hit": [],
            }
        return None

    def _match_goal_keywords(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        best_goal: str | None = None
        best_hits: list[str] = []
        for goal, keywords in self.GOAL_KEYWORDS:
            hits = [keyword for keyword in keywords if keyword in lowered]
            if len(hits) > len(best_hits):
                best_goal, best_hits = goal, hits
        if not best_goal:
            return {
                "status": "ok",
                "matched": False,
                "confidence": 0.0,
                "clarification": (
                    f"暂时无法从“{text}”中识别具体目标。"
                    "可输入如“想考 1+X Java 应用开发认证”“备战世界职业院校技能大赛”“日常技能提升”，"
                    "或直接选择上方快捷目标。"
                ),
            }
        confidence = min(0.95, 0.7 + 0.15 * (len(best_hits) - 1))
        return {
            "status": "ok",
            "matched": True,
            "goal": dict(self.GOAL_META[best_goal]),
            "diagnosis_goal": best_goal,
            "confidence": round(confidence, 2),
            "keywords_hit": best_hits,
        }

    def start_diagnosis(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        session_id = str(incoming.get("session_id", "")).strip()
        goal = str(incoming.get("goal", "daily")).strip()
        if not student_id or not session_id:
            raise ApiError(400, "MISSING_IDENTITY", "缺少 student_id 或 session_id")
        goal_config = DIAGNOSIS_GOALS.get(goal)
        if not goal_config:
            raise ApiError(400, "UNKNOWN_GOAL", f"不支持的目标：{goal}")

        state = self.store.get_student_state(student_id) or {}
        # 生成式出题：工作流 → 本地校验 → 入库；失败回落本地取样（前端无需改动）
        # 薄弱点来自上次诊断归因回写（upstream_payload），首轮无数据时按目标全覆盖出题
        upstream = as_dict(state.get("upstream_payload"))
        diagnostic = as_dict(upstream.get("diagnostic_result"))
        weak_points = [
            item
            for item in as_list(diagnostic.get("weak_points"))
            if isinstance(item, dict)
        ]
        generated, provider = self._generate_diagnosis_questions(
            student_id, goal, weak_points
        )

        questions = [
            {
                "question_id": item["question_id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "title": item["title"],
                "options": item["options"],
                "difficulty": item["difficulty"],
                "answer": item["answer"],
                "explanation": item["explanation"],
            }
            for item in generated
        ]
        rounds = int(state.get("diagnosis_rounds", 0) or 0) + 1
        state["diagnosis_session"] = {
            "goal": goal,
            "questions": questions,
            "index": 0,
            "correct": 0,
            "wrong": 0,
            "skipped": 0,
            "results": [],
            "done": False,
        }
        state["diagnosis_rounds"] = rounds
        self.store.save_student_state(student_id, state)
        public_questions = [
            {k: v for k, v in q.items() if k not in ("answer", "explanation")}
            for q in questions
        ]
        return {
            "status": "ok",
            "round": rounds,
            "goal": goal,
            "goal_label": goal_config["label"],
            "provider": provider,
            "questions": public_questions,
            "total": len(public_questions),
        }

    def submit_diagnosis_answer(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        session_id = str(incoming.get("session_id", "")).strip()
        if not student_id or not session_id:
            raise ApiError(400, "MISSING_IDENTITY", "缺少 student_id 或 session_id")
        state = self.store.get_student_state(student_id) or {}
        session = as_dict(state.get("diagnosis_session"))
        if not session:
            raise ApiError(409, "DIAGNOSIS_NOT_ACTIVE", "当前没有进行中的诊断，请先选择目标开始")
        if session.get("done"):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮诊断已结束，请重新开始")
        skipped = bool(incoming.get("skipped"))
        selected = str(incoming.get("selected", "")).strip()
        index = int(session.get("index", 0) or 0)
        questions = as_list(session.get("questions"))
        if index >= len(questions):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮诊断已结束")
        current = questions[index]
        if skipped:
            correct = False
            session["skipped"] = int(session.get("skipped", 0) or 0) + 1
        else:
            if selected not in {"a", "b", "c", "d"}:
                raise ApiError(400, "INVALID_ANSWER", "无效的选项")
            correct = selected == current.get("answer")
            key = "correct" if correct else "wrong"
            session[key] = int(session.get(key, 0) or 0) + 1
        if not skipped:
            # 诊断作答落库：进入 attempts，供画像溯源/学习记录/成长曲线使用
            self.domain.record_choice_attempt(
                student_id=student_id,
                source_question_id=str(current.get("question_id", "")),
                mode="diagnosis",
                knowledge_point_id=str(current.get("knowledge_point_id", "")),
                knowledge_point_name=str(current.get("knowledge_point_name", "")),
                title=str(current.get("title", "")),
                prompt=str(current.get("title", "")),
                options=as_dict(current.get("options")),
                expected=str(current.get("answer", "")),
                selected=selected,
                explanation=str(current.get("explanation", "")),
            )
        session.setdefault("results", []).append(
            {
                "question_id": current.get("question_id", ""),
                "knowledge_point_id": current.get("knowledge_point_id", ""),
                "knowledge_point_name": current.get("knowledge_point_name", ""),
                "correct": correct,
                "skipped": skipped,
            }
        )
        is_last = index + 1 >= len(questions)
        session["index"] = index + 1
        if is_last:
            session["done"] = True
        state["diagnosis_session"] = session
        self.store.save_student_state(student_id, state)

        stats = {
            "correct": session["correct"],
            "wrong": session["wrong"],
            "skipped": session["skipped"],
            "done": session["done"],
            "question_index": session["index"],
            "total": len(questions),
        }
        base = {
            "status": "ok",
            "correct": correct,
            "skipped": skipped,
            "explanation": current.get("explanation", ""),
            "knowledge_point_id": current.get("knowledge_point_id", ""),
            "knowledge_point_name": current.get("knowledge_point_name", ""),
            "answer": current.get("answer", ""),
            "stats": stats,
        }
        if not is_last:
            return base
        summary = self._finalize_diagnosis(student_id, state, session)
        base["status"] = "completed"
        base["summary"] = summary
        return base

    def _finalize_diagnosis(
        self,
        student_id: str,
        state: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """答错题目按知识点归因，更新掌握度并生成薄弱点摘要。"""
        wrong_counts: dict[str, dict[str, Any]] = {}
        for record in as_list(session.get("results")):
            if record.get("correct") or record.get("skipped"):
                continue
            kp_id = str(record.get("knowledge_point_id", ""))
            entry = wrong_counts.setdefault(
                kp_id,
                {"count": 0, "name": str(record.get("knowledge_point_name", kp_id))},
            )
            entry["count"] += 1
        # 更新持久化路径中对应知识点的掌握度（答错 -12）
        path = as_dict(state.get("learning_path"))
        items = [dict(item) for item in as_list(path.get("items")) if isinstance(item, dict)]
        updated = []
        for item in items:
            kp_id = str(item.get("knowledge_point_id", ""))
            if kp_id in wrong_counts:
                try:
                    mastery = int(item.get("mastery", 0) or 0)
                except (TypeError, ValueError):
                    mastery = 0
                item["mastery"] = max(0, min(100, mastery - 12))
            updated.append(item)
        if updated:
            state["learning_path"] = {**path, "items": updated}
            self.store.save_student_state(student_id, state)
        weak_points = sorted(
            (
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": entry["name"],
                    "error_count": entry["count"],
                    # 归因字段来自错误卡配置（P1-3），无配置时为缺省空值
                    "error_id": card.get("error_id", ""),
                    "error_type": card.get("error_type", ""),
                    "misconception_tag": card.get("misconception_tag", ""),
                    "root_cause": card.get("root_cause", ""),
                }
                for kp_id, entry in wrong_counts.items()
                for card in (default_error_card_for(kp_id),)
            ),
            key=lambda item: -item["error_count"],
        )
        # 归因结果回写 upstream_payload：画像页（portrait）与学习兜底（weak_points[0]）
        # 直接消费，形成「诊断 → 薄弱点 → 复测按薄弱点出题」闭环
        upstream = as_dict(state.get("upstream_payload"))
        diagnostic = as_dict(upstream.get("diagnostic_result"))
        upstream["diagnostic_result"] = {**diagnostic, "weak_points": weak_points}
        state["upstream_payload"] = upstream
        self.store.save_student_state(student_id, state)
        return {
            "weak_points": weak_points,
            "feedback": (
                f"诊断完成：发现 {len(weak_points)} 个薄弱知识点，"
                "已更新掌握度，建议按路径顺序优先学习薄弱项。"
            ),
        }

    # ---------- 项目（agent 形态：每个学习目标一个项目）----------

    # 项目目标 → 诊断取样配置的映射（goal_graph 目标 → DIAGNOSIS_GOALS 键）
    PROJECT_GOAL_DIAGNOSIS: dict[str, str] = {
        "GOAL-JAVA-001": "daily",
        "GOAL-JAVA-COMPETITION": "competition",
        "GOAL-JAVA-CERT": "certification",
        "GOAL-JAVA-DAILY": "daily",
    }

    # ---------- 生成式题库（工作流出题 → 本地校验 → 入库）----------

    def _validate_quiz_questions(
        self, questions: list[Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """本地审核工作流出题：答案确定性、选项合法性、知识点绑定。

        返回 (valid, dropped)。任何不满足确定性/完整性规则的题直接丢弃，
        宁可少题也不让非法题进入诊断（比赛"内容专业准确性"的本地防线）。
        """
        valid: list[dict[str, Any]] = []
        dropped = 0
        for raw in questions:
            if not isinstance(raw, dict):
                dropped += 1
                continue
            title = str(raw.get("title") or "").strip()
            options = as_dict(raw.get("options"))
            answer = str(raw.get("answer") or "").strip().lower()
            explanation = str(raw.get("explanation") or "").strip()
            kp_id = str(raw.get("knowledge_point_id") or "").strip()
            try:
                difficulty = int(raw.get("difficulty", 1) or 1)
            except (TypeError, ValueError):
                difficulty = 1
            if not title or not kp_id:
                dropped += 1
                continue
            if not options or answer not in options or len(options) < 3:
                dropped += 1
                continue
            valid.append(
                {
                    "question_id": str(raw.get("question_id") or "").strip()
                    or f"GEN-{uuid.uuid4().hex[:10]}",
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": str(raw.get("knowledge_point_name") or kp_id),
                    "title": title,
                    "options": options,
                    "answer": answer,
                    "explanation": explanation or "（未提供解析，请以知识库为准）",
                    "difficulty": max(1, min(3, difficulty)),
                    "source": str(raw.get("source") or "工作流生成（本地校验通过）"),
                }
            )
        return valid, dropped

    def _goal_knowledge_list(self, goal: str) -> list[dict[str, Any]]:
        """诊断目标（competition/certification/daily）→ 目标覆盖的知识点列表。

        供工作流出题约束 knowledge_point_id（与 goal_graph 目标图谱一致）；
        未知目标时回退全部知识点。
        """
        goal_id = next(
            (
                gid
                for gid, key in self.PROJECT_GOAL_DIAGNOSIS.items()
                if key == goal
            ),
            "",
        )
        point_ids = (
            list(GOAL_GRAPH_GOALS[goal_id].get("knowledge_points", []))
            if goal_id in GOAL_GRAPH_GOALS
            else list(GRAPH_KNOWLEDGE_POINTS)
        )
        return [
            {
                "knowledge_point_id": point_id,
                "knowledge_point_name": GRAPH_KNOWLEDGE_POINTS[point_id][
                    "knowledge_point_name"
                ],
            }
            for point_id in point_ids
            if point_id in GRAPH_KNOWLEDGE_POINTS
        ]

    def _reuse_generated_questions(
        self, goal: str, weak_points: list[dict[str, Any]], target_size: int
    ) -> list[dict[str, Any]]:
        """复用最近已校验入库的生成题：目标知识点内、每知识点最多一题、薄弱点优先。

        生成题库随每次诊断沉淀，复用后不足部分再由工作流生成/本地取样。
        """
        goal_ids = {
            str(item.get("knowledge_point_id", "")).strip()
            for item in self._goal_knowledge_list(goal)
        }
        weak_ids = {
            str(item.get("knowledge_point_id", "")).strip()
            for item in weak_points
            if str(item.get("knowledge_point_id", "")).strip()
        }
        candidates = [
            item
            for item in self.domain.recent_generated_questions(limit=40)
            if str(item.get("knowledge_point_id", "")).strip() in goal_ids
        ]
        # 薄弱点知识点优先，其余保持入库时间倒序（recent 已倒序）
        candidates.sort(
            key=lambda item: 0
            if str(item.get("knowledge_point_id", "")).strip() in weak_ids
            else 1
        )
        reused: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            if len(reused) >= target_size:
                break
            kp_id = str(item.get("knowledge_point_id", "")).strip()
            if not kp_id or kp_id in seen:
                continue
            seen.add(kp_id)
            options = as_dict(item.get("options"))
            if not options:
                continue
            reused.append(
                {
                    "question_id": str(item.get("question_id", "")).strip(),
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": str(
                        item.get("knowledge_point_name") or kp_id
                    ),
                    "title": str(item.get("title", "")).strip(),
                    "options": options,
                    "answer": str(item.get("answer", "")).strip(),
                    "explanation": str(item.get("explanation", "")).strip(),
                    "difficulty": int(item.get("difficulty", 1) or 1),
                    "source": str(item.get("source") or "历史生成题复用（本地校验通过）"),
                }
            )
        return reused

    def _generate_diagnosis_questions(
        self, student_id: str, goal: str, weak_points: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str]:
        """生成式出题：复用已校验生成题 → 星辰工作流 → 本地校验 → 入库；失败回落本地取样。

        返回 (questions, provider)，provider ∈
        {"workflow_reuse", "workflow", "mock_bank", "local_fallback"}。
        """
        target_size = int(DIAGNOSIS_GOALS.get(goal, {}).get("size", 6))
        reused = self._reuse_generated_questions(goal, weak_points, target_size)
        if len(reused) >= target_size:
            return reused, "workflow_reuse"
        generated: list[dict[str, Any]] = []
        provider = "workflow"
        try:
            result = self.gateway.invoke_quiz_workflow(
                {
                    "student_id": student_id,
                    "goal": goal,
                    "weak_points": weak_points,
                    "knowledge_list": self._goal_knowledge_list(goal),
                }
            )
            provider = str(result.get("provider") or "workflow")
            generated, _dropped = self._validate_quiz_questions(
                as_list(result.get("questions"))
            )
        except Exception:
            generated = []
        if generated:
            try:
                self.domain.save_generated_questions(generated)
            except Exception:
                pass  # 入库失败不影响本轮使用
            existing_ids = {q["question_id"] for q in reused}
            for item in generated:
                if len(reused) >= target_size:
                    break
                if item["question_id"] in existing_ids:
                    continue
                reused.append(item)
            if len(reused) < target_size:
                existing_ids = {q["question_id"] for q in reused}
                for item in select_diagnosis_questions(goal):
                    if len(reused) >= target_size:
                        break
                    if item["id"] in existing_ids:
                        continue
                    reused.append(
                        {
                            "question_id": item["id"],
                            "knowledge_point_id": item["knowledge_point_id"],
                            "knowledge_point_name": item["knowledge_point_name"],
                            "title": item["title"],
                            "options": item["options"],
                            "answer": item["answer"],
                            "explanation": item["explanation"],
                            "difficulty": item["difficulty"],
                            "source": "本地题库补足（生成题不足目标题量）",
                        }
                    )
            return reused, provider
        picked = select_diagnosis_questions(goal)
        return [
            {
                "question_id": item["id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "title": item["title"],
                "options": item["options"],
                "answer": item["answer"],
                "explanation": item["explanation"],
                "difficulty": item["difficulty"],
                "source": "本地题库（工作流不可用/校验未通过时回落）",
            }
            for item in picked
        ], "local_fallback"

    def _require_project(self, student_id: str, project_id: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project or str(project.get("student_id", "")) != student_id:
            raise ApiError(404, "PROJECT_NOT_FOUND", "未找到该项目")
        return project

    @staticmethod
    def _project_diagnosis_state(state: dict[str, Any]) -> str:
        session = as_dict(state.get("diagnosis_session"))
        if not session:
            return "not_started"
        return "done" if session.get("done") else "in_progress"

    @staticmethod
    def _project_progress(path: dict[str, Any]) -> int:
        items = [item for item in as_list(path.get("items")) if isinstance(item, dict)]
        if not items:
            return 0
        total = sum(
            max(0, min(100, int(item.get("mastery", 0) or 0))) for item in items
        )
        return round(total / len(items))

    GOAL_ACTION_WORDS: tuple[str, ...] = (
        "学习", "学会", "掌握", "提升", "入门", "熟悉", "精通", "备战",
        "备考", "考取", "通过", "完成", "开发", "制作", "实现", "转行",
        "就业", "面试", "训练", "练习",
    )
    NON_LEARNING_ACTIONS: tuple[str, ...] = (
        "订机票", "订酒店", "点外卖", "买东西", "查天气", "播放音乐",
        "发短信", "打电话", "写情书", "买彩票",
    )
    VAGUE_GOAL_TEXTS: tuple[str, ...] = (
        "随便学点什么", "不知道学什么", "推荐学什么", "提升自己", "学习技能",
        "学点东西", "都可以", "随便", "学习编程", "学习英语", "学习设计",
    )

    @staticmethod
    def _goal_duration(text: str) -> dict[str, Any]:
        number_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        match = re.search(
            r"(?:在)?([0-9一二两三四五六七八九十]+)\s*(天|周|个?月|年)(?:内|之内)?",
            text,
        )
        if not match:
            return {}
        raw_number, raw_unit = match.groups()
        if raw_number.isdigit():
            amount = int(raw_number)
        elif raw_number == "十":
            amount = 10
        elif raw_number.startswith("十") and len(raw_number) == 2:
            amount = 10 + number_map.get(raw_number[1], 0)
        elif raw_number.endswith("十") and len(raw_number) == 2:
            amount = number_map.get(raw_number[0], 0) * 10
        else:
            amount = number_map.get(raw_number, 0)
        if amount <= 0:
            return {}
        unit_days = 1 if raw_unit == "天" else 7 if raw_unit == "周" else 30 if "月" in raw_unit else 365
        return {
            "duration_text": match.group(0),
            "estimated_days": min(3650, amount * unit_days),
        }

    @staticmethod
    def _goal_outcome(text: str) -> str:
        match = re.search(
            r"(?:并且|并能|并可|能够|独立|完成|通过|考取|拿到|做出|开发出|实现)"
            r"([^，。；]{2,48})",
            text,
        )
        if not match:
            match = re.search(r"(?:^|[，。；\s])能\s*([^，。；]{2,48})", text)
        outcome = match.group(1).strip() if match else ""
        return "" if outcome in {"大赛", "比赛", "竞赛", "认证", "考试", "证书"} else outcome

    @staticmethod
    def _goal_title(text: str, fallback: str) -> str:
        title = re.sub(
            r"^(?:我想|我要|我希望|希望|计划|准备|打算|目标是|想要)\s*",
            "",
            text.strip(),
        ).strip(" ，。；")
        if not title:
            title = fallback
        return title[:56] + ("…" if len(title) > 56 else "")

    def _open_goal_analysis(self, text: str) -> dict[str, Any]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if any(action in normalized for action in self.NON_LEARNING_ACTIONS):
            return {
                "matched": False,
                "reason": "outside_learning_scope",
                "clarification": "这看起来不是学习或能力提升目标。本工作台只处理学习、考证、竞赛、岗位能力和实训项目。",
            }
        if len(normalized) < 4 or normalized in self.VAGUE_GOAL_TEXTS:
            return {
                "matched": False,
                "reason": "goal_too_broad",
                "missing_fields": ["具体学习内容", "希望达到的成果或应用场景"],
                "clarification": (
                    "这个目标还太宽泛。请补充“具体学什么”和“最终想做到什么”，"
                    "例如：六周内掌握 Python 数据分析，并完成一份销售数据看板。"
                ),
            }
        has_action = any(word in normalized for word in self.GOAL_ACTION_WORDS)
        has_goal_frame = any(
            word in normalized
            for word in ("我想", "我要", "目标", "计划", "希望", "准备", "打算")
        )
        if not has_action and not has_goal_frame:
            return {
                "matched": False,
                "reason": "intent_unclear",
                "missing_fields": ["学习意图"],
                "clarification": (
                    f"我识别到了“{normalized}”，但还不能确定你是要学习它还是咨询它。"
                    "如果要建立项目，请说明希望达到的能力或成果。"
                ),
            }
        goal_type = "course"
        if any(word in normalized for word in ("大赛", "比赛", "竞赛", "备赛")):
            goal_type = "competition"
        elif any(
            word in normalized.lower()
            for word in (
                "认证", "证书", "考证", "考级", "考试", "1+x", "四级", "六级",
                "雅思", "托福", "软考", "教资", "计算机等级",
            )
        ):
            goal_type = "certification"
        elif any(word in normalized for word in ("岗位", "就业", "转行", "面试", "工作")):
            goal_type = "job"
        elif any(word in normalized for word in ("完成", "制作", "开发", "做出", "实现")):
            goal_type = "project"
        constraints = self._goal_duration(normalized)
        outcome = self._goal_outcome(normalized)
        if outcome:
            constraints["target_outcome"] = outcome
        return {
            "matched": True,
            "goal": {
                "goal_id": "GOAL-CUSTOM-" + uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12].upper(),
                "goal_name": self._goal_title(normalized, normalized),
                "goal_type": goal_type,
                "original_text": normalized,
                "constraints": constraints,
                "support_level": "planning_required",
                "planning_state": "pending_knowledge_mapping",
            },
        }

    @staticmethod
    def _graph_goal_matches_text(goal: dict[str, Any] | None, text: str) -> bool:
        if not goal:
            return False
        goal_id = str(goal.get("goal_id") or "")
        lowered = text.lower().replace(" ", "")
        java_signals = (
            "java", "面向对象", "成绩管理", "类与对象", "封装", "继承",
            "多态", "集合框架", "javaio",
        )
        has_java_context = any(signal in lowered for signal in java_signals)
        if goal_id == "GOAL-JAVA-001":
            return has_java_context
        if goal_id == "GOAL-JAVA-COMPETITION":
            return has_java_context or "世界职业院校技能大赛" in text
        if goal_id == "GOAL-JAVA-CERT":
            return has_java_context or "1+x" in lowered
        if goal_id == "GOAL-JAVA-DAILY":
            return has_java_context or text.strip() in {"日常技能提升", "Java 日常技能提升"}
        return goal_id in GOAL_GRAPH_GOALS

    @staticmethod
    def _custom_goal_nodes(
        text: str, goal_type: str, target_outcome: str
    ) -> list[tuple[str, str]]:
        lowered = text.lower()
        if "python" in lowered and any(word in lowered for word in ("数据", "pandas", "分析", "看板")):
            return [
                ("Python 数据处理基础", "code"),
                ("NumPy 数组与数值计算", "code"),
                ("Pandas 数据读取与清洗", "code"),
                ("业务指标与探索性分析", "conceptual"),
                ("数据可视化与图表表达", "practice"),
                (target_outcome or "数据分析看板综合实战", "project"),
            ]
        if any(word in lowered for word in ("英语", "四级", "六级", "雅思", "托福")):
            return [
                ("考试结构与基线诊断", "conceptual"),
                ("高频词汇与核心语法", "conceptual"),
                ("听力理解与信息定位", "practice"),
                ("阅读理解与篇章分析", "practice"),
                ("写作与翻译表达", "practice"),
                (target_outcome or "全真模拟与错题复盘", "assessment"),
            ]
        if any(word in lowered for word in ("html", "css", "javascript", "前端", "网页", "web")):
            return [
                ("HTML 页面结构", "code"),
                ("CSS 布局与响应式设计", "code"),
                ("JavaScript 交互基础", "code"),
                ("组件化与状态管理", "conceptual"),
                ("接口联调与错误处理", "practice"),
                (target_outcome or "Web 项目综合实战", "project"),
            ]
        if any(word in lowered for word in ("短视频", "视频创作", "视频剪辑", "微电影")):
            return [
                ("赛项规程与评分标准", "conceptual"),
                ("选题策划与受众分析", "conceptual"),
                ("脚本、分镜与拍摄计划", "practice"),
                ("画面拍摄与声音采集", "practice"),
                ("剪辑节奏、包装与版权规范", "practice"),
                (target_outcome or "参赛作品制作与模拟评审", "project"),
            ]
        if "pmp" in lowered or "项目管理" in lowered:
            return [
                ("PMP 考纲、题型与报考要求", "conceptual"),
                ("项目管理原则与绩效域", "conceptual"),
                ("预测型项目管理方法", "conceptual"),
                ("敏捷与混合型项目管理", "conceptual"),
                ("情境题决策与错题归因", "practice"),
                (target_outcome or "PMP 全真模拟与复盘", "assessment"),
            ]
        if any(word in lowered for word in ("python", "java", "c++", "编程", "开发", "代码")):
            subject = "目标编程技术"
            for candidate in ("Python", "Java", "C++", "JavaScript"):
                if candidate.lower() in lowered:
                    subject = candidate
                    break
            return [
                (f"{subject} 开发环境与基础语法", "code"),
                (f"{subject} 数据结构与程序控制", "code"),
                (f"{subject} 函数、模块与代码组织", "code"),
                ("调试、测试与异常处理", "practice"),
                ("典型任务分步练习", "practice"),
                (target_outcome or f"{subject} 综合项目", "project"),
            ]
        if goal_type == "certification":
            return [
                ("考试范围与能力要求", "conceptual"),
                ("基础知识体系", "conceptual"),
                ("重点模块专项学习", "conceptual"),
                ("典型题型与解题方法", "practice"),
                ("薄弱项专项训练", "practice"),
                (target_outcome or "模拟考试与复盘", "assessment"),
            ]
        if any(word in lowered for word in ("设计", "绘画", "摄影", "剪辑", "建模", "ui", "海报")):
            return [
                ("目标作品与评价标准", "conceptual"),
                ("基础工具与操作规范", "practice"),
                ("构图、色彩与视觉表达", "conceptual"),
                ("案例拆解与临摹练习", "practice"),
                ("独立作品迭代", "project"),
                (target_outcome or "作品集整理与评审", "assessment"),
            ]
        topic = re.sub(
            r"^(?:我想|我要|我希望|希望|计划|准备|打算|目标是|想要|学习|掌握|备战|备考|通过)\s*",
            "",
            text,
        ).strip(" ，。；")
        topic = re.split(
            r"(?:并且|并能|并可|并完成|并制作|并开发|并实现|并做出)",
            topic,
            maxsplit=1,
        )[0].strip(" ，。；")[:24]
        topic = topic or "目标领域"
        if goal_type in {"project", "job"}:
            return [
                (f"{topic}任务要求与验收标准", "conceptual"),
                (f"{topic}前置知识与工具准备", "conceptual"),
                (f"{topic}核心方法与关键流程", "practice"),
                (f"{topic}分步任务训练", "practice"),
                (target_outcome or "综合任务实现", "project"),
                (f"{topic}测试、复盘与成果交付", "assessment"),
            ]
        return [
            (f"{topic}目标拆解与验收标准", "conceptual"),
            (f"{topic}基础概念与术语", "conceptual"),
            (f"{topic}核心原理与方法", "conceptual"),
            (f"{topic}典型案例分步练习", "practice"),
            (target_outcome or f"{topic}综合应用任务", "project"),
            (f"{topic}成果检验与复盘", "assessment"),
        ]

    def _build_custom_learning_path(
        self, goal_id: str, goal_name: str, goal_type: str, text: str, constraints: dict[str, Any]
    ) -> dict[str, Any]:
        nodes = self._custom_goal_nodes(
            text,
            goal_type,
            str(constraints.get("target_outcome") or ""),
        )
        items = []
        previous_id = ""
        for index, (name, knowledge_type) in enumerate(nodes, start=1):
            point_id = "KN-CUSTOM-" + uuid.uuid5(
                uuid.NAMESPACE_URL, f"{goal_id}:{index}:{name}"
            ).hex[:12].upper()
            item = {
                "knowledge_point_id": point_id,
                "knowledge_point_name": name,
                "knowledge_type": knowledge_type,
                "mastery": 0,
                "status": "current" if index == 1 else "pending",
                "recommended_order": index,
                "goal_id": goal_id,
                "source_status": "candidate",
            }
            if previous_id:
                item["prerequisites"] = [previous_id]
            items.append(item)
            previous_id = point_id
        return {
            "goal_id": goal_id,
            "goal_name": goal_name,
            "items": items,
            "progress": 0,
            "planning_state": "candidate_ready",
            "path_basis": "目标语义拆解生成；讲解与测评仍需来源校验",
        }

    def create_project(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """创建项目：口语目标 → 归一化（图谱/关键词）→ 生成路径 → 入库。

        无法归一化时返回 needs_clarification，供对话澄清后重试。
        """
        student_id = str(incoming.get("student_id", "")).strip()
        text = str(incoming.get("text", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        if not text:
            raise ApiError(400, "MISSING_GOAL_TEXT", "请先输入你的学习目标")

        goal = resolve_learning_goal({"goal_name": text})
        if goal and not self._graph_goal_matches_text(goal, text):
            goal = None
        if not goal:
            keyword_match = self._match_goal_keywords(text)
            keyword_goal = as_dict(keyword_match.get("goal"))
            if keyword_match.get("matched") and self._graph_goal_matches_text(
                keyword_goal, text
            ):
                goal = keyword_goal
        if not goal:
            open_goal = self._open_goal_analysis(text)
            if not open_goal.get("matched"):
                return {
                    "status": "needs_clarification",
                    "text": text,
                    "clarification": open_goal.get("clarification", "请补充更具体的学习目标。"),
                    "missing_fields": open_goal.get("missing_fields", []),
                    "reason": open_goal.get("reason", "goal_unclear"),
                }
            goal = as_dict(open_goal.get("goal"))

        goal_id = str(goal["goal_id"])
        canonical_goal_name = str(goal.get("goal_name") or goal_id)
        is_supported_goal = goal_id in GOAL_GRAPH_GOALS
        goal_name = str(incoming.get("goal_name") or "").strip() or self._goal_title(
            text, canonical_goal_name
        )
        constraints = dict(as_dict(goal.get("constraints")))
        constraints.update(self._goal_duration(text))
        outcome = self._goal_outcome(text)
        if outcome:
            constraints["target_outcome"] = outcome
        constraints.update(as_dict(incoming.get("goal_constraints")))
        if is_supported_goal:
            learning_path = build_learning_path(goal_id)
            learning_path["goal_name"] = goal_name
            planning_state = "ready"
            support_level = "validated_graph"
        else:
            learning_path = self._build_custom_learning_path(
                goal_id,
                goal_name,
                str(goal.get("goal_type") or "course"),
                text,
                constraints or as_dict(goal.get("constraints")),
            )
            planning_state = "ready"
            support_level = "generated_scaffold"
        state: dict[str, Any] = {
            "goal": {
                "goal_id": goal_id,
                "goal_name": goal_name,
                "goal_type": str(goal.get("goal_type") or "course"),
                "canonical_goal_name": canonical_goal_name if is_supported_goal else "",
                "original_text": text,
                "constraints": constraints or as_dict(goal.get("constraints")),
            },
            "learning_path": learning_path,
            "planning_state": planning_state,
            "support_level": support_level,
            "assessment_state": "ready" if is_supported_goal else "question_sources_pending",
            "diagnosis_session": None,
            "assessment_session": None,
            "weak_points": [],
            "learner_preferences": {},
            "learner_self_reports": [],
        }
        daily_minutes = int(constraints.get("daily_minutes", 0) or 0)
        if daily_minutes:
            state["learner_preferences"]["daily_minutes"] = max(
                5, min(daily_minutes, 720)
            )
        current_level = str(constraints.get("current_level") or "").strip()
        if current_level:
            state["learner_self_reports"].append({
                "type": "goal_intake_self_report",
                "claim": current_level,
                "message": str(incoming.get("intake_text") or text),
                "verification_state": "unverified",
                "created_at": utc_now(),
            })
        project_id = self.store.create_project(
            student_id, goal_id, goal_name, "created", state
        )
        return {
            "status": "ok",
            "project": self._project_payload(project_id, goal_name, "created", state),
        }

    @staticmethod
    def _project_payload(
        project_id: str,
        goal_name: str,
        status: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "goal_name": goal_name,
            "status": status,
            "diagnosis_state": LearningApplication._project_diagnosis_state(state),
            "planning_state": str(state.get("planning_state") or "ready"),
            "support_level": str(state.get("support_level") or "validated_graph"),
            "assessment_state": str(state.get("assessment_state") or "ready"),
            "goal_type": str(as_dict(state.get("goal")).get("goal_type") or "course"),
            "goal_constraints": as_dict(as_dict(state.get("goal")).get("constraints")),
            "weak_point_count": len(as_list(state.get("weak_points"))),
            "progress": LearningApplication._project_progress(
                as_dict(state.get("learning_path"))
            ),
        }

    def list_projects(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        projects = [
            self._project_payload(
                project["project_id"],
                str(project["goal_name"]),
                str(project["status"]),
                as_dict(project["state"]),
            )
            for project in self.store.list_projects(student_id)
        ]
        return {"status": "ok", "projects": projects}

    def get_project(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        return {
            "status": "ok",
            "project": {
                "project_id": project["project_id"],
                "goal_id": project["goal_id"],
                "goal_name": project["goal_name"],
                "goal_type": str(as_dict(state.get("goal")).get("goal_type") or ""),
                "original_goal_text": str(as_dict(state.get("goal")).get("original_text") or ""),
                "goal_constraints": as_dict(as_dict(state.get("goal")).get("constraints")),
                "planning_state": str(state.get("planning_state") or "ready"),
                "support_level": str(state.get("support_level") or "validated_graph"),
                "assessment_state": str(state.get("assessment_state") or "ready"),
                "status": project["status"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
                "diagnosis_state": self._project_diagnosis_state(state),
                "learning_path": state.get("learning_path", {}),
                "weak_points": as_list(state.get("weak_points")),
                "last_assessment_summary": as_dict(
                    state.get("last_assessment_summary")
                ),
                "learner_preferences": as_dict(state.get("learner_preferences")),
                "learner_self_reports": as_list(state.get("learner_self_reports")),
            },
        }

    def project_messages(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id") or "").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        self._require_project(student_id, project_id)
        return {
            "status": "ok",
            "project_id": project_id,
            "messages": self.store.list_project_messages(project_id, student_id),
        }

    def _save_project_conversation_turn(
        self,
        student_id: str,
        project_id: str,
        message: str,
        answer: str,
        action: str,
    ) -> None:
        self._require_project(student_id, project_id)
        self.store.add_project_message(project_id, student_id, "user", message, "user_input")
        if answer:
            self.store.add_project_message(project_id, student_id, "assistant", answer, action)

    def agent_turn(self, incoming: dict[str, Any]) -> dict[str, Any]:
        result = self._agent_turn_core(incoming)
        student_id = str(incoming.get("student_id") or "").strip()
        message = str(incoming.get("message") or incoming.get("text") or "").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        result_project = as_dict(result.get("project"))
        project_id = str(result_project.get("project_id") or project_id).strip()
        if student_id and message and project_id:
            self._save_project_conversation_turn(
                student_id,
                project_id,
                message,
                str(result.get("answer") or result.get("message") or "").strip(),
                str(result.get("action") or "reply"),
            )
        return result

    def _agent_turn_core(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """Tutor Agent 统一入口：理解意图并编排项目、测评、路径、讲解与问答。"""
        student_id = str(incoming.get("student_id") or "").strip()
        message = str(incoming.get("message") or incoming.get("text") or "").strip()
        session_id = str(incoming.get("session_id") or "agent-main").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        if not message:
            raise ApiError(400, "MISSING_MESSAGE", "请输入学习目标或问题")

        project = self._agent_project(student_id, project_id)
        goal_draft = (
            self.store.get_agent_goal_draft(student_id, session_id) if not project else {}
        )
        if goal_draft:
            continued = self._continue_goal_draft(
                student_id, session_id, message, goal_draft
            )
            if continued:
                return continued
        intent = self._classify_agent_intent(message, project)

        if intent == "create_project":
            if not project and self._goal_needs_outcome_clarification(message):
                return self._start_goal_draft(student_id, session_id, message)
            created = self.create_project({"student_id": student_id, "text": message})
            if created.get("status") != "ok":
                return {
                    "status": "needs_clarification",
                    "intent": "clarify_goal",
                    "action": "ask_clarification",
                    "message": created.get("clarification", "请补充更具体的学习目标。"),
                    "clarify_options": self._goal_clarify_options(),
                }
            return self._agent_project_created_response(created, message)

        if intent in {"start_assessment", "show_path", "open_lesson"}:
            project = project or self._single_recent_project(student_id)
            if not project:
                projects = self.store.list_projects(student_id)
                if projects:
                    return self._project_choice_response(message, projects)
                return {
                    "status": "needs_clarification",
                    "intent": "select_project",
                    "action": "ask_clarification",
                    "message": "还没有可操作的学习项目，请先告诉我你想达成什么目标。",
                    "clarify_options": self._goal_clarify_options(),
                }

        if intent == "start_assessment":
            assessment = self.project_diagnosis_start(
                {"student_id": student_id, "project_id": project["project_id"]}
            )
            project_payload = self._project_payload(
                project["project_id"],
                str(project["goal_name"]),
                "diagnosis",
                as_dict(self.store.get_project(project["project_id"])["state"]),
            )
            return {
                "status": "ok",
                "intent": "start_assessment",
                "action": "show_assessment",
                "message": f"已为“{project['goal_name']}”准备好 {assessment['total']} 道诊断题。",
                "project": project_payload,
                "artifact": {"type": "assessment", "data": assessment},
                "next_interaction": {"type": "assessment_answer"},
            }

        if intent == "show_path":
            detail = self.get_project(
                {"student_id": student_id, "project_id": project["project_id"]}
            )["project"]
            path = as_dict(detail.get("learning_path"))
            return {
                "status": "ok",
                "intent": "show_path",
                "action": "show_path",
                "message": (
                    f"“{detail['goal_name']}”当前总体进度为 "
                    f"{self._project_progress(path)}%。路径已在左侧展开，可点击章节学习。"
                ),
                "project": self._project_payload(
                    detail["project_id"], detail["goal_name"], detail["status"],
                    as_dict(self.store.get_project(detail["project_id"])["state"]),
                ),
                "artifact": {"type": "learning_path", "data": path},
            }

        if intent == "update_learning_context":
            return self._update_project_learning_context(
                student_id, project, message, as_dict(incoming.get("workspace_context"))
            )

        if intent == "open_lesson":
            state = as_dict(project.get("state"))
            target = self._agent_lesson_target(message, state)
            if not target:
                options = [
                    {
                        "id": str(item.get("knowledge_point_id") or ""),
                        "label": str(item.get("knowledge_point_name") or "学习章节"),
                        "prompt": f"学习{item.get('knowledge_point_name', '')}",
                    }
                    for item in as_list(as_dict(state.get("learning_path")).get("items"))[:4]
                    if isinstance(item, dict)
                ]
                return {
                    "status": "needs_clarification",
                    "intent": "select_lesson",
                    "action": "ask_clarification",
                    "message": "你想打开哪一个章节？",
                    "clarify_options": options,
                }
            lesson = self.project_explain(
                {
                    "student_id": student_id,
                    "project_id": project["project_id"],
                    "knowledge_point_id": target["knowledge_point_id"],
                }
            )
            return {
                "status": "ok",
                "intent": "open_lesson",
                "action": "open_lesson",
                "message": f"已在中间学习区打开“{target['knowledge_point_name']}”。",
                "project": self._project_payload(
                    project["project_id"],
                    str(project["goal_name"]),
                    str(project["status"]),
                    as_dict(self.store.get_project(project["project_id"])["state"]),
                ),
                "knowledge_point_id": target["knowledge_point_id"],
                "knowledge_point_name": target["knowledge_point_name"],
                "artifact": {"type": "lesson", "data": lesson},
            }

        if intent in {"knowledge_question", "general_assistant"}:
            answer = self.chat(
                {
                    "student_id": student_id,
                    "session_id": session_id,
                    "project_id": str(project.get("project_id") or "") if project else "",
                    "message": message,
                    "workspace_context": as_dict(incoming.get("workspace_context")),
                    "use_knowledge_base": incoming.get("use_knowledge_base", True),
                    "allow_web_search": incoming.get("allow_web_search", True),
                    "force_web_search": incoming.get("force_web_search", False),
                    "assistant_mode": (
                        "general" if intent == "general_assistant" else "education"
                    ),
                    "persist_history": False,
                }
            )
            return {
                **answer,
                "intent": intent,
                "action": (
                    "ask_clarification"
                    if answer.get("status") == "needs_clarification"
                    else "reply"
                ),
                "message": answer.get("message") or answer.get("answer") or "",
                "artifact": {"type": "answer", "data": answer},
            }

        return {
            "status": "needs_clarification",
            "intent": "clarify_intent",
            "action": "ask_clarification",
            "message": (
                "我还不能确定你是要建立学习目标、咨询知识点，还是操作当前项目。"
                "请选一个方向，或把目标说得更具体一些。"
            ),
            "clarify_options": self._agent_clarify_options(project),
        }

    def _classify_agent_intent(
        self, message: str, project: dict[str, Any] | None = None
    ) -> str:
        lowered = message.lower().strip()
        question_words = (
            "什么", "哪些", "怎么", "如何", "为什么", "区别", "是否", "能否",
            "吗", "么", "？", "?", "报错", "错误", "用法", "介绍", "解释",
        )
        is_question = any(word in lowered for word in question_words)
        goal_words = (
            "我想", "我要", "目标", "计划", "备战", "准备考", "想考", "系统掌握",
            "完成实训", "完成 java", "提升技能", "学习项目",
        )
        assessment_words = ("开始测评", "能力测评", "重新测评", "做测评", "测一下", "诊断一下")
        path_words = ("查看学习路径", "学习路径", "课程安排", "学习计划", "下一步学什么")
        lesson_words = ("开始学习", "继续学习", "打开课程", "打开章节", "学习章节", "下一课")
        general_request_words = (
            "上网搜索", "联网搜索", "网上查", "搜索一下", "帮我查", "查找资料",
            "总结一下", "帮我总结", "对比一下", "翻译一下", "帮我翻译", "翻译成",
            "帮我润色", "帮我改写", "帮我写", "写一份", "列出", "提取", "整理",
        )
        education_request_words = ("帮我解释", "解释一下")
        open_goal = self._open_goal_analysis(message)

        if any(word in lowered for word in general_request_words):
            return "general_assistant"
        relevant_knowledge = self._relevant_knowledge_items(message, limit=1)
        if any(word in lowered for word in education_request_words):
            return (
                "knowledge_question"
                if project or relevant_knowledge
                else "general_assistant"
            )
        if any(word in lowered for word in assessment_words) and not is_question:
            return "start_assessment"
        if any(word in lowered for word in path_words):
            return "show_path"
        if any(word in lowered for word in lesson_words):
            return "open_lesson"
        if project and self._is_learning_context_update(message):
            return "update_learning_context"
        learning_goal_hint = any(
            word in lowered
            for word in (
                "学习", "学会", "想学", "掌握", "备考", "考试", "考证", "竞赛",
                "实训", "课程", "岗位能力", "提升技能",
            )
        )
        if any(word in lowered for word in goal_words) and learning_goal_hint and not is_question:
            return "create_project"
        if open_goal.get("reason") == "goal_too_broad":
            return "create_project"
        if open_goal.get("reason") == "outside_learning_scope":
            return "general_assistant"
        if is_question:
            if project or learning_goal_hint or relevant_knowledge:
                return "knowledge_question"
            return "general_assistant"
        graph_goal = resolve_learning_goal({"goal_name": message})
        keyword_goal = as_dict(self._match_goal_keywords(message).get("goal"))
        if self._graph_goal_matches_text(graph_goal, message) or self._graph_goal_matches_text(
            keyword_goal, message
        ):
            return "create_project"
        if open_goal.get("matched"):
            if project and "学习" in lowered and self.domain.search_knowledge(query=message, limit=1):
                return "open_lesson"
            return "create_project"
        if not project and "学习" in lowered:
            return "create_project"
        if relevant_knowledge:
            return "knowledge_question"
        if project:
            return "knowledge_question"
        if lowered in {"随便来点", "随便聊聊", "聊聊", "随便"}:
            return "clarify_intent"
        if len(message.strip()) > 4:
            return "general_assistant"
        return "clarify_intent"

    def _relevant_knowledge_items(
        self, message: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        items = self.domain.search_knowledge(query=message, limit=max(limit, 3))
        lowered = str(message or "").lower()
        relevant = []
        for item in items:
            if not isinstance(item, dict):
                continue
            keyword_tokens = re.findall(
                r"[a-zA-Z][a-zA-Z0-9+#.-]*|[\u4e00-\u9fff]{2,}",
                " ".join(
                    str(item.get(key) or "")
                    for key in ("title", "keywords", "knowledge_point_name")
                ).lower(),
            )
            if any(token in lowered for token in keyword_tokens if len(token) >= 2):
                relevant.append(item)
            if len(relevant) >= limit:
                break
        return relevant

    def _agent_project(self, student_id: str, project_id: str) -> dict[str, Any] | None:
        if not project_id:
            return None
        return self._require_project(student_id, project_id)

    def _agent_project_created_response(
        self, created: dict[str, Any], fallback_message: str
    ) -> dict[str, Any]:
        new_project = as_dict(created.get("project"))
        planning_required = new_project.get("planning_state") != "ready"
        assessment_ready = new_project.get("assessment_state") == "ready"
        constraints = as_dict(new_project.get("goal_constraints"))
        intake_notes = []
        if constraints.get("current_level"):
            intake_notes.append("当前基础已按自报记录，等待测评验证")
        if constraints.get("daily_minutes"):
            intake_notes.append(f"每日可学习 {constraints['daily_minutes']} 分钟")
        intake_text = " " + "，".join(intake_notes) + "。" if intake_notes else ""
        return {
            "status": "ok",
            "intent": "create_project",
            "action": "project_created",
            "message": (
                f"已把“{new_project.get('goal_name', fallback_message)}”创建为学习项目。"
                + (
                    "这个目标正在生成候选知识结构，完成后再开放学习与测评。"
                    if planning_required
                    else (
                        "已按目标生成候选学习路径。下一步建议先做一次能力测评，我会据此调整学习顺序。"
                        if assessment_ready
                        else "已生成候选学习路径；当前还缺少经过校验的对应题源，可先查看路径。"
                    )
                )
                + intake_text
            ),
            "project": new_project,
            "next_interaction": (
                {
                    "type": "status",
                    "options": [],
                    "message": "等待知识结构校验",
                }
                if planning_required
                else {
                    "type": "choice" if assessment_ready else "status",
                    "options": (
                        [
                            {"id": "start_assessment", "label": "开始能力测评", "prompt": "开始能力测评"},
                            {"id": "show_path", "label": "先看学习路径", "prompt": "查看学习路径"},
                        ]
                        if assessment_ready
                        else [
                            {"id": "show_path", "label": "查看候选路径", "prompt": "查看学习路径"},
                        ]
                    ),
                    "message": "题源校验中" if not assessment_ready else "",
                }
            ),
        }

    def _goal_needs_outcome_clarification(self, message: str) -> bool:
        text = re.sub(r"\s+", " ", str(message or "")).strip()
        if not text or self._goal_outcome(text):
            return False
        goal = resolve_learning_goal({"goal_name": text})
        if self._graph_goal_matches_text(goal, text):
            return False
        lowered = text.lower()
        if any(word in lowered for word in ("大赛", "比赛", "竞赛", "备考", "认证", "证书", "考试", "考级", "四级", "六级", "雅思", "托福", "面试")):
            return False
        broad_subjects = (
            "python", "数据分析", "英语", "前端", "web", "网页", "javascript",
            "设计", "摄影", "剪辑", "人工智能", "ai", "项目管理", "编程",
        )
        has_subject = any(subject in lowered for subject in broad_subjects)
        has_specific_outcome = any(
            word in lowered
            for word in (
                "看板", "系统", "网站", "作品", "应用", "程序", "自动化", "报告",
                "岗位", "就业", "转行", "实训", "参赛作品", "口语交流",
            )
        )
        return has_subject and not has_specific_outcome

    @staticmethod
    def _goal_intake_daily_minutes(text: str) -> int:
        if re.search(r"(?:每天|每日)[^，。；]{0,8}?半\s*(?:个)?小时", text):
            return 30
        match = re.search(
            r"(?:每天|每日)[^，。；]{0,8}?(\d+(?:\.\d+)?|一|两|二)\s*(分钟|个?小时)",
            text,
        )
        if not match:
            return 0
        raw_amount = match.group(1)
        amount = {"一": 1.0, "两": 2.0, "二": 2.0}.get(raw_amount, 0.0)
        if not amount:
            amount = float(raw_amount)
        minutes = round(amount * 60) if "小时" in match.group(2) else round(amount)
        return max(5, min(minutes, 720))

    @staticmethod
    def _goal_intake_current_level(text: str) -> str:
        lowered = str(text or "").lower()
        if any(word in lowered for word in ("零基础", "没学过", "完全不会", "没有基础")):
            return "zero_foundation"
        if any(word in lowered for word in ("有一点基础", "有些基础", "学过一点", "入门基础")):
            return "basic"
        if any(word in lowered for word in ("有基础", "已经学过", "学过", "熟悉基础")):
            return "experienced"
        return ""

    @staticmethod
    def _goal_follow_up_outcome(message: str) -> str:
        text = re.sub(r"\s+", " ", str(message or "")).strip(" ，。；")
        if not text:
            return ""
        outcome = LearningApplication._goal_outcome(text)
        if outcome:
            return outcome
        cleaned = re.sub(
            r"^(?:我想|想要|想做|希望|最终想|目标是|主要是|为了|用来|用于|拿来|可以|能够|能|做|学习)\s*",
            "",
            text,
        ).strip(" ，。；")
        cleaned = re.sub(
            r"(?:我)?(?:是)?(?:零基础|没有基础|有一点基础|有些基础|有基础|学过一点|已经学过)[，。；\s]*",
            "",
            cleaned,
        ).strip(" ，。；")
        cleaned = re.sub(
            r"(?:每天|每日)[^，。；]{0,12}(?:分钟|个?小时)[，。；\s]*",
            "",
            cleaned,
        ).strip(" ，。；")
        cleaned = re.sub(
            r"(?:在)?[0-9一二两三四五六七八九十]+\s*(?:天|周|个?月|年)(?:内|之内)?[，。；\s]*",
            "",
            cleaned,
        ).strip(" ，。；")
        if cleaned in {"没有", "没有特定目标", "不知道", "都可以", "随便"}:
            return ""
        return cleaned[:64] if len(cleaned) >= 2 else ""

    def _goal_draft_options(self, topic: str) -> list[dict[str, str]]:
        lowered = topic.lower()
        if "python" in lowered:
            options = (
                ("data", "数据分析", "我想用 Python 完成销售数据分析看板"),
                ("web", "Web 开发", "我想用 Python 开发一个可部署的 Web 应用"),
                ("automation", "办公自动化", "我想用 Python 自动处理 Excel 和日常文件"),
            )
        elif any(word in lowered for word in ("英语", "english")):
            options = (
                ("exam", "通过考试", "我想通过大学英语四级考试"),
                ("work", "职场沟通", "我想能进行英文邮件和会议沟通"),
                ("travel", "旅行交流", "我想能完成出国旅行中的日常英语交流"),
            )
        elif any(word in lowered for word in ("前端", "web", "网页", "javascript")):
            options = (
                ("site", "完成网站", "我想独立完成一个响应式网站"),
                ("job", "求职面试", "我想达到前端初级岗位和面试要求"),
                ("app", "开发应用", "我想开发一个可交互的 Web 应用"),
            )
        else:
            options = (
                ("project", "完成项目", "我想完成一个可以验收的实际项目"),
                ("exam", "通过考试", "我想达到相关考试或认证要求"),
                ("job", "岗位应用", "我想把它用于目标岗位的实际任务"),
            )
        return [
            {"id": option_id, "label": label, "prompt": prompt}
            for option_id, label, prompt in options
        ]

    def _start_goal_draft(
        self, student_id: str, session_id: str, message: str
    ) -> dict[str, Any]:
        constraints = dict(self._goal_duration(message))
        daily_minutes = self._goal_intake_daily_minutes(message)
        current_level = self._goal_intake_current_level(message)
        if daily_minutes:
            constraints["daily_minutes"] = daily_minutes
        if current_level:
            constraints["current_level"] = current_level
        draft = {
            "topic_text": message,
            "constraints": constraints,
            "intake_messages": [message],
            "missing_fields": ["target_outcome"],
        }
        self.store.save_agent_goal_draft(student_id, session_id, draft)
        return {
            "status": "needs_clarification",
            "intent": "clarify_goal",
            "action": "ask_clarification",
            "message": (
                "我已经识别到你想学习的主题，但还缺少可验收的目标。"
                "你最终希望用它完成什么、通过什么考试，或解决什么实际任务？"
            ),
            "missing_fields": ["target_outcome"],
            "clarify_options": self._goal_draft_options(message),
        }

    def _continue_goal_draft(
        self,
        student_id: str,
        session_id: str,
        message: str,
        draft: dict[str, Any],
    ) -> dict[str, Any] | None:
        lowered = message.lower().strip()
        if lowered in {"取消", "取消创建", "重新开始", "换个目标"}:
            self.store.delete_agent_goal_draft(student_id, session_id)
            return {
                "status": "ok",
                "intent": "cancel_goal_draft",
                "action": "reply",
                "answer": "已取消刚才的目标草稿。你可以重新告诉我想学习什么。",
                "ai_generated": False,
                "sources": [],
            }
        assistant_request_words = (
            "上网搜索", "联网搜索", "网上查", "搜索一下", "帮我查", "查找资料",
            "总结一下", "帮我总结", "对比一下", "帮我解释", "解释一下", "翻译一下", "帮我润色",
        )
        if any(mark in message for mark in ("？", "?")) or any(
            lowered.startswith(word)
            for word in ("什么", "怎么", "如何", "为什么", "能不能", "可以吗")
        ) or any(word in lowered for word in assistant_request_words):
            return None
        constraints = as_dict(draft.get("constraints"))
        constraints.update(self._goal_duration(message))
        daily_minutes = self._goal_intake_daily_minutes(message)
        current_level = self._goal_intake_current_level(message)
        if daily_minutes:
            constraints["daily_minutes"] = daily_minutes
        if current_level:
            constraints["current_level"] = current_level
        outcome = self._goal_follow_up_outcome(message)
        intake_messages = [
            str(item) for item in as_list(draft.get("intake_messages")) if str(item).strip()
        ]
        intake_messages.append(message)
        if not outcome:
            updated = {
                **draft,
                "constraints": constraints,
                "intake_messages": intake_messages[-8:],
                "missing_fields": ["target_outcome"],
            }
            self.store.save_agent_goal_draft(student_id, session_id, updated)
            return {
                "status": "needs_clarification",
                "intent": "clarify_goal",
                "action": "ask_clarification",
                "message": (
                    "这些学习条件我已经记下了，但仍无法判断完成标准。"
                    "请补充一个具体结果，例如“完成销售数据看板”“通过四级”或“独立做出网站”。"
                ),
                "missing_fields": ["target_outcome"],
                "clarify_options": self._goal_draft_options(str(draft.get("topic_text") or "")),
            }
        constraints["target_outcome"] = outcome
        if not constraints.get("estimated_days"):
            constraints.update({
                "duration_text": "默认 6 周（可调整）",
                "estimated_days": 42,
                "duration_assumption": True,
            })
        topic_text = str(draft.get("topic_text") or "").strip()
        combined_text = f"{topic_text}，并完成{outcome}"
        topic_title = re.split(r"[，。；]", topic_text, maxsplit=1)[0].strip()
        goal_name = self._goal_title(
            f"{topic_title}，并完成{outcome}", combined_text
        )
        created = self.create_project({
            "student_id": student_id,
            "text": combined_text,
            "goal_name": goal_name,
            "goal_constraints": constraints,
            "intake_text": "；".join(intake_messages[-8:]),
        })
        if created.get("status") != "ok":
            return None
        project_id = str(as_dict(created.get("project")).get("project_id") or "")
        if project_id:
            for index, intake_message in enumerate(intake_messages[:-1]):
                self.store.add_project_message(
                    project_id, student_id, "user", intake_message, "goal_intake"
                )
                self.store.add_project_message(
                    project_id,
                    student_id,
                    "assistant",
                    (
                        "我已经识别到学习主题，还需要补充一个可验收的成果或应用场景。"
                        if index == 0
                        else "已记录这些学习条件，但仍需要明确最终成果。"
                    ),
                    "ask_goal_clarification",
                )
        self.store.delete_agent_goal_draft(student_id, session_id)
        return self._agent_project_created_response(created, combined_text)

    def _single_recent_project(self, student_id: str) -> dict[str, Any] | None:
        projects = self.store.list_projects(student_id)
        return projects[0] if len(projects) == 1 else None

    @staticmethod
    def _goal_clarify_options() -> list[dict[str, str]]:
        return [
            {"id": "course", "label": "Java 实训", "prompt": "两个月内掌握 Java 面向对象并完成成绩管理实训"},
            {"id": "data", "label": "Python 数据分析", "prompt": "六周内掌握 Python 数据分析并完成销售数据看板"},
            {"id": "certification", "label": "英语四级", "prompt": "三个月内通过大学英语四级考试"},
        ]

    def _agent_clarify_options(
        self, project: dict[str, Any] | None
    ) -> list[dict[str, str]]:
        if not project:
            return self._goal_clarify_options()
        return [
            {"id": "assessment", "label": "开始能力测评", "prompt": "开始能力测评"},
            {"id": "path", "label": "查看学习路径", "prompt": "查看学习路径"},
            {"id": "lesson", "label": "继续学习", "prompt": "继续学习"},
        ]

    @staticmethod
    def _is_learning_context_update(message: str) -> bool:
        lowered = str(message or "").lower()
        direct_signals = (
            "每天", "每周", "只能学", "有时间", "没时间", "学习时间", "学习时长",
            "太难", "太简单", "看不懂", "跟不上", "想先学", "先跳过", "从第",
            "喜欢案例", "先看案例", "案例优先", "多举例", "讲慢", "讲快", "详细一点", "简单一点",
        )
        if any(signal in lowered for signal in direct_signals):
            return True
        self_report_patterns = (
            r"(?:我|本人)[^，。；？?]{0,16}(?:已经会|会了|学过|没学过|不会|不太会|有基础|零基础)",
            r"(?:这个|这部分|这章)[^，。；？?]{0,8}(?:我会|我不会|学过|没学过)",
        )
        return any(re.search(pattern, lowered) for pattern in self_report_patterns)

    def _project_path_matches(
        self, message: str, state: dict[str, Any]
    ) -> list[dict[str, Any]]:
        lowered = str(message or "").lower()
        matches = []
        for item in as_list(as_dict(state.get("learning_path")).get("items")):
            if not isinstance(item, dict):
                continue
            point_name = str(item.get("knowledge_point_name") or "").strip()
            aliases = [point_name]
            if "类" in point_name and "对象" in point_name:
                aliases.extend(["类和对象", "类与对象"])
            if "封装" in point_name:
                aliases.append("封装")
            if "pandas" in point_name.lower():
                aliases.append("pandas")
            if any(alias and alias.lower() in lowered for alias in aliases):
                matches.append(item)
        return matches

    def _update_project_learning_context(
        self,
        student_id: str,
        project: dict[str, Any] | None,
        message: str,
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not project:
            return {
                "status": "needs_clarification",
                "intent": "select_project",
                "action": "ask_clarification",
                "message": "这是一条学习情况说明，但当前没有选中项目。请先选择要调整的学习项目。",
                "clarify_options": self._goal_clarify_options(),
            }
        project_id = str(project.get("project_id") or "")
        state = as_dict(project.get("state"))
        preferences = as_dict(state.get("learner_preferences"))
        evidence = [item for item in as_list(state.get("learner_self_reports")) if isinstance(item, dict)]
        updates = []

        minutes = 0
        if re.search(r"(?:每天|每日)[^，。；]{0,8}?半\s*(?:个)?小时", message):
            minutes = 30
        else:
            daily_time = re.search(
                r"(?:每天|每日)[^，。；]{0,8}?(\d+(?:\.\d+)?|一|两|二)\s*(分钟|个?小时)",
                message,
            )
            if daily_time:
                raw_amount = daily_time.group(1)
                amount = {"一": 1.0, "两": 2.0, "二": 2.0}.get(raw_amount, 0.0)
                if not amount:
                    amount = float(raw_amount)
                minutes = round(amount * 60) if "小时" in daily_time.group(2) else round(amount)
        if minutes:
            minutes = max(5, min(minutes, 720))
            preferences["daily_minutes"] = minutes
            updates.append(f"每日可学习时间按 {minutes} 分钟记录")

        if any(word in message for word in ("多举例", "喜欢案例", "先看案例", "案例优先", "案例讲")):
            preferences["explanation_style"] = "example_driven"
            updates.append("讲解偏好调整为案例优先")
        elif any(word in message for word in ("详细一点", "讲慢", "看不懂")):
            preferences["explanation_style"] = "step_by_step"
            updates.append("讲解偏好调整为分步慢讲")
        elif any(word in message for word in ("简单一点", "讲快")):
            preferences["explanation_style"] = "concise"
            updates.append("讲解偏好调整为精简模式")

        matched_points = self._project_path_matches(message, state)
        mastery_claim = any(word in message for word in ("已经会", "我会了", "学过", "已经学过"))
        weakness_claim = any(word in message for word in ("不会", "不太会", "看不懂", "没学过", "零基础"))
        for item in matched_points:
            evidence.append({
                "type": "self_report",
                "knowledge_point_id": str(item.get("knowledge_point_id") or ""),
                "knowledge_point_name": str(item.get("knowledge_point_name") or ""),
                "claim": "familiar" if mastery_claim else "needs_support" if weakness_claim else "priority",
                "message": message,
                "verification_state": "unverified",
                "created_at": utc_now(),
            })
        if matched_points and mastery_claim:
            names = "、".join(str(item.get("knowledge_point_name") or "") for item in matched_points)
            updates.append(f"已记录你自报熟悉“{names}”，但暂不改动掌握度")
        elif matched_points and weakness_claim:
            names = "、".join(str(item.get("knowledge_point_name") or "") for item in matched_points)
            updates.append(f"已把“{names}”记录为需要更多支持")
        elif matched_points and any(word in message for word in ("想先学", "先学", "优先学")):
            names = "、".join(str(item.get("knowledge_point_name") or "") for item in matched_points)
            updates.append(f"已记录你想优先学习“{names}”；实际顺序仍会检查必要前置知识")

        if not updates:
            return {
                "status": "needs_clarification",
                "intent": "update_learning_context",
                "action": "ask_clarification",
                "message": "我知道你在补充学习情况，但还缺少可执行信息。请说明可用时间、已学内容、困难点或偏好的讲解方式。",
                "clarify_options": [
                    {"id": "time", "label": "补充学习时间", "prompt": "我每天可以学习 30 分钟"},
                    {"id": "foundation", "label": "补充已有基础", "prompt": "类和对象已经学过，但封装还不熟"},
                    {"id": "style", "label": "补充讲解偏好", "prompt": "我喜欢先看案例，再解释原理"},
                ],
            }

        state["learner_preferences"] = preferences
        state["learner_self_reports"] = evidence[-30:]
        if workspace_context:
            state["last_workspace_context"] = workspace_context
        self.store.save_project_state(project_id, state)
        return {
            "status": "ok",
            "intent": "update_learning_context",
            "action": "context_updated",
            "message": "；".join(updates) + "。自报基础需要后续测评验证，我不会直接把它写成已掌握。",
            "project": self._project_payload(
                project_id,
                str(project.get("goal_name") or ""),
                str(project.get("status") or "created"),
                state,
            ),
            "context_update": {
                "learner_preferences": preferences,
                "self_reported_points": [
                    str(item.get("knowledge_point_id") or "") for item in matched_points
                ],
                "verification_state": "unverified" if matched_points else "not_applicable",
            },
        }

    @staticmethod
    def _project_choice_response(
        message: str, projects: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "status": "needs_clarification",
            "intent": "select_project",
            "action": "ask_clarification",
            "message": "你有多个学习项目，请先选择本次要操作的项目。",
            "clarify_options": [
                {
                    "id": str(project.get("project_id") or ""),
                    "label": str(project.get("goal_name") or "学习项目"),
                    "prompt": message,
                    "project_id": str(project.get("project_id") or ""),
                }
                for project in projects[:5]
            ],
        }

    @staticmethod
    def _agent_lesson_target(
        message: str, state: dict[str, Any]
    ) -> dict[str, Any] | None:
        items = [
            item
            for item in as_list(as_dict(state.get("learning_path")).get("items"))
            if isinstance(item, dict)
        ]
        lowered = message.lower()
        for item in items:
            point_id = str(item.get("knowledge_point_id") or "")
            point_name = str(item.get("knowledge_point_name") or point_id)
            if point_id.lower() in lowered or point_name.lower() in lowered:
                return item
        if any(word in message for word in ("开始学习", "继续学习", "下一课")):
            weak_ids = {
                str(item.get("knowledge_point_id") or "")
                for item in as_list(state.get("weak_points"))
                if isinstance(item, dict)
            }
            for item in items:
                if str(item.get("knowledge_point_id") or "") in weak_ids:
                    return item
            for item in items:
                if str(item.get("status") or "") in {"current", "learning"}:
                    return item
            return items[0] if items else None
        return None

    # ------------------------------------------------------------------
    # Learner State Discovery 模块（学习信息快速获取）
    # ------------------------------------------------------------------

    @staticmethod
    def _discovery_identity(incoming):
        learner_id = str(
            incoming.get("learner_id") or incoming.get("student_id") or ""
        ).strip()
        if not learner_id:
            raise ApiError(400, "MISSING_LEARNER_ID", "learner_id 不能为空")
        return learner_id

    def _discovery_call(self, fn):
        try:
            return fn()
        except DiscoveryError as error:
            status = 404 if error.code == "SESSION_NOT_FOUND" else (
                403 if error.code == "FORBIDDEN" else 400
            )
            raise ApiError(status, error.code, error.message)

    def discovery_create(self, incoming):
        learner_id = self._discovery_identity(incoming)
        project_id = str(incoming.get("project_id") or "").strip() or None
        if project_id:
            self._require_project(learner_id, project_id)
        return self._discovery_call(lambda: self.discovery.create_session(
            learner_id=learner_id,
            project_id=project_id,
            checkpoint_id=str(incoming.get("checkpoint_id") or "").strip() or None,
            goal_candidate=str(
                incoming.get("goal_candidate") or incoming.get("text") or ""
            ).strip(),
            desired_outcome=str(incoming.get("desired_outcome") or "").strip(),
            goal_id=str(incoming.get("goal_id") or "").strip() or None,
            seed=incoming.get("seed"),
            policy=incoming.get("policy"),
        ))

    def discovery_answer(self, incoming):
        learner_id = self._discovery_identity(incoming)
        session_id = str(incoming.get("session_id") or "").strip()
        if not session_id:
            raise ApiError(400, "MISSING_SESSION_ID", "session_id 不能为空")
        return self._discovery_call(
            lambda: self.discovery.answer(session_id, learner_id, incoming)
        )

    def discovery_get(self, incoming):
        learner_id = self._discovery_identity(incoming)
        session_id = str(incoming.get("session_id") or "").strip()
        if not session_id:
            raise ApiError(400, "MISSING_SESSION_ID", "session_id 不能为空")
        return self._discovery_call(
            lambda: self.discovery.get_session(session_id, learner_id)
        )

    def discovery_projection(self, incoming):
        learner_id = self._discovery_identity(incoming)
        session_id = str(incoming.get("session_id") or "").strip()
        if not session_id:
            raise ApiError(400, "MISSING_SESSION_ID", "session_id 不能为空")
        return self._discovery_call(
            lambda: self.discovery.get_projection(session_id, learner_id)
        )

    def discovery_correct(self, incoming):
        learner_id = self._discovery_identity(incoming)
        session_id = str(incoming.get("session_id") or "").strip()
        if not session_id:
            raise ApiError(400, "MISSING_SESSION_ID", "session_id 不能为空")
        return self._discovery_call(
            lambda: self.discovery.correct_event(session_id, learner_id, incoming)
        )

    def discovery_events(self, incoming):
        learner_id = self._discovery_identity(incoming)
        session_id = str(incoming.get("session_id") or "").strip() or None
        return self.discovery.export_events(learner_id, session_id)

    def discovery_sessions(self, incoming):
        learner_id = self._discovery_identity(incoming)
        return self.discovery.list_sessions(learner_id)


    ASSESSMENT_TYPES: dict[str, dict[str, str]] = {
        "initial_diagnostic": {
            "label": "目标能力诊断",
            "stakes": "formal",
            "evidence_role": "diagnostic",
            "description": "覆盖目标能力图谱，定位起点与薄弱项。",
        },
        "stage_check": {
            "label": "阶段检查",
            "stakes": "formal",
            "evidence_role": "verification",
            "description": "检查当前章节是否达到继续学习的条件。",
        },
        "self_check": {
            "label": "自主能力检测",
            "stakes": "low",
            "evidence_role": "practice",
            "description": "由学习者选择范围进行低风险自检。",
        },
        "provisional_self_check": {
            "label": "AI 临时自检",
            "stakes": "low",
            "evidence_role": "practice_unverified",
            "description": "题源未审核时用于即时反馈，不写入正式画像或掌握度。",
        },
    }

    def _assessment_target_point(
        self, state: dict[str, Any], requested_id: str
    ) -> dict[str, Any]:
        items = [
            item
            for item in as_list(as_dict(state.get("learning_path")).get("items"))
            if isinstance(item, dict)
        ]
        if requested_id:
            target = next(
                (
                    item
                    for item in items
                    if str(item.get("knowledge_point_id") or "") == requested_id
                ),
                None,
            )
            if not target:
                raise ApiError(404, "KNOWLEDGE_POINT_NOT_FOUND", "测评范围不在当前项目路径中")
            return target
        weak_ids = {
            str(item.get("knowledge_point_id") or "")
            for item in as_list(state.get("weak_points"))
            if isinstance(item, dict)
        }
        return next(
            (item for item in items if str(item.get("knowledge_point_id") or "") in weak_ids),
            next(
                (
                    item
                    for item in items
                    if str(item.get("status") or "") in {"current", "learning"}
                ),
                items[0] if items else {},
            ),
        )

    def _assessment_questions(
        self,
        student_id: str,
        goal_key: str,
        state: dict[str, Any],
        assessment_type: str,
        knowledge_point_id: str,
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        custom_goal = str(state.get("support_level") or "") == "generated_scaffold"
        if assessment_type == "initial_diagnostic":
            weak_points = [
                item
                for item in as_list(state.get("weak_points"))
                if isinstance(item, dict)
            ]
            if custom_goal:
                scope = [
                    {
                        "knowledge_point_id": str(item.get("knowledge_point_id") or ""),
                        "knowledge_point_name": str(item.get("knowledge_point_name") or ""),
                    }
                    for item in as_list(as_dict(state.get("learning_path")).get("items"))
                    if isinstance(item, dict) and str(item.get("knowledge_point_id") or "")
                ]
                if self.gateway.mode != "remote":
                    questions, provider = [], "source_pending"
                else:
                    try:
                        generated_result = self.gateway.invoke_quiz_workflow(
                            {
                                "student_id": student_id,
                                "goal": "custom",
                                "goal_description": str(
                                    as_dict(state.get("goal")).get("original_text") or ""
                                ),
                                "weak_points": weak_points,
                                "knowledge_list": scope,
                            }
                        )
                        questions, _ = self._validate_quiz_questions(
                            as_list(generated_result.get("questions"))
                        )
                        allowed_ids = {
                            str(item.get("knowledge_point_id") or "") for item in scope
                        }
                        questions = [
                            item
                            for item in questions
                            if str(item.get("knowledge_point_id") or "") in allowed_ids
                        ]
                        provider = str(generated_result.get("provider") or "workflow")
                    except Exception:
                        questions, provider = [], "source_pending"
            else:
                questions, provider = self._generate_diagnosis_questions(
                    student_id, goal_key, weak_points
                )
                scope = self._goal_knowledge_list(goal_key)
        else:
            target = self._assessment_target_point(state, knowledge_point_id)
            target_id = str(target.get("knowledge_point_id") or "")
            if not target_id:
                raise ApiError(409, "ASSESSMENT_SCOPE_EMPTY", "当前项目还没有可检测的知识点")
            candidates = [
                item
                for item in DIAGNOSIS_BANK
                if str(item.get("knowledge_point_id") or "") == target_id
                and (not item.get("goals") or goal_key in as_list(item.get("goals")))
            ]
            candidates.sort(key=lambda item: int(item.get("difficulty", 1) or 1))
            questions = [
                {
                    "question_id": str(item.get("id") or ""),
                    "knowledge_point_id": target_id,
                    "knowledge_point_name": str(
                        item.get("knowledge_point_name")
                        or target.get("knowledge_point_name")
                        or target_id
                    ),
                    "title": str(item.get("title") or ""),
                    "options": as_dict(item.get("options")),
                    "answer": str(item.get("answer") or ""),
                    "explanation": str(item.get("explanation") or ""),
                    "difficulty": int(item.get("difficulty", 1) or 1),
                    "source": str(item.get("source") or "本地审核题库"),
                }
                for item in candidates[:3]
            ]
            provider = "reviewed_bank"
            scope = [
                {
                    "knowledge_point_id": target_id,
                    "knowledge_point_name": str(
                        target.get("knowledge_point_name") or target_id
                    ),
                }
            ]
        if not questions:
            raise ApiError(
                409,
                "ASSESSMENT_QUESTION_GAP",
                (
                    "该目标的对应题源尚未通过校验，系统不会用其他领域题目或未核实的联网内容临时拼题"
                    if custom_goal
                    else "当前范围缺少已审核题目，系统不会用未核实的联网内容临时拼题"
                ),
            )
        normalized = []
        for item in questions:
            normalized.append(
                {
                    **item,
                    "source": str(item.get("source") or "本地审核题库"),
                    "source_type": (
                        "ai_generated_reviewed"
                        if provider in {"workflow", "workflow_reuse", "mock_bank"}
                        else "curated_bank"
                    ),
                    "quality_status": "reviewed",
                }
            )
        blueprint = {
            "assessment_type": assessment_type,
            "goal": goal_key,
            "coverage": scope,
            "question_count": len(normalized),
            "selection_rule": (
                "按目标能力图谱覆盖取样"
                if assessment_type == "initial_diagnostic"
                else "按所选知识点从已审核题库取样"
            ),
            "pass_rule": (
                "用于定位起点，不设置简单分数通过线"
                if assessment_type == "initial_diagnostic"
                else "至少两个不同题目形成独立正确证据"
            ),
            "source_policy": "权威材料或已审核题库优先；联网检索内容不得直接成为正式试题",
        }
        return normalized, provider, blueprint

    def _provisional_assessment_questions(
        self, student_id: str, state: dict[str, Any], knowledge_point_id: str
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        path_items = [
            item
            for item in as_list(as_dict(state.get("learning_path")).get("items"))
            if isinstance(item, dict) and str(item.get("knowledge_point_id") or "")
        ]
        if knowledge_point_id:
            path_items = [
                item
                for item in path_items
                if str(item.get("knowledge_point_id") or "") == knowledge_point_id
            ]
        scope = [
            {
                "knowledge_point_id": str(item.get("knowledge_point_id") or ""),
                "knowledge_point_name": str(item.get("knowledge_point_name") or ""),
            }
            for item in path_items[:6]
        ]
        if not scope:
            raise ApiError(409, "ASSESSMENT_SCOPE_EMPTY", "当前项目还没有可自检的学习节点")
        questions: list[dict[str, Any]] = []
        provider = "provisional_readiness_fallback"
        if self.gateway.mode == "remote":
            try:
                generated = self.gateway.invoke_quiz_workflow({
                    "student_id": student_id,
                    "goal": "custom",
                    "goal_description": str(
                        as_dict(state.get("goal")).get("original_text") or ""
                    ),
                    "assessment_type": "provisional_self_check",
                    "knowledge_list": scope,
                    "source_policy": (
                        "只生成低风险自检题；题目未经领域审核，不得写入正式画像或调整路径"
                    ),
                })
                questions, _ = self._validate_quiz_questions(
                    as_list(generated.get("questions"))
                )
                allowed_ids = {item["knowledge_point_id"] for item in scope}
                questions = [
                    item
                    for item in questions
                    if str(item.get("knowledge_point_id") or "") in allowed_ids
                ][:6]
                if questions:
                    provider = str(generated.get("provider") or "workflow_provisional")
            except Exception:
                questions = []
        if not questions:
            questions = [
                {
                    "question_id": f"PROVISIONAL-{uuid.uuid4().hex[:10].upper()}",
                    "knowledge_point_id": item["knowledge_point_id"],
                    "knowledge_point_name": item["knowledge_point_name"],
                    "title": (
                        f"对于“{item['knowledge_point_name']}”，下面哪项最能作为完成本阶段学习的可检查证据？"
                    ),
                    "options": {
                        "a": "看过一遍相关资料",
                        "b": "记住了几个术语",
                        "c": "能独立完成一个小任务，并解释结果和常见错误",
                        "d": "收藏了一个教程链接",
                    },
                    "answer": "c",
                    "explanation": (
                        "仅观看或记忆不能证明能够应用；独立产出、解释结果并识别错误是更可检查的学习证据。"
                    ),
                    "difficulty": 1,
                    "source": "通用学习证据规则（非领域知识题）",
                }
                for item in scope[:3]
            ]
        normalized = [
            {
                **item,
                "source": str(item.get("source") or "AI 临时生成（未做领域审核）"),
                "source_type": "ai_generated_unreviewed",
                "quality_status": "unverified",
            }
            for item in questions
        ]
        blueprint = {
            "assessment_type": "provisional_self_check",
            "goal": "custom",
            "coverage": scope,
            "question_count": len(normalized),
            "selection_rule": "按候选路径节点生成低风险临时自检",
            "pass_rule": "只提供即时反馈，不形成正式通过结论",
            "source_policy": (
                "AI 生成题或通用准备度题未经领域审核；结果不进入画像、不更新掌握度、不调整路径"
            ),
        }
        return normalized, provider, blueprint

    def project_assessment_start(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        assessment_type = str(
            incoming.get("assessment_type") or "initial_diagnostic"
        ).strip()
        provisional = assessment_type == "provisional_self_check"
        if str(state.get("planning_state") or "ready") != "ready":
            raise ApiError(
                409,
                "GOAL_KNOWLEDGE_MAPPING_PENDING",
                "该目标的知识结构和题目来源仍在校验，暂不能开始测评，以免生成与目标无关的题目",
            )
        if str(state.get("assessment_state") or "ready") != "ready" and not provisional:
            raise ApiError(
                409,
                "GOAL_ASSESSMENT_SOURCE_PENDING",
                "该目标的对应题源尚未通过校验，可先按候选路径学习；系统不会套用其他领域题目",
            )
        type_meta = self.ASSESSMENT_TYPES.get(assessment_type)
        if not type_meta:
            raise ApiError(400, "UNKNOWN_ASSESSMENT_TYPE", "不支持的测评类型")
        requested_point = str(incoming.get("knowledge_point_id") or "").strip()
        if provisional:
            goal_key = "custom"
            goal_label = str(project.get("goal_name") or "自定义目标")
            questions, provider, blueprint = self._provisional_assessment_questions(
                student_id, state, requested_point
            )
        else:
            goal_key = self.PROJECT_GOAL_DIAGNOSIS.get(
                str(project.get("goal_id", "")), "daily"
            )
            goal_config = DIAGNOSIS_GOALS.get(goal_key)
            if not goal_config:
                raise ApiError(400, "UNKNOWN_GOAL", f"不支持的目标：{goal_key}")
            goal_label = str(goal_config["label"])
            questions, provider, blueprint = self._assessment_questions(
                student_id,
                goal_key,
                state,
                assessment_type,
                requested_point,
            )
        title = f"{type_meta['label']} · {project['goal_name']}"
        assessment_id = self.store.create_assessment_run(
            project_id,
            student_id,
            assessment_type,
            title,
            type_meta["stakes"],
            provider,
            blueprint,
        )
        session = {
            "assessment_id": assessment_id,
            "assessment_type": assessment_type,
            "title": title,
            "stakes": type_meta["stakes"],
            "evidence_role": type_meta["evidence_role"],
            "goal": goal_key,
            "questions": questions,
            "index": 0,
            "correct": 0,
            "wrong": 0,
            "skipped": 0,
            "results": [],
            "done": False,
            "blueprint": blueprint,
            "formal_evidence": not provisional,
        }
        state["assessment_session"] = session
        if assessment_type == "initial_diagnostic":
            state["diagnosis_session"] = session
        self.store.save_project_state(project_id, state, status="assessment")
        public_questions = [
            {k: v for k, v in q.items() if k not in ("answer", "explanation")}
            for q in questions
        ]
        return {
            "status": "ok",
            "project_id": project_id,
            "assessment_id": assessment_id,
            "assessment_type": assessment_type,
            "title": title,
            "stakes": type_meta["stakes"],
            "goal": goal_key,
            "goal_label": goal_label,
            "provider": provider,
            "blueprint": blueprint,
            "source_policy": blueprint["source_policy"],
            "questions": public_questions,
            "total": len(public_questions),
        }

    def project_diagnosis_start(self, incoming: dict[str, Any]) -> dict[str, Any]:
        return self.project_assessment_start(
            {**incoming, "assessment_type": "initial_diagnostic"}
        )

    def project_assessment_answer(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        session = as_dict(
            state.get("assessment_session") or state.get("diagnosis_session")
        )
        if not session:
            raise ApiError(409, "DIAGNOSIS_NOT_ACTIVE", "当前没有进行中的测评，请先开始")
        if session.get("done"):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮测评已结束，请重新开始")
        expected_assessment_id = str(session.get("assessment_id") or "")
        requested_assessment_id = str(incoming.get("assessment_id") or "").strip()
        if requested_assessment_id and requested_assessment_id != expected_assessment_id:
            raise ApiError(409, "ASSESSMENT_SESSION_MISMATCH", "测评会话已变化，请重新打开当前测评")
        skipped = bool(incoming.get("skipped"))
        selected = str(incoming.get("selected", "")).strip()
        index = int(session.get("index", 0) or 0)
        questions = as_list(session.get("questions"))
        if index >= len(questions):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮测评已结束")
        current = questions[index]
        formal_evidence = bool(session.get("formal_evidence", True))
        if skipped:
            correct = False
            session["skipped"] = int(session.get("skipped", 0) or 0) + 1
        else:
            if selected not in {"a", "b", "c", "d"}:
                raise ApiError(400, "INVALID_ANSWER", "无效的选项")
            correct = selected == str(current.get("answer", ""))
            key = "correct" if correct else "wrong"
            session[key] = int(session.get(key, 0) or 0) + 1
        attempt_result: dict[str, Any] = {}
        if not skipped and formal_evidence:
            # 测评作答落库（与现有诊断一致），供画像溯源/学习记录使用
            attempt_result = self.domain.record_choice_attempt(
                student_id=student_id,
                source_question_id=str(current.get("question_id", "")),
                mode=(
                    "diagnosis"
                    if session.get("assessment_type") == "initial_diagnostic"
                    else str(session.get("assessment_type") or "assessment")
                ),
                knowledge_point_id=str(current.get("knowledge_point_id", "")),
                knowledge_point_name=str(current.get("knowledge_point_name", "")),
                title=str(current.get("title", "")),
                prompt=str(current.get("title", "")),
                options=as_dict(current.get("options")),
                expected=str(current.get("answer", "")),
                selected=selected,
                explanation=str(current.get("explanation", "")),
            )
        confidence = (
            0.3
            if skipped
            else 0.9
            if session.get("evidence_role") == "verification"
            else 0.85
            if session.get("evidence_role") == "diagnostic"
            else 0.65
        )
        evidence_event_id = ""
        if formal_evidence:
            evidence_event_id = self.store.record_assessment_evidence(
                expected_assessment_id,
                project_id,
                student_id,
                str(current.get("question_id") or ""),
                str(current.get("knowledge_point_id") or ""),
                "ANSWER_SKIPPED" if skipped else "ANSWER_SUBMITTED",
                str(session.get("evidence_role") or "diagnostic"),
                confidence,
                {
                    "correct": correct,
                    "skipped": skipped,
                    "selected": selected,
                    "assisted": False,
                    "difficulty": int(current.get("difficulty", 1) or 1),
                    "source": str(current.get("source") or ""),
                    "source_type": str(current.get("source_type") or ""),
                    "attempt_id": str(attempt_result.get("attempt_id") or ""),
                },
            )
        session.setdefault("results", []).append(
            {
                "question_id": current.get("question_id", ""),
                "knowledge_point_id": current.get("knowledge_point_id", ""),
                "knowledge_point_name": current.get("knowledge_point_name", ""),
                "correct": correct,
                "skipped": skipped,
                "evidence_event_id": evidence_event_id,
            }
        )
        is_last = index + 1 >= len(questions)
        session["index"] = index + 1
        if is_last:
            session["done"] = True
        state["assessment_session"] = session
        if session.get("assessment_type") == "initial_diagnostic":
            state["diagnosis_session"] = session
        self.store.save_project_state(project_id, state)

        stats = {
            "correct": session["correct"],
            "wrong": session["wrong"],
            "skipped": session["skipped"],
            "done": session["done"],
            "question_index": session["index"],
            "total": len(questions),
        }
        base = {
            "status": "ok",
            "correct": correct,
            "skipped": skipped,
            "explanation": current.get("explanation", ""),
            "knowledge_point_id": current.get("knowledge_point_id", ""),
            "knowledge_point_name": current.get("knowledge_point_name", ""),
            "answer": current.get("answer", ""),
            "assessment_id": expected_assessment_id,
            "assessment_type": session.get("assessment_type", "initial_diagnostic"),
            "evidence_event_id": evidence_event_id,
            "stats": stats,
        }
        if not is_last:
            return base
        summary = (
            self._finalize_project_assessment(student_id, project_id, state, session)
            if formal_evidence
            else self._finalize_provisional_self_check(session)
        )
        self.store.complete_assessment_run(expected_assessment_id, summary)
        self.store.save_project_state(project_id, state, status="assessment_done")
        base["status"] = "completed"
        base["summary"] = summary
        return base

    @staticmethod
    def _finalize_provisional_self_check(session: dict[str, Any]) -> dict[str, Any]:
        total = len(as_list(session.get("results")))
        correct = int(session.get("correct", 0) or 0)
        return {
            "assessment_id": str(session.get("assessment_id") or ""),
            "assessment_type": "provisional_self_check",
            "title": str(session.get("title") or "AI 临时自检"),
            "score": correct,
            "total": total,
            "weak_points": [],
            "knowledge_updates": [],
            "evidence_count": 0,
            "formal_evidence": False,
            "mastery_note": "题目未经领域审核，本次结果不写入正式画像或掌握度。",
            "path_adjustment": "未调整学习路径；请在正式题源接入后完成目标诊断。",
            "feedback": (
                f"临时自检完成：{correct}/{total}。结果仅作即时参考，不代表正式能力结论。"
            ),
        }

    def project_diagnosis_answer(self, incoming: dict[str, Any]) -> dict[str, Any]:
        return self.project_assessment_answer(incoming)

    def _finalize_project_assessment(
        self,
        student_id: str,
        project_id: str,
        state: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """证据账本 → 可解释状态 → 路径调整；数值是规则指数，不冒充统计概率。"""
        evidence = self.store.list_assessment_evidence(project_id, student_id)
        aggregates: dict[str, dict[str, Any]] = {}
        for event in evidence:
            kp_id = str(event.get("knowledge_point_id") or "")
            if not kp_id:
                continue
            payload = as_dict(event.get("payload"))
            aggregate = aggregates.setdefault(
                kp_id,
                {"correct": set(), "wrong": set(), "skipped": 0, "events": []},
            )
            aggregate["events"].append(str(event.get("event_id") or ""))
            question_id = str(event.get("question_id") or "")
            if event.get("event_type") == "ANSWER_SKIPPED":
                aggregate["skipped"] += 1
            elif payload.get("correct") and not payload.get("assisted"):
                aggregate["correct"].add(question_id)
            else:
                aggregate["wrong"].add(question_id)

        path = as_dict(state.get("learning_path"))
        items = [dict(item) for item in as_list(path.get("items")) if isinstance(item, dict)]
        knowledge_updates = []
        for item in items:
            kp_id = str(item.get("knowledge_point_id") or "")
            aggregate = aggregates.get(kp_id)
            if not aggregate:
                continue
            correct_count = len(aggregate["correct"])
            wrong_count = len(aggregate["wrong"])
            graded_count = correct_count + wrong_count
            ratio = correct_count / graded_count if graded_count else 0.0
            current_session_records = [
                record
                for record in as_list(session.get("results"))
                if str(record.get("knowledge_point_id") or "") == kp_id
                and not record.get("skipped")
            ]
            current_all_correct = bool(current_session_records) and all(
                record.get("correct") for record in current_session_records
            )
            if (
                session.get("evidence_role") == "verification"
                and len(current_session_records) >= 2
                and current_all_correct
            ):
                evidence_status, mastery_index = "verified_once", 85
            elif correct_count >= 2 and ratio >= 0.67:
                evidence_status, mastery_index = "supported", 80
            elif correct_count >= 1 and wrong_count == 0:
                evidence_status, mastery_index = "candidate", 60
            elif graded_count and ratio >= 0.5:
                evidence_status, mastery_index = "developing", 50
            elif graded_count:
                evidence_status, mastery_index = "needs_support", 35
            else:
                evidence_status, mastery_index = "unknown", 0
            confidence = min(0.95, 0.25 + graded_count * 0.15)
            item.update(
                {
                    "mastery": mastery_index,
                    "mastery_is_estimated": True,
                    "mastery_model": "evidence_rule_v1",
                    "evidence_status": evidence_status,
                    "evidence_count": len(aggregate["events"]),
                    "confidence": round(confidence, 2),
                }
            )
            if evidence_status in {"verified_once", "supported"}:
                item["status"] = "completed"
            elif evidence_status in {"needs_support", "developing"}:
                item["status"] = "current"
            knowledge_updates.append(
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": str(item.get("knowledge_point_name") or kp_id),
                    "evidence_status": evidence_status,
                    "mastery_index": mastery_index,
                    "confidence": round(confidence, 2),
                    "evidence_count": len(aggregate["events"]),
                    "correct_count": correct_count,
                    "wrong_count": wrong_count,
                }
            )
        verified_ids = {
            str(record.get("knowledge_point_id") or "")
            for record in as_list(session.get("results"))
            if record.get("correct")
        }
        for index, item in enumerate(items[:-1]):
            if (
                str(item.get("knowledge_point_id") or "") in verified_ids
                and item.get("evidence_status") == "verified_once"
                and str(items[index + 1].get("status") or "") == "pending"
            ):
                items[index + 1]["status"] = "current"
        state["learning_path"] = {**path, "items": items}

        weak_points = []
        for update in knowledge_updates:
            if update["evidence_status"] not in {"needs_support", "developing"}:
                continue
            kp_id = update["knowledge_point_id"]
            card = default_error_card_for(kp_id)
            weak_points.append(
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": update["knowledge_point_name"],
                    "error_count": update["wrong_count"],
                    "error_id": card.get("error_id", ""),
                    "error_type": card.get("error_type", ""),
                    "misconception_tag": card.get("misconception_tag", ""),
                    "root_cause": card.get("root_cause", ""),
                    "evidence_status": update["evidence_status"],
                }
            )
        weak_points.sort(key=lambda item: -int(item.get("error_count", 0) or 0))
        state["weak_points"] = weak_points
        total = len(as_list(session.get("results")))
        correct = int(session.get("correct", 0) or 0)
        summary = {
            "assessment_id": str(session.get("assessment_id") or ""),
            "assessment_type": str(session.get("assessment_type") or "initial_diagnostic"),
            "title": str(session.get("title") or "能力测评"),
            "score": correct,
            "total": total,
            "weak_points": weak_points,
            "knowledge_updates": knowledge_updates,
            "evidence_count": len(as_list(session.get("results"))),
            "mastery_note": "掌握度为 evidence_rule_v1 规则指数，不是统计概率；可点击证据记录追溯。",
            "path_adjustment": (
                "已依据证据状态标记补强节点，并在通过阶段检查后解锁下一节点。"
            ),
            "feedback": (
                f"测评完成：{correct}/{total}，发现 {len(weak_points)} 个需要补强的知识点。"
            ),
        }
        state["last_assessment_summary"] = summary
        return summary

    def project_assessments(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id") or "").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project.get("state"))
        planning_ready = str(state.get("planning_state") or "ready") == "ready"
        assessment_ready = str(state.get("assessment_state") or "ready") == "ready"
        target = self._assessment_target_point(state, "")
        catalog = []
        if planning_ready and assessment_ready:
            catalog = [
                {
                    "assessment_type": key,
                    **meta,
                    "recommended_knowledge_point_id": (
                        ""
                        if key == "initial_diagnostic"
                        else str(target.get("knowledge_point_id") or "")
                    ),
                    "recommended_knowledge_point_name": (
                        "目标能力图谱"
                        if key == "initial_diagnostic"
                        else str(target.get("knowledge_point_name") or "当前章节")
                    ),
                }
                for key, meta in self.ASSESSMENT_TYPES.items()
                if key != "provisional_self_check"
            ]
        elif planning_ready:
            catalog = [{
                "assessment_type": "provisional_self_check",
                **self.ASSESSMENT_TYPES["provisional_self_check"],
                "recommended_knowledge_point_id": str(
                    target.get("knowledge_point_id") or ""
                ),
                "recommended_knowledge_point_name": str(
                    target.get("knowledge_point_name") or "候选路径"
                ),
            }]
        return {
            "status": "ok",
            "project_id": project_id,
            "planning_state": str(state.get("planning_state") or "ready"),
            "assessment_available": bool(catalog),
            "formal_assessment_available": planning_ready and assessment_ready,
            "availability_message": (
                ""
                if planning_ready and assessment_ready
                else (
                    "正式题源尚未通过校验；仅开放不写入画像的 AI 临时自检"
                    if planning_ready
                    else "知识结构与题目来源尚未校验完成，测评暂不可用"
                )
            ),
            "catalog": catalog,
            "history": self.store.list_assessment_runs(project_id, student_id),
        }

    def project_assessment_evidence(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id") or "").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        assessment_id = str(incoming.get("assessment_id") or "").strip()
        self._require_project(student_id, project_id)
        return {
            "status": "ok",
            "project_id": project_id,
            "assessment_id": assessment_id,
            "events": self.store.list_assessment_evidence(
                project_id, student_id, assessment_id
            ),
        }

    def project_explain(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """项目章节讲解：按项目路径中的知识点生成教学包（复用学习工作流管道）。"""
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        knowledge_point_id = str(incoming.get("knowledge_point_id", "")).strip()
        if not knowledge_point_id:
            raise ApiError(400, "MISSING_KNOWLEDGE_POINT", "缺少 knowledge_point_id")
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        path = as_dict(state.get("learning_path"))
        items = [item for item in as_list(path.get("items")) if isinstance(item, dict)]
        target = next(
            (
                item
                for item in items
                if str(item.get("knowledge_point_id", "")) == knowledge_point_id
            ),
            None,
        )
        if not target:
            raise ApiError(
                404, "KNOWLEDGE_POINT_NOT_FOUND", "该项目路径中没有该知识点"
            )

        learner_preferences = as_dict(state.get("learner_preferences"))
        explanation_style = str(
            learner_preferences.get("explanation_style") or ""
        ).strip()
        event_type = {
            "example_driven": "show_example",
            "step_by_step": "show_steps",
        }.get(explanation_style, "initialize_learning")
        context = {
            "student_id": student_id,
            "session_id": f"PROJECT-{project_id}",
            "learning_goal": {
                "goal_id": str(project.get("goal_id", "")),
                "goal_name": str(project.get("goal_name", "")),
            },
            "learning_path": path,
            "current_knowledge_point": target,
            "event_type": event_type,
            "goal_driven": True,
            "learner_preferences": learner_preferences,
            "learner_self_reports": as_list(state.get("learner_self_reports"))[-5:],
        }
        if str(state.get("support_level") or "") == "generated_scaffold":
            result = self._custom_goal_lesson(project, state, target)
        else:
            self._prepare_learning_workflow_context(context, {})
            self._attach_video_search("learning", context)
            workflow_payload = self._learning_workflow_payload(context)
            try:
                result = self.gateway.invoke_learning_workflow(workflow_payload)
                result = self._normalize_learning_result(result, context)
                if str(result.get("status") or "") != "ok" or not as_list(
                    result.get("content_blocks")
                ):
                    raise GatewayError("学习工作流未返回可展示的讲解内容")
            except Exception:
                result = self.gateway._mock_learning(workflow_payload)
                result["fallback_used"] = True
                result["fallback_reason"] = "远程学习工作流暂时不可用"
                result["source_status"] = "verified_local_fallback"
                result["source_notice"] = (
                    "本次已自动改用本地课程知识库组织讲解；联网工作流恢复后会优先使用远程生成。"
                )
            self._merge_web_sources(result)
            self._merge_video_resources(result, context)

        # 路径状态推进：pending/current → learning（记录学习行为）
        for index, item in enumerate(items):
            if str(item.get("knowledge_point_id", "")) == knowledge_point_id and str(
                item.get("status", "")
            ) in {"pending", "current"}:
                items[index] = {**item, "status": "learning"}
                state["learning_path"] = {**path, "items": items}
                self.store.save_project_state(project_id, state)
                break

        result["project_id"] = project_id
        result["knowledge_point_id"] = knowledge_point_id
        return result

    @staticmethod
    def _custom_goal_lesson(
        project: dict[str, Any], state: dict[str, Any], target: dict[str, Any]
    ) -> dict[str, Any]:
        goal = as_dict(state.get("goal"))
        goal_name = str(project.get("goal_name") or goal.get("goal_name") or "学习目标")
        knowledge_name = str(target.get("knowledge_point_name") or "当前知识点")
        outcome = str(as_dict(goal.get("constraints")).get("target_outcome") or "")
        order = int(target.get("recommended_order", 1) or 1)
        path_items = [
            item
            for item in as_list(as_dict(state.get("learning_path")).get("items"))
            if isinstance(item, dict)
        ]
        previous = path_items[order - 2] if order > 1 and len(path_items) >= order - 1 else {}
        next_item = path_items[order] if len(path_items) > order else {}
        return {
            "status": "ok",
            "workflow_mode": "candidate_scaffold",
            "lesson_title": knowledge_name,
            "lesson_objective": (
                f"完成本节后，能够说明“{knowledge_name}”在“{goal_name}”中的作用，"
                + (f"并将其用于“{outcome}”。" if outcome else "并完成一个可检查的小任务。")
            ),
            "content_blocks": [
                {
                    "type": "warning",
                    "title": "内容状态说明",
                    "content": (
                        "这是根据目标语义生成的候选讲解框架，尚未绑定经过审核的课程标准或权威资料。"
                        "可用于确定学习方向，不应替代正式教材和教师审核。"
                    ),
                    "source": "目标语义拆解（待权威来源复核）",
                },
                {
                    "type": "weakness_connection",
                    "title": "本节在路径中的位置",
                    "content": (
                        f"这是第 {order} 个学习节点。"
                        + (
                            f"建议先完成“{previous.get('knowledge_point_name')}”，再进入本节。"
                            if previous
                            else "本节是当前候选路径的起点，用于建立后续学习所需基础。"
                        )
                    ),
                    "source": "候选学习路径",
                },
                {
                    "type": "concept",
                    "title": "学习重点",
                    "content": (
                        f"围绕“{knowledge_name}”建立三个层次：先理解关键术语与适用边界，"
                        "再观察一个完整案例，最后独立完成一个能被检查的产出。"
                    ),
                    "source": "通用教学任务框架（待领域资料补充）",
                },
                {
                    "type": "steps",
                    "title": "建议学习步骤",
                    "items": [
                        f"列出“{knowledge_name}”必须掌握的 3-5 个关键概念",
                        "找一个与目标一致的完整案例，标注输入、过程与输出",
                        "不看答案复现关键步骤，并记录卡住的位置",
                        (
                            f"完成一个能为“{outcome}”服务的小产出"
                            if outcome
                            else "完成一个可运行、可展示或可评分的小产出"
                        ),
                        "用结果、错误记录或作品对照标准进行复盘",
                    ],
                    "source": "候选学习策略",
                },
                {
                    "type": "workplace",
                    "title": "完成标准",
                    "content": (
                        "能用自己的话说明核心概念，能独立完成一次小任务，并能指出至少一个常见错误及修正方法。"
                        + (
                            f"完成后可继续“{next_item.get('knowledge_point_name')}”。"
                            if next_item
                            else "完成后进入整体成果验收与复盘。"
                        )
                    ),
                    "source": "候选验收标准（待教师或行业标准复核）",
                },
            ],
            "resources": [],
            "sources": [],
            "source_status": "candidate_unverified",
            "source_notice": "尚未检索到通过校验的领域资料",
            "alternative_modes": ["worked_example", "step_by_step"],
        }

    def run_code(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """本地执行用户代码（演示级沙箱：超时 + 输出上限 + 临时目录）。

        单机演示用途；生产多用户需容器隔离（本机无 Docker）。
        """
        language = str(incoming.get("language", "java")).strip().lower()
        code = str(incoming.get("code", "")).strip()
        if not code:
            raise ApiError(400, "EMPTY_CODE", "代码不能为空")
        if len(code) > 20_000:
            raise ApiError(400, "CODE_TOO_LONG", "代码过长（上限 20000 字符）")
        if language not in {"java", "python"}:
            raise ApiError(400, "UNSUPPORTED_LANGUAGE", f"暂不支持的语言：{language}")
        # 演示级执行超时（须小于客户端/网关超时，避免请求方先断）
        timeout = 4
        max_output = 64 * 1024

        with tempfile.TemporaryDirectory(
            prefix="code-run-", ignore_cleanup_errors=True
        ) as workdir:
            try:
                if language == "java":
                    if "class Main" not in code and "public class Main" not in code:
                        # 包装成可执行 Main 类（简单模式）
                        wrapped = code if "class Main" in code else (
                            "public class Main {\n  public static void main(String[] args) {\n"
                            + "\n".join(f"    {line}" for line in code.splitlines())
                            + "\n  }\n}\n"
                        )
                    else:
                        wrapped = code
                    source_path = os.path.join(workdir, "Main.java")
                    with open(source_path, "w", encoding="utf-8") as handle:
                        handle.write(wrapped)
                    compiled = subprocess.run(
                        ["javac", "Main.java"],
                        cwd=workdir,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    if compiled.returncode != 0:
                        return {
                            "status": "compile_error",
                            "language": language,
                            "output": "",
                            "error": (compiled.stderr or "编译失败").strip()[:2000],
                        }
                    executed = subprocess.run(
                        ["java", "Main"],
                        cwd=workdir,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                else:
                    source_path = os.path.join(workdir, "main.py")
                    with open(source_path, "w", encoding="utf-8") as handle:
                        handle.write(code)
                    executed = subprocess.run(
                        [sys.executable, "main.py"],
                        cwd=workdir,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
            except subprocess.TimeoutExpired:
                return {
                    "status": "timeout",
                    "language": language,
                    "output": "",
                    "error": f"执行超过 {timeout} 秒，已终止（可能存在死循环）。",
                }
            except OSError as error:
                return {
                    "status": "runtime_error",
                    "language": language,
                    "output": "",
                    "error": f"执行环境不可用：{error}",
                }
            output = (executed.stdout or "")[-max_output:]
            return {
                "status": "ok" if executed.returncode == 0 else "runtime_error",
                "language": language,
                "output": output,
                "error": (executed.stderr or "").strip()[-2000:] if executed.returncode != 0 else "",
                "exit_code": executed.returncode,
            }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.gateway.remote_ready() else "configuration_required",
            "service": "personalized-learning-backend",
            "xingchen_mode": self.gateway.mode,
            "remote_ready": self.gateway.remote_ready(),
            "video_search_mode": self.settings.video_search_mode,
            "video_search_enabled": self.video_search.enabled,
            "time": utc_now(),
        }

    def bootstrap(self, student_id: str) -> dict[str, Any]:
        state = self.store.get_student_state(student_id)
        upstream = as_dict(state.get("upstream_payload"))
        if upstream:
            identifiers = self.domain.ingest_context(upstream)
            migrated = False
            for result_key, scene in (
                ("latest_learning_result", "learn"),
                ("latest_review_result", "error_correction"),
            ):
                previous = as_dict(state.get(result_key))
                if previous.get("status") == "ok" and not previous.get("explanation_session_id"):
                    state[result_key] = self.domain.record_explanation(
                        student_id, scene, {**upstream, **identifiers}, previous
                    )
                    migrated = True
            if migrated:
                state["updated_at"] = utc_now()
                self.store.save_student_state(student_id, state)
        profile = self.domain.profile(student_id)["profile"]
        settings = self.domain.settings(student_id)["settings"]
        notifications = self.domain.notifications(student_id)
        current_knowledge_id = str(
            as_dict(state.get("current_knowledge_point")).get("knowledge_point_id", "")
        )
        profile_cache_status = self.student_models.status(student_id)
        if profile_cache_status["event_count"] and profile_cache_status["needs_refresh"]:
            self._trigger_profile_refresh(student_id)
        return {
            "status": "ok",
            "student_id": student_id,
            "xingchen_mode": self.gateway.mode,
            "has_upstream": bool(state.get("upstream_payload")),
            "latest_learning_result": state.get("latest_learning_result"),
            "latest_review_result": state.get("latest_review_result"),
            "learning_path": state.get("learning_path", {}),
            "profile": profile,
            "settings": settings,
            "notification_unread_count": notifications["unread_count"],
            "current_favorite": self.domain.is_favorite(student_id, current_knowledge_id),
            "student_model_status": profile_cache_status,
            "updated_at": state.get("updated_at", ""),
        }

    def ingest_upstream(self, payload: dict[str, Any]) -> dict[str, Any]:
        student_id, session_id = self._require_identity(payload)
        event_id, is_new = self.store.record_upstream(payload)
        if not is_new:
            return {
                "status": "duplicate",
                "event_id": event_id,
                "student_id": student_id,
                "dispatched": {},
            }
        payload = {**payload, **self.domain.ingest_context(payload)}
        state = self.store.get_student_state(student_id)
        state["upstream_payload"] = deep_merge(as_dict(state.get("upstream_payload")), payload)
        state["session_id"] = session_id
        state["updated_at"] = utc_now()
        self.store.save_student_state(student_id, state)

        dispatched: dict[str, Any] = {}
        evaluation = as_dict(payload.get("validated_evaluation"))
        if str(evaluation.get("evaluation_status", "")).lower() == "incorrect":
            dispatched["review"] = self.run_review(payload)
        diagnostic = as_dict(payload.get("diagnostic_result"))
        has_goal = resolve_learning_goal(as_dict(payload.get("learning_goal"))) is not None
        if as_list(diagnostic.get("weak_points")) or has_goal:
            learning_request = dict(payload)
            learning_request["event_type"] = "initialize_learning"
            dispatched["learning"] = self.run_learning(learning_request)
        if not dispatched:
            self.student_models.increment_event(student_id)
            self._trigger_profile_refresh(student_id)
        return {
            "status": "accepted",
            "event_id": event_id,
            "student_id": student_id,
            "dispatched": dispatched,
        }

    def _prepare_learning_workflow_context(
        self, context: dict[str, Any], state: dict[str, Any]
    ) -> None:
        """Map persisted application state to the unified Flow's learning contract."""
        event_type = str(context.get("event_type", "initialize_learning")).strip()
        action_by_event = {
            "initialize_learning": "first",
            "continue_learning": "continue",
            "show_example": "example",
            "show_steps": "steps",
            "switch_explanation": "alternative",
            "request_video": "alternative",
            "request_text": "alternative",
            "check_feedback": "check_answer",
        }
        learner_action = action_by_event.get(event_type, "continue")

        target = as_dict(context.get("current_knowledge_point"))
        path = as_dict(context.get("learning_path"))
        path_items = [item for item in as_list(path.get("items")) if isinstance(item, dict)]
        if not target:
            target = next(
                (item for item in path_items if str(item.get("status", "")) == "current"),
                {},
            )
        requested_target_id = str(context.get("target_knowledge_point_id", "")).strip()
        if requested_target_id:
            target = next(
                (
                    item for item in path_items
                    if str(item.get("knowledge_point_id", "")) == requested_target_id
                ),
                {"knowledge_point_id": requested_target_id},
            )
        if not target:
            weak_points = as_list(as_dict(context.get("diagnostic_result")).get("weak_points"))
            target = next((item for item in weak_points if isinstance(item, dict)), {})

        target_id = str(target.get("knowledge_point_id", "")).strip()
        target_name = str(target.get("knowledge_point_name", "")).strip() or target_id
        learning_target = {
            **as_dict(context.get("learning_target")),
            "knowledge_point_id": target_id,
            "knowledge_point_name": target_name,
            "topic": str(target.get("topic") or target_name),
        }

        teaching_history = as_dict(state.get("teaching_history"))
        history_events = [
            item for item in as_list(teaching_history.get("events")) if isinstance(item, dict)
        ]
        previous_modes = [
            str(item.get("teaching_mode", "")).strip()
            for item in history_events
            if str(item.get("teaching_mode", "")).strip()
        ]
        ineffective_modes = [
            str(item.get("teaching_mode", "")).strip()
            for item in history_events
            if str(item.get("effect", "")) in {"not_understood", "ineffective"}
            and str(item.get("teaching_mode", "")).strip()
        ]
        check_result = as_dict(context.get("check_result"))
        learning_state = {
            **as_dict(context.get("learning_state")),
            "learning_path": path,
            "current_knowledge_point": target,
            "previous_explanation_modes": previous_modes[-8:],
            "ineffective_modes": ineffective_modes[-8:],
            "resume_focus": str(
                context.get("feedback")
                or check_result.get("feedback")
                or context.get("previous_mode")
                or ""
            ),
            "check_result": check_result,
            "learner_answer": str(
                context.get("selected_answer") or check_result.get("selected_answer") or ""
            ),
        }
        knowledge_state = {
            **as_dict(context.get("knowledge_state")),
            "knowledge_point_id": target_id,
            "mastery": target.get("mastery", 0),
            "attempt_count": target.get("attempt_count", 0),
        }
        profile = as_dict(context.get("student_profile")) or as_dict(
            self.domain.profile(str(context.get("student_id", ""))).get("profile")
        )

        # The upstream assessment has an error-remediation route. It must never
        # leak into a later learning action when the unified Flow is in use.
        context.update({
            "route_type": "first_learning" if learner_action == "first" else "resume_learning",
            "workflow_mode": "learning",
            "learner_action": learner_action,
            "current_knowledge_point": target,
            "learning_target": learning_target,
            "learning_state": learning_state,
            "knowledge_state": knowledge_state,
            "student_profile": profile,
            "history_memory": {
                **as_dict(context.get("history_memory")),
                "events": history_events[-100:],
            },
            "resume_state": as_dict(context.get("resume_state")),
        })

    def run_learning(self, incoming: dict[str, Any], scene: str = "learn") -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        state = self.store.get_student_state(student_id)
        upstream = as_dict(state.get("upstream_payload"))
        context = deep_merge(upstream, incoming)
        if not as_dict(incoming.get("current_knowledge_point")):
            stored_target = as_dict(state.get("current_knowledge_point"))
            if stored_target:
                context["current_knowledge_point"] = stored_target
        context.setdefault("session_id", state.get("session_id") or f"LEARNING-{student_id}")
        context.setdefault("lesson_run_id", f"LESSON-{uuid.uuid4().hex[:10]}")
        context.setdefault("event_type", "initialize_learning")
        context["learning_goal"] = as_dict(context.get("learning_goal")) or as_dict(state.get("learning_goal"))
        if not context["learning_goal"]:
            context["learning_goal"] = {
                "goal_id": "GOAL-CURRENT",
                "goal_type": "course",
                "goal_name": "完成当前专业实训学习目标",
            }
        context["diagnostic_result"] = as_dict(context.get("diagnostic_result"))
        context["learning_path"] = as_dict(incoming.get("learning_path")) or as_dict(state.get("learning_path"))
        context["teaching_history"] = as_dict(state.get("teaching_history"))
        context["resource_preferences"] = as_dict(state.get("resource_preferences"))
        context.update(self.domain.ingest_context(context))
        context["scene"] = scene

        if str(context.get("event_type")) == "check_feedback" and "check_result" not in context:
            # 服务端判题：忽略客户端传入的 passed，答案以服务端注册表为准
            knowledge_id = str(
                as_dict(context.get("current_knowledge_point")).get("knowledge_point_id", "")
            )
            selected = str(incoming.get("selected_answer") or "").strip()
            expected = str(CHECK_ANSWER_REGISTRY.get(knowledge_id, "") or "").strip()
            server_passed = bool(expected) and selected == expected
            context["check_result"] = {
                "status": "correct" if server_passed else "not_understood",
                "selected_answer": incoming.get("selected_answer"),
                "feedback": incoming.get("feedback", ""),
            }
            # 阶段检查作答落库（仅前端带 question_text 的阶段检查触发，避免与练习提交重复记账）
            question_text = str(incoming.get("question_text") or "").strip()
            if question_text and selected:
                self.domain.record_choice_attempt(
                    student_id=student_id,
                    source_question_id=str(
                        incoming.get("question_id") or f"CHECK-{knowledge_id}"
                    ),
                    mode="stage_check",
                    knowledge_point_id=knowledge_id,
                    knowledge_point_name=str(
                        as_dict(context.get("current_knowledge_point")).get(
                            "knowledge_point_name", knowledge_id
                        )
                    ),
                    title=question_text[:60],
                    prompt=question_text,
                    options=as_dict(incoming.get("options")),
                    expected=expected,
                    selected=selected,
                    explanation=incoming.get("feedback", ""),
                )
        # 目标驱动（方向4）：无上游诊断、无既有路径时，按学习目标图谱生成路径
        if (
            not as_dict(context.get("current_knowledge_point"))
            and not as_list(as_dict(context.get("diagnostic_result")).get("weak_points"))
            and not as_list(as_dict(context.get("learning_path")).get("items"))
        ):
            goal_path = path_for_learning_goal(context.get("learning_goal"))
            if goal_path:
                context["current_knowledge_point"] = goal_path["items"][0]
                context["learning_path"] = goal_path
                context["goal_driven"] = True
        self._prepare_learning_workflow_context(context, state)
        self._attach_video_search("learning", context)
        self._trigger_profile_refresh(student_id)
        workflow_payload = self._learning_workflow_payload(context)
        result = self.gateway.invoke_learning_workflow(workflow_payload)
        result = self._normalize_learning_result(result, context)
        self._merge_web_sources(result)
        next_item = self._apply_check_feedback(result, context, incoming)
        result_context = context

        # A check-feedback reply may only contain a path update. Fetch the next
        # lesson with the same unified Flow so the client receives renderable content.
        if result.get("status") == "ok" and next_item:
            next_knowledge_id = str(next_item.get("knowledge_point_id", ""))
            has_next_lesson = (
                str(result.get("knowledge_point_id", "")) == next_knowledge_id
                and bool(str(result.get("lesson_title", "")).strip())
                and bool(as_list(result.get("content_blocks")))
            )
            if not has_next_lesson:
                continuation_context = deep_merge(
                    context,
                    {
                        "event_type": "continue_learning",
                        "current_knowledge_point": next_item,
                        "learning_path": as_dict(result.get("learning_path")),
                        "completed_knowledge_point_id": result.get("knowledge_point_id", ""),
                    },
                )
                # The completed lesson's target remains in the original context.
                # Rebuild the unified Flow contract before requesting the next lesson.
                self._prepare_learning_workflow_context(continuation_context, state)
                self._attach_video_search("learning", continuation_context)
                continuation_payload = self._learning_workflow_payload(continuation_context)
                continuation = self.gateway.invoke_learning_workflow(continuation_payload)
                continuation = self._normalize_learning_result(continuation, continuation_context)
                if continuation.get("status") == "ok":
                    continuation["learning_path"] = as_dict(result.get("learning_path"))
                    continuation["path_update"] = {
                        **as_dict(continuation.get("path_update")),
                        **as_dict(result.get("path_update")),
                    }
                    continuation["check_feedback"] = as_dict(result.get("check_feedback"))
                    continuation["completed_knowledge_point_id"] = result.get(
                        "knowledge_point_id", ""
                    )
                    result = continuation
                    result_context = continuation_context
                else:
                    result.update(
                        {
                            "knowledge_point_id": next_knowledge_id,
                            "lesson_title": str(
                                next_item.get("knowledge_point_name", "下一学习节点")
                            ),
                            "lesson_objective": "下一学习节点已解锁，等待讲解内容生成。",
                            "content_blocks": [
                                {
                                    "type": "notice",
                                    "title": "下一节已解锁",
                                    "content": continuation.get(
                                        "user_message",
                                        "下一节讲解暂未生成，请稍后重试。",
                                    ),
                                }
                            ],
                        }
                    )
        if result.get("status") == "ok":
            self._merge_kb_sources(result, result_context)
            result = self.domain.record_explanation(student_id, scene, result_context, result)
        if str(result.get("status")) in {"needs_web_search", "knowledge_unavailable"}:
            result["knowledge_gap"] = True
            result.setdefault(
                "user_message",
                "当前知识点暂时没有可用知识依据，系统已请求联网检索；若仍无结果，请换一个切入点或联系老师补充教学资料。",
            )
        self.store.record_run(student_id, "learning", workflow_payload, result)

        # 仅对可渲染状态更新持久状态；失败（system_retryable/fatal_internal）保留旧状态，
        # 避免失败结果覆盖上次成功的讲解与教学历史（P1-4）
        successful_statuses = {"ok", "needs_web_search", "knowledge_unavailable"}
        if str(result.get("status")) in successful_statuses:
            state["latest_learning_result"] = result
            state["learning_goal"] = context["learning_goal"]
            state["learning_path"] = as_dict(result.get("learning_path")) or context["learning_path"]
            path_items = as_list(as_dict(result.get("learning_path")).get("items"))
            current_path_item = next(
                (
                    item
                    for item in path_items
                    if isinstance(item, dict) and str(item.get("status", "")) == "current"
                ),
                {},
            )
            if current_path_item:
                state["current_knowledge_point"] = current_path_item
            elif str(as_dict(result.get("path_update")).get("current_status", "")) == "completed_all":
                state["current_knowledge_point"] = {}
            else:
                state["current_knowledge_point"] = {
                    "knowledge_point_id": result.get("knowledge_point_id", ""),
                    "knowledge_point_name": result.get("lesson_title", ""),
                }
            history = as_dict(state.get("teaching_history"))
            history_events = as_list(history.get("events"))
            history_events.append(
                {
                    "event_type": context.get("event_type"),
                    "knowledge_point_id": result.get(
                        "completed_knowledge_point_id", result.get("knowledge_point_id", "")
                    ),
                    "teaching_mode": as_dict(result.get("teaching_plan")).get("primary_mode", ""),
                    "effect": (
                        "passed"
                        if str(context.get("event_type")) == "check_feedback"
                        and str(as_dict(context.get("check_result")).get("status", "")).lower()
                        == "correct"
                        else "not_understood"
                        if str(context.get("event_type")) == "check_feedback"
                        else "pending"
                    ),
                    "created_at": utc_now(),
                }
            )
            state["teaching_history"] = {"events": history_events[-100:]}
        state["updated_at"] = utc_now()
        self.store.save_student_state(student_id, state)
        self.student_models.increment_event(student_id)
        self._trigger_profile_refresh(student_id)
        return result

    def run_review(self, incoming: dict[str, Any], scene: str = "error_correction") -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        if not student_id and incoming.get("resume_token"):
            student_id = str(incoming.get("resume_student_id", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        state = self.store.get_student_state(student_id)
        upstream = as_dict(state.get("upstream_payload"))
        if incoming.get("resume_token"):
            # P1-6 缓解：远程工作流令牌为 zlib+base64 自包含格式，校验内嵌身份与请求一致，
            # 拦截跨学生/跨会话令牌重放；无法解码的令牌（mock 服务端随机令牌）跳过，
            # mock 路径本身已绑定校验
            embedded = self._inspect_workflow_resume_token(incoming.get("resume_token"))
            if embedded is not None:
                embedded_student = str(embedded.get("student_id") or "").strip()
                embedded_session = str(embedded.get("session_id") or "").strip()
                request_session = str(incoming.get("session_id") or "").strip()
                if embedded_student and embedded_student != student_id:
                    raise ApiError(
                        403, "INVALID_RESUME_TOKEN",
                        "恢复令牌与当前学生不匹配，请重新提交测验结果。",
                    )
                if embedded_session and request_session and embedded_session != request_session:
                    raise ApiError(
                        403, "INVALID_RESUME_TOKEN",
                        "恢复令牌与当前会话不匹配，请重新提交测验结果。",
                    )
            identifiers = self.domain.ingest_context(upstream)
            context = {
                "resume_token": incoming.get("resume_token"),
                "clarification_reply": incoming.get("clarification_reply", ""),
                "student_id": student_id,
                "session_id": incoming.get("session_id") or state.get("session_id", ""),
                **identifiers,
            }
            # resume 分支恢复完整学情上下文：策略决策（_remediation_workflow_payload）
            # 与知识检索（_knowledge_point/_retrieve_knowledge_text）依赖这些字段，
            # 缺失会导致 remote 模式 mastery/错因/知识依据全部退化
            for domain_key in ("question_snapshot", "current_attempt", "validated_evaluation"):
                if domain_key in upstream:
                    context[domain_key] = upstream[domain_key]
        else:
            context = deep_merge(upstream, incoming)
            for domain_key in ("question_snapshot", "current_attempt", "validated_evaluation"):
                if domain_key in incoming:
                    context[domain_key] = incoming[domain_key]
            context.setdefault("route_type", "error_remediation")
            context.setdefault("attempt_id", f"ATTEMPT-{uuid.uuid4().hex[:10]}")
            context.update(self.domain.ingest_context(context))
            self._attach_video_search("review", context)
        context["scene"] = scene
        self._trigger_profile_refresh(student_id)
        workflow_payload = self._remediation_workflow_payload(context)
        result = self.gateway.invoke_remediation_workflow(workflow_payload)
        result = self._normalize_review_result(result, context, state)
        self._merge_web_sources(result)
        if result.get("status") == "ok":
            self._merge_kb_sources(result, context)
            result = self.domain.record_explanation(student_id, scene, context, result)
        if str(result.get("status")) in {"needs_web_search", "knowledge_unavailable"}:
            result["knowledge_gap"] = True
            result.setdefault(
                "user_message",
                "当前知识点暂时没有可用知识依据，系统已请求联网检索；若仍无结果，请换一个切入点或联系老师补充教学资料。",
            )
        self.store.record_run(student_id, "review", workflow_payload, result)
        state["latest_review_result"] = result
        if result.get("status") == "needs_clarification":
            state["pending_resume_token"] = result.get("resume_token", "")
        elif result.get("status") in {"ok", "ended_by_user"}:
            state.pop("pending_resume_token", None)
        state["updated_at"] = utc_now()
        self.store.save_student_state(student_id, state)
        self.student_models.increment_event(student_id)
        self._trigger_profile_refresh(student_id)
        return result

    def run_explanation(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id, session_id = self._require_identity(incoming)
        scene = str(incoming.get("scene", "")).strip()
        supported = {"learn", "re_explain", "error_correction", "stage_error", "prerequisite", "summary"}
        if scene not in supported:
            raise ApiError(400, "INVALID_SCENE", "scene 必须是六个受支持场景之一")
        if scene in {"stage_error", "prerequisite"}:
            return {
                "status": "not_implemented",
                "code": "SCENE_NOT_READY",
                "scene": scene,
                "student_id": student_id,
                "session_id": session_id,
                "user_message": "该讲解场景已保留，当前版本尚未启用。",
            }
        if scene == "summary":
            records = self.domain.records(student_id)
            return {
                "status": "ok",
                "scene": scene,
                "student_id": student_id,
                "session_id": session_id,
                "summary": {
                    "explanation_count": len(records["explanations"]),
                    "attempt_count": len(records["attempts"]),
                },
            }
        if scene == "learn":
            request = {**incoming, "event_type": incoming.get("event_type") or "initialize_learning"}
            return self.run_learning(request, scene=scene)
        if scene == "error_correction":
            return self.run_review(incoming, scene=scene)

        source_session_id = str(incoming.get("source_explanation_session_id", "")).strip()
        if not source_session_id:
            raise ApiError(
                400,
                "MISSING_SOURCE_EXPLANATION_SESSION",
                "换种讲法需要提供原讲解会话",
            )
        source = self.domain.explanation_context(source_session_id, student_id)
        if not source:
            raise ApiError(
                404,
                "SOURCE_EXPLANATION_NOT_FOUND",
                "未找到可用于换种讲法的原讲解会话",
            )
        request = {**incoming, "event_type": "switch_explanation"}
        if source.get("workflow_mode") == "learning":
            request["previous_mode"] = source.get("delivery_mode", "")
            return self.run_learning(request, scene=scene)
        if source.get("workflow_mode") in {"review", "remediation"}:
            return self.run_review(request, scene=scene)
        raise ApiError(
            409,
            "INVALID_SOURCE_EXPLANATION",
            "原讲解会话缺少有效的工作流类型",
        )

    def search_knowledge_api(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = max(1, min(int(params.get("limit") or 5), 20))
        except (TypeError, ValueError):
            limit = 5
        items = self.domain.search_knowledge(
            query=str(params.get("q") or ""),
            knowledge_point_id=str(params.get("knowledge_point_id") or ""),
            action=str(params.get("action") or ""),
            category=str(params.get("category") or ""),
            limit=limit,
        )
        return {
            "status": "ok",
            "query": str(params.get("q") or ""),
            "total": len(items),
            "items": items,
        }

    def chat(self, incoming: dict[str, Any]) -> dict[str, Any]:
        """对话页：多轮上下文 + 模糊提问澄清 + 知识库 RAG 回答（比赛硬要求）。

        输入：message（学生提问）、session_id（可选，默认 default）
        输出：
        - 模糊提问（"这个怎么弄"等）→ status=needs_clarification + clarify_options
        - 明确提问 → status=ok + answer（AI 生成标识）+ sources[]（知识库命中，带来源）
        多轮：按 (student_id, session_id) 保存最近 8 轮问答；短消息/指代词
        自动拼接上一轮提问作为检索上下文（如"那 getter 方法呢"承接"封装是什么"）。
        """
        message = str(incoming.get("message") or "").strip()
        if not message:
            raise ApiError(400, "MISSING_MESSAGE", "请输入要咨询的问题")
        student_id = str(incoming.get("student_id") or "").strip()
        session_id = str(incoming.get("session_id") or "default").strip()
        project_id = str(incoming.get("project_id") or "").strip()
        workspace_context = as_dict(incoming.get("workspace_context"))
        project = self._require_project(student_id, project_id) if project_id else None
        project_state = as_dict(project.get("state")) if project else {}
        assistant_mode = str(incoming.get("assistant_mode") or "education").strip().lower()
        if assistant_mode not in {"education", "general"}:
            assistant_mode = "education"
        use_knowledge_base = bool(incoming.get("use_knowledge_base", True))
        allow_web_search = bool(incoming.get("allow_web_search", True))
        force_web_search = bool(incoming.get("force_web_search", False)) or any(
            word in message.lower()
            for word in ("上网搜索", "联网搜索", "网上查", "搜索一下", "最新", "官网", "近期")
        )
        if (
            assistant_mode == "education"
            and not project
            and not self._relevant_knowledge_items(message, limit=1)
            and not any(
                word in message.lower()
                for word in (
                    "学习", "学会", "想学", "掌握", "备考", "考试", "考证", "竞赛",
                    "实训", "课程", "岗位能力", "提升技能",
                )
            )
        ):
            assistant_mode = "general"

        if message in {"谢谢", "感谢", "好的", "明白了", "知道了", "收到"}:
            return {
                "status": "ok",
                "answer": "好的，我会继续结合当前项目和你刚才提供的信息来调整后续建议。",
                "ai_generated": False,
                "answer_mode": "conversation_acknowledgement",
                "session_id": session_id,
                "sources": [],
            }

        unavailable_tool = self._unavailable_external_tool(message)
        if unavailable_tool:
            return {
                "status": "ok",
                "answer": unavailable_tool,
                "ai_generated": False,
                "answer_mode": "tool_unavailable",
                "session_id": session_id,
                "sources": [],
            }

        # 多轮上下文：读取会话历史，指代消解
        state = self.store.get_student_state(student_id)
        if project:
            history = [
                {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
                for item in self.store.list_project_messages(project_id, student_id, limit=16)
                if str(item.get("content") or "").strip()
            ]
        else:
            history = [
                item
                for item in as_list(state.get("chat_history"))
                if isinstance(item, dict) and str(item.get("content") or "").strip()
            ]
        resolved = self._resolve_reference(message, history)
        active_knowledge_id = str(workspace_context.get("knowledge_point_id") or "")
        candidate_project = bool(
            project and str(project_state.get("support_level") or "") == "generated_scaffold"
        )
        question_action = ""
        if any(word in message for word in ("为什么", "是什么", "原理", "作用")):
            question_action = "concept"
        elif any(word in message for word in ("怎么", "如何", "步骤", "怎么做")):
            question_action = "steps"
        elif any(word in message for word in ("报错", "错误", "易错", "注意")):
            question_action = "warning"
        elif any(word in message for word in ("例子", "示例", "代码")):
            question_action = "example"
        if assistant_mode == "general" or not use_knowledge_base or candidate_project:
            items = []
        elif active_knowledge_id:
            items = self.domain.search_knowledge(
                query=resolved,
                knowledge_point_id=active_knowledge_id,
                action=question_action,
                limit=3,
            )
            if not items:
                items = self.domain.search_knowledge(
                    knowledge_point_id=active_knowledge_id,
                    action=question_action,
                    limit=3,
                )
        else:
            items = self._relevant_knowledge_items(resolved, limit=3)

        # 1) 模糊提问识别：疑问词 + 缺少领域知识点关键词 → 引导澄清（用原始消息判断）
        vague_words = ("怎么弄", "怎么办", "怎么做", "咋办", "啥意思", "是什么呀", "怎么用", "怎么实现")
        knowledge_hint = ("java", "类", "对象", "封装", "继承", "多态", "接口", "集合",
                          "异常", "io", "成绩", "平均分", "缺考", "getter", "构造器", "数组")
        has_hint = bool(active_knowledge_id) or any(kw in message.lower() for kw in knowledge_hint)
        is_vague = any(v in message for v in vague_words) and not has_hint
        if assistant_mode == "education" and (is_vague or len(message) <= 4):
            return {
                "status": "needs_clarification",
                "message": "你问的有点笼统，先确认一下你想了解的具体方向：",
                "clarify_options": [
                    {"id": "concept", "label": "概念/原理（如什么是封装）"},
                    {"id": "code", "label": "怎么写代码（如如何排除缺考统计）"},
                    {"id": "error", "label": "报错/易错点（如空指针）"},
                ],
            }

        web_answer = None
        if allow_web_search and (force_web_search or (not items and assistant_mode == "education")):
            web_answer = self._chat_web_search(
                resolved,
                general_search=assistant_mode == "general",
            )
            if web_answer and assistant_mode == "education":
                if bool(incoming.get("persist_history", True)):
                    self._save_chat_history(
                        student_id, state, history, message, web_answer["answer"]
                    )
                return web_answer
            if force_web_search and not web_answer:
                return {
                    "status": "ok",
                    "answer": (
                        (
                            "本次联网检索没有取得可用的网页结果，"
                            if assistant_mode == "general"
                            else "本次联网检索没有取得可核验的白名单来源，"
                        )
                        +
                        "因此我不会用本地旧知识冒充最新搜索结果。"
                        "你可以稍后重试，或换成更具体的官网、标准名称和关键词。"
                    ),
                    "ai_generated": False,
                    "answer_mode": "web_search_unavailable",
                    "web_searched": True,
                    "session_id": session_id,
                    "sources": [],
                }

        # 2) remote 模式：生成类上平台（对话问答工作流，携带多轮历史）
        validated_project = not project or str(project_state.get("support_level") or "") == "validated_graph"
        if self.gateway.mode == "remote" and (assistant_mode == "general" or validated_project):
            try:
                context_memory = history[-6:]
                if project:
                    path_items = [
                        str(item.get("knowledge_point_name") or "")
                        for item in as_list(as_dict(project_state.get("learning_path")).get("items"))
                        if isinstance(item, dict)
                    ]
                    context_memory = [{
                        "role": "system",
                        "content": json_text({
                            "current_project": str(project.get("goal_name") or ""),
                            "learning_path": path_items,
                            "learner_preferences": as_dict(project_state.get("learner_preferences")),
                            "workspace": workspace_context,
                        }),
                    }] + context_memory
                project_context_text = ""
                if project:
                    project_context_text = (
                        "\n\n【当前项目运行上下文】"
                        + json_text({
                            "goal_name": str(project.get("goal_name") or ""),
                            "learning_path": path_items,
                            "learner_preferences": as_dict(project_state.get("learner_preferences")),
                            "learner_self_reports": as_list(project_state.get("learner_self_reports"))[-5:],
                            "workspace": workspace_context,
                            "instruction": (
                                "可依据这些信息回答学习安排、节奏和下一步建议；"
                                "自报基础均未验证，不得表述为已经掌握。"
                            ),
                        })
                    )
                source_items = items
                if web_answer:
                    source_items = as_list(web_answer.get("search_items"))
                source_context = "\n".join(
                    f"【{i.get('title')}】{i.get('content') or i.get('snippet') or ''} 来源：{i.get('url') or i.get('locator') or ''}"
                    for i in source_items
                    if isinstance(i, dict)
                )
                result = self.gateway.invoke_chat_workflow({
                    "message": message,
                    "student_id": student_id,
                    "student_profile": as_dict(self.domain.profile(student_id).get("profile")),
                    "assistant_mode": assistant_mode,
                    "source_kind": "web" if web_answer else ("knowledge_base" if items else "none"),
                    "kb_text": source_context + project_context_text,
                    "history_memory": context_memory,
                })
                result_data = as_dict(result)
                answer = str(
                    result_data.get("message")
                    or result_data.get("answer")
                    or result_data.get("user_message")
                    or ""
                ).strip()
                if answer:
                    if assistant_mode == "general" and any(
                        marker in answer
                        for marker in (
                            "知识库暂未覆盖",
                            "只回答 Java",
                            "专注 Java",
                            "与 Java/课程无关",
                        )
                    ):
                        answer = ""
                if answer:
                    if bool(incoming.get("persist_history", True)):
                        self._save_chat_history(student_id, state, history, message, answer)
                    return {
                        "status": "ok",
                        "answer": answer,
                        "ai_generated": True,
                        "answer_mode": (
                            "web_synthesis"
                            if web_answer
                            else "general_generation"
                            if assistant_mode == "general"
                            else "education_generation"
                        ),
                        "web_searched": bool(web_answer),
                        "session_id": session_id,
                        "sources": (
                            as_list(web_answer.get("sources"))
                            if web_answer
                            else self._knowledge_sources(items)
                        ),
                    }
            except Exception:
                # 工作流失败降级本地 RAG，保证演示不中断
                pass

        if assistant_mode == "general":
            if web_answer:
                if bool(incoming.get("persist_history", True)):
                    self._save_chat_history(
                        student_id, state, history, message, str(web_answer["answer"])
                    )
                return web_answer
            return {
                "status": "ok",
                "answer": (
                    "通用生成服务当前不可用。我仍可继续处理学习项目、测评、路径和已接入知识库的问答；"
                    "翻译、改写、总结等通用任务需要对话工作流恢复后才能可靠完成。"
                ),
                "ai_generated": False,
                "answer_mode": "general_generation_unavailable",
                "session_id": session_id,
                "sources": [],
            }

        # 3) 明确提问（本地 RAG 兜底 / mock 模式）：知识库检索（按知识点优先，命中前 3）
        if not items:
            # 3.1) 白名单联网检索兜底（方案 A：检索留本地、白名单域名、来源引用）
            web_answer = self._chat_web_search(resolved) if allow_web_search else None
            if web_answer:
                if bool(incoming.get("persist_history", True)):
                    self._save_chat_history(student_id, state, history, message, web_answer["answer"])
                return web_answer
            if project and str(project_state.get("support_level") or "") == "generated_scaffold":
                return {
                    "status": "ok",
                    "answer": (
                        f"我理解你是在“{project.get('goal_name')}”项目里提问，但当前候选路径还没有绑定"
                        "经过审核的领域资料。你可以问我调整学习顺序、记录已有基础或学习时间；"
                        "涉及知识结论时，我需要先接入可靠来源，不能用其他领域资料代答。"
                    ),
                    "ai_generated": False,
                    "answer_mode": "scope_boundary",
                    "session_id": session_id,
                    "sources": [],
                }
            return {
                "status": "ok",
                "answer": "知识库暂未检索到与「" + message + "」直接相关的内容。你可以换个问法，或进入「学情诊断」定位薄弱知识点。",
                "ai_generated": False,
                "sources": [],
            }
        # 组装回答：主条目内容 + 来源标注（AI 生成标识）
        answer = self._compose_local_chat_answer(message, items, workspace_context)
        if bool(incoming.get("persist_history", True)):
            self._save_chat_history(student_id, state, history, message, answer)
        return {
            "status": "ok",
            "answer": answer,
            "ai_generated": False,
            "answer_mode": "local_rag",
            "session_id": session_id,
            "sources": self._knowledge_sources(items),
        }

    @staticmethod
    def _compose_local_chat_answer(
        message: str, items: list[dict[str, Any]], workspace_context: dict[str, Any]
    ) -> str:
        primary = items[0]
        title = str(primary.get("title") or "当前知识点").strip()
        content = str(primary.get("content") or "").strip()
        if any(word in message for word in ("怎么", "如何", "步骤", "怎么做")):
            answer = f"针对“{title}”，可以先按三步处理：\n1. 明确它解决的问题和使用边界；\n2. 对照一个最小示例完成一次练习；\n3. 用结果或报错验证是否真正掌握。\n\n知识库要点：{content}"
        elif any(word in message for word in ("为什么", "原因")):
            answer = f"先说结论：{content}\n\n之所以这样做，是为了让“{title}”的职责、边界和错误处理保持一致。"
        elif any(word in message for word in ("区别", "比较", "不同")) and len(items) > 1:
            second = items[1]
            answer = (
                f"可以从用途上区分：\n- {title}：{content}\n"
                f"- {second.get('title') or '相关概念'}：{second.get('content') or ''}\n\n"
                "建议再用同一个小案例分别实现一次，差异会更直观。"
            )
        else:
            answer = f"你问的是“{title}”。{content}"
        active_name = str(workspace_context.get("knowledge_point_name") or "").strip()
        if active_name:
            answer += f"\n\n我已结合当前打开的“{active_name}”章节回答。"
        return answer

    @staticmethod
    def _knowledge_sources(items: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "title": str(item.get("source") or "知识库"),
                "locator": str(item.get("locator") or ""),
                "knowledge_point_id": str(item.get("knowledge_point_id") or ""),
                "quote_text": str(item.get("title") or ""),
                "verification_state": "knowledge_base",
            }
            for item in items
            if isinstance(item, dict)
        ]

    @staticmethod
    def _unavailable_external_tool(message: str) -> str:
        lowered = str(message or "").lower()
        execution_requests = (
            ("订机票", "机票预订"),
            ("订酒店", "酒店预订"),
            ("点外卖", "外卖下单"),
            ("帮我付款", "付款"),
            ("替我付款", "付款"),
            ("发邮件", "邮件发送"),
            ("发消息", "消息发送"),
        )
        for marker, capability in execution_requests:
            if marker in lowered:
                return (
                    f"我目前没有接入{capability}工具，不能替你执行真实操作。"
                    "我可以帮你比较方案、整理步骤或起草内容，但在接入相应账号授权和确认机制前不会假装已经完成。"
                )
        return ""

    def _resolve_reference(self, message: str, history: list[dict[str, Any]]) -> str:
        """多轮指代消解：短消息或指代词开头时，拼接最近一次用户提问作为检索上下文。

        例：先问"封装是什么"，再问"那 getter 方法呢" → 检索"封装是什么 那 getter 方法呢"，
        使第二问命中封装相关条目而非泛泛查询。
        """
        user_msgs = [
            str(item.get("content") or "").strip()
            for item in history
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ]
        if not user_msgs:
            return message
        stripped = message.strip()
        if len(stripped) > 10 and not any(
            stripped.startswith(word) for word in ("那", "它", "这个", "这些", "其", "然后")
        ):
            return message
        # 提取短消息核心词（去掉指代词/疑问词），优先命中本轮主题
        core = stripped
        for word in ("那", "呢", "是什么", "是啥", "怎么", "如何", "这个", "这些", "它", "的", "呀", "吗"):
            core = core.replace(word, " ")
        core = " ".join(core.split())
        previous = user_msgs[-1]
        if core and core != stripped:
            return f"{core} {previous}".strip()
        return f"{previous} {stripped}".strip()

    def _save_chat_history(
        self,
        student_id: str,
        state: dict[str, Any],
        history: list[dict[str, Any]],
        message: str,
        answer: str,
    ) -> None:
        """把本轮问答写入会话历史（保留最近 8 轮 = 16 条），按 student 持久化。"""
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": answer})
        state["chat_history"] = history[-16:]
        self.store.save_student_state(student_id, state)

    def _chat_web_search(
        self, message: str, general_search: bool = False
    ) -> dict[str, Any] | None:
        """chat 联网检索兜底：白名单域名（bing RSS）+ 来源引用。

        仅当文档联网检索开启（doc_enabled）时启用；未命中/失败/未开启
        均返回 None，由调用方保持"知识库未检索到"兜底文案（断网自动降级）。
        检索结果仅作为补充材料引用，不参与出题。
        """
        if not self.video_search.doc_enabled:
            return None
        if general_search:
            result = self.video_search.search_general_documents(message)
        else:
            payload = {"current_knowledge_point": {"knowledge_point_name": message}}
            result = self.video_search.search_documents("chat", payload)
        if str(result.get("status")) in {"search_failed", "skipped", "no_results"}:
            return None
        web_results = [
            item
            for item in as_list(result.get("results"))
            if isinstance(item, dict) and str(item.get("url", "")).strip()
        ]
        if not web_results:
            return None
        primary = web_results[0]
        snippet = str(
            primary.get("content")
            or primary.get("snippet")
            or primary.get("title", "")
        ).strip()
        answer = (
            (
                "已为你检索到以下网页结果。它们是搜索结果，不等于已核验结论；"
                "请结合来源与发布时间判断：\n\n"
            )
            if general_search
            else "知识库暂未收录该内容，为你联网检索到以下权威资料（来源域名已核验）：\n\n"
        ) + (
            f"【{primary.get('title', '')}】\n{snippet}\n\n"
            f"详细内容请访问：{primary.get('url', '')}"
        )
        extra = web_results[1:3]
        if extra:
            extras = [str(e.get("title", "")).strip() for e in extra if e.get("title")]
            if extras:
                answer += "\n\n（更多参考：" + "、".join(f"《{t}》" for t in extras) + "）"
        sources = [
            {
                "title": str(item.get("source") or item.get("source_domain") or "联网检索"),
                "locator": str(item.get("url") or ""),
                "quote_text": str(item.get("title") or ""),
                "verification_state": (
                    "web_sourced" if general_search else "whitelisted"
                ),
                "provider": str(result.get("provider") or "bing_rss"),
            }
            for item in web_results[:4]
        ]
        return {
            "status": "ok",
            "answer": answer,
            "ai_generated": False,
            "answer_mode": "web_results",
            "web_searched": True,
            "sources": sources,
            "search_items": web_results[:4],
        }

    def growth(self, student_id: str) -> dict[str, Any]:
        """成长轨迹：KPI + 规则徽章 + 能力对比 + 时间线（全部来自真实数据）。

        数据源：
        - 学习节点/掌握度：state.learning_path.items（mastery）
        - 诊断轮次：training_cycles 表
        - 作答与纠错：attempts / explanation_sessions 表
        """
        state = self.store.get_student_state(student_id)
        path_items = as_list(as_dict(state.get("learning_path")).get("items"))
        with self.domain._lock, closing(self.domain._connect()) as connection:
            cycle_count = connection.execute(
                "SELECT COUNT(*) FROM training_cycles WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]
            attempt_rows = connection.execute(
                "SELECT a.status, a.created_at, q.title FROM attempts a "
                "JOIN question_instances q ON q.question_instance_id = a.question_instance_id "
                "WHERE a.student_id = ? ORDER BY a.created_at DESC LIMIT 50",
                (student_id,),
            ).fetchall()
            review_count = connection.execute(
                "SELECT COUNT(*) FROM explanation_sessions "
                "WHERE student_id = ? AND scene IN ('error_correction', 'post_test_review', 're_explain')",
                (student_id,),
            ).fetchone()[0]

        nodes_total = len(path_items)
        mastered = sum(1 for it in path_items if int(it.get("mastery", 0) or 0) >= 80)
        avg_mastery = round(
            sum(int(it.get("mastery", 0) or 0) for it in path_items) / nodes_total
        ) if nodes_total else 0

        # 规则徽章（未接入独立徽章表，按可验证行为计算）
        badges = [
            {"id": "encapsulation", "title": "封装入门", "desc": "封装与访问控制掌握度 ≥80%",
             "earned": any(it.get("knowledge_point_id") == "KN_JAVA_ENCAPSULATION" and int(it.get("mastery", 0) or 0) >= 80 for it in path_items)},
            {"id": "foundation", "title": "知识奠基", "desc": "掌握 3 个以上知识点节点（≥80%）",
             "earned": mastered >= 3},
            {"id": "corrector", "title": "纠错能手", "desc": "完成 3 次以上纠错讲解",
             "earned": review_count >= 3},
            {"id": "diagnosis", "title": "精准诊断", "desc": "完成 2 轮以上学情诊断",
             "earned": cycle_count >= 2},
            {"id": "first-step", "title": "迈出第一步", "desc": "完成首次作答",
             "earned": bool(attempt_rows)},
        ]

        # 能力对比：时间线前 1/3 与后 1/3 作答正确率（诊断前后变化近似）
        ordered = list(reversed(attempt_rows))  # 时间正序
        total_attempts = len(ordered)
        if total_attempts >= 2:
            split = max(1, total_attempts // 3)
            early = [r for r in ordered[:split] if str(r["status"]).lower() == "correct"]
            late = [r for r in ordered[-split:] if str(r["status"]).lower() == "correct"]
            early_rate = round(len(early) / split * 100)
            late_rate = round(len(late) / split * 100)
        else:
            early_rate = 0
            late_rate = 0

        timeline = [
            {
                "type": "attempt",
                "title": str(r["title"] or "练习作答"),
                "status": str(r["status"]),
                "created_at": str(r["created_at"] or ""),
            }
            for r in attempt_rows[:10]
        ]

        return {
            "status": "ok",
            "kpi": {
                "nodes_total": nodes_total,
                "mastered_nodes": mastered,
                "avg_mastery": avg_mastery,
                "diagnosis_rounds": cycle_count,
                "badges_earned": sum(1 for b in badges if b["earned"]),
                "badges_total": len(badges),
            },
            "badges": badges,
            "ability_comparison": {"early_rate": early_rate, "late_rate": late_rate},
            "timeline": timeline,
        }

    def profile(self, student_id: str) -> dict[str, Any]:
        return self.domain.profile(student_id)

    def notifications(self, student_id: str) -> dict[str, Any]:
        return self.domain.notifications(student_id)

    def mark_notification_read(self, student_id: str, notification_id: str) -> dict[str, Any]:
        return self.domain.mark_notification_read(student_id, notification_id)

    def records(self, student_id: str) -> dict[str, Any]:
        return self.domain.records(student_id)

    def settings_for(self, student_id: str) -> dict[str, Any]:
        return self.domain.settings(student_id)

    def save_settings(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        return self.domain.save_settings(student_id, incoming)

    def toggle_favorite(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        knowledge_id = str(incoming.get("knowledge_point_id", "")).strip()
        if not knowledge_id:
            raise ApiError(400, "MISSING_KNOWLEDGE_POINT", "knowledge_point_id 不能为空")
        return self.domain.toggle_favorite(
            student_id,
            knowledge_id,
            str(incoming.get("title") or knowledge_id),
            bool(incoming.get("favorite")),
        )

    def sources(self, student_id: str, explanation_session_id: str) -> dict[str, Any]:
        items = self.domain.get_sources(explanation_session_id, student_id)
        if not items:
            raise ApiError(404, "SOURCES_NOT_FOUND", "未找到当前讲解的来源记录")
        return {
            "status": "ok",
            "explanation_session_id": explanation_session_id,
            "items": items,
        }

    def _explanation_sections(self, context: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        mode = str(context.get("workflow_mode") or "")
        if mode == "learning":
            blocks = [
                block for block in as_list(context.get("content_blocks")) if isinstance(block, dict)
            ]
            return "learning", blocks
        steps = [
            step for step in as_list(context.get("explanation_steps")) if isinstance(step, dict)
        ]
        if steps:
            return "review", [
                {
                    "type": "step",
                    "index": index,
                    "title": step.get("title", f"讲解步骤 {index}"),
                    "content": step.get("content", ""),
                    "evidence": step.get("evidence", ""),
                }
                for index, step in enumerate(steps, start=1)
            ]
        return "review", []

    def stream_explanation_sections(
        self, student_id: str, session_id: str
    ) -> tuple[str, list[dict[str, Any]], str]:
        context = self.domain.explanation_context(session_id, student_id)
        if not context:
            raise ApiError(404, "EXPLANATION_NOT_FOUND", "未找到该讲解会话")
        kind, sections = self._explanation_sections(context)
        return kind, sections, str(context.get("workflow_mode") or "")

    VAGUE_QUESTION_PHRASES = frozenset(
        {
            "这个怎么弄",
            "为什么",
            "为啥",
            "啥意思",
            "什么意思",
            "怎么办",
            "咋办",
            "然后呢",
            "所以呢",
            "到底",
            "是什么",
        }
    )

    def _compose_follow_up(
        self,
        context: dict[str, Any],
        selection: str,
        question: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        kind, sections = self._explanation_sections(context)
        knowledge_name = str(
            context.get("lesson_title")
            or context.get("knowledge_point_name")
            or context.get("target_error", {}).get("knowledge_point_name")
            or "当前知识点"
        )
        selected_block = None
        selection_text = selection.strip()
        if selection_text:
            for section in sections:
                haystack = " ".join(
                    [
                        str(section.get("title", "")),
                        str(section.get("content", "")),
                        " ".join(str(item) for item in as_list(section.get("items"))),
                    ]
                )
                if selection_text in haystack:
                    selected_block = section
                    break
            if selected_block is None and sections:
                selected_block = sections[0]
        normalized_question = question.strip("，。！？!?、 ")
        if len(normalized_question) <= 6 or normalized_question in self.VAGUE_QUESTION_PHRASES:
            return {
                "answer": "你的问题有点笼统，我想先确认你具体卡在哪一环，再给出针对性讲解。",
                "clarification": True,
                "follow_up_questions": [
                    "这个概念的定义是什么",
                    "它在岗位任务里怎么用",
                    "常见的易错点有哪些",
                ],
            }
        intro = f"关于你选中的「{selection_text}」" if selection_text else "关于你提的问题"
        block_lines: list[str] = []
        if selected_block:
            block_title = str(selected_block.get("title") or "本节内容")
            block_lines.append(f"**{block_title}**")
            content = str(selected_block.get("content") or "")
            if content:
                block_lines.append(content)
            items = [
                str(item)
                for item in as_list(selected_block.get("items"))
                if str(item).strip()
            ]
            if items:
                block_lines.append("步骤：")
                block_lines.extend(f"{index}. {item}" for index, item in enumerate(items, start=1))
            source = str(selected_block.get("source") or "")
            if source:
                block_lines.append(f"依据：{source}")
        else:
            block_lines.append(f"本节围绕「{knowledge_name}」展开，建议先把握核心规则，再对照实训任务验证。")
        answer = "\n".join([f"{intro}："] + block_lines)
        kb_items = self.domain.search_knowledge(
            query=f"{question} {selection_text}".strip(),
            knowledge_point_id=str(context.get("knowledge_point_id") or ""),
            action=self._detect_follow_up_action(question, selection_text),
            limit=3,
        )
        kb_sources: list[dict[str, str]] = []
        if kb_items:
            kb_lines: list[str] = []
            for item in kb_items:
                kb_lines.append(
                    f"- {item.get('title')}：{item.get('content')}"
                    f"（来源：{item.get('source')}"
                    + (f"，{item.get('locator')}" if item.get("locator") else "")
                    + "）"
                )
                kb_sources.append({
                    "title": str(item.get("title") or ""),
                    "source": str(item.get("source") or ""),
                    "locator": str(item.get("locator") or ""),
                    "document_id": str(item.get("document_id") or ""),
                })
            answer += "\n\n知识库依据：\n" + "\n".join(kb_lines)
        return {
            "answer": answer,
            "clarification": False,
            "kb_sources": kb_sources,
            "follow_up_questions": [
                "用岗位例子再讲一遍",
                "分步骤拆解这个过程",
                "常见易错点有哪些",
            ],
        }

    def ask_explanation(self, session_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        if not student_id:
            raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
        context = self.domain.explanation_context(session_id, student_id)
        if not context:
            raise ApiError(404, "EXPLANATION_NOT_FOUND", "未找到该讲解会话")
        question = str(incoming.get("question", "")).strip()
        selection = str(incoming.get("selection", "")).strip()
        history = [item for item in as_list(incoming.get("history")) if isinstance(item, dict)]
        if not question:
            raise ApiError(400, "MISSING_QUESTION", "追问内容不能为空")
        answer = self._compose_follow_up(context, selection, question, history)
        self.domain.add_explanation_turn(
            session_id,
            student_id,
            "user",
            {"selection": selection, "question": question, "history_depth": len(history)},
        )
        self.domain.add_explanation_turn(
            session_id, student_id, "assistant", {"answer": answer.get("answer", "")}
        )
        return {
            "status": "ok",
            "explanation_session_id": session_id,
            "mode": "local_fallback",
            **answer,
            "sources": self.domain.get_sources(session_id, student_id),
        }

    @staticmethod
    def _dimension_names() -> list[str]:
        return ["理解能力", "应用能力", "推理能力", "表达能力", "复盘能力", "迁移能力"]

    def portrait(self, student_id: str) -> dict[str, Any]:
        state = self.store.get_student_state(student_id)
        profile = self.domain.ensure_profile(student_id)
        model = self._student_model(student_id)
        path = as_dict(state.get("learning_path"))
        items = [item for item in as_list(path.get("items")) if isinstance(item, dict)]
        upstream = as_dict(state.get("upstream_payload"))
        diagnostic = as_dict(upstream.get("diagnostic_result"))
        weak_points = [
            item
            for item in as_list(diagnostic.get("weak_points"))
            if isinstance(item, dict)
        ]
        if not items:
            items = [
                {
                    "knowledge_point_id": str(item.get("knowledge_point_id") or f"KN-{index}"),
                    "knowledge_point_name": str(
                        item.get("knowledge_point_name") or f"学习节点 {index}"
                    ),
                    "knowledge_type": str(item.get("knowledge_type") or "conceptual"),
                    "mastery": int(item.get("mastery", 0) or 0),
                    "status": str(item.get("status") or "pending"),
                    "recommended_order": int(item.get("recommended_order", index) or index),
                }
                for index, item in enumerate(weak_points, start=1)
            ]
        if not items:
            items = [
                {
                    "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                    "knowledge_point_name": "封装与访问控制",
                    "knowledge_type": "conceptual",
                    "mastery": 42,
                    "status": "current",
                    "recommended_order": 1,
                }
            ]
        mastery_values = [int(item.get("mastery", 0) or 0) for item in items]
        overall_mastery = round(sum(mastery_values) / len(mastery_values)) if mastery_values else 0
        completed = sum(1 for item in items if str(item.get("status", "")) == "completed")

        activity = self.domain.explanation_sessions_for(student_id)
        day_counter: dict[str, int] = {}
        for entry in activity:
            day = str(entry.get("created_at") or "")[:10]
            if day:
                day_counter[day] = day_counter.get(day, 0) + 1
        now = datetime.now(timezone.utc)
        today = now.date()
        cursor = today
        streak = 0
        while cursor.isoformat() in day_counter:
            streak += 1
            cursor -= timedelta(days=1)
        if streak == 0:
            cursor = today - timedelta(days=1)
            while cursor.isoformat() in day_counter:
                streak += 1
                cursor -= timedelta(days=1)
        month_prefix = now.strftime("%Y-%m")
        lesson_count_this_month = sum(
            1
            for entry in activity
            if str(entry.get("created_at") or "").startswith(month_prefix)
        )
        heatmap = [
            {"date": (today - timedelta(days=offset)).isoformat(), "count": day_counter.get((today - timedelta(days=offset)).isoformat(), 0)}
            for offset in range(370, -1, -1)
        ]

        goal = (
            as_dict(state.get("learning_goal"))
            or as_dict(upstream.get("learning_goal"))
            or {
                "goal_id": "GOAL-PY-001",
                "goal_type": "course",
                "goal_name": "完成 Java 面向对象成绩管理实训",
            }
        )
        identity = {
            "name": str(profile.get("display_name") or "林同学"),
            "major": str(profile.get("program_name") or "Java 面向对象程序设计实训"),
            "learning_goal": {
                "goal_id": str(goal.get("goal_id") or "GOAL-CURRENT"),
                "goal_name": str(goal.get("goal_name") or "当前学习目标"),
                "goal_progress": round(overall_mastery / 100, 2),
            },
            "kpi": {
                "overall_mastery": overall_mastery,
                "mastered_knowledge_points": f"{completed}/{len(items)}",
                "streak_days": streak,
                "lesson_count_this_month": lesson_count_this_month,
            },
        }

        code_points = [
            item for item in items if str(item.get("knowledge_type", "")) == "code"
        ]
        conceptual_points = [
            item for item in items if str(item.get("knowledge_type", "")) != "code"
        ]
        code_avg = (
            round(sum(int(item.get("mastery", 0) or 0) for item in code_points) / len(code_points))
            if code_points
            else overall_mastery
        )
        conceptual_avg = (
            round(sum(int(item.get("mastery", 0) or 0) for item in conceptual_points) / len(conceptual_points))
            if conceptual_points
            else overall_mastery
        )
        pace = float(model.get("pace_factor", 1.0) or 1.0)
        workflow_scores = as_dict(model.get("ability_scores"))
        dimensions: list[dict[str, Any]] = []
        for label in self._dimension_names():
            entry = workflow_scores.get(label)
            if not isinstance(entry, dict):
                break
            try:
                score = float(entry.get("score"))
                confidence = float(entry.get("confidence"))
            except (TypeError, ValueError):
                break
            if not (0.0 <= score <= 100.0 and 0.0 <= confidence <= 1.0):
                break
            dimensions.append(
                {
                    "name": label,
                    "score": round(score, 1),
                    "confidence": round(confidence, 2),
                    "trend": None,
                    "evidence_count": None,
                }
            )
        if len(dimensions) == len(self._dimension_names()):
            abilities_fallback = False
        else:
            base_scores = {
                "understanding": 0.5 * conceptual_avg + 0.25 * code_avg + 15,
                "applying": 0.5 * code_avg + 0.3 * conceptual_avg + 8,
                "reasoning": 0.45 * code_avg + 0.25 * conceptual_avg + 12,
                "expressing": 0.35 * conceptual_avg + 0.2 * code_avg + 18,
                "reviewing": 0.4 * conceptual_avg + 0.25 * code_avg + 16,
                "transferring": 0.35 * (code_avg + conceptual_avg) / 2 + 12,
            }
            dimensions = [
                {
                    "name": label,
                    "score": round(
                        max(0.0, min(100.0, base_scores[key] + (4.0 if pace > 1 else -4.0))),
                        1,
                    ),
                    "confidence": None,
                    "trend": None,
                    "evidence_count": None,
                }
                for key, label in zip(
                    ["understanding", "applying", "reasoning", "expressing", "reviewing", "transferring"],
                    self._dimension_names(),
                )
            ]
            abilities_fallback = True

        style_key = str(model.get("learning_style") or "balanced")
        distributions = {
            "balanced": {"visual": 0.25, "auditory": 0.25, "kinesthetic": 0.25, "reading": 0.25},
            "visual_preferred": {"visual": 0.45, "auditory": 0.15, "kinesthetic": 0.2, "reading": 0.2},
            "procedural_learner": {"visual": 0.2, "auditory": 0.15, "kinesthetic": 0.45, "reading": 0.2},
            "example_driven": {"visual": 0.3, "auditory": 0.15, "kinesthetic": 0.2, "reading": 0.35},
        }
        distribution = distributions.get(style_key, distributions["balanced"])
        workflow_distribution = as_dict(model.get("learning_style_distribution"))
        if all(
            key in workflow_distribution
            for key in ("visual", "auditory", "kinesthetic", "reading")
        ):
            distribution_total = sum(
                float(workflow_distribution.get(key, 0.0) or 0.0)
                for key in ("visual", "auditory", "kinesthetic", "reading")
            )
            if distribution_total > 0:
                distribution = {
                    key: round(
                        float(workflow_distribution.get(key, 0.0) or 0.0) / distribution_total,
                        3,
                    )
                    for key in ("visual", "auditory", "kinesthetic", "reading")
                }
        style_summary = {
            "balanced": "偏好均衡，适合图文与案例结合",
            "visual_preferred": "偏好图示与可视化过程",
            "procedural_learner": "偏好动手实践与分步执行",
            "example_driven": "偏好案例驱动与示例先行",
        }.get(style_key, "偏好均衡")

        tags = [
            {"tag": str(tag), "weight": 0.8}
            for tag in as_list(model.get("misconception_tags"))
        ]
        error_counts: dict[str, int] = {}
        for point in as_list(diagnostic.get("error_points")):
            error_type = str(point.get("error_type") or "mixed")
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        error_breakdown = [
            {"error_type": key, "count": value} for key, value in error_counts.items()
        ]
        if not error_breakdown:
            error_breakdown = [{"error_type": "mixed", "count": max(1, len(weak_points))}]

        # 薄弱点来源：上游诊断 + 各学习项目诊断（多项目模型下学生级画像应收敛全部项目）
        for project in self.store.list_projects(student_id):
            for point in as_list(as_dict(project.get("state")).get("weak_points")):
                if isinstance(point, dict) and str(point.get("knowledge_point_id") or "").strip():
                    weak_points.append(point)

        # misconceptions 细分（对齐 LearnerState v1）：薄弱点知识点 × 错误卡，替代 mixed×N
        weak_counts: dict[str, int] = {}
        for point in weak_points:
            kp_id = str(point.get("knowledge_point_id") or "").strip()
            if not kp_id:
                continue
            weak_counts[kp_id] = weak_counts.get(kp_id, 0) + int(
                point.get("error_count", 1) or 1
            )
        misconception_items: list[dict[str, Any]] = []
        for kp_id, occurrence in weak_counts.items():
            for card in error_cards_for(kp_id):
                misconception_items.append(
                    {
                        "kc_id": kp_id,
                        "misconception_id": str(card.get("error_id") or ""),
                        "type": str(card.get("error_type") or "mixed"),
                        "description": str(
                            card.get("root_cause") or card.get("misconception_tag") or ""
                        ),
                        "severity": str(card.get("severity") or "medium"),
                        "confidence": (
                            float(card["confidence"])
                            if card.get("confidence") is not None
                            else None
                        ),
                        "occurrence_count": occurrence,
                        "status": "active",
                        "evidence": "诊断归因（错误卡匹配）",
                    }
                )

        evidence = self.domain.knowledge_evidence_stats(student_id)
        nodes = [
            {
                "id": str(item.get("knowledge_point_id") or f"KN-{index}"),
                "name": str(item.get("knowledge_point_name") or f"学习节点 {index}"),
                "mastery": int(item.get("mastery", 0) or 0),
                "type": str(item.get("knowledge_type") or "conceptual"),
                "status": str(item.get("status") or "pending"),
                "confidence": None,
                "trend": None,
                "evidence_count": evidence.get(
                    str(item.get("knowledge_point_id") or f"KN-{index}"), {}
                ).get("count"),
                "last_evidence_at": evidence.get(
                    str(item.get("knowledge_point_id") or f"KN-{index}"), {}
                ).get("last_at")
                or None,
                "is_estimated": None,
            }
            for index, item in enumerate(items, start=1)
        ]
        edges = [
            {"from": nodes[index]["id"], "to": nodes[index + 1]["id"]}
            for index in range(len(nodes) - 1)
        ]
        matrix = [
            {
                "knowledge_point": node["name"],
                "掌握": round(node["mastery"] / 100, 2),
                "基础": round((100 - node["mastery"]) / 100, 2),
                "熟练": round(1.0 if node["mastery"] >= 80 else 0.0, 2),
                "精通": 0.0,
            }
            for node in nodes
        ]

        recommendations: list[dict[str, Any]] = []
        mastery_by_point = {
            item.get("knowledge_point_id"): int(item.get("mastery", 0) or 0)
            for item in items
        }
        ordered_weak = sorted(
            weak_points,
            key=lambda point: int(point.get("priority", 0) or 0),
            reverse=True,
        )
        for index, point in enumerate(ordered_weak[:3], start=1):
            point_id = str(point.get("knowledge_point_id") or f"KN-{index}")
            point_name = str(point.get("knowledge_point_name") or point_id)
            # 掌握度统一取学习路径实时值（与图谱同源），避免两处数值不一致
            point_mastery = mastery_by_point.get(
                point_id, int(point.get("mastery", 0) or 0)
            )
            attempt_count = int(point.get("attempt_count", 0) or 0)
            reasons = []
            if attempt_count >= 2:
                reasons.append(f"连续 {attempt_count} 次同类错误")
            if point_mastery < 60:
                reasons.append(f"掌握度仅 {point_mastery}%")
            if not reasons:
                reasons.append("学习路径中的优先补强节点")
            recommendations.append(
                {
                    "type": "remediate",
                    "knowledge_point_id": point_id,
                    "title": f"先补强：{point_name}",
                    "reason": "；".join(reasons),
                    "priority": index,
                }
            )
        misconception_tags = as_list(model.get("misconception_tags"))
        if misconception_tags:
            recommendations.append(
                {
                    "type": "misconception",
                    "knowledge_point_id": "",
                    "title": f"梳理误解：{str(misconception_tags[0])}",
                    "reason": "画像中的高频误解标签，建议专项澄清",
                    "priority": len(recommendations) + 1,
                }
            )

        growth: list[dict[str, Any]] = []
        growth_index: dict[tuple[str, str], int] = {}
        for entry in activity[-20:]:
            point_id = entry.get("knowledge_point_id")
            after = mastery_by_point.get(point_id)
            if after is None:
                continue
            delta = 20 if str(entry.get("scene")) in {"review", "error_correction", "re_explain"} else 10
            day = str(entry.get("created_at") or "")[:10]
            growth_entry = {
                "at": day,
                "knowledge_point_id": point_id,
                "mastery_before": max(0, after - delta),
                "mastery_after": after,
                "is_estimated": True,
            }
            key = (day, point_id)
            if key in growth_index:
                growth[growth_index[key]] = growth_entry
            else:
                growth_index[key] = len(growth)
                growth.append(growth_entry)
        growth = growth[-8:]

        me = {dimension["name"]: dimension["score"] for dimension in dimensions}
        badges = [
            {"id": "B-01", "name": "完成首轮讲解", "unlocked": len(activity) >= 1},
            {"id": "B-02", "name": "连续学习 3 天", "unlocked": streak >= 3},
            {"id": "B-03", "name": "连续学习 7 天", "unlocked": streak >= 7},
            {"id": "B-04", "name": "本月讲解 5 次", "unlocked": lesson_count_this_month >= 5},
            {"id": "B-05", "name": "掌握首个薄弱点", "unlocked": completed >= 1},
        ]
        return {
            "status": "ok",
            "student_id": student_id,
            "identity": identity,
            "abilities": {
                "dimensions": dimensions,
                "class_average": {
                    "理解能力": 66,
                    "应用能力": 60,
                    "推理能力": 63,
                    "表达能力": 61,
                    "复盘能力": 60,
                    "迁移能力": 57,
                },
                "is_fallback": abilities_fallback,
            },
            "knowledge_mastery": {"nodes": nodes, "edges": edges, "matrix": matrix},
            "weak_points": {
                "tags": tags,
                "error_breakdown": error_breakdown,
                "source": "student_model + 上游诊断",
            },
            "learning_style": {
                **distribution,
                "summary": style_summary,
                "effective_modes": as_dict(model.get("effective_modes")),
                "is_fallback": not float(model.get("learning_style_confidence", 0.0) or 0.0),
            },
            "growth": growth,
            "recommendations": recommendations,
            "behavior": {
                "streak_days": streak,
                "heatmap": heatmap,
                "badges": badges,
            },
            "comparison": {
                "me": me,
                "class_avg": {
                    "理解能力": 66,
                    "应用能力": 60,
                    "推理能力": 63,
                    "表达能力": 61,
                    "复盘能力": 60,
                    "迁移能力": 57,
                },
                "top_student": {
                    "理解能力": 92,
                    "应用能力": 90,
                    "推理能力": 88,
                    "表达能力": 86,
                    "复盘能力": 89,
                    "迁移能力": 85,
                },
            },
            "updated_at": state.get("updated_at") or utc_now(),
            "data_evidence": self._portrait_evidence(student_id),
            # ---- LearnerState v1 对齐字段（如实缺省，不虚构） ----
            "schema_version": "1.0",
            "progress": round(overall_mastery / 100, 2),
            "summary": {
                "overall_mastery": round(overall_mastery / 100, 2),
                "mastered_kc_count": completed,
                "total_kc_count": len(items),
                "activity_count_30d": len(activity),
                "streak_days": streak,
            },
            "misconceptions": {
                "raw_summary": (
                    "mixed×" + str(len(weak_points)) if not misconception_items else ""
                ),
                "items": misconception_items,
            },
            "history_quality": {
                "mastery_before_after_available": True,
                "currently_estimated_only": True,
                "note": "confidence/trend 字段如实缺省为 null；evidence_count/last_evidence_at 来自真实作答记录",
            },
            "metadata": {
                "profile_version": "1.0",
                "source": "partner_learner_model",
                "generated_at": utc_now(),
            },
        }

    def _portrait_evidence(self, student_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """画像数字的来源证据：最近作答/纠错/讲解会话（可溯源）。"""
        evidence: list[dict[str, Any]] = []
        with self.domain._lock, closing(self.domain._connect()) as connection:
            attempt_rows = connection.execute(
                "SELECT a.status, a.created_at, q.title, q.knowledge_point_id "
                "FROM attempts a JOIN question_instances q "
                "ON q.question_instance_id = a.question_instance_id "
                "WHERE a.student_id = ? ORDER BY a.created_at DESC LIMIT ?",
                (student_id, limit),
            ).fetchall()
            for row in attempt_rows:
                evidence.append({
                    "type": "作答",
                    "title": str(row["title"] or "练习作答"),
                    "status": str(row["status"]),
                    "knowledge_point_id": str(row["knowledge_point_id"] or ""),
                    "created_at": str(row["created_at"] or ""),
                })
            if len(evidence) >= limit:
                return evidence
            session_rows = connection.execute(
                "SELECT scene, explanation_type, created_at, question_instance_id "
                "FROM explanation_sessions WHERE student_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (student_id, limit - len(evidence)),
            ).fetchall()
            for row in session_rows:
                evidence.append({
                    "type": "讲解",
                    "title": {
                        "learn": "个性化讲解",
                        "error_correction": "纠错讲解",
                        "re_explain": "换种讲法",
                        "post_test_review": "测验后讲解",
                    }.get(str(row["scene"]), str(row["scene"])),
                    "status": str(row["explanation_type"] or ""),
                    "knowledge_point_id": "",
                    "created_at": str(row["created_at"] or ""),
                })
        return evidence

    def create_practice(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id, _ = self._require_identity(incoming)
        try:
            return self.domain.create_practice(student_id, incoming)
        except ValueError as error:
            raise ApiError(400, "INVALID_PRACTICE_REQUEST", str(error)) from error

    def submit_practice_attempt(
        self, student_id: str, question_instance_id: str, incoming: dict[str, Any]
    ) -> dict[str, Any]:
        if str(incoming.get("student_id", "")).strip() != student_id:
            raise ApiError(403, "STUDENT_MISMATCH", "不能提交其他学生的题目")
        try:
            result = self.domain.submit_attempt(
                student_id, question_instance_id, str(incoming.get("answer", ""))
            )
            question = self.domain.question(question_instance_id, student_id)
            result["learning_result"] = self.run_learning(
                {
                    "student_id": student_id,
                    "session_id": incoming.get("session_id", ""),
                    "event_type": "check_feedback",
                    "passed": bool(result.get("correct")),
                    "selected_answer": incoming.get("answer", ""),
                    "feedback": (
                        "练习题作答正确"
                        if result.get("correct")
                        else "练习题作答错误，需要针对性讲解"
                    ),
                    "task_instance_id": question.get("task_instance_id", ""),
                    "current_knowledge_point": {
                        "knowledge_point_id": question.get("knowledge_point_id", ""),
                        "knowledge_point_name": question.get("title", "当前知识点"),
                    },
                },
                scene="learn",
            )
            return result
        except LookupError as error:
            raise ApiError(404, "QUESTION_NOT_FOUND", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_ANSWER", str(error)) from error

    def learning_state(self, student_id: str) -> dict[str, Any]:
        state = self.store.get_student_state(student_id)
        if not state:
            raise ApiError(404, "STUDENT_NOT_FOUND", "尚未找到该学生的学习状态")
        return {
            "status": "ok",
            "student_id": student_id,
            "learning_goal": state.get("learning_goal", {}),
            "learning_path": state.get("learning_path", {}),
            "current_knowledge_point": state.get("current_knowledge_point", {}),
            "teaching_history": state.get("teaching_history", {}),
            "updated_at": state.get("updated_at", ""),
        }

    def ensure_demo_seed(self) -> None:
        if self.gateway.mode != "mock" or not self.settings.seed_demo:
            return
        if self.store.get_student_state("STU-DEMO-001").get("upstream_payload"):
            return
        self.ingest_upstream(demo_upstream_payload())

    def _normalize_learning_result(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(result)
        # The endpoint, rather than an LLM-provided business label, owns routing.
        normalized["workflow_mode"] = "learning"
        normalized.setdefault("event_type", context.get("event_type", ""))
        target = as_dict(context.get("current_knowledge_point"))
        if not target:
            weak_points = as_list(as_dict(context.get("diagnostic_result")).get("weak_points"))
            target = weak_points[0] if weak_points and isinstance(weak_points[0], dict) else {}
        normalized.setdefault("knowledge_point_id", target.get("knowledge_point_id", ""))
        if "learning_strategy_json" in normalized and "learning_strategy" not in normalized:
            normalized["learning_strategy"] = parse_json_object(normalized["learning_strategy_json"]) or {}
        if "learning_target_json" in normalized and "learning_target" not in normalized:
            normalized["learning_target"] = parse_json_object(normalized["learning_target_json"]) or {}
        learning_target = as_dict(normalized.get("learning_target")) or as_dict(
            context.get("learning_target")
        )
        if not normalized.get("knowledge_point_id"):
            normalized["knowledge_point_id"] = learning_target.get("knowledge_point_id", "")

        # The unified v5 Flow returns a compact learning package. Adapt it to
        # the frontend's stable lesson contract so a successful answer always
        # renders the next lesson instead of only showing a success message.
        strategy = as_dict(normalized.get("learning_strategy"))
        if "teaching_plan" not in normalized:
            normalized["teaching_plan"] = {
                "primary_mode": "interactive_document",
                "reason": str(strategy.get("strategy_code") or "根据当前学习动作生成讲解"),
                "depth": str(strategy.get("explanation_depth") or "guided"),
            }
        if normalized.get("status") == "ok":
            target_name = str(
                learning_target.get("knowledge_point_name")
                or learning_target.get("topic")
                or normalized.get("knowledge_point_id")
                or "当前知识点"
            )
            normalized.setdefault("lesson_title", target_name)
            normalized.setdefault("lesson_objective", f"理解并能应用{target_name}。")
            if not as_list(normalized.get("content_blocks")):
                blocks: list[dict[str, str]] = []
                explanation = str(normalized.get("personalized_explanation", "")).strip()
                if explanation:
                    blocks.append({
                        "type": "concept",
                        "title": "核心讲解",
                        "content": explanation,
                    })
                micro_example = str(normalized.get("micro_example", "")).strip()
                if micro_example:
                    blocks.append({
                        "type": "example",
                        "title": "最小示例／步骤",
                        "content": micro_example,
                    })
                misconception = str(normalized.get("common_misconception", "")).strip()
                if misconception:
                    blocks.append({
                        "type": "warning",
                        "title": "常见误区",
                        "content": misconception,
                    })
                workplace = str(normalized.get("workplace_application", "")).strip()
                if workplace:
                    blocks.append({
                        "type": "workplace",
                        "title": "岗位应用",
                        "content": workplace,
                    })
                normalized["content_blocks"] = blocks
            check = as_dict(normalized.get("understanding_check"))
            if check and "check_request" not in normalized:
                normalized["check_request"] = {
                    "focus": str(check.get("question", "")),
                    "expected_key_points": as_list(check.get("expected_key_points")),
                }
        if "path_update" not in normalized:
            normalized["path_update"] = {}
        if "learning_path" not in normalized:
            strategy = as_dict(normalized.get("learning_strategy"))
            normalized["learning_path"] = as_dict(strategy.get("path_plan")) or as_dict(
                context.get("learning_path")
            )
        self._merge_video_resources(normalized, context)
        self._merge_document_resources(normalized, context)
        if self.gateway.mode == "mock":
            self._enrich_learning_knowledge_blocks(normalized, context)

        return normalized


    @staticmethod
    def _split_knowledge_steps(content: str) -> list[str]:
        parts = re.split(r"\s*\d+\s*[\)\.\u3001）]\s*", str(content or "").strip())
        steps = [part.strip() for part in parts if part.strip()]
        return steps if len(steps) >= 2 else []

    def _enrich_learning_knowledge_blocks(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> None:
        if str(result.get("status")) != "ok":
            return
        blocks = [
            block
            for block in as_list(result.get("content_blocks"))
            if isinstance(block, dict)
        ]
        if not blocks:
            return
        target = self._knowledge_point(context, "learning")
        knowledge_id = str(
            result.get("knowledge_point_id") or target.get("knowledge_point_id") or ""
        )
        name = str(
            result.get("lesson_title")
            or target.get("knowledge_point_name")
            or ""
        ).strip()
        if not knowledge_id and not name:
            return
        items = self.domain.search_knowledge(
            query=name or knowledge_id,
            knowledge_point_id=knowledge_id,
            limit=12,
        )
        if not items:
            return
        by_category: dict[str, dict[str, Any]] = {}
        for item in items:
            by_category.setdefault(str(item.get("category") or ""), item)

        def entry(*categories: str) -> dict[str, Any] | None:
            for category in categories:
                if category in by_category:
                    return by_category[category]
            return None

        def kb_source(item: dict[str, Any]) -> str:
            source = str(item.get("source") or "课程知识库").strip()
            locator = str(item.get("locator") or "").strip()
            if locator and locator not in source:
                return f"{source} · {locator}"
            return source or "课程知识库"

        replacement: list[dict[str, Any]] = []
        for block in blocks:
            btype = str(block.get("type") or "")
            if btype == "concept":
                kb = entry("concept", "standard")
                if kb:
                    replacement.append({
                        "type": "concept",
                        "title": f"知识讲解 · {str(kb.get('title') or '核心规则')}",
                        "content": str(kb.get("content") or block.get("content") or ""),
                        "source": kb_source(kb),
                    })
                    continue
            elif btype in {"steps", "example"}:
                kb = entry("example" if btype == "example" else "steps")
                if kb:
                    content = str(kb.get("content") or "")
                    steps = self._split_knowledge_steps(content)
                    kb_block: dict[str, Any] = {
                        "type": btype,
                        "title": (
                            f"完整案例：{str(kb.get('title') or '工作场景')}"
                            if btype == "example"
                            else f"步骤讲解：{str(kb.get('title') or '操作步骤')}"
                        ),
                        "source": kb_source(kb),
                    }
                    if steps:
                        kb_block["items"] = steps
                    else:
                        kb_block["content"] = content
                    replacement.append(kb_block)
                    continue
            replacement.append(block)
        kb = entry("warning", "safety")
        if kb:
            replacement.append({
                "type": "warning",
                "title": f"常见误区：{str(kb.get('title') or '易错点')}",
                "content": str(kb.get("content") or ""),
                "source": kb_source(kb),
            })
        result["content_blocks"] = replacement

    def _normalize_review_result(
        self,
        result: dict[str, Any],
        context: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(result)
        normalized["workflow_mode"] = "review"
        source_context = context
        if context.get("resume_token"):
            source_context = as_dict(state.get("upstream_payload"))
        normalized.setdefault("question_snapshot", as_dict(source_context.get("question_snapshot")))
        normalized.setdefault("current_attempt", as_dict(source_context.get("current_attempt")))
        normalized.setdefault("validated_evaluation", as_dict(source_context.get("validated_evaluation")))
        field_mappings = {
            "teaching_strategy_json": "teaching_strategy",
            "target_error_json": "target_error",
            "variant_practice_request_json": "variant_practice_request",
        }
        for source_key, target_key in field_mappings.items():
            if source_key in normalized and target_key not in normalized:
                normalized[target_key] = parse_json_object(normalized[source_key]) or {}
        if normalized.get("status") == "ok" and "explanation_steps" not in normalized:
            explanation = str(normalized.get("personalized_explanation", ""))
            sentences = [item.strip() for item in explanation.replace("！", "。").split("。") if item.strip()]
            normalized["explanation_steps"] = [
                {"title": f"讲解步骤 {index}", "content": sentence}
                for index, sentence in enumerate(sentences[:3], start=1)
            ]
        self._merge_video_resources(normalized, context)
        self._merge_document_resources(normalized, context)
        return normalized

    def _require_identity(self, payload: dict[str, Any]) -> tuple[str, str]:
        student_id = str(payload.get("student_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        missing = [name for name, value in (("student_id", student_id), ("session_id", session_id)) if not value]
        if missing:
            raise ApiError(400, "MISSING_IDENTITY", "缺少必要字段：" + "、".join(missing))
        return student_id, session_id


def demo_upstream_payload() -> dict[str, Any]:
    return {
        "event_id": "DEMO-UPSTREAM-001",
        "student_id": "STU-DEMO-001",
        "session_id": "DEMO-SESSION-001",
        "attempt_id": "DEMO-ATTEMPT-001",
        "route_type": "error_remediation",
        "learning_goal": {
            "goal_id": "GOAL-JAVA-001",
            "goal_type": "course",
            "goal_name": "完成 Java 面向对象成绩管理实训",
        },
        "question_snapshot": {
            "question_id": "Q-003",
            "question_text": "在 Student 类中实现 averageScore()：缺考学生成绩字段为 null，统计平均分时必须排除 null，且成绩数组不得被外部直接修改。请修复当前实现并说明原因。",
        },
        "current_attempt": {"student_answer": "public double averageScore() { return total / scores.length; }  // 直接访问了 scores 字段，未排除 null"},
        "validated_evaluation": {
            "validation_passed": True,
            "evaluation_status": "incorrect",
            "score": 6,
            "max_score": 10,
            "error_points": [
                {
                    "error_id": "JAVA_ENCAP_BYPASSED_ACCESS",
                    "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                    "knowledge_point_name": "封装与访问控制",
                    "error_type": "design",
                    "student_evidence": "averageScore() 直接读取了 scores 数组并除以 length，缺考 null 未排除",
                    "expected_behavior": "成绩数组保持 private，通过 getter/内部方法提供访问；统计时先过滤 null",
                    "diagnosis": "绕过了封装，且统计口径未排除缺考记录",
                    "root_cause": "成绩集合的访问没有收敛到类的内部方法，外部可任意读写",
                    "severity": "medium",
                    "confidence": 0.98,
                }
            ],
        },
        "diagnostic_result": {
            "weak_points": [
                {
                    "knowledge_point_id": "KN_JAVA_CLASS",
                    "knowledge_point_name": "类的定义与对象创建",
                    "knowledge_type": "code",
                    "mastery": 82,
                    "priority": 70,
                    "recommended_order": 1,
                },
                {
                    "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                    "knowledge_point_name": "封装与访问控制",
                    "knowledge_type": "conceptual",
                    "mastery": 42,
                    "priority": 90,
                    "recommended_order": 2,
                    "attempt_count": 2,
                    "weakness_evidence": "averageScore() 直接访问了私有字段，未走封装方法，缺考 null 也未排除。",
                },
                {
                    "knowledge_point_id": "KN_JAVA_INHERITANCE",
                    "knowledge_point_name": "继承与方法重写",
                    "knowledge_type": "code",
                    "mastery": 55,
                    "priority": 80,
                    "recommended_order": 3,
                },
                {
                    "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
                    "knowledge_point_name": "多态与接口",
                    "knowledge_type": "conceptual",
                    "mastery": 60,
                    "priority": 75,
                    "recommended_order": 4,
                },
                {
                    "knowledge_point_id": "KN_JAVA_COLLECTION",
                    "knowledge_point_name": "集合与泛型",
                    "knowledge_type": "code",
                    "mastery": 48,
                    "priority": 85,
                    "recommended_order": 5,
                },
                {
                    "knowledge_point_id": "KN_JAVA_EXCEPTION",
                    "knowledge_point_name": "异常处理",
                    "knowledge_type": "code",
                    "mastery": 50,
                    "priority": 80,
                    "recommended_order": 6,
                },
                {
                    "knowledge_point_id": "KN_JAVA_IO",
                    "knowledge_point_name": "输入输出流",
                    "knowledge_type": "code",
                    "mastery": 45,
                    "priority": 78,
                    "recommended_order": 7,
                },
            ]
        },
        "current_knowledge_point": {
            "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            "knowledge_point_name": "封装与访问控制",
            "knowledge_type": "conceptual",
            "mastery": 42,
            "attempt_count": 2,
            "weakness_evidence": "averageScore() 直接访问了私有字段，未走封装方法，缺考 null 也未排除。",
        },
    }


class ApiRequestHandler(BaseHTTPRequestHandler):
    application: LearningApplication

    def do_OPTIONS(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._validate_origin()
            self.send_response(204)
            self._send_common_headers("application/json; charset=utf-8", 0)
            self.end_headers()
        except ApiError as error:
            self._send_api_error(error)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            self._authorize_api_request(parsed.path)
            if parsed.path == "/api/health":
                self._send_json(200, self.application.health())
                return
            if parsed.path == "/api/bootstrap":
                student_id = parse_qs(parsed.query).get("student_id", ["STU-DEMO-001"])[0]
                self._send_json(200, self.application.bootstrap(student_id))
                return
            if parsed.path == "/api/knowledge/search":
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    self.application.search_knowledge_api(
                        {
                            "q": query_params.get("q", [""])[0],
                            "knowledge_point_id": query_params.get(
                                "knowledge_point_id", [""]
                            )[0],
                            "action": query_params.get("action", [""])[0],
                            "category": query_params.get("category", [""])[0],
                            "limit": query_params.get("limit", ["5"])[0],
                        }
                    ),
                )
                return
            if parsed.path == "/api/bank":
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "questions": bank_questions(
                            query_params.get("knowledge_point_id", [""])[0]
                        ),
                    },
                )
                return
            if parsed.path == "/api/projects":
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200, self.application.list_projects({"student_id": student_id})
                )
                return
            assessment_evidence_match = re.fullmatch(
                r"/api/projects/([^/]+)/assessments/([^/]+)/evidence", parsed.path
            )
            if assessment_evidence_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200,
                    self.application.project_assessment_evidence(
                        {
                            "student_id": student_id,
                            "project_id": unquote(assessment_evidence_match.group(1)),
                            "assessment_id": unquote(assessment_evidence_match.group(2)),
                        }
                    ),
                )
                return
            project_assessments_match = re.fullmatch(
                r"/api/projects/([^/]+)/assessments", parsed.path
            )
            if project_assessments_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200,
                    self.application.project_assessments(
                        {
                            "student_id": student_id,
                            "project_id": unquote(project_assessments_match.group(1)),
                        }
                    ),
                )
                return
            project_messages_match = re.fullmatch(
                r"/api/projects/([^/]+)/messages", parsed.path
            )
            if project_messages_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200,
                    self.application.project_messages(
                        {
                            "student_id": student_id,
                            "project_id": unquote(project_messages_match.group(1)),
                        }
                    ),
                )
                return
            project_match = re.fullmatch(r"/api/projects/([^/]+)", parsed.path)
            if project_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200,
                    self.application.get_project(
                        {
                            "student_id": student_id,
                            "project_id": unquote(project_match.group(1)),
                        }
                    ),
                )
                return
            if parsed.path == "/api/admin/profile-status":
                student_id = parse_qs(parsed.query).get("student_id", [""])[0]
                self._send_json(200, self.application.profile_status(student_id))
                return
            explanation_match = re.fullmatch(r"/api/explanations/([^/]+)/sources", parsed.path)
            if explanation_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                self._send_json(
                    200,
                    self.application.sources(student_id, unquote(explanation_match.group(1))),
                )
                return
            stream_match = re.fullmatch(r"/api/explanations/([^/]+)/stream", parsed.path)
            if stream_match:
                student_id = parse_qs(parsed.query).get("student_id", [""])[0].strip()
                if not student_id:
                    raise ApiError(400, "MISSING_STUDENT_ID", "student_id 不能为空")
                try:
                    stream = self.application.stream_explanation_sections(
                        student_id, unquote(stream_match.group(1))
                    )
                except ApiError as error:
                    self._send_sse_error(error.code, error.message)
                    return
                self._send_sse(stream)
                return
            student_resource = re.fullmatch(
                r"/api/students/([^/]+)/(profile|notifications|records|settings|portrait|growth)",
                parsed.path,
            )
            if student_resource:
                student_id = unquote(student_resource.group(1))
                resource = student_resource.group(2)
                handlers = {
                    "profile": self.application.profile,
                    "notifications": self.application.notifications,
                    "records": self.application.records,
                    "settings": self.application.settings_for,
                    "portrait": self.application.portrait,
                    "growth": self.application.growth,
                }
                self._send_json(200, handlers[resource](student_id))
                return
            prefix = "/api/students/"
            suffix = "/learning-state"
            if parsed.path.startswith(prefix) and parsed.path.endswith(suffix):
                student_id = unquote(parsed.path[len(prefix) : -len(suffix)]).strip("/")
                self._send_json(200, self.application.learning_state(student_id))
                return
            discovery_session_match = re.fullmatch(
                r"/api/discovery/sessions/([^/]+)/projection", parsed.path
            )
            if discovery_session_match:
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    self.application.discovery_projection({
                        "learner_id": query_params.get("learner_id", [""])[0],
                        "session_id": unquote(discovery_session_match.group(1)),
                    }),
                )
                return
            discovery_session_match = re.fullmatch(
                r"/api/discovery/sessions/([^/]+)", parsed.path
            )
            if discovery_session_match:
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    self.application.discovery_get({
                        "learner_id": query_params.get("learner_id", [""])[0],
                        "session_id": unquote(discovery_session_match.group(1)),
                    }),
                )
                return
            if parsed.path == "/api/discovery/sessions":
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    self.application.discovery_sessions({
                        "learner_id": query_params.get("learner_id", [""])[0],
                    }),
                )
                return
            discovery_events_match = re.fullmatch(
                r"/api/learners/([^/]+)/discovery/events", parsed.path
            )
            if discovery_events_match:
                query_params = parse_qs(parsed.query)
                self._send_json(
                    200,
                    self.application.discovery_events({
                        "learner_id": unquote(discovery_events_match.group(1)),
                        "session_id": query_params.get("session_id", [""])[0],
                    }),
                )
                return
            if parsed.path.startswith("/api/"):
                raise ApiError(404, "API_NOT_FOUND", "接口不存在")
            self._serve_static(parsed.path)
        except ApiError as error:
            self._send_api_error(error)
        except Exception as error:
            self.log_error("GET %s failed: %r", parsed.path, error)
            self._send_api_error(
                ApiError(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试")
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self._authorize_api_request(parsed.path)
            payload = self._read_json()
            if parsed.path == "/api/upstream/assessment-result":
                result = self.application.ingest_upstream(payload)
            elif parsed.path == "/api/admin/refresh-profile":
                result = self.application.refresh_profile(
                    str(payload.get("student_id", ""))
                )
            elif ask_match := re.fullmatch(r"/api/explanations/([^/]+)/ask", parsed.path):
                result = self.application.ask_explanation(unquote(ask_match.group(1)), payload)
            elif parsed.path == "/api/explanations":
                result = self.application.run_explanation(payload)
            elif parsed.path == "/api/agent/turn":
                result = self.application.agent_turn(payload)
            elif parsed.path == "/api/chat":
                result = self.application.chat(payload)
            elif parsed.path == "/api/practice/questions":
                result = self.application.create_practice(payload)
            elif parsed.path == "/api/goal/analyze":
                result = self.application.analyze_goal(payload)
            elif parsed.path == "/api/diagnosis/start":
                result = self.application.start_diagnosis(payload)
            elif parsed.path == "/api/diagnosis/answer":
                result = self.application.submit_diagnosis_answer(payload)
            elif parsed.path == "/api/bank/answer":
                result = self.application.submit_bank_answer(payload)
            elif parsed.path == "/api/code/run":
                result = self.application.run_code(payload)
            elif parsed.path == "/api/workflows/learning":
                result = self.application.run_learning(payload)
            elif parsed.path in {"/api/workflows/review", "/api/workflows/review/resume"}:
                result = self.application.run_review(payload)
            elif parsed.path == "/api/demo/seed":
                result = self.application.ingest_upstream(demo_upstream_payload())
            elif parsed.path == "/api/projects":
                result = self.application.create_project(payload)
            elif parsed.path == "/api/discovery/sessions":
                result = self.application.discovery_create(payload)
            else:
                discovery_action = re.fullmatch(
                    r"/api/discovery/sessions/([^/]+)/(answer|correct)",
                    parsed.path,
                )
                project_action = re.fullmatch(
                    r"/api/projects/([^/]+)/(diagnosis/start|diagnosis/answer|assessments/start|assessments/answer|explain)",
                    parsed.path,
                )
                attempt_match = re.fullmatch(
                    r"/api/question-instances/([^/]+)/attempts", parsed.path
                )
                settings_match = re.fullmatch(r"/api/students/([^/]+)/settings", parsed.path)
                favorite_match = re.fullmatch(r"/api/students/([^/]+)/favorites", parsed.path)
                notification_match = re.fullmatch(
                    r"/api/students/([^/]+)/notifications/([^/]+)/read", parsed.path
                )
                if discovery_action:
                    session_id = unquote(discovery_action.group(1))
                    action = discovery_action.group(2)
                    payload["session_id"] = session_id
                    if action == "answer":
                        result = self.application.discovery_answer(payload)
                    else:
                        result = self.application.discovery_correct(payload)
                elif project_action:
                    project_id = unquote(project_action.group(1))
                    action = project_action.group(2)
                    request = {**payload, "project_id": project_id}
                    if action == "diagnosis/start":
                        result = self.application.project_diagnosis_start(request)
                    elif action == "diagnosis/answer":
                        result = self.application.project_diagnosis_answer(request)
                    elif action == "assessments/start":
                        result = self.application.project_assessment_start(request)
                    elif action == "assessments/answer":
                        result = self.application.project_assessment_answer(request)
                    else:
                        result = self.application.project_explain(request)
                elif attempt_match:
                    result = self.application.submit_practice_attempt(
                        str(payload.get("student_id", "")),
                        unquote(attempt_match.group(1)),
                        payload,
                    )
                elif settings_match:
                    result = self.application.save_settings(
                        unquote(settings_match.group(1)), payload
                    )
                elif favorite_match:
                    result = self.application.toggle_favorite(
                        unquote(favorite_match.group(1)), payload
                    )
                elif notification_match:
                    result = self.application.mark_notification_read(
                        unquote(notification_match.group(1)),
                        unquote(notification_match.group(2)),
                    )
                else:
                    raise ApiError(404, "API_NOT_FOUND", "接口不存在")
            self._send_json(200, result)
        except ApiError as error:
            self._send_api_error(error)
        except GatewayError as error:
            self.log_error("POST %s gateway failed: %r", parsed.path, error)
            self._send_api_error(
                ApiError(
                    502,
                    "WORKFLOW_GATEWAY_ERROR",
                    "讲解服务暂时不可用，请稍后重试",
                )
            )
        except Exception as error:
            self.log_error("POST %s failed: %r", parsed.path, error)
            self._send_api_error(
                ApiError(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试")
            )

    def _validate_origin(self) -> None:
        origin = self.headers.get("Origin", "").strip()
        if origin and origin not in self.application.settings.allowed_origins:
            raise ApiError(403, "ORIGIN_NOT_ALLOWED", "当前请求来源未被允许")

    def _authorize_api_request(self, request_path: str) -> None:
        if not request_path.startswith("/api/"):
            return
        self._validate_origin()
        if request_path == "/api/health" or not self.application.settings.api_token:
            return
        authorization = self.headers.get("Authorization", "").strip()
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(token.strip(), self.application.settings.api_token)
        ):
            raise ApiError(401, "UNAUTHORIZED", "缺少或使用了无效的访问令牌")

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        if content_length > MAX_BODY_BYTES:
            raise ApiError(413, "BODY_TOO_LARGE", "请求体不能超过 2MB")
        body = self.rfile.read(content_length)
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError(400, "INVALID_JSON", "请求体必须是 UTF-8 JSON 对象") from error
        if not isinstance(value, dict):
            raise ApiError(400, "INVALID_JSON_TYPE", "请求体必须是 JSON 对象")
        return value

    def _serve_static(self, request_path: str) -> None:
        # 主入口为 agent 形态；旧版学习中心（含题库/画像/记录）保留在 /index.html
        relative_path = (
            "agent.html" if request_path in {"", "/"} else unquote(request_path).lstrip("/")
        )
        target = (FRONTEND_DIR / relative_path).resolve()
        try:
            target.relative_to(FRONTEND_DIR.resolve())
        except ValueError as error:
            raise ApiError(403, "FORBIDDEN", "禁止访问该路径") from error
        if not target.is_file():
            target = FRONTEND_DIR / "agent.html"
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self._send_common_headers(content_type, len(content))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._send_common_headers("application/json; charset=utf-8", len(content))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_sse(self, stream: tuple[str, list[dict[str, Any]], str]) -> None:
        kind, sections, workflow_mode = stream
        self._send_sse_headers()
        try:
            for label in ("正在定位薄弱点…", "正在检索知识库…", "正在生成讲解…"):
                self._write_sse_event("status", {"message": label})
                time.sleep(0.4)
            for index, section in enumerate(sections):
                self._write_sse_event(
                    "section",
                    {"index": index, "kind": kind, "section": section},
                )
                time.sleep(0.3)
            self._write_sse_event(
                "done",
                {
                    "kind": kind,
                    "workflow_mode": workflow_mode,
                    "section_count": len(sections),
                },
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            try:
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_sse_error(self, error_code: str, message: str) -> None:
        self._send_sse_headers()
        try:
            self._write_sse_event(
                "error",
                {"error_code": error_code, "message": message},
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            try:
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_sse_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        # The response is connection-delimited (no Content-Length): close the
        # socket after the last event so the client sees the stream end.
        self.close_connection = 1
        origin = self.headers.get("Origin", "").strip()
        if origin and origin in self.application.settings.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _write_sse_event(self, event: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_api_error(self, error: ApiError) -> None:
        self._send_json(
            error.status_code,
            {
                "status": "error",
                "error_code": error.code,
                "user_message": error.message,
            },
        )

    def _send_common_headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        origin = self.headers.get("Origin", "").strip()
        if origin and origin in self.application.settings.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")

    def log_message(self, message_format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {message_format % args}")


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def create_server(settings: Settings) -> ThreadingHTTPServer:
    if not _is_loopback_host(settings.host) and not settings.api_token:
        raise ValueError("监听非回环地址时必须配置 APP_API_TOKEN")
    store = StateStore(settings.database_path)
    domain = LearningDomainStore(settings.database_path)
    student_models = StudentModelCache(settings.database_path)
    knowledge_cache = KnowledgeCache(ttl_seconds=300)
    gateway = XingchenGateway(settings, domain)
    video_search = VideoSearchGateway(settings)
    application = LearningApplication(
        settings,
        store,
        gateway,
        video_search,
        domain,
        student_models,
        knowledge_cache,
    )
    application.ensure_demo_seed()

    class BoundHandler(ApiRequestHandler):
        pass

    BoundHandler.application = application
    server = ThreadingHTTPServer((settings.host, settings.port), BoundHandler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="个性化学习三工作流后端")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    arguments = parser.parse_args()
    load_environment_file(ROOT / "backend" / ".env")
    settings = Settings.from_env(arguments.host, arguments.port)
    server = create_server(settings)
    print(f"个性化学习系统已启动：http://{settings.host}:{server.server_port}/")
    print(f"星辰调用模式：{settings.xingchen_mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
