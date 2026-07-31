"""Normalized, transactional operational state for one or more Atlas v2 runs."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator, Mapping


APPLICATION_ID = 0x41544C53  # ATLS
SCHEMA_VERSION = 1


class IncompatibleRunStoreError(ValueError):
    """Raised when a pre-v2 or unknown database is opened as an AtlasRunStore."""


class AtlasRunStore:
    """Own normalized lifecycle, work, attempt, artifact, and event records."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decoded(row: sqlite3.Row, *json_columns: str) -> dict[str, Any]:
        result = dict(row)
        for column in json_columns:
            if result.get(column) is not None:
                result[column] = json.loads(result[column])
        return result

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            existing = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "checkpoint_meta" in existing and "schema_migrations" not in existing:
                raise IncompatibleRunStoreError(
                    "legacy checkpoint database is not an Atlas v2 run store"
                )
            if existing and "schema_migrations" not in existing:
                raise IncompatibleRunStoreError(
                    "unrecognized database is not an Atlas v2 run store"
                )
            connection.executescript(
                """
                PRAGMA application_id=1096043603;
                PRAGMA user_version=1;
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    code_revision TEXT NOT NULL,
                    checksum TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run (
                    run_id TEXT PRIMARY KEY,
                    atlas_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'planned',
                    config_json TEXT NOT NULL,
                    config_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stage_state (
                    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    PRIMARY KEY (run_id, stage)
                );
                CREATE TABLE IF NOT EXISTS work_items (
                    work_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    source_ordinal INTEGER NOT NULL CHECK(source_ordinal >= 0),
                    status TEXT NOT NULL DEFAULT 'pending',
                    UNIQUE(run_id, stage, source_type, source_key)
                );
                CREATE INDEX IF NOT EXISTS work_items_order
                    ON work_items(run_id, stage, source_ordinal, source_key);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_item_id INTEGER NOT NULL
                        REFERENCES work_items(work_item_id) ON DELETE CASCADE,
                    attempt_number INTEGER NOT NULL CHECK(attempt_number > 0),
                    outcome TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    retry_classification TEXT,
                    error_summary TEXT,
                    UNIQUE(work_item_id, attempt_number)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    publication_state TEXT NOT NULL DEFAULT 'published',
                    UNIQUE(run_id, role),
                    UNIQUE(run_id, relative_path)
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    work_item_id INTEGER REFERENCES work_items(work_item_id),
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(run_id, sequence)
                );
                """
            )
            schema_sql = "AtlasRunStore schema version 1"
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(
                    version, code_revision, checksum
                ) VALUES (?, ?, ?)
                """,
                (
                    SCHEMA_VERSION,
                    "atlas-v2",
                    hashlib.sha256(schema_sql.encode("utf-8")).hexdigest(),
                ),
            )

    def create_run(
        self,
        run_id: str,
        atlas_id: str,
        schema_version: str,
        config: Mapping[str, Any],
    ) -> None:
        if not run_id.strip() or not atlas_id.strip():
            raise ValueError("run_id and atlas_id must not be blank")
        config_json = self._json(config)
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO run(
                    run_id, atlas_id, schema_version, config_json, config_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    atlas_id,
                    schema_version,
                    config_json,
                    hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM run WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        result = self._decoded(row, "config_json")
        result["config"] = result.pop("config_json")
        return result

    def set_stage_state(
        self, run_id: str, stage: str, status: str, *, generation: int = 0
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO stage_state(run_id, stage, status, generation, started_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(run_id, stage) DO UPDATE SET
                    status=excluded.status,
                    generation=excluded.generation,
                    completed_at=CASE WHEN excluded.status='complete'
                        THEN CURRENT_TIMESTAMP ELSE NULL END
                """,
                (run_id, stage, status, generation),
            )

    def add_work_item(
        self,
        run_id: str,
        stage: str,
        source_type: str,
        source_key: str,
        source_ordinal: int,
    ) -> int:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO work_items(
                    run_id, stage, source_type, source_key, source_ordinal
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, stage, source_type, source_key, source_ordinal),
            )
            return int(cursor.lastrowid)

    def work_items(self, run_id: str, stage: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM work_items
                WHERE run_id=? AND stage=?
                ORDER BY source_ordinal, source_key
                """,
                (run_id, stage),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_attempt(
        self,
        work_item_id: int,
        *,
        outcome: str,
        retry_classification: str | None = None,
        error_summary: str | None = None,
    ) -> int:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) AS number "
                "FROM attempts WHERE work_item_id=?",
                (work_item_id,),
            ).fetchone()
            number = int(row["number"]) + 1
            connection.execute(
                """
                INSERT INTO attempts(
                    work_item_id, attempt_number, outcome,
                    retry_classification, error_summary
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    number,
                    outcome,
                    retry_classification,
                    error_summary,
                ),
            )
            connection.execute(
                "UPDATE work_items SET status=? WHERE work_item_id=?",
                (outcome, work_item_id),
            )
        return number

    def attempts(self, work_item_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM attempts WHERE work_item_id=? ORDER BY attempt_number",
                (work_item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(
        self,
        run_id: str,
        event_type: str,
        *,
        stage: str | None = None,
        work_item_id: int | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> int:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                "FROM run_events WHERE run_id=?",
                (run_id,),
            ).fetchone()
            sequence = int(row["sequence"]) + 1
            connection.execute(
                """
                INSERT INTO run_events(
                    run_id, sequence, event_type, stage, work_item_id, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    event_type,
                    stage,
                    work_item_id,
                    self._json(detail or {}),
                ),
            )
        return sequence

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM run_events WHERE run_id=? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [self._decoded(row, "detail_json") for row in rows]

    def register_artifact(
        self,
        run_id: str,
        role: str,
        relative_path: str,
        media_type: str,
        sha256: str,
        size_bytes: int,
    ) -> int:
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM artifacts WHERE run_id=? AND role=?",
                (run_id, role),
            ).fetchone()
            if existing is not None and existing["relative_path"] != relative_path:
                raise ValueError("artifact role already has a different path")
            if existing is not None:
                connection.execute(
                    """
                    UPDATE artifacts SET media_type=?, sha256=?, size_bytes=?
                    WHERE artifact_id=?
                    """,
                    (media_type, sha256, size_bytes, existing["artifact_id"]),
                )
                return int(existing["artifact_id"])
            cursor = connection.execute(
                """
                INSERT INTO artifacts(
                    run_id, role, relative_path, media_type, sha256, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, role, relative_path, media_type, sha256, size_bytes),
            )
            return int(cursor.lastrowid)


__all__ = ["AtlasRunStore", "IncompatibleRunStoreError"]
