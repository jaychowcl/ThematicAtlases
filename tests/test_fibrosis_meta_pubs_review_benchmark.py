from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import logging
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
RAW_CACHE_NAME = "fibrosis_meta_pubs_review_raw_cache.sqlite3"
AUDIT_NAME = "fibrosis_meta_pubs_review_cache_audit.json"

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
        accession = f"GSE-{publication_id}"
        return {
            "resolved_doi": row["doi"],
            "resolved_pmid": row["pmid"],
            "title": f"Title {publication_id}",
            "publication_text": f"Text {publication_id}",
            "text_source": "fullTextXML",
            "full_text_status": "available",
            "review_context": {
                "title": f"Title {publication_id}",
                "metadata": [
                    {
                        "accession": accession,
                        "status": "available",
                        "context": {"series": {"title": f"Series {publication_id}"}},
                    }
                ],
                "accessions": [accession],
                "metadata_statuses": {accession: "available"},
            },
            "hydration_status": "available",
            "retrieval_provenance": {"provider": "fixture"},
            "errors": [],
        }


class SequencedHydrator:
    def __init__(self, responses: dict[str, list[dict | Exception]]):
        self.responses = responses
        self.calls: list[str] = []

    def hydrate(self, row: dict) -> dict:
        publication_id = row["publication_id"]
        self.calls.append(publication_id)
        response = self.responses[publication_id].pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def complete_hydration(publication_id: str, *, pmid: str = "1") -> dict:
    row = dataset_row(publication_id, "relevant", pmid=pmid)
    return RecordingHydrator().hydrate(row)


def incomplete_hydration(publication_id: str, *, pmid: str = "1") -> dict:
    hydration = complete_hydration(publication_id, pmid=pmid)
    accession = hydration["review_context"]["accessions"][0]
    hydration["review_context"] = {
        "title": hydration["title"],
        "metadata": [
            {
                "accession": accession,
                "status": "degraded",
                "context": {},
            }
        ],
        "accessions": [accession],
        "metadata_statuses": {accession: "degraded"},
    }
    hydration["hydration_status"] = "degraded"
    return hydration


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
    assert report["benchmark"]["runtime"] == {
        "hydration_policy_version": runner.HYDRATION_POLICY_VERSION,
        "accession_discovery_policy_version": (
            runner.PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
        ),
        "miniml_strict_compatibility_policy_version": (
            "miniml-3.0-source-compat-v1"
        ),
        "full_metadata_enrichment": True,
    }
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


def test_cache_refreshes_rows_from_reduced_metadata_hydration_policy(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    cache = tmp_path / CACHE_NAME
    reviews = RecordingReviewRunner({"pub-1": "relevant"})
    row = dataset_row("pub-1", "relevant", doi="10.1000/one")
    write_dataset(dataset, [row])

    initial = RecordingHydrator()
    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=initial,
        review_runner=reviews,
    )

    with cache.open(encoding="utf-8", newline="") as handle:
        cache_rows = list(csv.DictReader(handle))
    legacy_identity = hashlib.sha256(
        runner._canonical_json({"doi": row["doi"], "pmid": row["pmid"]}).encode()
    ).hexdigest()
    cache_rows[0]["identity_sha256"] = legacy_identity
    with cache.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=runner.CACHE_COLUMNS)
        writer.writeheader()
        writer.writerows(cache_rows)

    refreshed = RecordingHydrator()
    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=refreshed,
        review_runner=reviews,
    )

    assert refreshed.calls == ["pub-1"]
    assert report["benchmark"]["cache"] == {
        "artifact": str(cache),
        "schema_version": runner.CACHE_SCHEMA_VERSION,
        "reused_count": 0,
        "refreshed_count": 1,
    }


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


def test_existing_cache_accepts_large_publication_text_fields(tmp_path: Path) -> None:
    runner = load_runner()
    cache = tmp_path / CACHE_NAME
    hydration = complete_hydration("large")
    hydration["publication_text"] = "A" * 200_000
    row = dataset_row("large", "relevant", pmid="1")
    runner._write_csv_atomic(
        cache,
        runner.CACHE_COLUMNS,
        [runner._cache_row(row, runner._identity_hash(row), hydration)],
    )

    loaded = runner._load_cache(cache)

    assert loaded["large"]["publication_text"] == "A" * 200_000


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


