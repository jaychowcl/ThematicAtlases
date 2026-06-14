import json

import pytest

from ThematicAtlases.filterer.review import PublicationTextReviewer


class FakeReviewer:
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
                            "reason": "Direct theme mention.",
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


class FailingReviewer:
    def review_relevancy(self, **kwargs):
        raise AssertionError("review should not be called")


def reviewed_atlas_parts() -> tuple[list[dict], dict]:
    return (
        [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {"publication_text_ref": "1", "pmid": "1"},
                    {"publication_text_ref": "2", "pmid": "2"},
                    {"publication_text_ref": "3", "pmid": "3"},
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [{"publication_text_ref": "2", "pmid": "2"}],
            },
        ],
        {
            "1": {
                "text": "Relevant text",
                "agentic_curator": {
                    "theme": "fibrosis",
                    "judgement": "relevant",
                },
            },
            "2": {
                "text": "Not relevant text",
                "agentic_curator": {
                    "theme": "fibrosis",
                    "judgement": "not relevant",
                },
            },
            "3": {
                "text": "Unsure text",
                "agentic_curator": {
                    "theme": "fibrosis",
                    "judgement": "unsure",
                },
            },
        },
    )


def test_validate_options_rejects_filter_without_theme() -> None:
    with pytest.raises(ValueError, match="requires a theme"):
        PublicationTextReviewer().validate_options(
            theme=None,
            review_filter="not_relevant",
        )


def test_review_publication_texts_parses_agentic_curator_schema() -> None:
    FakeReviewer.calls = []
    publication_texts = {"1": {"text": "Full text"}}

    result = PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={
            "1": {
                "title": "Fibrosis atlas publication",
                "metadata": {"series": {"title": "Series metadata"}},
            }
        },
        theme="fibrosis",
        reviewer=FakeReviewer(),
    )

    assert FakeReviewer.calls == [
        {
            "publication_text": "Full text",
            "theme": "fibrosis",
            "metadata": {"series": {"title": "Series metadata"}},
            "title": "Fibrosis atlas publication",
        }
    ]
    assert result["1"]["agentic_curator"] == {
        "theme": "fibrosis",
        "evidences": [
            {
                "evidence": "fibrotic tissue",
                "judgement": "relevant",
                "confidence": "direct",
                "reason": "Direct theme mention.",
            }
        ],
        "judgement": "relevant",
        "reasoning": "Direct evidence is present.",
        "confidence": "theme directly mentioned",
        "raw_evidences": json.dumps(
            {
                "evidences": [
                    {
                        "evidence": "fibrotic tissue",
                        "judgement": "relevant",
                        "confidence": "direct",
                        "reason": "Direct theme mention.",
                    }
                ]
            }
        ),
        "raw_judgement": json.dumps(
            {
                "judgement": "relevant",
                "reasoning": "Direct evidence is present.",
                "confidence": "theme directly mentioned",
            }
        ),
    }


def test_review_publication_texts_reuses_matching_theme() -> None:
    publication_texts = {
        "1": {
            "text": "Full text",
            "agentic_curator": {
                "theme": "fibrosis",
                "judgement": "relevant",
            },
        }
    }

    assert PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=FailingReviewer(),
    ) == publication_texts


def test_agentic_curator_review_preserves_raw_text_when_json_parse_fails() -> None:
    result = PublicationTextReviewer().agentic_curator_review(
        theme="fibrosis",
        review={
            "evidences": "not json evidence",
            "judgement": "not json judgement",
        },
    )

    assert result == {
        "theme": "fibrosis",
        "evidences": [],
        "judgement": "",
        "reasoning": "",
        "confidence": "",
        "raw_evidences": "not json evidence",
        "raw_judgement": "not json judgement",
    }


def test_filtered_result_drops_not_relevant_and_unsure_publications() -> None:
    accessions, publication_texts = reviewed_atlas_parts()

    filtered_accessions, filtered_publication_texts = (
        PublicationTextReviewer().filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter="not_relevant_and_unsure",
        )
    )

    assert filtered_accessions == [
        {
            "datalink_id": "GSE1",
            "publications": [{"publication_text_ref": "1", "pmid": "1"}],
        }
    ]
    assert set(filtered_publication_texts) == {"1"}
