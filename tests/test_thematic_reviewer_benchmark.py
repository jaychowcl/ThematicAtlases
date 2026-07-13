import json

import pytest

from benchmark_ThematicAtlases import ThematicReviewerBenchmark


WATSON_DOI = "10.1038/s41467-024-55325-4"
REICHART_DOI = "10.1126/science.abo1984"


def reviewed_output() -> dict:
    return {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "doi": WATSON_DOI.upper(),
                        "pmid": "39810001",
                        "title": "Spatial transcriptomics of healthy and fibrotic human liver",
                        "publication_text_ref": "39810001",
                    }
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [
                    {
                        "doi": WATSON_DOI,
                        "pmid": "39810001",
                        "title": "Spatial transcriptomics of healthy and fibrotic human liver",
                        "publication_text_ref": "39810001",
                    },
                    {
                        "pmid": "37700002",
                        "title": "PMID matched publication",
                        "publication_text_ref": "37700002",
                    },
                ],
            },
        ],
        "publication_texts": {
            "39810001": {
                "agentic_curator": {
                    "theme": "fibrosis",
                    "judgement": "Relevant",
                }
            },
            "37700002": {
                "agentic_curator": {
                    "theme": "fibrosis",
                    "judgement": "UNSURE",
                }
            },
        },
    }


def test_benchmark_reports_discovery_and_judgement_recall() -> None:
    report = ThematicReviewerBenchmark().benchmark(
        reference_publications=[
            {"doi": f"https://doi.org/{WATSON_DOI}", "source_row": 15},
            {"doi": f"DOI: {WATSON_DOI.upper()}", "source_row": "duplicate"},
            {"pmid": 37700002, "source_row": 16},
            {"doi": REICHART_DOI, "source_row": 17},
        ],
        thematic_output=reviewed_output(),
    )

    assert report["schema_version"] == "1.0"
    assert report["source"] == {
        "kind": "object",
        "artifact": None,
        "view": "unknown",
        "complete": None,
        "limitations": [
            "The source stage is unknown; publications removed by review filtering may be indistinguishable from publications that were never discovered."
        ],
    }
    assert report["summary"] == {
        "input_record_count": 4,
        "reference_publication_count": 3,
        "duplicate_record_count": 1,
        "matched_count": 2,
        "missed_count": 1,
        "conflict_count": 0,
        "discovery_recall": 2 / 3,
        "review_completed_count": 2,
        "review_failed_count": 0,
        "unreviewed_count": 0,
        "judgement_counts": {
            "relevant": 1,
            "unsure": 1,
            "not_relevant": 0,
            "other": 0,
        },
        "relevant_recall": 1 / 3,
        "candidate_recall": 2 / 3,
    }

    watson = report["publications"][0]
    assert watson["reference_indices"] == [0, 1]
    assert watson["references"][0]["source_row"] == 15
    assert watson["normalized_identifiers"] == {
        "dois": [WATSON_DOI],
        "pmids": [],
    }
    assert watson["status"] == "matched"
    assert watson["matched_by"] == ["doi"]
    assert watson["matched_publication"]["accession_ids"] == ["GSE1", "GSE2"]
    assert watson["review"] == {
        "status": "completed",
        "judgement": "relevant",
    }
    assert report["publications"][2]["status"] == "missed"
    json.dumps(report)


def test_benchmark_reports_identifier_conflicts_without_choosing_a_match() -> None:
    output = {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {"doi": WATSON_DOI, "publication_text_ref": "doi-ref"},
                    {"pmid": "37700002", "publication_text_ref": "pmid-ref"},
                ],
            }
        ],
        "publication_texts": {
            "doi-ref": {"agentic_curator": {"judgement": "relevant"}},
            "pmid-ref": {"agentic_curator": {"judgement": "relevant"}},
        },
    }

    report = ThematicReviewerBenchmark().benchmark(
        [{"doi": WATSON_DOI, "pmid": "37700002"}],
        output,
    )

    assert report["summary"]["matched_count"] == 0
    assert report["summary"]["conflict_count"] == 1
    assert report["publications"][0]["status"] == "conflict"
    assert report["publications"][0]["matched_publication"] is None
    assert len(report["publications"][0]["conflicting_publications"]) == 2


def test_benchmark_classifies_failed_unreviewed_and_other_reviews() -> None:
    output = {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {"pmid": "1", "publication_text_ref": "1"},
                    {"pmid": "2", "publication_text_ref": "2"},
                    {"pmid": "3", "publication_text_ref": "3"},
                    {"pmid": "4", "publication_text_ref": "4"},
                ],
            }
        ],
        "publication_texts": {
            "1": {"agentic_curator": {"judgement": "not_relevant"}},
            "2": {"agentic_curator": {"review_status": "failed"}},
            "3": {},
            "4": {"agentic_curator": {"judgement": "possibly relevant"}},
        },
    }

    report = ThematicReviewerBenchmark().benchmark(
        [{"pmid": value} for value in (1, 2, 3, 4)],
        output,
    )

    assert report["summary"]["review_completed_count"] == 2
    assert report["summary"]["review_failed_count"] == 1
    assert report["summary"]["unreviewed_count"] == 1
    assert report["summary"]["judgement_counts"] == {
        "relevant": 0,
        "unsure": 0,
        "not_relevant": 1,
        "other": 1,
    }


def test_benchmark_trace_directory_prefers_pre_filter_review_progress(tmp_path) -> None:
    trace = tmp_path / "run"
    trace.mkdir()
    progress = reviewed_output()
    filtered = {"accessions": [], "publication_texts": {}}
    (trace / "resume_review_progress.json").write_text(
        json.dumps(progress), encoding="utf-8"
    )
    (trace / "02_reviewed_datasets.json").write_text(
        json.dumps(filtered), encoding="utf-8"
    )

    report = ThematicReviewerBenchmark().benchmark(
        [{"doi": WATSON_DOI}],
        trace,
    )

    assert report["summary"]["matched_count"] == 1
    assert report["source"] == {
        "kind": "dev_trace",
        "artifact": str(trace / "resume_review_progress.json"),
        "view": "pre_filter",
        "complete": True,
        "limitations": [],
    }


def test_benchmark_loads_explicit_post_filter_json_with_limitation(tmp_path) -> None:
    output = tmp_path / "02_reviewed_datasets.json"
    output.write_text(json.dumps(reviewed_output()), encoding="utf-8")

    report = ThematicReviewerBenchmark().benchmark(
        [{"doi": WATSON_DOI}],
        output,
    )

    assert report["source"]["kind"] == "json"
    assert report["source"]["view"] == "post_filter"
    assert report["source"]["complete"] is True
    assert report["source"]["limitations"]


@pytest.mark.parametrize(
    "references, message",
    [
        ([], "must not be empty"),
        ([{"title": "No identifier"}], "DOI or PMID"),
        ([{"doi": "not-a-doi"}], "invalid DOI"),
        ([{"pmid": "PMID: abc"}], "invalid PMID"),
    ],
)
def test_benchmark_rejects_invalid_reference_publications(
    references, message
) -> None:
    with pytest.raises(ValueError, match=message):
        ThematicReviewerBenchmark().benchmark(references, reviewed_output())


def test_benchmark_rejects_output_without_atlas_shape(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="accessions.*publication_texts"):
        ThematicReviewerBenchmark().benchmark([{"pmid": "1"}], invalid)


def test_benchmark_trace_requires_a_supported_json_artifact(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="review artifact"):
        ThematicReviewerBenchmark().benchmark([{"pmid": "1"}], tmp_path)
