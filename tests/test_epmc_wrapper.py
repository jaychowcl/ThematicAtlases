import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from meta_standards_converter.xml_safety import (
    UnsafeXMLDocumentError,
    XMLSizeLimitError,
)

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers import epmc as epmc_module
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


def test_epmc_wrapper_accepts_an_injected_publication_policy() -> None:
    class PublicationPolicy:
        @staticmethod
        def merge_accessions(datalink_accessions, scraped_accessions):
            assert datalink_accessions == [{"datalink_id": "GSE1"}]
            assert scraped_accessions == []
            return [{"datalink_id": "injected"}]

    wrapper = EuropePMCWrapper(publication_policy=PublicationPolicy())

    assert wrapper.merge_accessions([{"datalink_id": "GSE1"}], []) == [
        {"datalink_id": "injected"}
    ]


def test_collect_accessions_adds_injected_link_graph_after_text(monkeypatch) -> None:
    class LinkGraph:
        def discover(self, publications, checkpoint_store=None, cached_only=False):
            assert [publication["pmid"] for publication in publications] == ["1"]
            assert checkpoint_store is None
            assert cached_only is False
            return [{
                "datalink_id": "GSE3",
                "discovery_sources": ["ncbi_pubmed_gds"],
                "publications": publications,
            }]

    wrapper = EuropePMCWrapper(
        request_delay=0,
        link_graph_provider=LinkGraph(),
    )
    publication = {"source": "MED", "epmc_id": "1", "pmid": "1"}
    monkeypatch.setattr(wrapper, "collect_publications", lambda **_kwargs: [publication])
    monkeypatch.setattr(wrapper, "collect_datalinks", lambda **_kwargs: [])
    monkeypatch.setattr(wrapper, "collect_publication_texts", lambda **_kwargs: [publication])
    monkeypatch.setattr(wrapper, "accessions_from_fulltexts", lambda *_args, **_kwargs: [])

    records = wrapper.collect_accessions(["query"])

    assert [record["datalink_id"] for record in records] == ["GSE3"]
    assert records[0]["discovery_sources"] == ["ncbi_pubmed_gds"]


def test_collect_accessions_publishes_main_phase_transition_before_text(
    tmp_path,
    monkeypatch,
) -> None:
    store = CheckpointStore(tmp_path / "atlas_run.sqlite3")
    wrapper = EuropePMCWrapper()
    publications = [{"source": "MED", "epmc_id": "1", "abstractText": "text"}]

    def collect_publications(**_kwargs):
        phase = store.get_meta("pipeline_position")
        assert phase["phase"] == "datalinks"
        return publications

    def collect_datalinks(**_kwargs):
        phase = store.get_meta("pipeline_position")
        assert phase["phase"] == "datalinks"
        return []

    def collect_publication_texts(**_kwargs):
        phase = store.get_meta("pipeline_position")
        assert phase["phase"] == "downstream"
        return publications

    monkeypatch.setattr(wrapper, "collect_publications", collect_publications)
    monkeypatch.setattr(wrapper, "collect_datalinks", collect_datalinks)
    monkeypatch.setattr(wrapper, "collect_publication_texts", collect_publication_texts)

    assert wrapper.collect_accessions(
        queries=["fibrosis"],
        checkpoint_store=store,
    ) == []
    assert store.get_meta("pipeline_position")["phase"] == "downstream"


def test_datalinks_and_full_text_share_checkpoint_provider_pacing(
    tmp_path,
    monkeypatch,
) -> None:
    store = CheckpointStore(tmp_path / "atlas_run.sqlite3")
    slots = []
    monkeypatch.setattr(
        store,
        "wait_for_provider_slot",
        lambda provider, *, min_interval_seconds: slots.append(
            (provider, min_interval_seconds)
        ),
        raising=False,
    )
    wrapper = EuropePMCWrapper(request_delay=0.25)
    monkeypatch.setattr(
        wrapper,
        "_datalinks",
        lambda **_kwargs: {"dataLinkList": {"Category": []}},
    )
    monkeypatch.setattr(
        wrapper,
        "_full_text_xml",
        lambda **_kwargs: "<article><body><p>Full text.</p></body></article>",
    )
    monkeypatch.setattr(epmc_module.time, "sleep", lambda _delay: None)
    publication = {
        "source": "MED",
        "epmc_id": "1",
        "pmcid": "PMC1",
        "abstractText": "Abstract",
    }

    wrapper.collect_datalinks([publication], checkpoint_store=store)
    wrapper.collect_publication_texts([publication], checkpoint_store=store)

    assert slots == []


class FakeResponse:
    def __init__(
        self,
        payload: dict,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
    ):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.close_calls = 0

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def close(self) -> None:
        self.close_calls += 1


