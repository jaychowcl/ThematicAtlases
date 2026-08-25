from __future__ import annotations

import json

import pytest

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.cli_atlas import _build_parser
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer.filterer import AtlasFilterer
from ThematicAtlases.filterer.resume import TracePublicationReviewResumer
from ThematicAtlases.filterer.review import PublicationTextReviewer
from ThematicAtlases.pipeline import (
    AtlasStagePause,
    STOP_AFTER_STAGES,
)
from ThematicAtlases.stage_worker import (
    StageWorkerBusy,
    TraceStageWorker,
    stage_worker_activity_lock,
)
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


class RecordingEPMC(EuropePMCWrapper):
    def __init__(self):
        super().__init__(request_delay=0)
        self.calls = []

    def collect_publications(self, **kwargs):
        self.calls.append("query-results")
        return [
            {
                "source": "MED",
                "epmc_id": "1",
                "pmid": "1",
                "title": "Fibrosis",
                "abstract": "GSE1",
            }
        ]

    def collect_datalinks(self, **kwargs):
        self.calls.append("datalinks")
        publication = kwargs["publications"][0]
        return [
            {
                "datalink_id": "GSE1",
                "publications": [publication],
            }
        ]

    def collect_publication_texts(self, publications, checkpoint_store=None):
        self.calls.append("publication-text")
        return [
            {
                **publications[0],
                "text": "GSE1",
                "text_source": "abstractText",
                "full_text_status": "available",
            }
        ]

    def accessions_from_fulltexts(self, publications, checkpoint_store=None):
        self.calls.append("fulltext-accessions")
        return []

    def accessions_from_link_graph(self, publications, **kwargs):
        self.calls.append("accession-graph")
        return []


@pytest.mark.parametrize(
    "stage, expected_calls",
    [
        ("query-results", ["query-results"]),
        ("datalinks", ["query-results", "datalinks"]),
        (
            "publication-text",
            ["query-results", "datalinks", "publication-text"],
        ),
        (
            "fulltext-accessions",
            [
                "query-results",
                "datalinks",
                "publication-text",
                "fulltext-accessions",
            ],
        ),
        (
            "accession-graph",
            [
                "query-results",
                "datalinks",
                "publication-text",
                "fulltext-accessions",
                "accession-graph",
            ],
        ),
    ],
)
def test_epmc_stops_at_each_discovery_boundary(stage, expected_calls):
    wrapper = RecordingEPMC()

    with pytest.raises(AtlasStagePause) as raised:
        wrapper.collect_accessions(
            queries=["fibrosis"],
            scrape_fulltext_accessions=True,
            stop_after=stage,
        )

    assert raised.value.stage == stage
    assert [
        record["datalink_id"] for record in raised.value.result["accessions"]
    ] == ([] if stage == "query-results" else ["GSE1"])
    assert wrapper.calls == expected_calls


def test_stop_after_contract_lists_every_major_boundary():
    assert STOP_AFTER_STAGES == (
        "query-results",
        "datalinks",
        "publication-text",
        "fulltext-accessions",
        "accession-graph",
        "metadata",
        "review",
        "harmonization",
    )


def test_generic_cli_accepts_every_stop_boundary_on_create_and_resume():
    parser = _build_parser()
    for stage in STOP_AFTER_STAGES:
        created = parser.parse_args(
            ["create-atlas", "--theme", "fibrosis", "--stop-after", stage]
        )
        resumed = parser.parse_args(["resume", "--stop-after", stage])
        assert created.stop_after == stage
        assert resumed.stop_after == stage


@pytest.mark.parametrize("stage", ["metadata", "review", "harmonization"])
def test_collector_keeps_downstream_pause_targets_out_of_epmc(stage):
    calls = []

    class EPMC:
        def collect_accessions(self, **kwargs):
            calls.append(kwargs)
            return []

    collector = AtlasCollector(
        epmc_wrapper_factory=EPMC,
        metadata_handlers={},
    )
    if stage == "metadata":
        with pytest.raises(AtlasStagePause):
            collector.collect_jsons(query=["fibrosis"], stop_after=stage)
    else:
        collector.collect_jsons(query=["fibrosis"], stop_after=stage)

    assert "stop_after" not in calls[0]


