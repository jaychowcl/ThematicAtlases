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
        text: str = "",
    ):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def test_collect_accessions_calls_collect_publications(monkeypatch) -> None:
    publications = [{"epmc_id": "1", "source": "MED"}]
    expected = [{"datalink_id": "GSE1", "publications": []}]
    calls = []

    def fake_collect_publications(self, queries: list[str]) -> list[dict]:
        calls.append("publications")
        assert queries == ["fibrosis"]
        return publications

    def fake_collect_datalinks(self, publications: list[dict]) -> list[dict]:
        calls.append("datalinks")
        assert publications == [{"epmc_id": "1", "source": "MED"}]
        return expected

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


def test_collect_publication_texts_retries_transient_failures(monkeypatch) -> None:
    calls = []
    responses = [
        FakeResponse({}, status_code=503),
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

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(
            {
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
                                                        "ID": "GSE1",
                                                        "IDScheme": "GEO",
                                                        "IDURL": "https://example.org/GSE1",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ],
                        },
                        {
                            "Name": "Ignored",
                            "Section": [
                                {
                                    "Linklist": {
                                        "Link": [
                                            {
                                                "Target": {
                                                    "Identifier": {
                                                        "ID": "IGNORE1",
                                                        "IDScheme": "OTHER",
                                                        "IDURL": "https://example.org/IGNORE1",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ],
                        },
                    ]
                }
            }
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(timeout=12).collect_datalinks(publications=[publication])

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            {"format": "json"},
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

    def fake_get(url, params, timeout):
        return FakeResponse(
            {
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
                                                        "ID": "GSE1",
                                                        "IDScheme": "GEO",
                                                        "IDURL": "https://example.org/GSE1",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ],
                        },
                    ]
                }
            }
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
    responses = [
        FakeResponse({}, status_code=503),
        FakeResponse(
            {
                "dataLinkList": {
                    "Category": [
                        {
                            "Name": "BioProject",
                            "Section": [
                                {
                                    "Linklist": {
                                        "Link": [
                                            {
                                                "Target": {
                                                    "Identifier": {
                                                        "ID": "PRJ1",
                                                        "IDScheme": "BioProject",
                                                        "IDURL": "https://example.org/PRJ1",
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

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=1).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "1"}]
    )

    assert len(calls) == 2
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


def test_collect_datalinks_falls_back_to_xml_when_json_endpoint_fails(
    monkeypatch,
) -> None:
    calls = []
    xml = """
    <responseWrapper xmlns:slx="http://www.scholix.org" xmlns:epmc="https://www.europepmc.org/data">
      <dataLinkList>
        <epmc:Category>
          <epmc:Name>Functional Genomics Experiments</epmc:Name>
          <epmc:Section>
            <epmc:Linklist>
              <slx:Link>
                <slx:Source>
                  <slx:Identifier>
                    <slx:ID>123</slx:ID>
                    <slx:IDScheme>MED</slx:IDScheme>
                  </slx:Identifier>
                </slx:Source>
                <slx:Target>
                  <slx:Identifier>
                    <slx:ID>E-MTAB-1</slx:ID>
                    <slx:IDScheme>ArrayExpress</slx:IDScheme>
                    <slx:IDURL>https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-1</slx:IDURL>
                  </slx:Identifier>
                </slx:Target>
              </slx:Link>
            </epmc:Linklist>
          </epmc:Section>
        </epmc:Category>
      </dataLinkList>
    </responseWrapper>
    """
    responses = [
        FakeResponse({}, status_code=500),
        FakeResponse({}, text=xml),
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return responses.pop(0)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=0, timeout=12).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            {"format": "json"},
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            None,
            12,
        ),
    ]
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


def test_collect_datalinks_falls_back_to_xml_when_json_endpoint_times_out(
    monkeypatch,
) -> None:
    calls = []
    xml = """
    <responseWrapper xmlns:slx="http://www.scholix.org" xmlns:epmc="https://www.europepmc.org/data">
      <dataLinkList>
        <epmc:Category>
          <epmc:Name>GEO</epmc:Name>
          <epmc:Section>
            <epmc:Linklist>
              <slx:Link>
                <slx:Target>
                  <slx:Identifier>
                    <slx:ID>GSE1</slx:ID>
                    <slx:IDScheme>GEO</slx:IDScheme>
                    <slx:IDURL>https://example.org/GSE1</slx:IDURL>
                  </slx:Identifier>
                </slx:Target>
              </slx:Link>
            </epmc:Linklist>
          </epmc:Section>
        </epmc:Category>
      </dataLinkList>
    </responseWrapper>
    """

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))

        if params == {"format": "json"}:
            raise requests.ReadTimeout("slow json")

        return FakeResponse({}, text=xml)

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)

    result = EuropePMCWrapper(max_retries=0, timeout=12).collect_datalinks(
        publications=[{"query": "q", "source": "MED", "epmc_id": "123"}]
    )

    assert calls == [
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            {"format": "json"},
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/123/datalinks",
            None,
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

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))

        if "/MED/failed/datalinks" in url:
            raise requests.ReadTimeout("dead datalink endpoint")

        return FakeResponse(
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
                                                        "IDURL": "https://example.org/E-MTAB-1",
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
        )

    monkeypatch.setattr(epmc_module.requests, "get", fake_get)
    monkeypatch.setattr(epmc_module.time, "sleep", lambda delay: None)
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
            {"format": "json"},
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/failed/datalinks",
            None,
            12,
        ),
        (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/ok/datalinks",
            {"format": "json"},
            12,
        ),
    ]
    assert "EuropePMC datalinks skipped publication source='MED' epmc_id='failed'" in caplog.text
    assert "failed_publications=1" in caplog.text


def test_collect_datalinks_logs_stats(monkeypatch, caplog) -> None:
    def fake_get(url, params, timeout):
        return FakeResponse(
            {
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
                                                        "ID": "GSE1",
                                                        "IDScheme": "GEO",
                                                        "IDURL": "",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ],
                        },
                        {"Name": "Ignored", "Section": []},
                    ]
                }
            }
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
