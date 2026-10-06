import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
import pytest

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.integrations import geo as geo_module
from ThematicAtlases.wrappers.geo import GEOWrapper
from ThematicAtlases.wrappers.enrichment import RetryTags
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.miniml_boundary import checkpoint_payload
from meta_standards_converter.miniml import MINiMLCodec


def invalid_reference_package(accession: str = "GSE1") -> dict:
    value = v2_package(accession)
    value["sample"] = [{
        "iid": "GSM1",
        "platform_ref": {"ref": "GPL-MISSING"},
        "channel": [],
    }]
    return value


def v2_package(accession: str = "GSE1") -> dict:
    return {
        "miniml_schema_version": "3.1",
        "source": {"format": "GEO MINiML"},
        "database": [],
        "organization": [],
        "contributor": [],
        "platform": [],
        "sample": [],
        "series": {"iid": accession, "accession": [{"value": accession}]},
    }


class FakeResponse:
    def __init__(
        self,
        payload: dict,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeGEOWrapper(GEOWrapper):
    accessions: list[str] = []
    metadata_calls: list[str] = []
    accessions_to_gse: dict[str, str | None] = {
        "GSE1": "GSE1",
        "GSE2": "GSE2",
        "GSM1": "GSE1",
        "GDS1": "GSE1",
        "GPL1": None,
    }
    metadata_packages: dict[str, list[dict]] = {
        "GSE1": [v2_package("GSE1")],
    }

    def __init__(self, **kwargs):
        owner = self
        class InjectedConverter:
            def convert(self, accession, **options):
                from meta_standards_converter.converters.unified.contracts import ConversionBatchResult, ConversionItemResult
                return ConversionBatchResult([ConversionItemResult("input_1", accession,
                    execution="succeeded", completeness="complete", validation="valid", status="complete",
                    payload=owner.metadata_packages_for_test(accession))])
        super().__init__(converter=InjectedConverter(), **kwargs)

    def get_gse(self, accession: str) -> str | None:
        self.__class__.accessions.append(accession)
        return self.accessions_to_gse.get(accession)

    def metadata_packages_for_test(self, gse_accession: str) -> list[dict]:
        self.__class__.metadata_calls.append(gse_accession)
        return self.metadata_packages.get(gse_accession, [])


def test_geo_wrapper_accepts_an_injected_record_policy() -> None:
    class RecordPolicy:
        @staticmethod
        def deduplicate_gse_jsons(records):
            assert records == [{"datalink_id": "GSE1"}]
            return [{"datalink_id": "injected"}]

    wrapper = GEOWrapper(record_policy=RecordPolicy())

    assert wrapper._deduplicate_gse_jsons([{"datalink_id": "GSE1"}]) == [
        {"datalink_id": "injected"}
    ]





def test_geo_wrapper_uses_optional_ncbi_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "secret-key")

    wrapper = GEOWrapper(tool="fibrosis_atlas", email="atlas@example.org")

    assert wrapper._ncbi_identity.params() == {
        "tool": "fibrosis_atlas",
        "email": "atlas@example.org",
        "api_key": "secret-key",
    }