@pytest.mark.parametrize("stage", ["publication-text", "fulltext-accessions"])
def test_text_pause_targets_require_text_scraping(stage):
    with pytest.raises(ValueError, match="scrape_fulltext_accessions"):
        Atlas(metadata={"atlas_id": "fibrosis"}).create_atlas(
            theme="fibrosis",
            query=["fibrosis"],
            generate_queries=False,
            scrape_fulltext_accessions=False,
            dev_trace=True,
            dev_out_dir="unused",
            stop_after=stage,
        )


def _worker_trace(tmp_path):
    trace = DevTraceWriter(
        root=tmp_path,
        run_id="run-1",
        manifest={
            "command": "create-atlas",
            "query": ["fibrosis"],
            "metadata_repositories": ["geo", "arrayexpress"],
            "theme": "fibrosis",
        },
    )
    publication_available = {
        "source": "MED",
        "epmc_id": "1",
        "pmid": "1",
    }
    publication_no_data = {
        "source": "MED",
        "epmc_id": "2",
        "pmid": "2",
    }
    trace.checkpoint_store.put(
        "search_pages",
        "query:000001",
        1,
        "available",
        payload={"publications": [publication_available, publication_no_data]},
    )
    trace.checkpoint_store.put(
        "datalinks",
        "MED:1",
        1,
        "available",
        payload={"rows": []},
    )
    trace.checkpoint_store.put(
        "datalinks",
        "MED:2",
        2,
        "no_data",
        payload={"rows": []},
    )
    trace.checkpoint_store.set_meta(
        "main_pipeline_phase", {"phase": "datalinks"}
    )
    return trace


def test_worker_frontier_includes_authoritative_no_data_datalinks(tmp_path):
    trace = _worker_trace(tmp_path)

    publications = TraceStageWorker().eligible_publications(
        trace.directory,
    )

    assert [publication["pmid"] for publication in publications] == ["1", "2"]


def test_text_worker_fetches_and_scrapes_one_fixed_terminal_frontier(tmp_path):
    trace = _worker_trace(tmp_path)
    calls = []

    class EPMC:
        def collect_publication_texts(self, publications, checkpoint_store=None):
            publication = {**publications[0], "text": "GSE1"}
            calls.append(("text", publication["pmid"]))
            checkpoint_store.put(
                "publication_text",
                f"MED:{publication['epmc_id']}",
                int(publication["pmid"]),
                "available",
                payload={"contract_version": 1, "publication": publication},
            )
            return [publication]

        def accessions_from_fulltexts(self, publications, checkpoint_store=None):
            calls.append(("scrape", publications[0]["pmid"]))
            checkpoint_store.put(
                "fulltext_accession_discovery",
                f"MED:{publications[0]['epmc_id']}",
                int(publications[0]["pmid"]),
                "no_data",
                payload={"contract_version": 1, "records": []},
            )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="text",
    )

    assert result["selected_count"] == 2
    assert result["completed_count"] == 2
    assert result["yielded_to_main"] is False
    assert calls == [
        ("text", "1"),
        ("scrape", "1"),
        ("text", "2"),
        ("scrape", "2"),
    ]
    progress = json.loads(
        (trace.directory / "incremental_text_progress.json").read_text()
    )
    assert progress == result


def test_text_worker_reports_actual_request_policy_metrics(tmp_path):
    trace = _worker_trace(tmp_path)

    class Policy:
        provider_attempts = 4
        retry_count = 2
        rate_wait_seconds = 1.25

    class EPMC:
        _request_policy = Policy()

        def collect_publication_texts(self, publications, checkpoint_store=None):
            publication = publications[0]
            checkpoint_store.put(
                "publication_text",
                f"MED:{publication['epmc_id']}",
                int(publication["pmid"]),
                "no_data",
            )
            return [publication]

        def accessions_from_fulltexts(self, publications, checkpoint_store=None):
            publication = publications[0]
            checkpoint_store.put(
                "fulltext_accession_discovery",
                f"MED:{publication['epmc_id']}",
                int(publication["pmid"]),
                "no_data",
            )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="text",
        item_limit=1,
    )

    assert result["provider_attempts"] == 4
    assert result["retry_count"] == 2
    assert result["rate_wait_seconds"] == 1.25


