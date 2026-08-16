from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile


REPORT_NAME = "fibrosis_meta_pubs_review_report.json"
CACHE_NAME = "fibrosis_meta_pubs_review_cache.csv"
RAW_CACHE_NAME = "fibrosis_meta_pubs_review_raw_cache.sqlite3"
AUDIT_NAME = "fibrosis_meta_pubs_review_cache_audit.json"
DEFAULT_DATASET = Path(__file__).with_name("fibrosis_meta_publications_review.csv")
DEFAULT_THEME = Path(__file__).with_name("theme_fibrosis.txt")
DEFAULT_OUTPUT_DIRECTORY = Path("benchmarks") / "benchmark_fibrosis_meta_pubs_review"

DATASET_COLUMNS = (
    "publication_id",
    "doi",
    "pmid",
    "expected_decision",
)
CACHE_COLUMNS = (
    "cache_schema_version",
    "publication_id",
    "identity_sha256",
    "resolved_doi",
    "resolved_pmid",
    "title",
    "publication_text",
    "text_source",
    "full_text_status",
    "review_context_json",
    "hydration_status",
    "retrieval_provenance_json",
    "errors_json",
    "retrieved_at_utc",
)
LABELS = ("relevant", "not_relevant", "unsure")
CACHE_SCHEMA_VERSION = "1.0"
CACHE_FIELD_SIZE_LIMIT = 256 * 1024 * 1024
HYDRATION_POLICY_VERSION = "complete-full-metadata-v3-raw-checkpoints"
HYDRATION_ATTEMPTS = 2
RAW_HYDRATION_STAGE = "review_benchmark_hydration"
RAW_SOURCE_STAGES = (
    "search_queries",
    "search_pages",
    "publication_text",
    "datalinks",
    "fulltext_accession_discovery",
    "geo_resolution",
    "geo_metadata",
    "arrayexpress_metadata",
    "pubmed_enrichment",
    "sra_xml",
    "ena_fastq",
)

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", flags=re.IGNORECASE)
DOI_PREFIX = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", flags=re.IGNORECASE
)
PMID_PREFIX = re.compile(r"^pmid\s*:\s*", flags=re.IGNORECASE)

logger = logging.getLogger(__name__)


class ProductionHydrator:
    """Resolve public publication text and TA review context without a trace."""

    def __init__(
        self,
        *,
        epmc_wrapper=None,
        collector=None,
        filterer=None,
        review_service=None,
        checkpoint_store=None,
    ) -> None:
        if epmc_wrapper is None:
            from ThematicAtlases.wrappers.epmc import EuropePMCWrapper

            epmc_wrapper = EuropePMCWrapper()
        if collector is None:
            from ThematicAtlases.collector import AtlasCollector
            from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
            from ThematicAtlases.wrappers.geo import GEOWrapper

            collector = AtlasCollector(
                metadata_handlers={
                    "arrayexpress": ArrayExpressWrapper,
                    "geo": GEOWrapper,
                }
            )
        if filterer is None:
            from ThematicAtlases.filterer import AtlasFilterer

            filterer = AtlasFilterer()
        if review_service is None:
            from ThematicAtlases.filterer import PublicationTextReviewer

            review_service = PublicationTextReviewer()
        self._epmc = epmc_wrapper
        self._collector = collector
        self._filterer = filterer
        self._review_service = review_service
        self._checkpoint_store = checkpoint_store

    def hydrate(self, row: dict) -> dict:
        return self._hydrate(row, cached_metadata_only=False)

    def hydrate_cached(self, row: dict) -> dict:
        """Rebuild compact context strictly from already checkpointed payloads."""

        return self._hydrate(row, cached_metadata_only=True)

    def _hydrate(self, row: dict, *, cached_metadata_only: bool) -> dict:
        query = (
            f"EXT_ID:{row['pmid']} AND SRC:MED"
            if row["pmid"]
            else f"DOI:{row['doi']}"
        )
        checkpoint_options = (
            {} if self._checkpoint_store is None
            else {"checkpoint_store": self._checkpoint_store}
        )
        publications = self._epmc.collect_publications(
            [query], max_publications=2, **checkpoint_options
        )
        matches = [
            publication
            for publication in publications
            if _publication_matches(publication, row)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"identifier lookup for {row['publication_id']!r} returned "
                f"{len(matches)} exact matches"
            )
        publication = matches[0]
        enriched = self._epmc.collect_publication_texts(
            [publication], **checkpoint_options
        )
        if len(enriched) != 1:
            raise ValueError(
                f"publication text lookup for {row['publication_id']!r} "
                "did not return one record"
            )
        enriched_publication = enriched[0]
        publication_text = str(
            enriched_publication.get("text", "") or ""
        ).strip()
        if not publication_text:
            raise ValueError(
                f"publication {row['publication_id']!r} has no full text or abstract"
            )

        datalinks = self._epmc.collect_datalinks(
            [enriched_publication], **checkpoint_options
        )
        linked = self._epmc.accessions_from_datalinks(datalinks)
        scraped = self._epmc.accessions_from_fulltexts(
            [enriched_publication], **checkpoint_options
        )
        accessions = self._epmc.merge_accessions(linked, scraped)
        accessions = self._collector.filter_accessions(accessions)

        errors = []
        try:
            if cached_metadata_only:
                accessions = self._collector.available_accession_metadata(
                    jsons=accessions,
                    checkpoint_store=self._checkpoint_store,
                )
            else:
                accessions = self._collector.collect_accession_metadata(
                    jsons=accessions,
                    **checkpoint_options,
                )
        except Exception as error:
            errors.append(
                {
                    "stage": "metadata",
                    "error_type": type(error).__name__,
                }
            )

        publication_ref = self._filterer.publication_text_ref(
            enriched_publication
        )
        text_mapping = {
            publication_ref: {
                "text": publication_text,
                "text_source": enriched_publication.get("text_source", "none"),
                "full_text_status": enriched_publication.get(
                    "full_text_status", "unavailable"
                ),
            }
        }
        accessions = self._filterer.accessions_with_publication_text_refs(
            jsons=accessions,
            publication_texts=text_mapping,
        )
        contexts = self._review_service.publication_review_contexts(accessions)
        title = str(enriched_publication.get("title", "") or "").strip()
        context = contexts.get(
            publication_ref,
            {
                "title": title,
                "metadata": [],
                "accessions": [],
                "metadata_statuses": {},
            },
        )
        if not context.get("title"):
            context["title"] = title

        text_source = str(enriched_publication.get("text_source", "none"))
        result = {
            "resolved_doi": _safe_doi(enriched_publication.get("doi")),
            "resolved_pmid": _safe_pmid(enriched_publication.get("pmid")),
            "title": title,
            "publication_text": publication_text,
            "text_source": text_source,
            "full_text_status": str(
                enriched_publication.get("full_text_status", "unavailable")
            ),
            "review_context": context,
            "hydration_status": "degraded",
            "retrieval_provenance": {
                "provider": "Europe PMC",
                "query": query,
                "source": str(enriched_publication.get("source", "")),
                "epmc_id": str(enriched_publication.get("epmc_id", "")),
            },
            "errors": errors,
        }
        if _hydration_downloads_complete(result):
            result["hydration_status"] = "available"
        return result


