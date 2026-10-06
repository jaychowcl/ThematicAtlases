from checkpoint_fixtures import conversion_payload
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from meta_standards_converter.helpers.request_helper import (
    HostRequestCooldownDeferred,
)

from ThematicAtlases.filterer.review import (
    REVIEW_CONTRACT_VERSION,
    PublicationTextReviewer,
)
from ThematicAtlases.filterer.resume import TracePublicationReviewResumer
from ThematicAtlases.filterer import review as review_module
from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.miniml_boundary import checkpoint_payload
from ThematicAtlases.run_store import AtlasRunStore
from ThematicAtlases.wrappers.geo import GEOWrapper


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
            "criteria": [
                {
                    "criterion_id": "theme_condition",
                    "status": "fails",
                    "evidence": "The accession does not satisfy the theme.",
                }
            ],
            "confidence": "high",
            "reason": "Mouse-only dataset.",
            "decision": "exclude",
        }
        return {
            "criteria": [
                {
                    "id": "theme_condition",
                    "description": "The accession satisfies the supplied theme.",
                }
            ],
            "judgement": "relevant",
            "reasoning": "The model found a relevant accession.",
            "confidence": "high",
            "accessions_to_remove": [
                {
                    "accession": "GSE2",
                    "reason": "Mouse-only dataset.",
                    "confidence": "high",
                }
            ],
            "accession_assessments": [assessment],
            "review_revision": 1,
            "evidence_contract_version": 2,
            "strategy": strategy,
        }


class FailingReviewer:
    def review_relevancy(self, **kwargs):
        raise AssertionError("review should not be called")


class RubricReviewer:
    derive_calls: list[str] = []
    review_calls: list[dict] = []
    criteria = [
        {
            "id": "theme_condition",
            "description": "The accession satisfies the supplied theme.",
        }
    ]

    def derive_criteria(self, theme):
        self.__class__.derive_calls.append(theme)
        return {"criteria": self.criteria}

    def review_relevancy(
        self,
        *,
        publication_text,
        theme,
        metadata,
        title,
        accessions,
        criteria,
        strategy,
    ):
        self.__class__.review_calls.append(
            {"publication_text": publication_text, "criteria": criteria}
        )
        return {
            "criteria": criteria,
            "judgement": "relevant",
            "reasoning": "The supplied evidence matches the fixed criteria.",
            "confidence": "high",
            "accessions_to_remove": [],
            "accession_assessments": [],
            "review_revision": 4,
            "evidence_contract_version": 2,
            "strategy": strategy,
        }


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
                    "workflow_checkpoint_contract": "2.0",
                    "theme": "fibrosis",
                    "metadata_repositories": ["geo"],
                    "review_before_metadata": True,
                }
            ),
            encoding="utf-8",
        )
    state_path = trace_dir / "atlas_run.sqlite3"
    if not state_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_store = AtlasRunStore(state_path)
        run_store.create_run(
            trace_dir.name,
            f"atlas-{trace_dir.name}",
            "1.0",
            manifest,
        )
    store = CheckpointStore(state_path)
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


def available_geo_metadata(store: CheckpointStore, accession: str, *, partial=False):
    package = {
        "miniml_schema_version": "3.0",
        "source": {"format": "test"},
        "database": [],
        "organization": [],
        "contributor": [],
        "platform": [],
        "sample": [],
        "series": {"iid": accession, "accession": [{"value": accession}]},
    }
    payload = checkpoint_payload([package], checkpoint_version=4)
    if partial:
        payload["repair_summary"] = {"failed_count": 1}
    store.put('metadata_conversion', 'geo:' + str(accession), 1, "available", payload=conversion_payload(payload))


class SnapshotMetadataCollector:
    def __init__(self, *, trace_dir: Path, fail_once=(), terminal=(), on_collect=None):
        self.trace_dir = trace_dir
        self.fail_once = set(fail_once)
        self.terminal = set(terminal)
        self.on_collect = on_collect
        self.calls = []
        self.failures = set()

    def filter_accessions(self, accessions, metadata_repositories=None):
        return list(accessions)

    def available_accession_metadata(
        self,
        jsons,
        metadata_repositories=None,
        checkpoint_store=None,
    ):
        records = []
        for record in jsons:
            accession = record["datalink_id"]
            checkpoint = checkpoint_store.get('metadata_conversion', 'geo:' + str(accession))
            status = None if checkpoint is None else checkpoint["status"]
            metadata_status = (
                "available"
                if status == "available"
                else "unavailable"
                if status == "no_data"
                else "error"
                if status == "terminal_error"
                else "pending"
            )
            records.append(
                {
                    **record,
                    "metadata_repository": "geo",
                    "metadata_status": metadata_status,
                    "accession_metadata": (
                        {"series": {"accession": [{"value": accession}]}}
                        if metadata_status == "available"
                        else None
                    ),
                }
            )
        return records

    def collect_accession_metadata(
        self,
        jsons,
        metadata_repositories=None,
        checkpoint_store=None,
    ):
        assert len(jsons) == 1
        record = jsons[0]
        accession = record["datalink_id"]
        self.calls.append(accession)
        if self.on_collect is not None:
            callback, self.on_collect = self.on_collect, None
            callback()
        if accession in self.terminal:
            checkpoint_store.put(
                'metadata_conversion',
                'geo:' + str(accession),
                len(self.calls),
                "terminal_error",
                error="invalid metadata",
             payload=conversion_payload())
            raise ValueError("invalid metadata")
        if accession in self.fail_once and accession not in self.failures:
            self.failures.add(accession)
            checkpoint_store.put(
                'metadata_conversion',
                'geo:' + str(accession),
                len(self.calls),
                "retryable_error",
                error="temporary metadata timeout",
             payload=conversion_payload())
            raise TimeoutError("temporary metadata timeout")
        available_geo_metadata(checkpoint_store, accession)
        return self.available_accession_metadata(
            jsons,
            metadata_repositories=metadata_repositories,
            checkpoint_store=checkpoint_store,
        )


