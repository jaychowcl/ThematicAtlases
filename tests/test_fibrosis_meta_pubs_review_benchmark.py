from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark_ThematicAtlases._fibrosis_references import (
    load_reference_tsv,
    reference_groups,
)


pytestmark = pytest.mark.allow_subprocess


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = (
    ROOT
    / "src"
    / "benchmark_ThematicAtlases"
    / "benchmark_fibrosis_meta_pubs_review"
)
RUNNER = BENCHMARK_DIR / "benchmark_fibrosis_meta_pubs_review.py"
DATASET = BENCHMARK_DIR / "fibrosis_meta_publications_review.csv"
THEME = BENCHMARK_DIR / "theme_fibrosis.txt"
RECALL_DATASET = (
    ROOT
    / "src"
    / "benchmark_ThematicAtlases"
    / "benchmark_fibrosis_meta_pubs_recall"
    / "fibrosis_meta_publications.tsv"
)
REPORT_NAME = "fibrosis_meta_pubs_review_report.json"
CACHE_NAME = "fibrosis_meta_pubs_review_cache.csv"

DATASET_COLUMNS = (
    "publication_id",
    "doi",
    "pmid",
    "expected_decision",
)


def load_runner():
    spec = importlib.util.spec_from_file_location("fibrosis_review_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_dataset(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def dataset_row(
    publication_id: str,
    expected: str,
    *,
    doi: str = "",
    pmid: str = "",
) -> dict[str, str]:
    return {
        "publication_id": publication_id,
        "doi": doi,
        "pmid": pmid,
        "expected_decision": expected,
    }


def read_dataset(path: Path = DATASET) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == DATASET_COLUMNS
        return list(reader)


def projected_recall_rows() -> list[dict[str, str]]:
    references = load_reference_tsv(RECALL_DATASET)
    rows = []
    for group in reference_groups(references["rows"]):
        doi = group["dois"][0] if group["dois"] else ""
        pmid = group["pmids"][0] if group["pmids"] else ""
        rows.append(
            dataset_row(
                f"doi:{doi}" if doi else f"pmid:{pmid}",
                "relevant",
                doi=doi,
                pmid=pmid,
            )
        )
    return rows


class RecordingHydrator:
    def __init__(self, failures: set[str] | None = None):
        self.calls: list[str] = []
        self.failures = failures or set()

    def hydrate(self, row: dict) -> dict:
        publication_id = row["publication_id"]
        self.calls.append(publication_id)
        if publication_id in self.failures:
            raise TimeoutError("provider detail must not enter the report")
        return {
            "resolved_doi": row["doi"],
            "resolved_pmid": row["pmid"],
            "title": f"Title {publication_id}",
            "publication_text": f"Text {publication_id}",
            "text_source": "fullTextXML",
            "full_text_status": "available",
            "review_context": {
                "title": f"Title {publication_id}",
                "metadata": [],
                "accessions": [],
                "metadata_statuses": {},
            },
            "hydration_status": "available",
            "retrieval_provenance": {"provider": "fixture"},
            "errors": [],
        }


class RecordingReviewRunner:
    def __init__(self, decisions: dict[str, str | None]):
        self.decisions = decisions
        self.calls: list[dict] = []

    def __call__(self, publication_texts: dict, contexts: dict, theme: str) -> dict:
        self.calls.append(
            {
                "publication_texts": publication_texts,
                "contexts": contexts,
                "theme": theme,
            }
        )
        reviewed = {}
        for publication_id, publication in publication_texts.items():
            decision = self.decisions[publication_id]
            review = (
                {
                    "review_status": "failed",
                    "error_type": "TimeoutError",
                    "error": {"error_type": "TimeoutError", "retryable": True},
                }
                if decision is None
                else {
                    "judgement": decision,
                    "reasoning": f"Reason {publication_id}",
                    "confidence": "high",
                    "reviewer_identity": {
                        "provider": "fixture",
                        "model": "fixture-model",
                    },
                }
            )
            reviewed[publication_id] = {
                **publication,
                "agentic_curator": review,
            }
        return reviewed


def test_packaged_review_dataset_is_all_recall_publications_labeled_relevant() -> None:
    assert RUNNER.is_file()
    assert DATASET.is_file()
    assert THEME.read_bytes() == (ROOT / "docs" / "theme_fibrosis.txt").read_bytes()
    assert not (ROOT / "src" / "benchmark_ThematicAtlases" / "thematic_reviewer").exists()
    assert not (ROOT / "src" / "benchmark_ThematicAtlases" / "ontology_harmonizer").exists()

    references = load_reference_tsv(RECALL_DATASET)
    rows = read_dataset()

    assert len(references["rows"]) == 92
    assert len(rows) == 90
    assert rows == projected_recall_rows()
    assert {row["expected_decision"] for row in rows} == {"relevant"}
    assert {
        (row["doi"], row["pmid"])
        for row in rows
        if row["doi"]
        in {"10.1038/s41467-024-55325-4", "10.1038/s41586-024-07465-2"}
    } == {
        ("10.1038/s41467-024-55325-4", "39747812"),
        ("10.1038/s41586-024-07465-2", "38778114"),
    }