def hydrate_cache(
    *,
    dataset_csv: str | Path,
    cache_csv: str | Path,
    raw_cache: str | Path,
    audit_json: str | Path,
    refresh_cache: bool = False,
    hydrator=None,
) -> dict:
    """Fill the benchmark hydration cache without constructing a reviewer."""

    from ThematicAtlases.checkpoint import CheckpointStore

    dataset_path = Path(dataset_csv)
    cache_path = Path(cache_csv)
    raw_cache_path = Path(raw_cache)
    audit_path = Path(audit_json)
    protected = {dataset_path.resolve(), cache_path.resolve(), audit_path.resolve()}
    if raw_cache_path.resolve() in protected:
        raise ValueError("raw cache path must differ from dataset, CSV cache, and audit")
    if cache_path.resolve() in {dataset_path.resolve(), audit_path.resolve()}:
        raise ValueError("cache path must differ from dataset and audit paths")

    rows = _load_dataset(dataset_path)
    previous_cache = _load_cache(cache_path)
    working_path, requires_publish = _raw_cache_working_path(
        raw_cache_path, refresh_cache=refresh_cache
    )
    store = CheckpointStore(working_path)
    fingerprint = {
        "benchmark": "fibrosis_meta_publication_review_hydration",
        "dataset_sha256": _file_sha256(dataset_path),
        "record_count": len(rows),
        "hydration_policy_version": HYDRATION_POLICY_VERSION,
        "production_sources": [
            "Europe PMC", "PMC", "preprint", "NCBI GEO", "ArrayExpress",
            "BioStudies", "PubMed", "SRA", "ENA",
        ],
    }
    store.validate_fingerprint(fingerprint)
    store.set_meta("cache_fill_state", {"status": "running", "record_count": len(rows)})
    if refresh_cache:
        _requeue_terminal_checkpoints(store)
    hydrator = hydrator or ProductionHydrator(checkpoint_store=store)

    hydrated_rows = []
    reused_count = 0
    refreshed_count = 0
    for index, row in enumerate(rows, start=1):
        identity_hash = _identity_hash(row)
        checkpoint = store.get(RAW_HYDRATION_STAGE, row["publication_id"])
        payload = (checkpoint or {}).get("payload") or {}
        reuse = (
            not refresh_cache
            and checkpoint is not None
            and checkpoint.get("status") == "available"
            and payload.get("identity_sha256") == identity_hash
            and isinstance(payload.get("hydration"), dict)
        )
        logger.info(
            "Reviewer benchmark progress stage=hydrate publication_index=%s "
            "publication_total=%s publication_id=%s raw_cache_action=%s",
            index, len(rows), row["publication_id"], "reuse" if reuse else "refresh",
        )
        if reuse:
            hydration = payload["hydration"]
            reused_count += 1
        else:
            hydration = _hydrate_with_retry(hydrator, row)
            refreshed_count += 1
            store.put(
                RAW_HYDRATION_STAGE,
                row["publication_id"],
                index,
                "available",
                payload={
                    "contract_version": "1.0",
                    "identity_sha256": identity_hash,
                    "hydration": hydration,
                    "terminal_outcome": (
                        "complete" if _hydration_is_complete(hydration)
                        else "retrieval_failed" if hydration.get("hydration_status") == "failed"
                        else "incomplete"
                    ),
                },
            )
        hydrated_rows.append({"dataset": row, "hydration": hydration})

    _terminalize_exhausted_checkpoints(store)
    _reproject_terminal_hydrations(hydrated_rows, hydrator, store)
    cache_rows = [
        _cache_row(item["dataset"], _identity_hash(item["dataset"]), item["hydration"])
        for item in hydrated_rows
    ]
    store.set_meta(
        "cache_fill_state",
        {
            "status": "complete",
            "record_count": len(rows),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    if requires_publish:
        _publish_sqlite_cache(working_path, raw_cache_path)
        store = CheckpointStore(raw_cache_path)

    _write_csv_atomic(cache_path, CACHE_COLUMNS, cache_rows)
    audit = _cache_audit(
        rows=rows,
        hydrated_rows=hydrated_rows,
        previous_cache=previous_cache,
        store=store,
        dataset_path=dataset_path,
        raw_cache_path=raw_cache_path,
        cache_path=cache_path,
    )
    _write_json_atomic(audit_path, audit)
    return {
        "audit_path": audit_path,
        "cache_path": cache_path,
        "raw_cache_path": raw_cache_path,
        "reused_count": reused_count,
        "refreshed_count": refreshed_count,
        "hydrated_rows": hydrated_rows,
        "audit": audit,
    }


def _raw_cache_working_path(
    raw_cache_path: Path, *, refresh_cache: bool
) -> tuple[Path, bool]:
    raw_cache_path.parent.mkdir(parents=True, exist_ok=True)
    staging = raw_cache_path.with_name(f".{raw_cache_path.name}.building")
    if staging.exists():
        return staging, True
    if raw_cache_path.exists() and not refresh_cache:
        return raw_cache_path, False
    if raw_cache_path.exists():
        _checkpoint_sqlite(raw_cache_path)
        shutil.copy2(raw_cache_path, staging)
    return staging, True


def _checkpoint_sqlite(path: Path) -> None:
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        connection.close()


def _publish_sqlite_cache(working_path: Path, raw_cache_path: Path) -> None:
    _checkpoint_sqlite(working_path)
    raw_cache_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(working_path, raw_cache_path)
    for suffix in ("-wal", "-shm"):
        Path(f"{working_path}{suffix}").unlink(missing_ok=True)


def _requeue_terminal_checkpoints(store) -> None:
    """Make only exhausted provider work eligible for an explicit refresh."""

    for stage in RAW_SOURCE_STAGES:
        for item in store.items(stage):
            payload = item.get("payload")
            is_partial_geo = (
                stage == "geo_metadata"
                and item["status"] == "available"
                and isinstance(payload, dict)
                and payload.get("enrichment_mode") == "partial"
            )
            if item["status"] != "terminal_error" and not is_partial_geo:
                continue
            store.put(
                stage,
                item["key"],
                item["ordinal"],
                "retryable_error",
                payload=payload,
                error="explicit benchmark cache refresh requested",
                error_type="ManualRetry",
                failure_category="manual_retry",
            )


def _terminalize_exhausted_checkpoints(store) -> None:
    """Close provider work after the benchmark retry allowance is exhausted."""

    failed_enrichment = {}
    for stage in ("pubmed_enrichment", "sra_xml", "ena_fastq"):
        for item in store.items(stage):
            if item["status"] in {"pending", "retryable_error", "terminal_error"}:
                failed_enrichment[str(item["key"]).upper()] = {
                    "stage": stage,
                    "identifier": item["key"],
                    "status": "failed",
                    "error_type": item.get("error_type"),
                    "failure_category": item.get("failure_category"),
                }

    for stage in RAW_SOURCE_STAGES:
        for item in store.items(stage):
            payload = item.get("payload")
            packages = payload.get("packages") if isinstance(payload, dict) else None
            matching_enrichment_failures = []
            if stage == "geo_metadata" and isinstance(packages, list) and packages:
                serialized_packages = _canonical_json(packages).upper()
                matching_enrichment_failures = [
                    failure
                    for identifier, failure in failed_enrichment.items()
                    if identifier in serialized_packages
                ]
            needs_partial = (
                stage == "geo_metadata"
                and isinstance(packages, list)
                and packages
                and (
                    item["status"] in {"pending", "retryable_error"}
                    or bool(matching_enrichment_failures)
                )
            )
            if not needs_partial and item["status"] not in {"pending", "retryable_error"}:
                continue
            if needs_partial:
                repair_summary = dict(payload.get("repair_summary") or {})
                outcomes = list(repair_summary.get("outcomes", []))
                observed = {
                    (str(value.get("stage")), str(value.get("identifier")))
                    for value in outcomes if isinstance(value, dict)
                }
                outcomes.extend(
                    failure
                    for failure in matching_enrichment_failures
                    if (failure["stage"], str(failure["identifier"])) not in observed
                )
                repair_summary.update(
                    {
                        "contract_version": "1.0",
                        "attempt_count": max(
                            int(repair_summary.get("attempt_count", 0)),
                            int(item.get("attempt_count", 0)),
                            1,
                        ),
                        "failed_count": max(
                            int(repair_summary.get("failed_count", 0)),
                            len(matching_enrichment_failures),
                            1,
                        ),
                        "succeeded_count": int(
                            repair_summary.get("succeeded_count", 0)
                        ),
                        "outcomes": outcomes,
                    }
                )
                store.put(
                    stage,
                    item["key"],
                    item["ordinal"],
                    "available",
                    payload={
                        **payload,
                        "enrichment_mode": "partial",
                        "enrichment_state": "complete",
                        "repair_summary": repair_summary,
                    },
                )
                continue
            store.put(
                stage,
                item["key"],
                item["ordinal"],
                "terminal_error",
                payload=payload,
                error=item.get("error") or _canonical_json(
                    {
                        "error_type": item.get("error_type") or "ExhaustedStage",
                        "failure_category": item.get("failure_category") or "exhausted",
                    }
                ),
                error_type=item.get("error_type") or "ExhaustedStage",
                failure_category=item.get("failure_category") or "exhausted",
            )


def _reproject_terminal_hydrations(hydrated_rows: list[dict], hydrator, store) -> None:
    cached_hydrator = getattr(hydrator, "hydrate_cached", None)
    if not callable(cached_hydrator):
        return
    for index, item in enumerate(hydrated_rows, start=1):
        current = item["hydration"]
        if _hydration_is_complete(current):
            continue
        try:
            candidate = _validated_hydration(cached_hydrator(item["dataset"]))
        except Exception:
            continue
        if _hydration_context_score(candidate) <= _hydration_context_score(current):
            continue
        item["hydration"] = candidate
        row = item["dataset"]
        store.put(
            RAW_HYDRATION_STAGE,
            row["publication_id"],
            index,
            "available",
            payload={
                "contract_version": "1.0",
                "identity_sha256": _identity_hash(row),
                "hydration": candidate,
                "terminal_outcome": (
                    "complete" if _hydration_is_complete(candidate) else "incomplete"
                ),
            },
        )


def _hydration_context_score(hydration: dict) -> tuple[int, int, int, int]:
    context = hydration.get("review_context") or {}
    statuses = context.get("metadata_statuses") or {}
    usable = sum(
        str(status).lower() in {"available", "partial"}
        for status in statuses.values()
    )
    return (
        int(_full_text_available(hydration)),
        len(context.get("accessions") or []),
        usable,
        -len(hydration.get("errors") or []),
    )


def _cache_audit(
    *,
    rows: list[dict],
    hydrated_rows: list[dict],
    previous_cache: dict[str, dict],
    store,
    dataset_path: Path,
    raw_cache_path: Path,
    cache_path: Path,
) -> dict:
    stage_counts = {}
    failures = []
    pending_stage_count = 0
    for stage in (*RAW_SOURCE_STAGES, RAW_HYDRATION_STAGE):
        items = store.items(stage)
        if not items:
            continue
        counts = {}
        for item in items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
            if item["status"] in {"pending", "retryable_error"}:
                pending_stage_count += 1
            if item["status"] in {"retryable_error", "terminal_error"}:
                failures.append(
                    {
                        "stage": stage,
                        "item_id": item["key"],
                        "status": item["status"],
                        "attempt_count": item.get("attempt_count", 0),
                        "error_type": item.get("error_type"),
                        "failure_category": item.get("failure_category"),
                    }
                )
        stage_counts[stage] = counts

    accession_status_counts = {}
    unique_accessions = set()
    publication_audit = []
    recovered_full_texts = 0
    newly_discovered_accessions = set()
    recovered_metadata_packages = set()
    for item in hydrated_rows:
        row = item["dataset"]
        hydration = item["hydration"]
        context = hydration.get("review_context") or {}
        accessions = [str(value) for value in context.get("accessions", [])]
        statuses = {
            str(key): str(value)
            for key, value in (context.get("metadata_statuses") or {}).items()
        }
        unique_accessions.update(accessions)
        for status in statuses.values():
            accession_status_counts[status] = accession_status_counts.get(status, 0) + 1

        previous_row = previous_cache.get(row["publication_id"])
        previous = _hydration_from_cache(previous_row) if previous_row else None
        previous_context = (previous or {}).get("review_context") or {}
        previous_accessions = {
            str(value) for value in previous_context.get("accessions", [])
        }
        newly_discovered_accessions.update(set(accessions) - previous_accessions)
        if (
            previous is not None
            and not _full_text_available(previous)
            and _full_text_available(hydration)
        ):
            recovered_full_texts += 1
        previous_statuses = previous_context.get("metadata_statuses") or {}
        for accession, status in statuses.items():
            if status == "available" and previous_statuses.get(accession) != "available":
                recovered_metadata_packages.add(accession)

        publication_audit.append(
            {
                "publication_id": row["publication_id"],
                "identifiers": {"doi": row["doi"], "pmid": row["pmid"]},
                "text_source": hydration.get("text_source", "none"),
                "full_text_status": hydration.get("full_text_status", "unavailable"),
                "hydration_status": hydration.get("hydration_status", "failed"),
                "terminal_outcome": (
                    "complete" if _hydration_is_complete(hydration)
                    else "retrieval_failed" if hydration.get("hydration_status") == "failed"
                    else "incomplete"
                ),
                "accessions": [
                    {"accession": accession, "metadata_status": statuses.get(accession, "missing")}
                    for accession in accessions
                ],
                "errors": [
                    {
                        "stage": error.get("stage"),
                        "error_type": error.get("error_type"),
                    }
                    for error in hydration.get("errors", [])
                    if isinstance(error, dict)
                ],
            }
        )

    terminal_publications = store.items(RAW_HYDRATION_STAGE)
    summary = {
        "input_count": len(rows),
        "terminal_publication_count": sum(
            item["status"] in {"available", "no_data", "terminal_error"}
            for item in terminal_publications
        ),
        "pending_stage_count": pending_stage_count,
        "complete_count": sum(
            _hydration_is_complete(item["hydration"]) for item in hydrated_rows
        ),
        "degraded_count": sum(
            item["hydration"].get("hydration_status") == "degraded"
            for item in hydrated_rows
        ),
        "retrieval_failed_count": sum(
            item["hydration"].get("hydration_status") == "failed"
            for item in hydrated_rows
        ),
        "supported_accession_count": len(unique_accessions),
        "accession_status_counts": accession_status_counts,
        "recovered_full_text_count": recovered_full_texts,
        "newly_discovered_accession_count": len(newly_discovered_accessions),
        "recovered_metadata_package_count": len(recovered_metadata_packages),
        "exhausted_failure_count": len(failures),
    }
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hydration_policy_version": HYDRATION_POLICY_VERSION,
        "dataset": {
            "artifact": str(dataset_path),
            "sha256": _file_sha256(dataset_path),
            "record_count": len(rows),
        },
        "artifacts": {
            "raw_cache": {
                "artifact": str(raw_cache_path),
                "size_bytes": raw_cache_path.stat().st_size,
            },
            "derived_cache": {
                "artifact": str(cache_path),
                "size_bytes": cache_path.stat().st_size,
            },
        },
        "summary": summary,
        "stage_status_counts": stage_counts,
        "recovered_identifiers": {
            "new_accessions": sorted(newly_discovered_accessions),
            "metadata_packages": sorted(recovered_metadata_packages),
        },
        "failures": failures,
        "publications": publication_audit,
    }


def _full_text_available(hydration: dict) -> bool:
    return (
        hydration.get("text_source") in {"fullTextXML", "preprintJATSXML"}
        and hydration.get("full_text_status") == "available"
        and bool(str(hydration.get("publication_text") or "").strip())
    )


def run_benchmark(
    *,
    dataset_csv: str | Path,
    cache_csv: str | Path,
    theme_file: str | Path = DEFAULT_THEME,
    refresh_cache: bool = False,
    raw_cache: str | Path | None = None,
    audit_json: str | Path | None = None,
    hydrator=None,
    review_runner=None,
) -> dict:
    dataset_path = Path(dataset_csv)
    cache_path = Path(cache_csv)
    theme_path = Path(theme_file)
    if cache_path.resolve() in {dataset_path.resolve(), theme_path.resolve()}:
        raise ValueError("cache path must differ from dataset and theme paths")
    rows = _load_dataset(dataset_path)
    theme = theme_path.read_text(encoding="utf-8").strip()
    if not theme:
        raise ValueError("fibrosis review theme must not be empty")

    if raw_cache is not None:
        fill = hydrate_cache(
            dataset_csv=dataset_path,
            cache_csv=cache_path,
            raw_cache=raw_cache,
            audit_json=(
                Path(audit_json)
                if audit_json is not None
                else cache_path.with_name(AUDIT_NAME)
            ),
            refresh_cache=refresh_cache,
            hydrator=hydrator,
        )
        hydrated_rows = fill["hydrated_rows"]
        reused_count = fill["reused_count"]
        refreshed_count = fill["refreshed_count"]
    else:
        cached = _load_cache(cache_path)
        hydrator = hydrator or ProductionHydrator()
        hydrated_rows = []
        cache_rows = []
        reused_count = 0
        refreshed_count = 0
        for index, row in enumerate(rows, start=1):
            identity_hash = _identity_hash(row)
            cached_row = cached.get(row["publication_id"])
            cached_hydration = (
                _hydration_from_cache(cached_row) if cached_row is not None else None
            )
            reuse_cached = (
                not refresh_cache
                and cached_row is not None
                and cached_row["identity_sha256"] == identity_hash
                and _hydration_is_complete(cached_hydration)
            )
            logger.info(
                "Reviewer benchmark progress stage=hydrate publication_index=%s "
                "publication_total=%s publication_id=%s cache_action=%s",
                index, len(rows), row["publication_id"],
                "reuse" if reuse_cached else "refresh",
            )
            if reuse_cached:
                hydration = cached_hydration
                reused_count += 1
            else:
                refreshed_count += 1
                hydration = _hydrate_with_retry(hydrator, row)
            logger.info(
                "Reviewer benchmark progress stage=hydrate publication_id=%s "
                "hydration_status=%s",
                row["publication_id"], hydration["hydration_status"],
            )
            if not _hydration_is_complete(hydration):
                reason = (
                    "retrieval_failed"
                    if hydration["hydration_status"] == "failed"
                    else "metadata_incomplete"
                )
                logger.info(
                    "Reviewer benchmark progress stage=review publication_id=%s "
                    "review_eligibility=skipped reason=%s",
                    row["publication_id"], reason,
                )
            hydrated_rows.append({"dataset": row, "hydration": hydration})
            cache_rows.append(_cache_row(row, identity_hash, hydration))
        _write_csv_atomic(cache_path, CACHE_COLUMNS, cache_rows)

    reviewable = [
        item
        for item in hydrated_rows
        if _hydration_is_complete(item["hydration"])
    ]
    publication_texts = {
        item["dataset"]["publication_id"]: {
            "text": item["hydration"]["publication_text"],
            "text_source": item["hydration"]["text_source"],
            "full_text_status": item["hydration"]["full_text_status"],
        }
        for item in reviewable
    }
    contexts = {
        item["dataset"]["publication_id"]: item["hydration"]["review_context"]
        for item in reviewable
    }
    reviewed = {}
    review_batch_error = None
    if publication_texts:
        logger.info(
            "Reviewer benchmark progress stage=review publication_total=%s "
            "status=started",
            len(publication_texts),
        )
        try:
            reviewed = (review_runner or _production_review)(
                publication_texts,
                contexts,
                theme,
            )
            logger.info(
                "Reviewer benchmark progress stage=review publication_total=%s "
                "status=complete",
                len(publication_texts),
            )
        except Exception as error:
            review_batch_error = {"error_type": type(error).__name__}
            logger.warning(
                "Reviewer benchmark progress stage=review publication_total=%s "
                "status=failed error_type=%s",
                len(publication_texts),
                type(error).__name__,
            )
    else:
        logger.info(
            "Reviewer benchmark progress stage=review publication_total=0 "
            "status=skipped"
        )

    publication_results = [
        _publication_result(item, reviewed, review_batch_error)
        for item in hydrated_rows
    ]
    summary = _summary(publication_results)
    return {
        "schema_version": "1.0",
        "benchmark": {
            "method": "fibrosis_meta_publication_review",
            "dataset": {
                "artifact": str(dataset_path),
                "sha256": _file_sha256(dataset_path),
                "record_count": len(rows),
            },
            "theme": {
                "artifact": str(theme_path),
                "sha256": _file_sha256(theme_path),
            },
            "cache": {
                "artifact": str(cache_path),
                "schema_version": CACHE_SCHEMA_VERSION,
                "reused_count": reused_count,
                "refreshed_count": refreshed_count,
            },
        },
        "summary": summary,
        "publications": publication_results,
    }


def _load_dataset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if fieldnames != DATASET_COLUMNS:
            raise ValueError(
                "review dataset columns must be exactly: "
                + ", ".join(DATASET_COLUMNS)
            )
        raw_rows = [dict(row) for row in reader]
    if not raw_rows:
        raise ValueError("review dataset requires at least one labeled publication")

    rows = []
    publication_ids = set()
    identity_keys = set()
    for index, raw in enumerate(raw_rows, start=2):
        if raw.get(None):
            raise ValueError(f"review dataset row {index} has unexpected fields")
        publication_id = str(raw.get("publication_id", "") or "").strip()
        if not publication_id:
            raise ValueError(f"review dataset row {index} requires publication_id")
        if publication_id in publication_ids:
            raise ValueError(f"duplicate publication_id in review dataset: {publication_id}")
        publication_ids.add(publication_id)
        doi = _optional_doi(raw.get("doi"), row=index)
        pmid = _optional_pmid(raw.get("pmid"), row=index)
        if not doi and not pmid:
            raise ValueError(f"review dataset row {index} requires a DOI or PMID")
        keys = tuple(key for key in (("doi", doi), ("pmid", pmid)) if key[1])
        if any(key in identity_keys for key in keys):
            raise ValueError(f"duplicate publication identity in review dataset row {index}")
        identity_keys.update(keys)
        expected = _normalize_label(raw.get("expected_decision"))
        if expected not in LABELS:
            raise ValueError(
                f"expected_decision in review dataset row {index} must be one of: "
                + ", ".join(LABELS)
            )
        rows.append(
            {
                "publication_id": publication_id,
                "doi": doi,
                "pmid": pmid,
                "expected_decision": expected,
            }
        )
    return rows


def _load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    previous_field_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(max(previous_field_limit, CACHE_FIELD_SIZE_LIMIT))
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CACHE_COLUMNS:
                raise ValueError("hydration cache has an unsupported column contract")
            rows = [dict(row) for row in reader]
    finally:
        csv.field_size_limit(previous_field_limit)
    result = {}
    for index, row in enumerate(rows, start=2):
        if row.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError(f"hydration cache row {index} has unsupported schema")
        publication_id = row.get("publication_id", "")
        if not publication_id or publication_id in result:
            raise ValueError(f"hydration cache row {index} has invalid publication_id")
        for field in (
            "review_context_json",
            "retrieval_provenance_json",
            "errors_json",
        ):
            try:
                json.loads(row.get(field, ""))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"hydration cache row {index} has invalid {field}"
                ) from error
        result[publication_id] = row
    return result