def test_text_worker_applies_limit_after_completed_prefix(tmp_path):
    trace = _worker_trace(tmp_path)
    for stage in ("publication_text", "fulltext_accession_discovery"):
        trace.checkpoint_store.put(
            stage,
            "MED:1",
            1,
            "no_data",
            payload={"records": []},
        )
    calls = []

    class EPMC:
        def collect_publication_texts(self, publications, checkpoint_store=None):
            calls.append(publications[0]["pmid"])
            checkpoint_store.put("publication_text", "MED:2", 2, "no_data")
            return [publications[0]]

        def accessions_from_fulltexts(self, publications, checkpoint_store=None):
            checkpoint_store.put(
                "fulltext_accession_discovery", "MED:2", 2, "no_data"
            )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="text",
        item_limit=1,
    )

    assert calls == ["2"]
    assert result["selected_count"] == 1
    assert result["scanned"] == 2
    assert result["actionable"] == 1


def test_text_worker_cancellation_finishes_current_item_and_records_summary(tmp_path):
    trace = _worker_trace(tmp_path)
    cancelled = False
    calls = []

    class EPMC:
        def collect_publication_texts(self, publications, checkpoint_store=None):
            nonlocal cancelled
            publication = publications[0]
            calls.append(publication["pmid"])
            checkpoint_store.put(
                "publication_text",
                f"MED:{publication['epmc_id']}",
                int(publication["pmid"]),
                "no_data",
            )
            cancelled = True
            return [publication]

        def accessions_from_fulltexts(self, publications, checkpoint_store=None):
            publication = publications[0]
            checkpoint_store.put(
                "fulltext_accession_discovery",
                f"MED:{publication['epmc_id']}",
                int(publication["pmid"]),
                "no_data",
            )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="text",
        cancelled=lambda: cancelled,
    )

    assert calls == ["1"]
    assert result["interrupted"] is True
    assert result["completed_count"] == 1
    assert result["deferred_count"] == 1
    assert trace.run_store.events(trace.directory.name)[-1]["event_type"] == (
        "stage_worker_interrupted"
    )


def test_graph_worker_terminally_resolves_no_data_datalinks_publications(tmp_path):
    trace = _worker_trace(tmp_path)

    class EPMC:
        def accessions_from_link_graph(
            self, publications, *, checkpoint_store, continue_predicate
        ):
            for index, publication in enumerate(publications, start=1):
                checkpoint_store.put(
                    "pubmed_gds_links",
                    publication["pmid"],
                    index,
                    "no_data",
                    payload={"target_uids": []},
                )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="graph",
    )

    assert result["selected_count"] == 2
    assert result["completed_count"] == 2
    assert result["deferred_count"] == 0


def test_graph_worker_applies_limit_after_completed_prefix(tmp_path):
    trace = _worker_trace(tmp_path)
    trace.checkpoint_store.put(
        "pubmed_gds_links", "1", 1, "no_data", payload={"target_uids": []}
    )
    calls = []

    class EPMC:
        def accessions_from_link_graph(
            self, publications, *, checkpoint_store, continue_predicate
        ):
            calls.extend(publication["pmid"] for publication in publications)
            checkpoint_store.put(
                "pubmed_gds_links", "2", 2, "no_data", payload={"target_uids": []}
            )
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="graph",
        item_limit=1,
    )

    assert calls == ["2"]
    assert result["selected_count"] == 1
    assert result["remaining_actionable"] == 0