def test_geo_metadata_resume_skips_completed_gse(tmp_path) -> None:
    records = [
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "publications": []},
        {"datalink_id": "GSE2", "datalink_id_scheme": "GEO", "publications": []},
    ]
    store = CheckpointStore(tmp_path / "resume_state.sqlite")

    class InterruptingGeo(FakeGEOWrapper):
        calls = []

        def metadata_packages_for_test(self, gse_accession):
            self.__class__.calls.append(gse_accession)
            if gse_accession == "GSE2":
                raise KeyboardInterrupt()
            return [v2_package(gse_accession)]

    try:
        InterruptingGeo().collect_accession_metadata(
            records, checkpoint_store=store
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("test interruption must propagate")

    class CompletingGeo(FakeGEOWrapper):
        calls = []

        def metadata_packages_for_test(self, gse_accession):
            self.__class__.calls.append(gse_accession)
            return [v2_package(gse_accession)]

    result = CompletingGeo().collect_accession_metadata(
        records, checkpoint_store=store
    )

    assert InterruptingGeo.calls == ["GSE1", "GSE2"]
    assert CompletingGeo.calls == ["GSE2"]
    assert [record["datalink_id"] for record in result] == ["GSE1", "GSE2"]








def test_geo_metadata_checkpoint_rebuilds_latest_publication_provenance(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    wrapper = FakeGEOWrapper()
    wrapper.collect_accession_metadata(
        [
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "GEO",
                "publications": [{"source": "MED", "epmc_id": "1"}],
            }
        ],
        checkpoint_store=store,
    )

    result = wrapper.collect_accession_metadata(
        [
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "GEO",
                "publications": [
                    {"source": "MED", "epmc_id": "1"},
                    {"source": "MED", "epmc_id": "2"},
                ],
            }
        ],
        checkpoint_store=store,
    )

    assert result[0]["publications"] == [
        {"source": "MED", "epmc_id": "1"},
        {"source": "MED", "epmc_id": "2"},
    ]
    assert "packages" in store.get("metadata_conversion", "geo:GSE1")["payload"]




def test_offline_geo_resume_marks_legacy_metadata_checkpoint_pending(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put(
        "geo_resolution", "GSE1", 1, "available", payload={"gse_accession": "GSE1"}
    )
    store.put(
        "geo_metadata", "GSE1", 1, "available", payload={"packages": [{"mage_tab": {}}]}
    )

    result = GEOWrapper().available_accession_metadata(
        [{"datalink_id": "GSE1", "publications": []}], store
    )

    assert result[0]["metadata_status"] == "pending"
    assert result[0]["accession_metadata"] is None


@pytest.mark.parametrize(
    "checkpoint_status, metadata_status",
    [
        ("retryable_error", "pending"),
        ("terminal_error", "error"),
    ],
)
def test_offline_geo_resolution_preserves_retry_policy_status(
    tmp_path,
    checkpoint_status,
    metadata_status,
) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    store.put(
        "geo_resolution",
        "GDS1",
        1,
        checkpoint_status,
        error="resolution failed",
    )

    result = GEOWrapper().available_accession_metadata(
        [{"datalink_id": "GDS1", "publications": []}], store
    )

    assert result[0]["metadata_status"] == metadata_status
    assert result[0]["accession_metadata"] is None


def test_geo_metadata_item_lock_prevents_duplicate_concurrent_downloads(tmp_path) -> None:
    store_path = tmp_path / "resume_state.sqlite"
    started = threading.Event()
    release = threading.Event()
    calls = []

    class SlowGeo(FakeGEOWrapper):
        def metadata_packages_for_test(self, gse_accession):
            calls.append(gse_accession)
            started.set()
            assert release.wait(timeout=5)
            return [v2_package(gse_accession)]

    record = {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "publications": []}

    def collect():
        return SlowGeo().collect_accession_metadata(
            [record], checkpoint_store=CheckpointStore(store_path)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(collect)
        assert started.wait(timeout=5)
        second = executor.submit(collect)
        release.set()
        assert first.result()[0]["metadata_status"] == "available"
        assert second.result()[0]["metadata_status"] == "available"

    assert calls == ["GSE1"]












def test_collect_accession_metadata_keeps_gse_and_publications() -> None:
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.metadata_calls = []
    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    results = FakeGEOWrapper().collect_accession_metadata(jsons=records)
    assert results[0]["metadata_conversion"]["outcome"]["validation"] == "valid"
    for result in results:
        result.pop("metadata_conversion")
    assert results == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
            "original_datalinks": [
                {
                    "datalink_id": "GSE1",
                    "datalink_id_scheme": "GEO",
                    "datalink_url": "https://example.org/GSE1",
                    "datalink_category": "GEO",
                }
            ],
            "metadata_repository": "geo",
            "accession_repository": "geo",
            "metadata_source": "msc.convert",
            "metadata_status": "available",
            "accession_metadata": v2_package("GSE1"),
        }
    ]
    assert FakeGEOWrapper.accessions == []
    assert FakeGEOWrapper.metadata_calls == ["GSE1"]


