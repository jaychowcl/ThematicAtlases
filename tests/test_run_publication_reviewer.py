import json

import pytest

import run_publication_reviewer as script


def test_requires_repository_virtual_environment(tmp_path) -> None:
    root = tmp_path / "project"
    with pytest.raises(RuntimeError, match=r"\.env/bin/python"):
        script.require_project_venv(root=root, executable=root / "other" / "python")


def test_runner_reviews_one_snapshot_of_existing_trace(
    tmp_path, monkeypatch, capsys
) -> None:
    calls = {}

    class RecordingPreflight:
        def check(self):
            calls["credential_check"] = True

    class RecordingReviewer:
        def resume(
            self,
            trace_dir,
            *,
            theme=None,
            strategy="direct",
            allow_theme_override=False,
        ):
            calls["resume"] = {
                "trace_dir": trace_dir,
                "theme": theme,
                "strategy": strategy,
                "allow_theme_override": allow_theme_override,
            }
            return {
                "accessions": [{"datalink_id": "GSE1"}],
                "publication_texts": {"1": {"text": "reviewed"}},
            }

    trace_dir = tmp_path / "active-trace"
    theme_file = tmp_path / "theme.txt"
    theme_file.write_text("fibrosis theme", encoding="utf-8")
    monkeypatch.setattr(script, "PublicationTextReviewer", RecordingReviewer)
    monkeypatch.setattr(script, "GoogleCredentialPreflight", RecordingPreflight)
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(script, "configure_logging", lambda verbosity: None)

    assert script.main(
        [str(trace_dir), "--theme-file", str(theme_file), "-v"]
    ) == 0

    assert calls == {
        "credential_check": True,
        "resume": {
            "trace_dir": trace_dir,
            "theme": "fibrosis theme",
            "strategy": "direct",
            "allow_theme_override": False,
        },
    }
    assert json.loads(capsys.readouterr().out) == {
        "trace_dir": str(trace_dir),
        "accessions": 1,
        "publication_texts": 1,
        "progress_artifact": str(trace_dir / "resume_review_progress.json"),
    }


def test_runner_can_select_legacy_review_strategy(tmp_path, monkeypatch) -> None:
    calls = {}

    class RecordingReviewer:
        def resume(self, trace_dir, **kwargs):
            strategy = kwargs.get("strategy", "direct")
            calls["strategy"] = strategy
            return {"accessions": [], "publication_texts": {}}

    monkeypatch.setattr(script, "PublicationTextReviewer", RecordingReviewer)
    monkeypatch.setattr(script, "GoogleCredentialPreflight", lambda: type(
        "Preflight", (), {"check": lambda self: None}
    )())
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(script, "configure_logging", lambda verbosity: None)

    assert script.main(
        [str(tmp_path / "trace"), "--strategy", "evidence_then_judgement"]
    ) == 0
    assert calls["strategy"] == "evidence_then_judgement"


def test_runner_can_explicitly_override_manifest_theme(tmp_path, monkeypatch) -> None:
    calls = {}

    class RecordingReviewer:
        def resume(self, trace_dir, **kwargs):
            calls.update(kwargs)
            return {"accessions": [], "publication_texts": {}}

    theme_file = tmp_path / "theme.txt"
    theme_file.write_text("current fibrosis theme", encoding="utf-8")
    monkeypatch.setattr(script, "PublicationTextReviewer", RecordingReviewer)
    monkeypatch.setattr(script, "GoogleCredentialPreflight", lambda: type(
        "Preflight", (), {"check": lambda self: None}
    )())
    monkeypatch.setattr(script, "require_project_venv", lambda **kwargs: None)
    monkeypatch.setattr(script, "configure_logging", lambda verbosity: None)

    assert script.main([
        str(tmp_path / "trace"),
        "--theme-file",
        str(theme_file),
        "--allow-theme-override",
    ]) == 0
    assert calls["theme"] == "current fibrosis theme"
    assert calls["allow_theme_override"] is True