def test_graph_worker_defers_persisted_future_cooldown(tmp_path):
    trace = _worker_trace(tmp_path)
    trace.checkpoint_store.put(
        "pubmed_gds_links",
        "1",
        1,
        "retryable_error",
        payload={"next_retry_at": 4_000_000_000},
    )
    trace.checkpoint_store.put(
        "pubmed_gds_links", "2", 2, "no_data", payload={"target_uids": []}
    )
    calls = []

    class EPMC:
        def accessions_from_link_graph(self, publications, **kwargs):
            calls.extend(publications)
            return []

    result = TraceStageWorker(epmc_wrapper_factory=EPMC).resume(
        trace.directory,
        stage="graph",
        item_limit=1,
    )

    assert calls == []
    assert result["actionable"] == 0
    assert result["cooldown_deferred"] == 1


def test_metadata_worker_merges_all_discovery_sources_and_limits_accessions(
    tmp_path,
):
    trace = _worker_trace(tmp_path)
    publication = {
        "source": "MED",
        "epmc_id": "1",
        "pmid": "1",
    }
    trace.checkpoint_store.put(
        "datalinks",
        "MED:1",
        1,
        "available",
        payload={
            "rows": [
                {"datalink_id": "GSE1", "publications": [publication]}
            ]
        },
    )
    trace.checkpoint_store.put(
        "fulltext_accession_discovery",
        "MED:1",
        1,
        "available",
        payload={
            "records": [
                {"datalink_id": "GSE2", "publications": [publication]}
            ]
        },
    )
    calls = []

    class EPMC:
        def accessions_from_datalinks(self, rows):
            return rows

        def accessions_from_link_graph(
            self, publications, *, checkpoint_store, cached_only
        ):
            return [{"datalink_id": "GSE3", "publications": publications[:1]}]

        def merge_accessions(self, *groups):
            return [record for group in groups for record in group]

    class Collector:
        def filter_accessions(self, accessions, metadata_repositories):
            return accessions

        def collect_accession_metadata(
            self, *, jsons, metadata_repositories, checkpoint_store
        ):
            calls.append(jsons[0]["datalink_id"])
            return [{**jsons[0], "metadata_status": "available"}]

    result = TraceStageWorker(
        epmc_wrapper_factory=EPMC,
        collector_factory=Collector,
    ).resume(trace.directory, stage="metadata", item_limit=2)

    assert calls == ["GSE1", "GSE2"]
    assert result["selected_count"] == 2
    assert result["completed_count"] == 2


def test_metadata_worker_applies_limit_after_compatible_prefix(tmp_path):
    trace = _worker_trace(tmp_path)
    publication = {"source": "MED", "epmc_id": "1", "pmid": "1"}
    trace.checkpoint_store.put(
        "datalinks",
        "MED:1",
        1,
        "available",
        payload={
            "rows": [
                {"datalink_id": "GSE1", "publications": [publication]},
                {"datalink_id": "GSE2", "publications": [publication]},
            ]
        },
    )
    calls = []

    class EPMC:
        def accessions_from_datalinks(self, rows):
            return rows

        def accessions_from_link_graph(self, publications, **kwargs):
            return []

        def merge_accessions(self, *groups):
            return [record for group in groups for record in group]

    class Collector:
        def filter_accessions(self, accessions, metadata_repositories=None):
            return accessions

        def available_accession_metadata(self, jsons, **kwargs):
            return [
                {
                    **record,
                    "metadata_status": (
                        "available"
                        if record["datalink_id"] == "GSE1"
                        else "missing"
                    ),
                }
                for record in jsons
            ]

        def collect_accession_metadata(self, *, jsons, **kwargs):
            calls.append(jsons[0]["datalink_id"])
            return [{**jsons[0], "metadata_status": "available"}]

    result = TraceStageWorker(
        epmc_wrapper_factory=EPMC,
        collector_factory=Collector,
    ).resume(trace.directory, stage="metadata", item_limit=1)

    assert calls == ["GSE2"]
    assert result["scanned"] == 2
    assert result["reused"] == 1


