from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from contextlib import contextmanager

import fcntl


class CheckpointStore:
    """Transactional, run-local storage for resumable workflow items."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoint_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoint_items (
                    stage TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stage, item_key)
                );
                CREATE INDEX IF NOT EXISTS checkpoint_items_stage_order
                    ON checkpoint_items(stage, ordinal, item_key);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO checkpoint_meta(key, value) VALUES (?, ?)",
                ("schema_version", json.dumps(self.SCHEMA_VERSION)),
            )

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)

    def set_meta(self, key: str, value) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO checkpoint_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, self._json(value)),
            )

    def get_meta_json(self, key: str) -> str | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM checkpoint_meta WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def get_meta(self, key: str, default=None):
        value = self.get_meta_json(key)
        return default if value is None else json.loads(value)

    def validate_fingerprint(self, configuration: dict) -> None:
        normalized = self._json(configuration)
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        existing = self.get_meta("run_fingerprint")
        if existing is None:
            self.set_meta(
                "run_fingerprint",
                {"sha256": fingerprint, "configuration": configuration},
            )
            return
        if existing.get("sha256") != fingerprint:
            raise ValueError(
                "checkpoint configuration does not match the requested workflow"
            )

    def put(
        self,
        stage: str,
        key: str,
        ordinal: int,
        status: str,
        payload=None,
        error: str | None = None,
    ) -> None:
        payload_json = None if payload is None else self._json(payload)
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO checkpoint_items(
                    stage, item_key, ordinal, status, payload, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(stage, item_key) DO UPDATE SET
                    ordinal=excluded.ordinal,
                    status=excluded.status,
                    payload=excluded.payload,
                    error=excluded.error,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (stage, key, ordinal, status, payload_json, error),
            )

    def get(self, stage: str, key: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT stage, item_key, ordinal, status, payload, error
                FROM checkpoint_items WHERE stage = ? AND item_key = ?
                """,
                (stage, key),
            ).fetchone()
        return None if row is None else self._item(row)

    def items(self, stage: str) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT stage, item_key, ordinal, status, payload, error
                FROM checkpoint_items WHERE stage = ?
                ORDER BY ordinal, item_key
                """,
                (stage,),
            ).fetchall()
        return [self._item(row) for row in rows]

    def has_retryable(self, stage: str | None = None) -> bool:
        query = "SELECT 1 FROM checkpoint_items WHERE status = 'retryable_error'"
        params: tuple = ()
        if stage is not None:
            query += " AND stage = ?"
            params = (stage,)
        query += " LIMIT 1"
        with self._lock, self._connection() as connection:
            return connection.execute(query, params).fetchone() is not None

    @contextmanager
    def item_lock(self, stage: str, key: str):
        """Serialize expensive work for one checkpoint item across processes."""
        lock_directory = self.path.with_name(f"{self.path.name}.locks")
        lock_directory.mkdir(parents=True, exist_ok=True)
        lock_name = hashlib.sha256(f"{stage}\0{key}".encode("utf-8")).hexdigest()
        lock_path = lock_directory / f"{lock_name}.lock"
        with open(lock_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _item(row: sqlite3.Row) -> dict:
        payload = row["payload"]
        return {
            "stage": row["stage"],
            "key": row["item_key"],
            "ordinal": row["ordinal"],
            "status": row["status"],
            "payload": None if payload is None else json.loads(payload),
            "error": row["error"],
        }


def is_retryable_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status == 429 or (isinstance(status, int) and status >= 500):
        return True
    trace = getattr(error, "request_trace", None)
    message = str(error).lower()
    markers = (
        "timeout",
        "temporar",
        "connection",
        "429",
        "500",
        "502",
        "503",
        "504",
        "resource_exhausted",
    )
    return bool(trace and trace.get("status") == "failed") or any(
        marker in message for marker in markers
    )