def snapshot_reviewer(collector: SnapshotMetadataCollector) -> PublicationTextReviewer:
    return PublicationTextReviewer(
        resume_orchestrator_factory=lambda publication_text_reviewer: (
            TracePublicationReviewResumer(
                publication_text_reviewer=publication_text_reviewer,
                collector_factory=lambda: collector,
                filterer_factory=AtlasFilterer,
            )
        )
    )


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
    stored_review = dict(result["1"]["agentic_curator"])
    review_input_hash = stored_review.pop("review_input_hash")
    reviewer_identity = stored_review.pop("reviewer_identity")
    assert stored_review.pop("review_contract_version") == REVIEW_CONTRACT_VERSION
    assert len(review_input_hash) == 64
    assert set(reviewer_identity) >= {
        "provider", "model", "generation", "prompt_sha256"
    }
    assert stored_review.pop("publication_policy")["review_required"]
    assert stored_review == {
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


def test_review_publication_texts_does_not_reuse_unfingerprinted_legacy_review() -> None:
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

    result = PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=FailingReviewer(),
    )

    assert result["1"]["agentic_curator"]["review_status"] == "failed"
    assert result["1"]["agentic_curator"]["error_type"] == "AssertionError"


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

    failed = result["bad"]["agentic_curator"]
    assert failed["theme"] == "fibrosis"
    assert failed["strategy"] == "direct"
    assert failed["review_status"] == "failed"
    assert failed["error_type"] == "ValueError"
    assert failed["error"]["error_type"] == "ValueError"
    assert "LLM response was not valid JSON" not in json.dumps(failed)
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