def _validated_hydration(value: object) -> dict:
    if not isinstance(value, dict):
        raise TypeError("hydrator must return a dictionary")
    required = {
        "resolved_doi",
        "resolved_pmid",
        "title",
        "publication_text",
        "text_source",
        "full_text_status",
        "review_context",
        "hydration_status",
        "retrieval_provenance",
        "errors",
    }
    if not required <= value.keys():
        raise ValueError("hydrator result is missing required fields")
    if value["hydration_status"] not in {"available", "degraded"}:
        raise ValueError("successful hydration status must be available or degraded")
    if not isinstance(value["review_context"], dict):
        raise TypeError("hydrator review_context must be a dictionary")
    if not str(value["publication_text"] or "").strip():
        raise ValueError("hydrator result requires publication text")
    hydration = dict(value)
    hydration["hydration_status"] = (
        "available" if _hydration_downloads_complete(hydration) else "degraded"
    )
    return hydration


def _hydrate_with_retry(hydrator, row: dict) -> dict:
    hydration = None
    for attempt in range(1, HYDRATION_ATTEMPTS + 1):
        logger.info(
            "Reviewer benchmark progress stage=hydrate publication_id=%s "
            "hydration_attempt=%s hydration_attempt_total=%s",
            row["publication_id"],
            attempt,
            HYDRATION_ATTEMPTS,
        )
        try:
            hydration = _validated_hydration(hydrator.hydrate(row))
        except Exception as error:
            hydration = _failed_hydration(error)
            logger.warning(
                "Reviewer benchmark progress stage=hydrate publication_id=%s "
                "hydration_attempt=%s hydration_status=failed error_type=%s",
                row["publication_id"],
                attempt,
                type(error).__name__,
            )
        if _hydration_is_complete(hydration):
            return hydration
        if attempt < HYDRATION_ATTEMPTS:
            logger.warning(
                "Reviewer benchmark progress stage=hydrate publication_id=%s "
                "hydration_attempt=%s hydration_status=incomplete retry=true",
                row["publication_id"],
                attempt,
            )
    return hydration


