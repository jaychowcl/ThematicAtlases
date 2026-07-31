import json

import pytest

import run_reference_set_review as runner
from ThematicAtlases.filterer import AtlasFilterer, PublicationTextReviewer


def _reference_data():
    return {
        "id": "leonie_2026_fibrosis",
        "reference_publications": [
            {"doi": "10.1/ONE", "title": "One"},
            {"doi": "https://doi.org/10.2/two", "title": "Two"},
        ],
    }


def test_reference_queries_use_exact_doi_field_syntax() -> None:
    assert runner.reference_queries(_reference_data()) == [
        "DOI:10.1/one",
        "DOI:10.2/two",
    ]


def test_exact_reference_matches_rejects_wrong_search_result() -> None:
    publications = [
        {"query": "DOI:10.1/one", "doi": "10.1/ONE", "epmc_id": "1"},
        {"query": "DOI:10.2/two", "doi": "10.2/not-two", "epmc_id": "2"},
    ]

    exact, audit = runner.exact_reference_matches(_reference_data(), publications)

    assert [item["epmc_id"] for item in exact] == ["1"]
    assert [item["status"] for item in audit] == ["resolved", "mismatched"]


def test_exact_reference_matches_records_unresolved_reference() -> None:
    exact, audit = runner.exact_reference_matches(_reference_data(), [])

    assert exact == []
    assert [item["status"] for item in audit] == ["unresolved", "unresolved"]


def test_main_writes_isolated_outputs_from_workflow(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_workflow(**kwargs):
        calls.append(kwargs)
        return {
            "audit": {"resolved": 2, "with_gse": 1},
            "reviewed": {"accessions": [], "publication_texts": {}},
            "benchmark": {"summary": {"matched_count": 1}},
        }

    theme = tmp_path / "theme.txt"
    theme.write_text("fibrosis theme", encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "THEME_FILE", theme)
    monkeypatch.setattr(runner, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(runner, "run_reference_review", fake_workflow)

    assert runner.main(["--reference-set", "leonie_2026_fibrosis"]) == 0

    output_dir = tmp_path / ".out" / "reference_reviews" / "leonie_2026_fibrosis"
    assert calls == [
        {
            "reference_set": "leonie_2026_fibrosis",
            "theme": "fibrosis theme",
            "output_dir": output_dir,
        }
    ]
    summary = json.loads((output_dir / "run_summary.json").read_text())
    assert summary == {
        "reference_set": "leonie_2026_fibrosis",
        "audit": {"resolved": 2, "with_gse": 1},
        "benchmark": {"matched_count": 1},
    }


def test_main_requires_project_environment_before_work(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "require_project_venv",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("use .env")),
    )
    with pytest.raises(RuntimeError, match="use .env"):
        runner.main([])


def test_reference_review_workflow_writes_diagnostic_artifacts(tmp_path) -> None:
    class FakeBenchmark:
        def load_reference_set(self, name):
            return {
                "id": name,
                "reference_publications": [
                    {"source_reference_number": 1, "doi": "10.1/one", "title": "One"}
                ],
            }

        def benchmark_reference_publication_recall(self, **kwargs):
            return {"summary": {"matched_count": 1}, "received": kwargs["thematic_output"]}

    class FakeEPMC:
        def collect_publications(self, queries, **kwargs):
            return [{"query": queries[0], "doi": "10.1/ONE", "source": "MED", "epmc_id": "1"}]

        def collect_datalinks(self, publications, checkpoint_store=None):
            rows = [{"datalink_id": "GSE1", "datalink_id_scheme": "GEO"}]
            checkpoint_store.put("datalinks", "MED:1", 1, "available", payload={"rows": rows})
            return [{**rows[0], "publications": publications}]

        def collect_publication_texts(self, publications, **kwargs):
            return [
                {
                    **publication,
                    "text": "fibrosis reference text",
                    "text_source": "abstract",
                    "full_text_status": "unavailable",
                }
                for publication in publications
            ]

    class FakeReviewer:
        def review_relevancy(self, **kwargs):
            return {
                "judgement": "relevant",
                "reasoning": "diagnostic",
                "confidence": "high",
                "evidences": ["fibrosis"],
                "accessions_to_remove": [],
            }

    class FakeCredentials:
        calls = 0

        def check(self):
            self.__class__.calls += 1

    epmc = FakeEPMC()
    filterer = AtlasFilterer(
        epmc_wrapper_factory=lambda: epmc,
        publication_text_reviewer=PublicationTextReviewer(reviewer_factory=FakeReviewer),
    )
    result = runner.run_reference_review(
        reference_set="diagnostic",
        theme="fibrosis",
        output_dir=tmp_path,
        benchmark=FakeBenchmark(),
        epmc_wrapper=epmc,
        filterer=filterer,
        credential_checker=FakeCredentials(),
    )

    assert result["audit"]["summary"] == {
        "reference_publications": 1,
        "resolved": 1,
        "unresolved": 0,
        "mismatched": 0,
        "with_gse": 1,
        "unique_gse_accessions": 1,
    }
    assert result["reviewed"]["publication_texts"]["10.1/ONE"]["agentic_curator"][
        "judgement"
    ] == "relevant"
    assert {
        path.name for path in tmp_path.iterdir() if path.is_file()
    } == {
        "00_run_manifest.json",
        "01_resolution_datalink_audit.json",
        "02_geo_accessions.json",
        "03_reviewer_input.json",
        "04_reviewed_output.json",
        "05_reference_benchmark.json",
        "resume_review_progress.json",
        "resume_state.sqlite",
    }
    assert FakeCredentials.calls == 1