def test_review_transient_failure_is_checkpointed_and_retried(tmp_path) -> None:
    class RecoveringReviewer:
        calls = 0

        def review_relevancy(self, publication_text, **kwargs):
            self.__class__.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary provider timeout")
            return FakeReviewer().review_relevancy(
                publication_text=publication_text,
                **kwargs,
            )

    store = CheckpointStore(tmp_path / "resume.sqlite")
    reviewer = RecoveringReviewer()
    publication_texts = {"1": {"text": "full text"}}

    PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )
    assert store.items("thematic_review")[0]["status"] == "retryable_error"

    result = PublicationTextReviewer().review_publication_texts(
        publication_texts=publication_texts,
        contexts={},
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    assert reviewer.calls == 2
    assert result["1"]["agentic_curator"]["judgement"] == "relevant"
    assert store.items("thematic_review")[0]["status"] == "available"


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


def test_review_checkpoint_is_invalidated_when_metadata_context_changes(
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

    assert len(FakeReviewer.calls) == 2
    assert result["1"]["agentic_curator"]["judgement"] == "relevant"


def test_review_records_metadata_context_coverage() -> None:
    FakeReviewer.calls = []
    result = PublicationTextReviewer().review_publication_texts(
        publication_texts={"1": {"text": "stable full text"}},
        contexts={
            "1": {
                "title": "Stable title",
                "accessions": ["GSE1", "GSE2"],
                "metadata": [{"accession": "GSE1", "context": "human liver"}],
                "metadata_statuses": {
                    "GSE1": "available",
                    "GSE2": "pending",
                },
            }
        },
        theme="fibrosis",
        reviewer=FakeReviewer(),
    )

    assert result["1"]["agentic_curator"]["metadata_context"] == {
        "used_accessions": ["GSE1"],
        "not_used_accessions": ["GSE2"],
        "statuses": {"GSE1": "available", "GSE2": "pending"},
    }


def test_publication_context_uses_capability_review_identities() -> None:
    publication = {
        "publication_text_ref": "1",
        "title": "Shared publication",
    }
    contexts = PublicationTextReviewer().publication_review_contexts(
        accessions=[
            {"datalink_id": "GSE1", "publications": [publication]},
            {"datalink_id": "GSE2", "publications": [publication]},
            {"datalink_id": "GSM3", "publications": [publication]},
            {"datalink_id": "E-MTAB-6486", "publications": [publication]},
        ]
    )

    assert contexts["1"]["title"] == "Shared publication"
    assert contexts["1"]["accessions"] == ["GSE1", "GSE2", "E-MTAB-6486"]
    assert contexts["1"]["metadata"] == [
        {"accession": "GSE1", "status": "pending", "context": ""},
        {"accession": "GSE2", "status": "pending", "context": ""},
        {"accession": "E-MTAB-6486", "status": "pending", "context": ""},
    ]


def test_direct_review_traces_and_applies_accession_removals(
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
    assert trace["review_revision"] == 1
    assert trace["evidence_contract_version"] == 2
    assert trace["criteria"] == [
        {
            "id": "theme_condition",
            "description": "The accession satisfies the supplied theme.",
        }
    ]
    assert trace["accession_assessments"][0]["decision"] == "exclude"
    assert trace["raw_review"]["criteria"] == trace["criteria"]
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
        prune_accessions=True,
    )
    assert [record["datalink_id"] for record in filtered] == ["GSE1"]


def test_review_derives_and_reuses_one_fixed_criteria_catalogue(tmp_path) -> None:
    RubricReviewer.derive_calls = []
    RubricReviewer.review_calls = []
    store = CheckpointStore(tmp_path / "criteria.sqlite")
    publication_texts = {
        "1": {"text": "first publication"},
        "2": {"text": "second publication"},
    }
    contexts = {"1": {}, "2": {}}
    service = PublicationTextReviewer()
    reviewer = RubricReviewer()

    result = service.review_publication_texts(
        publication_texts=publication_texts,
        contexts=contexts,
        theme="fibrosis",
        reviewer=reviewer,
        checkpoint_store=store,
    )

    assert RubricReviewer.derive_calls == ["fibrosis"]
    assert [call["criteria"] for call in RubricReviewer.review_calls] == [
        RubricReviewer.criteria,
        RubricReviewer.criteria,
    ]
    assert result["1"]["agentic_curator"]["criteria"] == RubricReviewer.criteria
    rubric_key = service._criteria_checkpoint_key(
        theme="fibrosis",
        strategy="direct",
        reviewer_identity=service._reviewer_identity(reviewer),
    )
    assert store.get_meta(rubric_key)["criteria"] == RubricReviewer.criteria

    service.review_publication_texts(
        publication_texts=publication_texts,
        contexts=contexts,
        theme="fibrosis",
        reviewer=RubricReviewer(),
        checkpoint_store=store,
    )
    assert RubricReviewer.derive_calls == ["fibrosis"]
    assert len(RubricReviewer.review_calls) == 2


def test_accession_pruning_defaults_to_non_destructive() -> None:
    accessions = [
        {
            "datalink_id": accession,
            "publications": [{"publication_text_ref": "1"}],
        }
        for accession in ("GSE1", "GSE2")
    ]
    publication_texts = {
        "1": {
            "agentic_curator": {
                "judgement": "relevant",
                "accessions_to_remove": [{"accession": "GSE2"}],
            }
        }
    }

    filtered, _ = PublicationTextReviewer().filtered_result(
        accessions=accessions,
        publication_texts=publication_texts,
        review_filter="none",
    )

    assert [record["datalink_id"] for record in filtered] == ["GSE1", "GSE2"]


def test_accession_pruning_removes_only_rejecting_publication_edge() -> None:
    accessions = [
        {
            "datalink_id": "gse2",
            "publications": [
                {"publication_text_ref": "rejecting"},
                {"publication_text_ref": "retaining"},
            ],
        }
    ]
    publication_texts = {
        "rejecting": {
            "agentic_curator": {
                "judgement": "relevant",
                "accessions_to_remove": [
                    {"accession": " GSE2 ", "reason": "Mouse-only dataset.", "confidence": "high"}
                ],
            }
        },
        "retaining": {
            "agentic_curator": {
                "judgement": "relevant",
                "accessions_to_remove": [],
            }
        },
    }

    filtered, texts = PublicationTextReviewer().filtered_result(
        accessions=accessions,
        publication_texts=publication_texts,
        review_filter="none",
        prune_accessions=True,
    )

    assert filtered == [
        {
            "datalink_id": "gse2",
            "publications": [{"publication_text_ref": "retaining"}],
        }
    ]
    assert set(texts) == {"retaining"}


def test_review_contract_version_requires_run_stable_criteria_catalogues() -> None:
    assert REVIEW_CONTRACT_VERSION == 11


def test_retired_evidence_then_judgement_strategy_is_rejected(tmp_path) -> None:
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

    with pytest.raises(ValueError, match="Unsupported review_strategy"):
        review.review_publication_texts(
            **options, strategy="evidence_then_judgement"
        )

    assert DirectReviewer.calls == []
    assert store.get("thematic_review", "evidence_then_judgement:1") is None


def test_review_checkpoint_identity_includes_provider_model_and_prompt() -> None:
    class IdentityReviewer:
        calls = 0

        def __init__(self, model):
            self.model = model

        def review_execution_identity(self):
            return {
                "provider": "test-provider",
                "model": self.model,
                "generation": {"temperature": 0},
                "prompt_sha256": "prompt-v1",
            }

        def review_relevancy(self, **_kwargs):
            self.__class__.calls += 1
            return {
                "judgement": "relevant",
                "reasoning": "grounded",
                "confidence": "high",
                "criteria": [],
                "accessions_to_remove": [],
                "accession_assessments": [],
                "review_revision": 3,
                "strategy": "direct",
            }

    publication_texts = {"1": {"text": "fibrosis"}}
    contexts = {"1": {"title": "Title", "accessions": ["GSE1"]}}
    review = PublicationTextReviewer()

    first = review.review_publication_texts(
        publication_texts=publication_texts,
        contexts=contexts,
        theme="fibrosis",
        reviewer=IdentityReviewer("model-a"),
    )
    second = review.review_publication_texts(
        publication_texts=first,
        contexts=contexts,
        theme="fibrosis",
        reviewer=IdentityReviewer("model-b"),
    )

    assert IdentityReviewer.calls == 2
    identity = second["1"]["agentic_curator"]["reviewer_identity"]
    assert identity == {
        "max_review_criteria": 12,
        "publication_policy_version": 1,
        "provider": "test-provider",
        "model": "model-b",
        "generation": {"temperature": 0},
        "prompt_sha256": "prompt-v1",
    }


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
        (trace_dir / "incremental_review_progress.json").read_text(encoding="utf-8")
    ) == {"accession_count": 1, "publication_count": 1}


def test_resume_forwards_worker_snapshot_constraints_to_orchestrator(tmp_path) -> None:
    calls = []

    class RecordingResumer:
        def resume(self, **kwargs):
            calls.append(kwargs)
            return {"accessions": [], "publication_texts": {}}

    accessions = [{"datalink_id": "GSE1"}]
    publication_keys = [("MED", "1", "1", "", "")]
    reviewer = PublicationTextReviewer(
        resume_orchestrator_factory=lambda publication_text_reviewer: RecordingResumer()
    )

    result = reviewer.resume(
        tmp_path,
        snapshot_accessions=accessions,
        publication_keys=publication_keys,
        review_action_limit=3,
    )

    assert result == {"accessions": [], "publication_texts": {}}
    assert calls[0]["snapshot_accessions"] is accessions
    assert calls[0]["publication_keys"] is publication_keys
    assert calls[0]["review_action_limit"] == 3


def test_resume_preserves_full_snapshot_defaults_when_constraints_are_omitted(
    tmp_path,
) -> None:
    calls = []

    class RecordingResumer:
        def resume(self, **kwargs):
            calls.append(kwargs)
            return {"accessions": [], "publication_texts": {}}

    reviewer = PublicationTextReviewer(
        resume_orchestrator_factory=lambda publication_text_reviewer: RecordingResumer()
    )

    reviewer.resume(tmp_path)

    assert calls[0]["snapshot_accessions"] is None
    assert calls[0]["publication_keys"] is None
    assert calls[0]["review_action_limit"] is None


def test_review_action_limit_is_applied_after_prerequisite_deferrals(tmp_path):
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir, epmc_id="1", datalink_id="GSE1", text="deferred"
    )
    traced_publication(
        trace_dir, epmc_id="2", datalink_id="GSE2", text="eligible second"
    )
    traced_publication(
        trace_dir, epmc_id="3", datalink_id="GSE3", text="eligible third"
    )
    available_geo_metadata(store, "GSE2")
    available_geo_metadata(store, "GSE3")
    FakeReviewer.calls = []

    result = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        review_action_limit=1,
    )

    assert set(result["publication_texts"]) == {"2"}
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "eligible second"
    ]
    assert result["metadata_summary"]["review_action_limit"] == 1
    assert result["metadata_summary"]["review_action_count"] == 1
    assert result["metadata_summary"]["review_completed_action_count"] == 1
    assert result["metadata_summary"]["review_reused_count"] == 0
    assert result["metadata_summary"]["review_actionable_count"] == 2
    assert result["metadata_summary"]["review_remaining_actionable_count"] == 1


