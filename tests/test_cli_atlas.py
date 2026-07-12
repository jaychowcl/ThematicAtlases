import logging
import json

import pytest

from ThematicAtlases.cli_atlas import _configure_logging, main
from ThematicAtlases import atlas as atlas_module
from ThematicAtlases import cli_atlas as cli_module


class FakeOntologyHarmonizer:
    def harmonize_miniml_json(self, publication_context=None, miniml_json=None):
        return {
            "miniml_json": miniml_json,
            "harmonization_targets": [],
            "strategy": "websearch",
            "target_paths": [],
        }


@pytest.fixture(autouse=True)
def fake_ontology_harmonizer(monkeypatch):
    import agentic_curator

    monkeypatch.setattr(agentic_curator, "OntologyHarmonizer", FakeOntologyHarmonizer)


class FakeEuropePMCWrapper:
    def collect_accessions(
        self,
        queries: list[str],
        max_publications: int | None = None,
    ) -> list[dict]:
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


class RecordingCollectionAtlas:
    calls = []

    def __init__(self, metadata):
        pass

    def collect_datasets(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return {"accessions": [], "publication_texts": {}}

    def create_atlas(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return {"accessions": [], "publication_texts": {}}


def test_query_generator_flag_is_forwarded_to_collect_method(
    tmp_path,
    monkeypatch,
) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("# ignored\nfile query\n", encoding="utf-8")
    RecordingCollectionAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingCollectionAtlas)

    assert main([
        "collect-datasets",
        "--query",
        "explicit query",
        "--file",
        str(query_file),
        "--theme",
        "fibrosis theme",
        "--query-generator",
    ]) == 0

    assert RecordingCollectionAtlas.calls[0]["query"] == ["explicit query"]
    assert RecordingCollectionAtlas.calls[0]["file"] == str(query_file)
    assert RecordingCollectionAtlas.calls[0]["generate_queries"] is True
    assert RecordingCollectionAtlas.calls[0]["max_generated_queries"] == 3


def test_query_generator_flag_and_theme_file_are_forwarded_to_create_method(
    tmp_path, monkeypatch
) -> None:
    theme_file = tmp_path / "theme.txt"
    theme_file.write_text("theme from file", encoding="utf-8")
    RecordingCollectionAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingCollectionAtlas)

    assert main([
        "create-atlas",
        "--theme",
        "ignored theme",
        "--theme-file",
        str(theme_file),
        "--query-generator",
    ]) == 0

    assert RecordingCollectionAtlas.calls[0]["theme"] == "theme from file"
    assert RecordingCollectionAtlas.calls[0]["generate_queries"] is True


def test_query_generator_requires_non_empty_theme(tmp_path, monkeypatch) -> None:
    theme_file = tmp_path / "theme.txt"
    theme_file.write_text("\n", encoding="utf-8")
    RecordingCollectionAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingCollectionAtlas)

    with pytest.raises(SystemExit, match="2"):
        main([
            "collect-datasets",
            "--theme-file",
            str(theme_file),
            "--query-generator",
        ])

    assert RecordingCollectionAtlas.calls == []


def test_query_generator_is_not_called_without_flag(monkeypatch) -> None:
    RecordingCollectionAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingCollectionAtlas)

    assert main(["collect-datasets", "--query", "manual query"]) == 0

    assert RecordingCollectionAtlas.calls[0]["query"] == ["manual query"]
    assert RecordingCollectionAtlas.calls[0]["generate_queries"] is False


def test_collect_datasets_does_not_emit_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["collect-datasets", "--query", "fibrosis", "--query", "transcriptomics"]) == 0

    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == ""


