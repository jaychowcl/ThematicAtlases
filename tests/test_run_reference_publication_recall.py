import json
from pathlib import Path

import pytest

import run_reference_publication_recall as runner


BENCHMARK_FIXTURES = Path(__file__).parent / "fixtures" / "benchmark"


class RecordingBenchmark:
    calls = []

    @staticmethod
    def available_reference_sets():
        return ("leonie_2026_fibrosis", "taylor_2020_nafld_fibrosis")

    def benchmark_reference_publication_recall(self, **kwargs):
        self.__class__.calls.append(kwargs)
        reference_id = kwargs.get("reference_set")
        if reference_id is None:
            reference_data = json.loads(
                kwargs["reference_set_file"].read_text(encoding="utf-8")
            )
            reference_id = reference_data["id"]
        return {
            "schema_version": "1.1",
            "benchmark": {"reference_set": {"id": reference_id}},
            "summary": {"matched_count": 1},
        }


def test_runner_runs_all_packaged_sets_into_one_report(tmp_path, monkeypatch, capsys):
    RecordingBenchmark.calls = []
    output = tmp_path / "report.json"
    thematic_output = tmp_path / "atlas.json"
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)

    result = runner.main([str(thematic_output), "--out", str(output)])

    assert result == 0
    assert RecordingBenchmark.calls == [
        {
            "reference_set": "leonie_2026_fibrosis",
            "thematic_output": thematic_output,
        },
        {
            "reference_set": "taylor_2020_nafld_fibrosis",
            "thematic_output": thematic_output,
        },
    ]
    aggregate = json.loads(output.read_text(encoding="utf-8"))
    assert aggregate["schema_version"] == "1.0"
    assert aggregate["thematic_output"] == str(thematic_output)
    assert list(aggregate["reports"]) == [
        "leonie_2026_fibrosis",
        "taylor_2020_nafld_fibrosis",
    ]
    displayed = capsys.readouterr().out
    assert '"leonie_2026_fibrosis"' in displayed
    assert '"taylor_2020_nafld_fibrosis"' in displayed


def test_runner_adds_repeated_custom_reference_set_files(tmp_path, monkeypatch):
    RecordingBenchmark.calls = []
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"id": "custom_one"}', encoding="utf-8")
    second.write_text('{"id": "custom_two"}', encoding="utf-8")
    output = tmp_path / "report.json"

    runner.main(
        [
            str(tmp_path / "atlas.json"),
            "--reference-set-file",
            str(first),
            "--reference-set-file",
            str(second),
            "--out",
            str(output),
        ]
    )

    assert list(json.loads(output.read_text())["reports"]) == [
        "leonie_2026_fibrosis",
        "taylor_2020_nafld_fibrosis",
        "custom_one",
        "custom_two",
    ]
    assert RecordingBenchmark.calls[-2]["reference_set_file"] == first
    assert RecordingBenchmark.calls[-1]["reference_set_file"] == second


def test_runner_rejects_duplicate_ids_without_writing_report(tmp_path, monkeypatch):
    RecordingBenchmark.calls = []
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"id": "leonie_2026_fibrosis"}', encoding="utf-8")
    output = tmp_path / "report.json"

    with pytest.raises(ValueError, match="duplicate reference set"):
        runner.main(
            [
                str(tmp_path / "atlas.json"),
                "--reference-set-file",
                str(duplicate),
                "--out",
                str(output),
            ]
        )

    assert not output.exists()


def test_runner_defaults_to_aggregate_output_under_root(tmp_path, monkeypatch):
    RecordingBenchmark.calls = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)

    runner.main([str(tmp_path / "atlas.json")])

    assert (tmp_path / ".out" / "reference_publication_recall.json").is_file()


def test_resolved_configuration_lists_packaged_and_custom_sets(tmp_path):
    config = runner.resolved_configuration(
        thematic_output=tmp_path / "atlas.json",
        out=tmp_path / "report.json",
        packaged_reference_sets=("one", "two"),
        reference_set_files=[tmp_path / "custom.json"],
    )

    assert config == {
        "thematic_output": str(tmp_path / "atlas.json"),
        "report_out": str(tmp_path / "report.json"),
        "packaged_reference_sets": ["one", "two"],
        "reference_set_files": [str(tmp_path / "custom.json")],
    }


def test_real_runner_benchmarks_both_packaged_sets(tmp_path, capsys):
    thematic_output = BENCHMARK_FIXTURES / "taylor_mixed_thematic_output.json"
    output = tmp_path / "aggregate.json"

    result = runner.main([str(thematic_output), "--out", str(output)])

    assert result == 0
    aggregate = json.loads(output.read_text(encoding="utf-8"))
    assert list(aggregate["reports"]) == [
        "leonie_2026_fibrosis",
        "taylor_2020_nafld_fibrosis",
    ]
    assert aggregate["reports"]["leonie_2026_fibrosis"]["summary"][
        "matched_count"
    ] == 0
    assert aggregate["reports"]["taylor_2020_nafld_fibrosis"]["summary"][
        "matched_count"
    ] == 6
    capsys.readouterr()
