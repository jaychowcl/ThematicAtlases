"""Safe downstream forks of completed metadata collection traces."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.trace import DevTraceWriter


DOWNSTREAM_OVERRIDE_FIELDS = frozenset(
    {
        "theme",
        "review_filter",
        "review_strategy",
        "prune_accessions",
        "harmonization_options",
        "atlas_out",
        "harmonization_details_out",
        "unsupported_accessions_out",
    }
)

_COLLECTION_FILES = (
    "01_collected_accessions.json",
    "resume_publication_collection.json",
    "resume_review_progress.json",
    "unsupported_accessions.json",
)


def fork_metadata_trace(
    *,
    dev_out_dir: str,
    run_id: str,
    new_run_id: str,
    overrides: dict | None = None,
) -> Path:
    """Clone a metadata checkpoint for independent downstream processing."""

    overrides = dict(overrides or {})
    unknown = sorted(set(overrides) - DOWNSTREAM_OVERRIDE_FIELDS)
    if unknown:
        raise ValueError(
            "trace forks accept downstream configuration only; unsupported fields: "
            + ", ".join(unknown)
        )
    _validate_run_id(new_run_id)

    root = Path(dev_out_dir)
    source = root / run_id
    destination = root / new_run_id
    if destination.exists():
        raise FileExistsError(f"fork destination already exists: {destination}")
    manifest_path = source / "00_run_manifest.json"
    database_path = source / "atlas_run.sqlite3"
    collected_path = source / "01_collected_accessions.json"
    if not manifest_path.is_file() or not database_path.is_file():
        raise ValueError("source is not a resumable Atlas v1 trace")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("command") != "create-atlas"
        or manifest.get("stop_after") != "metadata"
        or not collected_path.is_file()
    ):
        raise ValueError("source trace is not paused after metadata collection")
    source_trace = DevTraceWriter.existing(source)
    source_run = source_trace.run_store.get_run(source.name)
    if source_run is None:
        raise ValueError("source trace ledger does not match its run directory")

    downstream_items = sum(
        len(source_trace.checkpoint_store.items(stage))
        for stage in ("thematic_review", "harmonization")
    )
    if downstream_items:
        raise ValueError("source trace already contains downstream work")

    temporary = root / f".{new_run_id}.forking-{uuid4().hex}"
    temporary.mkdir(parents=True)
    try:
        for name in _COLLECTION_FILES:
            source_file = source / name
            if source_file.is_file():
                shutil.copy2(source_file, temporary / name)
        _backup_database(database_path, temporary / "atlas_run.sqlite3")

        forked_manifest = {
            **manifest,
            **overrides,
            "run_id": new_run_id,
            "created_at": new_run_id,
            "forked_from": {
                "run_id": source.name,
                "config_sha256": source_run["config_sha256"],
            },
        }
        _rewrite_database_identity(
            temporary / "atlas_run.sqlite3",
            source_run_id=source.name,
            new_run_id=new_run_id,
            manifest=forked_manifest,
        )
        _amend_fingerprint(
            temporary / "atlas_run.sqlite3",
            new_run_id=new_run_id,
            overrides=overrides,
        )
        _write_json(temporary / "00_run_manifest.json", forked_manifest)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    forked = DevTraceWriter.existing(destination)
    forked.run_store.record_event(
        new_run_id,
        "run_forked",
        detail={"source_run_id": source.name, "overrides": sorted(overrides)},
    )
    return destination


def _validate_run_id(run_id: str) -> None:
    candidate = str(run_id or "").strip()
    if not candidate or candidate in {".", ".."} or Path(candidate).name != candidate:
        raise ValueError("new_run_id must be one non-empty path component")


def _backup_database(source: Path, destination: Path) -> None:
    source_uri = f"file:{source.resolve()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def _rewrite_database_identity(
    path: Path,
    *,
    source_run_id: str,
    new_run_id: str,
    manifest: dict,
) -> None:
    config = {
        key: value
        for key, value in manifest.items()
        if key not in {"artifacts", "run_id"}
    }
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in (
            "stage_state",
            "work_items",
            "artifacts",
            "run_events",
            "run_metadata",
        ):
            connection.execute(
                f"UPDATE {table} SET run_id=? WHERE run_id=?",
                (new_run_id, source_run_id),
            )
        connection.execute(
            """
            UPDATE run
            SET run_id=?, created_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP,
                status='running', config_json=?, config_sha256=?
            WHERE run_id=?
            """,
            (
                new_run_id,
                config_json,
                hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                source_run_id,
            ),
        )
        connection.execute("DELETE FROM artifacts")
        connection.execute("DELETE FROM run_events")


def _amend_fingerprint(path: Path, *, new_run_id: str, overrides: dict) -> None:
    store = CheckpointStore(path)
    current = store.get_meta("run_fingerprint")
    if current is None:
        raise ValueError("source trace does not contain a run fingerprint")
    configuration = dict(current["configuration"])
    for key in (
        "theme",
        "review_filter",
        "review_strategy",
        "prune_accessions",
    ):
        if key in overrides:
            configuration[key] = overrides[key]
    store.amend_fingerprint(
        configuration,
        amendment_id=f"fork-{new_run_id}",
        metadata={"reason": "downstream trace fork"},
    )


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
