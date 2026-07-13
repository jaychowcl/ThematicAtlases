import json
import sqlite3

import pytest

from ThematicAtlases.checkpoint import CheckpointStore


def test_checkpoint_store_round_trips_items_and_meta(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.set_meta("resolved_queries", ["fibrosis", "cirrhosis"])
    store.put(
        stage="datalinks",
        key="MED:1",
        ordinal=2,
        status="available",
        payload={"rows": [{"datalink_id": "GSE1"}]},
    )

    reopened = CheckpointStore(tmp_path / "resume_state.sqlite")

    assert reopened.get_meta("resolved_queries") == ["fibrosis", "cirrhosis"]
    assert reopened.get("datalinks", "MED:1") == {
        "stage": "datalinks",
        "key": "MED:1",
        "ordinal": 2,
        "status": "available",
        "payload": {"rows": [{"datalink_id": "GSE1"}]},
        "error": None,
    }
    assert reopened.items("datalinks")[0]["key"] == "MED:1"


def test_checkpoint_store_replaces_item_atomically(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put("geo_metadata", "GSE1", 1, "retryable_error", error="timeout")
    store.put(
        "geo_metadata",
        "GSE1",
        1,
        "available",
        payload={"metadata_status": "available"},
    )

    assert store.get("geo_metadata", "GSE1")["status"] == "available"
    assert store.has_retryable("geo_metadata") is False


def test_checkpoint_store_validates_run_fingerprint(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.validate_fingerprint({"query": ["fibrosis"], "max_publications": 50})

    reopened = CheckpointStore(tmp_path / "resume_state.sqlite")
    reopened.validate_fingerprint({"query": ["fibrosis"], "max_publications": 50})

    try:
        reopened.validate_fingerprint(
            {"query": ["different"], "max_publications": 50}
        )
    except ValueError as error:
        assert "checkpoint configuration does not match" in str(error)
    else:
        raise AssertionError("mismatched checkpoints must be rejected")


def test_checkpoint_database_is_valid_sqlite_not_json(tmp_path) -> None:
    path = tmp_path / "resume_state.sqlite"
    CheckpointStore(path).set_meta("value", {"ok": True})

    assert path.read_bytes().startswith(b"SQLite format 3")
    assert json.loads(CheckpointStore(path).get_meta_json("value")) == {"ok": True}


def test_checkpoint_store_archives_and_removes_only_requested_stage(tmp_path) -> None:
    live_path = tmp_path / "resume_state.sqlite"
    archive_path = tmp_path / "review_archive.sqlite"
    store = CheckpointStore(live_path)
    store.put("thematic_review", "direct:1", 1, "available", payload={"v": 2})
    store.put("thematic_review", "direct:2", 2, "terminal_error", error="bad")
    store.put("datalinks", "MED:1", 1, "available", payload={"rows": []})

    result = store.archive_stage(
        "thematic_review",
        archive_path,
        archive_id="pre-contract-v3",
        metadata={"source_trace": "trace-1", "package_commit": "abc123"},
    )

    assert result == {
        "archive_id": "pre-contract-v3",
        "stage": "thematic_review",
        "item_count": 2,
        "archive_path": str(archive_path),
    }
    assert store.items("thematic_review") == []
    assert [item["key"] for item in store.items("datalinks")] == ["MED:1"]
    with sqlite3.connect(archive_path) as connection:
        rows = connection.execute(
            "SELECT item_key, status, payload, error FROM checkpoint_archive_items "
            "WHERE archive_id = ? ORDER BY ordinal",
            ("pre-contract-v3",),
        ).fetchall()
        meta = connection.execute(
            "SELECT stage, item_count, metadata FROM checkpoint_archive_meta "
            "WHERE archive_id = ?",
            ("pre-contract-v3",),
        ).fetchone()
    assert rows == [
        ("direct:1", "available", '{"v":2}', None),
        ("direct:2", "terminal_error", None, "bad"),
    ]
    assert meta[:2] == ("thematic_review", 2)
    assert json.loads(meta[2]) == {
        "package_commit": "abc123",
        "source_trace": "trace-1",
    }


def test_checkpoint_store_refuses_archive_id_collision_without_deleting_live_rows(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    archive_path = tmp_path / "review_archive.sqlite"
    store.put("thematic_review", "direct:1", 1, "available")
    store.archive_stage(
        "thematic_review", archive_path, archive_id="pre-contract-v3"
    )
    store.put("thematic_review", "direct:2", 2, "available")

    with pytest.raises(ValueError, match="archive_id already exists"):
        store.archive_stage(
            "thematic_review", archive_path, archive_id="pre-contract-v3"
        )

    assert [item["key"] for item in store.items("thematic_review")] == [
        "direct:2"
    ]
