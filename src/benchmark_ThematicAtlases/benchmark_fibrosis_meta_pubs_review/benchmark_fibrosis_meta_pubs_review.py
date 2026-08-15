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
import sys
import tempfile


REPORT_NAME = "fibrosis_meta_pubs_review_report.json"
CACHE_NAME = "fibrosis_meta_pubs_review_cache.csv"
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
HYDRATION_POLICY_VERSION = "complete-full-metadata-v2"
HYDRATION_ATTEMPTS = 2

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

    def hydrate(self, row: dict) -> dict:
        query = (
            f"EXT_ID:{row['pmid']} AND SRC:MED"
            if row["pmid"]
            else f"DOI:{row['doi']}"
        )
        publications = self._epmc.collect_publications(
            [query], max_publications=2
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
        enriched = self._epmc.collect_publication_texts([publication])
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

        datalinks = self._epmc.collect_datalinks([enriched_publication])
        linked = self._epmc.accessions_from_datalinks(datalinks)
        scraped = self._epmc.accessions_from_fulltexts([enriched_publication])
        accessions = self._epmc.merge_accessions(linked, scraped)
        accessions = self._collector.filter_accessions(accessions)

        errors = []
        try:
            accessions = self._collector.collect_accession_metadata(
                jsons=accessions
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


def run_benchmark(
    *,
    dataset_csv: str | Path,
    cache_csv: str | Path,
    theme_file: str | Path = DEFAULT_THEME,
    refresh_cache: bool = False,
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
            index,
            len(rows),
            row["publication_id"],
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
            row["publication_id"],
            hydration["hydration_status"],
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
                row["publication_id"],
                reason,
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
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CACHE_COLUMNS:
            raise ValueError("hydration cache has an unsupported column contract")
        rows = [dict(row) for row in reader]
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
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_directory,
            prefix=f".{REPORT_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, report_path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return report_path


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
    try:
        protected_inputs = {
            args.dataset_csv.resolve(),
            DEFAULT_THEME.resolve(),
            cache_path.resolve(),
        }
        if report_path.resolve() in protected_inputs:
            raise ValueError("report path must differ from dataset, theme, and cache paths")
        report = run_benchmark(
            dataset_csv=args.dataset_csv,
            cache_csv=cache_path,
            theme_file=DEFAULT_THEME,
            refresh_cache=args.refresh_cache,
        )
        report_path = _write_report(report, output_directory)
    except (OSError, TypeError, ValueError) as error:
        print(f"benchmark failed: {error}", file=sys.stderr)
        return 1
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