def test_review_action_limit_reuses_prefix_then_advances_to_next_action(tmp_path):
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir, epmc_id="1", datalink_id="GSE1", text="first eligible"
    )
    traced_publication(
        trace_dir, epmc_id="2", datalink_id="GSE2", text="second eligible"
    )
    FakeReviewer.calls = []
    review = PublicationTextReviewer()

    first = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        review_action_limit=1,
    )
    second = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        review_action_limit=1,
    )

    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "first eligible",
        "second eligible",
    ]
    assert first["metadata_summary"]["review_reused_count"] == 0
    assert first["metadata_summary"]["review_remaining_actionable_count"] == 1
    assert second["metadata_summary"]["review_action_count"] == 1
    assert second["metadata_summary"]["review_completed_action_count"] == 1
    assert second["metadata_summary"]["review_reused_count"] == 1
    assert second["metadata_summary"]["review_actionable_count"] == 1
    assert second["metadata_summary"]["review_remaining_actionable_count"] == 0


def test_review_summary_reports_model_request_metrics(tmp_path):
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="eligible publication",
    )
    available_geo_metadata(store, "GSE1")

    class ModelMetrics:
        provider_attempts = 0
        retry_count = 0
        rate_wait_seconds = 0.0

    class MeteredReviewer(FakeReviewer):
        def __init__(self):
            self.llm = ModelMetrics()

        def review_relevancy(self, **kwargs):
            result = super().review_relevancy(**kwargs)
            self.llm.provider_attempts += 3
            self.llm.retry_count += 1
            self.llm.rate_wait_seconds += 1.5
            return result

    reviewer = MeteredReviewer()
    result = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=reviewer,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        review_action_limit=1,
    )

    assert result["metadata_summary"]["provider_attempts"] == 3
    assert result["metadata_summary"]["retry_count"] == 1
    assert result["metadata_summary"]["rate_wait_seconds"] == 1.5


def test_review_persists_and_defers_future_model_cooldown(tmp_path):
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="eligible publication",
    )
    available_geo_metadata(store, "GSE1")

    class ThrottledReviewer(FakeReviewer):
        def review_relevancy(self, **_kwargs):
            raise HostRequestCooldownDeferred("model:test", 4_000_000_000)

    first = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=ThrottledReviewer(),
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        review_action_limit=1,
    )
    checkpoint = store.get("thematic_review", "direct:1")

    assert checkpoint["status"] == "retryable_error"
    assert checkpoint["payload"]["next_retry_at"] == 4_000_000_000
    FakeReviewer.calls = []
    second = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        review_action_limit=1,
    )

    assert FakeReviewer.calls == []
    assert first["metadata_summary"]["review_action_count"] == 1
    assert second["metadata_summary"]["review_action_count"] == 0
    assert second["metadata_summary"]["review_cooldown_deferred_count"] == 1


