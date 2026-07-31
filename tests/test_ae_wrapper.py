import pytest

from ThematicAtlases.wrappers.ae import ArrayExpressWrapper


def test_arrayexpress_default_wrapper_rejects_unimplemented_live_metadata() -> None:
    records = [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    with pytest.raises(NotImplementedError, match="ArrayExpress metadata"):
        ArrayExpressWrapper().collect_accession_metadata(jsons=records)

    assert records[0]["datalink_id"] == "E-MTAB-1"
    assert "metadata_status" not in records[0]