def test_retries_incomplete_hydration_once_and_only_reviews_complete_context(
    tmp_path: Path, caplog
) -> None:
    runner = load_runner()
    caplog.set_level(logging.INFO, logger=runner.__name__)
    dataset = tmp_path / "dataset.csv"
    write_dataset(
        dataset,
        [
            dataset_row("retry-complete", "relevant", pmid="1"),
            dataset_row("still-incomplete", "relevant", pmid="2"),
            dataset_row("exception-complete", "relevant", pmid="3"),
        ],
    )
    hydrator = SequencedHydrator(
        {
            "retry-complete": [
                incomplete_hydration("retry-complete", pmid="1"),
                complete_hydration("retry-complete", pmid="1"),
            ],
            "still-incomplete": [
                incomplete_hydration("still-incomplete", pmid="2"),
                incomplete_hydration("still-incomplete", pmid="2"),
            ],
            "exception-complete": [
                TimeoutError("private provider detail"),
                complete_hydration("exception-complete", pmid="3"),
            ],
        }
    )
    reviewer = RecordingReviewRunner(
        {
            "retry-complete": "relevant",
            "exception-complete": "relevant",
        }
    )

    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=tmp_path / CACHE_NAME,
        theme_file=THEME,
        hydrator=hydrator,
        review_runner=reviewer,
    )

    assert hydrator.calls == [
        "retry-complete",
        "retry-complete",
        "still-incomplete",
        "still-incomplete",
        "exception-complete",
        "exception-complete",
    ]
    assert set(reviewer.calls[0]["publication_texts"]) == {
        "retry-complete",
        "exception-complete",
    }
    assert set(reviewer.calls[0]["contexts"]) == {
        "retry-complete",
        "exception-complete",
    }
    assert [row["status"] for row in report["publications"]] == [
        "scored",
        "metadata_incomplete",
        "scored",
    ]
    assert report["summary"]["review_eligible_count"] == 2
    assert report["summary"]["metadata_incomplete_count"] == 1
    assert report["summary"]["review_completed_count"] == 2
    assert (
        "publication_id=still-incomplete review_eligibility=skipped "
        "reason=metadata_incomplete"
    ) in caplog.text
    assert "private provider detail" not in json.dumps(report)


def test_incomplete_cached_hydration_is_retried_instead_of_reused(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    cache = tmp_path / CACHE_NAME
    write_dataset(dataset, [dataset_row("pub-1", "relevant", pmid="1")])
    reviewer = RecordingReviewRunner({})

    first = SequencedHydrator(
        {
            "pub-1": [
                incomplete_hydration("pub-1"),
                incomplete_hydration("pub-1"),
            ]
        }
    )
    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=first,
        review_runner=reviewer,
    )

    second = SequencedHydrator(
        {
            "pub-1": [
                incomplete_hydration("pub-1"),
                incomplete_hydration("pub-1"),
            ]
        }
    )
    report = runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=cache,
        theme_file=THEME,
        hydrator=second,
        review_runner=reviewer,
    )

    assert second.calls == ["pub-1", "pub-1"]
    assert reviewer.calls == []
    assert report["benchmark"]["cache"]["reused_count"] == 0
    assert report["summary"]["metadata_incomplete_count"] == 1


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
            return []

        def accessions_from_datalinks(self, datalinks):
            return datalinks

        def accessions_from_fulltexts(self, publications):
            return []

        def accessions_from_link_graph(
            self, publications, checkpoint_store=None, cached_only=False
        ):
            return [{
                "datalink_id": "GSE1",
                "publications": publications,
                "discovery_sources": ["ncbi_pubmed_gds"],
            }]

        def merge_accessions(
            self, datalink_accessions, scraped_accessions, graph_accessions
        ):
            return datalink_accessions + scraped_accessions + graph_accessions

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
                    "metadata": [
                        {
                            "accession": "GSE1",
                            "status": "available",
                            "context": "metadata",
                        }
                    ],
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


