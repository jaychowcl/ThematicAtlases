"""Build the external inventory for discovered accessions without metadata handlers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


REPORT_SCHEMA_VERSION = "1.0"
_PUBLICATION_FIELDS = (
    "query",
    "queries",
    "epmc_id",
    "source",
    "pmid",
    "pmcid",
    "doi",
    "title",
    "accession_discovery_sources",
)


def is_unsupported_accession(record: Mapping[str, Any]) -> bool:
    return str(record.get("metadata_status") or "").lower() == "unsupported"


def partition_unsupported_accessions(
    records: list[dict],
) -> tuple[list[dict], list[dict]]:
    supported = []
    unsupported = []
    for record in records:
        (unsupported if is_unsupported_accession(record) else supported).append(record)
    return supported, unsupported


def build_unsupported_accessions_report(
    records: list[dict],
    *,
    atlas_id: str,
    run_id: str,
) -> dict[str, Any]:
    accessions = [_report_record(record) for record in records]
    repository_counts = Counter(
        str(record.get("metadata_repository") or "unknown") for record in accessions
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "atlas_id": atlas_id,
        "run_id": run_id,
        "accessions": accessions,
        "summary": {
            "accession_count": len(accessions),
            "repository_counts": dict(sorted(repository_counts.items())),
        },
    }


def _report_record(record: Mapping[str, Any]) -> dict[str, Any]:
    publications = []
    for raw in record.get("publications", []) or []:
        if not isinstance(raw, Mapping):
            continue
        publication = {
            field: raw[field]
            for field in _PUBLICATION_FIELDS
            if raw.get(field) is not None and raw.get(field) not in ("", (), [])
        }
        if publication:
            publications.append(publication)
    return {
        "datalink_id": str(record.get("datalink_id") or ""),
        "datalink_id_scheme": str(record.get("datalink_id_scheme") or ""),
        "datalink_url": str(record.get("datalink_url") or ""),
        "datalink_category": str(record.get("datalink_category") or ""),
        "accession_repository": str(record.get("accession_repository") or ""),
        "accession_object_type": str(record.get("accession_object_type") or ""),
        "metadata_repository": str(record.get("metadata_repository") or ""),
        "metadata_status": "unsupported",
        "accession_metadata": None,
        "discovery_sources": list(record.get("discovery_sources") or []),
        "publications": publications,
    }


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "build_unsupported_accessions_report",
    "is_unsupported_accession",
    "partition_unsupported_accessions",
]
