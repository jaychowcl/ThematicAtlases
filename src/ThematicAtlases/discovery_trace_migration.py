"""Audited migration of stopped pre-graph traces into graph-aware runs."""

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
from ThematicAtlases.trace_fork import (
    _backup_database,
    _rewrite_database_identity,
    _validate_run_id,
    _write_json,
)
from ThematicAtlases.wrappers.pubmed_gds import (
    GDS_SUMMARY_STAGE,
    PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
    PUBMED_GDS_LINK_STAGE,
)


_MAIN_DOWNSTREAM_ARTIFACTS = (
    "01_collected_accessions.json",
    "02_reviewed_datasets.json",
    "03_pre_harmonization_accession_metadata.json",
    "04_harmonization_details.json",
    "05_post_harmonization_accession_metadata.json",
    "06_final_atlas.json",
    "collection_snapshot.json",
    "resume_metadata_enriched_datasets.json",
    "resume_harmonized_datasets.json",
)

_DISCOVERY_FIELDS = (
    "query",
    "query_file",
    "metadata_repositories",
    "max_publications",
    "max_publications_per_query",
    "collect_metadata",
    "scrape_fulltext_accessions",
)

_OUTPUT_FIELDS = (
    "atlas_out",
    "harmonization_details_out",
    "unsupported_accessions_out",
)


def migrate_pre_graph_discovery_trace(
    *,
    dev_out_dir: str,
    run_id: str,
    new_run_id: str,
) -> Path:
    """Clone a stopped mid-Datalinks trace and adopt graph contract 1.0."""

    _validate_run_id(new_run_id)
    if run_id == new_run_id:
        raise ValueError("discovery migration requires a new run identity")
    root = Path(dev_out_dir)
    source = root / run_id
    destination = root / new_run_id
    if destination.exists():
        raise FileExistsError(f"migration destination already exists: {destination}")
    manifest_path = source / "00_run_manifest.json"
    database_path = source / "atlas_run.sqlite3"
    if not manifest_path.is_file() or not database_path.is_file():
        raise ValueError("source is not a resumable Atlas v1 trace")
    _require_healthy_database(database_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("command") != "create-atlas":
        raise ValueError("source is not a create-atlas trace")
    completed_artifacts = [
        name for name in _MAIN_DOWNSTREAM_ARTIFACTS if (source / name).exists()
    ]
    if completed_artifacts:
        raise ValueError(
            "source trace is past discovery: " + ", ".join(completed_artifacts)
        )

    source_trace = DevTraceWriter.existing(source)
    source_run = source_trace.run_store.get_run(run_id)
    if source_run is None:
        raise ValueError("source trace ledger does not match its run directory")
    phase = source_trace.checkpoint_store.get_meta("main_pipeline_phase") or {}
    if phase.get("phase") != "datalinks":
        raise ValueError("source trace must remain in the Datalinks phase")
    if any(
        source_trace.checkpoint_store.items(stage)
        for stage in (PUBMED_GDS_LINK_STAGE, GDS_SUMMARY_STAGE)
    ):
        raise ValueError("source trace already contains graph checkpoints")

    fingerprint = source_trace.checkpoint_store.get_meta("run_fingerprint")
    if fingerprint is None:
        raise ValueError("source trace does not contain a run fingerprint")
    configuration = dict(fingerprint.get("configuration") or {})
    if "pubmed_gds_discovery_contract" in configuration:
        raise ValueError("source trace is already graph-aware")
    _validate_discovery_configuration(manifest, configuration)

    checkpoint_counts = source_trace.checkpoint_store.stage_counts()
    branch_root = root.parent / "branches" / new_run_id
    migrated_manifest = {
        **manifest,
        "run_id": new_run_id,
        "created_at": new_run_id,
        "pubmed_gds_discovery_contract": (
            PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
        ),
        "migrated_from": {
            "run_id": run_id,
            "config_sha256": source_run["config_sha256"],
            "run_fingerprint_sha256": fingerprint["sha256"],
        },
    }
    for field in _OUTPUT_FIELDS:
        value = manifest.get(field)
        if value:
            migrated_manifest[field] = str(branch_root / Path(value).name)

    temporary = root / f".{new_run_id}.migrating-{uuid4().hex}"
    temporary.mkdir(parents=True)
    try:
        migrated_database = temporary / "atlas_run.sqlite3"
        _backup_database(database_path, migrated_database)
        _rewrite_database_identity(
            migrated_database,
            source_run_id=run_id,
            new_run_id=new_run_id,
            manifest=migrated_manifest,
        )
        store = CheckpointStore(migrated_database)
        replacement = {
            **configuration,
            "pubmed_gds_discovery_contract": (
                PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
            ),
        }
        store.amend_fingerprint(
            replacement,
            amendment_id=f"pubmed-gds-{PUBMED_GDS_DISCOVERY_CONTRACT_VERSION}",
            metadata={
                "reason": "adopt exact PubMed-GDS discovery",
                "source_run_id": run_id,
                "new_run_id": new_run_id,
            },
        )
        audit = {
            "source_run_id": run_id,
            "new_run_id": new_run_id,
            "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
            "source_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "previous_fingerprint_sha256": fingerprint["sha256"],
            "replacement_fingerprint_sha256": store.get_meta("run_fingerprint")[
                "sha256"
            ],
            "checkpoint_counts": checkpoint_counts,
        }
        store.set_meta("discovery_contract_migration", audit)
        _write_json(temporary / "00_run_manifest.json", migrated_manifest)
        _require_healthy_database(migrated_database)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    migrated = DevTraceWriter.existing(destination)
    migrated.run_store.record_event(
        new_run_id,
        "discovery_contract_migrated",
        stage="datalinks",
        detail=audit,
    )
    return destination


def _validate_discovery_configuration(manifest: dict, configuration: dict) -> None:
    defaults = {
        "query_file": None,
        "metadata_repositories": None,
        "max_publications": None,
        "max_publications_per_query": None,
        "collect_metadata": True,
        "scrape_fulltext_accessions": False,
    }
    changed = []
    for field in _DISCOVERY_FIELDS:
        expected = configuration.get(field, defaults.get(field))
        actual = manifest.get(field, defaults.get(field))
        if actual != expected:
            changed.append(field)
    if changed:
        raise ValueError(
            "manifest discovery configuration differs from its fingerprint: "
            + ", ".join(changed)
        )


def _require_healthy_database(path: Path) -> None:
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as error:
        raise ValueError("source trace SQLite integrity check failed") from error
    if result is None or result[0] != "ok":
        raise ValueError("source trace SQLite integrity check failed")


__all__ = ["migrate_pre_graph_discovery_trace"]
