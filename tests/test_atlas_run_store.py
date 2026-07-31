import sqlite3

import pytest

from ThematicAtlases.run_store import AtlasRunStore, IncompatibleRunStoreError


def test_run_store_creates_normalized_versioned_schema(tmp_path):
    path = tmp_path / "atlas_run.sqlite3"
    store = AtlasRunStore(path)
    store.create_run(
        run_id="01JTEST",
        atlas_id="atlas-lung",
        schema_version="2.0",
        config={"queries": ["lung"]},
    )

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "schema_migrations",
            "run",
            "stage_state",
            "work_items",
            "attempts",
            "artifacts",
            "run_events",
        } <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA application_id").fetchone()[0] != 0

    assert store.get_run("01JTEST")["config"] == {"queries": ["lung"]}


def test_run_store_preserves_work_order_attempts_events_and_artifact_roles(tmp_path):
    store = AtlasRunStore(tmp_path / "atlas_run.sqlite3")
    store.create_run("run-1", "atlas-1", "2.0", {})
    later = store.add_work_item("run-1", "collection", "geo", "GSE2", 1)
    earlier = store.add_work_item("run-1", "collection", "geo", "GSE1", 0)

    assert [item["source_key"] for item in store.work_items("run-1", "collection")] == [
        "GSE1",
        "GSE2",
    ]

    first_attempt = store.record_attempt(
        earlier,
        outcome="retryable_error",
        retry_classification="transient",
        error_summary="timeout",
    )
    second_attempt = store.record_attempt(earlier, outcome="succeeded")
    assert first_attempt == 1
    assert second_attempt == 2
    assert [item["attempt_number"] for item in store.attempts(earlier)] == [1, 2]

    store.record_event("run-1", "work_retry", stage="collection", work_item_id=later)
    store.record_event("run-1", "work_complete", stage="collection", work_item_id=earlier)
    assert [event["sequence"] for event in store.events("run-1")] == [1, 2]

    store.register_artifact(
        "run-1", "final_atlas", "atlas.json", "application/json", "abc", 10
    )
    store.set_run_status("run-1", "complete")
    assert store.get_run("run-1")["status"] == "complete"
    assert store.artifact("run-1", "final_atlas")["relative_path"] == "atlas.json"
    assert [item["role"] for item in store.artifacts("run-1")] == ["final_atlas"]
    with pytest.raises(ValueError, match="artifact role already has a different path"):
        store.register_artifact(
            "run-1", "final_atlas", "snapshot.json", "application/json", "def", 12
        )


def test_run_store_rejects_invalid_lifecycle_and_artifact_values(tmp_path):
    store = AtlasRunStore(tmp_path / "atlas_run.sqlite3")
    store.create_run("run-1", "atlas-1", "2.0", {})

    with pytest.raises(ValueError, match="unsupported run status"):
        store.set_run_status("run-1", "done")
    with pytest.raises(ValueError, match="relative path"):
        store.register_artifact(
            "run-1", "final_atlas", "/tmp/atlas.json", "application/json", "a", 1
        )


def test_run_store_rejects_legacy_checkpoint_database(tmp_path):
    path = tmp_path / "resume_state.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE checkpoint_meta(key TEXT PRIMARY KEY, value TEXT)")

    with pytest.raises(IncompatibleRunStoreError, match="legacy checkpoint"):
        AtlasRunStore(path)