def test_collect_accession_metadata_resolves_gsm_and_preserves_original_metadata() -> None:
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.metadata_calls = []
    records = [
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    result = FakeGEOWrapper().collect_accession_metadata(jsons=records)

    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["original_datalinks"] == [
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
        }
    ]
    assert result[0]["publications"] == [{"source": "MED", "epmc_id": "1"}]
    assert result[0]["metadata_status"] == "available"
    assert result[0]["accession_metadata"] == v2_package("GSE1")
    assert FakeGEOWrapper.metadata_calls == ["GSE1"]


def test_collect_accession_metadata_resolves_gds() -> None:
    records = [
        {
            "datalink_id": "GDS1",
            "datalink_id_scheme": "GEO",
            "publications": [],
        }
    ]

    assert FakeGEOWrapper().collect_accession_metadata(jsons=records)[0][
        "datalink_id"
    ] == "GSE1"


def test_collect_accession_metadata_drops_gpl_and_unresolved() -> None:
    records = [
        {"datalink_id": "GPL1", "datalink_id_scheme": "GEO", "publications": []},
        {"datalink_id": "GSM404", "datalink_id_scheme": "GEO", "publications": []},
    ]

    assert FakeGEOWrapper().collect_accession_metadata(jsons=records) == []


def test_collect_accession_metadata_collapses_same_gse_and_merges_metadata() -> None:
    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                }
            ],
        },
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                },
                {
                    "source": "MED",
                    "epmc_id": "2",
                    "pmid": "2",
                    "pmcid": "PMC2",
                    "doi": "10.1/two",
                },
            ],
        },
    ]

    result = FakeGEOWrapper().collect_accession_metadata(jsons=records)

    assert len(result) == 1
    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["datalink_url"] == "https://example.org/GSE1"
    assert result[0]["original_datalinks"] == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        },
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
        },
    ]
    assert result[0]["publications"] == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
        },
        {
            "source": "MED",
            "epmc_id": "2",
            "pmid": "2",
            "pmcid": "PMC2",
            "doi": "10.1/two",
        },
    ]
    assert result[0]["metadata_status"] == "available"


def test_collect_accession_metadata_includes_related_gse_records() -> None:
    class LocalGEOWrapper(FakeGEOWrapper):
        metadata_packages = {
            "GSE1": [v2_package("GSE1"), v2_package("GSE2")]
        }

    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    result = LocalGEOWrapper().collect_accession_metadata(jsons=records)

    assert [record["datalink_id"] for record in result] == ["GSE1", "GSE2"]
    assert result[1]["source_datalink_id"] == "GSE1"
    assert result[1]["publications"] == [{"source": "MED", "epmc_id": "1"}]
    assert result[1]["original_datalinks"] == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        }
    ]


def test_collect_accession_metadata_merges_duplicate_related_gse_provenance() -> None:
    class LocalGEOWrapper(FakeGEOWrapper):
        accessions_to_gse = {
            "GSE1": "GSE1",
            "GSE3": "GSE3",
        }
        metadata_packages = {
            "GSE1": [v2_package("GSE2")],
            "GSE3": [v2_package("GSE2")],
        }

    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        },
        {
            "datalink_id": "GSE3",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE3",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "3"}],
        },
    ]

    result = LocalGEOWrapper().collect_accession_metadata(jsons=records)

    assert len(result) == 1
    assert result[0]["datalink_id"] == "GSE2"
    assert result[0]["publications"] == [
        {"source": "MED", "epmc_id": "1"},
        {"source": "MED", "epmc_id": "3"},
    ]
    assert result[0]["original_datalinks"] == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        },
        {
            "datalink_id": "GSE3",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE3",
            "datalink_category": "GEO",
        },
    ]