def _geo_datalink_response(accession: str) -> dict:
    return {
        "dataLinkList": {
            "Category": [
                {
                    "Name": "GEO",
                    "Section": [
                        {
                            "Linklist": {
                                "Link": [
                                    {
                                        "Target": {
                                            "Identifier": {
                                                "ID": accession,
                                                "IDScheme": "GEO",
                                                "IDURL": f"https://example.org/{accession}",
                                            }
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                }
            ]
        }
    }


def _datalinks_xml(
    *categories: tuple[str, str | None, str | None, str | None],
) -> str:
    category_xml = []
    for name, identifier, scheme, url in categories:
        link_xml = ""
        if identifier is not None:
            link_xml = f"""
              <epmc:Section>
                <epmc:Linklist>
                  <slx:Link>
                    <slx:Target>
                      <slx:Identifier>
                        <slx:ID>{identifier}</slx:ID>
                        <slx:IDScheme>{scheme or ''}</slx:IDScheme>
                        <slx:IDURL>{url or ''}</slx:IDURL>
                      </slx:Identifier>
                    </slx:Target>
                  </slx:Link>
                </epmc:Linklist>
              </epmc:Section>
            """
        category_xml.append(
            f"""
            <epmc:Category>
              <epmc:Name>{name}</epmc:Name>
              {link_xml}
            </epmc:Category>
            """
        )
    return f"""
    <responseWrapper xmlns:slx="http://www.scholix.org" xmlns:epmc="https://www.europepmc.org/data">
      <dataLinkList>{''.join(category_xml)}</dataLinkList>
    </responseWrapper>
    """


def test_default_request_delay_is_gentle_and_can_be_overridden() -> None:
    assert EuropePMCWrapper()._request_settings["request_delay"] == 0.5
    assert EuropePMCWrapper(request_delay=0)._request_settings["request_delay"] == 0

    with pytest.raises(ValueError, match="request_delay must not be negative"):
        EuropePMCWrapper(request_delay=-0.1)


def test_epmc_forwards_configured_ncbi_identity_to_graph_provider(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "secret-key")

    wrapper = EuropePMCWrapper(
        ncbi_tool="fibrosis_atlas",
        ncbi_email="atlas@example.org",
    )

    assert wrapper._link_graph_provider._ncbi_identity.params() == {
        "tool": "fibrosis_atlas",
        "email": "atlas@example.org",
        "api_key": "secret-key",
    }


def test_collect_publications_resumes_from_completed_search_page(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    wrapper = EuropePMCWrapper(page_limit=3)
    calls = []

    def interrupting_search(query, cursor):
        calls.append(cursor)
        if cursor == "*":
            return {
                "hitCount": 2,
                "nextCursorMark": "page-2",
                "resultList": {"result": [{"id": "1", "source": "MED"}]},
            }
        raise KeyboardInterrupt()

    wrapper._search = interrupting_search
    with pytest.raises(KeyboardInterrupt):
        wrapper.collect_publications(["fibrosis"], checkpoint_store=store)

    resumed_calls = []

    def completing_search(query, cursor):
        resumed_calls.append(cursor)
        return {
            "hitCount": 2,
            "nextCursorMark": None,
            "resultList": {"result": [{"id": "2", "source": "MED"}]},
        }

    wrapper._search = completing_search
    publications = wrapper.collect_publications(
        ["fibrosis"], checkpoint_store=store
    )

    assert calls == ["*", "page-2"]
    assert resumed_calls == ["page-2"]
    assert [publication["epmc_id"] for publication in publications] == ["1", "2"]
    assert store.items("search_queries")[0]["status"] == "available"


def test_collect_publications_checkpoints_transient_query_failure(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    wrapper = EuropePMCWrapper(page_limit=1)
    wrapper._search = lambda **kwargs: (_ for _ in ()).throw(
        requests.Timeout("temporary timeout")
    )

    with pytest.raises(requests.Timeout):
        wrapper.collect_publications(["fibrosis"], checkpoint_store=store)

    item = store.items("search_queries")[0]
    assert item["status"] == "retryable_error"
    assert item["failure_category"] == "transient"
    assert item["payload"]["next_cursor"] == "*"


def test_collect_datalinks_resumes_after_last_completed_publication(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume_state.sqlite")
    publications = [
        {"query": "fibrosis", "source": "MED", "epmc_id": "1"},
        {"query": "fibrosis", "source": "MED", "epmc_id": "2"},
    ]
    wrapper = EuropePMCWrapper(request_delay=0)
    calls = []

    def interrupting_datalinks(source, epmc_id):
        calls.append(epmc_id)
        if epmc_id == "2":
            raise KeyboardInterrupt()
        return _geo_datalink_response("GSE1")

    wrapper._datalinks = interrupting_datalinks
    with pytest.raises(KeyboardInterrupt):
        wrapper.collect_datalinks(publications, checkpoint_store=store)

    resumed_calls = []

    def completing_datalinks(source, epmc_id):
        resumed_calls.append(epmc_id)
        return _geo_datalink_response("GSE2")

    wrapper._datalinks = completing_datalinks
    result = wrapper.collect_datalinks(publications, checkpoint_store=store)

    assert calls == ["1", "2"]
    assert resumed_calls == ["2"]
    assert [record["datalink_id"] for record in result] == ["GSE1", "GSE2"]


def test_collect_accessions_calls_collect_publications(monkeypatch) -> None:
    publications = [{"epmc_id": "1", "source": "MED"}]
    datalinks = [{"datalink_id": "GSE1", "publications": []}]
    expected = [
        {
            "datalink_id": "GSE1",
            "publications": [],
            "discovery_sources": ["europe_pmc_datalink"],
        }
    ]
    calls = []

    def fake_collect_publications(
        self,
        queries: list[str],
        max_publications: int | None = None,
    ) -> list[dict]:
        calls.append("publications")
        assert queries == ["fibrosis"]
        assert max_publications is None
        return publications

    def fake_collect_datalinks(self, publications: list[dict]) -> list[dict]:
        calls.append("datalinks")
        assert publications == [{"epmc_id": "1", "source": "MED"}]
        return datalinks

    monkeypatch.setattr(
        EuropePMCWrapper,
        "collect_publications",
        fake_collect_publications,
    )
    monkeypatch.setattr(
        EuropePMCWrapper,
        "collect_datalinks",
        fake_collect_datalinks,
    )

    assert EuropePMCWrapper().collect_accessions(queries=["fibrosis"]) == expected
    assert calls == ["publications", "datalinks"]


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


def test_collect_publications_limits_results_within_page(monkeypatch) -> None:
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
                "hitCount": 3,
                "resultList": {
                    "result": [
                        {"id": "1", "source": "MED"},
                        {"id": "2", "source": "MED"},
                        {"id": "3", "source": "MED"},
                    ]
                },
                "nextCursorMark": "page-2",
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    result = EuropePMCWrapper(page_limit=5).collect_publications(
        queries=["q"],
        max_publications=2,
    )

    assert [publication["epmc_id"] for publication in result] == ["1", "2"]


def test_collect_publications_stops_pagination_at_max_publications(
    monkeypatch,
) -> None:
    cursors = []

    def fake_get(url, params, timeout):
        cursors.append(params["cursorMark"])
        return FakeResponse(
            {
                "hitCount": 4,
                "resultList": {
                    "result": [
                        {"id": "1", "source": "MED"},
                        {"id": "2", "source": "MED"},
                    ]
                },
                "nextCursorMark": "page-2",
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    result = EuropePMCWrapper(page_limit=5, page_size=2).collect_publications(
        queries=["q"],
        max_publications=2,
    )

    assert cursors == ["*"]
    assert [publication["epmc_id"] for publication in result] == ["1", "2"]


def test_collect_publications_rejects_invalid_max_publications() -> None:
    with pytest.raises(ValueError, match="max_publications"):
        EuropePMCWrapper().collect_publications(
            queries=["q"],
            max_publications=0,
        )


def test_collect_publications_applies_independent_query_limits_and_deduplicates(
    monkeypatch,
) -> None:
    responses = {
        "old": [
            {"id": "1", "source": "MED", "pmid": "1", "title": "First"},
            {"id": "2", "source": "MED", "doi": "10.1/shared"},
        ],
        "expanded": [
            {"id": "duplicate", "source": "MED", "doi": "10.1/SHARED"},
            {"id": "3", "source": "MED", "pmcid": "PMC3"},
        ],
    }
    calls = []

    def fake_search(self, query, cursor):
        calls.append(query)
        return {
            "hitCount": len(responses[query]),
            "nextCursorMark": None,
            "resultList": {"result": responses[query]},
        }

    monkeypatch.setattr(EuropePMCWrapper, "_search", fake_search)

    result = EuropePMCWrapper(page_limit=2).collect_publications(
        queries=["old", "expanded"],
        max_publications_per_query=[1, 2],
    )

    assert calls == ["old", "expanded"]
    assert [row["epmc_id"] for row in result] == ["1", "duplicate", "3"]
    assert [row["queries"] for row in result] == [
        ["old"],
        ["expanded"],
        ["expanded"],
    ]


def test_collect_publications_merges_duplicate_query_provenance(monkeypatch) -> None:
    def fake_search(self, query, cursor):
        return {
            "hitCount": 1,
            "nextCursorMark": None,
            "resultList": {
                "result": [
                    {
                        "id": "1",
                        "source": "MED",
                        "pmid": "1",
                        "title": "" if query == "old" else "Merged title",
                    }
                ]
            },
        }

    monkeypatch.setattr(EuropePMCWrapper, "_search", fake_search)

    result = EuropePMCWrapper().collect_publications(
        ["old", "expanded"],
        max_publications_per_query=[1, 1],
    )

    assert len(result) == 1
    assert result[0]["query"] == "old"
    assert result[0]["queries"] == ["old", "expanded"]
    assert result[0]["title"] == "Merged title"


def test_collect_publications_validates_per_query_limits() -> None:
    with pytest.raises(ValueError, match="max_publications_per_query"):
        EuropePMCWrapper().collect_publications(
            ["one", "two"],
            max_publications_per_query=[5],
        )
    with pytest.raises(ValueError, match="max_publications_per_query"):
        EuropePMCWrapper().collect_publications(
            ["one"],
            max_publications_per_query=[0],
        )


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


def test_collect_publication_texts_fetches_full_text_xml_by_pmcid(monkeypatch) -> None:
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(
            {},
            text="<article><body><sec><title>Methods</title><p>Body text.</p></sec></body></article>",
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(timeout=12).collect_publication_texts(
        publications=[
            {
                "epmc_id": "123",
                "pmcid": "PMC123",
                "abstractText": "Abstract",
            }
        ]
    )

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML",
            12,
        )
    ]
    assert result[0]["text"] == (
        "<<<THEMATIC_ATLASES_SECTION:title=Methods>>>\nBody text."
    )
    assert result[0]["text_source"] == "fullTextXML"
    assert result[0]["full_text_status"] == "available"


def test_publication_text_item_lock_prevents_duplicate_concurrent_requests(
    monkeypatch,
    tmp_path,
) -> None:
    store_path = tmp_path / "resume_state.sqlite"
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        started.set()
        assert release.wait(timeout=5)
        return FakeResponse(
            {},
            text="<article><body><p>Shared full text.</p></body></article>",
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    publication = {
        "source": "MED",
        "epmc_id": "123",
        "pmcid": "PMC123",
        "abstractText": "Abstract fallback",
    }

    def collect():
        return EuropePMCWrapper(max_retries=0).collect_publication_texts(
            publications=[publication],
            checkpoint_store=CheckpointStore(store_path),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(collect)
        assert started.wait(timeout=5)
        second = executor.submit(collect)
        release.set()
        assert first.result(timeout=5)[0]["text_source"] == "fullTextXML"
        assert second.result(timeout=5)[0]["text_source"] == "fullTextXML"

    assert calls == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML"
    ]


def test_publication_text_defers_when_bounded_item_lock_is_busy(
    monkeypatch,
    tmp_path,
) -> None:
    store_path = tmp_path / "resume_state.sqlite"
    started = threading.Event()
    release = threading.Event()
    calls = []

    def hold_lock() -> None:
        with CheckpointStore(store_path).item_lock("publication_text", "MED:123"):
            started.set()
            assert release.wait(timeout=5)

    monkeypatch.setattr(
        epmc_module.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    publication = {
        "source": "MED",
        "epmc_id": "123",
        "pmcid": "PMC123",
        "abstractText": "Abstract fallback",
    }

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(hold_lock)
        assert started.wait(timeout=5)
        result = EuropePMCWrapper(max_retries=0).collect_publication_texts(
            publications=[publication],
            checkpoint_store=CheckpointStore(
                store_path,
                default_item_lock_timeout_seconds=0.05,
            ),
        )
        release.set()
        holder.result(timeout=5)

    assert result == []
    assert calls == []


def test_collect_publication_texts_uses_abstract_when_full_text_unavailable(
    monkeypatch,
) -> None:
    def fake_get(url, timeout):
        return FakeResponse({}, status_code=404)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper().collect_publication_texts(
        publications=[
            {
                "epmc_id": "123",
                "pmcid": "PMC123",
                "abstractText": "Abstract fallback",
            }
        ]
    )

    assert result[0]["text"] == "Abstract fallback"
    assert result[0]["text_source"] == "abstractText"
    assert result[0]["full_text_status"] == "unavailable"


def test_known_pmcid_404_keeps_abstract_but_marks_checkpoint_terminal(
    monkeypatch, tmp_path
) -> None:
    def fake_get(url, timeout):
        return FakeResponse({}, status_code=404)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    store = CheckpointStore(tmp_path / "resume_state.sqlite")

    result = EuropePMCWrapper(max_retries=0).collect_publication_texts(
        publications=[
            {
                "source": "MED",
                "epmc_id": "123",
                "pmcid": "PMC123",
                "abstractText": "Abstract fallback",
            }
        ],
        checkpoint_store=store,
    )

    assert result[0]["text"] == "Abstract fallback"
    checkpoint = store.get("publication_text", "MED:123")
    assert checkpoint["status"] == "terminal_error"
    assert checkpoint["error_type"] == "HTTPError"
    assert checkpoint["failure_category"] == "public_full_text_unavailable"


def test_collect_publication_texts_missing_pmcid_skips_request(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper().collect_publication_texts(
        publications=[
            {
                "epmc_id": "123",
                "abstractText": "Abstract fallback",
            }
        ]
    )

    assert calls == []
    assert result[0]["text"] == "Abstract fallback"
    assert result[0]["text_source"] == "abstractText"
    assert result[0]["full_text_status"] == "missing_pmcid"


def test_collect_publication_texts_empty_abstract_has_no_text(monkeypatch) -> None:
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper().collect_publication_texts(
        publications=[
            {
                "epmc_id": "123",
                "abstractText": "",
            }
        ]
    )

    assert result[0]["text"] == ""
    assert result[0]["text_source"] == "none"
    assert result[0]["full_text_status"] == "missing_pmcid"


@pytest.mark.parametrize("status_code", [403, 503])
def test_collect_publication_texts_retries_transient_failures(
    monkeypatch, status_code
) -> None:
    calls = []
    responses = [
        FakeResponse({}, status_code=status_code),
        FakeResponse({}, text="<article><body><p>Recovered text.</p></body></article>"),
    ]

    def fake_get(url, timeout):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=1).collect_publication_texts(
        publications=[
            {
                "pmcid": "PMC123",
                "abstractText": "Abstract",
            }
        ]
    )

    assert len(calls) == 2
    assert result[0]["text"] == (
        "<<<THEMATIC_ATLASES_SECTION:title=Text>>>\nRecovered text."
    )
    assert result[0]["text_source"] == "fullTextXML"


def test_collect_publication_texts_uses_pmc_epmc_id_without_pmcid(monkeypatch) -> None:
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse({}, text="<article><body><p>Text.</p></body></article>")

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    EuropePMCWrapper().collect_publication_texts(
        publications=[
            {
                "epmc_id": "PMC123",
                "abstractText": "Abstract",
            }
        ]
    )

    assert calls == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML"
    ]


def test_collect_publication_texts_resumes_after_completed_publication(
    tmp_path, monkeypatch
) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    calls = []
    interrupted = True

    def fake_get(url, timeout):
        nonlocal interrupted
        calls.append(url)
        if "PMC2" in url and interrupted:
            interrupted = False
            raise KeyboardInterrupt
        return FakeResponse(
            {}, text="<article><body><p>Recovered text.</p></body></article>"
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    publications = [
        {"epmc_id": "1", "pmcid": "PMC1", "abstractText": "one"},
        {"epmc_id": "2", "pmcid": "PMC2", "abstractText": "two"},
    ]
    store = CheckpointStore(tmp_path / "resume.sqlite")
    wrapper = EuropePMCWrapper()

    with pytest.raises(KeyboardInterrupt):
        wrapper.collect_publication_texts(publications, checkpoint_store=store)

    result = wrapper.collect_publication_texts(publications, checkpoint_store=store)

    assert sum("PMC1" in url for url in calls) == 1
    assert sum("PMC2" in url for url in calls) == 2
    assert [publication["full_text_status"] for publication in result] == [
        "available",
        "available",
    ]


def test_plain_text_from_xml_preserves_title_abstract_and_sections() -> None:
    full_text_xml = """
    <article>
      <front>
        <article-meta>
          <title-group><article-title>Article title</article-title></title-group>
          <abstract><p>Abstract text.</p></abstract>
        </article-meta>
      </front>
      <body>
        <sec><title>Background</title><p>Background text.</p></sec>
        <sec><title>Methods</title><p>Methods text.</p></sec>
      </body>
    </article>
    """

    assert EuropePMCWrapper()._plain_text_from_xml(full_text_xml) == (
        "<<<THEMATIC_ATLASES_SECTION:title=Title>>>\nArticle title\n\n"
        "<<<THEMATIC_ATLASES_SECTION:title=Abstract>>>\nAbstract text.\n\n"
        "<<<THEMATIC_ATLASES_SECTION:title=Background>>>\nBackground text.\n\n"
        "<<<THEMATIC_ATLASES_SECTION:title=Methods>>>\nMethods text."
    )


def test_plain_text_from_xml_uses_tag_fallback_and_skips_empty_sections() -> None:
    full_text_xml = """
    <article>
      <body>
        <sec><p>Untitled section text.</p></sec>
        <sec><title>Empty</title></sec>
      </body>
    </article>
    """

    assert EuropePMCWrapper()._plain_text_from_xml(full_text_xml) == (
        "<<<THEMATIC_ATLASES_SECTION:title=sec>>>\nUntitled section text."
    )


def test_plain_text_from_xml_sanitizes_delimiter_breaking_titles() -> None:
    full_text_xml = """
    <article>
      <body>
        <sec><title>Bad &lt;&lt;&lt;Title&gt;&gt;&gt;</title><p>Text.</p></sec>
      </body>
    </article>
    """

    assert EuropePMCWrapper()._plain_text_from_xml(full_text_xml) == (
        "<<<THEMATIC_ATLASES_SECTION:title=Bad Title>>>\nText."
    )


def test_publication_text_sections_parses_delimited_text() -> None:
    text = (
        "<<<THEMATIC_ATLASES_SECTION:title=Abstract>>>\nAbstract text.\n\n"
        "<<<THEMATIC_ATLASES_SECTION:title=Methods>>>\nMethods text."
    )

    assert EuropePMCWrapper().publication_text_sections(text=text) == [
        {"title": "Abstract", "text": "Abstract text."},
        {"title": "Methods", "text": "Methods text."},
    ]


def test_publication_text_sections_returns_text_section_for_plain_text() -> None:
    assert EuropePMCWrapper().publication_text_sections(text=" Plain fallback text. ") == [
        {"title": "Text", "text": "Plain fallback text."}
    ]


def test_publication_text_sections_returns_empty_for_empty_text() -> None:
    assert EuropePMCWrapper().publication_text_sections(text="  ") == []


def test_collect_datalinks_returns_empty_without_publications(monkeypatch) -> None:
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse({})

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    assert EuropePMCWrapper().collect_datalinks(publications=[]) == []
    assert calls == []


def test_collect_datalinks_sends_expected_request_and_returns_accessions(
    monkeypatch,
) -> None:
    calls = []
    publication = {
        "query": "fibrosis",
        "epmc_id": "123",
        "source": "MED",
        "pmid": "123",
        "pmcid": "PMC123",
        "doi": "10.1/example",
        "title": "Fibrosis study",
        "abstractText": "Abstract",
        "text": "Text",
        "text_source": "fullTextXML",
        "full_text_status": "available",
    }

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return FakeResponse(
            {},
            text=_datalinks_xml(
                ("GEO", "GSE1", "GEO", "https://example.org/GSE1"),
                ("Ignored", "IGNORE1", "OTHER", "https://example.org/IGNORE1"),
            ),
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(timeout=12).collect_datalinks(publications=[publication])

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            None,
            12,
        )
    ]
    assert result == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "query": "fibrosis",
                    "epmc_id": "123",
                    "source": "MED",
                    "pmid": "123",
                    "pmcid": "PMC123",
                    "doi": "10.1/example",
                    "title": "Fibrosis study",
                    "abstractText": "Abstract",
                    "text": "Text",
                    "text_source": "fullTextXML",
                    "full_text_status": "available",
                }
            ],
        }
    ]


def test_collect_datalinks_deduplicates_flattened_rows(monkeypatch) -> None:
    flattened_datalinks = []

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(
            {},
            text=_datalinks_xml(
                ("GEO", "GSE1", "GEO", "https://example.org/GSE1"),
            ),
        )

    def fake_deduplicate_accessions(self, datalinks: list[dict]) -> list[dict]:
        flattened_datalinks.extend(datalinks)
        return [{"datalink_id": "GSE1", "publications": []}]

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        EuropePMCWrapper,
        "_deduplicate_accessions",
        fake_deduplicate_accessions,
    )

    result = EuropePMCWrapper().collect_datalinks(
        publications=[
            {
                "query": "fibrosis",
                "epmc_id": "123",
                "source": "MED",
                "pmid": "123",
            }
        ]
    )

    assert result == [{"datalink_id": "GSE1", "publications": []}]
    assert flattened_datalinks == [
        {
            "query": "fibrosis",
            "epmc_id": "123",
            "source": "MED",
            "pmid": "123",
            "pmcid": "",
            "doi": "",
            "title": "",
            "abstractText": "",
            "text": "",
            "text_source": "",
            "full_text_status": "",
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        }
    ]


def test_collect_datalinks_retries_transient_failures(monkeypatch) -> None:
    calls = []
    sleeps = []
    responses = [
        FakeResponse({}, status_code=503),
        FakeResponse({}, status_code=503),
        FakeResponse(
            {},
            text=_datalinks_xml(
                ("BioProject", "PRJ1", "BioProject", "https://example.org/PRJ1"),
            ),
        ),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)

    result = EuropePMCWrapper(max_retries=1, request_delay=0.25).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "1"}]
    )

    assert calls == [None, {"format": "json"}, None]
    assert len(sleeps) >= 2
    assert all(0 <= delay <= 1 for delay in sleeps)
    assert result[0]["datalink_id"] == "PRJ1"
    assert result[0]["publications"] == [
        {
            "query": "q",
            "epmc_id": "1",
            "source": "MED",
            "pmid": "",
            "pmcid": "",
            "doi": "",
            "title": "",
            "abstractText": "",
            "text": "",
            "text_source": "",
            "full_text_status": "",
        }
    ]


def test_collect_datalinks_falls_back_to_json_when_xml_endpoint_fails(
    monkeypatch,
) -> None:
    calls = []
    sleeps = []
    responses = [
        FakeResponse({}, status_code=500),
        FakeResponse(
            {
                "dataLinkList": {
                    "Category": [
                        {
                            "Name": "Functional Genomics Experiments",
                            "Section": [
                                {
                                    "Linklist": {
                                        "Link": [
                                            {
                                                "Target": {
                                                    "Identifier": {
                                                        "ID": "E-MTAB-1",
                                                        "IDScheme": "ArrayExpress",
                                                        "IDURL": "https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-1",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)

    result = EuropePMCWrapper(
        max_retries=3,
        request_delay=0.25,
        timeout=12,
    ).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            None,
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            {"format": "json"},
            12,
        ),
    ]
    assert len(sleeps) == 1
    assert 0.4 <= sleeps[0] <= 0.5
    assert result == [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [
                {
                    "query": "q",
                    "epmc_id": "123",
                    "source": "MED",
                    "pmid": "",
                    "pmcid": "",
                    "doi": "",
                    "title": "",
                    "abstractText": "",
                    "text": "",
                    "text_source": "",
                    "full_text_status": "",
                }
            ],
        }
    ]


def test_collect_datalinks_honors_retry_after_before_json(monkeypatch) -> None:
    calls = []
    sleeps = []
    responses = [
        FakeResponse({}, status_code=429, headers={"Retry-After": "3"}),
        FakeResponse(_geo_datalink_response("GSE1")),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)

    result = EuropePMCWrapper(max_retries=3).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert calls == [None, {"format": "json"}]
    assert sleeps == [3.0]
    assert result[0]["datalink_id"] == "GSE1"


def test_datalinks_returns_to_xml_after_retryable_pair_with_malformed_json(
    monkeypatch,
) -> None:
    calls = []
    sleeps = []

    class MalformedJSONResponse(FakeResponse):
        def json(self) -> dict:
            raise requests.JSONDecodeError("invalid JSON", "{", 1)

    responses = [
        FakeResponse({}, status_code=500),
        MalformedJSONResponse({}),
        FakeResponse({}, text=_datalinks_xml(("GEO", "GSE1", "GEO", ""))),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)

    result = EuropePMCWrapper(
        max_retries=1,
        request_delay=0,
    )._datalinks(source="MED", epmc_id="123")

    assert calls == [None, {"format": "json"}, None]
    assert len(sleeps) >= 2
    assert all(0 <= delay <= 1 for delay in sleeps)
    assert result["dataLinkList"]["Category"][0]["Section"][0]["Linklist"][
        "Link"
    ][0]["Target"]["Identifier"]["ID"] == "GSE1"


def test_valid_empty_datalinks_xml_is_authoritative(monkeypatch, tmp_path) -> None:
    calls = []
    store = CheckpointStore(tmp_path / "resume.sqlite")

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({}, text=_datalinks_xml())

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda _delay: None)

    result = EuropePMCWrapper(request_delay=0).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}],
        checkpoint_store=store,
    )

    assert result == []
    assert calls == [None]
    assert store.get("datalinks", "MED:123")["status"] == "no_data"


def test_datalinks_closes_failed_and_successful_format_responses(monkeypatch) -> None:
    xml_response = FakeResponse({}, status_code=500)
    json_response = FakeResponse(_geo_datalink_response("GSE1"))
    responses = [xml_response, json_response]

    monkeypatch.setattr(
        epmc_module.requests,
        "get",
        lambda url, params=None, timeout=None: responses.pop(0),
    )
    monkeypatch.setattr(epmc_module.time, "sleep", lambda _delay: None)

    result = EuropePMCWrapper(
        max_retries=0,
        request_delay=0,
    )._datalinks(source="MED", epmc_id="123")

    assert result == _geo_datalink_response("GSE1")
    assert xml_response.close_calls == 1
    assert json_response.close_calls == 1


def test_datalinks_alternates_formats_until_bounded_retry_exhaustion(
    monkeypatch,
) -> None:
    calls = []
    sleeps = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({}, status_code=500)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)
    wrapper = EuropePMCWrapper(max_retries=3)

    with pytest.raises(requests.HTTPError) as error:
        wrapper._datalinks(source="MED", epmc_id="123")

    assert error.value.response.status_code == 500
    assert calls == [None, {"format": "json"}] * 4
    assert len(sleeps) >= len(calls) - 1
    assert all(0 <= delay <= 4 for delay in sleeps)


def test_datalinks_stops_after_one_permanent_failure_pair(monkeypatch) -> None:
    calls = []
    sleeps = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({}, status_code=404)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)
    wrapper = EuropePMCWrapper(max_retries=3)

    with pytest.raises(requests.HTTPError) as error:
        wrapper._datalinks(source="MED", epmc_id="123")

    assert error.value.response.status_code == 404
    assert calls == [None, {"format": "json"}]
    assert len(sleeps) == 1
    assert 0.4 <= sleeps[0] <= 0.5


def test_collect_datalinks_preserves_retryable_pair_failure_for_resume(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []
    store = CheckpointStore(tmp_path / "resume.sqlite")

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({}, status_code=404 if params else 500)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda _delay: None)

    result = EuropePMCWrapper(
        max_retries=1,
        request_delay=0,
    ).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}],
        checkpoint_store=store,
    )

    assert result == []
    assert calls == [None, {"format": "json"}] * 2
    checkpoint = store.get("datalinks", "MED:123")
    assert checkpoint["status"] == "retryable_error"
    assert checkpoint["failure_category"] == "transient"


def test_collect_datalinks_falls_back_to_json_when_xml_endpoint_times_out(
    monkeypatch,
) -> None:
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))

        if params is None:
            raise requests.ReadTimeout("slow xml")

        return FakeResponse(_geo_datalink_response("GSE1"))

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=0, timeout=12).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            None,
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            {"format": "json"},
            12,
        ),
    ]
    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["datalink_id_scheme"] == "GEO"


