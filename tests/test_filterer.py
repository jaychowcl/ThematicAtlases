import json
import logging

from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import filterer as filterer_module


class FakeEuropePMCWrapper:
    publications: list[dict] | None = None

    def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
        self.__class__.publications = publications
        return [
            {
                **publication,
                "text": f"Text {publication.get('epmc_id', '')}",
                "text_source": "abstractText",
                "full_text_status": "missing_pmcid",
            }
            for publication in publications
        ]


class _FailingReviewer:
    def review_relevancy(self, **kwargs):
        raise AssertionError("existing review should be reused")


def _reviewed_atlas_object() -> dict:
    return {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {"source": "MED", "epmc_id": "1", "pmid": "1", "publication_text_ref": "1"},
                    {"source": "MED", "epmc_id": "2", "pmid": "2", "publication_text_ref": "2"},
                    {"source": "MED", "epmc_id": "3", "pmid": "3", "publication_text_ref": "3"},
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [
                    {"source": "MED", "epmc_id": "2", "pmid": "2", "publication_text_ref": "2"}
                ],
            },
        ],
        "publication_texts": {
            "1": {"text": "Relevant text", "agentic_curator": {"theme": "fibrosis", "strategy": "direct", "judgement": "relevant"}},
            "2": {"text": "Not relevant text", "agentic_curator": {"theme": "fibrosis", "strategy": "direct", "judgement": "not relevant"}},
            "3": {"text": "Unsure text", "agentic_curator": {"theme": "fibrosis", "strategy": "direct", "judgement": "unsure"}},
        },
    }


def test_collect_publication_texts_returns_shared_text_map(monkeypatch) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [
        {
            "datalink_id": "GSE1",
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
            "datalink_id": "GSE2",
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
    ]

    result = AtlasFilterer().collect_publication_texts(jsons=records)

    assert FakeEuropePMCWrapper.publications == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
        }
    ]
    assert result == {
        "1": {
            "text": "Text 1",
            "text_source": "abstractText",
            "full_text_status": "missing_pmcid",
        }
    }


def test_collect_publication_texts_skips_empty_publication_lists(monkeypatch) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None

    assert AtlasFilterer().collect_publication_texts(
        jsons=[{"datalink_id": "GSE1", "publications": []}]
    ) == {}
    assert FakeEuropePMCWrapper.publications is None


def test_filter_jsons_returns_accessions_and_publication_texts(monkeypatch) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [
        {
            "datalink_id": "GSE1",
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
            "datalink_id": "GSE2",
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
    ]

    assert AtlasFilterer().filter_jsons(jsons=records) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "pmcid": "PMC1",
                        "doi": "10.1/one",
                        "publication_text_ref": "1",
                    }
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "pmcid": "PMC1",
                        "doi": "10.1/one",
                        "publication_text_ref": "1",
                    }
                ],
            },
        ],
        "publication_texts": {
            "1": {
                "text": "Text 1",
                "text_source": "abstractText",
                "full_text_status": "missing_pmcid",
            }
        },
    }


def test_filter_jsons_reviews_publication_texts_with_agentic_curator_namespace(
    monkeypatch,
) -> None:
    class RecordingReviewer:
        calls: list[dict] = []

        def review_relevancy(
            self,
            publication_text=None,
            theme=None,
            metadata=None,
            title=None,
        ):
            self.__class__.calls.append(
                {
                    "publication_text": publication_text,
                    "theme": theme,
                    "metadata": metadata,
                    "title": title,
                }
            )
            return {
                "evidences": json.dumps(
                    {
                        "evidences": [
                            {
                                "evidence": "fibrotic tissue",
                                "judgement": "relevant",
                                "confidence": "direct",
                                "reason": "Theme is directly named.",
                            }
                        ]
                    }
                ),
                "judgement": json.dumps(
                    {
                        "judgement": "relevant",
                        "reasoning": "Direct evidence is present.",
                        "confidence": "theme directly mentioned",
                    }
                ),
            }

    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    records = [
        {
            "datalink_id": "GSE1",
            "accession_metadata": {
                "series": {
                    "title": "Series metadata",
                    "summary": "must not enter the prompt",
                },
                "platform": {"title": "platform must not enter the prompt"},
                "sample": [{"channel": [{
                    "source": "fibrotic lung",
                    "organism": [{"value": "Homo sapiens"}],
                    "extract_protocol": "must not enter the prompt",
                }]}],
            },
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "title": "Fibrosis atlas publication",
                }
            ],
        }
    ]
    RecordingReviewer.calls = []

    result = AtlasFilterer().filter_jsons(
        jsons=records,
        theme="fibrosis",
        reviewer=RecordingReviewer(),
    )

    assert RecordingReviewer.calls == [
        {
            "publication_text": "Text 1",
            "theme": "fibrosis",
            "metadata": [
                {
                    "accession": "GSE1",
                    "context": (
                        "Study: Series metadata | source=fibrotic lung; "
                        "organism=Homo sapiens"
                    ),
                }
            ],
            "title": "Fibrosis atlas publication",
        }
    ]
    assert result["publication_texts"]["1"]["agentic_curator"]["judgement"] == "relevant"
    assert result["accessions"][0]["accession_metadata"] == records[0][
        "accession_metadata"
    ]


