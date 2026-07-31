import json

from ThematicAtlases.application import AtlasDocumentService
from ThematicAtlases.domain import RunStatus


def test_document_service_assembles_and_publishes_the_v2_boundary(tmp_path):
    service = AtlasDocumentService()
    document = service.assemble(
        {
            "accessions": [
                {
                    "datalink_id": "GSE1",
                    "metadata_repository": "geo",
                    "metadata_status": "available",
                    "accession_metadata": {"series": {"iid": "GSE1"}},
                    "publications": [],
                }
            ],
            "publication_texts": {},
        },
        atlas_metadata={"atlas_id": "atlas-1", "title": "Atlas"},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="lung",
        config={"queries": ["lung"]},
        run_status=RunStatus.COMPLETE,
    )
    output = tmp_path / "nested" / "atlas.json"

    summary = service.publish(document, output, include_summary=True)

    assert json.loads(output.read_text()) == document.to_mapping()
    assert json.loads((output.parent / "atlas.summary.json").read_text()) == summary
    assert summary["dataset_count"] == 1
    assert service.to_legacy(document)["accessions"][0]["datalink_id"] == "GSE1"
