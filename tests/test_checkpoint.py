import json

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