def test_review_checkpoints_shared_criteria_cooldown_as_retryable(tmp_path):
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="eligible publication",
    )
    available_geo_metadata(store, "GSE1")

    class CriteriaThrottledReviewer(FakeReviewer):
        def derive_criteria(self, _theme):
            raise HostRequestCooldownDeferred("model:test", 4_000_000_000)

        def review_relevancy(self, criteria=None, **kwargs):
            raise AssertionError("review must not start without criteria")

    result = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=CriteriaThrottledReviewer(),
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        review_action_limit=1,
    )
    checkpoint = store.get("thematic_review", "direct:1")

    assert checkpoint["status"] == "retryable_error"
    assert checkpoint["payload"]["next_retry_at"] == 4_000_000_000
    assert result["metadata_summary"]["review_action_count"] == 1


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


def test_main_review_reuses_incremental_checkpoint_without_progress_file(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="shared canonical review",
    )
    available_geo_metadata(store, "GSE1")
    collector = SnapshotMetadataCollector(trace_dir=trace_dir)
    reviewer = FakeReviewer()
    FakeReviewer.calls = []
    sidecar = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=reviewer,
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )
    (trace_dir / "incremental_review_progress.json").unlink()
    unreviewed_texts = {
        publication_ref: {
            key: value
            for key, value in publication_text.items()
            if key != "agentic_curator"
        }
        for publication_ref, publication_text in sidecar["publication_texts"].items()
    }

    main_result = AtlasFilterer().filter_jsons(
        jsons={
            "accessions": sidecar["accessions"],
            "publication_texts": unreviewed_texts,
        },
        theme="fibrosis",
        reviewer=reviewer,
        _checkpoint_store=CheckpointStore(trace_dir / "atlas_run.sqlite3"),
    )

    assert len(FakeReviewer.calls) == 1
    assert main_result["publication_texts"]["1"]["agentic_curator"][
        "judgement"
    ] == "relevant"
    assert not (trace_dir / "incremental_review_progress.json").exists()


def test_resume_can_defer_publications_until_all_linked_metadata_is_resolved(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="available metadata",
    )
    available_geo_metadata(store, "GSE1")
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="pending metadata",
    )
    traced_publication(
        trace_dir,
        epmc_id="3",
        datalink_id="GSE3",
        text="unavailable metadata",
    )
    store.put('metadata_conversion', 'geo:' + str("GSE3"), 3, "no_data", payload=conversion_payload())
    traced_publication(
        trace_dir,
        epmc_id="4",
        datalink_id="GSE4",
        text="mixed metadata",
    )
    shared = store.get("datalinks", "MED:4")
    first_row = shared["payload"]["rows"][0]
    store.put(
        "datalinks",
        "MED:4",
        shared["ordinal"],
        "available",
        payload={
            "rows": [first_row, {**first_row, "datalink_id": "GSE5"}],
        },
    )
    available_geo_metadata(store, "GSE4")
    traced_publication(
        trace_dir,
        epmc_id="5",
        datalink_id="GSE6",
        text="terminal metadata error",
    )
    store.put('metadata_conversion', 'geo:' + str("GSE6"), 5, "terminal_error", error="invalid", payload=conversion_payload())
    traced_publication(
        trace_dir,
        epmc_id="6",
        datalink_id="GSE7",
        text="partial usable metadata",
    )
    available_geo_metadata(store, "GSE7", partial=True)
    FakeReviewer.calls = []

    result = PublicationTextReviewer().resume(
        trace_dir,
        reviewer=FakeReviewer(),
        require_resolved_metadata=True,
    )

    assert set(result["publication_texts"]) == {"1", "3", "5", "6"}
    assert {record["datalink_id"] for record in result["accessions"]} == {
        "GSE1",
        "GSE3",
        "GSE6",
        "GSE7",
    }
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "available metadata",
        "unavailable metadata",
        "terminal metadata error",
        "partial usable metadata",
    ]


def test_resolved_metadata_gate_picks_up_deferred_publication_on_later_snapshot(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="review after metadata",
    )
    FakeReviewer.calls = []
    review = PublicationTextReviewer()

    assert review.resume(
        trace_dir,
        reviewer=FailingReviewer(),
        require_resolved_metadata=True,
    ) == {"accessions": [], "publication_texts": {}}

    available_geo_metadata(store, "GSE1")
    result = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        require_resolved_metadata=True,
    )

    assert set(result["publication_texts"]) == {"1"}
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "review after metadata"
    ]


def test_resume_collects_metadata_for_one_fixed_datalink_snapshot(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="first snapshot",
    )

    def add_later_publication():
        traced_publication(
            trace_dir,
            epmc_id="2",
            datalink_id="GSE2",
            text="later snapshot",
        )

    collector = SnapshotMetadataCollector(
        trace_dir=trace_dir,
        on_collect=add_later_publication,
    )
    review = snapshot_reviewer(collector)
    FakeReviewer.calls = []

    first = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )
    second = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )
    assert set(first["publication_texts"]) == {"1"}
    assert first["metadata_summary"] == {
        "snapshot_datalink_checkpoint_count": 1,
        "snapshot_datalink_row_count": 1,
        "snapshot_accession_count": 1,
        "snapshot_publication_count": 1,
        "selected_publication_count": 1,
        "publication_limit": None,
        "review_action_limit": None,
        "review_action_count": 1,
        "review_completed_action_count": 1,
        "review_reused_count": 0,
        "review_actionable_count": 1,
        "review_remaining_actionable_count": 0,
        "eligible_publication_count": 1,
        "deferred_publication_count": 0,
        "metadata_attempted_count": 1,
        "metadata_reused_count": 0,
        "metadata_deferred_accession_count": 0,
        "metadata_busy_count": 0,
        "metadata_timeout_count": 0,
        "publication_text_deferred_count": 0,
        "publication_text_timeout_count": 0,
        "review_deferred_count": 0,
        "review_timeout_count": 0,
        "review_cooldown_deferred_count": 0,
        "provider_attempts": 0,
        "retry_count": 0,
        "rate_wait_seconds": 0.0,
        "metadata_status_counts": {"available": 1},
        "yielded_to_main": False,
        "main_phase": "missing",
    }
    assert set(second["publication_texts"]) == {"1", "2"}
    assert collector.calls == ["GSE1", "GSE2"]
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "first snapshot",
        "later snapshot",
    ]


