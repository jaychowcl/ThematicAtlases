from ThematicAtlases.summary import build_atlas_summary, summary_path


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
                "publications": [{"pmid": "1", "publication_text_ref": "1"}],
                "accession_metadata": {
                    "platform": [{"iid": "GPL1", "technology": "high-throughput sequencing"}],
                    "sample": [
                        {
                            "iid": "GSM1",
                            "platform_ref": {"ref": "GPL1"},
                            "channel": [
                                {
                                    "source": "lung biopsy",
                                    "organism": [{"name": "Homo sapiens"}],
                                    "characteristics": [
                                        {"tag": "disease", "value": "fibrosis"},
                                        {"tag": "hz_disease", "value": "pulmonary fibrosis"},
                                        {"tag": "tissue", "value": "lung"},
                                    ],
                                },
                                {
                                    "source": "lung biopsy",
                                    "characteristics": [{"tag": "tissue", "value": "lung"}],
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
    assert "harmonization_statuses" not in summary
    profile = summary["scientific_profile"]
    assert profile["samples_total"] == 1
    assert profile["organisms"] == {"Homo sapiens": 1}
    assert profile["sample_sources"] == {"lung biopsy": 1}
    assert profile["tissues_organs"] == {"lung": 1}
    assert profile["diseases_conditions"] == {"pulmonary fibrosis": 1}
    assert profile["platform_technologies"] == {"high-throughput sequencing": 1}
    assert profile["observed_characteristics"]["disease"] == {"pulmonary fibrosis": 1}
