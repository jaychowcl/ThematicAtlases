import json
import os
import re

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.domain import AtlasDocument
from ThematicAtlases.run_store import AtlasRunStore


class Collector:
    def collect_jsons(self, **_kwargs):
        return [
            {
                "datalink_id": "GSE1",
                "metadata_repository": "geo",
                "metadata_status": "available",
                "accession_metadata": {
                    "series": {"iid": "GSE1"},
                    "sample": [{"iid": "GSM1"}],
                },
                "publications": [],
            }
        ]


class Filterer:
    def filter_jsons(self, jsons=None, **_kwargs):
        return {"accessions": list(jsons or []), "publication_texts": {}}


class Harmonizer:
    def harmonize_datasets(self, datasets, details_out=None, **_kwargs):
        records = []
        details = []
        for record in datasets["accessions"]:
            records.append(
                {
                    **record,
                    "accession_metadata": {
                        **record["accession_metadata"],
                        "harmonized": True,
                    },
                    "ontology_harmonization_run_status": "completed",
                    "ontology_harmonization_quality_status": "healthy",
                }
            )
            details.append(
                {
                    "datalink_id": record["datalink_id"],
                    "run_status": "completed",
                    "harmonization_targets": [],
                    "degraded_stages": [],
                }
            )
        return {**datasets, "accessions": records}, details


def _atlas():
    return Atlas(
        metadata={"atlas_id": "atlas-test", "title": "Test atlas"},
        collector=Collector(),
        filterer=Filterer(),
        harmonizer=Harmonizer(),
    )


def test_create_atlas_rolls_back_the_public_bundle_when_summary_publish_fails(
    tmp_path,
):
    output = tmp_path / "atlas.json"
    summary = tmp_path / "atlas.summary.json"
    output.write_text('{"old": "atlas"}\n', encoding="utf-8")
    summary.write_text('{"old": "summary"}\n', encoding="utf-8")
    real_replace = os.replace

    def failing_replace(source, destination):
        if str(source).endswith(".stage") and os.fspath(destination) == os.fspath(
            summary
        ):
            raise OSError("injected summary publication failure")
        real_replace(source, destination)

    atlas = Atlas(
        metadata={"atlas_id": "atlas-test", "title": "Test atlas"},
        collector=Collector(),
        filterer=Filterer(),
        harmonizer=Harmonizer(),
        artifact_publisher=JsonArtifactBundlePublisher(replace=failing_replace),
    )

    with pytest.raises(OSError, match="injected summary publication failure"):
        atlas.create_atlas(query=["lung"], out=str(output))

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": "atlas"}
    assert json.loads(summary.read_text(encoding="utf-8")) == {"old": "summary"}


def test_collect_datasets_returns_and_atomically_writes_a_v2_snapshot(tmp_path):
    output = tmp_path / "nested" / "collection.json"

    result = _atlas().collect_datasets(
        query=["lung"], theme="lung", out=str(output), run_id="run-collect"
    )

    document = AtlasDocument.from_mapping(result)
    assert document.run.run_id == "run-collect"
    assert document.run.status.value == "running"
    assert document.datasets[0].status.value == "collected"
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert "accessions" not in result


def test_create_atlas_returns_v2_and_publishes_derived_summary(tmp_path):
    output = tmp_path / "atlas.json"

    result = _atlas().create_atlas(
        query=["lung"], theme="lung", out=str(output)
    )

    document = AtlasDocument.from_mapping(result)
    assert document.run.status.value == "complete"
    assert document.datasets[0].status.value == "harmonized"
    summary = json.loads((tmp_path / "atlas.summary.json").read_text())
    assert summary == {
        "atlas_id": document.atlas.atlas_id,
        "atlas_path": str(output),
        "completed_dataset_count": 1,
        "dataset_count": 1,
        "failed_dataset_count": 0,
        "publication_count": 0,
        "run_id": document.run.run_id,
        "schema_version": "2.0",
    }


def test_harmonize_datasets_accepts_v2_and_rejects_legacy_v1():
    collected = _atlas().collect_datasets(query=["lung"], run_id="run-1")

    result = _atlas().harmonize_datasets(collected)

    document = AtlasDocument.from_mapping(result)
    assert document.datasets[0].status.value == "harmonized"
    assert document.datasets[0].metadata["harmonized"] is True
    with pytest.raises(ValueError, match="unknown AtlasDocument fields"):
        _atlas().harmonize_datasets({"accessions": []})


def test_traced_create_records_normalized_lifecycle_and_final_artifact_roles(tmp_path):
    _atlas().create_atlas(
        query=["lung"],
        theme="lung",
        dev_trace=True,
        dev_out_dir=str(tmp_path),
    )
    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    store = AtlasRunStore(run_dir / "atlas_run.sqlite3")

    run = store.get_run(run_dir.name)
    assert run["status"] == "complete"
    assert {item["role"] for item in store.artifacts(run_dir.name)} == {
        "final_atlas",
        "harmonization_details",
        "summary",
    }
    assert store.artifact(run_dir.name, "final_atlas")["relative_path"] == (
        "06_final_atlas.json"
    )


def test_traced_collection_publishes_snapshot_role_without_final_role(tmp_path):
    _atlas().collect_datasets(
        query=["lung"],
        dev_trace=True,
        dev_out_dir=str(tmp_path),
        run_id="run-collect",
    )
    run_dir = tmp_path / "run-collect"
    store = AtlasRunStore(run_dir / "atlas_run.sqlite3")

    assert (run_dir / "collection_snapshot.json").exists()
    assert not (run_dir / "06_final_atlas.json").exists()
    assert store.artifact("run-collect", "collection_snapshot") is not None
    assert store.artifact("run-collect", "final_atlas") is None


def test_generated_run_ids_are_lexically_sortable_and_collision_resistant():
    atlas = _atlas()

    run_ids = [atlas._dev_run_id() for _ in range(200)]

    assert len(set(run_ids)) == len(run_ids)
    assert all(
        re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{8}", run_id)
        for run_id in run_ids
    )
    assert run_ids == sorted(run_ids)