def test_metadata_worker_reports_collector_provider_metrics(tmp_path):
    trace = _worker_trace(tmp_path)
    publication = {"source": "MED", "epmc_id": "1", "pmid": "1"}
    trace.checkpoint_store.put(
        "datalinks",
        "MED:1",
        1,
        "available",
        payload={
            "rows": [
                {"datalink_id": "GSE1", "publications": [publication]},
            ]
        },
    )

    class EPMC:
        def accessions_from_datalinks(self, rows):
            return rows

        def accessions_from_link_graph(self, publications, **kwargs):
            return []

        def merge_accessions(self, *groups):
            return [record for group in groups for record in group]

    class Collector:
        provider_attempts = 3
        retry_count = 1
        rate_wait_seconds = 0.75

        def filter_accessions(self, accessions, metadata_repositories=None):
            return accessions

        def collect_accession_metadata(self, *, jsons, **kwargs):
            return [{**jsons[0], "metadata_status": "available"}]

    result = TraceStageWorker(
        epmc_wrapper_factory=EPMC,
        collector_factory=Collector,
    ).resume(trace.directory, stage="metadata", item_limit=1)

    assert result["provider_attempts"] == 3
    assert result["retry_count"] == 1
    assert result["rate_wait_seconds"] == 0.75


def test_worker_yields_without_claiming_when_main_is_downstream(tmp_path):
    trace = _worker_trace(tmp_path)
    trace.checkpoint_store.set_meta(
        "main_pipeline_phase", {"phase": "downstream"}
    )

    result = TraceStageWorker().resume(trace.directory, stage="graph")

    assert result["selected_count"] == 0
    assert result["yielded_to_main"] is True


def test_worker_reports_per_stage_singleton_contention_as_busy(tmp_path):
    trace = _worker_trace(tmp_path)

    with stage_worker_activity_lock(trace.directory, "text"):
        with pytest.raises(StageWorkerBusy):
            TraceStageWorker().resume(trace.directory, stage="text")


def test_review_worker_uses_only_terminal_discovery_frontiers(tmp_path):
    trace = _worker_trace(tmp_path)
    store = trace.checkpoint_store
    for stage in ("publication_text", "fulltext_accession_discovery"):
        store.put(stage, "MED:1", 1, "no_data", payload={"records": []})
    store.put(
        "pubmed_gds_links",
        "1",
        1,
        "available",
        payload={"target_uids": ["101"]},
    )
    store.put("gds_summaries", "101", 1, "no_data", payload={})
    calls = []

    class RecordingResumer:
        def resume(self, **kwargs):
            calls.append(kwargs)
            return {
                "accessions": [],
                "publication_texts": {},
                "metadata_summary": {
                    "selected_publication_count": 1,
                    "review_deferred_count": 0,
                    "deferred_publication_count": 0,
                },
            }

    def reviewer_factory():
        return PublicationTextReviewer(
            resume_orchestrator_factory=lambda publication_text_reviewer: (
                RecordingResumer()
            )
        )

    worker = TraceStageWorker(publication_text_reviewer_factory=reviewer_factory)
    result = worker.resume(trace.directory, stage="review")

    assert result["selected_count"] == 1
    assert calls[0]["publication_keys"] == [("MED", "1", "1", "", "")]