def test_production_hydrator_passes_raw_checkpoint_store_to_every_download(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    observed = []

    class FakeEPMC:
        def collect_publications(self, queries, max_publications, checkpoint_store=None):
            observed.append(("search", checkpoint_store))
            return [{
                "source": "MED", "epmc_id": "123", "pmid": "123",
                "doi": "10.1000/test", "title": "Fetched title",
                "abstractText": "Abstract",
            }]

        def collect_publication_texts(self, publications, checkpoint_store=None):
            observed.append(("text", checkpoint_store))
            return [{
                **publications[0], "text": "Full text", "text_source": "fullTextXML",
                "full_text_status": "available",
            }]

        def collect_datalinks(self, publications, checkpoint_store=None):
            observed.append(("datalinks", checkpoint_store))
            return [{"datalink_id": "GSE1", "publications": publications}]

        def accessions_from_datalinks(self, datalinks):
            return datalinks

        def accessions_from_fulltexts(self, publications, checkpoint_store=None):
            observed.append(("fulltext_accessions", checkpoint_store))
            return []

        def accessions_from_link_graph(
            self, publications, checkpoint_store=None, cached_only=False
        ):
            observed.append(("link_graph", checkpoint_store))
            assert cached_only is False
            return []

        def merge_accessions(
            self, datalink_accessions, scraped_accessions, graph_accessions
        ):
            return datalink_accessions + scraped_accessions + graph_accessions

    class FakeCollector:
        def filter_accessions(self, accessions):
            return accessions

        def collect_accession_metadata(self, jsons, checkpoint_store=None):
            observed.append(("metadata", checkpoint_store))
            return [{**jsons[0], "metadata_status": "available"}]

    class FakeFilterer:
        def publication_text_ref(self, publication):
            return publication["pmid"]

        def accessions_with_publication_text_refs(self, jsons, publication_texts):
            return jsons

    class FakeReviewService:
        def publication_review_contexts(self, accessions):
            return {"123": {
                "title": "Fetched title",
                "metadata": [{"accession": "GSE1", "status": "available", "context": "metadata"}],
                "accessions": ["GSE1"],
                "metadata_statuses": {"GSE1": "available"},
            }}

    hydration = runner.ProductionHydrator(
        checkpoint_store=store,
        epmc_wrapper=FakeEPMC(),
        collector=FakeCollector(),
        filterer=FakeFilterer(),
        review_service=FakeReviewService(),
    ).hydrate(dataset_row("pub-1", "relevant", doi="10.1000/test", pmid="123"))

    assert hydration["hydration_status"] == "available"
    assert [stage for stage, _store in observed] == [
        "search", "text", "datalinks", "fulltext_accessions", "link_graph",
        "metadata",
    ]
    assert all(observed_store is store for _stage, observed_store in observed)


def test_hydrate_only_publishes_terminal_raw_csv_and_private_audit_without_review(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(dataset, [
        dataset_row("complete", "relevant", pmid="1"),
        dataset_row("terminal-gap", "relevant", pmid="2"),
    ])
    cache = tmp_path / CACHE_NAME
    raw_cache = tmp_path / RAW_CACHE_NAME
    audit = tmp_path / AUDIT_NAME
    hydrator = SequencedHydrator({
        "complete": [complete_hydration("complete" )],
        "terminal-gap": [
            incomplete_hydration("terminal-gap", pmid="2"),
            incomplete_hydration("terminal-gap", pmid="2"),
        ],
    })

    result = runner.hydrate_cache(
        dataset_csv=dataset,
        cache_csv=cache,
        raw_cache=raw_cache,
        audit_json=audit,
        hydrator=hydrator,
    )

    assert result["audit_path"] == audit
    assert raw_cache.is_file() and cache.is_file() and audit.is_file()
    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_payload["summary"]["input_count"] == 2
    assert audit_payload["summary"]["pending_stage_count"] == 0
    assert audit_payload["summary"]["terminal_publication_count"] == 2
    serialized_audit = json.dumps(audit_payload)
    assert "Text complete" not in serialized_audit
    assert "Series complete" not in serialized_audit
    assert "publication_text" not in serialized_audit

    with cache.open(encoding="utf-8", newline="") as handle:
        cache_rows = list(csv.DictReader(handle))
    assert len(cache_rows) == 2
    assert cache_rows[0]["publication_text"] == "Text complete"
    assert json.loads(cache_rows[0]["review_context_json"])["accessions"]


def test_audit_lifts_sanitized_provider_failure_fields_from_error_contract() -> None:
    runner = load_runner()
    item = {
        "error": json.dumps({
            "error_type": "MINiMLCompatibilityError",
            "failure_category": "metadata_compatibility",
            "correlation_id": "safe-correlation-id",
        }),
        "error_type": None,
        "failure_category": None,
    }

    assert runner._sanitized_failure_fields(item) == {
        "error_type": "MINiMLCompatibilityError",
        "failure_category": "metadata_compatibility",
        "correlation_id": "safe-correlation-id",
    }


def test_terminal_incomplete_raw_hydration_is_reused_without_download(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(dataset, [dataset_row("pub-1", "relevant", pmid="1")])
    cache = tmp_path / CACHE_NAME
    raw_cache = tmp_path / RAW_CACHE_NAME
    audit = tmp_path / AUDIT_NAME
    first = SequencedHydrator({
        "pub-1": [incomplete_hydration("pub-1"), incomplete_hydration("pub-1")]
    })
    runner.hydrate_cache(
        dataset_csv=dataset, cache_csv=cache, raw_cache=raw_cache,
        audit_json=audit, hydrator=first,
    )

    reused = SequencedHydrator({"pub-1": []})
    result = runner.hydrate_cache(
        dataset_csv=dataset, cache_csv=cache, raw_cache=raw_cache,
        audit_json=audit, hydrator=reused,
    )

    assert reused.calls == []
    assert result["reused_count"] == 1
    assert result["refreshed_count"] == 0


def test_targeted_metadata_retry_isolated_from_unrelated_stages(tmp_path: Path) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    store.put("geo_metadata", "GSE1", 1, "terminal_error", payload={"packages": []})
    store.put(
        "arrayexpress_metadata", "E-MTAB-1", 1, "terminal_error",
        payload={"packages": []},
    )
    store.put("publication_text", "MED:1", 1, "terminal_error")
    store.put("sra_xml", "SRX1", 1, "terminal_error")

    class Handler:
        def __init__(self, stage):
            self.stage = stage
            self.calls = []

        def collect_accession_metadata(self, records, checkpoint_store):
            accession = records[0]["datalink_id"]
            self.calls.append(accession)
            checkpoint_store.put(
                self.stage, accession, 1, "available", payload={"packages": [{}]}
            )

    handlers = {
        "geo": Handler("geo_metadata"),
        "arrayexpress": Handler("arrayexpress_metadata"),
    }

    class Collector:
        def metadata_handler(self, repository):
            return handlers[repository]

    hydrator = runner.ProductionHydrator(
        epmc_wrapper=object(), collector=Collector(), filterer=object(),
        review_service=object(), checkpoint_store=store,
    )
    outcomes = hydrator.retry_terminal_metadata()

    assert handlers["geo"].calls == ["GSE1"]
    assert handlers["arrayexpress"].calls == ["E-MTAB-1"]
    assert {item["status"] for item in outcomes} == {"available"}
    assert store.get("publication_text", "MED:1")["status"] == "terminal_error"
    assert store.get("sra_xml", "SRX1")["status"] == "terminal_error"


def test_targeted_metadata_retry_makes_exactly_two_construction_attempts(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    store.put("geo_metadata", "GSE1", 1, "terminal_error", payload={"packages": []})

    class FailingHandler:
        calls = 0

        def collect_accession_metadata(self, records, checkpoint_store):
            self.calls += 1
            checkpoint_store.put(
                "geo_metadata",
                records[0]["datalink_id"],
                1,
                "retryable_error",
                payload={"packages": []},
                error_type="MINiMLCompatibilityError",
                failure_category="metadata_compatibility",
            )

    handler = FailingHandler()

    class Collector:
        def metadata_handler(self, repository):
            return handler

    hydrator = runner.ProductionHydrator(
        epmc_wrapper=object(), collector=Collector(), filterer=object(),
        review_service=object(), checkpoint_store=store,
    )

    outcomes = hydrator.retry_terminal_metadata(attempts=2)

    assert handler.calls == 2
    assert outcomes == [{
        "stage": "geo_metadata",
        "accession": "GSE1",
        "attempts": 2,
        "status": "terminal_error",
    }]
    assert store.get("geo_metadata", "GSE1")["status"] == "terminal_error"


def test_targeted_retry_reprojects_all_rows_from_cached_stages_only(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    dataset = tmp_path / "dataset.csv"
    write_dataset(dataset, [dataset_row("pub-1", "relevant", pmid="1")])
    raw_cache = tmp_path / RAW_CACHE_NAME
    store = CheckpointStore(raw_cache)
    fingerprint = {
        "benchmark": "fibrosis_meta_publication_review_hydration",
        "dataset_sha256": runner._file_sha256(dataset),
        "record_count": 1,
        "hydration_policy_version": runner.PREVIOUS_HYDRATION_POLICY_VERSION,
        "miniml_strict_compatibility_policy_version": (
            runner.MINIML_STRICT_COMPATIBILITY_POLICY_VERSION
        ),
        "production_sources": [
            "Europe PMC", "PMC", "preprint", "NCBI GEO", "ArrayExpress",
            "BioStudies", "PubMed", "SRA", "ENA",
        ],
    }
    store.validate_fingerprint(fingerprint)
    old = complete_hydration("pub-1")
    old["hydration_status"] = "degraded"
    store.put(
        runner.RAW_HYDRATION_STAGE,
        "pub-1",
        1,
        "available",
        payload={
            "identity_sha256": "old-policy-identity",
            "hydration": old,
            "terminal_outcome": "incomplete",
        },
    )

    class CachedOnlyHydrator:
        cached_calls = []

        def retry_terminal_metadata(self, attempts):
            assert attempts == 2
            return []

        def hydrate(self, _row):
            pytest.fail("targeted retry entered normal public hydration")

        def hydrate_cached(self, row):
            self.cached_calls.append(row["publication_id"])
            return incomplete_hydration(row["publication_id"])

    hydrator = CachedOnlyHydrator()
    result = runner.hydrate_cache(
        dataset_csv=dataset,
        cache_csv=tmp_path / CACHE_NAME,
        raw_cache=raw_cache,
        audit_json=tmp_path / AUDIT_NAME,
        retry_terminal_metadata=True,
        hydrator=hydrator,
    )

    assert hydrator.cached_calls == ["pub-1"]
    assert result["reused_count"] == 1
    assert result["refreshed_count"] == 0
    published = CheckpointStore(raw_cache).get(runner.RAW_HYDRATION_STAGE, "pub-1")
    assert published["payload"]["identity_sha256"] == runner._identity_hash(
        dataset_row("pub-1", "relevant", pmid="1")
    )


def test_metadata_evidence_audit_excludes_raw_and_package_contents(tmp_path: Path) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    store.put(
        "geo_miniml_source", "GSE1", 1, "available",
        payload={"data": "RAW-PRIVATE-XML", "sha256": "abc", "byte_count": 15},
    )
    store.put(
        "geo_precanonical_metadata", "GSE1", 1, "available",
        payload={"packages": [{"private": "PRECANONICAL-PRIVATE"}]},
    )
    store.put(
        "geo_metadata", "GSE1", 1, "terminal_error", payload={"packages": []},
        error_type="MINiMLCompatibilityError",
        failure_category="metadata_compatibility",
    )
    store.put(
        "metadata_validation_diagnostics", "geo:GSE1", 1, "terminal_error",
        payload={
            "provider": "geo",
            "accession": "GSE1",
            "failure_stage": "canonicalization",
            "attempt_count": 2,
            "correlation_id": "safe-correlation",
            "diagnostics": [{
                "package_index": 0,
                "code": "unresolved_reference",
                "path": "/sample/0/platform_ref/ref",
                "severity": "warning",
                "message": "PRIVATE-DIAGNOSTIC-MESSAGE",
            }],
        },
    )
    store.set_meta("terminal_metadata_retry", {
        "attempts_per_accession": 2,
        "outcomes": [{
            "stage": "geo_metadata", "accession": "GSE1",
            "attempts": 2, "status": "terminal_error",
            "private": "PRIVATE-RETRY-DETAIL",
        }],
    })

    audit = runner._metadata_evidence_audit(store)
    serialized = json.dumps(audit)

    assert audit["summary"]["download_status_counts"] == {"available": 1}
    assert audit["summary"]["parse_status_counts"] == {"available": 1}
    assert audit["summary"]["canonicalization_status_counts"] == {
        "terminal_error": 1
    }
    assert audit["accessions"][0]["attempt_count"] == 2
    assert "RAW-PRIVATE-XML" not in serialized
    assert "PRECANONICAL-PRIVATE" not in serialized
    assert "PRIVATE-DIAGNOSTIC-MESSAGE" not in serialized
    assert "PRIVATE-RETRY-DETAIL" not in serialized


def test_metadata_evidence_audit_counts_accepted_warnings_without_contents(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    store.put("geo_miniml_source", "GSE1", 1, "available", payload={})
    store.put("geo_precanonical_metadata", "GSE1", 1, "available", payload={})
    store.put("geo_metadata", "GSE1", 1, "available", payload={"packages": []})
    store.put(
        "metadata_validation_diagnostics", "geo:GSE1", 1, "available",
        payload={
            "provider": "geo",
            "accession": "GSE1",
            "failure_stage": None,
            "attempt_count": 2,
            "correlation_id": None,
            "accepted_warning_count": 1,
            "compatibility_policy_version": "miniml-3.0-source-compat-v1",
            "diagnostics": [{
                "package_index": 0,
                "code": "xsd_uniqueness",
                "path": "/sample/1/title",
                "severity": "warning",
                "message": "PRIVATE-SAMPLE-TITLE",
            }],
        },
    )

    audit = runner._metadata_evidence_audit(store)
    serialized = json.dumps(audit)

    assert audit["summary"]["accepted_warning_count"] == 1
    assert audit["summary"]["accepted_warning_accession_count"] == 1
    assert audit["summary"]["accepted_diagnostic_code_counts"] == {
        "xsd_uniqueness": 1
    }
    assert audit["summary"]["compatibility_policy_versions"] == [
        "miniml-3.0-source-compat-v1"
    ]
    assert audit["accessions"][0]["accepted_warning_count"] == 1
    assert "PRIVATE-SAMPLE-TITLE" not in serialized


def test_link_graph_policy_amends_previous_fingerprint_without_losing_items(tmp_path: Path) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    current = {
        "benchmark": "benchmark",
        "hydration_policy_version": runner.HYDRATION_POLICY_VERSION,
        "accession_discovery_policy_version": (
            runner.PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
        ),
        "miniml_strict_compatibility_policy_version": (
            runner.MINIML_STRICT_COMPATIBILITY_POLICY_VERSION
        ),
    }
    previous = {
        "benchmark": "benchmark",
        "hydration_policy_version": runner.PREVIOUS_HYDRATION_POLICY_VERSION,
        "miniml_strict_compatibility_policy_version": (
            runner.MINIML_STRICT_COMPATIBILITY_POLICY_VERSION
        ),
    }
    store.validate_fingerprint(previous)
    store.put("search_queries", "query", 1, "available", payload={"rows": []})

    runner._validate_or_amend_hydration_fingerprint(store, current)

    assert store.get("search_queries", "query")["status"] == "available"
    amendments = store.get_meta("run_configuration_amendments")
    assert amendments[0]["amendment_id"] == "reviewer-pubmed-gds-link-graph-v1"


def test_link_graph_audit_counts_graph_only_merges_and_failures_without_titles(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    store.put(
        "pubmed_gds_links", "1", 1, "available",
        payload={"contract_version": "1.0", "target_uids": ["101", "102"]},
    )
    store.put(
        "pubmed_gds_links", "2", 2, "no_data",
        payload={"contract_version": "1.0", "target_uids": []},
    )
    store.put(
        "pubmed_gds_links", "3", 3, "retryable_error",
        error_type="Timeout", failure_category="transient",
    )
    store.put(
        "gds_summaries", "101", 1, "available",
        payload={
            "contract_version": "1.0", "uid": "101", "accession": "GSE1",
            "entrytype": "GSE", "accepted": True,
        },
    )
    store.put(
        "gds_summaries", "102", 2, "no_data",
        payload={
            "contract_version": "1.0", "uid": "102", "accession": "GDS2",
            "entrytype": "GDS", "accepted": False,
            "rejection_reason": "non_gse_entrytype",
        },
    )
    store.put(
        "datalinks", "MED:1", 1, "available",
        payload={"rows": [{"datalink_id": "GSE1", "pmid": "1"}]},
    )

    audit = runner._link_graph_audit(store)

    assert audit["summary"] == {
        "publication_checkpoint_count": 3,
        "publication_no_data_count": 1,
        "linked_uid_count": 2,
        "accepted_gse_count": 1,
        "rejected_summary_count": 1,
        "link_failure_count": 1,
        "summary_failure_count": 0,
        "graph_only_publication_accession_count": 0,
        "duplicate_source_publication_accession_count": 1,
    }
    assert audit["accepted_accessions"] == ["GSE1"]
    assert audit["rejection_reason_counts"] == {"non_gse_entrytype": 1}
    assert "title" not in json.dumps(audit).lower()


def test_targeted_retry_uses_staging_copy(tmp_path: Path) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    raw_cache = tmp_path / RAW_CACHE_NAME
    store = CheckpointStore(raw_cache)
    store.put("geo_metadata", "GSE1", 1, "terminal_error")

    working, publish = runner._raw_cache_working_path(
        raw_cache, refresh_cache=False, force_staging=True
    )

    assert publish is True
    assert working.name == f".{RAW_CACHE_NAME}.building"
    assert working.is_file()
    assert CheckpointStore(raw_cache).get("geo_metadata", "GSE1")["status"] == "terminal_error"


def test_retry_terminal_metadata_requires_hydrate_only(capsys) -> None:
    runner = load_runner()

    assert runner.main(["--retry-terminal-metadata"]) == 1
    assert "requires --hydrate-only" in capsys.readouterr().err


def test_raw_cache_resumes_after_interruption_without_repeating_completed_row(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(dataset, [
        dataset_row("first", "relevant", pmid="1"),
        dataset_row("second", "relevant", pmid="2"),
    ])
    cache = tmp_path / CACHE_NAME
    raw_cache = tmp_path / RAW_CACHE_NAME
    audit = tmp_path / AUDIT_NAME

    interrupted = SequencedHydrator({
        "first": [complete_hydration("first")],
        "second": [KeyboardInterrupt()],
    })
    with pytest.raises(KeyboardInterrupt):
        runner.hydrate_cache(
            dataset_csv=dataset, cache_csv=cache, raw_cache=raw_cache,
            audit_json=audit, hydrator=interrupted,
        )
    assert not raw_cache.exists()

    resumed = SequencedHydrator({"second": [complete_hydration("second", pmid="2")]})
    result = runner.hydrate_cache(
        dataset_csv=dataset, cache_csv=cache, raw_cache=raw_cache,
        audit_json=audit, hydrator=resumed,
    )
    assert resumed.calls == ["second"]
    assert result["reused_count"] == 1
    assert raw_cache.is_file()


def test_exhausted_geo_enrichment_retains_base_package_as_partial(tmp_path: Path) -> None:
    runner = load_runner()
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / RAW_CACHE_NAME)
    package = {"series": {"accession": [{"value": "GSE1"}], "title": "Base"}}
    store.put(
        "geo_metadata", "GSE1", 1, "retryable_error",
        payload={
            "packages": [package],
            "enrichment_mode": "all",
            "enrichment_state": "pending",
        },
        error="sanitized enrichment failure",
        error_type="TimeoutError",
        failure_category="provider_timeout",
    )

    runner._terminalize_exhausted_checkpoints(store)

    item = store.get("geo_metadata", "GSE1")
    assert item["status"] == "available"
    assert item["payload"]["packages"] == [package]
    assert item["payload"]["enrichment_mode"] == "partial"
    assert item["payload"]["repair_summary"]["failed_count"] == 1


def test_hydrate_only_cli_never_enters_benchmark_or_report_path(
    monkeypatch, tmp_path: Path
) -> None:
    runner = load_runner()
    calls = []
    audit_path = tmp_path / "out" / AUDIT_NAME
    monkeypatch.setattr(
        runner,
        "hydrate_cache",
        lambda **kwargs: calls.append(kwargs) or {"audit_path": audit_path},
    )
    monkeypatch.setattr(
        runner,
        "run_benchmark",
        lambda **_kwargs: pytest.fail("hydrate-only initialized the reviewer benchmark"),
    )
    monkeypatch.setattr(
        runner,
        "_write_report",
        lambda *_args, **_kwargs: pytest.fail("hydrate-only replaced the report"),
    )

    assert runner.main(["--out", str(tmp_path / "out"), "--hydrate-only"]) == 0
    assert len(calls) == 1
    assert calls[0]["raw_cache"].name == RAW_CACHE_NAME


def test_default_production_hydrator_uses_full_geo_identifier_enrichment(
    monkeypatch,
) -> None:
    runner = load_runner()
    import ThematicAtlases.collector as collector_module

    captured = {}

    class CapturingCollector:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(collector_module, "AtlasCollector", CapturingCollector)

    runner.ProductionHydrator(
        epmc_wrapper=object(),
        filterer=object(),
        review_service=object(),
    )

    handlers = captured["metadata_handlers"]
    assert set(handlers) == {"arrayexpress", "geo"}
    assert handlers["geo"]()._enrich_metadata is True


def test_abstract_with_complete_metadata_is_review_eligible() -> None:
    runner = load_runner()
    hydration = complete_hydration("abstract")
    hydration.update({
        "publication_text": "Usable abstract",
        "text_source": "abstractText",
        "full_text_status": "unavailable",
    })

    assert runner._hydration_downloads_complete(hydration)
    assert runner._hydration_is_complete(hydration)


def test_run_benchmark_logs_hydration_and_review_progress(
    tmp_path: Path, caplog
) -> None:
    runner = load_runner()
    dataset = tmp_path / "dataset.csv"
    write_dataset(
        dataset,
        [
            dataset_row("first", "relevant", pmid="1"),
            dataset_row("second", "relevant", pmid="2"),
        ],
    )
    caplog.set_level(logging.INFO, logger=runner.__name__)

    runner.run_benchmark(
        dataset_csv=dataset,
        cache_csv=tmp_path / CACHE_NAME,
        theme_file=THEME,
        hydrator=RecordingHydrator(),
        review_runner=RecordingReviewRunner(
            {"first": "relevant", "second": "relevant"}
        ),
    )

    assert "stage=hydrate publication_index=1 publication_total=2" in caplog.text
    assert "publication_id=first cache_action=refresh" in caplog.text
    assert "publication_id=second hydration_status=available" in caplog.text
    assert "stage=review publication_total=2 status=started" in caplog.text
    assert "stage=review publication_total=2 status=complete" in caplog.text


def test_main_verbose_configures_info_logging(monkeypatch, tmp_path: Path) -> None:
    runner = load_runner()
    calls = []
    report_path = tmp_path / "out" / REPORT_NAME

    monkeypatch.setattr(
        runner.logging,
        "basicConfig",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(runner, "run_benchmark", lambda **_kwargs: {})
    monkeypatch.setattr(
        runner,
        "_write_report",
        lambda _report, _output_directory: report_path,
    )

    assert runner.main(["--out", str(tmp_path / "out"), "--verbose"]) == 0
    assert calls == [
        {
            "level": logging.INFO,
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    ]


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
