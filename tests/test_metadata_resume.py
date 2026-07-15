import json

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.collector.resume import TraceMetadataResumer


class FakeEPMC:
    def accessions_from_datalinks(self, datalinks):
        return [
            {
                "datalink_id": row["datalink_id"],
                "datalink_id_scheme": row["datalink_id_scheme"],
                "publications": [{"source": row["source"], "epmc_id": row["epmc_id"]}],
            }
            for row in datalinks
        ]


class FakeCollector:
    def filter_accessions(self, accessions, metadata_repositories=None):
        return accessions

    def collect_accession_metadata(self, jsons, metadata_repositories=None, checkpoint_store=None):
        return [
            {
                **record,
                "metadata_repository": "geo",
                "metadata_status": "available",
                "accession_metadata": {"series": record["datalink_id"]},
            }
            for record in jsons
        ]


def _checkpoint_publication(trace_dir, epmc_id, datalink_id):
    store = CheckpointStore(trace_dir / "resume_state.sqlite")
    store.put(
        "datalinks",
        f"MED:{epmc_id}",
        len(store.items("datalinks")) + 1,
        "available",
        payload={
            "rows": [
                {
                    "source": "MED",
                    "epmc_id": epmc_id,
                    "datalink_id": datalink_id,
                    "datalink_id_scheme": "GEO",
                }
            ]
        },
    )


def test_metadata_resumer_processes_one_snapshot_and_later_additions(tmp_path, caplog) -> None:
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()
    (trace_dir / "00_run_manifest.json").write_text(
        json.dumps({"metadata_repositories": ["geo"]}), encoding="utf-8"
    )
    _checkpoint_publication(trace_dir, "1", "GSE1")
    resumer = TraceMetadataResumer(
        collector_factory=FakeCollector,
        epmc_wrapper_factory=FakeEPMC,
    )

    caplog.set_level("INFO")
    first = resumer.resume(trace_dir)
    _checkpoint_publication(trace_dir, "2", "GSE2")
    second = resumer.resume(trace_dir)

    assert [record["datalink_id"] for record in first["accessions"]] == ["GSE1"]
    assert [record["datalink_id"] for record in second["accessions"]] == ["GSE1", "GSE2"]
    assert second["publication_texts"] == {}
    assert json.loads((trace_dir / "resume_metadata_progress.json").read_text()) == second
    assert "Metadata snapshot stats datalink_checkpoints=1 datalink_rows=1" in caplog.text
    assert "Metadata checkpoint stats" in caplog.text
    assert "Metadata snapshot complete accessions=2" in caplog.text
