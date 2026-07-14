import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ThematicAtlases.filterer.review import (
    REVIEW_CONTRACT_VERSION,
    PublicationTextReviewer,
)
from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.checkpoint import CheckpointStore


class FakeReviewer:
    calls: list[dict] = []

    def review_relevancy(
        self,
        publication_text=None,
        theme=None,
        metadata=None,
        title=None,
        accessions=None,
        strategy="direct",
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


class DirectReviewer:
    calls: list[dict] = []

    def review_relevancy(
        self,
        publication_text=None,
        theme=None,
        metadata=None,
        title=None,
        accessions=None,
        strategy="direct",
    ):
        self.__class__.calls.append(
            {
                "publication_text": publication_text,
                "theme": theme,
                "metadata": metadata,
                "title": title,
                "accessions": accessions,
                "strategy": strategy,
            }
        )
        assessment = {
            "accession": "GSE2",
            "human_samples": {
                "status": "fails",
                "evidence": "The publication identifies GSE2 as mouse-only.",
            },
            "transcriptomics_assay": {"status": "meets", "evidence": "RNA-seq."},
            "established_fibrosis": {"status": "meets", "evidence": "Fibrosis."},
            "accession_linkage": {"status": "meets", "evidence": "Names GSE2."},
            "confidence": "high",
            "reason": "Mouse-only dataset.",
            "decision": "exclude",
        }
        return {
            "judgement": "relevant",
            "reasoning": "GSE1 contains human fibrosis samples.",
            "confidence": "high",
            "accessions_to_remove": [
                {
                    "accession": "GSE2",
                    "reason": "Mouse-only dataset.",
                    "confidence": "high",
                }
            ],
            "accession_assessments": [assessment],
            "review_revision": 2,
            "strategy": strategy,
        }


class FailingReviewer:
    def review_relevancy(self, **kwargs):
        raise AssertionError("review should not be called")


def traced_publication(
    trace_dir: Path,
    *,
    epmc_id: str,
    datalink_id: str,
    scheme: str = "GEO",
    text: str,
) -> CheckpointStore:
    trace_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = trace_dir / "00_run_manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": trace_dir.name,
                    "theme": "fibrosis",
                    "metadata_repositories": ["geo"],
                    "review_before_metadata": True,
                }
            ),
            encoding="utf-8",
        )
    store = CheckpointStore(trace_dir / "resume_state.sqlite")
    ordinal = len(store.items("datalinks")) + 1
    publication = {
        "query": "fibrosis",
        "source": "MED",
        "epmc_id": epmc_id,
        "pmid": epmc_id,
        "pmcid": "",
        "doi": "",
        "title": f"Publication {epmc_id}",
        "abstractText": text,
    }
    store.put(
        "datalinks",
        f"MED:{epmc_id}",
        ordinal,
        "available",
        payload={
            "rows": [
                {
                    **publication,
                    "datalink_id": datalink_id,
                    "datalink_id_scheme": scheme,
                    "datalink_url": "",
                    "datalink_category": "GEO",
                }
            ]
        },
    )
    store.put(
        "publication_text",
        f"MED:{epmc_id}",
        ordinal,
        "available",
        payload={
            "publication": {
                **publication,
                "text": text,
                "text_source": "abstractText",
                "full_text_status": "unavailable",
            }
        },
    )
    return store


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
        "strategy": "direct",
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
        "accessions_to_remove": [],
    }


