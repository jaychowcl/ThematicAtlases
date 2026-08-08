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


def test_adapter_unwraps_agentic_curator_evidence_envelope():
    legacy = _legacy_atlas()
    expected = {
        "evidence": "single-cell RNA sequencing of P0 telencephalic tissue",
        "judgement": "relevant",
        "confidence": "high",
        "reason": "Directly supports the theme.",
    }
    legacy["publication_texts"]["PMID:1"]["agentic_curator"]["evidences"] = {
        "evidences": [expected]
    }

    document = AtlasDocumentAdapter().assemble(
        legacy,
        atlas_metadata={"atlas_id": "atlas-review"},
        run_id="run-review",
        created_at="2026-07-31T00:00:00Z",
        theme="neonatal cortical single-cell transcriptomics",
        config={},
        run_status=RunStatus.RUNNING,
    )

    assert document.publications[0].review.evidence == (expected,)


def test_adapter_ignores_malformed_evidence_without_leaking_mapping_keys():
    legacy = _legacy_atlas()
    legacy["publication_texts"]["PMID:1"]["agentic_curator"]["evidences"] = {
        "unexpected": ["must not leak"]
    }

    document = AtlasDocumentAdapter().assemble(
        legacy,
        atlas_metadata={"atlas_id": "atlas-review"},
        run_id="run-review",
        created_at="2026-07-31T00:00:00Z",
        theme="review theme",
        config={},
        run_status=RunStatus.RUNNING,
    )

    assert document.publications[0].review.evidence == ()


def test_adapter_projects_agentic_curator_harmonization_targets():
    document = AtlasDocumentAdapter().assemble(
        _legacy_atlas(),
        atlas_metadata={"atlas_id": "atlas-lung"},
        run_id="run-harmonization",
        created_at="2026-07-31T00:00:00Z",
        theme="lung",
        config={},
        run_status=RunStatus.COMPLETE,
        harmonization_details=[
            {
                "datalink_id": "GSE1",
                "degraded_stages": [],
                "harmonization_targets": [
                    {
                        "pre_hz_field": "tissue",
                        "pre_hz_label": "lung",
                        "pre_hz_label_path": "/sample/0/tissue",
                        "ontology_match": True,
                        "ontology_id": "gsk",
                        "ontology_lookup": {
                            "id": "UBERON:0002048",
                            "title": "lung",
                            "ontology_id": "gsk",
                        },
                    },
                    {
                        "pre_hz_field": "disease",
                        "pre_hz_label": "unknown syndrome",
                        "pre_hz_field_path": "/sample/0/disease",
                        "ontology_match": False,
                    },
                ],
            }
        ],
    )

    targets = document.datasets[0].harmonization.targets
    assert targets[0].path == "/sample/0/tissue"
    assert targets[0].raw_value == "lung"
    assert targets[0].match.label == "lung"
    assert targets[0].match.accession == "UBERON:0002048"
    assert targets[0].match.framework == "gsk"
    assert targets[1].path == "/sample/0/disease"
    assert targets[1].raw_value == "unknown syndrome"
    assert targets[1].match is None


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


def test_adapter_preserves_versioned_miniml_package_metadata():
    legacy = _legacy_atlas()
    legacy["accessions"][0]["accession_metadata"] = {
        "miniml_schema_version": "1.0",
        "series": {"iid": "GSE1"},
        "sample": [{"iid": "GSM1"}],
        "mage_tab": {"version": "1.1"},
    }

    adapter = AtlasDocumentAdapter()
    document = adapter.assemble(
        legacy,
        atlas_metadata={"atlas_id": "atlas-lung"},
        run_id="run-1",
        created_at="2026-07-31T00:00:00Z",
        theme="lung",
        config={},
        run_status=RunStatus.COMPLETE,
    )

    assert document.datasets[0].metadata["miniml_schema_version"] == "1.0"
    assert adapter.to_legacy(document)["accessions"][0]["accession_metadata"] == (
        legacy["accessions"][0]["accession_metadata"]
    )


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
