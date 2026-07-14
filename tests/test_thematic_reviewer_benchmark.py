import json
from importlib import resources
from pathlib import Path

import pytest

from benchmark_ThematicAtlases import ThematicReviewerBenchmark


BENCHMARK_FIXTURES = Path(__file__).parent / "fixtures" / "benchmark"
WATSON_DOI = "10.1038/s41467-024-55325-4"
REICHART_DOI = "10.1126/science.abo1984"

LEONIE_DOIS = [
    "10.64898/2026.03.09.709232",
    "10.1038/s41467-024-55325-4",
    "10.1126/science.abo1984",
    "10.1164/rccm.201712-2410oc",
    "10.1126/sciadv.aba1972",
    "10.1038/s41467-020-17358-3",
    "10.1126/sciadv.aba1983",
    "10.1038/s41467-020-15647-5",
    "10.1016/j.celrep.2023.112086",
    "10.1038/s41586-022-04817-8",
    "10.1038/s44161-022-00028-6",
    "10.1038/s41586-022-05060-x",
    "10.1038/s41586-023-05769-3",
    "10.1101/2025.09.12.25335572",
    "10.1038/s41588-024-01802-x",
    "10.1038/s41467-022-34255-z",
    "10.1016/j.cmet.2024.02.015",
    "10.1038/s41467-022-32972-z",
    "10.1038/s41586-019-1631-3",
    "10.1038/s41586-024-07465-2",
    "10.1016/j.jhep.2021.12.036",
]

TAYLOR_DOIS = [
    "10.1053/j.gastro.2020.01.043",
    "10.1002/hep.24491",
    "10.1002/hep.22868",
    "10.1016/j.jhep.2017.07.027",
    "10.1002/hep4.1124",
    "10.1016/j.cgh.2018.12.016",
    "10.1111/jgh.14448",
    "10.1002/hep.28697",
    "10.1371/journal.pone.0202393",
    "10.1371/journal.pone.0128774",
    "10.1111/hepr.12407",
    "10.1053/j.gastro.2018.04.034",
    "10.1002/hep.24268",
    "10.1002/hep4.1054",
    "10.1111/liv.13706",
]


def benchmark_references(references: list[dict], thematic_output) -> dict:
    benchmark = ThematicReviewerBenchmark()
    benchmark._load_reference_set = lambda _name: {
        "schema_version": "1.0",
        "id": "test-references",
        "name": "Test references",
        "description": "Synthetic unit-test references.",
        "source": {"doi": "10.0000/test"},
        "reference_publications": references,
    }
    return benchmark.benchmark_reference_publication_recall(
        reference_set="test-references",
        thematic_output=thematic_output,
    )


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
    report = benchmark_references(
        [
            {"doi": f"https://doi.org/{WATSON_DOI}", "source_row": 15},
            {"doi": f"DOI: {WATSON_DOI.upper()}", "source_row": "duplicate"},
            {"pmid": 37700002, "source_row": 16},
            {"doi": REICHART_DOI, "source_row": 17},
        ],
        reviewed_output(),
    )

    assert report["schema_version"] == "1.1"
    assert report["benchmark"] == {
        "method": "reference_publication_recall",
        "reference_set": {
            "id": "test-references",
            "name": "Test references",
            "description": "Synthetic unit-test references.",
            "source": {"doi": "10.0000/test"},
            "publication_count": 4,
        },
    }
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

    report = benchmark_references(
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

    report = benchmark_references(
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

    report = benchmark_references(
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

    report = benchmark_references(
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
        benchmark_references(references, reviewed_output())


def test_benchmark_rejects_output_without_atlas_shape(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="accessions.*publication_texts"):
        benchmark_references([{"pmid": "1"}], invalid)


def test_benchmark_trace_requires_a_supported_json_artifact(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="review artifact"):
        benchmark_references([{"pmid": "1"}], tmp_path)


def test_leonie_reference_set_is_packaged_and_complete() -> None:
    data_file = resources.files(
        "benchmark_ThematicAtlases.thematic_reviewer"
    ).joinpath("data", "leonie_2026_fibrosis.json")
    assert data_file.is_file()

    reference_set = ThematicReviewerBenchmark()._load_reference_set(
        "leonie_2026_fibrosis"
    )
    publications = reference_set["reference_publications"]

    assert reference_set["id"] == "leonie_2026_fibrosis"
    assert reference_set["source"]["doi"] == "10.64898/2026.03.09.709232"
    assert [publication["doi"] for publication in publications] == LEONIE_DOIS
    assert publications[0]["relationship"] == "source_meta_study"
    assert publications[0]["source_reference_number"] is None
    assert [
        publication["source_reference_number"] for publication in publications[1:]
    ] == list(range(15, 35))
    assert all(
        {
            "source_reference_number",
            "relationship",
            "doi",
            "title",
            "authors_as_cited",
            "journal",
            "year",
            "citation",
        }
        <= publication.keys()
        for publication in publications
    )
    assert len({publication["doi"] for publication in publications}) == 21
    json.dumps(reference_set)


def test_named_reference_set_benchmarks_all_publications() -> None:
    accessions = []
    publication_texts = {}
    for index, doi in enumerate(LEONIE_DOIS):
        publication_ref = f"publication-{index}"
        accessions.append(
            {
                "datalink_id": f"GSE{index}",
                "publications": [
                    {"doi": doi, "publication_text_ref": publication_ref}
                ],
            }
        )
        publication_texts[publication_ref] = {
            "agentic_curator": {"judgement": "relevant"}
        }

    report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
        reference_set="leonie_2026_fibrosis",
        thematic_output={
            "accessions": accessions,
            "publication_texts": publication_texts,
        },
    )

    assert report["benchmark"]["reference_set"]["publication_count"] == 21
    assert report["summary"]["matched_count"] == 21
    assert report["summary"]["relevant_recall"] == 1


def test_public_reference_set_loader_returns_packaged_data() -> None:
    reference_set = ThematicReviewerBenchmark().load_reference_set(
        "leonie_2026_fibrosis"
    )

    assert reference_set["id"] == "leonie_2026_fibrosis"
    assert len(reference_set["reference_publications"]) == 21


def test_named_reference_set_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown.*leonie_2026_fibrosis"):
        ThematicReviewerBenchmark().benchmark_reference_publication_recall(
            reference_set="missing",
            thematic_output=reviewed_output(),
        )


def test_old_generic_benchmark_method_is_removed() -> None:
    assert not hasattr(ThematicReviewerBenchmark(), "benchmark")


def test_available_reference_sets_include_leonie_and_taylor() -> None:
    assert ThematicReviewerBenchmark.available_reference_sets() == (
        "leonie_2026_fibrosis",
        "taylor_2020_nafld_fibrosis",
    )


def test_taylor_reference_set_is_packaged_and_complete() -> None:
    data_file = resources.files(
        "benchmark_ThematicAtlases.thematic_reviewer"
    ).joinpath("data", "taylor_2020_nafld_fibrosis.json")
    assert data_file.is_file()

    reference_set = ThematicReviewerBenchmark()._load_reference_set(
        "taylor_2020_nafld_fibrosis"
    )
    publications = reference_set["reference_publications"]

    assert reference_set["source"]["doi"] == "10.1053/j.gastro.2020.01.043"
    assert [publication["doi"] for publication in publications] == TAYLOR_DOIS
    assert publications[0]["relationship"] == "source_meta_study"
    assert publications[0]["source_reference_number"] is None
    assert [item["source_reference_number"] for item in publications[1:]] == list(
        range(18, 32)
    )
    assert len({publication["doi"] for publication in publications}) == 15


def test_benchmark_loads_reference_set_from_file(tmp_path) -> None:
    reference_file = tmp_path / "custom.json"
    reference_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "id": "custom_fibrosis",
                "name": "Custom fibrosis references",
                "description": "One custom publication.",
                "source": {"doi": "10.1000/source"},
                "reference_publications": [{"doi": WATSON_DOI}],
            }
        ),
        encoding="utf-8",
    )

    report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
        reference_set_file=reference_file,
        thematic_output=reviewed_output(),
    )

    assert report["benchmark"]["reference_set"]["id"] == "custom_fibrosis"
    assert report["summary"]["matched_count"] == 1


