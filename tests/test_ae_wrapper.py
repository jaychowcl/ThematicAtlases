from __future__ import annotations

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from meta_standards_converter.ae_handlers.ae_webfetcher import MAGETabInput, TextResource
from meta_standards_converter.miniml import MINiMLCodec
from meta_standards_converter.runtime_contracts import get_resource_profile


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
        "miniml_schema_version": "3.0",
        "source": {"format": "MAGE-TAB"},
        "database": [],
        "organization": [],
        "contributor": [],
        "platform": [],
        "series": {"accession": [
            {"value": accession},
            {"value": "GSE1"},
        ]},
        "sample": [],
    }


def invalid_reference_package(accession="E-MTAB-1"):
    value = package(accession)
    value["sample"] = [{
        "iid": "sample-1",
        "platform_ref": {"ref": "platform-missing"},
        "channel": [],
    }]
    return value


class FakeConverter:
    calls = []

    def convert(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return [MINiMLCodec().decode(package(kwargs["source"]), strict=True).package]


def test_arrayexpress_default_converter_preserves_typed_resource_overrides() -> None:
    profile = get_resource_profile(
        "standard",
        overrides={"max_xml_bytes": 4096, "network_workers": 2},
    )

    converter = ArrayExpressWrapper(resource_profile=profile)._converter()

    assert converter.fetcher.resource_profile is profile
    assert converter.fetcher.requester.settings.timeout == (10, 60)
    assert converter.fetcher.requester.settings.max_in_flight == 2


def test_arrayexpress_canonicalizes_typed_magetab_package_into_memory() -> None:
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
    assert result[0]["accession_metadata"] == package()


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


def test_arrayexpress_checkpoint_captures_sources_and_diagnostics_before_failure(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "raw.sqlite3")

    class Fetcher:
        calls = 0

        def resolve(self, source, sdrf_sources=None):
            self.__class__.calls += 1
            return MAGETabInput(
                TextResource("study.idf.txt", "IDF source", "https://example/idf"),
                (TextResource("study.sdrf.txt", "SDRF source", "https://example/sdrf"),),
                source,
                "accession",
            )

    class Parser:
        def parse(self, _source):
            return MINiMLCodec().decode(invalid_reference_package()).package

    class Converter:
        def __init__(self):
            self.fetcher = Fetcher()
            self.parser = Parser()

    wrapper = ArrayExpressWrapper(converter_factory=Converter)
    result = wrapper.collect_accession_metadata([record()], checkpoint_store=store)

    assert result[0]["metadata_status"] == "error"
    assert store.get("arrayexpress_magetab_source", "E-MTAB-1")["status"] == "available"
    assert store.get("arrayexpress_precanonical_metadata", "E-MTAB-1")["status"] == "available"
    diagnostics = store.get(
        "metadata_validation_diagnostics", "arrayexpress:E-MTAB-1"
    )
    assert diagnostics["payload"]["diagnostics"][0] == {
        "package_index": 0,
        "code": "unresolved_reference",
        "path": "/sample/0/platform_ref/ref",
        "severity": "warning",
    }

    failed = store.get("arrayexpress_metadata", "E-MTAB-1")
    store.put(
        "arrayexpress_metadata", "E-MTAB-1", 1, "retryable_error",
        payload=failed["payload"], error="targeted retry",
    )
    wrapper.collect_accession_metadata([record()], checkpoint_store=store)
    assert Fetcher.calls == 1


def test_arrayexpress_recomputes_legacy_unversioned_checkpoint(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "atlas.sqlite3")
    store.put(
        "arrayexpress_metadata",
        "E-MTAB-1",
        1,
        "available",
        payload={"checkpoint_version": 1, "packages": [{"mage_tab": {}}]},
    )
    FakeConverter.calls = []

    result = ArrayExpressWrapper(converter_factory=FakeConverter).collect_accession_metadata(
        [record()], checkpoint_store=store
    )

    assert FakeConverter.calls
    assert result[0]["accession_metadata"] == package()


def test_arrayexpress_offline_resume_marks_legacy_checkpoint_pending(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "atlas.sqlite3")
    store.put(
        "arrayexpress_metadata",
        "E-MTAB-1",
        1,
        "available",
        payload={"checkpoint_version": 1, "packages": [{"mage_tab": {}}]},
    )

    result = ArrayExpressWrapper().available_accession_metadata([record()], store)

    assert result[0]["metadata_status"] == "pending"
    assert result[0]["accession_metadata"] is None


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
