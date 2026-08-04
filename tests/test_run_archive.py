import json
from pathlib import Path
import sqlite3

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases import run_archive
from ThematicAtlases.run_archive import ArchiveDurabilityError, workflow_activity_lock
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
    assert (archived[0] / "atlas_run.sqlite3").exists()
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


def test_archive_omits_transient_sidecars_and_preserves_healthy_database(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")
    durable = source / "durable.json"
    durable.write_text('{"preserved": true}', encoding="utf-8")
    original_prepare = run_archive._prepare_checkpoint_database

    def prepare_with_sidecars(database_path):
        original_prepare(database_path)
        Path(f"{database_path}-wal").write_bytes(b"")
        Path(f"{database_path}-shm").write_bytes(b"transient shared memory")

    monkeypatch.setattr(run_archive, "_prepare_checkpoint_database", prepare_with_sidecars)

    archived = Atlas.archive_existing_runs(
        dev_out_dir=active,
        archive_root=tmp_path / "archive",
        workflow="discovery",
    )[0]

    assert not source.exists()
    assert (archived / "durable.json").read_text(encoding="utf-8") == (
        '{"preserved": true}'
    )
    assert not (archived / "atlas_run.sqlite3-wal").exists()
    assert not (archived / "atlas_run.sqlite3-shm").exists()
    with sqlite3.connect(archived / "atlas_run.sqlite3") as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        row = connection.execute(
            "SELECT payload FROM checkpoint_items "
            "WHERE stage = ? AND item_key = ?",
            ("datalinks", "MED:run-1"),
        ).fetchone()
    assert row is not None
    assert json.loads(row[0]) == {"rows": []}


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


def test_archive_rejects_a_symlinked_trace_root(tmp_path) -> None:
    real_active = tmp_path / "real-active"
    source = _trace(real_active, "run-1", tmp_path / "out.json")
    active = tmp_path / "active"
    active.mkdir()
    (active / "run-1").symlink_to(source, target_is_directory=True)

    with pytest.raises(ValueError, match="trace must not be a symlink"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
        )

    assert source.exists()
    assert not (tmp_path / "archive" / "discovery" / "run-1").exists()


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
    (source / "atlas_run.sqlite3").write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError, match="database|encrypted"):
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