def test_benchmark_requires_exactly_one_reference_set_source(tmp_path) -> None:
    benchmark = ThematicReviewerBenchmark()
    with pytest.raises(ValueError, match="exactly one"):
        benchmark.benchmark_reference_publication_recall(
            thematic_output=reviewed_output()
        )
    with pytest.raises(ValueError, match="exactly one"):
        benchmark.benchmark_reference_publication_recall(
            reference_set="leonie_2026_fibrosis",
            reference_set_file=tmp_path / "custom.json",
            thematic_output=reviewed_output(),
        )


def test_file_reference_set_rejects_invalid_schema(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"id": "incomplete"}', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid reference set"):
        ThematicReviewerBenchmark().benchmark_reference_publication_recall(
            reference_set_file=invalid,
            thematic_output=reviewed_output(),
        )


def test_leonie_mixed_example_matches_complete_expected_report() -> None:
    thematic_output = BENCHMARK_FIXTURES / "leonie_mixed_thematic_output.json"
    expected_path = BENCHMARK_FIXTURES / "leonie_mixed_expected_report.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert expected["source"]["artifact"] == "<THEMATIC_OUTPUT_PATH>"
    expected["source"]["artifact"] = str(thematic_output)

    report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
        reference_set="leonie_2026_fibrosis",
        thematic_output=thematic_output,
    )

    assert report["summary"] == {
        "input_record_count": 21,
        "reference_publication_count": 21,
        "duplicate_record_count": 0,
        "matched_count": 6,
        "missed_count": 15,
        "conflict_count": 0,
        "discovery_recall": 6 / 21,
        "review_completed_count": 4,
        "review_failed_count": 1,
        "unreviewed_count": 1,
        "judgement_counts": {
            "relevant": 2,
            "unsure": 1,
            "not_relevant": 1,
            "other": 0,
        },
        "relevant_recall": 2 / 21,
        "candidate_recall": 3 / 21,
    }
    assert report == expected


def test_taylor_mixed_example_matches_complete_expected_report() -> None:
    thematic_output = BENCHMARK_FIXTURES / "taylor_mixed_thematic_output.json"
    expected_path = BENCHMARK_FIXTURES / "taylor_mixed_expected_report.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert expected["source"]["artifact"] == "<THEMATIC_OUTPUT_PATH>"
    expected["source"]["artifact"] = str(thematic_output)

    report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
        reference_set="taylor_2020_nafld_fibrosis",
        thematic_output=thematic_output,
    )

    assert report["summary"] == {
        "input_record_count": 15,
        "reference_publication_count": 15,
        "duplicate_record_count": 0,
        "matched_count": 6,
        "missed_count": 9,
        "conflict_count": 0,
        "discovery_recall": 6 / 15,
        "review_completed_count": 4,
        "review_failed_count": 1,
        "unreviewed_count": 1,
        "judgement_counts": {
            "relevant": 2,
            "unsure": 1,
            "not_relevant": 1,
            "other": 0,
        },
        "relevant_recall": 2 / 15,
        "candidate_recall": 3 / 15,
    }
    assert report == expected
