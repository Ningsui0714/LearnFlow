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
    from goal_engine import path_for_learning_goal, resolve_learning_goal

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
    from backend.data.error_cards import default_error_card_for
except ModuleNotFoundError:
    from data.error_cards import default_error_card_for


ROOT = Path(__file__).resolve().parents[1]
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
            input_key=os.getenv("XINGCHEN_INPUT_KEY", "AGENT_USER_INPUT").strip(),
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
            domain = self._allowed_domain(host, domain_map)
            if not title or not url or not domain:
                continue
            source = domain_map[domain]
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
            return {"status": "ok", "workflow_mode": "quiz", "questions": []}
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
        return self._match_goal_keywords(text)

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

        # 取样逻辑在数据模块（P1-2）：每知识点先取一题，再用剩余题补足目标数量
        picked = select_diagnosis_questions(goal)

        questions = [
            {
                "question_id": item["id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "title": item["title"],
                "options": item["options"],
                "difficulty": item["difficulty"],
                "answer": item["answer"],
                "explanation": item["explanation"],
            }
            for item in picked
        ]
        state = self.store.get_student_state(student_id) or {}
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
            if selected not in {"a", "b", "c"}:
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
        if not goal:
            keyword_match = self._match_goal_keywords(text)
            if keyword_match.get("matched"):
                goal = keyword_match["goal"]
        if not goal:
            return {
                "status": "needs_clarification",
                "text": text,
                "clarification": (
                    f"暂时无法从“{text}”中识别具体目标。"
                    "可以输入如“想考 1+X Java 应用开发认证”“备战世界职业院校技能大赛”"
                    "“完成 Java 面向对象成绩管理实训”，或从下方快捷目标中选择。"
                ),
            }

        goal_id = str(goal["goal_id"])
        goal_name = str(goal.get("goal_name") or goal_id)
        learning_path = build_learning_path(goal_id)
        state: dict[str, Any] = {
            "goal": {
                "goal_id": goal_id,
                "goal_name": goal_name,
                "goal_type": str(goal.get("goal_type") or "course"),
            },
            "learning_path": learning_path,
            "diagnosis_session": None,
            "weak_points": [],
        }
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
                "status": project["status"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
                "diagnosis_state": self._project_diagnosis_state(state),
                "learning_path": state.get("learning_path", {}),
                "weak_points": as_list(state.get("weak_points")),
            },
        }

    def project_diagnosis_start(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        goal_key = self.PROJECT_GOAL_DIAGNOSIS.get(
            str(project.get("goal_id", "")), "daily"
        )
        goal_config = DIAGNOSIS_GOALS.get(goal_key)
        if not goal_config:
            raise ApiError(400, "UNKNOWN_GOAL", f"不支持的目标：{goal_key}")
        picked = select_diagnosis_questions(goal_key)
        questions = [
            {
                "question_id": item["id"],
                "knowledge_point_id": item["knowledge_point_id"],
                "knowledge_point_name": item["knowledge_point_name"],
                "title": item["title"],
                "options": item["options"],
                "difficulty": item["difficulty"],
                "answer": item["answer"],
                "explanation": item["explanation"],
            }
            for item in picked
        ]
        state["diagnosis_session"] = {
            "goal": goal_key,
            "questions": questions,
            "index": 0,
            "correct": 0,
            "wrong": 0,
            "skipped": 0,
            "results": [],
            "done": False,
        }
        self.store.save_project_state(project_id, state, status="diagnosis")
        public_questions = [
            {k: v for k, v in q.items() if k not in ("answer", "explanation")}
            for q in questions
        ]
        return {
            "status": "ok",
            "project_id": project_id,
            "goal": goal_key,
            "goal_label": goal_config["label"],
            "questions": public_questions,
            "total": len(public_questions),
        }

    def project_diagnosis_answer(self, incoming: dict[str, Any]) -> dict[str, Any]:
        student_id = str(incoming.get("student_id", "")).strip()
        project_id = str(incoming.get("project_id", "")).strip()
        project = self._require_project(student_id, project_id)
        state = as_dict(project["state"])
        session = as_dict(state.get("diagnosis_session"))
        if not session:
            raise ApiError(409, "DIAGNOSIS_NOT_ACTIVE", "当前没有进行中的测评，请先开始")
        if session.get("done"):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮测评已结束，请重新开始")
        skipped = bool(incoming.get("skipped"))
        selected = str(incoming.get("selected", "")).strip()
        index = int(session.get("index", 0) or 0)
        questions = as_list(session.get("questions"))
        if index >= len(questions):
            raise ApiError(409, "DIAGNOSIS_FINISHED", "本轮测评已结束")
        current = questions[index]
        if skipped:
            correct = False
            session["skipped"] = int(session.get("skipped", 0) or 0) + 1
        else:
            if selected not in {"a", "b", "c", "d"}:
                raise ApiError(400, "INVALID_ANSWER", "无效的选项")
            correct = selected == str(current.get("answer", ""))
            key = "correct" if correct else "wrong"
            session[key] = int(session.get(key, 0) or 0) + 1
        if not skipped:
            # 测评作答落库（与现有诊断一致），供画像溯源/学习记录使用
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
            "stats": stats,
        }
        if not is_last:
            return base
        summary = self._finalize_project_diagnosis(state, session)
        self.store.save_project_state(project_id, state, status="diagnosis_done")
        base["status"] = "completed"
        base["summary"] = summary
        return base

    @staticmethod
    def _finalize_project_diagnosis(
        state: dict[str, Any], session: dict[str, Any]
    ) -> dict[str, Any]:
        """答错题目按知识点归因：更新项目路径掌握度并生成薄弱点摘要。"""
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
        weak_points = sorted(
            (
                {
                    "knowledge_point_id": kp_id,
                    "knowledge_point_name": entry["name"],
                    "error_count": entry["count"],
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
        state["weak_points"] = weak_points
        return {
            "weak_points": weak_points,
            "feedback": (
                f"测评完成：发现 {len(weak_points)} 个薄弱知识点，"
                "已更新掌握度，建议按路径顺序优先学习薄弱项。"
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

        context = {
            "student_id": student_id,
            "session_id": f"PROJECT-{project_id}",
            "learning_goal": {
                "goal_id": str(project.get("goal_id", "")),
                "goal_name": str(project.get("goal_name", "")),
            },
            "learning_path": path,
            "current_knowledge_point": target,
            "event_type": "initialize_learning",
            "goal_driven": True,
        }
        self._prepare_learning_workflow_context(context, {})
        self._attach_video_search("learning", context)
        workflow_payload = self._learning_workflow_payload(context)
        result = self.gateway.invoke_learning_workflow(workflow_payload)
        result = self._normalize_learning_result(result, context)
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
        """对话页：模糊提问澄清 + 知识库 RAG 回答（比赛硬要求）。

        输入：message（学生提问）
        输出：
        - 模糊提问（"这个怎么弄"等）→ status=needs_clarification + clarify_options
        - 明确提问 → status=ok + answer（AI 生成标识）+ sources[]（知识库命中，带来源）
        说明：此实现走本地知识库 RAG；接入星辰工作流后可将 answer 生成改为
        workflow 节点（生成类上平台），检索与来源核验留在本地。
        """
        message = str(incoming.get("message") or "").strip()
        if not message:
            raise ApiError(400, "MISSING_MESSAGE", "请输入要咨询的问题")
        student_id = str(incoming.get("student_id") or "").strip()

        # 1) 模糊提问识别：疑问词 + 缺少领域知识点关键词 → 引导澄清
        vague_words = ("怎么弄", "怎么办", "怎么做", "咋办", "啥意思", "是什么呀", "怎么用", "怎么实现")
        knowledge_hint = ("java", "类", "对象", "封装", "继承", "多态", "接口", "集合",
                          "异常", "io", "成绩", "平均分", "缺考", "getter", "构造器", "数组")
        has_hint = any(kw in message.lower() for kw in knowledge_hint)
        is_vague = any(v in message for v in vague_words) and not has_hint
        if is_vague or len(message) <= 4:
            return {
                "status": "needs_clarification",
                "message": "你问的有点笼统，先确认一下你想了解的具体方向：",
                "clarify_options": [
                    {"id": "concept", "label": "概念/原理（如什么是封装）"},
                    {"id": "code", "label": "怎么写代码（如如何排除缺考统计）"},
                    {"id": "error", "label": "报错/易错点（如空指针）"},
                ],
            }

        # 2) remote 模式：生成类上平台（对话问答工作流）
        if self.gateway.mode == "remote":
            try:
                result = self.gateway.invoke_chat_workflow({
                    "message": message,
                    "student_id": student_id,
                    "student_profile": as_dict(self.domain.profile(student_id).get("profile")),
                    "kb_text": "\n".join(
                        f"【{i.get('title')}】{i.get('content')}" for i in items
                    ) if items else "",
                })
                answer = str(as_dict(result).get("message") or "").strip()
                if answer:
                    return {
                        "status": "ok",
                        "answer": answer,
                        "ai_generated": True,
                        "sources": [
                            {
                                "title": str(i.get("source") or "知识库"),
                                "locator": str(i.get("locator") or ""),
                                "knowledge_point_id": str(i.get("knowledge_point_id") or ""),
                                "quote_text": str(i.get("title") or ""),
                            }
                            for i in items
                        ],
                    }
            except Exception:
                # 工作流失败降级本地 RAG，保证演示不中断
                pass

        # 3) 明确提问（本地 RAG 兜底 / mock 模式）：知识库检索（按知识点优先，命中前 3）
        items = self.domain.search_knowledge(query=message, limit=3)
        if not items:
            # 3.1) 白名单联网检索兜底（方案 A：检索留本地、白名单域名、来源引用）
            web_answer = self._chat_web_search(message)
            if web_answer:
                return web_answer
            return {
                "status": "ok",
                "answer": "知识库暂未检索到与「" + message + "」直接相关的内容。你可以换个问法，或进入「学情诊断」定位薄弱知识点。",
                "ai_generated": False,
                "sources": [],
            }
        # 组装回答：主条目内容 + 来源标注（AI 生成标识）
        primary = items[0]
        answer = str(primary.get("content") or "").strip()
        if len(items) > 1:
            extra = [str(i.get("title") or "") for i in items[1:] if i.get("title")]
            if extra:
                answer += "\n\n（延伸参考：" + "、".join(extra) + "）"
        return {
            "status": "ok",
            "answer": answer,
            "ai_generated": True,
            "sources": [
                {
                    "title": str(i.get("source") or "知识库"),
                    "locator": str(i.get("locator") or ""),
                    "knowledge_point_id": str(i.get("knowledge_point_id") or ""),
                    "quote_text": str(i.get("title") or ""),
                }
                for i in items
            ],
        }

    def _chat_web_search(self, message: str) -> dict[str, Any] | None:
        """chat 联网检索兜底：白名单域名（bing RSS）+ 来源引用。

        仅当文档联网检索开启（doc_enabled）时启用；未命中/失败/未开启
        均返回 None，由调用方保持"知识库未检索到"兜底文案（断网自动降级）。
        检索结果仅作为补充材料引用，不参与出题。
        """
        if not self.video_search.doc_enabled:
            return None
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
            "知识库暂未收录该内容，为你联网检索到以下权威资料（来源域名已核验）：\n\n"
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
                "verification_state": "whitelisted",
                "provider": str(result.get("provider") or "bing_rss"),
            }
            for item in web_results[:4]
        ]
        return {
            "status": "ok",
            "answer": answer,
            "ai_generated": True,
            "web_searched": True,
            "sources": sources,
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

        nodes = [
            {
                "id": str(item.get("knowledge_point_id") or f"KN-{index}"),
                "name": str(item.get("knowledge_point_name") or f"学习节点 {index}"),
                "mastery": int(item.get("mastery", 0) or 0),
                "type": str(item.get("knowledge_type") or "conceptual"),
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
            else:
                project_action = re.fullmatch(
                    r"/api/projects/([^/]+)/(diagnosis/start|diagnosis/answer|explain)",
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
                if project_action:
                    project_id = unquote(project_action.group(1))
                    action = project_action.group(2)
                    request = {**payload, "project_id": project_id}
                    if action == "diagnosis/start":
                        result = self.application.project_diagnosis_start(request)
                    elif action == "diagnosis/answer":
                        result = self.application.project_diagnosis_answer(request)
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
