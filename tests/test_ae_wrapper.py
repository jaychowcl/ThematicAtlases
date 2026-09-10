from __future__ import annotations

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from meta_standards_converter.sources.magetab import MAGETabInput, TextResource
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


class FakeResolver:
    calls = []

    def resolve(self, source, sdrf_sources=None):
        self.__class__.calls.append({"source": source, "sdrf_sources": sdrf_sources})
        return MAGETabInput(TextResource("idf", "text", "origin"), (), source, "accession")


class FakeParser:
    def parse(self, source):
        return MINiMLCodec().decode(package(source.source), strict=True).package


def test_arrayexpress_default_converter_preserves_typed_resource_overrides() -> None:
    profile = get_resource_profile(
        "standard",
        overrides={"max_xml_bytes": 4096, "network_workers": 2},
    )

    resolver = ArrayExpressWrapper(resource_profile=profile).source_resolver

    assert resolver.resource_profile is profile
    assert resolver.requester.settings.timeout == (10, 60)
    assert resolver.requester.settings.max_in_flight == 2


def test_arrayexpress_canonicalizes_typed_magetab_package_into_memory() -> None:
    FakeResolver.calls = []
    result = ArrayExpressWrapper(source_resolver=FakeResolver(), parser=FakeParser()).collect_accession_metadata(
        [record()]
    )

    assert FakeResolver.calls == [{
        "source": "E-MTAB-1", "sdrf_sources": None
    }]
    assert result[0]["metadata_repository"] == "arrayexpress"
    assert result[0]["metadata_source"] == "ae2json"
    assert result[0]["metadata_status"] == "available"
    assert result[0]["accession_metadata"] == package()


def test_arrayexpress_exposes_converter_request_metrics() -> None:
    from meta_standards_converter.sources.contracts import RequestMetrics

    class Resolver(FakeResolver):
        def metrics(self):
            return RequestMetrics(2, 1, 0.5)

    wrapper = ArrayExpressWrapper(source_resolver=Resolver(), parser=FakeParser())
    wrapper.collect_accession_metadata([record()])

    assert wrapper.provider_attempts == 2
    assert wrapper.retry_count == 1
    assert wrapper.rate_wait_seconds == 0.5


def test_arrayexpress_checkpoint_resume_is_offline_and_rebuilds_record(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "atlas.sqlite3")
    FakeResolver.calls = []
    wrapper = ArrayExpressWrapper(source_resolver=FakeResolver(), parser=FakeParser())
    wrapper.collect_accession_metadata([record()], checkpoint_store=store)
    latest = {**record(), "publications": [{"pmid": "new"}]}

    result = ArrayExpressWrapper(
        source_resolver=object(), parser=object()
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

    wrapper = ArrayExpressWrapper(source_resolver=Fetcher(), parser=Parser())
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
    FakeResolver.calls = []

    result = ArrayExpressWrapper(source_resolver=FakeResolver(), parser=FakeParser()).collect_accession_metadata(
        [record()], checkpoint_store=store
    )

    assert FakeResolver.calls
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
    class PartialParser:
        def parse(self, source):
            if source.source == "E-MTAB-1":
                raise ValueError("invalid MAGE-TAB")
            return None

    result = ArrayExpressWrapper(
        source_resolver=FakeResolver(), parser=PartialParser()
    ).collect_accession_metadata([record(), record("E-MTAB-2")])

    assert [item["metadata_status"] for item in result] == ["error", "unavailable"]
    assert all(item["accession_metadata"] is None for item in result)