def test_collect_datalinks_skips_failed_publication_and_continues(
    monkeypatch,
    caplog,
) -> None:
    calls = []
    sleeps = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))

        if "/MED/failed/datalinks" in url:
            raise requests.ReadTimeout("dead datalink endpoint")

        return FakeResponse(
            {},
            text=_datalinks_xml(
                (
                    "Functional Genomics Experiments",
                    "E-MTAB-1",
                    "ArrayExpress",
                    "https://example.org/E-MTAB-1",
                ),
            ),
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", sleeps.append)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    result = EuropePMCWrapper(max_retries=0, timeout=12).collect_datalinks(
        publications=[
            {"query": "q", "source": "MED", "epmc_id": "failed"},
            {"query": "q", "source": "MED", "epmc_id": "ok"},
        ]
    )

    assert result == [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [
                {
                    "query": "q",
                    "epmc_id": "ok",
                    "source": "MED",
                    "pmid": "",
                    "pmcid": "",
                    "doi": "",
                    "title": "",
                    "abstractText": "",
                    "text": "",
                    "text_source": "",
                    "full_text_status": "",
                }
            ],
        }
    ]
    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/failed/datalinks",
            None,
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/failed/datalinks",
            {"format": "json"},
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/ok/datalinks",
            None,
            12,
        ),
    ]
    assert len(sleeps) == len(calls) - 1
    assert all(0.4 <= delay <= 0.5 for delay in sleeps)
    assert "EuropePMC datalinks skipped publication source='MED' epmc_id='failed'" in caplog.text
    assert "failed_publications=1" in caplog.text