def test_empty_custom_dataset_fails_clearly(tmp_path: Path) -> None:
    runner = load_runner()
    dataset = tmp_path / "empty.csv"
    write_dataset(dataset, [])

    with pytest.raises(ValueError, match="at least one labeled publication"):
        runner.run_benchmark(
            dataset_csv=dataset,
            cache_csv=tmp_path / "unused.csv",
            theme_file=THEME,
            hydrator=RecordingHydrator(),
            review_runner=RecordingReviewRunner({}),
        )


def test_packaged_all_relevant_dataset_runs_offline(tmp_path: Path) -> None:
    runner = load_runner()
    rows = read_dataset()
    decisions = {row["publication_id"]: "relevant" for row in rows}
    hydrator = RecordingHydrator()
    reviewer = RecordingReviewRunner(decisions)

    report = runner.run_benchmark(
        dataset_csv=DATASET,
        cache_csv=tmp_path / CACHE_NAME,
        theme_file=THEME,
        hydrator=hydrator,
        review_runner=reviewer,
    )

    assert report["summary"]["input_count"] == 90
    assert report["summary"]["hydrated_count"] == 90
    assert report["summary"]["review_completed_count"] == 90
    assert report["summary"]["scored_count"] == 90
    assert report["summary"]["correct_count"] == 90
    assert report["summary"]["accuracy"] == 1.0
    assert report["summary"]["per_class"]["relevant"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "support": 90,
    }
    assert report["summary"]["macro_f1"] == pytest.approx(1 / 3)
    assert hydrator.calls == [row["publication_id"] for row in rows]


@pytest.mark.parametrize(
    "rows,message",
    [
        (
            [dataset_row("pub-1", "relevant")],
            "requires a DOI or PMID",
        ),
        (
            [dataset_row("pub-1", "maybe", pmid="1")],
            "expected_decision",
        ),
        (
            [
                dataset_row("pub-1", "relevant", pmid="1"),
                dataset_row("pub-1", "unsure", pmid="2"),
            ],
            "duplicate publication_id",
        ),
        (
            [
                dataset_row("pub-1", "relevant", pmid="1"),
                dataset_row("pub-2", "unsure", pmid="PMID: 1"),
            ],
            "duplicate publication identity",
        ),
    ],
)
def test_dataset_validation(tmp_path: Path, rows: list[dict], message: str) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(dataset, rows)

    with pytest.raises(ValueError, match=message):
        runner.run_benchmark(
            dataset_csv=dataset,
            cache_csv=tmp_path / "cache.csv",
            theme_file=THEME,
            hydrator=RecordingHydrator(),
            review_runner=RecordingReviewRunner({}),
        )


def test_report_scores_three_classes_and_writes_hydration_cache(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(
        dataset,
        [
            dataset_row("relevant", "Relevant", doi="10.1000/relevant"),
            dataset_row("not", "not relevant", pmid="2"),
            dataset_row("unsure", "unsure", pmid="3"),
        ],
    )
    cache = tmp_path / CACHE_NAME
    hydrator = RecordingHydrator()
    reviews = RecordingReviewRunner(
        {
            "relevant": "relevant",
            "not": "unsure",
            "unsure": "UNSURE",
        }
    )

    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=hydrator,
        review_runner=reviews,
    )

    assert report["schema_version"] == "1.0"
    assert report["benchmark"]["method"] == "fibrosis_meta_publication_review"
    assert report["summary"]["input_count"] == 3
    assert report["summary"]["hydrated_count"] == 3
    assert report["summary"]["review_completed_count"] == 3
    assert report["summary"]["scored_count"] == 3
    assert report["summary"]["correct_count"] == 2
    assert report["summary"]["accuracy"] == pytest.approx(2 / 3)
    assert report["summary"]["confusion_matrix"]["not_relevant"] == {
        "relevant": 0,
        "not_relevant": 0,
        "unsure": 1,
    }
    assert report["summary"]["per_class"]["relevant"]["f1"] == 1.0
    assert report["summary"]["macro_f1"] == pytest.approx(5 / 9)
    assert [row["correct"] for row in report["publications"]] == [True, False, True]
    assert "publication_text" not in json.dumps(report)
    assert hydrator.calls == ["relevant", "not", "unsure"]
    assert reviews.calls[0]["contexts"]["relevant"]["title"] == "Title relevant"

    with cache.open(encoding="utf-8", newline="") as handle:
        cache_rows = list(csv.DictReader(handle))
    assert [row["publication_id"] for row in cache_rows] == [
        "relevant",
        "not",
        "unsure",
    ]
    assert cache_rows[0]["publication_text"] == "Text relevant"


