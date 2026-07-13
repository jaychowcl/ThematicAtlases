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


def test_review_publication_texts_isolates_and_retains_failed_publication(caplog) -> None:
    class PartlyFailingReviewer:
        def review_relevancy(self, publication_text, theme, metadata, title):
            if publication_text == "bad":
                raise ValueError("LLM response was not valid JSON.")
            return FakeReviewer().review_relevancy(
                publication_text=publication_text,
                theme=theme,
                metadata=metadata,
                title=title,
            )

    publication_texts = {"bad": {"text": "bad"}, "good": {"text": "good"}}
    result = PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=PartlyFailingReviewer(),
    )

    assert result["bad"]["agentic_curator"] == {
        "theme": "fibrosis",
        "review_status": "failed",
        "error_type": "ValueError",
        "error": "LLM response was not valid JSON.",
    }
    assert result["good"]["agentic_curator"]["judgement"] == "relevant"
    accessions = [
        {"datalink_id": "GSE1", "publications": [{"publication_text_ref": "bad"}]},
        {"datalink_id": "GSE2", "publications": [{"publication_text_ref": "good"}]},
    ]
    filtered, texts = PublicationTextReviewer().filtered_result(
        accessions=accessions,
        publication_texts=result,
        review_filter="not_relevant_and_unsure",
    )
    assert [item["datalink_id"] for item in filtered] == ["GSE1", "GSE2"]
    assert set(texts) == {"bad", "good"}


def test_review_publication_texts_reports_atomic_progress_after_each_result() -> None:
    snapshots = []
    PublicationTextReviewer().review_publication_texts(
        publication_texts={"1": {"text": "one"}, "2": {"text": "two"}},
        contexts={},
        theme="fibrosis",
        reviewer=FakeReviewer(),
        progress_callback=lambda values: snapshots.append(list(values)),
    )
    assert snapshots == [["1"], ["1", "2"]]


def test_review_publication_texts_resumes_after_completed_publication(tmp_path) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    class InterruptingReviewer:
        calls = []
        interrupted = True

        def review_relevancy(self, publication_text, **kwargs):
            self.calls.append(publication_text)
            if publication_text == "two" and self.interrupted:
                self.interrupted = False
                raise KeyboardInterrupt
            return FakeReviewer().review_relevancy(
                publication_text=publication_text, **kwargs
            )

    reviewer = InterruptingReviewer()
    store = CheckpointStore(tmp_path / "resume.sqlite")
    publication_texts = {"1": {"text": "one"}, "2": {"text": "two"}}

    with pytest.raises(KeyboardInterrupt):
        PublicationTextReviewer().review_publication_texts(
            publication_texts=publication_texts,
            contexts={},
            theme="fibrosis",
            reviewer=reviewer,
            checkpoint_store=store,
        )

    result = PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    assert reviewer.calls == ["one", "two", "two"]
    assert result["1"]["agentic_curator"]["judgement"] == "relevant"
    assert result["2"]["agentic_curator"]["judgement"] == "relevant"


def test_review_checkpoint_is_invalidated_when_publication_text_changes(
    tmp_path,
) -> None:
    from ThematicAtlases.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / "resume.sqlite")
    FakeReviewer.calls = []
    reviewer = FakeReviewer()
    PublicationTextReviewer().review_publication_texts(
        publication_texts={"1": {"text": "abstract fallback"}},
        contexts={},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    result = PublicationTextReviewer().review_publication_texts(
        publication_texts={"1": {"text": "recovered full text"}},
        contexts={},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "abstract fallback",
        "recovered full text",
    ]
    assert result["1"]["agentic_curator"]["judgement"] == "relevant"


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