def test_collect_datalinks_checkpoints_non_network_processing_failure(
    monkeypatch, tmp_path
) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    monkeypatch.setattr(
        EuropePMCWrapper,
        "_datalinks",
        lambda self, source, epmc_id: (_ for _ in ()).throw(
            ValueError("malformed provider payload")
        ),
    )

    result = EuropePMCWrapper().collect_datalinks(
        [{"source": "MED", "epmc_id": "123"}],
        checkpoint_store=store,
    )

    assert result == []
    item = store.get("datalinks", "MED:123")
    assert item["status"] == "terminal_error"
    assert item["error_type"] == "ValueError"
    assert json.loads(item["error"])["error_type"] == "ValueError"
    assert "malformed provider payload" not in item["error"]


def test_collect_datalinks_falls_back_to_json_when_xml_is_malformed(
    monkeypatch,
) -> None:
    calls = []
    responses = [
        FakeResponse({}, text="<responseWrapper>"),
        FakeResponse(_geo_datalink_response("GSE1")),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)

    result = EuropePMCWrapper(max_retries=0, timeout=12).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert [call[1] for call in calls] == [None, {"format": "json"}]
    assert result[0]["datalink_id"] == "GSE1"


@pytest.mark.parametrize(
    ("xml", "resource_overrides", "error_type"),
    [
        (
            '<!DOCTYPE x [<!ENTITY y "z">]><root>&y;</root>',
            None,
            UnsafeXMLDocumentError,
        ),
        ("<root>" + "x" * 64 + "</root>", {"max_xml_bytes": 32}, XMLSizeLimitError),
    ],
)
def test_datalinks_xml_safety_failures_do_not_fallback_to_json(
    monkeypatch,
    xml,
    resource_overrides,
    error_type,
) -> None:
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return FakeResponse({}, text=xml)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    wrapper = EuropePMCWrapper(
        max_retries=0,
        timeout=12,
        resource_overrides=resource_overrides,
    )

    with pytest.raises(error_type):
        wrapper._datalinks(source="MED", epmc_id="123")

    assert [call[1] for call in calls] == [None]