def test_snapshot_yields_without_work_when_main_has_left_datalinks(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="main owns downstream",
    )
    store.set_meta(
        "pipeline_position",
        {"phase": "downstream", "invocation_id": "main-1"},
    )
    collector = SnapshotMetadataCollector(trace_dir=trace_dir)
    FakeReviewer.calls = []

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
    )

    assert result["accessions"] == []
    assert result["publication_texts"] == {}
    assert result["metadata_summary"]["yielded_to_main"] is True
    assert result["metadata_summary"]["main_phase"] == "downstream"
    assert collector.calls == []
    assert FakeReviewer.calls == []
    assert (trace_dir / "incremental_review_progress.json").exists()
    assert not (trace_dir / "resume_review_progress.json").exists()


def test_snapshot_cancellation_is_not_reported_as_yield_to_main(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="cancelled worker",
    )
    store.set_meta("pipeline_position", {"phase": "datalinks"})
    collector = SnapshotMetadataCollector(trace_dir=trace_dir)

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
        cancelled=lambda: True,
    )

    assert result["metadata_summary"]["yielded_to_main"] is False
    assert result["metadata_summary"]["main_phase"] == "datalinks"
    assert collector.calls == []


def test_snapshot_stops_starting_items_when_main_enters_downstream(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="finishes before transition",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="must remain deferred",
    )
    store.set_meta("pipeline_position", {"phase": "datalinks"})

    def transition_main():
        store.set_meta("pipeline_position", {"phase": "downstream"})

    collector = SnapshotMetadataCollector(
        trace_dir=trace_dir,
        on_collect=transition_main,
    )
    FakeReviewer.calls = []

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
    )

    assert collector.calls == ["GSE1"]
    assert store.get('metadata_conversion', 'geo:' + str("GSE1"))["status"] == "available"
    assert store.get('metadata_conversion', 'geo:' + str("GSE2")) is None
    assert result["publication_texts"] == {}
    assert result["metadata_summary"]["yielded_to_main"] is True
    assert result["metadata_summary"]["main_phase"] == "downstream"
    assert FakeReviewer.calls == []


def test_snapshot_publication_limit_is_deterministic_and_applied_before_metadata(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="3",
        datalink_id="GSE3",
        text="third publication",
    )
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="first publication",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="second publication",
    )
    store.set_meta("pipeline_position", {"phase": "datalinks"})
    collector = SnapshotMetadataCollector(trace_dir=trace_dir)
    FakeReviewer.calls = []

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
        publication_limit=2,
    )

    assert collector.calls == ["GSE1", "GSE2"]
    assert set(result["publication_texts"]) == {"1", "2"}
    assert result["metadata_summary"]["snapshot_publication_count"] == 3
    assert result["metadata_summary"]["selected_publication_count"] == 2
    assert result["metadata_summary"]["publication_limit"] == 2


def test_snapshot_stops_before_next_review_when_main_enters_downstream(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="first review",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="second review",
    )
    available_geo_metadata(store, "GSE1")
    available_geo_metadata(store, "GSE2")
    store.set_meta("pipeline_position", {"phase": "datalinks"})
    collector = SnapshotMetadataCollector(trace_dir=trace_dir)

    class TransitioningReviewer(FakeReviewer):
        calls = []

        def review_relevancy(self, **kwargs):
            result = super().review_relevancy(**kwargs)
            store.set_meta("pipeline_position", {"phase": "downstream"})
            return result

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=TransitioningReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
    )

    assert [call["publication_text"] for call in TransitioningReviewer.calls] == [
        "first review"
    ]
    assert set(result["publication_texts"]) == {"1"}
    assert result["metadata_summary"]["yielded_to_main"] is True
    assert result["metadata_summary"]["main_phase"] == "downstream"
    assert store.get("thematic_review", "direct:2") is None


def test_snapshot_metadata_deadline_defers_one_item_and_continues(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="slow metadata",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="fast metadata",
    )
    store.set_meta("pipeline_position", {"phase": "datalinks"})

    class SlowFirstCollector(SnapshotMetadataCollector):
        def collect_accession_metadata(self, jsons, **kwargs):
            if jsons[0]["datalink_id"] == "GSE1":
                self.calls.append("GSE1")
                time.sleep(1)
            return super().collect_accession_metadata(jsons, **kwargs)

    collector = SlowFirstCollector(trace_dir=trace_dir)
    FakeReviewer.calls = []
    started = time.monotonic()
    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
        metadata_item_timeout_seconds=0.05,
    )

    assert time.monotonic() - started < 1.5
    assert collector.calls == ["GSE1", "GSE2"]
    assert result["metadata_summary"]["metadata_timeout_count"] == 1
    assert store.get('metadata_conversion', 'geo:' + str("GSE1")) is None
    assert store.get('metadata_conversion', 'geo:' + str("GSE2"))["status"] == "available"
    assert set(result["publication_texts"]) == {"2"}
    assert store.get_meta("pipeline_position")["phase"] == "datalinks"


