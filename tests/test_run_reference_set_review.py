import json

import pytest

import run_reference_set_review as runner


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