def test_xml_boundaries_reject_unsafe_and_oversized_documents() -> None:
    with pytest.raises(UnsafeXMLDocumentError):
        EuropePMCWrapper()._datalinks_xml_to_json(
            '<!DOCTYPE x [<!ENTITY y "z">]><root>&y;</root>'
        )
    with pytest.raises(XMLSizeLimitError):
        EuropePMCWrapper(
            resource_overrides={"max_xml_bytes": 32}
        )._plain_text_from_xml("<article>" + "x" * 64 + "</article>")


def test_collect_datalinks_logs_stats(monkeypatch, caplog) -> None:
    def fake_get(url, params=None, timeout=None):
        return FakeResponse(
            {},
            text=_datalinks_xml(
                ("GEO", "GSE1", "GEO", ""),
                ("Ignored", None, None, None),
            ),
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    EuropePMCWrapper().collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "1"}]
    )

    assert "publications_checked=1" in caplog.text
    assert "datalinks_collected=1" in caplog.text
    assert "skipped_categories=1" in caplog.text
    assert "failed_publications=0" in caplog.text


def test_collect_datalinks_logs_periodic_progress(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        epmc_module.requests,
        "get",
        lambda url, params=None, timeout=None: FakeResponse(
            {}, text=_datalinks_xml()
        ),
    )
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    EuropePMCWrapper().collect_datalinks(
        publications=[
            {"source": "MED", "epmc_id": str(index)} for index in range(1, 13)
        ]
    )

    assert "datalink progress publication_index=1 publication_total=12" in caplog.text
    assert "datalink progress publication_index=10 publication_total=12" in caplog.text
    assert "datalink progress publication_index=12 publication_total=12" in caplog.text
    assert "datalink progress publication_index=2 publication_total=12" not in caplog.text


