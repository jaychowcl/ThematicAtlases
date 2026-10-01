import hashlib
import json

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.domain import AtlasDocument
from ThematicAtlases.run_store import AtlasRunStore
from ThematicAtlases import cli_atlas
from ThematicAtlases.harmonizer import AtlasHarmonizer
from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    ValidationStatus,
)


SUCCESS_STATUS = OperationStatusV2(
    execution=ExecutionStatus.SUCCEEDED,
    completeness=CompletenessStatus.COMPLETE,
    evidence_confidence=EvidenceConfidence.HIGH,
    validation=ValidationStatus.VALID,
    publication=PublicationDisposition.PUBLISHABLE,
    terminal_reason="harmonization_complete",
).to_dict()


def _run_dir(tmp_path, manifest, *, run_id="run-1"):
    run_dir = tmp_path / "trace" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "00_run_manifest.json").write_text(
        json.dumps({"command": "create-atlas", "run_id": run_id, "workflow_checkpoint_contract": "2.0", **manifest}),
        encoding="utf-8",
    )
    store = AtlasRunStore(run_dir / "atlas_run.sqlite3")
    store.create_run(run_id, f"atlas-{run_id}", "1.0", manifest)
    store.set_run_status(run_id, "running")
    return run_dir


def test_resume_cli_forwards_retry_selections(monkeypatch, tmp_path) -> None:
    calls = []

    class RecordingAtlas:
        def __init__(self, metadata):
            pass

        def resume(self, **kwargs):
            calls.append(kwargs)
            return {"accessions": [], "publication_texts": {}}

    monkeypatch.setattr(cli_atlas, "Atlas", RecordingAtlas)
    decisions = {"schema_version": "1.0", "run_id": "run-7"}
    decision_file = tmp_path / "review.json"
    decision_file.write_text(json.dumps(decisions), encoding="utf-8")

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
            "--review-decisions-file",
            str(decision_file),
        ]
    ) == 0
    assert calls == [
        {
            "dev_out_dir": "trace",
            "run_id": "run-7",
                "out": "atlas.json",
                "stop_before_review": False,
                "stop_after": None,
                "retry_stages": ["thematic_review"],
            "retry_items": {"harmonization": ["work-1"]},
            "retry_degraded_stages": ["target_checker"],
            "review_decisions": decisions,
        }
    ]


def test_resume_rejects_review_decisions_for_a_different_run_before_mutation(
    tmp_path,
) -> None:
    run_dir = _run_dir(tmp_path, {"atlas_out": None, "theme": None})
    (run_dir / "06_final_atlas.json").write_text(
        json.dumps({"accessions": [], "publication_texts": {}}),
        encoding="utf-8",
    )
    store = AtlasRunStore(run_dir / "atlas_run.sqlite3")
    before = store.get_run("run-1")

    with pytest.raises(ValueError, match="belongs to run 'run-2'"):
        Atlas(metadata={}).resume(
            dev_out_dir=str(tmp_path / "trace"),
            run_id="run-1",
            review_decisions={
                "schema_version": "1.0",
                "run_id": "run-2",
                "source_fingerprint": "a" * 64,
                "decisions": [],
            },
        )

    assert AtlasRunStore(run_dir / "atlas_run.sqlite3").get_run("run-1") == before




def test_invalid_retry_selection_is_atomic(tmp_path) -> None:
    final = {"accessions": [{"datalink_id": "GSE-final"}], "publication_texts": {}}
    run_dir = _run_dir(tmp_path, {"atlas_out": None, "theme": None})
    final_path = run_dir / "06_final_atlas.json"
    final_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    store = CheckpointStore(run_dir / "atlas_run.sqlite3")
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
