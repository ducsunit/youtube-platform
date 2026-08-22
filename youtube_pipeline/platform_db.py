"""SQLite metadata index for pipeline runs.

Artifacts remain files inside runs/<run_id>. This database is deliberately an
index/telemetry store so it can be rebuilt from run_state.json when needed.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .core.state import RunState


SCHEMA_VERSION = 2


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class PlatformDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def for_run_root(cls, run_root: Path) -> "PlatformDatabase":
        # Production layout is <backend>/runs/<run_id>. Unit/integration tests
        # may pass a standalone temporary run root, where climbing two parents
        # would incorrectly attempt to write to the OS temp root.
        root = Path(run_root)
        database_root = root.parent.parent if root.parent.name == "runs" else root
        return cls(database_root / "runtime" / "platform.sqlite3")

    @classmethod
    def path_for_run_root(cls, run_root: Path) -> Path:
        root = Path(run_root)
        database_root = root.parent.parent if root.parent.name == "runs" else root
        return database_root / "runtime" / "platform.sqlite3"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    profile TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    execution_started_at TEXT,
                    execution_finished_at TEXT,
                    execution_elapsed_seconds REAL,
                    total_started_at TEXT,
                    total_finished_at TEXT,
                    total_elapsed_seconds REAL NOT NULL DEFAULT 0,
                    run_dir TEXT NOT NULL,
                    config_snapshot_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_stages (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage_name TEXT NOT NULL,
                    stage_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    metrics_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (run_id, stage_name)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    artifact_type TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    producer_stage TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    qa_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, artifact_type)
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    role TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms REAL,
                    status TEXT NOT NULL,
                    error_type TEXT,
                    error_message TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_model_calls_run_id ON model_calls(run_id, id);
                CREATE TABLE IF NOT EXISTS topic_history (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_concept TEXT NOT NULL,
                    source_work TEXT NOT NULL,
                    audience_moment TEXT NOT NULL,
                    promise TEXT NOT NULL,
                    angle TEXT NOT NULL,
                    mechanisms_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_topic_history_status ON topic_history(status, recorded_at DESC);
                """
            )
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))

    def sync_state(self, state: RunState, run_root: Path) -> None:
        payload = state.to_dict()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    profile=excluded.profile, topic=excluded.topic, status=excluded.status,
                    updated_at=excluded.updated_at, execution_started_at=excluded.execution_started_at,
                    execution_finished_at=excluded.execution_finished_at,
                    execution_elapsed_seconds=excluded.execution_elapsed_seconds,
                    total_started_at=excluded.total_started_at, total_finished_at=excluded.total_finished_at,
                    total_elapsed_seconds=excluded.total_elapsed_seconds, run_dir=excluded.run_dir,
                    config_snapshot_json=excluded.config_snapshot_json,
                    warnings_json=excluded.warnings_json, errors_json=excluded.errors_json""",
                (state.run_id, state.profile, state.topic, state.status, state.created_at, state.updated_at,
                 state.execution_started_at, state.execution_finished_at, state.execution_elapsed_seconds,
                 state.total_started_at, state.total_finished_at, state.total_elapsed_seconds, str(run_root),
                 _json(payload["config_snapshot"]), _json(state.warnings), _json(state.errors)),
            )
            for record in state.stage_records.values():
                connection.execute(
                    """INSERT INTO run_stages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, stage_name) DO UPDATE SET
                        stage_version=excluded.stage_version, status=excluded.status, attempts=excluded.attempts,
                        input_fingerprint=excluded.input_fingerprint, started_at=excluded.started_at,
                        finished_at=excluded.finished_at, metrics_json=excluded.metrics_json,
                        warnings_json=excluded.warnings_json, error=excluded.error""",
                    (state.run_id, record.stage_name, record.stage_version, record.status, record.attempts,
                     record.input_fingerprint, record.started_at, record.finished_at, _json(record.metrics),
                     _json(record.warnings), record.error),
                )
            for ref in state.artifact_index.values():
                connection.execute(
                    """INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, artifact_type) DO UPDATE SET
                        artifact_id=excluded.artifact_id, path=excluded.path, sha256=excluded.sha256,
                        producer_stage=excluded.producer_stage, content_type=excluded.content_type,
                        size_bytes=excluded.size_bytes, qa_status=excluded.qa_status,
                        metadata_json=excluded.metadata_json""",
                    (state.run_id, ref.artifact_type, ref.artifact_id, ref.path, ref.sha256,
                     ref.producer_stage, ref.content_type, ref.size_bytes, ref.qa_status, _json(ref.metadata)),
                )

    def record_model_call_started(self, *, run_id: str, label: str, provider: str, model: str, temperature: float, started_at: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO model_calls(run_id,label,provider,model,temperature,started_at,status) VALUES (?, ?, ?, ?, ?, ?, 'running')",
                (run_id, label, provider, model, temperature, started_at),
            )
            return int(cursor.lastrowid)

    def record_model_call_finished(self, call_id: int, *, finished_at: str, duration_ms: float, status: str, error: BaseException | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_calls SET finished_at=?, duration_ms=?, status=?, error_type=?, error_message=? WHERE id=?",
                (finished_at, duration_ms, status, type(error).__name__ if error else None, str(error) if error else None, call_id),
            )

    def record_completed_topic(self, run_id: str, entry: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO topic_history(
                       run_id,status,topic,title,source_concept,source_work,audience_moment,
                       promise,angle,mechanisms_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                     status=excluded.status, topic=excluded.topic, title=excluded.title,
                     source_concept=excluded.source_concept, source_work=excluded.source_work,
                     audience_moment=excluded.audience_moment, promise=excluded.promise,
                     angle=excluded.angle, mechanisms_json=excluded.mechanisms_json,
                     recorded_at=CURRENT_TIMESTAMP""",
                (
                    run_id, str(entry.get("status", "completed")), str(entry.get("topic", "")),
                    str(entry.get("title", "")), str(entry.get("source_concept", "")),
                    str(entry.get("source_work", "")), str(entry.get("audience_moment", "")),
                    str(entry.get("promise", "")), str(entry.get("angle", "")),
                    _json(entry.get("mechanisms", [])),
                ),
            )

    def set_topic_status(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE topic_history SET status=?, recorded_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (status, run_id),
            )

    def has_run(self, run_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is not None

    def completed_topics(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT run_id,status,topic,title,source_concept,source_work,audience_moment,
                          promise,angle,mechanisms_json
                   FROM topic_history ORDER BY recorded_at"""
            ).fetchall()
        return [
            {
                "run_id": row[0], "status": row[1], "topic": row[2], "selected_topic": row[2],
                "title": row[3], "source_concept": row[4], "source_work": row[5],
                "audience_moment": row[6], "promise": row[7], "angle": row[8],
                "mechanisms": json.loads(row[9]),
            }
            for row in rows
        ]

    def run_diagnostics(self, run_id: str, model_call_limit: int = 100) -> dict[str, Any] | None:
        """Read safe operational metadata for the UI. Never return prompts or secrets."""
        with self._connect() as connection:
            run = connection.execute(
                "SELECT status, updated_at, config_snapshot_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                return None
            stages = connection.execute(
                """SELECT stage_name, status, attempts, started_at, finished_at, metrics_json,
                          warnings_json, error FROM run_stages WHERE run_id=? ORDER BY rowid""",
                (run_id,),
            ).fetchall()
            calls = connection.execute(
                """SELECT label, provider, model, temperature, started_at, finished_at,
                          duration_ms, status, error_type
                   FROM model_calls WHERE run_id=? ORDER BY id DESC LIMIT ?""",
                (run_id, max(1, min(model_call_limit, 200))),
            ).fetchall()
        config = json.loads(run[2])
        stage_rows = [
            {
                "stage_name": row[0], "status": row[1], "attempts": row[2],
                "started_at": row[3], "finished_at": row[4],
                "metrics": json.loads(row[5]), "warnings": json.loads(row[6]), "error": row[7],
            }
            for row in stages
        ]
        call_rows = [
            {
                "label": row[0], "provider": row[1], "model": row[2], "temperature": row[3],
                "started_at": row[4], "finished_at": row[5], "duration_ms": row[6],
                "status": row[7], "error_type": row[8],
            }
            for row in calls
        ]
        return {
            "indexed": True,
            "run_status": run[0],
            "updated_at": run[1],
            "routing_snapshot": config.get("model_routing"),
            "stages": stage_rows,
            "model_calls": {
                "total": len(call_rows),
                "succeeded": sum(row["status"] == "succeeded" for row in call_rows),
                "failed": sum(row["status"] == "failed" for row in call_rows),
                "duration_ms": round(sum(float(row["duration_ms"] or 0) for row in call_rows), 3),
                "calls": call_rows,
            },
        }