def test_deduplicate_accessions_collapses_duplicate_ids() -> None:
    datalinks = [
        {
            "query": "q1",
            "epmc_id": "1",
            "source": "MED",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
            "title": "One",
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        },
        {
            "query": "q2",
            "epmc_id": "2",
            "source": "MED",
            "pmid": "2",
            "pmcid": "PMC2",
            "doi": "10.1/two",
            "title": "Two",
            "datalink_id": "GSE1",
            "datalink_id_scheme": "URL",
            "datalink_url": "https://other.example.org/GSE1",
            "datalink_category": "Other",
        },
    ]

    assert EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks) == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "query": "q1",
                    "epmc_id": "1",
                    "source": "MED",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                    "title": "One",
                    "abstractText": "",
                    "text": "",
                    "text_source": "",
                    "full_text_status": "",
                },
                {
                    "query": "q2",
                    "epmc_id": "2",
                    "source": "MED",
                    "pmid": "2",
                    "pmcid": "PMC2",
                    "doi": "10.1/two",
                    "title": "Two",
                    "abstractText": "",
                    "text": "",
                    "text_source": "",
                    "full_text_status": "",
                },
            ],
        }
    ]


def test_deduplicate_accessions_ignores_repeated_publication() -> None:
    datalink = {
        "query": "q",
        "epmc_id": "1",
        "source": "MED",
        "pmid": "1",
        "pmcid": "PMC1",
        "doi": "10.1/one",
        "title": "One",
        "datalink_id": "GSE1",
        "datalink_id_scheme": "GEO",
        "datalink_url": "https://example.org/GSE1",
        "datalink_category": "GEO",
    }

    result = EuropePMCWrapper()._deduplicate_accessions(datalinks=[datalink, datalink])

    assert len(result) == 1
    assert len(result[0]["publications"]) == 1