def test_deduplicate_gse_jsons_keeps_first_available_metadata() -> None:
    records = [
        {
            "datalink_id": "GSE1",
            "metadata_repository": "geo",
            "accession_repository": "geo",
            "metadata_source": "msc.convert",
            "metadata_status": "error",
            "accession_metadata": None,
            "publications": [{"source": "MED", "epmc_id": "1"}],
            "original_datalinks": [{"datalink_id": "GSE1"}],
        },
        {
            "datalink_id": "GSE1",
            "metadata_repository": "geo",
            "accession_repository": "geo",
            "metadata_source": "msc.convert",
            "metadata_status": "available",
            "accession_metadata": {
                "series": {
                    "accession": "GSE1",
                }
            },
            "publications": [{"source": "MED", "epmc_id": "2"}],
            "original_datalinks": [{"datalink_id": "GSM1"}],
        },
    ]

    result = GEOWrapper()._deduplicate_gse_jsons(jsons=records)

    assert result[0]["metadata_status"] == "available"
    assert result[0]["accession_metadata"] == {
        "series": {
            "accession": "GSE1",
        }
    }
    assert result[0]["publications"] == [
        {"source": "MED", "epmc_id": "1"},
        {"source": "MED", "epmc_id": "2"},
    ]
    assert result[0]["original_datalinks"] == [
        {"datalink_id": "GSE1"},
        {"datalink_id": "GSM1"},
    ]


def test_collect_accession_metadata_keeps_record_when_metadata_collection_fails() -> None:
    class LocalGEOWrapper(FakeGEOWrapper):
        def metadata_packages_for_test(self, gse_accession: str) -> list[dict]:
            raise RuntimeError("boom")

    result = LocalGEOWrapper().collect_accession_metadata(
        jsons=[
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "GEO",
                "publications": [],
            }
        ]
    )

    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["metadata_repository"] == "geo"
    assert result[0]["metadata_source"] == "msc.convert"
    assert result[0]["metadata_status"] == "error"
    assert result[0]["accession_metadata"] is None


def test_package_gse_accession_extracts_series_accession() -> None:
    assert (
        GEOWrapper()._package_gse_accession(
            package={
                "series": {
                    "accession": [
                        {
                            "value": "gse123",
                        }
                    ]
                }
            }
        )
        == "GSE123"
    )


def test_package_gse_accession_extracts_string_series_accession() -> None:
    assert (
        GEOWrapper()._package_gse_accession(
            package={
                "series": {
                    "accession": "gse456",
                }
            }
        )
        == "GSE456"
    )














def test_collect_accession_metadata_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=geo_module.logger.name)

    FakeGEOWrapper().collect_accession_metadata(
        jsons=[
            {"datalink_id": "GSE1", "datalink_id_scheme": "GEO"},
            {"datalink_id": "GPL1", "datalink_id_scheme": "GEO"},
        ]
    )

    assert "stage=resolve-accessions input_records=2" in caplog.text
    assert "resolved_records=1" in caplog.text
    assert "dropped_records=1" in caplog.text
    assert "stage=collect-gse-metadata gse_records=1" in caplog.text
    assert "output_records=1" in caplog.text




def test_deduplicate_gse_jsons_logs_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=geo_module.logger.name)

    GEOWrapper()._deduplicate_gse_jsons(
        jsons=[
            {
                "datalink_id": "GSE1",
                "publications": [{"source": "MED", "epmc_id": "1"}],
                "original_datalinks": [{"datalink_id": "GSE1"}],
            },
            {
                "datalink_id": "GSE1",
                "publications": [{"source": "MED", "epmc_id": "2"}],
                "original_datalinks": [{"datalink_id": "GSM1"}],
            },
        ]
    )

    assert "GEO GSE dedupe stats" in caplog.text
    assert "input_rows=2" in caplog.text
    assert "output_rows=1" in caplog.text
    assert "duplicate_rows_collapsed=1" in caplog.text
    assert "publication_links=2" in caplog.text
    assert "original_datalink_links=2" in caplog.text


