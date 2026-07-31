import hashlib
import json

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases import cli_atlas
from ThematicAtlases.harmonizer import AtlasHarmonizer


def _run_dir(tmp_path, manifest, *, run_id="run-1"):
    run_dir = tmp_path / "trace" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps({"command": "create-atlas", "run_id": run_id, **manifest}),
        encoding="utf-8",
    )
    return run_dir


def test_resume_cli_forwards_retry_selections(monkeypatch) -> None:
    calls = []

    class RecordingAtlas:
        def __init__(self, metadata):
            pass

        def resume(self, **kwargs):
            calls.append(kwargs)
            return {"accessions": [], "publication_texts": {}}

    monkeypatch.setattr(cli_atlas, "Atlas", RecordingAtlas)

    assert cli_atlas.main(
        [
            "resume",
            "--dev-out-dir",
            "trace",
            "--run-id",
            "run-7",
            "--out",
            "atlas.json",
            "--retry-stage",
            "thematic_review",
            "--retry-item",
            "harmonization:work-1",
            "--retry-degraded-stage",
            "target_checker",
        ]
    ) == 0
    assert calls == [
        {
            "dev_out_dir": "trace",
            "run_id": "run-7",
            "out": "atlas.json",
            "stop_before_review": False,
            "retry_stages": ["thematic_review"],
            "retry_items": {"harmonization": ["work-1"]},
            "retry_degraded_stages": ["target_checker"],
        }
    ]


def test_resume_retries_only_selected_harmonization_item(tmp_path) -> None:
    datasets = {
        "accessions": [
            {"datalink_id": "GSE1", "accession_metadata": {"value": "one"}},
            {"datalink_id": "GSE2", "accession_metadata": {"value": "two"}},
        ],
        "publication_texts": {},
    }
    run_dir = _run_dir(tmp_path, {"theme": None, "review_filter": "none", "harmonization_options": {}})
    (run_dir / "02_reviewed_datasets.json").write_text(json.dumps(datasets), encoding="utf-8")
    (run_dir / "06_final_atlas.json").write_text(json.dumps({"stale": True}), encoding="utf-8")
    calls = []

    class RecordingOntology:
        def harmonize_miniml_json(self, **kwargs):
            calls.append(kwargs["miniml_json"]["value"])
            return {
                "miniml_json": {**kwargs["miniml_json"], "retried": True},
                "harmonization_targets": [],
                "workflow": "retry",
                "target_paths": [],
            }

    harmonizer = AtlasHarmonizer(ontology_harmonizer=RecordingOntology())
    store = CheckpointStore(run_dir / "resume_state.sqlite")
    work_keys = []
    for ordinal, record in enumerate(datasets["accessions"], start=1):
        key = harmonizer._work_key(record["accession_metadata"], None, {})
        work_key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        work_keys.append(work_key)
        store.put("harmonization", work_key, ordinal, "terminal_error", error=f"bad-{ordinal}")

    result = Atlas(metadata={}, harmonizer=harmonizer).resume(
        dev_out_dir=str(tmp_path / "trace"),
        run_id="run-1",
        retry_items={"harmonization": [work_keys[0]]},
    )

    assert calls == ["one"]
    assert result["accessions"][0]["accession_metadata"]["retried"] is True
    assert result["accessions"][1]["ontology_harmonization_error"] == "bad-2"
    assert store.get("harmonization", work_keys[0])["status"] == "available"
    assert store.get("harmonization", work_keys[1])["status"] == "terminal_error"


def test_invalid_retry_selection_is_atomic(tmp_path) -> None:
    final = {"accessions": [{"datalink_id": "GSE-final"}], "publication_texts": {}}
    run_dir = _run_dir(tmp_path, {"atlas_out": None, "theme": None})
    final_path = run_dir / "06_final_atlas.json"
    final_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    store = CheckpointStore(run_dir / "resume_state.sqlite")
    for ordinal, key in enumerate(("one", "two"), start=1):
        store.put(
            "harmonization",
            key,
            ordinal,
            "available",
            payload={"miniml_json": {"key": key}},
        )
        store.put(
            "harmonization",
            key,
            ordinal,
            "terminal_error",
            error=f"bad {key}",
        )
    before_final = final_path.read_bytes()
    before_rows = store.items("harmonization")
    before_history = {
        key: store.history("harmonization", key) for key in ("one", "two")
    }
    collaborator_calls = []

    class UnexpectedCollaborator:
        def __getattr__(self, name):
            collaborator_calls.append(name)
            raise AssertionError(f"invalid retry must not call collaborator method {name}")

    atlas = Atlas(
        metadata={},
        collector=UnexpectedCollaborator(),
        filterer=UnexpectedCollaborator(),
        harmonizer=UnexpectedCollaborator(),
    )

    with pytest.raises(ValueError, match="checkpoint item was not found"):
        atlas.resume(
            dev_out_dir=str(tmp_path / "trace"),
            run_id="run-1",
            retry_items={"harmonization": ["one", "missing"]},
        )

    assert final_path.read_bytes() == before_final
    assert store.items("harmonization") == before_rows
    assert {
        key: store.history("harmonization", key) for key in ("one", "two")
    } == before_history
    assert collaborator_calls == []


def test_resume_reuses_final_without_calling_collaborators(tmp_path) -> None:
    final = {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}}
    run_dir = _run_dir(tmp_path, {"atlas_out": None, "theme": None})
    (run_dir / "06_final_atlas.json").write_text(json.dumps(final), encoding="utf-8")

    class Unexpected:
        def __getattr__(self, name):
            raise AssertionError(f"final reuse must not access collaborator method {name}")

    result = Atlas(
        metadata={}, collector=Unexpected(), filterer=Unexpected(), harmonizer=Unexpected()
    ).resume(dev_out_dir=str(tmp_path / "trace"), run_id="run-1")

    assert result == final
    assert json.loads((run_dir / "07_summary.json").read_text(encoding="utf-8"))["counts"] == {
        "accessions": 1,
        "publications": 0,
        "publication_texts": 0,
    }