def test_deduplicate_accessions_preserves_publication_text_fields() -> None:
    datalinks = [
        {
            "query": "q",
            "epmc_id": "1",
            "source": "MED",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
            "title": "One",
            "text": "Publication text",
            "text_source": "fullTextXML",
            "full_text_status": "available",
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
        },
    ]

    result = EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks)

    assert result[0]["publications"][0]["text"] == "Publication text"
    assert result[0]["publications"][0]["text_source"] == "fullTextXML"
    assert result[0]["publications"][0]["full_text_status"] == "available"


def test_deduplicate_accessions_preserves_publication_abstract_text() -> None:
    datalinks = [
        {
            "query": "q",
            "epmc_id": "1",
            "source": "MED",
            "abstractText": "Abstract fallback",
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
        },
    ]

    result = EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks)

    assert result[0]["publications"][0]["abstractText"] == "Abstract fallback"


def test_deduplicate_accessions_skips_empty_ids() -> None:
    datalinks = [
        {"datalink_id": "", "datalink_id_scheme": "GEO"},
        {"datalink_id": "  ", "datalink_id_scheme": "GEO"},
    ]

    assert EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks) == []


def test_deduplicate_accessions_is_case_insensitive() -> None:
    datalinks = [
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "epmc_id": "1"},
        {"datalink_id": "gse1", "datalink_id_scheme": "GEO", "epmc_id": "2"},
    ]

    result = EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks)

    assert len(result) == 1
    assert result[0]["datalink_id"] == "GSE1"
    assert [publication["epmc_id"] for publication in result[0]["publications"]] == [
        "1",
        "2",
    ]


def test_deduplicate_accessions_logs_stats(caplog) -> None:
    datalinks = [
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "epmc_id": "1"},
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "epmc_id": "2"},
        {"datalink_id": "", "datalink_id_scheme": "GEO", "epmc_id": "3"},
    ]
    caplog.set_level(logging.INFO, logger=epmc_module.__name__)

    EuropePMCWrapper()._deduplicate_accessions(datalinks=datalinks)

    assert "input_datalinks=3" in caplog.text
    assert "output_accessions=1" in caplog.text
    assert "duplicate_rows_collapsed=1" in caplog.text
    assert "skipped_rows=1" in caplog.text