def test_review_publication_texts_reuses_matching_theme() -> None:
    publication_texts = {
        "1": {
            "text": "Full text",
            "agentic_curator": {
                "theme": "fibrosis",
                "strategy": "direct",
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
        "strategy": "direct",
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


def test_review_checkpoint_is_reused_when_only_metadata_context_changes(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    FakeReviewer.calls = []
    reviewer = FakeReviewer()
    review = PublicationTextReviewer()

    review.review_publication_texts(
        publication_texts={"1": {"text": "stable full text"}},
        contexts={"1": {"title": "Stable title", "metadata": "early"}},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )
    result = review.review_publication_texts(
        publication_texts={"1": {"text": "stable full text"}},
        contexts={"1": {"title": "Stable title", "metadata": "later metadata"}},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    assert len(FakeReviewer.calls) == 1
    assert result["1"]["agentic_curator"]["judgement"] == "relevant"


def test_publication_context_aggregates_every_gse_for_shared_publication() -> None:
    publication = {
        "publication_text_ref": "1",
        "title": "Shared publication",
    }
    contexts = PublicationTextReviewer().publication_review_contexts(
        accessions=[
            {"datalink_id": "GSE1", "publications": [publication]},
            {"datalink_id": "GSE2", "publications": [publication]},
            {"datalink_id": "GSM3", "publications": [publication]},
        ]
    )

    assert contexts["1"]["title"] == "Shared publication"
    assert contexts["1"]["accessions"] == ["GSE1", "GSE2"]


def test_direct_review_traces_accession_removals_without_filtering_them(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    DirectReviewer.calls = []
    review = PublicationTextReviewer()
    accessions = [
        {
            "datalink_id": accession,
            "publications": [{"publication_text_ref": "1", "title": "Study"}],
        }
        for accession in ("GSE1", "GSE2")
    ]
    texts = review.review_publication_texts(
        publication_texts={"1": {"text": "GSE1 human; GSE2 mouse"}},
        contexts=review.publication_review_contexts(accessions),
        theme="fibrosis",
        reviewer=DirectReviewer(),
        strategy="direct",
        checkpoint_store=store,
    )

    trace = texts["1"]["agentic_curator"]
    assert trace["review_revision"] == 2
    assert trace["accession_assessments"][0]["decision"] == "exclude"
    assert trace["accessions_to_remove"] == [
        {
            "accession": "GSE2",
            "reason": "Mouse-only dataset.",
            "confidence": "high",
        }
    ]
    filtered, _ = review.filtered_result(
        accessions=accessions,
        publication_texts=texts,
        review_filter="not_relevant",
    )
    assert [record["datalink_id"] for record in filtered] == ["GSE1", "GSE2"]


def test_review_contract_version_requires_criterion_based_direct_reviews() -> None:
    assert REVIEW_CONTRACT_VERSION == 3


def test_review_strategies_resume_independently_and_ignore_legacy_checkpoint(
    tmp_path,
) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    store.put(
        "thematic_review",
        "1",
        1,
        "available",
        payload={"publication_text": {"text": "legacy"}},
    )
    DirectReviewer.calls = []
    review = PublicationTextReviewer()
    options = {
        "publication_texts": {"1": {"text": "text"}},
        "contexts": {"1": {"title": "Title", "accessions": ["GSE1"]}},
        "theme": "fibrosis",
        "reviewer": DirectReviewer(),
        "checkpoint_store": store,
    }

    review.review_publication_texts(**options, strategy="direct")
    review.review_publication_texts(**options, strategy="evidence_then_judgement")
    review.review_publication_texts(**options, strategy="direct")

    assert [call["strategy"] for call in DirectReviewer.calls] == [
        "direct",
        "evidence_then_judgement",
    ]
    assert store.get("thematic_review", "direct:1")["status"] == "available"
    assert (
        store.get("thematic_review", "evidence_then_judgement:1")["status"]
        == "available"
    )


def test_review_checkpoint_lock_prevents_duplicate_concurrent_calls(tmp_path) -> None:
    store_path = tmp_path / "resume.sqlite"
    started = threading.Event()
    release = threading.Event()
    calls = []

    class SlowReviewer:
        def review_relevancy(self, publication_text, **kwargs):
            calls.append(publication_text)
            started.set()
            assert release.wait(timeout=5)
            return FakeReviewer().review_relevancy(
                publication_text=publication_text, **kwargs
            )

    def run_review():
        return PublicationTextReviewer().review_publication_texts(
            publication_texts={"1": {"text": "one"}},
            contexts={},
            theme="fibrosis",
            reviewer=SlowReviewer(),
            checkpoint_store=CheckpointStore(store_path),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_review)
        assert started.wait(timeout=5)
        second = executor.submit(run_review)
        release.set()
        assert first.result()["1"]["agentic_curator"]["judgement"] == "relevant"
        assert second.result()["1"]["agentic_curator"]["judgement"] == "relevant"

    assert calls == ["one"]


def test_resume_reviews_current_datalink_checkpoint_snapshot(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="first abstract",
    )
    FakeReviewer.calls = []

    result = PublicationTextReviewer().resume(
        trace_dir,
        reviewer=FakeReviewer(),
    )

    assert [record["datalink_id"] for record in result["accessions"]] == ["GSE1"]
    assert result["publication_texts"]["1"]["agentic_curator"]["judgement"] == "relevant"
    assert json.loads(
        (trace_dir / "resume_review_progress.json").read_text(encoding="utf-8")
    ) == result


def test_resume_adds_new_checkpointed_publications_without_rereview(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="first abstract",
    )
    FakeReviewer.calls = []
    reviewer = FakeReviewer()
    review = PublicationTextReviewer()
    review.resume(trace_dir, reviewer=reviewer)

    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="second abstract",
    )
    result = review.resume(trace_dir, reviewer=reviewer)

    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "first abstract",
        "second abstract",
    ]
    assert [record["datalink_id"] for record in result["accessions"]] == [
        "GSE1",
        "GSE2",
    ]
    assert set(result["publication_texts"]) == {"1", "2"}


def test_resume_picks_up_retryable_datalink_after_it_becomes_available(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="recovered abstract",
    )
    store.put(
        "datalinks",
        "MED:1",
        1,
        "retryable_error",
        error="temporary timeout",
    )
    FakeReviewer.calls = []
    review = PublicationTextReviewer()

    assert review.resume(trace_dir, reviewer=FakeReviewer()) == {
        "accessions": [],
        "publication_texts": {},
    }

    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="recovered abstract",
    )
    result = review.resume(trace_dir, reviewer=FakeReviewer())

    assert [record["datalink_id"] for record in result["accessions"]] == ["GSE1"]
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "recovered abstract"
    ]


def test_normal_filterer_reuses_review_created_by_incremental_resume(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="reviewed early",
    )
    snapshot = PublicationTextReviewer().resume(
        trace_dir,
        reviewer=FakeReviewer(),
    )

    result = AtlasFilterer().filter_jsons(
        jsons=snapshot["accessions"],
        theme="fibrosis",
        reviewer=FailingReviewer(),
        _checkpoint_store=store,
    )

    assert result["publication_texts"]["1"]["agentic_curator"]["judgement"] == (
        "relevant"
    )


def test_resume_applies_manifest_repository_selection(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="geo abstract",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="E-MTAB-2",
        scheme="ArrayExpress",
        text="arrayexpress abstract",
    )
    FakeReviewer.calls = []

    result = PublicationTextReviewer().resume(trace_dir, reviewer=FakeReviewer())

    assert [record["datalink_id"] for record in result["accessions"]] == ["GSE1"]
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "geo abstract"
    ]


def test_resume_requires_theme_and_rejects_manifest_conflict(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="abstract",
    )
    manifest_path = trace_dir / "00_run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["theme"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty theme"):
        PublicationTextReviewer().resume(trace_dir, reviewer=FakeReviewer())

    manifest["theme"] = "fibrosis"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        PublicationTextReviewer().resume(
            trace_dir,
            theme="cancer",
            reviewer=FakeReviewer(),
        )

    result = PublicationTextReviewer().resume(
        trace_dir,
        theme="current fibrosis theme",
        allow_theme_override=True,
        reviewer=FakeReviewer(),
    )
    assert result["publication_texts"]["1"]["agentic_curator"]["theme"] == (
        "current fibrosis theme"
    )


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
        "strategy": "direct",
        "evidences": [],
        "judgement": "",
        "reasoning": "",
        "confidence": "",
        "raw_evidences": "not json evidence",
        "raw_judgement": "not json judgement",
        "accessions_to_remove": [],
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