def test_snapshot_review_deadline_releases_lock_and_continues(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="slow review",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="fast review",
    )
    available_geo_metadata(store, "GSE1")
    available_geo_metadata(store, "GSE2")
    store.set_meta("pipeline_position", {"phase": "datalinks"})

    class SlowFirstReviewer(FakeReviewer):
        calls = []

        def review_relevancy(self, **kwargs):
            if kwargs.get("publication_text") == "slow review":
                self.__class__.calls.append(kwargs)
                time.sleep(1)
            return super().review_relevancy(**kwargs)

    started = time.monotonic()
    result = snapshot_reviewer(
        SnapshotMetadataCollector(trace_dir=trace_dir)
    ).resume(
        trace_dir,
        reviewer=SlowFirstReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
        item_lock_timeout_seconds=0.05,
        review_item_timeout_seconds=0.05,
    )

    assert time.monotonic() - started < 1.5
    assert result["metadata_summary"]["review_timeout_count"] == 1
    assert set(result["publication_texts"]) == {"2"}
    assert store.get("thematic_review", "direct:1") is None
    assert store.get("thematic_review", "direct:2")["status"] == "available"
    with CheckpointStore(trace_dir / "atlas_run.sqlite3").item_lock(
        "thematic_review",
        "direct:1",
        timeout_seconds=0,
    ):
        pass


def test_snapshot_publication_text_deadline_defers_one_item_and_continues(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="slow full text",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="fast full text",
    )
    available_geo_metadata(store, "GSE1")
    available_geo_metadata(store, "GSE2")
    store.set_meta("pipeline_position", {"phase": "datalinks"})

    class SlowFirstTextFilterer(AtlasFilterer):
        calls = []

        def collect_publication_texts(self, jsons, **kwargs):
            publication_ref = self.publication_text_ref(jsons[0]["publications"][0])
            self.__class__.calls.append(publication_ref)
            if publication_ref == "1":
                time.sleep(1)
            return {
                publication_ref: {
                    "text": "fast full text",
                    "text_source": "abstractText",
                    "full_text_status": "unavailable",
                }
            }

    collector = SnapshotMetadataCollector(trace_dir=trace_dir)
    review = PublicationTextReviewer(
        resume_orchestrator_factory=lambda publication_text_reviewer: (
            TracePublicationReviewResumer(
                publication_text_reviewer=publication_text_reviewer,
                collector_factory=lambda: collector,
                filterer_factory=SlowFirstTextFilterer,
            )
        )
    )
    FakeReviewer.calls = []
    started = time.monotonic()
    result = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
        require_main_datalinks_phase=True,
        publication_text_item_timeout_seconds=0.05,
    )

    assert time.monotonic() - started < 1.5
    assert SlowFirstTextFilterer.calls == ["1", "2"]
    assert result["metadata_summary"]["publication_text_timeout_count"] == 1
    assert set(result["publication_texts"]) == {"2"}
    assert store.get("thematic_review", "direct:1") is None
    assert store.get("thematic_review", "direct:2")["status"] == "available"


def test_resume_metadata_failures_defer_linked_publications_and_continue(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="unrelated success",
    )
    traced_publication(
        trace_dir,
        epmc_id="2",
        datalink_id="GSE2",
        text="retry later",
    )
    traced_publication(
        trace_dir,
        epmc_id="3",
        datalink_id="GSE3",
        text="terminal manual retry",
    )
    collector = SnapshotMetadataCollector(
        trace_dir=trace_dir,
        fail_once={"GSE2"},
        terminal={"GSE3"},
    )
    review = snapshot_reviewer(collector)
    FakeReviewer.calls = []

    first = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )
    second = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )
    collector.terminal.clear()
    CheckpointStore(trace_dir / "atlas_run.sqlite3").request_retries(
        items={"metadata_conversion": ["geo:GSE3"]}
    )
    third = review.resume(
        trace_dir,
        reviewer=FakeReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )

    assert set(first["publication_texts"]) == {"1"}
    assert first["metadata_summary"]["metadata_deferred_accession_count"] == 2
    assert first["metadata_summary"]["snapshot_publication_count"] == 3
    assert first["metadata_summary"]["eligible_publication_count"] == 1
    assert first["metadata_summary"]["deferred_publication_count"] == 2
    assert first["metadata_summary"]["metadata_status_counts"] == {
        "available": 1,
        "error": 1,
        "pending": 1,
    }
    assert set(second["publication_texts"]) == {"1", "2"}
    assert second["metadata_summary"]["metadata_deferred_accession_count"] == 1
    assert set(third["publication_texts"]) == {"1", "2", "3"}
    assert collector.calls == ["GSE1", "GSE2", "GSE3", "GSE2", "GSE3"]
    assert [call["publication_text"] for call in FakeReviewer.calls] == [
        "unrelated success",
        "retry later",
        "terminal manual retry",
    ]


