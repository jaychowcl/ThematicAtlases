import json
import logging

import pytest

import run_accession_metadata_collector as script


def test_requires_repository_virtual_environment(tmp_path) -> None:
    root = tmp_path / "project"
    with pytest.raises(RuntimeError, match=r"\.env/bin/python"):
        script.require_project_venv(root=root, executable=root / "other" / "python")


def test_runner_collects_one_metadata_snapshot(tmp_path, monkeypatch, capsys) -> None:
    calls = {}

    class RecordingCollector:
        def resume_metadata(self, trace_dir):
            calls["trace_dir"] = trace_dir
            return {
                "accessions": [{"datalink_id": "GSE1"}],
                "publication_texts": {},
            }

    trace_dir = tmp_path / "trace"
    monkeypatch.setattr(script, "AtlasCollector", RecordingCollector)
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(
        script,
        "configure_logging",
        lambda verbosity, path: calls.update(log_path=path),
    )

    assert script.main([str(trace_dir), "-v"]) == 0
    assert calls == {
        "trace_dir": trace_dir,
        "log_path": trace_dir / "resume_metadata.log",
    }
    assert json.loads(capsys.readouterr().out) == {
        "trace_dir": str(trace_dir),
        "accessions": 1,
        "progress_artifact": str(trace_dir / "resume_metadata_progress.json"),
        "log_path": str(trace_dir / "resume_metadata.log"),
    }


def test_configure_logging_appends_to_trace_log(tmp_path) -> None:
    path = tmp_path / "resume_metadata.log"
    script.configure_logging(1, path)
    logging.getLogger("metadata-test").info("snapshot stats accessions=3")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "snapshot stats accessions=3" in path.read_text(encoding="utf-8")
