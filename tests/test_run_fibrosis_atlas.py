import json
import logging
from pathlib import Path

import pytest

import run_fibrosis_atlas as script


def test_requires_repository_virtual_environment(tmp_path) -> None:
    root = tmp_path / "project"
    executable = root / "other" / "python"

    with pytest.raises(RuntimeError, match=r"\.env/bin/python"):
        script.require_project_venv(root=root, executable=executable)


def test_configure_logging_enables_debug_console_and_file(tmp_path) -> None:
    path = tmp_path / "run.log"

    script.configure_logging(path)

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert any(isinstance(handler, logging.FileHandler) for handler in root.handlers)
    assert any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root.handlers
    )


def test_full_fibrosis_run_wires_fixed_configuration(tmp_path, monkeypatch, capsys) -> None:
    calls = {}

    class RecordingStore:
        def __init__(self, storage_dir):
            calls["storage_dir"] = storage_dir
            self.ontology_frameworks = {"efo": {}, "snomed": {}}

        def configure_framework(self, name, *, remove=False):
            calls["configure_framework"] = (name, remove)
            if remove:
                del self.ontology_frameworks[name]

    class RecordingPreflight:
        pass

    class RecordingAtlas:
        def __init__(
            self, metadata, ontostore, cache_ontologies, credential_checker
        ):
            calls["atlas"] = {
                "metadata": metadata,
                "ontostore": ontostore,
                "cache_ontologies": cache_ontologies,
                "credential_checker": credential_checker,
            }

        def create_atlas(self, **kwargs):
            calls["create_atlas"] = kwargs
            return {"accessions": [], "publication_texts": {}}

    theme = tmp_path / "theme.txt"
    theme.write_text("fibrosis theme", encoding="utf-8")
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "THEME_FILE", theme)
    monkeypatch.setattr(script, "OUTPUT_DIR", tmp_path / ".out")
    monkeypatch.setattr(script, "OntoStore", RecordingStore)
    monkeypatch.setattr(script, "GoogleCredentialPreflight", RecordingPreflight)
    monkeypatch.setattr(script, "Atlas", RecordingAtlas)
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(script, "configure_logging", lambda path: None)

    assert script.main() == 0

    assert calls["configure_framework"] == ("snomed", True)
    assert "snomed" not in calls["atlas"]["ontostore"].ontology_frameworks
    assert calls["atlas"]["cache_ontologies"] is True
    assert calls["create_atlas"] == {
        "query": None,
        "file": None,
        "out": str(tmp_path / ".out" / "fibrosis_atlas.json"),
        "theme": "fibrosis theme",
        "review_filter": "not_relevant",
        "metadata_repositories": ["geo"],
        "max_publications": 50,
        "collect_metadata": True,
        "dev_trace": True,
        "dev_out_dir": str(tmp_path / ".out" / "dev_trace"),
        "harmonization_details_out": str(
            tmp_path / ".out" / "fibrosis_harmonization_details.json"
        ),
        "generate_queries": True,
        "max_generated_queries": 3,
        "harmonization_options": {
            "strategy": "websearch",
            "lookup_llm_judge": True,
            "lookup_llm_threshold": 2,
            "search_llm_judge": True,
            "llm": True,
        },
    }

    displayed = json.loads(capsys.readouterr().out)
    assert displayed["max_publications"] == 50
    assert displayed["removed_ontology_frameworks"] == ["snomed"]
    assert displayed["dev_trace"] is True