def test_review_worker_limits_real_facade_and_writes_review_checkpoint(tmp_path):
    trace = _worker_trace(tmp_path)
    store = trace.checkpoint_store
    for ordinal in (1, 2):
        publication = {
            "source": "MED",
            "epmc_id": str(ordinal),
            "pmid": str(ordinal),
            "pmcid": "",
            "doi": "",
            "title": f"Fibrosis publication {ordinal}",
            "abstractText": "Fibrotic human tissue profiled by RNA sequencing.",
            "text": "Fibrotic human tissue profiled by RNA sequencing.",
            "text_source": "abstractText",
            "full_text_status": "unavailable",
        }
        store.put(
            "datalinks",
            f"MED:{ordinal}",
            ordinal,
            "available",
            payload={
                "rows": [
                    {
                        **publication,
                        "datalink_id": f"GSE{ordinal}",
                        "datalink_id_scheme": "GEO",
                        "datalink_category": "GEO",
                    }
                ]
            },
        )
        store.put(
            "publication_text",
            f"MED:{ordinal}",
            ordinal,
            "available",
            payload={"publication": publication},
        )
        store.put(
            "fulltext_accession_discovery",
            f"MED:{ordinal}",
            ordinal,
            "no_data",
            payload={"records": []},
        )
        store.put(
            "pubmed_gds_links",
            str(ordinal),
            ordinal,
            "no_data",
            payload={"target_uids": []},
        )

    class ResolvedMetadataCollector:
        def filter_accessions(self, accessions, metadata_repositories=None):
            return list(accessions)

        def available_accession_metadata(
            self,
            jsons,
            metadata_repositories=None,
            checkpoint_store=None,
        ):
            return [
                {
                    **record,
                    "metadata_repository": "geo",
                    "metadata_status": "available",
                    "accession_metadata": {
                        "series": {
                            "accession": [{"value": record["datalink_id"]}]
                        }
                    },
                }
                for record in jsons
            ]

    class RelevantReviewer:
        def review_relevancy(self, **kwargs):
            return {
                "evidences": json.dumps(
                    {
                        "evidences": [
                            {
                                "evidence": "Fibrotic human tissue",
                                "judgement": "relevant",
                                "confidence": "direct",
                                "reason": "Direct theme evidence.",
                            }
                        ]
                    }
                ),
                "judgement": json.dumps(
                    {
                        "judgement": "relevant",
                        "reasoning": "Direct fibrosis evidence is present.",
                        "confidence": "theme directly mentioned",
                    }
                ),
            }

    def reviewer_factory():
        return PublicationTextReviewer(
            reviewer_factory=RelevantReviewer,
            resume_orchestrator_factory=lambda publication_text_reviewer: (
                TracePublicationReviewResumer(
                    publication_text_reviewer=publication_text_reviewer,
                    collector_factory=ResolvedMetadataCollector,
                    filterer_factory=AtlasFilterer,
                )
            ),
        )

    result = TraceStageWorker(
        collector_factory=ResolvedMetadataCollector,
        publication_text_reviewer_factory=reviewer_factory,
    ).resume(trace.directory, stage="review", item_limit=1)

    assert result["selected_count"] == 1
    assert result["completed_count"] == 1
    assert result["deferred_count"] == 0
    assert store.get("thematic_review", "direct:1")["status"] == "available"
    assert store.get("thematic_review", "direct:2") is None
    progress = json.loads(
        (trace.directory / "incremental_review_progress.json").read_text()
    )
    assert progress == result

    second = TraceStageWorker(
        collector_factory=ResolvedMetadataCollector,
        publication_text_reviewer_factory=reviewer_factory,
    ).resume(trace.directory, stage="review", item_limit=1)

    assert second["selected_count"] == 1
    assert second["completed_count"] == 1
    assert second["claimed"] == 1
    assert second["reused"] == 1
    assert second["remaining_actionable"] == 0
    assert store.get("thematic_review", "direct:2")["status"] == "available"


class PausingCollector:
    def collect_jsons(self, *, stop_after=None, checkpoint_store=None, **kwargs):
        if stop_after == "metadata":
            raise AtlasStagePause(
                "metadata",
                {"accessions": [{"datalink_id": "GSE1"}], "publication_texts": {}},
            )
        return [{"datalink_id": "GSE1", "publications": []}]


class PassFilterer:
    def filter_jsons(self, jsons=None, **kwargs):
        return {"accessions": list(jsons or []), "publication_texts": {}}

    @staticmethod
    def accessions_with_publication_text_refs(accessions, publication_texts):
        return accessions


class PassHarmonizer:
    def harmonize_datasets(self, datasets=None, **kwargs):
        return datasets, []