def _hydration_downloads_complete(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("text_source") or "") not in {
        "fullTextXML",
        "preprintJATSXML",
    }:
        return False
    if str(value.get("full_text_status") or "") != "available":
        return False
    if not str(value.get("publication_text") or "").strip():
        return False
    if value.get("errors"):
        return False
    return _review_context_complete(value.get("review_context"))


def _review_context_complete(value: object) -> bool:
    if not isinstance(value, dict) or not str(value.get("title") or "").strip():
        return False
    accessions = value.get("accessions")
    statuses = value.get("metadata_statuses")
    metadata = value.get("metadata")
    if not isinstance(accessions, list) or not accessions:
        return False
    if not isinstance(statuses, dict) or not isinstance(metadata, list):
        return False
    accession_set = {
        str(accession).strip() for accession in accessions if str(accession).strip()
    }
    if len(accession_set) != len(accessions) or set(statuses) != accession_set:
        return False
    if any(str(statuses[accession]).lower() != "available" for accession in accession_set):
        return False
    complete_metadata = {
        str(item.get("accession") or "").strip()
        for item in metadata
        if isinstance(item, dict)
        and str(item.get("status") or "").lower() == "available"
        and item.get("context")
    }
    return complete_metadata == accession_set


def _hydration_is_complete(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("hydration_status") == "available"
        and _hydration_downloads_complete(value)
    )


