import json

import pytest

from ThematicAtlases.cli_atlas import main
from ThematicAtlases import atlas as atlas_module


class FakeEuropePMCWrapper:
    def collect_accessions(self, queries: list[str]) -> list[dict]:
        return [{"epmc_id": query} for query in queries]


def test_collect_jsons_emits_placeholder_response(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--query", "fibrosis", "--query", "transcriptomics"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "collect-jsons",
        "status": "placeholder",
        "result": [{"epmc_id": "fibrosis"}, {"epmc_id": "transcriptomics"}],
    }


def test_collect_jsons_accepts_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("fibrosis\\ntranscriptomics\\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--file", str(query_file)]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "collect-jsons",
        "status": "placeholder",
        "result": [{"epmc_id": "fibrosis"}, {"epmc_id": "transcriptomics"}],
    }


def test_collect_jsons_writes_outfile(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--query", "fibrosis", "--out", str(outfile)]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "collect-jsons",
        "status": "placeholder",
        "result": [{"epmc_id": "fibrosis"}],
    }
    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "epmc_id": "fibrosis"\n  }\n]'


def test_filter_jsons_emits_placeholder_response(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["filter-jsons"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "filter-jsons",
        "status": "placeholder",
        "result": None,
    }


def test_harmonize_jsons_emits_placeholder_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["harmonize-jsons"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "harmonize-jsons",
        "status": "placeholder",
        "result": None,
    }


def test_unknown_command_exits_with_argparse_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-command"])

    assert exc_info.value.code == 2
