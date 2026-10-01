from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import threading

import pytest

from ThematicAtlases.run_store import IncompatibleRunStoreError
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases import trace as trace_module


def test_new_trace_initializes_authoritative_v2_run_store_and_registers_artifacts(
    tmp_path,
):
    trace = DevTraceWriter(
        root=str(tmp_path),
        run_id="run-1",
        manifest={
            "command": "create-atlas",
            "created_at": "2026-07-31T00:00:00Z",
            "atlas_id": "atlas-1",
            "query": ["lung"],
        },
    )
    trace.write("06_final_atlas.json", {"schema_version": "1.0"})

    trace.register_artifact("final_atlas", "06_final_atlas.json")

    run = trace.run_store.get_run("run-1")
    assert run["atlas_id"] == "atlas-1"
    assert run["schema_version"] == "1.0"
    assert run["config"]["query"] == ["lung"]
    artifact = trace.run_store.artifact("run-1", "final_atlas")
    content = (trace.directory / "06_final_atlas.json").read_bytes()
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["size_bytes"] == len(content)


def test_new_trace_keeps_item_checkpoints_in_the_single_run_database(tmp_path):
    trace = DevTraceWriter(
        root=str(tmp_path),
        run_id="run-1",
        manifest={"command": "create-atlas", "atlas_id": "atlas-1"},
    )

    trace.checkpoint_store.put(
        "search_queries",
        "lung",
        0,
        "available",
        payload={"rows": []},
    )
    trace.checkpoint_store.put(
        "search_queries",
        "lung",
        0,
        "retryable_error",
        payload={"rows": []},
        error="timeout",
        error_type="TimeoutError",
        failure_category="transient",
    )
    trace.checkpoint_store.set_meta("resolved_queries", ["lung"])

    assert not (trace.directory / "resume_state.sqlite").exists()
    reopened = DevTraceWriter.existing(trace.directory)
    assert reopened.checkpoint_store.get(
        "search_queries", "lung"
    )["status"] == "retryable_error"
    normalized = reopened.run_store.work_items("run-1", "search_queries")
    assert len(normalized) == 1
    assert normalized[0]["source_key"] == "lung"
    assert normalized[0]["status"] == "retryable_error"
    assert normalized[0]["payload_json"] == '{"rows":[]}'
    attempts = reopened.run_store.attempts(normalized[0]["work_item_id"])
    assert [attempt["outcome"] for attempt in attempts] == ["available"]
    assert reopened.run_store.metadata("run-1", "resolved_queries") == ["lung"]


def test_existing_trace_requires_an_initialized_v2_run_store(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()

    (directory / "00_run_manifest.json").write_text('{"workflow_checkpoint_contract":"2.0"}')
    trace = DevTraceWriter.existing(directory)
    with pytest.raises(IncompatibleRunStoreError, match="atlas_run.sqlite3"):
        _ = trace.run_store


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", ".", "", None])
def test_trace_rejects_unsafe_run_id_components(tmp_path, run_id):
    with pytest.raises(ValueError, match="run_id must be a filesystem-safe"):
        DevTraceWriter(str(tmp_path), run_id, {"command": "test"})


@pytest.mark.parametrize("name", ["../escape.json", "nested/file.json", "."])
def test_trace_rejects_unsafe_artifact_name_components(tmp_path, name):
    trace = DevTraceWriter(str(tmp_path), "run-1", {"command": "test"})

    with pytest.raises(ValueError, match="artifact name must be a filesystem-safe"):
        trace.write(name, {})

    with pytest.raises(ValueError, match="artifact name must be a filesystem-safe"):
        trace.register_artifact("result", name)


def test_concurrent_trace_writes_use_independent_temporary_files(
    tmp_path, monkeypatch
):
    trace = DevTraceWriter(str(tmp_path), "run-1", {"debug_snapshots": True, "command": "test"})
    barrier = threading.Barrier(2)
    original_dump = trace_module.json.dump

    def synchronized_dump(value, handle, **kwargs):
        barrier.wait(timeout=5)
        return original_dump(value, handle, **kwargs)

    monkeypatch.setattr(trace_module.json, "dump", synchronized_dump)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = [
            executor.submit(trace.write, "resume_review_progress.json", value)
            for value in ({"writer": 1}, {"writer": 2})
        ]
        for write in writes:
            write.result(timeout=5)

    assert json.loads(
        (trace.directory / "resume_review_progress.json").read_text()
    ) in ({"writer": 1}, {"writer": 2})