def test_resume_accepts_a_new_stop_target_and_records_pause_summary(tmp_path):
    atlas = Atlas(
        metadata={"atlas_id": "fibrosis"},
        collector=PausingCollector(),
        filterer=PassFilterer(),
        harmonizer=PassHarmonizer(),
    )
    trace = DevTraceWriter(
        root=tmp_path,
        run_id="run-1",
        manifest={
            "command": "create-atlas",
            "query": ["fibrosis"],
            "query_file": None,
            "theme": "fibrosis",
            "review_filter": "none",
            "review_strategy": "direct",
            "metadata_repositories": ["geo"],
            "collect_metadata": True,
            "generate_queries": False,
            "review_before_metadata": False,
            "scrape_fulltext_accessions": True,
            "thematic_review": False,
        },
    )
    trace.checkpoint_store.put(
        "geo_metadata",
        "GSE1",
        1,
        "available",
        payload={"metadata_status": "available"},
    )

    result = atlas.resume(
        dev_out_dir=str(tmp_path),
        run_id=trace.directory.name,
        stop_after="metadata",
    )

    summary = json.loads(
        (trace.directory / "pause_metadata_summary.json").read_text()
    )
    assert summary["stage"] == "metadata"
    assert summary["accession_count"] == 1
    assert summary["frontier_counts"]["terminal"] == 1
    assert summary["invocation_identity"]["event_sequence"] > 0
    assert summary["hashes"]["run_config_sha256"]
    assert result["run"]["status"] == "running"
    assert not (trace.directory / "06_final_atlas.json").exists()


def test_resume_stop_target_already_passed_is_a_noop_without_rollback(tmp_path):
    atlas = Atlas(metadata={"atlas_id": "fibrosis"})
    trace = DevTraceWriter(
        root=tmp_path,
        run_id="run-1",
        manifest={"command": "create-atlas", "theme": "fibrosis"},
    )
    trace.checkpoint_store.set_meta(
        "main_pipeline_stage",
        {"stage": "metadata", "state": "paused", "contract_version": "1.0"},
    )
    trace.write(
        "collection_snapshot.json",
        {
            "schema_version": "1.0",
            "atlas": {"atlas_id": "fibrosis", "theme": "fibrosis", "accessions": []},
            "run": {
                "run_id": "run-1",
                "created_at": "run-1",
                "status": "running",
                "config": {"queries": [], "metadata_repositories": [], "options": {}},
            },
            "publication_texts": {},
        },
    )

    result = atlas.resume(
        dev_out_dir=str(tmp_path),
        run_id="run-1",
        stop_after="datalinks",
    )

    summary = json.loads(
        (trace.directory / "pause_datalinks_summary.json").read_text()
    )
    assert summary["already_complete"] is True
    assert summary["current_stage"] == "metadata"
    assert result["run"]["run_id"] == "run-1"
    assert trace.checkpoint_store.get_meta("main_pipeline_stage")["stage"] == "metadata"


def test_resume_earlier_target_reuses_a_final_snapshot_as_noop(tmp_path):
    atlas = Atlas(metadata={"atlas_id": "fibrosis"})
    trace = DevTraceWriter(
        root=tmp_path,
        run_id="run-1",
        manifest={"command": "create-atlas", "theme": "fibrosis"},
    )
    trace.checkpoint_store.set_meta(
        "main_pipeline_stage",
        {"stage": "harmonization", "state": "complete", "contract_version": "1.0"},
    )
    final = {
        "schema_version": "1.0",
        "atlas": {"atlas_id": "fibrosis", "theme": "fibrosis", "accessions": []},
        "run": {
            "run_id": "run-1",
            "created_at": "run-1",
            "status": "complete",
            "config": {"queries": [], "metadata_repositories": [], "options": {}},
        },
        "publication_texts": {},
    }
    trace.write("06_final_atlas.json", final)

    result = atlas.resume(
        dev_out_dir=str(tmp_path),
        run_id="run-1",
        stop_after="datalinks",
    )

    assert result == final
    assert trace.checkpoint_store.get_meta("main_pipeline_stage")["stage"] == (
        "harmonization"
    )
