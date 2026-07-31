import hashlib

import pytest

from ThematicAtlases.run_store import IncompatibleRunStoreError
from ThematicAtlases.trace import DevTraceWriter


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
    trace.write("06_final_atlas.json", {"schema_version": "2.0"})

    trace.register_artifact("final_atlas", "06_final_atlas.json")

    run = trace.run_store.get_run("run-1")
    assert run["atlas_id"] == "atlas-1"
    assert run["schema_version"] == "2.0"
    assert run["config"]["query"] == ["lung"]
    artifact = trace.run_store.artifact("run-1", "final_atlas")
    content = (trace.directory / "06_final_atlas.json").read_bytes()
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["size_bytes"] == len(content)


def test_existing_trace_requires_an_initialized_v2_run_store(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()

    trace = DevTraceWriter.existing(directory)

    with pytest.raises(IncompatibleRunStoreError, match="atlas_run.sqlite3"):
        _ = trace.run_store
