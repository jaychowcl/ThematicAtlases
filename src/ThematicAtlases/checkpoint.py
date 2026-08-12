from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager

import fcntl
from meta_standards_converter.runtime_contracts import (
    ExecutionStatus,
    OperationStatusV2,
)


CHECKPOINT_STATUSES = {
    "pending",
    "available",
    "no_data",
    "retryable_error",
    "terminal_error",
}

STAGE_POLICIES = {
    "query_generation": "discovery",
    "search_queries": "discovery",
    "datalinks": "discovery",
    "fulltext_accession_discovery": "discovery",
    "publication_text": "review",
    "geo_resolution": "metadata",
    "geo_metadata": "metadata",
    "arrayexpress_metadata": "metadata",
    "pubmed_enrichment": "metadata",
    "sra_xml": "metadata",
    "ena_fastq": "metadata",
    "thematic_review": "review",
    "harmonization": "harmonization",
}

HARMONIZATION_RETRY_STAGES = frozenset(
    {
        "target_checker",
        "local_lookup",
        "rag_index_prepare",
        "rag_query_embedding",
        "rag_index_search",
        "rag_judge",
        "ols_lookup_judge",
        "field_assignment",
        "field_assignment_validation",
        "hierarchy_enrichment",
        "structured_response_validation",
    }
)


class CheckpointItemLockTimeout(TimeoutError):
    """Report that another process retained an item lock past its deadline."""