def test_filter_jsons_reuses_existing_agentic_curator_review() -> None:
    result = AtlasFilterer().filter_jsons(
        jsons={
            "accessions": [
                {
                    "datalink_id": "GSE1",
                    "publications": [
                        {
                            "source": "MED",
                            "epmc_id": "1",
                            "pmid": "1",
                            "publication_text_ref": "1",
                        }
                    ],
                }
            ],
            "publication_texts": {
                "1": {
                    "text": "Existing full text",
                    "agentic_curator": {
                        "theme": "fibrosis",
                        "strategy": "direct",
                        "judgement": "relevant",
                    },
                }
            },
        },
        theme="fibrosis",
        reviewer=_FailingReviewer(),
    )

    assert result["publication_texts"]["1"]["agentic_curator"]["judgement"] == "relevant"


def test_filter_jsons_review_filters_publications() -> None:
    result = AtlasFilterer().filter_jsons(
        jsons=_reviewed_atlas_object(),
        theme="fibrosis",
        review_filter="not_relevant_and_unsure",
        reviewer=_FailingReviewer(),
    )

    assert result["accessions"] == [
        {
            "datalink_id": "GSE1",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "publication_text_ref": "1",
                }
            ],
        }
    ]
    assert set(result["publication_texts"]) == {"1"}


def test_filter_jsons_review_filter_requires_theme() -> None:
    try:
        AtlasFilterer().filter_jsons(review_filter="not_relevant")
    except ValueError as error:
        assert "requires a theme" in str(error)
    else:
        raise AssertionError("review_filter without theme should fail")


def test_publication_text_ref_prefers_pmid_then_fallbacks() -> None:
    filterer = AtlasFilterer()

    assert filterer.publication_text_ref({"pmid": "1", "pmcid": "PMC1"}) == "1"
    assert filterer.publication_text_ref({"pmcid": "PMC1", "doi": "10.1/one"}) == "PMC1"
    assert filterer.publication_text_ref({"doi": "10.1/one"}) == "10.1/one"
    assert filterer.publication_text_ref({"source": "MED", "epmc_id": "1"}) == "MED:1"


def test_filter_jsons_strips_duplicate_text_from_publications(monkeypatch) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    records = [
        {
            "datalink_id": "GSE1",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "text": "Old text",
                    "text_source": "fullTextXML",
                    "full_text_status": "available",
                }
            ],
        }
    ]

    publication = AtlasFilterer().filter_jsons(jsons=records)["accessions"][0][
        "publications"
    ][0]

    assert publication == {
        "source": "MED",
        "epmc_id": "1",
        "pmid": "1",
        "publication_text_ref": "1",
    }


def test_filter_jsons_empty_input_returns_empty_shape(monkeypatch) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None

    assert AtlasFilterer().filter_jsons() == {
        "accessions": [],
        "publication_texts": {},
    }
    assert FakeEuropePMCWrapper.publications is None


def test_filter_jsons_reuses_existing_publication_texts_from_file(
    monkeypatch,
    tmp_path,
) -> None:
    class FailingEuropePMCWrapper:
        def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
            raise AssertionError("existing publication text should be reused")

    input_file = tmp_path / "atlas.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [
                            {
                                "source": "MED",
                                "epmc_id": "1",
                                "pmid": "1",
                                "publication_text_ref": "1",
                            }
                        ],
                    }
                ],
                "publication_texts": {
                    "1": {
                        "text": "Existing full text",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FailingEuropePMCWrapper)

    assert AtlasFilterer().filter_jsons(file=str(input_file))["publication_texts"] == {
        "1": {
            "text": "Existing full text",
            "text_source": "fullTextXML",
            "full_text_status": "available",
        }
    }


def test_filter_jsons_appends_file_accessions_to_jsons(tmp_path) -> None:
    input_file = tmp_path / "collected.json"
    input_file.write_text(
        json.dumps([{"datalink_id": "GSE2", "publications": []}]),
        encoding="utf-8",
    )

    assert AtlasFilterer().filter_jsons(
        jsons=[{"datalink_id": "GSE1", "publications": []}],
        file=str(input_file),
    )["accessions"] == [
        {"datalink_id": "GSE1", "publications": []},
        {"datalink_id": "GSE2", "publications": []},
    ]


def test_filter_jsons_fetches_only_missing_publication_texts(
    monkeypatch,
    tmp_path,
) -> None:
    class RecordingEuropePMCWrapper:
        publications: list[dict] | None = None

        def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
            self.__class__.publications = publications
            return [
                {
                    **publication,
                    "text": f"Fetched text {publication.get('pmid', '')}",
                    "text_source": "abstractText",
                    "full_text_status": "missing_pmcid",
                }
                for publication in publications
            ]

    input_file = tmp_path / "atlas.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [
                            {"source": "MED", "epmc_id": "1", "pmid": "1"},
                            {"source": "MED", "epmc_id": "2", "pmid": "2"},
                        ],
                    }
                ],
                "publication_texts": {
                    "1": {
                        "text": "Existing text 1",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", RecordingEuropePMCWrapper)

    result = AtlasFilterer().filter_jsons(file=str(input_file))

    assert RecordingEuropePMCWrapper.publications == [
        {"source": "MED", "epmc_id": "2", "pmid": "2"}
    ]
    assert set(result["publication_texts"]) == {"1", "2"}


def test_filter_jsons_logs_publication_text_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(filterer_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    caplog.set_level(logging.INFO, logger=filterer_module.__name__)

    AtlasFilterer().filter_jsons(
        jsons=[
            {
                "datalink_id": "GSE1",
                "publications": [{"source": "MED", "epmc_id": "1", "pmid": "1"}],
            }
        ]
    )

    assert "stage=collect-publication-texts" in caplog.text
    assert "publication_texts=1" in caplog.text
    assert "accessions_with_text_refs=1" in caplog.text
