from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from backend.data.error_cards import variant_practice_for
except ModuleNotFoundError:
    from data.error_cards import variant_practice_for


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class StudentModelCache:
    """SQLite-backed student model cache with event-based refresh tracking."""

    REFRESH_INTERVAL = 5

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS student_model (
                    student_id TEXT PRIMARY KEY,
                    model_json TEXT NOT NULL,
                    strategy_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    profile_event_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(student_model)").fetchall()
            }
            if "profile_event_count" not in columns:
                connection.execute(
                    "ALTER TABLE student_model ADD COLUMN profile_event_count INTEGER NOT NULL DEFAULT 0"
                )
            connection.commit()

    def _ensure_row(self, connection: sqlite3.Connection, student_id: str) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO student_model(
                student_id, model_json, strategy_json, generated_at,
                event_count, profile_event_count
            ) VALUES (?, '{}', '{}', '', 0, 0)
            """,
            (student_id,),
        )

    @staticmethod
    def _decode_object(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def get_model(self, student_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT model_json, strategy_json, generated_at,
                       event_count, profile_event_count
                FROM student_model WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        if not row or not str(row["generated_at"]):
            return None
        model = self._decode_object(row["model_json"])
        if not model:
            return None
        return {
            "student_model": model,
            "strategy_defaults": self._decode_object(row["strategy_json"]),
            "generated_at": str(row["generated_at"]),
            "based_on_event_count": int(row["profile_event_count"] or 0),
            "event_count": int(row["event_count"] or 0),
        }

    def event_count(self, student_id: str) -> int:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        return int(row["event_count"] or 0) if row else 0

    def increment_event(self, student_id: str) -> int:
        with self._lock, closing(self._connect()) as connection:
            self._ensure_row(connection, student_id)
            connection.execute(
                "UPDATE student_model SET event_count = event_count + 1 WHERE student_id = ?",
                (student_id,),
            )
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            connection.commit()
        return int(row["event_count"] or 0) if row else 0

    def save_model(
        self,
        student_id: str,
        model: dict[str, Any],
        strategy: dict[str, Any],
        based_on_event_count: int | None = None,
    ) -> None:
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            self._ensure_row(connection, student_id)
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            current_count = int(row["event_count"] or 0) if row else 0
            profile_count = (
                current_count
                if based_on_event_count is None
                else max(0, min(int(based_on_event_count), current_count))
            )
            connection.execute(
                """
                UPDATE student_model SET
                    model_json = ?, strategy_json = ?, generated_at = ?,
                    profile_event_count = ?
                WHERE student_id = ?
                """,
                (json_text(model), json_text(strategy), now, profile_count, student_id),
            )
            connection.commit()

    def should_refresh(self, student_id: str) -> bool:
        status = self.status(student_id)
        return bool(status["needs_refresh"])

    def status(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT model_json, generated_at, event_count, profile_event_count
                FROM student_model WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        if not row:
            return {
                "has_profile": False,
                "generated_at": "",
                "event_count": 0,
                "events_since_profile": 0,
                "needs_refresh": True,
            }
        has_profile = bool(str(row["generated_at"])) and bool(
            self._decode_object(row["model_json"])
        )
        event_count = int(row["event_count"] or 0)
        profile_count = int(row["profile_event_count"] or 0)
        events_since_profile = max(0, event_count - profile_count)
        return {
            "has_profile": has_profile,
            "generated_at": str(row["generated_at"]),
            "event_count": event_count,
            "events_since_profile": events_since_profile,
            "needs_refresh": not has_profile or events_since_profile >= self.REFRESH_INTERVAL,
        }


class LearningDomainStore:
    DEFAULT_SETTINGS = {
        "preferred_delivery_mode": "text",
        "explanation_depth": "guided",
        "reduced_motion": False,
        "auto_play_video": False,
    }

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS student_profiles (
                    student_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    program_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_cycles (
                    training_cycle_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cycles_student
                    ON training_cycles(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS learning_tasks (
                    learning_task_id TEXT PRIMARY KEY,
                    training_cycle_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_cycle_knowledge
                    ON learning_tasks(training_cycle_id, knowledge_point_id);
                CREATE TABLE IF NOT EXISTS task_instances (
                    task_instance_id TEXT PRIMARY KEY,
                    learning_task_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_instances_student
                    ON task_instances(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS question_instances (
                    question_instance_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    source_question_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    answer_schema_json TEXT NOT NULL,
                    expected_answer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_questions_student
                    ON question_instances(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    question_instance_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_student
                    ON attempts(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS explanation_sessions (
                    explanation_session_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    question_instance_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    explanation_type TEXT NOT NULL,
                    explanation_mode TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    source_explanation_session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_explanations_student
                    ON explanation_sessions(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS explanation_turns (
                    explanation_turn_id TEXT PRIMARY KEY,
                    explanation_session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_references (
                    source_reference_id TEXT PRIMARY KEY,
                    explanation_session_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    quote_text TEXT NOT NULL,
                    url TEXT NOT NULL,
                    verification_state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sources_explanation
                    ON source_references(explanation_session_id, created_at);
                CREATE TABLE IF NOT EXISTS resume_tokens (
                    token_hash TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS student_settings (
                    student_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS student_favorites (
                    student_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, knowledge_point_id)
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    read_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_student
                    ON notifications(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_entries (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    document_id TEXT NOT NULL DEFAULT '',
                    locator TEXT NOT NULL DEFAULT '',
                    safety INTEGER NOT NULL DEFAULT 0,
                    job_role TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_point
                    ON knowledge_entries(knowledge_point_id, category);
                """
            )
            resume_token_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(resume_tokens)"
                ).fetchall()
            }
            if "student_id" not in resume_token_columns:
                connection.execute(
                    "ALTER TABLE resume_tokens "
                    "ADD COLUMN student_id TEXT NOT NULL DEFAULT ''"
                )
            if "session_id" not in resume_token_columns:
                connection.execute(
                    "ALTER TABLE resume_tokens "
                    "ADD COLUMN session_id TEXT NOT NULL DEFAULT ''"
                )
            self._initialize_knowledge(connection)
            connection.commit()

    def ensure_profile(self, student_id: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO student_profiles(
                    student_id, display_name, program_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (student_id, "林同学", "Java 面向对象程序设计实训", now, now),
            )
            row = connection.execute(
                "SELECT * FROM student_profiles WHERE student_id = ?", (student_id,)
            ).fetchone()
            connection.commit()
        return dict(row) if row else {}

    def ingest_context(self, payload: dict[str, Any]) -> dict[str, str]:
        student_id = str(payload.get("student_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        if not student_id or not session_id:
            return {}
        self.ensure_profile(student_id)
        goal = as_dict(payload.get("learning_goal"))
        goal_id = str(goal.get("goal_id") or "GOAL-CURRENT")
        title = str(goal.get("goal_name") or "当前学习目标")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            cycle_id = str(payload.get("training_cycle_id", "")).strip()
            if not cycle_id:
                row = connection.execute(
                    """
                    SELECT training_cycle_id FROM training_cycles
                    WHERE student_id = ? AND goal_id = ? AND status = 'active'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, goal_id),
                ).fetchone()
                cycle_id = str(row[0]) if row else new_id("CYCLE")
            connection.execute(
                """
                INSERT INTO training_cycles(
                    training_cycle_id, student_id, goal_id, title, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(training_cycle_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (cycle_id, student_id, goal_id, title, now, now),
            )

            diagnostic = as_dict(payload.get("diagnostic_result"))
            weak_points = [item for item in as_list(diagnostic.get("weak_points")) if isinstance(item, dict)]
            current = as_dict(payload.get("current_knowledge_point"))
            if current and not any(
                str(item.get("knowledge_point_id", "")) == str(current.get("knowledge_point_id", ""))
                for item in weak_points
            ):
                weak_points.append(current)
            if not weak_points:
                weak_points = [{
                    "knowledge_point_id": "KN_CURRENT",
                    "knowledge_point_name": "当前知识点",
                    "recommended_order": 1,
                }]

            current_id = str(current.get("knowledge_point_id") or weak_points[0].get("knowledge_point_id") or "KN_CURRENT")
            task_id = ""
            for index, item in enumerate(weak_points, start=1):
                knowledge_id = str(item.get("knowledge_point_id") or f"KN-{index}")
                existing = connection.execute(
                    """
                    SELECT learning_task_id FROM learning_tasks
                    WHERE training_cycle_id = ? AND knowledge_point_id = ?
                    """,
                    (cycle_id, knowledge_id),
                ).fetchone()
                item_task_id = str(existing[0]) if existing else new_id("TASK")
                status = "current" if knowledge_id == current_id else (
                    "completed" if int(item.get("mastery", 0) or 0) >= 80 else "pending"
                )
                connection.execute(
                    """
                    INSERT INTO learning_tasks(
                        learning_task_id, training_cycle_id, knowledge_point_id, title,
                        sequence_number, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(learning_task_id) DO UPDATE SET
                        title = excluded.title,
                        sequence_number = excluded.sequence_number,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item_task_id,
                        cycle_id,
                        knowledge_id,
                        str(item.get("knowledge_point_name") or knowledge_id),
                        int(item.get("recommended_order", index) or index),
                        status,
                        now,
                        now,
                    ),
                )
                if knowledge_id == current_id:
                    task_id = item_task_id
            if not task_id:
                row = connection.execute(
                    """
                    SELECT learning_task_id FROM learning_tasks
                    WHERE training_cycle_id = ? ORDER BY sequence_number LIMIT 1
                    """,
                    (cycle_id,),
                ).fetchone()
                task_id = str(row[0])

            task_instance_id = str(payload.get("task_instance_id", "")).strip()
            if not task_instance_id:
                row = connection.execute(
                    """
                    SELECT task_instance_id FROM task_instances
                    WHERE student_id = ? AND session_id = ? AND learning_task_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, session_id, task_id),
                ).fetchone()
                task_instance_id = str(row[0]) if row else new_id("TASKINST")
            connection.execute(
                """
                INSERT INTO task_instances(
                    task_instance_id, learning_task_id, student_id, session_id,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(task_instance_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (task_instance_id, task_id, student_id, session_id, now, now),
            )

            question = as_dict(payload.get("question_snapshot"))
            question_instance_id = str(payload.get("question_instance_id", "")).strip()
            source_question_id = str(question.get("question_id", "")).strip()
            if source_question_id and not question_instance_id:
                row = connection.execute(
                    """
                    SELECT question_instance_id FROM question_instances
                    WHERE student_id = ? AND source_question_id = ? AND mode = 'assessment'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, source_question_id),
                ).fetchone()
                question_instance_id = str(row[0]) if row else new_id("QUESTION")
            if source_question_id:
                prompt = str(question.get("question_text") or "待补充题目描述")
                connection.execute(
                    """
                    INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'assessment', ?, ?, ?, ?, '', 'reviewed', ?, ?)
                    ON CONFLICT(question_instance_id) DO UPDATE SET
                        prompt = excluded.prompt,
                        updated_at = excluded.updated_at
                    """,
                    (
                        question_instance_id,
                        student_id,
                        task_instance_id,
                        source_question_id,
                        current_id,
                        str(current.get("knowledge_point_name") or "测验题目"),
                        prompt,
                        json_text({"type": "text", "label": "作答"}),
                        now,
                        now,
                    ),
                )

            attempt_id = str(payload.get("attempt_id", "")).strip()
            attempt = as_dict(payload.get("current_attempt"))
            if question_instance_id and attempt_id and attempt:
                evaluation = as_dict(payload.get("validated_evaluation"))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO attempts(
                        attempt_id, question_instance_id, student_id, answer_text,
                        evaluation_json, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        question_instance_id,
                        student_id,
                        str(attempt.get("student_answer", "")),
                        json_text(evaluation),
                        str(evaluation.get("evaluation_status") or "submitted"),
                        now,
                    ),
                )
            connection.commit()
        return {
            "training_cycle_id": cycle_id,
            "learning_task_id": task_id,
            "task_instance_id": task_instance_id,
            "question_instance_id": question_instance_id,
            "attempt_id": str(payload.get("attempt_id", "")),
        }

    def create_resume_token(
        self,
        context: dict[str, Any],
        student_id: str,
        session_id: str,
        ttl_minutes: int = 15,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO resume_tokens(
                    token_hash, student_id, session_id, context_json,
                    expires_at, used_at, created_at
                ) VALUES (?, ?, ?, ?, ?, '', ?)
                """,
                (
                    token_hash,
                    student_id,
                    session_id,
                    json_text(context),
                    (now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
            connection.commit()
        return "resume." + token

    def consume_resume_token(
        self, token: str, student_id: str, session_id: str
    ) -> dict[str, Any]:
        if not token.startswith("resume."):
            return {}
        raw_token = token[7:]
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT context_json, expires_at, used_at FROM resume_tokens
                WHERE token_hash = ? AND student_id = ? AND session_id = ?
                """,
                (token_hash, student_id, session_id),
            ).fetchone()
            if not row or row["used_at"]:
                return {}
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                return {}
            if expires_at <= now:
                return {}
            cursor = connection.execute(
                """
                UPDATE resume_tokens SET used_at = ?
                WHERE token_hash = ? AND student_id = ? AND session_id = ? AND used_at = ''
                """,
                (
                    now.isoformat(timespec="seconds"),
                    token_hash,
                    student_id,
                    session_id,
                ),
            )
            connection.commit()
            if cursor.rowcount <= 0:
                return {}
        try:
            parsed = json.loads(str(row["context_json"]))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def record_explanation(
        self,
        student_id: str,
        scene: str,
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = str(result.get("explanation_session_id") or new_id("EXPLAIN"))
        strategy = as_dict(result.get("teaching_strategy")) or as_dict(result.get("teaching_plan"))
        explanation_type = str(
            result.get("explanation_type")
            or strategy.get("strategy_code")
            or ("concept_guidance" if scene == "learn" else "evidence_contrast")
        )
        explanation_mode = str(result.get("explanation_mode") or explanation_type)
        delivery_mode = str(
            result.get("delivery_mode")
            or strategy.get("delivery_mode")
            or strategy.get("primary_mode")
            or "interactive_document"
        )
        identifiers = {
            "task_instance_id": str(context.get("task_instance_id", "")),
            "question_instance_id": str(context.get("question_instance_id", "")),
            "attempt_id": str(context.get("attempt_id", "")),
        }
        references = self._build_source_references(session_id, result)
        enriched = {
            **result,
            **identifiers,
            "explanation_session_id": session_id,
            "scene": scene,
            "explanation_type": explanation_type,
            "explanation_mode": explanation_mode,
            "delivery_mode": delivery_mode,
            "source_references": references,
        }
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO explanation_sessions(
                    explanation_session_id, student_id, task_instance_id,
                    question_instance_id, attempt_id, scene, explanation_type,
                    explanation_mode, delivery_mode, source_explanation_session_id,
                    status, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    student_id,
                    identifiers["task_instance_id"],
                    identifiers["question_instance_id"],
                    identifiers["attempt_id"],
                    scene,
                    explanation_type,
                    explanation_mode,
                    delivery_mode,
                    str(context.get("source_explanation_session_id", "")),
                    str(result.get("status", "unknown")),
                    json_text(enriched),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO explanation_turns(
                    explanation_turn_id, explanation_session_id, role, content_json, created_at
                ) VALUES (?, ?, 'assistant', ?, ?)
                """,
                (new_id("TURN"), session_id, json_text(enriched), now),
            )
            connection.execute(
                "DELETE FROM source_references WHERE explanation_session_id = ?", (session_id,)
            )
            for reference in references:
                connection.execute(
                    """
                    INSERT INTO source_references(
                        source_reference_id, explanation_session_id, source_type,
                        title, document_id, locator, quote_text, url,
                        verification_state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference["source_reference_id"],
                        session_id,
                        reference["source_type"],
                        reference["title"],
                        reference["document_id"],
                        reference["locator"],
                        reference["quote_text"],
                        reference["url"],
                        reference["verification_state"],
                        now,
                    ),
                )
            connection.commit()
        return enriched

    def _build_source_references(
        self, explanation_session_id: str, result: dict[str, Any]
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for source in as_list(result.get("sources")):
            if isinstance(source, dict):
                candidates.append({
                    "source_type": str(source.get("type") or "document"),
                    "title": str(source.get("title") or source.get("source") or "课程资料"),
                    "document_id": str(source.get("document_id") or ""),
                    "locator": str(source.get("locator") or source.get("page") or ""),
                    "quote_text": str(source.get("quote") or ""),
                    "url": str(source.get("url") or ""),
                    "verification_state": str(source.get("verification_state") or "provided"),
                })
            elif str(source).strip():
                candidates.append({
                    "source_type": "document",
                    "title": str(source).strip(),
                    "document_id": "",
                    "locator": "",
                    "quote_text": "",
                    "url": "",
                    "verification_state": "provided",
                })
        for block in as_list(result.get("content_blocks")):
            if isinstance(block, dict) and str(block.get("source", "")).strip():
                candidates.append({
                    "source_type": "document",
                    "title": str(block["source"]).strip(),
                    "document_id": "",
                    "locator": str(block.get("locator") or ""),
                    "quote_text": str(block.get("content") or "")[:280],
                    "url": "",
                    "verification_state": "provided",
                })
        for resource in as_list(result.get("resources")):
            if isinstance(resource, dict):
                candidates.append({
                    "source_type": str(resource.get("type") or "resource"),
                    "title": str(resource.get("title") or resource.get("source") or "学习资源"),
                    "document_id": str(resource.get("document_id") or ""),
                    "locator": str(resource.get("segment") or ""),
                    "quote_text": str(resource.get("reason") or resource.get("description") or "")[:280],
                    "url": str(resource.get("url") or ""),
                    "verification_state": "verified" if resource.get("url") else "provided",
                })
        target = as_dict(result.get("target_error"))
        if target:
            candidates.append({
                "source_type": "diagnosis",
                "title": f"错误诊断 {target.get('error_id') or '上游测验'}",
                "document_id": str(target.get("error_id") or ""),
                "locator": str(target.get("knowledge_point_id") or ""),
                "quote_text": str(target.get("diagnosis") or target.get("student_evidence") or "")[:280],
                "url": "",
                "verification_state": "validated",
            })
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for candidate in candidates:
            key = (candidate["title"], candidate["locator"], candidate["url"])
            if key in seen:
                continue
            seen.add(key)
            unique.append({
                "source_reference_id": new_id("SOURCE"),
                "explanation_session_id": explanation_session_id,
                **candidate,
            })
        return unique

    ACTION_CATEGORIES: dict[str, tuple[str, ...]] = {
        "concept": ("concept", "standard"),
        "steps": ("steps",),
        "example": ("example",),
        "warning": ("warning", "safety"),
        "workplace": ("workplace",),
        "maintenance": ("maintenance",),
        "review": ("warning", "safety", "workplace"),
        "standard": ("standard",),
    }

    def _initialize_knowledge(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
                "title, category, content, source, safety, job_role, "
                "knowledge_point_id, keywords, "
                "content='knowledge_entries', content_rowid='rowid')"
            )
        except sqlite3.OperationalError:
            pass
        try:
            from backend.data.knowledge_seed import KNOWLEDGE_ENTRIES
        except ModuleNotFoundError:
            try:
                from data.knowledge_seed import KNOWLEDGE_ENTRIES
            except (ImportError, ModuleNotFoundError):
                return
        now = utc_now()
        for entry in KNOWLEDGE_ENTRIES:
            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_entries(
                    entry_id, knowledge_point_id, title, category, content, source,
                    source_type, document_id, locator, safety, job_role, action,
                    keywords, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.get("entry_id", "")),
                    str(entry.get("knowledge_point_id", "")),
                    str(entry.get("title", "")),
                    str(entry.get("category", "")),
                    str(entry.get("content", "")),
                    str(entry.get("source", "")),
                    str(entry.get("source_type", "document")),
                    str(entry.get("document_id", "")),
                    str(entry.get("locator", "")),
                    1 if entry.get("safety") else 0,
                    str(entry.get("job_role", "")),
                    str(entry.get("action", "")),
                    str(entry.get("keywords", "")),
                    now,
                ),
            )
        try:
            connection.execute(
                "INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')"
            )
        except sqlite3.OperationalError:
            pass

    def knowledge_count(self) -> int:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM knowledge_entries"
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def search_knowledge(
        self,
        query: str = "",
        knowledge_point_id: str = "",
        action: str = "",
        category: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        knowledge_point_id = str(knowledge_point_id or "").strip()
        action = str(action or "").strip()
        category = str(category or "").strip()
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5
        where: list[str] = []
        params: list[Any] = []
        if knowledge_point_id:
            where.append("k.knowledge_point_id = ?")
            params.append(knowledge_point_id)
        if category:
            where.append("k.category = ?")
            params.append(category)
        elif action and action in self.ACTION_CATEGORIES:
            categories = self.ACTION_CATEGORIES[action]
            where.append("k.category IN ({})".format(",".join("?" * len(categories))))
            params.extend(categories)
        base_where = " AND ".join(where) if where else "1=1"
        rows: list[sqlite3.Row] = []
        with self._lock, closing(self._connect()) as connection:
            if query:
                fts_query = '"' + query.replace('"', '""') + '"'
                try:
                    rows = connection.execute(
                        "SELECT k.* FROM knowledge_entries k "
                        "JOIN knowledge_fts ON knowledge_fts.rowid = k.rowid "
                        f"WHERE {base_where} AND knowledge_fts MATCH ? "
                        "ORDER BY bm25(knowledge_fts) LIMIT ?",
                        params + [fts_query, limit],
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                if not rows:
                    like = f"%{query}%"
                    rows = connection.execute(
                        "SELECT k.* FROM knowledge_entries k "
                        f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                        "OR k.keywords LIKE ? OR k.source LIKE ?) "
                        "ORDER BY k.entry_id LIMIT ?",
                        params + [like, like, like, like, limit],
                    ).fetchall()
                if not rows:
                    # 提问式 query 清洗：先剔除疑问词/停用词，再按标点分词逐 token 检索；
                    # 中文长句整句命中失败时，回退为 2 字滑动窗口关键词。
                    stop_words = {"什么", "如何", "为什么", "怎么", "请", "解释", "一下", "是", "的", "吗", "呢", "有", "没有", "能", "可以", "讲", "说", "什么是", "请解释", "是什么意思"}
                    cleaned = query
                    for word in stop_words:
                        cleaned = cleaned.replace(word, "")
                    tokens = [
                        token
                        for token in re.split(r"[\s/、,，;；|？?！!。.：:]+", cleaned)
                        if len(token) >= 2
                    ]
                    for token in tokens:
                        like = f"%{token}%"
                        rows = connection.execute(
                            "SELECT k.* FROM knowledge_entries k "
                            f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                            "OR k.keywords LIKE ? OR k.source LIKE ?) "
                            "ORDER BY k.entry_id LIMIT ?",
                            params + [like, like, like, like, limit],
                        ).fetchall()
                        if rows:
                            break
                    if not rows and cleaned:
                        # 2 字滑动窗口（去重、按出现顺序），提高中文长句命中率
                        seen: set[str] = set()
                        window_tokens: list[str] = []
                        for i in range(len(cleaned) - 1):
                            piece = cleaned[i:i + 2]
                            if piece not in seen:
                                seen.add(piece)
                                window_tokens.append(piece)
                        for token in window_tokens:
                            like = f"%{token}%"
                            rows = connection.execute(
                                "SELECT k.* FROM knowledge_entries k "
                                f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                                "OR k.keywords LIKE ? OR k.source LIKE ?) "
                                "ORDER BY k.entry_id LIMIT ?",
                                params + [like, like, like, like, limit],
                            ).fetchall()
                            if rows:
                                break
            else:
                rows = connection.execute(
                    "SELECT k.* FROM knowledge_entries k "
                    f"WHERE {base_where} "
                    "ORDER BY k.category, k.entry_id LIMIT ?",
                    params + [limit],
                ).fetchall()
        return [self._knowledge_row_to_dict(row) for row in rows]

    @staticmethod
    def _knowledge_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "entry_id": str(row["entry_id"]),
            "knowledge_point_id": str(row["knowledge_point_id"]),
            "title": str(row["title"]),
            "category": str(row["category"]),
            "content": str(row["content"]),
            "source": str(row["source"]),
            "source_type": str(row["source_type"]),
            "document_id": str(row["document_id"]),
            "locator": str(row["locator"]),
            "safety": bool(row["safety"]),
            "job_role": str(row["job_role"]),
            "action": str(row["action"]),
            "keywords": str(row["keywords"]),
            "url": "",
        }

    def get_sources(self, explanation_session_id: str, student_id: str) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
            if not owner:
                return []
            rows = connection.execute(
                """
                SELECT source_reference_id, source_type, title, document_id,
                       locator, quote_text, url, verification_state, created_at
                FROM source_references WHERE explanation_session_id = ?
                ORDER BY created_at, source_reference_id
                """,
                (explanation_session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def explanation_context(self, explanation_session_id: str, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT result_json FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(str(row["result_json"]))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
        return value if isinstance(value, dict) else {}

    def add_explanation_turn(
        self,
        explanation_session_id: str,
        student_id: str,
        role: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a user or assistant turn for a follow-up conversation."""
        with self._lock, closing(self._connect()) as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
            if not owner:
                raise LookupError("explanation_session_id")
            connection.execute(
                """
                INSERT INTO explanation_turns(
                    explanation_turn_id, explanation_session_id, role, content_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("TURN"), explanation_session_id, role, json_text(content), utc_now()),
            )
            connection.commit()
        return content

    def explanation_sessions_for(self, student_id: str) -> list[dict[str, Any]]:
        """Compact activity list (created_at, scene, knowledge_point_id) for a student."""
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT scene, created_at, result_json FROM explanation_sessions
                WHERE student_id = ?
                ORDER BY created_at ASC
                """,
                (student_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            knowledge_point_id = ""
            try:
                result = json.loads(str(row["result_json"]))
            except json.JSONDecodeError:
                result = {}
            if isinstance(result, dict):
                knowledge_point_id = str(
                    result.get("knowledge_point_id")
                    or as_dict(result.get("learning_target")).get("knowledge_point_id")
                    or ""
                )
            items.append(
                {
                    "scene": str(row["scene"]),
                    "created_at": str(row["created_at"]),
                    "knowledge_point_id": knowledge_point_id,
                }
            )
        return items
    def profile(self, student_id: str) -> dict[str, Any]:
        return {"status": "ok", "profile": self.ensure_profile(student_id)}

    def settings(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT settings_json, updated_at FROM student_settings WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        values = dict(self.DEFAULT_SETTINGS)
        if row:
            try:
                stored = json.loads(str(row["settings_json"]))
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                values.update(stored)
        return {"status": "ok", "student_id": student_id, "settings": values}

    def save_settings(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        values = self.settings(student_id)["settings"]
        allowed = set(self.DEFAULT_SETTINGS)
        values.update({key: value for key, value in incoming.items() if key in allowed})
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO student_settings(student_id, settings_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (student_id, json_text(values), now),
            )
            connection.commit()
        return {"status": "ok", "student_id": student_id, "settings": values, "updated_at": now}

    def toggle_favorite(
        self, student_id: str, knowledge_point_id: str, title: str, favorite: bool
    ) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            if favorite:
                connection.execute(
                    """
                    INSERT INTO student_favorites(student_id, knowledge_point_id, title, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(student_id, knowledge_point_id) DO UPDATE SET title = excluded.title
                    """,
                    (student_id, knowledge_point_id, title, utc_now()),
                )
            else:
                connection.execute(
                    "DELETE FROM student_favorites WHERE student_id = ? AND knowledge_point_id = ?",
                    (student_id, knowledge_point_id),
                )
            connection.commit()
        return {
            "status": "ok",
            "student_id": student_id,
            "knowledge_point_id": knowledge_point_id,
            "favorite": favorite,
        }

    def is_favorite(self, student_id: str, knowledge_point_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM student_favorites
                WHERE student_id = ? AND knowledge_point_id = ?
                """,
                (student_id, knowledge_point_id),
            ).fetchone()
        return bool(row)

    def _ensure_notifications(self, student_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE student_id = ?", (student_id,)
            ).fetchone()[0]
            if count == 0:
                now = utc_now()
                messages = [
                    ("学习路径已更新", "系统已根据最近测验把“平均分统计口径”设为当前节点。"),
                    ("错题讲解已生成", "第 3 题的错误证据、正确要求和重做检查点已经准备完成。"),
                ]
                for title, message in messages:
                    connection.execute(
                        """
                        INSERT INTO notifications(
                            notification_id, student_id, title, message, read_at, created_at
                        ) VALUES (?, ?, ?, ?, '', ?)
                        """,
                        (new_id("NOTICE"), student_id, title, message, now),
                    )
                connection.commit()

    def notifications(self, student_id: str) -> dict[str, Any]:
        self._ensure_notifications(student_id)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT notification_id, title, message, read_at, created_at
                FROM notifications WHERE student_id = ?
                ORDER BY created_at DESC, notification_id DESC LIMIT 20
                """,
                (student_id,),
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "status": "ok",
            "items": items,
            "unread_count": sum(1 for item in items if not item["read_at"]),
        }

    def mark_notification_read(self, student_id: str, notification_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE notifications SET read_at = ?
                WHERE notification_id = ? AND student_id = ?
                """,
                (utc_now(), notification_id, student_id),
            )
            connection.commit()
        return {"status": "ok", "updated": cursor.rowcount == 1}

    def records(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            explanation_rows = connection.execute(
                """
                SELECT explanation_session_id, scene, explanation_type, delivery_mode,
                       status, question_instance_id, attempt_id, created_at
                FROM explanation_sessions WHERE student_id = ?
                ORDER BY created_at DESC LIMIT 30
                """,
                (student_id,),
            ).fetchall()
            attempt_rows = connection.execute(
                """
                SELECT a.attempt_id, a.question_instance_id, a.status, a.created_at,
                       q.title, q.mode, q.source_question_id, q.knowledge_point_id
                FROM attempts a JOIN question_instances q
                  ON q.question_instance_id = a.question_instance_id
                WHERE a.student_id = ? ORDER BY a.created_at DESC LIMIT 30
                """,
                (student_id,),
            ).fetchall()
        return {
            "status": "ok",
            "explanations": [dict(row) for row in explanation_rows],
            "attempts": [dict(row) for row in attempt_rows],
        }

    def record_choice_attempt(
        self,
        student_id: str,
        source_question_id: str,
        mode: str,
        knowledge_point_id: str,
        knowledge_point_name: str,
        title: str,
        prompt: str,
        options: dict[str, Any],
        expected: str,
        selected: str,
        explanation: str = "",
    ) -> dict[str, Any]:
        """选择题作答落库：按 (student, mode, source_question_id) 复用题目实例，
        每次作答写入 attempts，返回判题结果与 attempt 信息。

        供题库刷题 / 学情诊断 / 阶段检查三类选择题共用，保证练习-归因-讲解-画像
        主闭环可溯源（E-2）。
        """
        expected_key = str(expected).strip().lower()
        selected_key = str(selected).strip().lower()
        correct = bool(expected_key) and selected_key == expected_key
        attempt_id = new_id("ATTEMPT")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT question_instance_id FROM question_instances
                WHERE student_id = ? AND mode = ? AND source_question_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (student_id, mode, source_question_id),
            ).fetchone()
            if row:
                question_instance_id = str(row["question_instance_id"])
            else:
                question_instance_id = new_id("QUESTION")
                task_instance_id = new_id("TASKINST")
                connection.execute(
                    """
                    INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                    """,
                    (
                        question_instance_id,
                        student_id,
                        task_instance_id,
                        source_question_id,
                        mode,
                        knowledge_point_id,
                        title,
                        prompt,
                        json_text({
                            "type": "choice",
                            "label": "选择答案",
                            "options": options,
                            "expected": expected,
                        }),
                        expected,
                        now,
                        now,
                    ),
                )
            evaluation = {
                "validation_passed": True,
                "evaluation_status": "correct" if correct else "incorrect",
                "score": 1 if correct else 0,
                "max_score": 1,
                "explanation": explanation,
                "error_points": [] if correct else [{
                    "error_id": "CHOICE_ANSWER_INCORRECT",
                    "knowledge_point_id": knowledge_point_id,
                    "knowledge_point_name": knowledge_point_name or title,
                    "error_type": "practice",
                    "student_evidence": selected,
                    "expected_behavior": expected,
                    "diagnosis": "选择题作答与正确答案不一致",
                    "root_cause": "关键规则尚未稳定掌握",
                    "severity": "medium",
                    "confidence": 1.0,
                }],
            }
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, question_instance_id, student_id, answer_text,
                    evaluation_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_instance_id,
                    student_id,
                    selected,
                    json_text(evaluation),
                    evaluation["evaluation_status"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE question_instances SET status = 'submitted', updated_at = ? WHERE question_instance_id = ?",
                (now, question_instance_id),
            )
            connection.commit()
        return {
            "status": "ok",
            "attempt_id": attempt_id,
            "question_instance_id": question_instance_id,
            "correct": correct,
            "evaluation": evaluation,
        }

    def create_practice(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        mode = str(incoming.get("mode") or "retry_original")
        if mode not in {"retry_original", "variant"}:
            raise ValueError("mode 必须是 retry_original 或 variant")
        task_instance_id = str(incoming.get("task_instance_id", ""))
        source_question_id = str(incoming.get("source_question_instance_id", ""))
        knowledge_id = str(incoming.get("knowledge_point_id") or "KN_JAVA_ENCAPSULATION")
        source = self.question(source_question_id, student_id) if source_question_id else {}
        if not task_instance_id:
            task_instance_id = str(source.get("task_instance_id", ""))

        if mode == "retry_original" and source:
            title = str(source.get("title") or "重做原题")
            prompt = str(source.get("prompt") or "请重新完成原题。")
            schema = as_dict(source.get("answer_schema")) or {"type": "text", "label": "你的答案"}
            expected = str(source.get("expected_answer", ""))
        else:
            # 变式练习模板来自错误卡配置（P1-3），新知识点加配置即可
            template = variant_practice_for(knowledge_id)
            title = str(template.get("title") or "同知识点变式题")
            prompt = str(template.get("prompt") or "请用自己的话说明当前知识点的核心规则，并给出一个应用例子。")
            schema = as_dict(template.get("schema")) or {"type": "text", "label": "你的答案"}
            expected = str(template.get("expected_answer") or "")

        question_instance_id = new_id("QUESTION")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO question_instances(
                    question_instance_id, student_id, task_instance_id, source_question_id,
                    mode, knowledge_point_id, title, prompt, answer_schema_json,
                    expected_answer, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                """,
                (
                    question_instance_id,
                    student_id,
                    task_instance_id,
                    source_question_id,
                    mode,
                    knowledge_id,
                    title,
                    prompt,
                    json_text(schema),
                    expected,
                    now,
                    now,
                ),
            )
            connection.commit()
        return {
            "status": "ok",
            "question": {
                "question_instance_id": question_instance_id,
                "task_instance_id": task_instance_id,
                "source_question_instance_id": source_question_id,
                "mode": mode,
                "knowledge_point_id": knowledge_id,
                "title": title,
                "prompt": prompt,
                "answer_schema": schema,
            },
        }

    def question(self, question_instance_id: str, student_id: str) -> dict[str, Any]:
        if not question_instance_id:
            return {}
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM question_instances
                WHERE question_instance_id = ? AND student_id = ?
                """,
                (question_instance_id, student_id),
            ).fetchone()
        if not row:
            return {}
        result = dict(row)
        try:
            result["answer_schema"] = json.loads(result.pop("answer_schema_json"))
        except json.JSONDecodeError:
            result["answer_schema"] = {"type": "text", "label": "你的答案"}
        return result

    def submit_attempt(
        self, student_id: str, question_instance_id: str, answer: str
    ) -> dict[str, Any]:
        question = self.question(question_instance_id, student_id)
        if not question:
            raise LookupError("题目实例不存在")
        answer = answer.strip()
        if not answer:
            raise ValueError("答案不能为空")
        expected = str(question.get("expected_answer", "")).strip()
        schema_type = str(as_dict(question.get("answer_schema")).get("type", "text"))
        if schema_type == "number":
            try:
                correct = abs(float(answer) - float(expected)) < 1e-9
            except ValueError:
                correct = False
        elif question.get("mode") == "retry_original" and not expected:
            # 无答案标准的 retry 题不得乱判对（历史上曾硬编码 Python 题魔术串）
            correct = False
        else:
            # 语义短语 any 命中；token 长度 ≥3 排除"75/有效"这类泛词误判
            expected_tokens = [
                token for token in expected.replace("或", " ").split() if len(token) >= 3
            ]
            correct = bool(expected_tokens) and any(token in answer for token in expected_tokens)

        attempt_id = new_id("ATTEMPT")
        knowledge_id = str(question.get("knowledge_point_id", ""))
        evaluation = {
            "validation_passed": True,
            "evaluation_status": "correct" if correct else "incorrect",
            "score": 1 if correct else 0,
            "max_score": 1,
            "error_points": [] if correct else [{
                "error_id": "PRACTICE_ANSWER_INCORRECT",
                "knowledge_point_id": knowledge_id,
                "knowledge_point_name": str(question.get("title") or "当前知识点"),
                "error_type": "practice",
                "student_evidence": answer,
                "expected_behavior": expected or "按照题目要求给出完整答案",
                "diagnosis": "本次练习答案与预期要求不一致",
                "root_cause": "关键规则尚未稳定迁移到新题情境",
                "severity": "medium",
                "confidence": 1.0,
            }],
        }
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, question_instance_id, student_id, answer_text,
                    evaluation_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_instance_id,
                    student_id,
                    answer,
                    json_text(evaluation),
                    evaluation["evaluation_status"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE question_instances SET status = 'submitted', updated_at = ? WHERE question_instance_id = ?",
                (now, question_instance_id),
            )
            connection.commit()
        return {
            "status": "ok",
            "attempt_id": attempt_id,
            "question_instance_id": question_instance_id,
            "correct": correct,
            "feedback": "回答正确，可以继续下一项学习。" if correct else "答案尚未满足要求，已准备针对性讲解。",
            "evaluation": evaluation,
            "explanation_input": {
                "question_instance_id": question_instance_id,
                "task_instance_id": str(question.get("task_instance_id", "")),
                "attempt_id": attempt_id,
                "question_snapshot": {
                    "question_id": question_instance_id,
                    "question_text": str(question.get("prompt", "")),
                },
                "current_attempt": {"student_answer": answer},
                "validated_evaluation": evaluation,
            },
        }
