from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


pytestmark = pytest.mark.allow_subprocess


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = (
    ROOT
    / "src"
    / "benchmark_ThematicAtlases"
    / "benchmark_fibrosis_meta_pubs_query_recall"
)
RUNNER = BENCHMARK_DIR / "benchmark_fibrosis_meta_pubs_query_recall.py"
REFERENCES = (
    ROOT
    / "src"
    / "benchmark_ThematicAtlases"
    / "benchmark_fibrosis_meta_pubs_recall"
    / "fibrosis_meta_publications.tsv"
)
REPORT_NAME = "fibrosis_meta_pubs_query_recall_report.json"

TSV_COLUMNS = (
    "reference_set_id",
    "source_reference_number",
    "doi",
    "pmid",
    "title",
)


def load_runner():
    spec = importlib.util.spec_from_file_location("fibrosis_query_recall_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=TSV_COLUMNS,
            delimiter="\t",
            quotechar=None,
            quoting=csv.QUOTE_NONE,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def reference_row(
    set_id: str,
    title: str,
    *,
    doi: str = "",
    pmid: str = "",
    number: int = 1,
) -> dict[str, object]:
    return {
        "reference_set_id": set_id,
        "source_reference_number": number,
        "doi": doi,
        "pmid": pmid,
        "title": title,
    }


def write_trace(
    directory: Path,
    queries: list[str],
    *,
    pages: dict[str, list[list[dict]]] | None = None,
    statuses: dict[str, str | None] | None = None,
) -> Path:
    directory.mkdir(parents=True)
    (directory / "00_run_manifest.json").write_text(
        json.dumps({"run_id": directory.name, "command": "create-atlas"}),
        encoding="utf-8",
    )
    database = directory / "atlas_run.sqlite3"
    pages = pages or {}
    statuses = statuses or {}
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE checkpoint_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE checkpoint_items (
                stage TEXT NOT NULL,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload TEXT,
                error TEXT,
                PRIMARY KEY (stage, item_key)
            );
            """
        )
        connection.execute(
            "INSERT INTO checkpoint_meta(key, value) VALUES (?, ?)",
            ("resolved_queries", json.dumps(queries)),
        )
        for query_index, query in enumerate(queries):
            query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
            query_pages = pages.get(query, [])
            collected_hits = 0
            for page_index, publications in enumerate(query_pages, start=1):
                collected_hits += len(publications)
                connection.execute(
                    """
                    INSERT INTO checkpoint_items(
                        stage, item_key, ordinal, status, payload, error
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "search_pages",
                        f"{query_hash}:{page_index:06d}",
                        query_index * 1_000_000 + page_index,
                        "available",
                        json.dumps(
                            {
                                "query": query,
                                "publications": publications,
                                "total_hits": collected_hits,
                                "next_cursor": None,
                            }
                        ),
                        None,
                    ),
                )
            status = statuses.get(query, "available" if collected_hits else "no_data")
            if status is None:
                continue
            connection.execute(
                """
                INSERT INTO checkpoint_items(
                    stage, item_key, ordinal, status, payload, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "search_queries",
                    query_hash,
                    query_index,
                    status,
                    json.dumps(
                        {
                            "query": query,
                            "pages": len(query_pages),
                            "next_cursor": None,
                            "collected_hits": collected_hits,
                        }
                    ),
                    "query failed" if status.endswith("error") else None,
                ),
            )
    return directory


def small_references(path: Path) -> Path:
    write_tsv(
        path,
        [
            reference_row("set-a", "DOI publication", doi="10.1000/one"),
            reference_row("set-a", "PMID publication", pmid="2", number=2),
            reference_row("set-a", "Missing publication", pmid="3", number=3),
            reference_row("set-b", "Duplicate DOI publication", doi="10.1000/one"),
        ],
    )
    return path


def test_query_recall_runner_layout_and_shared_reference_fixture() -> None:
    assert RUNNER.is_file()
    assert REFERENCES.is_file()
    assert not (BENCHMARK_DIR / "fibrosis_meta_publications.tsv").exists()


def test_report_scores_union_reference_sets_and_each_query(tmp_path: Path) -> None:
    runner = load_runner()
    references = small_references(tmp_path / "references.tsv")
    trace = write_trace(
        tmp_path / "trace-run",
        ["query one", "query two"],
        pages={
            "query one": [
                [
                    {
                        "query": "query one",
                        "source": "MED",
                        "id": "1",
                        "doi": "DOI: 10.1000/ONE",
                        "title": "Found by DOI",
                    }
                ]
            ],
            "query two": [
                [
                    {
                        "query": "query two",
                        "source": "MED",
                        "id": "2",
                        "pmid": "PMID: 2",
                        "title": "Found by PMID",
                    }
                ]
            ],
        },
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["schema_version"] == "1.0"
    assert report["benchmark"]["method"] == "fibrosis_meta_publication_query_recall"
    assert report["source"] == {
        "kind": "dev_trace_search_checkpoints",
        "artifact": str(trace / "atlas_run.sqlite3"),
        "run_id": "trace-run",
        "complete": True,
        "score_interpretation": "final",
        "query_status_counts": {"available": 2},
        "limitations": [],
    }
    assert report["aggregate"]["summary"] == {
        "input_record_count": 4,
        "reference_publication_count": 3,
        "duplicate_record_count": 1,
        "matched_count": 2,
        "missed_count": 1,
        "conflict_count": 0,
        "query_recall": pytest.approx(2 / 3),
    }
    assert [item["id"] for item in report["reference_sets"]] == ["set-a", "set-b"]
    assert report["reference_sets"][0]["summary"]["matched_count"] == 2
    assert report["reference_sets"][1]["summary"]["query_recall"] == 1.0

    by_query = {item["query"]: item for item in report["queries"]}
    assert by_query["query one"]["raw_hit_count"] == 1
    assert by_query["query one"]["summary"]["matched_count"] == 1
    assert by_query["query two"]["summary"]["matched_count"] == 1
    doi_match = next(
        row
        for row in report["aggregate"]["publications"]
        if row["normalized_identifiers"]["dois"] == ["10.1000/one"]
    )
    assert doi_match["status"] == "matched"
    assert doi_match["matched_by"] == ["doi"]
    assert doi_match["matched_publication"]["queries"] == [
        {"ordinal": 0, "query": "query one"}
    ]


def test_cross_query_duplicate_hits_merge_query_provenance(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [reference_row("set-a", "Shared publication", doi="10.1000/shared")],
    )
    publication = {
        "source": "MED",
        "id": "10",
        "doi": "10.1000/shared",
        "title": "Shared publication",
    }
    trace = write_trace(
        tmp_path / "trace",
        ["first", "second"],
        pages={
            "first": [[{**publication, "query": "first"}]],
            "second": [[{**publication, "query": "second"}]],
        },
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["aggregate"]["summary"]["matched_count"] == 1
    assert report["aggregate"]["publications"][0]["matched_publication"]["queries"] == [
        {"ordinal": 0, "query": "first"},
        {"ordinal": 1, "query": "second"},
    ]


def test_distinct_doi_and_pmid_hits_are_reported_as_conflict(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [
            {
                **reference_row("set-a", "Conflicting publication", doi="10.1000/x"),
                "pmid": "10",
            }
        ],
    )
    trace = write_trace(
        tmp_path / "trace",
        ["query"],
        pages={
            "query": [
                [
                    {"query": "query", "doi": "10.1000/x", "title": "DOI hit"},
                    {"query": "query", "pmid": "10", "title": "PMID hit"},
                ]
            ]
        },
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["aggregate"]["summary"]["conflict_count"] == 1
    assert report["aggregate"]["summary"]["query_recall"] == 0.0
    row = report["aggregate"]["publications"][0]
    assert row["status"] == "conflict"
    assert len(row["conflicting_publications"]) == 2


def test_partial_query_checkpoints_produce_lower_bound_report(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(
        references,
        [reference_row("set-a", "Available result", pmid="1")],
    )
    trace = write_trace(
        tmp_path / "partial",
        ["available", "pending", "failed", "terminal", "not-started"],
        pages={
            "available": [[{"query": "available", "pmid": "1"}]],
            "failed": [[{"query": "failed", "pmid": "999"}]],
        },
        statuses={
            "pending": "pending",
            "failed": "retryable_error",
            "terminal": "terminal_error",
            "not-started": None,
        },
    )

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["source"]["complete"] is False
    assert report["source"]["score_interpretation"] == "lower_bound"
    assert report["source"]["query_status_counts"] == {
        "available": 1,
        "pending": 1,
        "retryable_error": 1,
        "terminal_error": 1,
        "missing": 1,
    }
    assert report["source"]["limitations"]
    assert report["aggregate"]["summary"]["query_recall"] == 1.0
    assert [item["complete"] for item in report["queries"]] == [
        True,
        False,
        False,
        False,
        False,
    ]


def test_no_data_query_is_complete(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Missing", pmid="1")])
    trace = write_trace(tmp_path / "empty", ["query"])

    report = runner.run_benchmark(trace_dir=trace, references_tsv=references)

    assert report["source"]["complete"] is True
    assert report["source"]["query_status_counts"] == {"no_data": 1}
    assert report["aggregate"]["summary"]["query_recall"] == 0.0


def test_benchmark_reads_trace_database_without_modifying_it(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Found", pmid="1")])
    trace = write_trace(
        tmp_path / "trace",
        ["query"],
        pages={"query": [[{"query": "query", "pmid": "1"}]]},
    )
    database = trace / "atlas_run.sqlite3"
    before = (database.read_bytes(), database.stat().st_mtime_ns, sorted(trace.iterdir()))

    runner.run_benchmark(trace_dir=trace, references_tsv=references)

    after = (database.read_bytes(), database.stat().st_mtime_ns, sorted(trace.iterdir()))
    assert after == before


def test_cli_uses_shared_fixture_and_atomically_replaces_report(tmp_path: Path) -> None:
    trace = write_trace(tmp_path / "trace", ["query"])
    out = tmp_path / "reports"
    out.mkdir()
    report_path = out / REPORT_NAME
    report_path.write_text('{"stale": true}', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(trace), "--out", str(out)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(report_path)
    assert completed.stderr == ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["benchmark"]["references"]["artifact"] == str(REFERENCES)


@pytest.mark.parametrize(
    "setup,message",
    [
        (lambda trace: trace.mkdir(), "atlas_run.sqlite3"),
        (
            lambda trace: (
                trace.mkdir(),
                sqlite3.connect(trace / "atlas_run.sqlite3").close(),
            ),
            "checkpoint_meta",
        ),
    ],
)
def test_invalid_trace_fails_without_partial_report(
    tmp_path: Path,
    setup,
    message: str,
) -> None:
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Reference", pmid="1")])
    trace = tmp_path / "trace"
    setup(trace)
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(trace),
            "--references",
            str(references),
            "--out",
            str(out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert message in completed.stderr
    assert completed.stdout == ""
    assert not (out / REPORT_NAME).exists()


def test_malformed_search_page_payload_fails(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Reference", pmid="1")])
    trace = write_trace(tmp_path / "trace", ["query"])
    query_hash = hashlib.sha256(b"query").hexdigest()
    with sqlite3.connect(trace / "atlas_run.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO checkpoint_items(
                stage, item_key, ordinal, status, payload, error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "search_pages",
                f"{query_hash}:000001",
                1,
                "available",
                json.dumps({"query": "query", "publications": {"not": "a list"}}),
                None,
            ),
        )

    with pytest.raises(ValueError, match="publications"):
        runner.run_benchmark(trace_dir=trace, references_tsv=references)


def test_invalid_resolved_queries_metadata_fails(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Reference", pmid="1")])
    trace = write_trace(tmp_path / "trace", ["query"])
    with sqlite3.connect(trace / "atlas_run.sqlite3") as connection:
        connection.execute(
            "UPDATE checkpoint_meta SET value = ? WHERE key = ?",
            (json.dumps({"not": "a list"}), "resolved_queries"),
        )

    with pytest.raises(ValueError, match="non-empty list"):
        runner.run_benchmark(trace_dir=trace, references_tsv=references)


def test_completed_query_count_mismatch_fails(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Reference", pmid="1")])
    trace = write_trace(
        tmp_path / "trace",
        ["query"],
        pages={"query": [[{"query": "query", "pmid": "1"}]]},
    )
    query_hash = hashlib.sha256(b"query").hexdigest()
    with sqlite3.connect(trace / "atlas_run.sqlite3") as connection:
        payload = json.dumps(
            {
                "query": "query",
                "pages": 1,
                "next_cursor": None,
                "collected_hits": 2,
            }
        )
        connection.execute(
            "UPDATE checkpoint_items SET payload = ? WHERE stage = ? AND item_key = ?",
            (payload, "search_queries", query_hash),
        )

    with pytest.raises(ValueError, match="counts do not match"):
        runner.run_benchmark(trace_dir=trace, references_tsv=references)


def test_unknown_query_status_fails(tmp_path: Path) -> None:
    runner = load_runner()
    references = tmp_path / "references.tsv"
    write_tsv(references, [reference_row("set-a", "Reference", pmid="1")])
    trace = write_trace(
        tmp_path / "trace",
        ["query"],
        statuses={"query": "unexpected"},
    )

    with pytest.raises(ValueError, match="unsupported status"):
        runner.run_benchmark(trace_dir=trace, references_tsv=references)
