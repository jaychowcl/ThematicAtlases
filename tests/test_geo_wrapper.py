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
    accessions_to_gse: dict[str, str | None] = {
        "GSE1": "GSE1",
        "GSM1": "GSE1",
        "GDS1": "GSE1",
        "GPL1": None,
    }

    def get_gse(self, accession: str) -> str | None:
        self.__class__.accessions.append(accession)
        return self.accessions_to_gse.get(accession)


def test_collect_accession_metadata_keeps_gse_and_publications() -> None:
    FakeGEOWrapper.accessions = []
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
        }
    ]
    assert FakeGEOWrapper.accessions == ["GSE1"]


def test_collect_accession_metadata_resolves_gsm_and_preserves_original_metadata() -> None:
    FakeGEOWrapper.accessions = []
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


def test_get_gse_retries_transient_failures(monkeypatch) -> None:
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
