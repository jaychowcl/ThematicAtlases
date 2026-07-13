import json
import logging
from pathlib import Path

import pytest

import run_fibrosis_discovery as script


def test_requires_repository_virtual_environment(tmp_path) -> None:
    root = tmp_path / "project"
    with pytest.raises(RuntimeError, match=r"\.env/bin/python"):
        script.require_project_venv(root=root, executable=root / "other" / "python")


def test_configure_logging_enables_debug_console_and_file(tmp_path) -> None:
    script.configure_logging(tmp_path / "discovery.log")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert any(isinstance(handler, logging.FileHandler) for handler in root.handlers)
    assert any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root.handlers
    )


def test_discovery_runs_search_and_review_without_harmonization(
    tmp_path, monkeypatch, capsys
) -> None:
    calls = {}

    class RecordingPreflight:
        pass

    class RecordingAtlas:
        def __init__(self, metadata, credential_checker):
            calls["atlas"] = {
                "metadata": metadata,
                "credential_checker": credential_checker,
            }

        def collect_datasets(self, **kwargs):
            calls["collect_datasets"] = kwargs
            result = {"accessions": [], "publication_texts": {}}
            Path(kwargs["out"]).write_text(json.dumps(result), encoding="utf-8")
            return result

        def create_atlas(self, **kwargs):
            raise AssertionError("discovery must not create or harmonize an atlas")

        def harmonize_datasets(self, **kwargs):
            raise AssertionError("discovery must not harmonize datasets")

    theme = tmp_path / "theme.txt"
    theme.write_text("fibrosis theme", encoding="utf-8")
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "THEME_FILE", theme)
    monkeypatch.setattr(script, "OUTPUT_DIR", tmp_path / ".out")
    monkeypatch.setattr(script, "Atlas", RecordingAtlas)
    monkeypatch.setattr(script, "GoogleCredentialPreflight", RecordingPreflight)
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(script, "configure_logging", lambda path: None)

    assert script.main() == 0

    assert calls["collect_datasets"] == {
        "query": None,
        "file": None,
        "out": str(tmp_path / ".out" / "fibrosis_discovery.json"),
        "theme": "fibrosis theme",
        "review_filter": "not_relevant",
        "metadata_repositories": ["geo"],
        "max_publications": 1000,
        "collect_metadata": True,
        "generate_queries": True,
        "max_generated_queries": 3,
    }
    assert not hasattr(calls["atlas"]["credential_checker"], "ontology_frameworks")
    summary = json.loads(
        (tmp_path / ".out" / "fibrosis_discovery.summary.json").read_text()
    )
    assert summary["counts"] == {
        "accessions": 0,
        "publications": 0,
        "publication_texts": 0,
    }
    displayed = json.loads(capsys.readouterr().out)
    assert displayed["max_publications"] == 1000
    assert displayed["harmonization"] is False
    assert displayed["collect_metadata"] is True
