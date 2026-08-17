import hashlib
import json

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.pubmed_gds import (
    PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
)


def _source_trace(root, *, run_id="source"):
    manifest = {
        "command": "create-atlas",
        "run_id": run_id,
        "created_at": run_id,
        "atlas_id": "fibrosis",
        "atlas_out": str(root.parent / "fibrosis_atlas.json"),
        "harmonization_details_out": str(root.parent / "details.json"),
        "unsupported_accessions_out": str(root.parent / "unsupported.json"),
        "query": ["fibrosis"],
        "query_file": None,
        "theme": "human fibrosis",
        "review_filter": "not_relevant",
        "metadata_repositories": ["geo", "arrayexpress"],
        "max_publications": None,
        "max_publications_per_query": [10000],
        "collect_metadata": True,
        "scrape_fulltext_accessions": True,
    }
    trace = DevTraceWriter(root=str(root), run_id=run_id, manifest=manifest)
    trace.checkpoint_store.validate_fingerprint(
        {
            "query": ["fibrosis"],
            "query_file": None,
            "theme": "human fibrosis",
            "review_filter": "not_relevant",
            "metadata_repositories": ["geo", "arrayexpress"],
            "max_publications": None,
            "max_publications_per_query": [10000],
            "collect_metadata": True,
            "scrape_fulltext_accessions": True,
        }
    )
    trace.checkpoint_store.put(
        "datalinks", "MED:1", 1, "available", payload={"rows": []}
    )
    trace.checkpoint_store.put(
        "thematic_review", "1", 1, "available", payload={"historical": True}
    )
    trace.checkpoint_store.set_meta("main_pipeline_phase", {"phase": "datalinks"})
    return trace


def test_migrate_discovery_run_clones_mid_discovery_trace_atomically(tmp_path):
    source = _source_trace(tmp_path / "runs")
    source_manifest_hash = hashlib.sha256(
        (source.directory / "00_run_manifest.json").read_bytes()
    ).hexdigest()
    source_fingerprint = source.checkpoint_store.get_meta("run_fingerprint")

    destination = Atlas(metadata={}).migrate_discovery_run(
        dev_out_dir=str(tmp_path / "runs"),
        run_id="source",
        new_run_id="graph-run",
    )

    assert destination == tmp_path / "runs" / "graph-run"
    migrated = DevTraceWriter.existing(destination)
    manifest = json.loads((destination / "00_run_manifest.json").read_text())
    assert manifest["run_id"] == "graph-run"
    assert manifest["migrated_from"]["run_id"] == "source"
    assert manifest["pubmed_gds_discovery_contract"] == "1.0"
    assert manifest["atlas_out"] == str(
        tmp_path / "branches" / "graph-run" / "fibrosis_atlas.json"
    )
    assert migrated.run_store.get_run("graph-run") is not None
    assert migrated.run_store.get_run("source") is None
    assert migrated.checkpoint_store.get("datalinks", "MED:1")["status"] == "available"
    assert migrated.checkpoint_store.get("thematic_review", "1")["status"] == "available"
    fingerprint = migrated.checkpoint_store.get_meta("run_fingerprint")
    assert fingerprint["configuration"]["pubmed_gds_discovery_contract"] == (
        PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
    )
    assert migrated.checkpoint_store.get_meta("discovery_contract_migration")[
        "source_run_id"
    ] == "source"
    assert any(
        event["event_type"] == "discovery_contract_migrated"
        for event in migrated.run_store.events("graph-run")
    )
    assert hashlib.sha256(
        (source.directory / "00_run_manifest.json").read_bytes()
    ).hexdigest() == source_manifest_hash
    assert source.checkpoint_store.get_meta("run_fingerprint") == source_fingerprint


@pytest.mark.parametrize(
    "invalidator, message",
    [
        (
            lambda trace: trace.write("01_collected_accessions.json", []),
            "past discovery",
        ),
        (
            lambda trace: trace.checkpoint_store.put(
                "pubmed_gds_links",
                "1",
                1,
                "available",
                payload={"contract_version": "1.0", "target_uids": []},
            ),
            "graph checkpoints",
        ),
        (
            lambda trace: trace.checkpoint_store.set_meta(
                "main_pipeline_phase", {"phase": "downstream"}
            ),
            "Datalinks phase",
        ),
    ],
)
def test_migrate_discovery_run_rejects_invalid_source(
    tmp_path, invalidator, message
):
    trace = _source_trace(tmp_path / "runs")
    invalidator(trace)

    with pytest.raises(ValueError, match=message):
        Atlas(metadata={}).migrate_discovery_run(
            dev_out_dir=str(tmp_path / "runs"),
            run_id="source",
            new_run_id="graph-run",
        )


def test_migrate_discovery_run_rejects_manifest_fingerprint_drift(tmp_path):
    trace = _source_trace(tmp_path / "runs")
    manifest_path = trace.directory / "00_run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["query"] = ["different"]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="discovery configuration"):
        Atlas(metadata={}).migrate_discovery_run(
            dev_out_dir=str(tmp_path / "runs"),
            run_id="source",
            new_run_id="graph-run",
        )

