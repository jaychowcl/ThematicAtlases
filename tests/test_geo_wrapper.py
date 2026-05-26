import logging

import requests

from ThematicAtlases.wrappers import geo as geo_module
from ThematicAtlases.wrappers.geo import GEOWrapper


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
        "GSM1": "GSE1",
        "GDS1": "GSE1",
        "GPL1": None,
    }
    metadata_packages: dict[str, list[dict]] = {
        "GSE1": [
            {
                "series": {
                    "accession": [
                        {
                            "value": "GSE1",
                        }
                    ]
                }
            }
        ],
    }

    def get_gse(self, accession: str) -> str | None:
        self.__class__.accessions.append(accession)
        return self.accessions_to_gse.get(accession)

    def _gse_metadata_packages(self, gse_accession: str) -> list[dict]:
        self.__class__.metadata_calls.append(gse_accession)
        return self.metadata_packages.get(gse_accession, [])


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

    assert FakeGEOWrapper().collect_accession_metadata(jsons=records) == [
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
            "metadata_source": "geo2json",
            "metadata_status": "available",
            "accession_metadata": {
                "series": {
                    "accession": [
                        {
                            "value": "GSE1",
                        }
                    ]
                }
            },
        }
    ]
    assert FakeGEOWrapper.accessions == ["GSE1"]
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
    assert result[0]["accession_metadata"] == {
        "series": {
            "accession": [
                {
                    "value": "GSE1",
                }
            ]
        }
    }
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
            "GSE1": [
                {
                    "series": {
                        "accession": [
                            {
                                "value": "GSE1",
                            }
                        ]
                    }
                },
                {
                    "series": {
                        "accession": [
                            {
                                "value": "GSE2",
                            }
                        ]
                    }
                },
            ]
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
            "GSE1": [
                {
                    "series": {
                        "accession": [
                            {
                                "value": "GSE2",
                            }
                        ]
                    }
                }
            ],
            "GSE3": [
                {
                    "series": {
                        "accession": [
                            {
                                "value": "GSE2",
                            }
                        ]
                    }
                }
            ],
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
            "metadata_source": "geo2json",
            "metadata_status": "error",
            "accession_metadata": None,
            "publications": [{"source": "MED", "epmc_id": "1"}],
            "original_datalinks": [{"datalink_id": "GSE1"}],
        },
        {
            "datalink_id": "GSE1",
            "metadata_repository": "geo",
            "metadata_source": "geo2json",
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
        def _gse_metadata_packages(self, gse_accession: str) -> list[dict]:
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
    assert result[0]["metadata_source"] == "geo2json"
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


def test_gse_metadata_packages_calls_geo2json_convert(monkeypatch) -> None:
    calls = []

    class FakeGeo2JsonConverter:
        def convert(self, **kwargs):
            calls.append(kwargs)
            return [{"series": {"accession": [{"value": "GSE1"}]}}]

    monkeypatch.setattr(
        geo_module,
        "geo2json",
        lambda: FakeGeo2JsonConverter(),
    )

    assert GEOWrapper()._gse_metadata_packages(gse_accession="GSE1") == [
        {"series": {"accession": [{"value": "GSE1"}]}}
    ]
    assert calls == [
        {
            "gse": "GSE1",
            "related_series": True,
            "remove_empty": True,
            "enrich": True,
            "out": None,
        }
    ]


def test_collect_accession_metadata_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=geo_module.__name__)

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


def test_collect_gse_metadata_records_logs_progress_and_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=geo_module.__name__)

    FakeGEOWrapper()._collect_gse_metadata_records(
        records=[
            {
                "datalink_id": "GSE1",
                "publications": [],
                "original_datalinks": [],
            }
        ]
    )

    assert "GEO metadata progress gse_index=1 gse_total=1 gse_accession=GSE1" in caplog.text
    assert "metadata_packages=1" in caplog.text
    assert "output_records=1" in caplog.text


def test_deduplicate_gse_jsons_logs_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=geo_module.__name__)

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
    caplog.set_level(logging.DEBUG, logger=geo_module.__name__)

    assert GEOWrapper(max_retries=1).get_gse("GSM1") is None
    assert len(calls) == 2
    assert "GEO retry status=503 attempt=1" in caplog.text
    assert "GEO ESearch request accession='GSM1'" in caplog.text


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