def _failed_hydration(error: Exception) -> dict:
    return {
        "resolved_doi": "",
        "resolved_pmid": "",
        "title": "",
        "publication_text": "",
        "text_source": "none",
        "full_text_status": "unavailable",
        "review_context": {},
        "hydration_status": "failed",
        "retrieval_provenance": {},
        "errors": [
            {
                "stage": "hydration",
                "error_type": type(error).__name__,
            }
        ],
    }


def _cache_row(row: dict, identity_hash: str, hydration: dict) -> dict:
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "publication_id": row["publication_id"],
        "identity_sha256": identity_hash,
        "resolved_doi": hydration["resolved_doi"],
        "resolved_pmid": hydration["resolved_pmid"],
        "title": hydration["title"],
        "publication_text": hydration["publication_text"],
        "text_source": hydration["text_source"],
        "full_text_status": hydration["full_text_status"],
        "review_context_json": _canonical_json(hydration["review_context"]),
        "hydration_status": hydration["hydration_status"],
        "retrieval_provenance_json": _canonical_json(
            hydration["retrieval_provenance"]
        ),
        "errors_json": _canonical_json(hydration["errors"]),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _hydration_from_cache(row: dict) -> dict:
    return {
        "resolved_doi": row["resolved_doi"],
        "resolved_pmid": row["resolved_pmid"],
        "title": row["title"],
        "publication_text": row["publication_text"],
        "text_source": row["text_source"],
        "full_text_status": row["full_text_status"],
        "review_context": json.loads(row["review_context_json"]),
        "hydration_status": row["hydration_status"],
        "retrieval_provenance": json.loads(row["retrieval_provenance_json"]),
        "errors": json.loads(row["errors_json"]),
    }


