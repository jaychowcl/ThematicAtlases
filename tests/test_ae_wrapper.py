from __future__ import annotations

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper


def record(accession="E-MTAB-1"):
    return {
        "datalink_id": accession,
        "datalink_id_scheme": "ArrayExpress",
        "datalink_url": f"https://example.org/{accession}",
        "datalink_category": "Functional Genomics Experiments",
        "publications": [{"source": "MED", "epmc_id": "1"}],
    }


def package(accession="E-MTAB-1"):
    return {
        "series": {"accession": [
            {"database": "ArrayExpress", "value": accession},
            {"database": "GEO", "value": "GSE1"},
        ]},
        "sample": [],
        "mage_tab": {"model": {"schema_version": 1}},
    }


class FakeConverter:
    calls = []

    def convert(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return [package(kwargs["source"])]


def test_arrayexpress_collects_magetab_into_memory() -> None:
    FakeConverter.calls = []
    result = ArrayExpressWrapper(converter_factory=FakeConverter).collect_accession_metadata(
        [record()]
    )

    assert FakeConverter.calls == [{
        "source": "E-MTAB-1", "out": None, "sdrf_sources": None
    }]
    assert result[0]["metadata_repository"] == "arrayexpress"
    assert result[0]["metadata_source"] == "ae2json"
    assert result[0]["metadata_status"] == "available"
    assert result[0]["accession_metadata"]["mage_tab"]["model"]["schema_version"] == 1


def test_arrayexpress_checkpoint_resume_is_offline_and_rebuilds_record(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "atlas.sqlite3")
    FakeConverter.calls = []
    wrapper = ArrayExpressWrapper(converter_factory=FakeConverter)
    wrapper.collect_accession_metadata([record()], checkpoint_store=store)
    latest = {**record(), "publications": [{"pmid": "new"}]}

    result = ArrayExpressWrapper(
        converter_factory=lambda: (_ for _ in ()).throw(AssertionError("network"))
    ).available_accession_metadata([latest], store)

    assert result[0]["publications"] == [{"pmid": "new"}]
    assert result[0]["metadata_status"] == "available"
    assert store.get("arrayexpress_metadata", "E-MTAB-1")["status"] == "available"


def test_arrayexpress_isolates_errors_and_no_data() -> None:
    class PartialConverter:
        def convert(self, source, **_kwargs):
            if source == "E-MTAB-1":
                raise ValueError("invalid MAGE-TAB")
            return []

    result = ArrayExpressWrapper(
        converter_factory=PartialConverter
    ).collect_accession_metadata([record(), record("E-MTAB-2")])

    assert [item["metadata_status"] for item in result] == ["error", "unavailable"]
    assert all(item["accession_metadata"] is None for item in result)
