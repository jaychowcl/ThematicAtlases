from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from benchmark_ThematicAtlases._fibrosis_references import (
    connected_groups,
    load_reference_tsv,
    reference_groups,
    safe_doi,
    safe_pmid,
)


REPORT_NAME = "fibrosis_meta_pubs_query_recall_report.json"
DEFAULT_REFERENCES = (
    Path(__file__).resolve().parents[1]
    / "benchmark_fibrosis_meta_pubs_recall"
    / "fibrosis_meta_publications.tsv"
)
DEFAULT_OUTPUT_DIRECTORY = Path("benchmarks")
COMPLETE_QUERY_STATUSES = frozenset({"available", "no_data"})
INCOMPLETE_QUERY_STATUSES = frozenset(
    {"missing", "pending", "retryable_error", "terminal_error"}
)
QUERY_STATUSES = COMPLETE_QUERY_STATUSES | INCOMPLETE_QUERY_STATUSES
PARTIAL_LIMITATION = (
    "One or more resolved queries are incomplete; query recall is a lower bound "
    "computed from the search pages present in this transaction snapshot."
)


def run_benchmark(*, trace_dir: str | Path, references_tsv: str | Path) -> dict:
    """Compare raw query-search checkpoints with fibrosis publication references."""
    trace_directory = Path(trace_dir)
    reference_path = Path(references_tsv)
    reference_data = load_reference_tsv(reference_path)
    snapshot = _load_query_snapshot(trace_directory)

    aggregate_references = reference_groups(reference_data["rows"])
    publication_groups = _publication_groups(snapshot["publications"])
    aggregate_rows = _match_rows(aggregate_references, publication_groups)

    reference_sets = []
    for set_id in reference_data["set_ids"]:
        set_rows = [
            row for row in reference_data["rows"] if row["reference_set_id"] == set_id
        ]
        matched_rows = _match_rows(reference_groups(set_rows), publication_groups)
        reference_sets.append(
            {
                "id": set_id,
                "summary": _summary(len(set_rows), matched_rows),
                "publications": matched_rows,
            }
        )

    queries = []
    for query in snapshot["queries"]:
        query_publications = [
            publication
            for publication in publication_groups
            if query["ordinal"] in publication["query_ordinals"]
        ]
        query_rows = _match_rows(aggregate_references, query_publications)
        queries.append(
            {
                **query,
                "summary": _summary(len(reference_data["rows"]), query_rows),
            }
        )

    complete = all(query["complete"] for query in snapshot["queries"])
    status_counts: dict[str, int] = {}
    for query in snapshot["queries"]:
        status = query["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "schema_version": "1.0",
        "benchmark": {
            "method": "fibrosis_meta_publication_query_recall",
            "references": {
                "format": "tsv",
                "artifact": str(reference_path),
                "input_record_count": len(reference_data["rows"]),
                "reference_set_count": len(reference_data["set_ids"]),
            },
        },
        "source": {
            "kind": "dev_trace_search_checkpoints",
            "artifact": str(snapshot["database"]),
            "run_id": snapshot["run_id"],
            "complete": complete,
            "score_interpretation": "final" if complete else "lower_bound",
            "query_status_counts": status_counts,
            "limitations": [] if complete else [PARTIAL_LIMITATION],
        },
        "aggregate": {
            "summary": _summary(len(reference_data["rows"]), aggregate_rows),
            "publications": aggregate_rows,
        },
        "reference_sets": reference_sets,
        "queries": queries,
    }