def _production_review(publication_texts: dict, contexts: dict, theme: str) -> dict:
    from agentic_curator import ThematicReviewer
    from ThematicAtlases.filterer import PublicationTextReviewer

    return PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts=contexts,
        theme=theme,
        reviewer=ThematicReviewer(egress_classification="public"),
        strategy="direct",
    )


def _publication_result(item: dict, reviewed: dict, batch_error: dict | None) -> dict:
    dataset = item["dataset"]
    hydration = item["hydration"]
    base = {
        "publication_id": dataset["publication_id"],
        "identifiers": {"doi": dataset["doi"], "pmid": dataset["pmid"]},
        "resolved_identifiers": {
            "doi": hydration["resolved_doi"],
            "pmid": hydration["resolved_pmid"],
        },
        "title": hydration["title"],
        "expected_decision": dataset["expected_decision"],
        "actual_decision": None,
        "correct": None,
        "hydration": {
            "status": hydration["hydration_status"],
            "text_source": hydration["text_source"],
            "full_text_status": hydration["full_text_status"],
            "text_sha256": (
                hashlib.sha256(hydration["publication_text"].encode()).hexdigest()
                if hydration["publication_text"]
                else None
            ),
            "accessions": hydration["review_context"].get("accessions", []),
            "metadata_statuses": hydration["review_context"].get(
                "metadata_statuses", {}
            ),
            "provenance": hydration["retrieval_provenance"],
            "errors": hydration["errors"],
        },
        "review": None,
    }
    if hydration["hydration_status"] == "failed":
        return {**base, "status": "retrieval_failed"}
    if not _hydration_is_complete(hydration):
        return {**base, "status": "metadata_incomplete"}
    if batch_error is not None:
        return {
            **base,
            "status": "review_failed",
            "review": {"error": batch_error},
        }
    publication = reviewed.get(dataset["publication_id"], {})
    review = publication.get("agentic_curator", {})
    if not isinstance(review, dict) or review.get("review_status") == "failed":
        error = review.get("error") if isinstance(review, dict) else None
        return {
            **base,
            "status": "review_failed",
            "review": {
                "error_type": (
                    review.get("error_type") if isinstance(review, dict) else "InvalidReview"
                ),
                "error": error if isinstance(error, dict) else None,
            },
        }
    actual = _normalize_label(review.get("judgement"))
    if actual not in LABELS:
        return {
            **base,
            "status": "review_failed",
            "review": {"error_type": "InvalidReviewJudgement"},
        }
    result = {
        **base,
        "status": "scored",
        "actual_decision": actual,
        "correct": actual == dataset["expected_decision"],
        "review": {
            key: review[key]
            for key in (
                "judgement",
                "reasoning",
                "confidence",
                "criteria",
                "accession_assessments",
                "review_revision",
                "review_contract_version",
                "reviewer_identity",
            )
            if key in review
        },
    }
    return result


