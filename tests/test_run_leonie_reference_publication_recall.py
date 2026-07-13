import json
from pathlib import Path

import run_leonie_reference_publication_recall as runner


class RecordingBenchmark:
    calls = []

    def benchmark_reference_publication_recall(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return {
            "schema_version": "1.1",
            "summary": {"matched_count": 7, "reference_publication_count": 21},
        }


def test_runner_scores_existing_output_with_leonie_set(tmp_path, monkeypatch, capsys):
    RecordingBenchmark.calls = []
    thematic_output = tmp_path / "atlas.json"
    thematic_output.write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)

    result = runner.main([str(thematic_output), "--out", str(output)])

    assert result == 0
    assert RecordingBenchmark.calls == [
        {
            "reference_set": "leonie_2026_fibrosis",
            "thematic_output": thematic_output,
        }
    ]
    assert json.loads(output.read_text(encoding="utf-8"))["summary"] == {
        "matched_count": 7,
        "reference_publication_count": 21,
    }
    stdout = capsys.readouterr().out
    assert "leonie_2026_fibrosis" in stdout
    assert '"matched_count": 7' in stdout


def test_runner_defaults_report_under_out_directory(tmp_path, monkeypatch):
    RecordingBenchmark.calls = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "ThematicReviewerBenchmark", RecordingBenchmark)

    result = runner.main([str(tmp_path / "trace")])

    assert result == 0
    expected = tmp_path / ".out" / "leonie_2026_reference_publication_recall.json"
    assert expected.is_file()
    assert RecordingBenchmark.calls[0]["thematic_output"] == tmp_path / "trace"


def test_resolved_configuration_uses_stable_reference_set(tmp_path):
    config = runner.resolved_configuration(
        thematic_output=tmp_path / "atlas.json",
        out=tmp_path / "report.json",
    )

    assert config == {
        "reference_set": "leonie_2026_fibrosis",
        "thematic_output": str(tmp_path / "atlas.json"),
        "report_out": str(tmp_path / "report.json"),
    }