def _load_query_snapshot(trace_directory: Path) -> dict:
    if not trace_directory.is_dir():
        raise ValueError(
            f"trace directory does not exist or is not a directory: {trace_directory}"
        )
    database = trace_directory / "atlas_run.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(
            f"trace does not contain atlas_run.sqlite3: {trace_directory}"
        )

    from ThematicAtlases.runtime.snapshots import read_checkpoint_snapshot
    snapshot = read_checkpoint_snapshot(trace_directory, stages=('search_queries', 'search_pages'))
    if 'resolved_queries' not in snapshot.metadata:
        raise ValueError("trace database is missing resolved_queries metadata")
    try:
        resolved_queries = json.loads(snapshot.metadata["resolved_queries"])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("resolved_queries metadata is not valid JSON") from error
    if (
        not isinstance(resolved_queries, list)
        or not resolved_queries
        or any(not isinstance(query, str) or not query.strip() for query in resolved_queries)
    ):
        raise ValueError("resolved_queries metadata must be a non-empty list of queries")
    if len(set(resolved_queries)) != len(resolved_queries):
        raise ValueError("resolved_queries metadata contains duplicate queries")

    checkpoint_rows = snapshot.items


    search_queries = {
        row["item_key"]: row for row in checkpoint_rows if row["stage"] == "search_queries"
    }
    search_pages = [row for row in checkpoint_rows if row["stage"] == "search_pages"]
    publications = []
    query_reports = []
    for ordinal, query in enumerate(resolved_queries):
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        checkpoint = search_queries.get(query_hash)
        status = "missing" if checkpoint is None else str(checkpoint["status"])
        if status not in QUERY_STATUSES:
            raise ValueError(f"search query {ordinal} has unsupported status: {status}")
        checkpoint_payload = (
            {}
            if checkpoint is None
            else _payload_mapping(checkpoint["payload"], "search query")
        )
        if checkpoint_payload and checkpoint_payload.get("query") != query:
            raise ValueError(f"search query checkpoint does not match resolved query {ordinal}")

        page_count = 0
        raw_hit_count = 0
        total_hits = None
        for page in search_pages:
            if not str(page["item_key"]).startswith(f"{query_hash}:"):
                continue
            if page["status"] != "available":
                raise ValueError(f"search page checkpoint is not available: {page['item_key']}")
            payload = _payload_mapping(page["payload"], "search page")
            if payload.get("query") != query:
                raise ValueError(f"search page checkpoint does not match resolved query {ordinal}")
            page_publications = payload.get("publications")
            if not isinstance(page_publications, list):
                raise ValueError(
                    f"search page checkpoint publications must be a list: {page['item_key']}"
                )
            for publication in page_publications:
                if not isinstance(publication, Mapping):
                    raise ValueError(
                        f"search page checkpoint publications must contain objects: {page['item_key']}"
                    )
                publications.append(
                    {**publication, "_query": query, "_query_ordinal": ordinal}
                )
            page_count += 1
            raw_hit_count += len(page_publications)
            if total_hits is None and payload.get("total_hits") is not None:
                total_hits = payload["total_hits"]

        if status in COMPLETE_QUERY_STATUSES:
            collected_hits = checkpoint_payload.get("collected_hits")
            recorded_pages = checkpoint_payload.get("pages")
            if not isinstance(collected_hits, int) or isinstance(collected_hits, bool):
                raise ValueError(f"completed query {ordinal} has invalid collected_hits")
            if not isinstance(recorded_pages, int) or isinstance(recorded_pages, bool):
                raise ValueError(f"completed query {ordinal} has invalid pages count")
            if collected_hits != raw_hit_count or recorded_pages != page_count:
                raise ValueError(f"completed query {ordinal} checkpoint counts do not match pages")
            if status == "no_data" and raw_hit_count:
                raise ValueError(f"no_data query {ordinal} contains search results")

        query_reports.append(
            {
                "ordinal": ordinal,
                "query": query,
                "status": status,
                "complete": status in COMPLETE_QUERY_STATUSES,
                "page_count": page_count,
                "raw_hit_count": raw_hit_count,
                "total_hits": total_hits,
                "next_cursor": checkpoint_payload.get("next_cursor"),
            }
        )

    return {
        "database": database,
        "run_id": _trace_run_id(trace_directory),
        "queries": query_reports,
        "publications": publications,
    }


def _payload_mapping(raw: object, label: str) -> dict:
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} checkpoint payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} checkpoint payload must be an object")
    return payload