def test_collect_datasets_accepts_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("fibrosis\\ntranscriptomics\\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["collect-datasets", "--file", str(query_file)]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_collect_datasets_writes_outfile(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["collect-datasets", "--query", "fibrosis", "--out", str(outfile)]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert json.loads(outfile.read_text(encoding="utf-8")) == {
        "accessions": [
            {
                "datalink_id": "GSE_FIBROSIS",
                "datalink_id_scheme": "GEO",
                "publications": [],
                "original_datalinks": [
                    {
                        "datalink_id": "GSE_fibrosis",
                        "datalink_id_scheme": "GEO",
                        "datalink_url": "",
                        "datalink_category": "",
                    }
                ],
                "metadata_repository": "geo",
                "metadata_source": "geo2json",
                "metadata_status": "available",
                "accession_metadata": {
                    "series": {"accession": [{"value": "GSE_FIBROSIS"}]}
                },
            }
        ],
        "publication_texts": {},
    }


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
    result = json.loads(outfile.read_text(encoding="utf-8"))
    assert result["accessions"][0]["datalink_id"] == "GSE_FIBROSIS"
    assert result["accessions"][0]["accession_metadata"] == {
        "series": {"accession": [{"value": "GSE_FIBROSIS"}]}
    }
    assert result["accessions"][0]["ontology_harmonization_status"] == "available"
    assert result["publication_texts"] == {}