def _summary(publications: list[dict]) -> dict:
    scored = [row for row in publications if row["status"] == "scored"]
    confusion = {
        expected: {actual: 0 for actual in LABELS} for expected in LABELS
    }
    expected_counts = {label: 0 for label in LABELS}
    predicted_counts = {label: 0 for label in LABELS}
    for row in publications:
        expected_counts[row["expected_decision"]] += 1
    for row in scored:
        predicted_counts[row["actual_decision"]] += 1
        confusion[row["expected_decision"]][row["actual_decision"]] += 1

    per_class = {}
    for label in LABELS:
        true_positive = confusion[label][label]
        predicted = predicted_counts[label]
        expected = expected_counts[label]
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / expected if expected else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": expected,
        }
    correct = sum(bool(row["correct"]) for row in scored)
    return {
        "input_count": len(publications),
        "hydrated_count": sum(
            row["hydration"]["status"] in {"available", "degraded"}
            for row in publications
        ),
        "degraded_count": sum(
            row["hydration"]["status"] == "degraded" for row in publications
        ),
        "retrieval_failed_count": sum(
            row["status"] == "retrieval_failed" for row in publications
        ),
        "metadata_incomplete_count": sum(
            row["status"] == "metadata_incomplete" for row in publications
        ),
        "review_eligible_count": sum(
            row["hydration"]["status"] == "available" for row in publications
        ),
        "review_completed_count": len(scored),
        "review_failed_count": sum(
            row["status"] == "review_failed" for row in publications
        ),
        "scored_count": len(scored),
        "correct_count": correct,
        "accuracy": correct / len(scored) if scored else None,
        "expected_counts": expected_counts,
        "predicted_counts": predicted_counts,
        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": sum(values["f1"] for values in per_class.values()) / len(LABELS),
    }


