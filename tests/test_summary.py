from ThematicAtlases.summary import build_atlas_summary, summary_path


SUCCESS_STATUS = {
    "contract_version": "2.0",
    "execution": "succeeded",
    "completeness": "complete",
    "evidence_confidence": "high",
    "validation": "valid",
    "publication": "publishable",
    "terminal_reason": "harmonization_complete",
    "errors": [],
}

NOT_RUN_STATUS = {
    "contract_version": "2.0",
    "execution": "not_run",
    "completeness": "empty",
    "evidence_confidence": "not_assessed",
    "validation": "not_run",
    "publication": "not_requested",
    "terminal_reason": "metadata_unavailable",
    "errors": [],
}


def test_summary_path_is_written_beside_atlas() -> None:
    assert str(summary_path("results/atlas.json")) == "results/atlas.summary.json"
    assert str(summary_path("results/atlas")) == "results/atlas.summary.json"


def test_build_atlas_summary_reports_operations_and_scientific_profile() -> None:
    atlas = {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "metadata_repository": "geo",
                "ontology_harmonization_run_status": "completed",
                "ontology_harmonization_status": SUCCESS_STATUS,
                "publications": [{"pmid": "1", "publication_text_ref": "1"}],
                "accession_metadata": {
                    "platform": [{"iid": "GPL1", "technology": "high-throughput sequencing"}],
                    "sample": [
                        {
                            "iid": "GSM1",
                            "platform_ref": {"ref": "GPL1"},
                            "channel": [
                                {
                                    "source": {
                                        "value": "biopsy",
                                        "hz_organism_part": "lung biopsy",
                                        "hz_organism_part_id": "UBERON:0002048",
                                        "hz_organism_part_onto": "UBERON",
                                    },
                                    "organism": [{
                                        "name": "human",
                                        "hz_organism": "Homo sapiens",
                                        "hz_organism_id": "NCBITaxon:9606",
                                        "hz_organism_onto": "NCBITaxon",
                                    }],
                                    "characteristics": [
                                        {
                                            "name": "disease",
                                            "value": "fibrosis",
                                        },
                                        {"name": "hz_disease", "value": "pulmonary fibrosis"},
                                        {"name": "hz_disease_id", "value": "MONDO:0002771"},
                                        {"name": "hz_disease_onto", "value": "MONDO"},
                                        {"name": "tissue", "value": "lung"},
                                    ],
                                },
                                {
                                    "source": {"value": "lung biopsy"},
                                    "characteristics": [{"name": "tissue", "value": "lung"}],
                                },
                            ],
                        }
                    ],
                },
            },
            {
                "datalink_id": "E-MTAB-1",
                "metadata_repository": "arrayexpress",
                "ontology_harmonization_run_status": "not_run",
                "ontology_harmonization_status": NOT_RUN_STATUS,
                "accession_metadata": None,
                "publications": [{"pmid": "1", "publication_text_ref": "1"}],
            },
        ],
        "publication_texts": {
            "1": {"agentic_curator": {"judgement": "relevant"}},
            "2": {"text": "unreviewed"},
        },
    }

    summary = build_atlas_summary(atlas, atlas_path="atlas.json")

    assert summary["counts"] == {"accessions": 2, "publications": 1, "publication_texts": 2}
    assert summary["repositories"] == {"arrayexpress": 1, "geo": 1}
    assert summary["review_judgements"] == {"relevant": 1, "unreviewed": 1}
    assert summary["harmonization_run_statuses"] == {"completed": 1, "not_run": 1}
    assert summary["harmonization_execution_statuses"] == {
        "not_run": 1,
        "succeeded": 1,
    }
    assert summary["harmonization_completeness_statuses"] == {
        "complete": 1,
        "empty": 1,
    }
    assert summary["harmonization_publication_dispositions"] == {
        "not_requested": 1,
        "publishable": 1,
    }
    assert summary["harmonization_evidence_confidence_statuses"] == {
        "high": 1,
        "not_assessed": 1,
    }
    assert summary["harmonization_validation_statuses"] == {
        "not_run": 1,
        "valid": 1,
    }
    assert "harmonization_quality_statuses" not in summary
    profile = summary["scientific_profile"]
    assert profile["samples_total"] == 1
    assert profile["organisms"] == {"Homo sapiens": 1}
    assert profile["sample_sources"] == {"lung biopsy": 1}
    assert profile["tissues_organs"] == {"lung": 1}
    assert profile["diseases_conditions"] == {"pulmonary fibrosis": 1}
    assert profile["platform_technologies"] == {"high-throughput sequencing": 1}
    assert profile["observed_characteristics"]["disease"] == {"pulmonary fibrosis": 1}
