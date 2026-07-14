#!/usr/bin/env python3
"""Resolve, datalink, and directly review one packaged reference set."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

from benchmark_ThematicAtlases import ThematicReviewerBenchmark
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.credentials import GoogleCredentialPreflight
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


ROOT = Path(__file__).resolve().parent
THEME_FILE = ROOT / "docs" / "theme_fibrosis.txt"
DEFAULT_REFERENCE_SET = "leonie_2026_fibrosis"
DEFAULT_OUTPUT_ROOT = ROOT / ".out" / "reference_reviews"


def normalize_doi(value) -> str:
    normalized = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def reference_queries(reference_data: dict) -> list[str]:
    return [
        f"DOI:{normalize_doi(item.get('doi'))}"
        for item in reference_data["reference_publications"]
    ]


def exact_reference_matches(
    reference_data: dict,
    publications: list[dict],
) -> tuple[list[dict], list[dict]]:
    by_query = {str(item.get("query", "")): item for item in publications}
    exact = []
    audit = []
    for reference, query in zip(
        reference_data["reference_publications"],
        reference_queries(reference_data),
        strict=True,
    ):
        publication = by_query.get(query)
        expected_doi = normalize_doi(reference.get("doi"))
        actual_doi = normalize_doi((publication or {}).get("doi"))
        status = "unresolved"
        if publication is not None:
            status = "resolved" if actual_doi == expected_doi else "mismatched"
        row = {
            "source_reference_number": reference.get("source_reference_number"),
            "title": reference.get("title"),
            "doi": expected_doi,
            "query": query,
            "status": status,
            "resolved_doi": actual_doi or None,
            "source": (publication or {}).get("source"),
            "epmc_id": (publication or {}).get("epmc_id"),
        }
        audit.append(row)
        if status == "resolved":
            exact.append(publication)
    return exact, audit


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _datalink_audit(
    rows: list[dict],
    *,
    checkpoint_store: CheckpointStore,
) -> dict:
    for row in rows:
        if row["status"] != "resolved":
            row["datalink_status"] = "not_checked"
            row["gse_accessions"] = []
            continue
        key = f"{row['source']}:{row['epmc_id']}"
        checkpoint = checkpoint_store.get("datalinks", key)
        row["datalink_status"] = (checkpoint or {}).get("status", "missing")
        payload = (checkpoint or {}).get("payload") or {}
        row["gse_accessions"] = sorted(
            {
                str(item.get("datalink_id"))
                for item in payload.get("rows", [])
                if str(item.get("datalink_id") or "").upper().startswith("GSE")
            }
        )
    return {
        "summary": {
            "reference_publications": len(rows),
            "resolved": sum(row["status"] == "resolved" for row in rows),
            "unresolved": sum(row["status"] == "unresolved" for row in rows),
            "mismatched": sum(row["status"] == "mismatched" for row in rows),
            "with_gse": sum(bool(row["gse_accessions"]) for row in rows),
            "unique_gse_accessions": len(
                {
                    accession
                    for row in rows
                    for accession in row["gse_accessions"]
                }
            ),
        },
        "publications": rows,
    }


def run_reference_review(
    *,
    reference_set: str,
    theme: str,
    output_dir: Path,
    benchmark=None,
    epmc_wrapper=None,
    filterer=None,
    credential_checker=None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark = benchmark or ThematicReviewerBenchmark()
    epmc_wrapper = epmc_wrapper or EuropePMCWrapper()
    filterer = filterer or AtlasFilterer(
        epmc_wrapper_factory=lambda: epmc_wrapper
    )
    credential_checker = credential_checker or GoogleCredentialPreflight()
    reference_data = benchmark.load_reference_set(reference_set)
    queries = reference_queries(reference_data)
    checkpoint_store = CheckpointStore(output_dir / "resume_state.sqlite")
    checkpoint_store.validate_fingerprint(
        {
            "workflow": "reference-set-review",
            "reference_set": reference_set,
            "queries": queries,
            "theme_sha256": hashlib.sha256(theme.encode("utf-8")).hexdigest(),
            "review_strategy": "direct",
            "metadata_repositories": ["geo"],
        }
    )
    _write_json(
        output_dir / "00_run_manifest.json",
        {
            "reference_set": reference_set,
            "theme_file": str(THEME_FILE),
            "queries": queries,
            "review_strategy": "direct",
            "collect_metadata": False,
            "metadata_repositories": ["geo"],
        },
    )

    publications = epmc_wrapper.collect_publications(
        queries,
        max_publications_per_query=[1] * len(queries),
        checkpoint_store=checkpoint_store,
    )
    exact_publications, resolution_rows = exact_reference_matches(
        reference_data,
        publications,
    )
    datalinks = epmc_wrapper.collect_datalinks(
        exact_publications,
        checkpoint_store=checkpoint_store,
    )
    geo_accessions = AtlasCollector(
        metadata_repositories=["geo"]
    ).filter_accessions(datalinks, metadata_repositories=["geo"])
    audit = _datalink_audit(
        resolution_rows,
        checkpoint_store=checkpoint_store,
    )
    _write_json(output_dir / "01_resolution_datalink_audit.json", audit)
    _write_json(output_dir / "02_geo_accessions.json", geo_accessions)

    publication_texts = filterer.collect_publication_texts(
        jsons=geo_accessions,
        checkpoint_store=checkpoint_store,
    )
    reviewer_accessions = filterer.accessions_with_publication_text_refs(
        jsons=geo_accessions,
        publication_texts=publication_texts,
    )
    reviewer_input = filterer.atlas_object(
        accessions=reviewer_accessions,
        publication_texts=publication_texts,
    )
    _write_json(output_dir / "03_reviewer_input.json", reviewer_input)
    if publication_texts:
        credential_checker.check()
    reviewed = filterer.filter_jsons(
        jsons=reviewer_input,
        theme=theme,
        review_filter="none",
        review_strategy="direct",
        _review_progress_callback=lambda texts: _write_json(
            output_dir / "resume_review_progress.json",
            filterer.atlas_object(
                accessions=filterer.accessions_with_publication_text_refs(
                    jsons=geo_accessions,
                    publication_texts=texts,
                ),
                publication_texts=texts,
            ),
        ),
        _checkpoint_store=checkpoint_store,
    )
    _write_json(output_dir / "04_reviewed_output.json", reviewed)
    report = benchmark.benchmark_reference_publication_recall(
        reference_set=reference_set,
        thematic_output=reviewed,
    )
    _write_json(output_dir / "05_reference_benchmark.json", report)
    return {"audit": audit, "reviewed": reviewed, "benchmark": report}


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with .env/bin/python run_reference_set_review.py"
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-set",
        default=DEFAULT_REFERENCE_SET,
        choices=ThematicReviewerBenchmark.available_reference_sets(),
    )
    return parser.parse_args(argv)


def _configure_logging(path: Path) -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(path)],
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    require_project_venv()
    output_dir = ROOT / ".out" / "reference_reviews" / args.reference_set
    output_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(output_dir / "run.log")
    theme = THEME_FILE.read_text(encoding="utf-8")
    config = {
        "reference_set": args.reference_set,
        "theme_file": str(THEME_FILE),
        "output_dir": str(output_dir),
        "review_scope": "exact publications with GEO datalinks",
    }
    print(json.dumps(config, indent=2))
    result = run_reference_review(
        reference_set=args.reference_set,
        theme=theme,
        output_dir=output_dir,
    )
    summary = {
        "reference_set": args.reference_set,
        "audit": result["audit"],
        "benchmark": result["benchmark"]["summary"],
    }
    _write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