def test_verbose_enables_info_logging(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["--verbose", "collect-datasets", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()

    assert "INFO:ThematicAtlases.test:fake info" in output.out
    assert "DEBUG:ThematicAtlases.test:fake debug" not in output.out
    assert output.err == ""


def test_collect_datasets_accepts_verbose_after_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["collect-datasets", "--verbose", "--query", "fibrosis"]) == 0

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

    assert "INFO:ThematicAtlases.atlas:Atlas create_atlas progress stage=collect-datasets" in output.out
    assert "INFO:ThematicAtlases.test:fake info" in output.out
    assert output.err == ""


def test_create_atlas_accepts_verbose_after_command(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    assert main(["create-atlas", "--verbose", "--query", "fibrosis"]) == 0

    output = capsys.readouterr()
    assert "INFO:ThematicAtlases.atlas:Atlas create_atlas progress stage=collect-datasets" in output.out
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
                "collect-datasets",
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


def test_collect_datasets_accepts_log_file_after_command(
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
                "collect-datasets",
                "--verbose",
                "--log-file",
                str(log_file),
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
    assert "INFO:ThematicAtlases.atlas:Atlas create_atlas progress stage=collect-datasets" in log_text
    assert "INFO:ThematicAtlases.test:fake info" in log_text


def test_double_verbose_enables_debug_logging(tmp_path) -> None:
    log_file = tmp_path / "atlas.log"

    _configure_logging(verbosity=2, log_file=str(log_file))
    logging.getLogger("ThematicAtlases.test").debug("debug enabled")

    assert "DEBUG:ThematicAtlases.test:debug enabled" in log_file.read_text(
        encoding="utf-8"
    )


def test_collect_datasets_passes_options_to_atlas(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    class RecordingAtlas:
        calls: list[dict] = []

        def __init__(self, metadata: dict):
            pass

        def collect_datasets(
            self,
            query=None,
            file=None,
            out=None,
            theme=None,
            review_filter="none",
            metadata_repositories=None,
            max_publications=None,
            reviewer=None,
            collect_metadata=True,
            dev_out_dir=".dev",
        ):
            self.__class__.calls.append(
                {
                    "query": query,
                    "file": file,
                    "out": out,
                    "theme": theme,
                    "review_filter": review_filter,
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "reviewer": reviewer,
                    "collect_metadata": collect_metadata,
                    "dev_out_dir": dev_out_dir,
                }
            )
            return {"accessions": [], "publication_texts": {}}

    RecordingAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingAtlas)

    assert (
        main(
            [
                "collect-datasets",
                "--query",
                "fibrosis",
                "--theme",
                "theme",
                "--review-filter",
                "not-relevant",
                "--metadata-repository",
                "geo",
                "--metadata-repository",
                "arrayexpress",
                "--max-publications",
                "25",
                "--skip-metadata",
                "--dev-out-dir",
                ".dev/custom",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert RecordingAtlas.calls == [
        {
            "query": ["fibrosis"],
            "file": None,
            "out": None,
            "theme": "theme",
            "review_filter": "not_relevant",
            "metadata_repositories": ["geo", "arrayexpress"],
            "max_publications": 25,
            "reviewer": None,
            "collect_metadata": False,
            "dev_out_dir": ".dev/custom",
        }
    ]


def test_collect_datasets_no_dev_output_passes_none_to_atlas(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    class RecordingAtlas:
        calls: list[dict] = []

        def __init__(self, metadata: dict):
            pass

        def collect_datasets(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return {"accessions": [], "publication_texts": {}}

    RecordingAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingAtlas)

    assert main(["collect-datasets", "--query", "fibrosis", "--no-dev-output"]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert RecordingAtlas.calls[0]["dev_out_dir"] is None


def test_collect_datasets_rejects_non_positive_max_publications() -> None:
    with pytest.raises(SystemExit):
        main(["collect-datasets", "--query", "fibrosis", "--max-publications", "0"])


def test_create_atlas_passes_theme_and_review_filter_to_atlas(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    class RecordingAtlas:
        calls: list[dict] = []

        def __init__(self, metadata: dict):
            pass

        def create_atlas(
            self,
            query=None,
            file=None,
            out=None,
            theme=None,
            review_filter="none",
            metadata_repositories=None,
            max_publications=None,
            reviewer=None,
            collect_metadata=True,
            dev_out_dir=".dev",
            harmonization_details_out=None,
        ):
            self.__class__.calls.append(
                {
                    "query": query,
                    "file": file,
                    "out": out,
                    "theme": theme,
                    "review_filter": review_filter,
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "reviewer": reviewer,
                    "collect_metadata": collect_metadata,
                    "dev_out_dir": dev_out_dir,
                    "harmonization_details_out": harmonization_details_out,
                }
            )
            return {"accessions": [], "publication_texts": {}}

    RecordingAtlas.calls = []
    monkeypatch.setattr(cli_module, "Atlas", RecordingAtlas)

    assert (
        main(
            [
                "create-atlas",
                "--query",
                "fibrosis",
                "--theme",
                "fibrosis theme",
                "--review-filter",
                "not-relevant",
                "--metadata-repository",
                "arrayexpress",
                "--max-publications",
                "25",
                "--skip-metadata",
                "--no-dev-output",
                "--harmonization-details-out",
                "harmonization.json",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert RecordingAtlas.calls == [
        {
            "query": ["fibrosis"],
            "file": None,
            "out": None,
            "theme": "fibrosis theme",
            "review_filter": "not_relevant",
            "metadata_repositories": ["arrayexpress"],
            "max_publications": 25,
            "reviewer": None,
            "collect_metadata": False,
            "dev_out_dir": None,
            "harmonization_details_out": "harmonization.json",
        }
    ]


def test_harmonize_datasets_transforms_file_without_stdout(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    infile = tmp_path / "datasets.json"
    outfile = tmp_path / "harmonized.json"
    details = tmp_path / "details.json"
    infile.write_text('{"accessions": [], "publication_texts": {}}', encoding="utf-8")

    class RecordingAtlas:
        calls = []

        def __init__(self, metadata):
            pass

        def harmonize_datasets(self, datasets, harmonization_details_out=None):
            self.__class__.calls.append((datasets, harmonization_details_out))
            return {**datasets, "harmonized": True}

    monkeypatch.setattr(cli_module, "Atlas", RecordingAtlas)

    assert main([
        "harmonize-datasets",
        "--file",
        str(infile),
        "--out",
        str(outfile),
        "--harmonization-details-out",
        str(details),
    ]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""
    assert RecordingAtlas.calls == [
        ({"accessions": [], "publication_texts": {}}, str(details))
    ]
    assert json.loads(outfile.read_text(encoding="utf-8"))["harmonized"] is True


def test_harmonize_datasets_accepts_verbose_after_command(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch,
) -> None:
    infile = tmp_path / "datasets.json"
    outfile = tmp_path / "harmonized.json"
    infile.write_text('{"accessions": []}', encoding="utf-8")

    class RecordingAtlas:
        def __init__(self, metadata):
            pass

        def harmonize_datasets(self, datasets, harmonization_details_out=None):
            return datasets

    monkeypatch.setattr(cli_module, "Atlas", RecordingAtlas)

    assert main([
        "harmonize-datasets",
        "--verbose",
        "--file",
        str(infile),
        "--out",
        str(outfile),
    ]) == 0

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_unknown_command_exits_with_argparse_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-command"])

    assert exc_info.value.code == 2


def test_unknown_command_argument_exits_with_argparse_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["collect-datasets", "--query", "fibrosis", "--not-an-option"])

    assert exc_info.value.code == 2