class CheckpointStore:
    """Transactional, run-local storage for resumable workflow items."""

    SCHEMA_VERSION = 2

    def __init__(
        self,
        path: str | Path,
        *,
        default_item_lock_timeout_seconds: int | float | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.default_item_lock_timeout_seconds = self._validated_lock_timeout(
            default_item_lock_timeout_seconds
        )
        self._initialize()

    @staticmethod
    def _validated_lock_timeout(value: int | float | None):
        if (
            value is not None
            and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            )
        ):
            raise ValueError("item lock timeout must be a non-negative number")
        return None if value is None else float(value)

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
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    first_failed_at TEXT,
                    last_attempt_at TEXT,
                    error_type TEXT,
                    failure_category TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stage, item_key)
                );
                CREATE INDEX IF NOT EXISTS checkpoint_items_stage_order
                    ON checkpoint_items(stage, ordinal, item_key);
                CREATE INDEX IF NOT EXISTS checkpoint_items_status_stage_order
                    ON checkpoint_items(status, stage, ordinal, item_key);
                CREATE TABLE IF NOT EXISTS checkpoint_attempt_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stage TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT,
                    error TEXT,
                    attempt_count INTEGER NOT NULL,
                    first_failed_at TEXT,
                    last_attempt_at TEXT,
                    error_type TEXT,
                    failure_category TEXT,
                    replaced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS checkpoint_history_stage_item_order
                    ON checkpoint_attempt_history(stage, item_key, history_id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(checkpoint_items)")
            }
            additions = {
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "first_failed_at": "TEXT",
                "last_attempt_at": "TEXT",
                "error_type": "TEXT",
                "failure_category": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE checkpoint_items ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO checkpoint_meta(key, value) VALUES (?, ?)",
                ("schema_version", json.dumps(self.SCHEMA_VERSION)),
            )
            connection.execute(
                "UPDATE checkpoint_meta SET value = ? WHERE key = ?",
                (json.dumps(self.SCHEMA_VERSION), "schema_version"),
            )
            self._initialize_atlas_projection(connection)

    @staticmethod
    def _initialize_atlas_projection(connection: sqlite3.Connection) -> None:
        """Project the compatibility checkpoint API into normalized v1 rows."""
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"run", "work_items", "attempts"} <= tables:
            return
        run_count = int(connection.execute("SELECT COUNT(*) FROM run").fetchone()[0])
        if run_count != 1:
            raise ValueError(
                "Atlas checkpoint compatibility requires exactly one run per database"
            )
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS checkpoint_item_normalized_insert
            AFTER INSERT ON checkpoint_items
            BEGIN
                INSERT OR IGNORE INTO work_items(
                    run_id, stage, source_type, source_key, source_ordinal,
                    status, payload_json, error_summary, attempt_count,
                    first_failed_at, last_attempt_at, error_type,
                    retry_classification
                )
                SELECT run_id, NEW.stage, 'checkpoint', NEW.item_key,
                       NEW.ordinal, NEW.status, NEW.payload, NEW.error,
                       NEW.attempt_count, NEW.first_failed_at,
                       NEW.last_attempt_at, NEW.error_type,
                       NEW.failure_category
                FROM run LIMIT 1;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_item_normalized_update
            AFTER UPDATE ON checkpoint_items
            BEGIN
                UPDATE work_items
                SET source_ordinal=NEW.ordinal,
                    status=NEW.status,
                    payload_json=NEW.payload,
                    error_summary=NEW.error,
                    attempt_count=NEW.attempt_count,
                    first_failed_at=NEW.first_failed_at,
                    last_attempt_at=NEW.last_attempt_at,
                    error_type=NEW.error_type,
                    retry_classification=NEW.failure_category
                WHERE run_id=(SELECT run_id FROM run LIMIT 1)
                  AND stage=NEW.stage
                  AND source_type='checkpoint'
                  AND source_key=NEW.item_key;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_item_normalized_delete
            AFTER DELETE ON checkpoint_items
            BEGIN
                DELETE FROM work_items
                WHERE run_id=(SELECT run_id FROM run LIMIT 1)
                  AND stage=OLD.stage
                  AND source_type='checkpoint'
                  AND source_key=OLD.item_key;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_history_normalized_insert
            AFTER INSERT ON checkpoint_attempt_history
            BEGIN
                INSERT INTO attempts(
                    work_item_id, attempt_number, outcome,
                    retry_classification, error_summary, payload_json,
                    error_type
                )
                SELECT work_item_id,
                       (SELECT COALESCE(MAX(attempt_number), 0) + 1
                        FROM attempts AS prior
                        WHERE prior.work_item_id=work_items.work_item_id),
                       NEW.status, NEW.failure_category, NEW.error,
                       NEW.payload, NEW.error_type
                FROM work_items
                WHERE run_id=(SELECT run_id FROM run LIMIT 1)
                  AND stage=NEW.stage
                  AND source_type='checkpoint'
                  AND source_key=NEW.item_key;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_meta_normalized_insert
            AFTER INSERT ON checkpoint_meta
            BEGIN
                INSERT OR REPLACE INTO run_metadata(run_id, key, value_json)
                SELECT run_id, NEW.key, NEW.value FROM run LIMIT 1;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_meta_normalized_update
            AFTER UPDATE ON checkpoint_meta
            BEGIN
                UPDATE run_metadata
                SET value_json=NEW.value
                WHERE run_id=(SELECT run_id FROM run LIMIT 1)
                  AND key=NEW.key;
            END;

            CREATE TRIGGER IF NOT EXISTS checkpoint_meta_normalized_delete
            AFTER DELETE ON checkpoint_meta
            BEGIN
                DELETE FROM run_metadata
                WHERE run_id=(SELECT run_id FROM run LIMIT 1)
                  AND key=OLD.key;
            END;
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO work_items(
                run_id, stage, source_type, source_key, source_ordinal,
                status, payload_json, error_summary, attempt_count,
                first_failed_at, last_attempt_at, error_type,
                retry_classification
            )
            SELECT run.run_id, item.stage, 'checkpoint', item.item_key,
                   item.ordinal, item.status, item.payload, item.error,
                   item.attempt_count, item.first_failed_at,
                   item.last_attempt_at, item.error_type,
                   item.failure_category
            FROM checkpoint_items AS item CROSS JOIN run
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO run_metadata(run_id, key, value_json)
            SELECT run.run_id, meta.key, meta.value
            FROM checkpoint_meta AS meta CROSS JOIN run
            """
        )

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

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

    def amend_fingerprint(
        self,
        configuration: dict,
        *,
        amendment_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """Replace a run fingerprint while retaining an atomic audit history."""
        if not amendment_id.strip():
            raise ValueError("amendment_id must not be blank")
        normalized = self._json(configuration)
        replacement = {
            "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "configuration": configuration,
        }
        with self._lock, self._connection() as connection:
            fingerprint_row = connection.execute(
                "SELECT value FROM checkpoint_meta WHERE key = ?",
                ("run_fingerprint",),
            ).fetchone()
            if fingerprint_row is None:
                raise ValueError("run fingerprint must exist before it can be amended")
            previous = json.loads(fingerprint_row["value"])
            history_row = connection.execute(
                "SELECT value FROM checkpoint_meta WHERE key = ?",
                ("run_configuration_amendments",),
            ).fetchone()
            history = [] if history_row is None else json.loads(history_row["value"])
            existing = next(
                (
                    item
                    for item in history
                    if item.get("amendment_id") == amendment_id
                ),
                None,
            )
            if existing is not None:
                if existing.get("replacement", {}).get("sha256") != replacement["sha256"]:
                    raise ValueError(
                        "amendment_id already exists with a different configuration"
                    )
                return existing["previous"]

            amendment = {
                "amendment_id": amendment_id,
                "metadata": metadata or {},
                "previous": previous,
                "replacement": replacement,
            }
            history.append(amendment)
            connection.execute(
                "UPDATE checkpoint_meta SET value = ? WHERE key = ?",
                (self._json(replacement), "run_fingerprint"),
            )
            connection.execute(
                """
                INSERT INTO checkpoint_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                ("run_configuration_amendments", self._json(history)),
            )
        return previous

    def put(
        self,
        stage: str,
        key: str,
        ordinal: int,
        status: str,
        payload=None,
        error: str | None = None,
        error_type: str | None = None,
        failure_category: str | None = None,
    ) -> None:
        if status not in CHECKPOINT_STATUSES:
            raise ValueError(f"unsupported checkpoint status: {status!r}")
        payload_json = None if payload is None else self._json(payload)
        with self._lock, self._connection() as connection:
            previous = connection.execute(
                "SELECT * FROM checkpoint_items WHERE stage = ? AND item_key = ?",
                (stage, key),
            ).fetchone()
            if previous is not None:
                connection.execute(
                    """
                    INSERT INTO checkpoint_attempt_history(
                        stage, item_key, ordinal, status, payload, error,
                        attempt_count, first_failed_at, last_attempt_at,
                        error_type, failure_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        previous["stage"],
                        previous["item_key"],
                        previous["ordinal"],
                        previous["status"],
                        previous["payload"],
                        previous["error"],
                        previous["attempt_count"],
                        previous["first_failed_at"],
                        previous["last_attempt_at"],
                        previous["error_type"],
                        previous["failure_category"],
                    ),
                )
            failed = status in {"retryable_error", "terminal_error"}
            prior_attempts = 0 if previous is None else previous["attempt_count"]
            attempt_count = prior_attempts + (1 if failed else 0)
            first_failed_at = (
                previous["first_failed_at"] if previous is not None else None
            )
            connection.execute(
                """
                INSERT INTO checkpoint_items(
                    stage, item_key, ordinal, status, payload, error,
                    attempt_count, first_failed_at, last_attempt_at,
                    error_type, failure_category, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE ? END,
                    CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(stage, item_key) DO UPDATE SET
                    ordinal=excluded.ordinal,
                    status=excluded.status,
                    payload=excluded.payload,
                    error=excluded.error,
                    attempt_count=excluded.attempt_count,
                    first_failed_at=COALESCE(
                        checkpoint_items.first_failed_at,
                        excluded.first_failed_at
                    ),
                    last_attempt_at=excluded.last_attempt_at,
                    error_type=excluded.error_type,
                    failure_category=excluded.failure_category,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    stage,
                    key,
                    ordinal,
                    status,
                    payload_json,
                    error,
                    attempt_count,
                    failed,
                    first_failed_at,
                    error_type,
                    failure_category,
                ),
            )

    def get(self, stage: str, key: str) -> dict | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM checkpoint_items WHERE stage = ? AND item_key = ?
                """,
                (stage, key),
            ).fetchone()
        return None if row is None else self._item(row)

    def items(self, stage: str) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
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

    def _has_statuses(
        self,
        statuses: set[str],
        stage: str | None = None,
    ) -> bool:
        placeholders = ", ".join("?" for _ in statuses)
        query = f"SELECT 1 FROM checkpoint_items WHERE status IN ({placeholders})"
        params: tuple = tuple(sorted(statuses))
        if stage is not None:
            query += " AND stage = ?"
            params += (stage,)
        query += " LIMIT 1"
        with self._lock, self._connection() as connection:
            return connection.execute(query, params).fetchone() is not None

    def has_actionable(self, stage: str | None = None) -> bool:
        """Return whether resume can automatically attempt pending or transient work."""
        return self._has_statuses({"pending", "retryable_error"}, stage)

    def has_incomplete(self, stage: str | None = None) -> bool:
        """Return whether any automatic or explicitly retried work remains."""
        return self._has_statuses(
            {"pending", "retryable_error", "terminal_error"}, stage
        )

    def has_retryable_boundary(self, boundary: str) -> bool:
        stages = [
            stage for stage, stage_boundary in STAGE_POLICIES.items()
            if stage_boundary == boundary
        ]
        return any(self.has_retryable(stage) for stage in stages)

    def has_actionable_boundary(self, boundary: str) -> bool:
        stages = [
            stage for stage, stage_boundary in STAGE_POLICIES.items()
            if stage_boundary == boundary
        ]
        return any(self.has_actionable(stage) for stage in stages)

    def has_incomplete_boundary(self, boundary: str) -> bool:
        stages = [
            stage for stage, stage_boundary in STAGE_POLICIES.items()
            if stage_boundary == boundary
        ]
        return any(self.has_incomplete(stage) for stage in stages)

    def retry_report(self) -> dict:
        """Summarize automatic resume work and terminal items needing selection."""
        automatic_statuses = {"pending", "retryable_error"}
        report = {
            "requires_retry": False,
            "automatic_retry_count": 0,
            "manual_retry_count": 0,
            "stages": {},
        }
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM checkpoint_items
                WHERE status IN ('pending', 'retryable_error', 'terminal_error')
                ORDER BY stage, ordinal, item_key
                """
            ).fetchall()
        for row in rows:
            item = self._item(row)
            stage_report = report["stages"].setdefault(
                item["stage"], {"counts": {}, "automatic": [], "manual": []}
            )
            status = item["status"]
            stage_report["counts"][status] = stage_report["counts"].get(status, 0) + 1
            detail = {
                key: item[key]
                for key in (
                    "key", "status", "attempt_count", "error",
                    "error_type", "failure_category",
                )
            }
            if status in automatic_statuses:
                stage_report["automatic"].append(detail)
                report["automatic_retry_count"] += 1
            else:
                stage_report["manual"].append(detail)
                report["manual_retry_count"] += 1
        report["requires_retry"] = bool(
            report["automatic_retry_count"] or report["manual_retry_count"]
        )
        return report

    def history(self, stage: str, key: str) -> list[dict]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM checkpoint_attempt_history
                WHERE stage = ? AND item_key = ?
                ORDER BY history_id
                """,
                (stage, key),
            ).fetchall()
        return [self._item(row) for row in rows]

    def request_retries(
        self,
        *,
        stages=(),
        items: dict[str, list[str]] | None = None,
        degraded_stages=(),
    ) -> int:
        """Requeue explicitly selected terminal or degraded work items."""
        selected: dict[tuple[str, str], dict] = {}
        for stage in stages:
            if stage not in STAGE_POLICIES:
                raise ValueError(f"unknown checkpoint stage: {stage!r}")
            for item in self.items(stage):
                if item["status"] == "terminal_error":
                    selected[(stage, item["key"])] = item
        for stage, keys in (items or {}).items():
            if stage not in STAGE_POLICIES:
                raise ValueError(f"unknown checkpoint stage: {stage!r}")
            for key in keys:
                item = self.get(stage, key)
                if item is None:
                    raise ValueError(
                        f"checkpoint item was not found: {stage}:{key}"
                    )
                if item["status"] not in {"terminal_error", "retryable_error"}:
                    raise ValueError(
                        f"checkpoint item is not failed: {stage}:{key}"
                    )
                selected[(stage, key)] = item
        requested_degraded = {str(value) for value in degraded_stages}
        for stage in requested_degraded:
            if stage not in HARMONIZATION_RETRY_STAGES:
                raise ValueError(f"unknown degraded harmonization stage: {stage!r}")
        if requested_degraded:
            for item in self.items("harmonization"):
                payload = item.get("payload") or {}
                try:
                    status = OperationStatusV2.from_dict(payload.get("status", {}))
                except (KeyError, TypeError, ValueError):
                    continue
                observed = (
                    {error.stage for error in status.errors if error.stage}
                    if status.execution is ExecutionStatus.DEGRADED
                    else set()
                )
                if item["status"] == "available" and observed & requested_degraded:
                    selected[("harmonization", item["key"])] = item
        if (stages or items or degraded_stages) and not selected:
            raise ValueError("retry selection did not match any eligible items")
        with self._lock, self._connection() as connection:
            for stage, key in selected:
                connection.execute(
                    """
                    INSERT INTO checkpoint_attempt_history(
                        stage, item_key, ordinal, status, payload, error,
                        attempt_count, first_failed_at, last_attempt_at,
                        error_type, failure_category
                    )
                    SELECT stage, item_key, ordinal, status, payload, error,
                           attempt_count, first_failed_at, last_attempt_at,
                           error_type, failure_category
                    FROM checkpoint_items
                    WHERE stage = ? AND item_key = ?
                    """,
                    (stage, key),
                )
                connection.execute(
                    """
                    UPDATE checkpoint_items
                    SET status = 'retryable_error',
                        error = 'operator requested retry',
                        attempt_count = attempt_count + 1,
                        first_failed_at = COALESCE(
                            first_failed_at, CURRENT_TIMESTAMP
                        ),
                        last_attempt_at = CURRENT_TIMESTAMP,
                        error_type = 'ManualRetry',
                        failure_category = 'manual_retry',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE stage = ? AND item_key = ?
                    """,
                    (stage, key),
                )
        return len(selected)

    def archive_stage(
        self,
        stage: str,
        archive_path: str | Path,
        *,
        archive_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """Atomically move one checkpoint stage into a comparison archive."""
        return self._archive_checkpoint_items(
            stage,
            None,
            archive_path,
            archive_id=archive_id,
            metadata=metadata,
        )

    def archive_items(
        self,
        stage: str,
        item_keys: list[str] | tuple[str, ...] | set[str],
        archive_path: str | Path,
        *,
        archive_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """Atomically move selected keys from one stage into an archive."""
        normalized_keys = sorted(
            {str(value).strip() for value in item_keys if str(value).strip()}
        )
        if not normalized_keys:
            raise ValueError("item_keys must contain at least one non-empty key")
        return self._archive_checkpoint_items(
            stage,
            normalized_keys,
            archive_path,
            archive_id=archive_id,
            metadata=metadata,
        )

    def _archive_checkpoint_items(
        self,
        stage: str,
        item_keys: list[str] | None,
        archive_path: str | Path,
        *,
        archive_id: str,
        metadata: dict | None,
    ) -> dict:
        normalized_stage = str(stage).strip()
        normalized_archive_id = str(archive_id).strip()
        if not normalized_stage:
            raise ValueError("stage must be non-empty")
        if not normalized_archive_id:
            raise ValueError("archive_id must be non-empty")

        destination = Path(archive_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == self.path.resolve():
            raise ValueError("archive database must differ from the live database")

        metadata_json = self._json(metadata or {})
        with self._lock:
            connection = self._connect()
            attached = False
            try:
                connection.execute(
                    "ATTACH DATABASE ? AS checkpoint_archive",
                    (str(destination),),
                )
                attached = True
                connection.execute("BEGIN IMMEDIATE")
                if item_keys is not None:
                    connection.execute(
                        "CREATE TEMP TABLE selected_archive_keys(item_key TEXT PRIMARY KEY)"
                    )
                    connection.executemany(
                        "INSERT INTO selected_archive_keys(item_key) VALUES (?)",
                        ((value,) for value in item_keys),
                    )
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS checkpoint_archive.checkpoint_archive_meta (
                        archive_id TEXT PRIMARY KEY,
                        source_path TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        item_count INTEGER NOT NULL,
                        metadata TEXT NOT NULL,
                        archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS checkpoint_archive.checkpoint_archive_items (
                        archive_id TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        item_key TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        payload TEXT,
                        error TEXT,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        first_failed_at TEXT,
                        last_attempt_at TEXT,
                        error_type TEXT,
                        failure_category TEXT,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (archive_id, stage, item_key)
                    );
                    CREATE INDEX IF NOT EXISTS checkpoint_archive.checkpoint_archive_stage_order
                        ON checkpoint_archive_items(archive_id, stage, ordinal, item_key);
                    """
                )
                archive_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA checkpoint_archive.table_info(checkpoint_archive_items)"
                    )
                }
                for name, definition in {
                    "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                    "first_failed_at": "TEXT",
                    "last_attempt_at": "TEXT",
                    "error_type": "TEXT",
                    "failure_category": "TEXT",
                }.items():
                    if name not in archive_columns:
                        connection.execute(
                            "ALTER TABLE checkpoint_archive.checkpoint_archive_items "
                            f"ADD COLUMN {name} {definition}"
                        )
                if connection.execute(
                    "SELECT 1 FROM checkpoint_archive.checkpoint_archive_meta "
                    "WHERE archive_id = ?",
                    (normalized_archive_id,),
                ).fetchone() is not None:
                    raise ValueError(
                        f"archive_id already exists: {normalized_archive_id!r}"
                    )

                if item_keys is None:
                    selection_sql = "stage = ?"
                else:
                    selection_sql = (
                        "stage = ? AND item_key IN "
                        "(SELECT item_key FROM selected_archive_keys)"
                    )
                source_count = int(connection.execute(
                    f"SELECT COUNT(*) FROM checkpoint_items WHERE {selection_sql}",
                    (normalized_stage,),
                ).fetchone()[0])
                if item_keys is not None and source_count != len(item_keys):
                    missing_count = len(item_keys) - source_count
                    raise ValueError(
                        f"{missing_count} selected checkpoint item(s) were not present "
                        f"in stage {normalized_stage!r}"
                    )
                connection.execute(
                    """
                    INSERT INTO checkpoint_archive.checkpoint_archive_meta(
                        archive_id, source_path, stage, item_count, metadata
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_archive_id,
                        str(self.path),
                        normalized_stage,
                        source_count,
                        metadata_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO checkpoint_archive.checkpoint_archive_items(
                        archive_id, stage, item_key, ordinal, status, payload,
                        error, attempt_count, first_failed_at, last_attempt_at,
                        error_type, failure_category, updated_at
                    )
                    SELECT ?, stage, item_key, ordinal, status, payload, error,
                           attempt_count, first_failed_at, last_attempt_at,
                           error_type, failure_category, updated_at
                    FROM checkpoint_items WHERE """ + selection_sql,
                    (normalized_archive_id, normalized_stage),
                )
                archived_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM "
                        "checkpoint_archive.checkpoint_archive_items "
                        "WHERE archive_id = ? AND stage = ?",
                        (normalized_archive_id, normalized_stage),
                    ).fetchone()[0]
                )
                if archived_count != source_count:
                    raise RuntimeError(
                        "checkpoint archive count did not match the live stage"
                    )
                connection.execute(
                    f"DELETE FROM checkpoint_items WHERE {selection_sql}",
                    (normalized_stage,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                if attached:
                    connection.execute("DETACH DATABASE checkpoint_archive")
                connection.close()

        return {
            "archive_id": normalized_archive_id,
            "stage": normalized_stage,
            "item_count": source_count,
            "archive_path": str(destination),
        }

    def wait_for_provider_slot(
        self,
        provider: str,
        *,
        min_interval_seconds: int | float,
    ) -> float:
        """Pace one provider across every process sharing this run store."""
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")
        if (
            isinstance(min_interval_seconds, bool)
            or not isinstance(min_interval_seconds, (int, float))
            or min_interval_seconds < 0
        ):
            raise ValueError("provider interval must be a non-negative number")
        interval = float(min_interval_seconds)
        lock_directory = self.path.with_name(f"{self.path.name}.locks")
        lock_directory.mkdir(parents=True, exist_ok=True)
        provider_hash = hashlib.sha256(
            provider.strip().lower().encode("utf-8")
        ).hexdigest()
        pace_path = lock_directory / f"provider-{provider_hash}.pace"

        with open(pace_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                try:
                    next_allowed = float(handle.read().decode("ascii") or "0")
                except (UnicodeDecodeError, ValueError):
                    next_allowed = 0.0
                now = time.time()
                next_allowed = min(next_allowed, now + interval)
                delay = max(0.0, next_allowed - now)
                if delay:
                    time.sleep(delay)
                granted_at = time.time()
                handle.seek(0)
                handle.truncate()
                handle.write(f"{granted_at + interval:.9f}".encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
                return delay
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def item_lock(
        self,
        stage: str,
        key: str,
        *,
        timeout_seconds: int | float | None = None,
    ):
        """Serialize expensive work for one checkpoint item across processes."""
        timeout_seconds = self._validated_lock_timeout(
            self.default_item_lock_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        lock_directory = self.path.with_name(f"{self.path.name}.locks")
        lock_directory.mkdir(parents=True, exist_ok=True)
        lock_name = hashlib.sha256(f"{stage}\0{key}".encode("utf-8")).hexdigest()
        lock_path = lock_directory / f"{lock_name}.lock"
        with open(lock_path, "a+b") as handle:
            if timeout_seconds is None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            else:
                deadline = time.monotonic() + float(timeout_seconds)
                while True:
                    try:
                        fcntl.flock(
                            handle.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError as error:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise CheckpointItemLockTimeout(
                                f"checkpoint item lock timed out: {stage}:{key}"
                            ) from error
                        time.sleep(min(0.05, remaining))
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
            "attempt_count": row["attempt_count"],
            "first_failed_at": row["first_failed_at"],
            "last_attempt_at": row["last_attempt_at"],
            "error_type": row["error_type"],
            "failure_category": row["failure_category"],
        }


def is_retryable_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status in {403, 429} or (isinstance(status, int) and status >= 500):
        return True
    trace = getattr(error, "request_trace", None)
    message = str(error).lower()
    markers = (
        "timeout",
        "temporar",
        "connection",
        "429",
        "403",
        "500",
        "502",
        "503",
        "504",
        "resource_exhausted",
    )
    return bool(trace and trace.get("status") == "failed") or any(
        marker in message for marker in markers
    )


def failure_category(error: Exception) -> str:
    try:
        from agentic_curator.curators.structured_response import (
            InvalidModelOutputError,
        )
    except ImportError:
        InvalidModelOutputError = ()  # type: ignore[assignment]
    if InvalidModelOutputError and isinstance(error, InvalidModelOutputError):
        return "invalid_output"
    if is_retryable_error(error):
        return "transient"
    return "permanent"
