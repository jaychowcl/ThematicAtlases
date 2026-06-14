from ThematicAtlases.wrappers.ae import ArrayExpressWrapper


def test_arrayexpress_placeholder_preserves_record_and_adds_metadata_fields() -> None:
    records = [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    assert ArrayExpressWrapper().collect_accession_metadata(jsons=records) == [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [{"source": "MED", "epmc_id": "1"}],
            "metadata_repository": "arrayexpress",
            "metadata_source": "placeholder",
            "metadata_status": "placeholder",
            "accession_metadata": None,
        }
    ]
