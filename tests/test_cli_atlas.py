import logging
import json

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

    def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
        return publications


class FakeGEOWrapper:
    def collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        return [
            {
                **record,
                "datalink_id": str(record.get("datalink_id", "")).upper(),
                "original_datalinks": [
                    {
                        "datalink_id": record.get("datalink_id", ""),
                        "datalink_id_scheme": record.get("datalink_id_scheme", ""),
                        "datalink_url": record.get("datalink_url", ""),
                        "datalink_category": record.get("datalink_category", ""),
                    }
                ],
                "metadata_repository": "geo",
                "metadata_source": "geo2json",
                "metadata_status": "available",
                "accession_metadata": {
                    "series": {
                        "accession": [
                            {
                                "value": str(record.get("datalink_id", "")).upper(),
                            }
                        ]
                    }
                },
            }
            for record in jsons
        ]


def test_collect_jsons_does_not_emit_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

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
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

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
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["collect-jsons", "--query", "fibrosis", "--out", str(outfile)]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "datalink_id": "GSE_FIBROSIS",\n    "datalink_id_scheme": "GEO",\n    "publications": [],\n    "original_datalinks": [\n      {\n        "datalink_id": "GSE_fibrosis",\n        "datalink_id_scheme": "GEO",\n        "datalink_url": "",\n        "datalink_category": ""\n      }\n    ],\n    "metadata_repository": "geo",\n    "metadata_source": "geo2json",\n    "metadata_status": "available",\n    "accession_metadata": {\n      "series": {\n        "accession": [\n          {\n            "value": "GSE_FIBROSIS"\n          }\n        ]\n      }\n    }\n  }\n]'


def test_create_atlas_does_not_emit_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["create-atlas", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == ""


def test_create_atlas_writes_final_filtered_object(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["create-atlas", "--query", "fibrosis", "--out", str(outfile)]) == 0

    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == ""
    assert outfile.read_text(encoding="utf-8") == '{\n  "accessions": [\n    {\n      "datalink_id": "GSE_FIBROSIS",\n      "datalink_id_scheme": "GEO",\n      "publications": [],\n      "original_datalinks": [\n        {\n          "datalink_id": "GSE_fibrosis",\n          "datalink_id_scheme": "GEO",\n          "datalink_url": "",\n          "datalink_category": ""\n        }\n      ],\n      "metadata_repository": "geo",\n      "metadata_source": "geo2json",\n      "metadata_status": "available",\n      "accession_metadata": {\n        "series": {\n          "accession": [\n            {\n              "value": "GSE_FIBROSIS"\n            }\n          ]\n        }\n      }\n    }\n  ],\n  "publication_texts": {}\n}'


def test_verbose_enables_info_logging(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["--verbose", "collect-jsons", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()

    assert "INFO:ThematicAtlases.test:fake info" in output.out
    assert "DEBUG:ThematicAtlases.test:fake debug" not in output.out
    assert output.err == ""


def test_verbose_create_atlas_emits_info_logging_to_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["--verbose", "create-atlas", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()

    assert "INFO:ThematicAtlases.atlas:Atlas create_atlas progress stage=collect-jsons" in output.out
    assert "INFO:ThematicAtlases.test:fake info" in output.out
    assert output.err == ""


def test_verbose_log_file_writes_logs_and_keeps_stdout_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
    tmp_path,
) -> None:
    log_file = tmp_path / "atlas.log"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

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


def test_verbose_create_atlas_log_file_writes_logs_only_to_file(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
    tmp_path,
) -> None:
    log_file = tmp_path / "atlas.log"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert (
        main(
            [
                "--verbose",
                "--log-file",
                str(log_file),
                "create-atlas",
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
    assert "INFO:ThematicAtlases.atlas:Atlas create_atlas progress stage=collect-jsons" in log_text
    assert "INFO:ThematicAtlases.test:fake info" in log_text


def test_double_verbose_enables_debug_logging(tmp_path) -> None:
    log_file = tmp_path / "atlas.log"

    _configure_logging(verbosity=2, log_file=str(log_file))
    logging.getLogger("ThematicAtlases.test").debug("debug enabled")

    assert "DEBUG:ThematicAtlases.test:debug enabled" in log_file.read_text(
        encoding="utf-8"
    )


def test_filter_command_does_not_emit_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["filter-jsons"]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_filter_jsons_accepts_list_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    input_file = tmp_path / "collected.json"
    output_file = tmp_path / "filtered.json"
    input_file.write_text(
        json.dumps(
            [
                {
                    "datalink_id": "GSE1",
                    "publications": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "filter-jsons",
                "--file",
                str(input_file),
                "--out",
                str(output_file),
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert json.loads(output_file.read_text(encoding="utf-8")) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [],
            }
        ],
        "publication_texts": {},
    }


def test_filter_jsons_accepts_atlas_object_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    input_file = tmp_path / "atlas.json"
    output_file = tmp_path / "filtered.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [],
                    }
                ],
                "publication_texts": {"old": {"text": "ignored"}},
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "filter-jsons",
                "--file",
                str(input_file),
                "--out",
                str(output_file),
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert json.loads(output_file.read_text(encoding="utf-8")) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [],
            }
        ],
        "publication_texts": {"old": {"text": "ignored"}},
    }


def test_filter_jsons_reuses_existing_publication_texts(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    input_file = tmp_path / "atlas.json"
    output_file = tmp_path / "filtered.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [
                            {
                                "source": "MED",
                                "epmc_id": "1",
                                "pmid": "1",
                                "publication_text_ref": "1",
                            }
                        ],
                    }
                ],
                "publication_texts": {
                    "1": {
                        "text": "Existing full text",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "filter-jsons",
                "--file",
                str(input_file),
                "--out",
                str(output_file),
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert json.loads(output_file.read_text(encoding="utf-8")) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "publication_text_ref": "1",
                    }
                ],
            }
        ],
        "publication_texts": {
            "1": {
                "text": "Existing full text",
                "text_source": "fullTextXML",
                "full_text_status": "available",
            }
        },
    }


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
