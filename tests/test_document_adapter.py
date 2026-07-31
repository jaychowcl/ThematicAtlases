from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import DatasetStatus, RunStatus


def _legacy_atlas():
    return {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "metadata_repository": "geo",
                "metadata_status": "available",
                "accession_metadata": {
                    "series": {"iid": "GSE1"},
                    "sample": [{"iid": "GSM1"}],
                },
                "publications": [
                    {
                        "publication_text_ref": "PMID:1",
                        "pmid": "1",
                        "title": "Study one",
                    }
                ],
                "ontology_harmonization_run_status": "completed",
                "ontology_harmonization_quality_status": "healthy",
            },
            {
                "datalink_id": "GSE2",
                "metadata_repository": "geo",
                "metadata_status": "error",
                "accession_metadata": None,
                "publications": [
                    {
                        "publication_text_ref": "PMID:1",
                        "pmid": "1",
                        "title": "Study one",
                    }
                ],
                "ontology_harmonization_run_status": "error",
                "ontology_harmonization_error": "lookup failed",
            },
        ],
        "publication_texts": {
            "PMID:1": {
                "title": "Study one",
                "text": "An abstract.",
                "text_source": "abstract",
                "agentic_curator": {
                    "judgement": "relevant",
                    "confidence": "high",
                    "reasoning": "Direct evidence.",
                    "evidences": ["fibrosis"],
                },
            }
        },
    }


def test_adapter_assembles_one_valid_canonical_document_without_fragmented_json():
    document = AtlasDocumentAdapter().assemble(
        _legacy_atlas(),
        atlas_metadata={"atlas_id": "atlas-lung", "title": "Lung atlas"},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="lung",
        config={"queries": ["lung"], "metadata_repositories": ["geo"]},
        run_status=RunStatus.PARTIAL,
        harmonization_details=[
            {
                "datalink_id": "GSE1",
                "run_status": "completed",
                "degraded_stages": [],
                "harmonization_targets": [{"path": "/sample/0/organism"}],
            }
        ],
    )

    document.validate()
    assert [item.dataset_id for item in document.datasets] == ["GSE1", "GSE2"]
    assert [item.status for item in document.datasets] == [
        DatasetStatus.HARMONIZED,
        DatasetStatus.FAILED,
    ]
    assert [item.publication_id for item in document.publications] == ["PMID:1"]
    assert document.publications[0].review.judgement.value == "relevant"
    assert document.datasets[0].harmonization.targets[0].path == "/sample/0/organism"
    assert document.datasets[1].diagnostics[0].message == "lookup failed"
    assert document.summary.dataset_count == 2
    assert document.summary.publication_count == 1
    assert document.summary.completed_dataset_count == 1
    assert document.summary.failed_dataset_count == 1


def test_adapter_wraps_multiple_miniml_packages_explicitly():
    legacy = _legacy_atlas()
    legacy["accessions"] = [
        {
            "datalink_id": "GSE1",
            "metadata_repository": "geo",
            "accession_metadata": [
                {"series": {"iid": "GSE1"}, "sample": [{"iid": "GSM1"}]},
                {"series": {"iid": "GSE1"}, "sample": [{"iid": "GSM2"}]},
            ],
            "ontology_harmonization_run_status": "completed",
        }
    ]
    legacy["publication_texts"] = {}

    document = AtlasDocumentAdapter().assemble(
        legacy,
        atlas_metadata={},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="",
        config={},
        run_status=RunStatus.COMPLETE,
    )

    assert len(document.datasets[0].metadata["packages"]) == 2


def test_adapter_projects_v2_back_to_minimal_internal_harmonization_input():
    adapter = AtlasDocumentAdapter()
    document = adapter.assemble(
        _legacy_atlas(),
        atlas_metadata={"atlas_id": "atlas-lung"},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="lung",
        config={},
        run_status=RunStatus.PARTIAL,
    )

    legacy = adapter.to_legacy(document)

    assert [item["datalink_id"] for item in legacy["accessions"]] == [
        "GSE1",
        "GSE2",
    ]
    assert legacy["accessions"][0]["accession_metadata"]["sample"][0]["iid"] == "GSM1"
    assert legacy["publication_texts"]["PMID:1"]["agentic_curator"]["judgement"] == "relevant"