def test_resume_defers_publication_when_any_linked_metadata_download_fails(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="two linked accessions",
    )
    item = store.get("datalinks", "MED:1")
    row = item["payload"]["rows"][0]
    store.put(
        "datalinks",
        "MED:1",
        item["ordinal"],
        "available",
        payload={"rows": [row, {**row, "datalink_id": "GSE2"}]},
    )
    collector = SnapshotMetadataCollector(
        trace_dir=trace_dir,
        fail_once={"GSE2"},
    )

    result = snapshot_reviewer(collector).resume(
        trace_dir,
        reviewer=FailingReviewer(),
        collect_metadata=True,
        require_resolved_metadata=True,
        defer_metadata_errors=True,
    )

    assert result["accessions"] == []
    assert result["publication_texts"] == {}
    assert result["metadata_summary"]["metadata_deferred_accession_count"] == 1
    assert result["metadata_summary"]["deferred_publication_count"] == 1


def test_snapshot_and_main_metadata_collection_share_accession_lock(tmp_path) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="shared metadata download",
    )
    started = threading.Event()
    release = threading.Event()
    calls = []

    from test_geo_wrapper import FakeGEOWrapper
    class SlowGeo(FakeGEOWrapper):
        def metadata_packages_for_test(self, gse_accession):
            calls.append(gse_accession)
            started.set()
            assert release.wait(timeout=5)
            return [
                {
                    "miniml_schema_version": "3.0",
                    "source": {"format": "test"},
                    "database": [],
                    "organization": [],
                    "contributor": [],
                    "platform": [],
                    "sample": [],
                    "series": {
                        "iid": gse_accession,
                        "accession": [{"value": gse_accession}],
                    },
                }
            ]

    def collector_factory():
        return AtlasCollector(
            metadata_handlers={"geo": SlowGeo},
            metadata_repositories=["geo"],
        )

    review = PublicationTextReviewer(
        resume_orchestrator_factory=lambda publication_text_reviewer: (
            TracePublicationReviewResumer(
                publication_text_reviewer=publication_text_reviewer,
                collector_factory=collector_factory,
                filterer_factory=AtlasFilterer,
            )
        )
    )
    main_record = {
        "datalink_id": "GSE1",
        "datalink_id_scheme": "GEO",
        "publications": [{"source": "MED", "epmc_id": "1"}],
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        sidecar = executor.submit(
            review.resume,
            trace_dir,
            reviewer=FakeReviewer(),
            collect_metadata=True,
            require_resolved_metadata=True,
            defer_metadata_errors=True,
        )
        assert started.wait(timeout=5)
        main = executor.submit(
            collector_factory().collect_accession_metadata,
            [main_record],
            checkpoint_store=store,
        )
        release.set()
        assert sidecar.result()["publication_texts"]["1"]["agentic_curator"][
            "judgement"
        ] == "relevant"
        assert main.result()[0]["metadata_status"] == "available"

    assert calls == ["GSE1"]


def test_resume_rereviews_when_metadata_becomes_available(tmp_path, monkeypatch) -> None:
    trace_dir = tmp_path / "trace"
    store = traced_publication(
        trace_dir,
        epmc_id="1",
        datalink_id="GSE1",
        text="stable abstract",
    )
    monkeypatch.setattr(
        review_module,
        "build_miniml_metadata_context",
        lambda metadata: "compact metadata" if metadata else "",
    )
    FakeReviewer.calls = []
    review = PublicationTextReviewer()

    first = review.resume(trace_dir, reviewer=FakeReviewer())
    store.put(
        'metadata_conversion',
        'geo:' + str("GSE1"),
        1,
        "available",
        payload=conversion_payload(checkpoint_payload(
            [{
                "miniml_schema_version": "3.0",
                "source": {"format": "test"},
                "database": [], "organization": [], "contributor": [],
                "platform": [], "sample": [],
                "series": {"iid": "GSE1", "accession": [{"value": "GSE1"}]},
            }],
            checkpoint_version=4,
        )),
    )
    second = review.resume(trace_dir, reviewer=FakeReviewer())

    assert len(FakeReviewer.calls) == 2
    assert first["publication_texts"]["1"]["agentic_curator"]["metadata_context"] == {
        "used_accessions": [],
        "not_used_accessions": ["GSE1"],
        "statuses": {"GSE1": "pending"},
    }
    assert second["publication_texts"]["1"]["agentic_curator"]["metadata_context"] == {
        "used_accessions": ["GSE1"],
        "not_used_accessions": [],
        "statuses": {"GSE1": "available"},
    }


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
    FakeReviewer.calls = []
    snapshot = PublicationTextReviewer().resume(
        trace_dir,
        reviewer=FakeReviewer(),
    )

    result = AtlasFilterer().filter_jsons(
        jsons=snapshot["accessions"],
        theme="fibrosis",
        reviewer=FakeReviewer(),
        _checkpoint_store=store,
    )

    assert result["publication_texts"]["1"]["agentic_curator"]["judgement"] == (
        "relevant"
    )
    assert len(FakeReviewer.calls) == 1


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

    assert result.pop("publication_policy")["review_required"]
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


def test_filtered_result_retains_historical_reviews_without_confidence() -> None:
    accessions, publication_texts = reviewed_atlas_parts()

    filtered_accessions, filtered_publication_texts = (
        PublicationTextReviewer().filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter="not_relevant_and_unsure",
        )
    )

    assert filtered_accessions == accessions
    assert set(filtered_publication_texts) == set(publication_texts)
    assert all(t["agentic_curator"]["publication_policy"]["review_required"] for t in filtered_publication_texts.values())
