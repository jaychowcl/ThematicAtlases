import json
from pathlib import Path

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases import run_archive
from ThematicAtlases.run_archive import workflow_activity_lock
from ThematicAtlases.trace import DevTraceWriter


def _trace(root: Path, run_id: str, atlas_out: Path) -> Path:
    trace = DevTraceWriter(
        str(root),
        run_id,
        {
            "command": "collect-datasets",
            "atlas_out": str(atlas_out),
            "created_at": run_id,
        },
    )
    trace.checkpoint_store.put(
        "datalinks",
        f"MED:{run_id}",
        1,
        "available",
        payload={"rows": []},
    )
    return trace.directory


def test_archive_existing_runs_moves_all_traces_and_latest_artifacts(tmp_path) -> None:
    active = tmp_path / "dev_trace_discovery"
    archive_root = tmp_path / "previous_runs"
    output = tmp_path / "fibrosis_discovery.json"
    summary = tmp_path / "fibrosis_discovery.summary.json"
    log = tmp_path / "fibrosis_discovery.log"
    first = _trace(active, "20260713T100000", output)
    second = _trace(active, "20260713T110000", output)
    output.write_text('{"accessions": []}', encoding="utf-8")
    summary.write_text('{"counts": {}}', encoding="utf-8")
    log.write_text("finished\n", encoding="utf-8")

    archived = Atlas.archive_existing_runs(
        dev_out_dir=active,
        archive_root=archive_root,
        workflow="fibrosis_discovery",
        artifact_paths=[output, summary, log],
    )

    assert archived == [
        archive_root / "fibrosis_discovery" / "20260713T100000",
        archive_root / "fibrosis_discovery" / "20260713T110000",
    ]
    assert not first.exists()
    assert not second.exists()
    assert not output.exists()
    assert not summary.exists()
    assert not log.exists()
    assert (archived[0] / "resume_state.sqlite").exists()
    assert not (archived[0] / "artifacts").exists()
    assert (archived[1] / "artifacts" / output.name).read_text() == '{"accessions": []}'
    archive_manifest = json.loads(
        (archived[1] / "archive_manifest.json").read_text()
    )
    assert archive_manifest["workflow"] == "fibrosis_discovery"
    assert archive_manifest["run_id"] == "20260713T110000"
    assert archive_manifest["source_trace"] == str(second)
    assert archive_manifest["artifacts"][0]["sha256"]
    relocated_manifest = json.loads(
        (archived[1] / "00_run_manifest.json").read_text()
    )
    assert relocated_manifest["atlas_out"] == str(
        archived[1] / "artifacts" / output.name
    )


def test_archive_existing_runs_is_noop_without_runs_or_artifacts(tmp_path) -> None:
    assert Atlas.archive_existing_runs(
        dev_out_dir=tmp_path / "active",
        archive_root=tmp_path / "archive",
        workflow="fibrosis_discovery",
        artifact_paths=[],
    ) == []


def test_archive_existing_runs_refuses_destination_collision(tmp_path) -> None:
    active = tmp_path / "active"
    output = tmp_path / "out.json"
    source = _trace(active, "20260713T100000", output)
    destination = tmp_path / "archive" / "discovery" / source.name
    destination.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="archive destination already exists"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[output],
        )

    assert source.exists()


def test_archive_existing_runs_refuses_active_workflow(tmp_path) -> None:
    active = tmp_path / "active"
    output = tmp_path / "out.json"
    source = _trace(active, "20260713T100000", output)

    with workflow_activity_lock(active, exclusive=False):
        with pytest.raises(RuntimeError, match="workflow is active"):
            Atlas.archive_existing_runs(
                dev_out_dir=active,
                archive_root=tmp_path / "archive",
                workflow="discovery",
                artifact_paths=[output],
            )

    assert source.exists()


def test_archive_existing_runs_preserves_orphan_artifacts(tmp_path) -> None:
    artifact = tmp_path / "fibrosis_discovery.log"
    artifact.write_text("orphaned log\n", encoding="utf-8")

    archived = Atlas.archive_existing_runs(
        dev_out_dir=tmp_path / "active",
        archive_root=tmp_path / "archive",
        workflow="discovery",
        artifact_paths=[artifact],
    )

    assert len(archived) == 1
    assert archived[0].name.startswith("orphan-")
    assert (archived[0] / "artifacts" / artifact.name).read_text() == "orphaned log\n"
    assert not artifact.exists()


def test_archive_rejects_archive_root_nested_inside_active_root(tmp_path) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")

    with pytest.raises(ValueError, match="archive_root must not be inside dev_out_dir"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=active / "nested-archive",
            workflow="discovery",
        )

    assert source.exists()
    assert not (active / "nested-archive" / "discovery" / "run-1").exists()


def test_archive_rejects_trace_and_artifact_symlinks(tmp_path) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")
    real = tmp_path / "real.txt"
    real.write_text("real", encoding="utf-8")
    (source / "linked.txt").symlink_to(real)

    with pytest.raises(ValueError, match="trace must not contain symlinks"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
        )

    assert source.exists()
    assert not (tmp_path / "archive" / "discovery" / "run-1").exists()

    (source / "linked.txt").unlink()
    linked_artifact = tmp_path / "linked-artifact.txt"
    linked_artifact.symlink_to(real)
    with pytest.raises(ValueError, match="artifact must be a regular file"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[linked_artifact],
        )
    assert source.exists()


def test_archive_rejects_duplicate_artifact_basenames_without_publishing(tmp_path) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")
    first = tmp_path / "a" / "result.json"
    second = tmp_path / "b" / "result.json"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    with pytest.raises(ValueError, match="basenames must be unique"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[first, second],
        )

    assert source.exists() and first.exists() and second.exists()
    assert not (tmp_path / "archive" / "discovery" / "run-1").exists()


def test_archive_rejects_corrupt_sqlite_without_publishing(tmp_path) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")
    (source / "resume_state.sqlite").write_bytes(b"not a sqlite database")

    with pytest.raises(Exception, match="database|encrypted"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
        )

    assert source.exists()
    assert not (tmp_path / "archive" / "discovery" / "run-1").exists()


def test_archive_copy_failure_retains_sources_and_publishes_nothing(tmp_path, monkeypatch) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")

    def fail_copy(*args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(run_archive.shutil, "copytree", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[artifact],
        )

    assert source.exists() and artifact.exists()
    assert not (tmp_path / "archive" / "discovery" / "run-1").exists()


def test_archive_publish_failure_retains_sources_and_publishes_nothing(tmp_path, monkeypatch) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")
    destination = tmp_path / "archive" / "discovery" / "run-1"
    original_replace = run_archive.os.replace

    def fail_publish(source_path, destination_path):
        if Path(destination_path) == destination:
            raise OSError("publish failed")
        return original_replace(source_path, destination_path)

    monkeypatch.setattr(run_archive.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[artifact],
        )

    assert source.exists() and artifact.exists()
    assert not destination.exists()
