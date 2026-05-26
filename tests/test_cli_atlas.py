import logging

import pytest

from ThematicAtlases.cli_atlas import _configure_logging, main
from ThematicAtlases import atlas as atlas_module


class FakeEuropePMCWrapper:
    def collect_accessions(self, queries: list[str]) -> list[dict]:
        logging.getLogger("ThematicAtlases.test").info("fake info")
        logging.getLogger("ThematicAtlases.test").debug("fake debug")
        return [
            {
                "datalink_id": f"GSE_{query}",
                "datalink_id_scheme": "GEO",
                "publications": [],
            }
            for query in queries
        ]


def test_collect_jsons_does_not_emit_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--query", "fibrosis", "--query", "transcriptomics"]) == 0

    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == ""


def test_collect_jsons_accepts_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("fibrosis\\ntranscriptomics\\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--file", str(query_file)]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_collect_jsons_writes_outfile(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["collect-jsons", "--query", "fibrosis", "--out", str(outfile)]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "datalink_id": "GSE_FIBROSIS",\n    "datalink_id_scheme": "GEO",\n    "publications": [],\n    "original_datalinks": [\n      {\n        "datalink_id": "GSE_fibrosis",\n        "datalink_id_scheme": "GEO",\n        "datalink_url": "",\n        "datalink_category": ""\n      }\n    ]\n  }\n]'


def test_verbose_enables_info_logging(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert main(["--verbose", "collect-jsons", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()

    assert output.out == ""
    assert "INFO:ThematicAtlases.test:fake info" in output.err
    assert "DEBUG:ThematicAtlases.test:fake debug" not in output.err


def test_verbose_log_file_writes_logs_and_keeps_stdout_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
    tmp_path,
) -> None:
    log_file = tmp_path / "atlas.log"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert (
        main(
            [
                "--verbose",
                "--log-file",
                str(log_file),
                "collect-jsons",
                "--query",
                "fibrosis",
            ]
        )
        == 0
    )

    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == ""
    log_text = log_file.read_text(encoding="utf-8")
    assert "INFO:ThematicAtlases.test:fake info" in log_text
    assert "DEBUG:ThematicAtlases.test:fake debug" not in log_text


def test_double_verbose_enables_debug_logging(tmp_path) -> None:
    log_file = tmp_path / "atlas.log"

    _configure_logging(verbosity=2, log_file=str(log_file))
    logging.getLogger("ThematicAtlases.test").debug("debug enabled")

    assert "DEBUG:ThematicAtlases.test:debug enabled" in log_file.read_text(
        encoding="utf-8"
    )


def test_filter_jsons_does_not_emit_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["filter-jsons"]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_harmonize_jsons_does_not_emit_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["harmonize-jsons"]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_unknown_command_exits_with_argparse_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-command"])

    assert exc_info.value.code == 2
