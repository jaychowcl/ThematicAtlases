import json
import logging

from ThematicAtlases.operational_events import OperationalEventEmitter, redact
from ThematicAtlases.run_store import AtlasRunStore


def test_operational_event_writes_redacted_jsonl_logs_and_metrics(tmp_path, caplog):
    emitter = OperationalEventEmitter(
        repository="ThematicAtlases", jsonl_path=tmp_path / "events.jsonl"
    )
    with caplog.at_level(logging.INFO):
        event = emitter.emit(
            "work_complete",
            component="collector",
            run_id="run-1",
            stage="collection",
            status="complete",
            duration_seconds=1.25,
            attributes={
                "api_key": "secret",
                "url": "https://example.org/data?token=secret",
                "count": 2,
            },
        )

    stored = json.loads((tmp_path / "events.jsonl").read_text())
    assert stored == event
    assert stored["schema_version"] == "1.0"
    assert stored["attributes"]["api_key"] == "[REDACTED]"
    assert stored["attributes"]["url"] == "https://example.org/data"
    assert "secret" not in caplog.text
    summary = emitter.export_json(tmp_path / "metrics.json")
    assert summary["events"]["work_complete|complete"]["count"] == 1
    prometheus = emitter.export_prometheus(tmp_path / "metrics.prom")
    assert "operational_events_total" in prometheus
    assert 'event_type="work_complete"' in prometheus


def test_run_store_remains_authority_and_emits_same_redacted_event(tmp_path):
    emitter = OperationalEventEmitter(
        repository="ThematicAtlases", jsonl_path=tmp_path / "events.jsonl"
    )
    store = AtlasRunStore(tmp_path / "run.sqlite3", event_emitter=emitter)
    store.create_run("run-1", atlas_id="atlas-1", schema_version="1.0", config={})

    sequence = store.record_event(
        "run-1", "run_started", stage="collection", detail={"token": "secret"}
    )

    assert sequence == 1
    assert store.events("run-1")[0]["detail_json"] == {"token": "[REDACTED]"}
    emitted = json.loads((tmp_path / "events.jsonl").read_text())
    assert emitted["run_id"] == "run-1"
    assert emitted["attributes"]["token"] == "[REDACTED]"


def test_redaction_is_recursive_and_preserves_scientific_values():
    assert redact({"authorization": "Bearer abc", "nested": [{"theme": "fibrosis"}]}) == {
        "authorization": "[REDACTED]",
        "nested": [{"theme": "fibrosis"}],
    }