def _publication_matches(publication: dict, row: dict) -> bool:
    if row["doi"] and _safe_doi(publication.get("doi")) != row["doi"]:
        return False
    if row["pmid"] and _safe_pmid(publication.get("pmid")) != row["pmid"]:
        return False
    return True


def _normalize_label(value: object) -> str:
    return "_".join(
        str(value or "").strip().lower().replace("-", " ").replace("_", " ").split()
    )


def _optional_doi(value: object, *, row: int) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return _normalize_doi(value)
    except ValueError as error:
        raise ValueError(f"invalid DOI in review dataset row {row}") from error


def _optional_pmid(value: object, *, row: int) -> str:
    if not str(value or "").strip():
        return ""
    try:
        return _normalize_pmid(value)
    except ValueError as error:
        raise ValueError(f"invalid PMID in review dataset row {row}") from error


def _normalize_doi(value: object) -> str:
    doi = DOI_PREFIX.sub("", str(value or "").strip()).strip().rstrip(".,;").lower()
    if not DOI_PATTERN.fullmatch(doi):
        raise ValueError("invalid DOI")
    return doi


def _normalize_pmid(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("invalid PMID")
    pmid = PMID_PREFIX.sub("", str(value or "").strip()).strip()
    if not pmid.isdecimal() or int(pmid) < 1:
        raise ValueError("invalid PMID")
    return str(int(pmid))


def _safe_doi(value: object) -> str:
    try:
        return _normalize_doi(value)
    except ValueError:
        return ""


def _safe_pmid(value: object) -> str:
    try:
        return _normalize_pmid(value)
    except ValueError:
        return ""


def _identity_hash(row: dict) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "doi": row["doi"],
                "pmid": row["pmid"],
                "hydration_policy_version": HYDRATION_POLICY_VERSION,
            }
        ).encode()
    ).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv_atomic(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _write_report(report: dict, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / REPORT_NAME
    _write_json_atomic(report_path, report)
    return report_path


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark TA thematic-review decisions against labeled fibrosis "
            "publication identifiers."
        )
    )
    parser.add_argument("dataset_csv", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--raw-cache", type=Path, default=None)
    parser.add_argument("--hydrate-only", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    output_directory = args.out.resolve()
    report_path = output_directory / REPORT_NAME
    cache_path = (
        args.cache.resolve()
        if args.cache is not None
        else output_directory / CACHE_NAME
    )
    raw_cache_path = (
        args.raw_cache.resolve()
        if args.raw_cache is not None
        else output_directory / RAW_CACHE_NAME
    )
    audit_path = output_directory / AUDIT_NAME
    try:
        protected_inputs = {
            args.dataset_csv.resolve(),
            DEFAULT_THEME.resolve(),
            cache_path.resolve(),
            raw_cache_path.resolve(),
            audit_path.resolve(),
        }
        if report_path.resolve() in protected_inputs:
            raise ValueError("report path must differ from benchmark inputs and caches")
        if args.hydrate_only:
            fill = hydrate_cache(
                dataset_csv=args.dataset_csv,
                cache_csv=cache_path,
                raw_cache=raw_cache_path,
                audit_json=audit_path,
                refresh_cache=args.refresh_cache,
            )
            print(fill["audit_path"])
            return 0
        report = run_benchmark(
            dataset_csv=args.dataset_csv,
            cache_csv=cache_path,
            theme_file=DEFAULT_THEME,
            refresh_cache=args.refresh_cache,
            raw_cache=raw_cache_path,
            audit_json=audit_path,
        )
        report_path = _write_report(report, output_directory)
    except (OSError, TypeError, ValueError) as error:
        print(f"benchmark failed: {error}", file=sys.stderr)
        return 1
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