def test_archive_fsyncs_published_directory_before_removing_sources(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")
    calls = []
    original_fsync_directory = run_archive._fsync_directory

    def record_fsync(path):
        calls.append(Path(path))
        return original_fsync_directory(path)

    monkeypatch.setattr(run_archive, "_fsync_directory", record_fsync)

    destination = Atlas.archive_existing_runs(
        dev_out_dir=active,
        archive_root=tmp_path / "archive",
        workflow="discovery",
        artifact_paths=[artifact],
    )[0]

    assert destination in calls
    assert destination.parent in calls
    assert not source.exists() and not artifact.exists()


def test_archive_cleanup_failure_reports_published_archive_and_retains_artifact(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")
    destination = tmp_path / "archive" / "discovery" / "run-1"
    original_rmtree = run_archive.shutil.rmtree

    def fail_source_cleanup(path, *args, **kwargs):
        if Path(path) == source:
            raise OSError("cleanup failed")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(run_archive.shutil, "rmtree", fail_source_cleanup)

    with pytest.raises(ArchiveDurabilityError, match="archive was published") as caught:
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[artifact],
        )

    assert caught.value.destination == destination
    assert destination.exists()
    assert source.exists() and artifact.exists()


def test_archive_publish_fsync_failure_reports_destination_and_retains_sources(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")
    destination = tmp_path / "archive" / "discovery" / "run-1"
    original_fsync_directory = run_archive._fsync_directory

    def fail_published_fsync(path):
        if Path(path) == destination:
            raise OSError("directory fsync failed")
        return original_fsync_directory(path)

    monkeypatch.setattr(run_archive, "_fsync_directory", fail_published_fsync)

    with pytest.raises(ArchiveDurabilityError, match="archive was published") as caught:
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
            artifact_paths=[artifact],
        )

    assert caught.value.destination == destination
    assert destination.exists()
    assert source.exists() and artifact.exists()


def test_archive_publish_failure_ignores_transient_sqlite_sidecar_changes(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    artifact = tmp_path / "out.json"
    source = _trace(active, "run-1", artifact)
    artifact.write_text("{}", encoding="utf-8")
    destination = tmp_path / "archive" / "discovery" / "run-1"
    original_prepare = run_archive._prepare_checkpoint_database
    original_copytree = run_archive.shutil.copytree
    original_replace = run_archive.os.replace

    def prepare_with_sidecars(database_path):
        original_prepare(database_path)
        Path(f"{database_path}-wal").write_bytes(b"")
        Path(f"{database_path}-shm").write_bytes(b"initial shared memory")

    def copy_while_sidecars_change(source_path, destination_path, *args, **kwargs):
        result = original_copytree(source_path, destination_path, *args, **kwargs)
        Path(f"{source_path / 'atlas_run.sqlite3'}-wal").unlink()
        Path(f"{source_path / 'atlas_run.sqlite3'}-shm").write_bytes(
            b"changed shared memory"
        )
        return result

    def fail_publish(source_path, destination_path):
        if Path(destination_path) == destination:
            raise OSError("publish failed")
        return original_replace(source_path, destination_path)

    monkeypatch.setattr(run_archive, "_prepare_checkpoint_database", prepare_with_sidecars)
    monkeypatch.setattr(run_archive.shutil, "copytree", copy_while_sidecars_change)
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
    assert not list(destination.parent.glob(".run-1.tmp-*"))


def test_archive_rejects_durable_trace_mutation_during_copy(
    tmp_path, monkeypatch
) -> None:
    active = tmp_path / "active"
    source = _trace(active, "run-1", tmp_path / "out.json")
    durable = source / "durable.json"
    durable.write_text('{"state": "before"}', encoding="utf-8")
    destination = tmp_path / "archive" / "discovery" / "run-1"
    original_copytree = run_archive.shutil.copytree

    def copy_then_mutate(source_path, destination_path, *args, **kwargs):
        result = original_copytree(source_path, destination_path, *args, **kwargs)
        durable.write_text('{"state": "after"}', encoding="utf-8")
        return result

    monkeypatch.setattr(run_archive.shutil, "copytree", copy_then_mutate)

    with pytest.raises(OSError, match="archive trace verification failed"):
        Atlas.archive_existing_runs(
            dev_out_dir=active,
            archive_root=tmp_path / "archive",
            workflow="discovery",
        )

    assert source.exists()
    assert durable.read_text(encoding="utf-8") == '{"state": "after"}'
    assert not destination.exists()
    assert not list(destination.parent.glob(".run-1.tmp-*"))


def test_prepare_checkpoint_database_rejects_busy_checkpoint_and_closes(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "atlas_run.sqlite3"
    database.touch()

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        closed = False

        def execute(self, statement):
            if statement == "PRAGMA wal_checkpoint(TRUNCATE)":
                return Result((1, 2, 1))
            return Result(("ok",))

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(run_archive.sqlite3, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(sqlite3.OperationalError, match="checkpoint database is busy"):
        run_archive._prepare_checkpoint_database(database)

    assert connection.closed


def test_prepare_checkpoint_database_rejects_nonempty_wal_after_close(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "atlas_run.sqlite3"
    database.touch()

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        def execute(self, statement):
            if statement == "PRAGMA wal_checkpoint(TRUNCATE)":
                return Result((0, 0, 0))
            return Result(("ok",))

        def close(self):
            Path(f"{database}-wal").write_bytes(b"uncheckpointed")

    monkeypatch.setattr(
        run_archive.sqlite3, "connect", lambda *args, **kwargs: Connection()
    )

    with pytest.raises(sqlite3.OperationalError, match="WAL remained non-empty"):
        run_archive._prepare_checkpoint_database(database)