def test_get_gse_returns_gse_without_network(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSE123") == "GSE123"
    assert calls == []


def test_get_gse_normalizes_whitespace_and_case_without_network(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("  gse123  ") == "GSE123"
    assert calls == []


def test_get_gse_returns_none_for_gpl_without_network(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GPL96") is None
    assert calls == []


def test_get_gse_resolves_gds_from_exact_summary(monkeypatch) -> None:
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["505"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["505"],
                    "505": {
                        "accession": "GDS505",
                        "gse": "781",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GDS505") == "GSE781"


def test_get_gse_resolves_gsm_from_exact_summary_when_related_records_return(
    monkeypatch,
) -> None:
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["200000781", "300011805"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["200000781", "300011805"],
                    "200000781": {
                        "accession": "GSE781",
                        "gse": "781",
                    },
                    "300011805": {
                        "accession": "GSM11805",
                        "gse": "781",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSM11805") == "GSE781"


def test_get_gse_returns_first_gse_when_summary_has_multiple_values(monkeypatch) -> None:
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["1"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["1"],
                    "1": {
                        "accession": "GSM1",
                        "gse": "781;11805",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSM1") == "GSE781"


def test_get_gse_returns_none_for_empty_search(monkeypatch) -> None:
    def fake_get(url, params, timeout):
        return FakeResponse({"esearchresult": {"idlist": []}})

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSM1") is None


def test_get_gse_returns_none_when_no_exact_accession_match(monkeypatch) -> None:
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["1"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["1"],
                    "1": {
                        "accession": "GSE1",
                        "gse": "1",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSM1") is None


def test_get_gse_returns_none_for_malformed_accession(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("") is None
    assert GEOWrapper().get_gse("ERR123") is None
    assert calls == []


def test_get_gse_returns_none_when_summary_has_no_gse(monkeypatch) -> None:
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["1"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["1"],
                    "1": {
                        "accession": "GSM1",
                        "gse": "",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert GEOWrapper().get_gse("GSM1") is None


def test_get_gse_sends_expected_request_params(monkeypatch) -> None:
    calls = []
    responses = [
        FakeResponse({"esearchresult": {"idlist": ["1"]}}),
        FakeResponse(
            {
                "result": {
                    "uids": ["1"],
                    "1": {
                        "accession": "GSM1",
                        "gse": "1",
                    },
                }
            }
        ),
    ]

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)

    assert (
        GEOWrapper(
            api_key="key",
            tool="tool",
            email="email@example.org",
            timeout=12,
        ).get_gse("GSM1")
        == "GSE1"
    )
    assert calls == [
        (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {
                "db": "gds",
                "term": "GSM1[ACCN]",
                "retmode": "json",
                "retmax": 20,
                "tool": "tool",
                "email": "email@example.org",
                "api_key": "key",
            },
            12,
        ),
        (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            {
                "db": "gds",
                "id": "1",
                "retmode": "json",
                "tool": "tool",
                "email": "email@example.org",
                "api_key": "key",
            },
            12,
        ),
    ]


def test_get_gse_retries_transient_failures(monkeypatch, caplog) -> None:
    calls = []
    responses = [
        FakeResponse({}, status_code=503),
        FakeResponse({"esearchresult": {"idlist": []}}),
    ]

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)
    monkeypatch.setattr(geo_module.time, "sleep", lambda delay: None)
    caplog.set_level(logging.DEBUG, logger=geo_module.logger.name)

    assert GEOWrapper(max_retries=1).get_gse("GSM1") is None
    assert len(calls) == 2
    assert "GEO retry status=503 attempt=1" in caplog.text
    assert "GEO ESearch request accession='GSM1'" in caplog.text


def test_get_gse_retries_public_provider_forbidden_response(monkeypatch) -> None:
    calls = []
    responses = [
        FakeResponse({}, status_code=403),
        FakeResponse({"esearchresult": {"idlist": []}}),
    ]

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)
    monkeypatch.setattr(geo_module.time, "sleep", lambda delay: None)

    assert GEOWrapper(max_retries=1).get_gse("GSM1") is None
    assert len(calls) == 2


def test_get_gse_honors_retry_after(monkeypatch) -> None:
    sleeps = []
    responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "3"}),
        FakeResponse({"esearchresult": {"idlist": []}}),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(geo_module.requests, "get", fake_get)
    monkeypatch.setattr(geo_module.time, "sleep", sleeps.append)

    GEOWrapper(max_retries=1).get_gse("GSM1")

    assert sleeps == [3.0]
