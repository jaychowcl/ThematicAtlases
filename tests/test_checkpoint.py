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
        "attempt_count": 0,
        "first_failed_at": None,
        "last_attempt_at": reopened.get("datalinks", "MED:1")["last_attempt_at"],
        "error_type": None,
        "failure_category": None,
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
    assert store.get("geo_metadata", "GSE1")["attempt_count"] == 1
    assert store.history("geo_metadata", "GSE1")[0]["status"] == "retryable_error"


def test_checkpoint_store_rejects_unknown_status(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")

    with pytest.raises(ValueError, match="unsupported checkpoint status"):
        store.put("stage", "key", 1, "typo")


def test_checkpoint_store_reports_all_incomplete_retry_work(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put("datalinks", "MED:1", 1, "pending")
    store.put("geo_metadata", "GSE1", 1, "retryable_error", error="403")
    store.put(
        "thematic_review",
        "direct:1",
        1,
        "terminal_error",
        error="invalid model output",
    )
    store.put("geo_metadata", "GSE2", 2, "available", payload={})

    assert store.has_actionable() is True
    assert store.has_incomplete() is True
    assert store.has_actionable_boundary("discovery") is True
    assert store.has_incomplete_boundary("review") is True

    report = store.retry_report()
    assert report["requires_retry"] is True
    assert report["automatic_retry_count"] == 2
    assert report["manual_retry_count"] == 1
    assert report["stages"]["datalinks"]["counts"] == {"pending": 1}
    assert report["stages"]["geo_metadata"]["automatic"][0]["key"] == "GSE1"
    assert report["stages"]["thematic_review"]["manual"][0]["key"] == "direct:1"


def test_checkpoint_store_migrates_version_one_database(tmp_path) -> None:
    path = tmp_path / "resume_state.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE checkpoint_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO checkpoint_meta VALUES ('schema_version', '1');
            CREATE TABLE checkpoint_items (
                stage TEXT NOT NULL,
                item_key TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload TEXT,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (stage, item_key)
            );
            INSERT INTO checkpoint_items(stage, item_key, ordinal, status)
            VALUES ('datalinks', 'MED:1', 1, 'retryable_error');
            """
        )

    store = CheckpointStore(path)

    assert store.get_meta("schema_version") == 2
    assert store.get("datalinks", "MED:1")["attempt_count"] == 0


def test_checkpoint_store_selectively_requeues_terminal_and_degraded_items(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put("thematic_review", "direct:1", 1, "terminal_error", error="bad")
    store.put(
        "harmonization",
        "work-1",
        1,
        "available",
        payload={
            "contract_version": "2.0",
            "status": {
                "contract_version": "2.0",
                "execution": "degraded",
                "completeness": "partial",
                "evidence_confidence": "insufficient",
                "validation": "valid",
                "publication": "review_required",
                "terminal_reason": "provider_degraded",
                "errors": [{
                    "contract_version": "1.0",
                    "error_type": "ProviderError",
                    "provider": "llm",
                    "location": None,
                    "http_status": None,
                    "retry_category": "retryable",
                    "stage": "target_checker",
                    "item_id": "target-1",
                    "correlation_id": "test-correlation",
                }],
            },
        },
    )

    assert store.request_retries(
        stages=["thematic_review"],
        degraded_stages=["target_checker"],
    ) == 2
    assert store.get("thematic_review", "direct:1")["status"] == "retryable_error"
    assert store.get("harmonization", "work-1")["status"] == "retryable_error"
    assert store.history("harmonization", "work-1")[0]["status"] == "available"


def test_checkpoint_store_does_not_infer_degradation_from_retired_fields(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put(
        "harmonization",
        "legacy-work",
        1,
        "available",
        payload={"quality_status": "degraded", "degraded_stages": [{"stage": "target_checker"}]},
    )

    with pytest.raises(ValueError, match="did not match any eligible items"):
        store.request_retries(degraded_stages=["target_checker"])


def test_checkpoint_store_rejects_ineligible_retry_selection(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put("datalinks", "MED:1", 1, "available")

    with pytest.raises(ValueError, match="not failed"):
        store.request_retries(items={"datalinks": ["MED:1"]})


def test_checkpoint_store_installs_status_and_history_lookup_indexes(tmp_path) -> None:
    path = tmp_path / "resume_state.sqlite"
    CheckpointStore(path)

    with sqlite3.connect(path) as connection:
        item_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(checkpoint_items)")
        }
        history_indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(checkpoint_attempt_history)"
            )
        }

    assert "checkpoint_items_status_stage_order" in item_indexes
    assert "checkpoint_history_stage_item_order" in history_indexes


def test_checkpoint_retry_selection_is_one_atomic_write(tmp_path) -> None:
    path = tmp_path / "resume_state.sqlite"
    store = CheckpointStore(path)
    store.put("datalinks", "first", 1, "terminal_error")
    store.put("datalinks", "second", 2, "terminal_error")
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_second_retry
            BEFORE UPDATE ON checkpoint_items
            WHEN NEW.item_key = 'second' AND NEW.status = 'retryable_error'
            BEGIN
                SELECT RAISE(ABORT, 'injected retry failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected retry failure"):
        store.request_retries(stages=["datalinks"])

    assert store.get("datalinks", "first")["status"] == "terminal_error"
    assert store.get("datalinks", "second")["status"] == "terminal_error"


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


def test_checkpoint_store_amends_fingerprint_and_archives_previous_configuration(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    old = {"query": ["old"], "max_publications": 5000}
    new = {
        "query": ["old", "expanded"],
        "max_publications": None,
        "max_publications_per_query": [5000, 15000],
    }
    store.validate_fingerprint(old)

    archived = store.amend_fingerprint(
        new,
        amendment_id="expanded-queries",
        metadata={"reason": "append complementary searches"},
    )

    assert archived["configuration"] == old
    assert store.get_meta("run_fingerprint")["configuration"] == new
    assert store.get_meta("run_configuration_amendments") == [
        {
            "amendment_id": "expanded-queries",
            "metadata": {"reason": "append complementary searches"},
            "previous": archived,
            "replacement": store.get_meta("run_fingerprint"),
        }
    ]
    store.validate_fingerprint(new)


def test_checkpoint_store_fingerprint_amendment_is_idempotent(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.validate_fingerprint({"query": ["old"]})
    replacement = {"query": ["old", "new"]}
    first = store.amend_fingerprint(replacement, amendment_id="queries-v2")
    second = store.amend_fingerprint(replacement, amendment_id="queries-v2")

    assert second == first
    assert len(store.get_meta("run_configuration_amendments")) == 1

    with pytest.raises(ValueError, match="amendment_id"):
        store.amend_fingerprint(
            {"query": ["different"]}, amendment_id="queries-v2"
        )


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


def test_checkpoint_store_archives_only_selected_stage_items(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    archive_path = tmp_path / "selected_reviews.sqlite"
    for ordinal, key in enumerate(("direct:1", "direct:2", "direct:3"), start=1):
        store.put(
            "thematic_review",
            key,
            ordinal,
            "available",
            payload={"publication": key},
        )
    store.put("datalinks", "MED:1", 1, "available")

    result = store.archive_items(
        "thematic_review",
        ["direct:3", "direct:1", "direct:1"],
        archive_path,
        archive_id="contested-reviews",
        metadata={"selection": "safety_union"},
    )

    assert result["item_count"] == 2
    assert [item["key"] for item in store.items("thematic_review")] == [
        "direct:2"
    ]
    assert [item["key"] for item in store.items("datalinks")] == ["MED:1"]
    with sqlite3.connect(archive_path) as connection:
        archived = connection.execute(
            "SELECT item_key FROM checkpoint_archive_items "
            "WHERE archive_id = ? ORDER BY ordinal",
            ("contested-reviews",),
        ).fetchall()
    assert archived == [("direct:1",), ("direct:3",)]


def test_checkpoint_store_refuses_missing_selected_archive_item(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put("thematic_review", "direct:1", 1, "available")

    with pytest.raises(ValueError, match="were not present"):
        store.archive_items(
            "thematic_review",
            ["direct:1", "direct:missing"],
            tmp_path / "archive.sqlite",
            archive_id="incomplete-selection",
        )

    assert [item["key"] for item in store.items("thematic_review")] == [
        "direct:1"
    ]