def _trace_run_id(trace_directory: Path) -> str:
    manifest_path = trace_directory / "00_run_manifest.json"
    if not manifest_path.is_file():
        return trace_directory.name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("trace manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise ValueError("trace manifest must be an object")
    run_id = str(manifest.get("run_id") or trace_directory.name).strip()
    if not run_id:
        raise ValueError("trace run_id must be non-empty")
    return run_id


def _publication_groups(publications: list[dict]) -> list[dict]:
    occurrences = []
    for publication in publications:
        doi = safe_doi(publication.get("doi"))
        pmid = safe_pmid(publication.get("pmid"))
        if not doi and not pmid:
            continue
        occurrences.append(
            {
                "doi": doi,
                "pmid": pmid,
                "epmc_id": str(
                    publication.get("epmc_id") or publication.get("id") or ""
                ).strip(),
                "source": str(publication.get("source") or "").strip(),
                "title": str(publication.get("title") or "").strip(),
                "query": publication["_query"],
                "query_ordinal": publication["_query_ordinal"],
            }
        )

    identity_keys = []
    for item in occurrences:
        keys = []
        if item["doi"]:
            keys.append(("doi", item["doi"]))
        if item["pmid"]:
            keys.append(("pmid", item["pmid"]))
        identity_keys.append(keys)

    groups = []
    for indices in connected_groups(identity_keys):
        items = [occurrences[index] for index in indices]
        queries = {
            item["query_ordinal"]: item["query"]
            for item in sorted(items, key=lambda value: value["query_ordinal"])
        }
        groups.append(
            {
                "dois": sorted({item["doi"] for item in items if item["doi"]}),
                "pmids": sorted(
                    {item["pmid"] for item in items if item["pmid"]}, key=int
                ),
                "epmc_ids": sorted(
                    {item["epmc_id"] for item in items if item["epmc_id"]}
                ),
                "sources": sorted({item["source"] for item in items if item["source"]}),
                "titles": sorted({item["title"] for item in items if item["title"]}),
                "query_ordinals": sorted(queries),
                "queries": [
                    {"ordinal": query_ordinal, "query": queries[query_ordinal]}
                    for query_ordinal in sorted(queries)
                ],
            }
        )
    return groups


def _match_rows(references: list[dict], publications: list[dict]) -> list[dict]:
    doi_index: dict[str, set[int]] = {}
    pmid_index: dict[str, set[int]] = {}
    for index, publication in enumerate(publications):
        for doi in publication["dois"]:
            doi_index.setdefault(doi, set()).add(index)
        for pmid in publication["pmids"]:
            pmid_index.setdefault(pmid, set()).add(index)

    rows = []
    for reference in references:
        doi_matches = (
            set().union(*(doi_index.get(doi, set()) for doi in reference["dois"]))
            if reference["dois"]
            else set()
        )
        pmid_matches = (
            set().union(*(pmid_index.get(pmid, set()) for pmid in reference["pmids"]))
            if reference["pmids"]
            else set()
        )
        candidates = doi_matches | pmid_matches
        row = {
            "reference_indices": reference["reference_indices"],
            "references": reference["references"],
            "normalized_identifiers": {
                "dois": reference["dois"],
                "pmids": reference["pmids"],
            },
            "matched_by": [
                identifier
                for identifier, matches in (("doi", doi_matches), ("pmid", pmid_matches))
                if matches
            ],
            "matched_publication": None,
            "conflicting_publications": [],
        }
        if not candidates:
            row["status"] = "missed"
        elif len(candidates) > 1:
            row["status"] = "conflict"
            row["conflicting_publications"] = [
                _publication_result(publications[index]) for index in sorted(candidates)
            ]
        else:
            row["status"] = "matched"
            row["matched_publication"] = _publication_result(
                publications[next(iter(candidates))]
            )
        rows.append(row)
    return rows


def _summary(input_count: int, rows: list[dict]) -> dict:
    total = len(rows)
    matched_count = sum(row["status"] == "matched" for row in rows)
    return {
        "input_record_count": input_count,
        "reference_publication_count": total,
        "duplicate_record_count": input_count - total,
        "matched_count": matched_count,
        "missed_count": sum(row["status"] == "missed" for row in rows),
        "conflict_count": sum(row["status"] == "conflict" for row in rows),
        "query_recall": matched_count / total,
    }


def _publication_result(publication: dict) -> dict:
    return {
        "dois": publication["dois"],
        "pmids": publication["pmids"],
        "epmc_ids": publication["epmc_ids"],
        "sources": publication["sources"],
        "titles": publication["titles"],
        "queries": publication["queries"],
    }


def _write_report(report: dict, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / REPORT_NAME
    temporary_path: Path | None = None
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
            json.dump(report, handle, indent=2, ensure_ascii=False)
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
        description="Benchmark fibrosis publication recall from TA query checkpoints."
    )
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--references", type=Path, default=DEFAULT_REFERENCES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = run_benchmark(
            trace_dir=args.trace_dir,
            references_tsv=args.references,
        )
        report_path = _write_report(report, args.out.resolve())
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        print(f"benchmark failed: {error}", file=sys.stderr)
        return 1
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