def test_cache_reuses_unchanged_hydration_and_refreshes_changed_rows(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    cache = tmp_path / CACHE_NAME
    reviews = RecordingReviewRunner({"pub-1": "relevant"})
    write_dataset(
        dataset,
        [dataset_row("pub-1", "relevant", doi="10.1000/one")],
    )

    first = RecordingHydrator()
    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=first,
        review_runner=reviews,
    )
    assert first.calls == ["pub-1"]

    write_dataset(
        dataset,
        [dataset_row("pub-1", "unsure", doi="10.1000/one")],
    )
    reused = RecordingHydrator()
    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=reused,
        review_runner=reviews,
    )
    assert reused.calls == []
    assert report["benchmark"]["cache"]["reused_count"] == 1

    write_dataset(
        dataset,
        [dataset_row("pub-1", "relevant", doi="10.1000/two")],
    )
    changed = RecordingHydrator()
    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=changed,
        review_runner=reviews,
    )
    assert changed.calls == ["pub-1"]

    refreshed = RecordingHydrator()
    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=refreshed,
        review_runner=reviews,
        refresh_cache=True,
    )
    assert refreshed.calls == ["pub-1"]


def test_cache_must_not_overwrite_the_dataset(tmp_path: Path) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(
        dataset,
        [dataset_row("pub-1", "relevant", pmid="1")],
    )
    original = dataset.read_bytes()

    with pytest.raises(ValueError, match="cache path must differ"):
        runner.run_benchmark(
            dataset_csv=dataset,
            cache_csv=dataset,
            theme_file=THEME,
            hydrator=RecordingHydrator(),
            review_runner=RecordingReviewRunner({"pub-1": "relevant"}),
        )

    assert dataset.read_bytes() == original


def test_row_failures_are_reported_and_excluded_from_metrics(tmp_path: Path) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(
        dataset,
        [
            dataset_row("hydrate-fail", "relevant", pmid="1"),
            dataset_row("review-fail", "not_relevant", pmid="2"),
            dataset_row("scored", "unsure", pmid="3"),
        ],
    )
    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=tmp_path / CACHE_NAME,
        theme_file=THEME,
        hydrator=RecordingHydrator({"hydrate-fail"}),
        review_runner=RecordingReviewRunner(
            {"review-fail": None, "scored": "unsure"}
        ),
    )

    assert report["summary"]["retrieval_failed_count"] == 1
    assert report["summary"]["review_failed_count"] == 1
    assert report["summary"]["scored_count"] == 1
    assert report["summary"]["accuracy"] == 1.0
    assert [row["status"] for row in report["publications"]] == [
        "retrieval_failed",
        "review_failed",
        "scored",
    ]
    serialized = json.dumps(report)
    assert "provider detail" not in serialized


def test_production_hydrator_uses_exact_query_and_ta_context() -> None:
    runner = load_runner()

    class FakeEPMC:
        def __init__(self):
            self.queries = []

        def collect_publications(self, queries, max_publications):
            self.queries.append((queries, max_publications))
            return [
                {
                    "source": "MED",
                    "epmc_id": "123",
                    "pmid": "123",
                    "doi": "10.1000/test",
                    "title": "Fetched title",
                    "abstractText": "Abstract",
                }
            ]

        def collect_publication_texts(self, publications):
            return [
                {
                    **publications[0],
                    "text": "Full text",
                    "text_source": "fullTextXML",
                    "full_text_status": "available",
                }
            ]

        def collect_datalinks(self, publications):
            return [{"datalink_id": "GSE1", "publications": publications}]

        def accessions_from_datalinks(self, datalinks):
            return datalinks

        def accessions_from_fulltexts(self, publications):
            return []

        def merge_accessions(self, datalink_accessions, scraped_accessions):
            return datalink_accessions + scraped_accessions

    class FakeCollector:
        def filter_accessions(self, accessions):
            return accessions

        def collect_accession_metadata(self, jsons):
            return [{**jsons[0], "metadata_status": "available"}]

    class FakeFilterer:
        def publication_text_ref(self, publication):
            return publication["pmid"]

        def accessions_with_publication_text_refs(self, jsons, publication_texts):
            return jsons

    class FakeReviewService:
        def publication_review_contexts(self, accessions):
            return {
                "123": {
                    "title": "Fetched title",
                    "metadata": [{"accession": "GSE1", "context": "metadata"}],
                    "accessions": ["GSE1"],
                    "metadata_statuses": {"GSE1": "available"},
                }
            }

    epmc = FakeEPMC()
    hydrator = runner.ProductionHydrator(
        epmc_wrapper=epmc,
        collector=FakeCollector(),
        filterer=FakeFilterer(),
        review_service=FakeReviewService(),
    )

    result = hydrator.hydrate(
        {
            "publication_id": "pub-1",
            "doi": "10.1000/test",
            "pmid": "123",
            "expected_decision": "relevant",
        }
    )

    assert epmc.queries == [(["EXT_ID:123 AND SRC:MED"], 2)]
    assert result["publication_text"] == "Full text"
    assert result["review_context"]["accessions"] == ["GSE1"]
    assert result["hydration_status"] == "available"


def test_cli_rejects_empty_custom_dataset_without_cache_or_report(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "empty.csv"
    write_dataset(dataset, [])
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(dataset),
            "--out",
            str(tmp_path / "out"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "at least one labeled publication" in completed.stderr
    assert completed.stdout == ""
    assert not (tmp_path / "out" / REPORT_NAME).exists()
    assert not (tmp_path / "out" / CACHE_NAME).exists()
