import logging

import pytest
import requests

from ThematicAtlases.wrappers import epmc as epmc_module
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


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


def test_collect_accessions_calls_collect_publications(monkeypatch) -> None:
    expected = [{"epmc_id": "1"}]

    def fake_collect_publications(self, queries: list[str]) -> list[dict]:
        assert queries == ["fibrosis"]
        return expected

    monkeypatch.setattr(
        EuropePMCWrapper,
        "collect_publications",
        fake_collect_publications,
    )

    assert EuropePMCWrapper().collect_accessions(queries=["fibrosis"]) == expected


def test_collect_publications_returns_empty_without_queries(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    assert EuropePMCWrapper().collect_publications(queries=[]) == []
    assert calls == []


def test_collect_publications_sends_expected_search_params(monkeypatch) -> None:
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(
            {
                "resultList": {
                    "result": [
                        {
                            "id": "123",
                            "source": "MED",
                            "pmid": "123",
                            "pmcid": "PMC123",
                            "doi": "10.1/example",
                            "title": "Fibrosis study",
                            "authorString": "A Author",
                            "abstractText": "Abstract",
                            "affiliation": "Institute",
                            "fullTextUrlList": {
                                "fullTextUrl": [{"url": "https://example.org/full"}]
                            },
                            "firstPublicationDate": "2024-01-01",
                        }
                    ]
                },
                "nextCursorMark": None,
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    result = EuropePMCWrapper(
        page_limit=1,
        page_size=12,
        timeout=34,
    ).collect_publications(queries=["fibrosis"])

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            {
                "query": "fibrosis",
                "format": "json",
                "resultType": "core",
                "pageSize": 12,
                "cursorMark": "*",
                "synonym": "TRUE",
            },
            34,
        )
    ]
    assert result == [
        {
            "query": "fibrosis",
            "epmc_id": "123",
            "source": "MED",
            "pmid": "123",
            "pmcid": "PMC123",
            "doi": "10.1/example",
            "title": "Fibrosis study",
            "authorString": "A Author",
            "abstractText": "Abstract",
            "affiliation": "Institute",
            "fullTextUrls": ["https://example.org/full"],
            "firstPublicationDate": "2024-01-01",
        }
    ]


def test_collect_publications_follows_cursor_pagination(monkeypatch) -> None:
    cursors = []
    responses = [
        FakeResponse(
            {
                "resultList": {"result": [{"id": "1"}]},
                "nextCursorMark": "page-2",
            }
        ),
        FakeResponse(
            {
                "resultList": {"result": [{"id": "2"}]},
                "nextCursorMark": None,
            }
        ),
    ]

    def fake_get(url, params, timeout):
        cursors.append(params["cursorMark"])
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(page_limit=5).collect_publications(queries=["q"])

    assert cursors == ["*", "page-2"]
    assert [row["epmc_id"] for row in result] == ["1", "2"]


def test_collect_publications_retries_transient_failures(monkeypatch) -> None:
    calls = []
    responses = [
        FakeResponse({}, status_code=503),
        FakeResponse(
            {
                "resultList": {"result": [{"id": "1"}]},
                "nextCursorMark": None,
            }
        ),
    ]

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=1).collect_publications(queries=["q"])

    assert len(calls) == 2
    assert result[0]["epmc_id"] == "1"


def test_collect_publications_honors_retry_after(monkeypatch) -> None:
    sleeps = []
    responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "3"}),
        FakeResponse({"resultList": {"result": []}, "nextCursorMark": None}),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)

    EuropePMCWrapper(max_retries=1).collect_publications(queries=["q"])

    assert sleeps == [3.0]


def test_collect_publications_logs_search_stats(monkeypatch, caplog) -> None:
    responses = [
        FakeResponse(
            {
                "hitCount": 3,
                "resultList": {"result": [{"id": "1"}, {"id": "2"}]},
                "nextCursorMark": "page-2",
            }
        ),
        FakeResponse(
            {
                "hitCount": 3,
                "resultList": {"result": [{"id": "3"}]},
                "nextCursorMark": None,
            }
        ),
    ]

    def fake_get(url, params, timeout):
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    result = EuropePMCWrapper(page_limit=5).collect_publications(queries=["q"])

    assert [row["epmc_id"] for row in result] == ["1", "2", "3"]
    assert "total_hits=3" in caplog.text
    assert "collected_hits=3" in caplog.text
    assert "pages_fetched=2" in caplog.text
    assert "page_limit_reached=False" in caplog.text


def test_collect_publications_logs_page_limit_reached(monkeypatch, caplog) -> None:
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "hitCount": 2,
                "resultList": {"result": [{"id": "1"}]},
                "nextCursorMark": "page-2",
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    EuropePMCWrapper(page_limit=1).collect_publications(queries=["q"])

    assert "total_hits=2" in caplog.text
    assert "collected_hits=1" in caplog.text
    assert "pages_fetched=1" in caplog.text
    assert "page_limit_reached=True" in caplog.text


def test_collect_publications_logs_empty_page_as_fetched(monkeypatch, caplog) -> None:
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "hitCount": 0,
                "resultList": {"result": []},
                "nextCursorMark": None,
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    result = EuropePMCWrapper().collect_publications(queries=["q"])

    assert result == []
    assert "total_hits=0" in caplog.text
    assert "collected_hits=0" in caplog.text
    assert "pages_fetched=1" in caplog.text
