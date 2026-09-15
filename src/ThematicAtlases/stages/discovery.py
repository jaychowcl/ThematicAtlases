"""DiscoveryStage: a typed operation shared by caller-specific scheduling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .results import RecordsResult
if TYPE_CHECKING:
    from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.pipeline import AtlasStagePause, DISCOVERY_STOP_STAGES


@dataclass(frozen=True, kw_only=True)
class DiscoveryRequest:
    queries: list[str]
    max_publications: int | None = None
    max_publications_per_query: list[int | None] | None = None
    checkpoint_store: Any = None
    scrape_fulltext_accessions: bool = True
    stop_after: str | None = None


class DiscoveryStage:
    def __init__(self, owner: EuropePMCWrapper):
        self.owner = owner

    def run(self, request: DiscoveryRequest) -> RecordsResult:
        return RecordsResult(self._execute(
            queries=request.queries,
            max_publications=request.max_publications,
            max_publications_per_query=request.max_publications_per_query,
            checkpoint_store=request.checkpoint_store,
            scrape_fulltext_accessions=request.scrape_fulltext_accessions,
            stop_after=request.stop_after,
        ))

    def _execute(
        self,
        queries: list[str],
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        checkpoint_store=None,
        scrape_fulltext_accessions: bool = True,
        stop_after: str | None = None,
    ) -> list[dict]:
        stage_owner = self.owner
        if stop_after is not None and stop_after not in DISCOVERY_STOP_STAGES:
            raise ValueError(
                "EuropePMC stop_after must be a discovery stage: "
                + ", ".join(DISCOVERY_STOP_STAGES)
            )
        if stop_after in {"publication-text", "fulltext-accessions"} and not (
            scrape_fulltext_accessions
        ):
            raise ValueError(
                f"stop_after={stop_after!r} requires "
                "scrape_fulltext_accessions=True"
            )
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                "main_pipeline_phase",
                {"phase": "datalinks"},
            )
            stage_owner._set_pipeline_stage(checkpoint_store, "query-results", "running")
        publication_options = {
            "queries": queries,
            "max_publications": max_publications,
        }
        if max_publications_per_query is not None:
            publication_options["max_publications_per_query"] = (
                max_publications_per_query
            )
        datalink_options = {}
        if checkpoint_store is not None:
            publication_options["checkpoint_store"] = checkpoint_store
            datalink_options["checkpoint_store"] = checkpoint_store
        publications = stage_owner.collect_publications(**publication_options)
        stage_owner._set_pipeline_stage(checkpoint_store, "query-results", "complete")
        if stop_after == "query-results":
            raise AtlasStagePause(
                "query-results",
                {"accessions": [], "publication_texts": {}, "publications": publications},
            )
        stage_owner._set_pipeline_stage(checkpoint_store, "datalinks", "running")
        accessions = stage_owner.collect_datalinks(
            publications=publications,
            **datalink_options,
        )
        stage_owner._set_pipeline_stage(checkpoint_store, "datalinks", "complete")
        if stop_after == "datalinks":
            raise AtlasStagePause(
                "datalinks",
                {"accessions": accessions, "publication_texts": {}},
            )
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                "main_pipeline_phase",
                {"phase": "downstream"},
            )
        enriched_publications = publications
        scraped = []
        if scrape_fulltext_accessions:
            stage_owner._set_pipeline_stage(checkpoint_store, "publication-text", "running")
            text_options = {"publications": publications}
            if checkpoint_store is not None:
                text_options["checkpoint_store"] = checkpoint_store
            enriched_publications = stage_owner.collect_publication_texts(**text_options)
            stage_owner._set_pipeline_stage(checkpoint_store, "publication-text", "complete")
            if stop_after == "publication-text":
                raise AtlasStagePause(
                    "publication-text",
                    {"accessions": accessions, "publication_texts": {}},
                )
            accessions = stage_owner._accessions_with_enriched_publications(
                accessions,
                enriched_publications,
            )
            stage_owner._set_pipeline_stage(
                checkpoint_store, "fulltext-accessions", "running"
            )
            scraped = stage_owner.accessions_from_fulltexts(
                enriched_publications,
                checkpoint_store=checkpoint_store,
            )
            stage_owner._set_pipeline_stage(
                checkpoint_store, "fulltext-accessions", "complete"
            )
            if stop_after == "fulltext-accessions":
                raise AtlasStagePause(
                    "fulltext-accessions",
                    {
                        "accessions": stage_owner.merge_accessions(accessions, scraped),
                        "publication_texts": {},
                    },
                )
        stage_owner._set_pipeline_stage(checkpoint_store, "accession-graph", "running")
        graph = stage_owner.accessions_from_link_graph(
            enriched_publications,
            checkpoint_store=checkpoint_store,
        )
        stage_owner._set_pipeline_stage(checkpoint_store, "accession-graph", "complete")
        merged = stage_owner.merge_accessions(accessions, scraped, graph)
        if stop_after == "accession-graph":
            raise AtlasStagePause(
                "accession-graph",
                {"accessions": merged, "publication_texts": {}},
            )
        return merged

