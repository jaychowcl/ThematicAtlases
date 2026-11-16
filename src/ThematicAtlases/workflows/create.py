"""CreateAtlasWorkflow: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

from dataclasses import asdict
from ThematicAtlases.pipeline import AtlasStagePause, validate_stop_after
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.unsupported_accessions import build_unsupported_accessions_report
from ThematicAtlases.wrappers.pubmed_gds import PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
import logging
logger = logging.getLogger("ThematicAtlases.atlas")


class CreateAtlasWorkflow:
    def __init__(self, context: Atlas):
        self.context = context

    def run(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        review_strategy: str = "direct",
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        reviewer=None,
        collect_metadata: bool = True,
        dev_trace: bool = False,
        dev_out_dir: str = ".dev",
        harmonization_details_out: str | None = None,
        generate_queries: bool = True,
        max_generated_queries: int = 3,
        harmonization_options: dict | None = None,
        review_before_metadata: bool = False,
        scrape_fulltext_accessions: bool = True,
        unsupported_accessions_out: str | None = None,
        thematic_review: bool = True,
        prune_accessions: bool = False,
        stop_after: str | None = None,
        max_review_criteria: int = 12,
    ) -> dict:
        context = self.context
        from ThematicAtlases.filterer.review import validate_max_review_criteria
        validate_max_review_criteria(max_review_criteria)
        if theme is None or not theme.strip():
            raise ValueError("create_atlas requires a non-empty theme")
        if not generate_queries and not context._has_input_queries(query, file):
            raise ValueError(
                "create_atlas requires at least one query when query generation "
                "is disabled"
            )
        if not thematic_review and review_filter != "none":
            raise ValueError(
                "review_filter must be 'none' when thematic_review is disabled"
            )
        if not thematic_review and review_before_metadata:
            raise ValueError(
                "review_before_metadata requires thematic_review to be enabled"
            )
        stop_after = validate_stop_after(stop_after)
        if stop_after in {"metadata", "review", "harmonization"} and not collect_metadata:
            raise ValueError(
                f"stop_after={stop_after!r} requires collect_metadata=True"
            )
        if stop_after == "metadata" and review_before_metadata:
            raise ValueError(
                "stop_after='metadata' requires review_before_metadata=False"
            )
        if stop_after in {"publication-text", "fulltext-accessions"} and not (
            scrape_fulltext_accessions
        ):
            raise ValueError(
                f"stop_after={stop_after!r} requires "
                "scrape_fulltext_accessions=True"
            )
        if stop_after is not None and not dev_trace:
            raise ValueError("stop_after requires dev_trace=True")
        if context._cache_ontologies:
            context._preflight_credentials()
        context._prepare_ontology_cache()
        run_id = context._dev_run_id()
        trace = None
        if dev_trace:
            trace = DevTraceWriter(
                root=dev_out_dir,
                run_id=run_id,
                manifest={
                    "debug_snapshots": context._debug_snapshots,
                    "command": "create-atlas",
                    "created_at": run_id,
                    "atlas_id": str(
                        context.metadata.get("atlas_id") or f"atlas-{run_id}"
                    ),
                    "atlas_out": out,
                    "artifacts": [
                        "00_run_manifest.json",
                        "atlas_run.sqlite3",
                        "01_collected_accessions.json",
                        "02_reviewed_datasets.json",
                        "03_pre_harmonization_accession_metadata.json",
                        "04_harmonization_details.json",
                        "05_post_harmonization_accession_metadata.json",
                        "06_final_atlas.json",
                        "07_summary.json",
                        "unsupported_accessions.json",
                    ],
                    "query": query,
                    "query_file": file,
                    "theme": theme,
                    "review_filter": review_filter,
                    "review_strategy": review_strategy,
                    "max_review_criteria": max_review_criteria,
                    "prune_accessions": prune_accessions,
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "max_publications_per_query": max_publications_per_query,
                    "collect_metadata": collect_metadata,
                    "generate_queries": generate_queries,
                    "max_generated_queries": max_generated_queries,
                    "harmonization_options": harmonization_options,
                    "harmonization_details_out": harmonization_details_out,
                    "review_before_metadata": review_before_metadata,
                    "scrape_fulltext_accessions": scrape_fulltext_accessions,
                    "pubmed_gds_discovery_contract": (
                        PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
                    ),
                    "unsupported_accessions_out": unsupported_accessions_out,
                    "thematic_review": thematic_review,
                    "stop_after": stop_after,
                    "resource_profile": asdict(context._resource_profile),
                    "runtime_provenance": context._runtime_provenance,
                },
            )
            trace.run_store.set_run_status(run_id, "running")
            trace.run_store.set_stage_state(run_id, "collection", "running")
        logger.info("Atlas create_atlas progress stage=collect-datasets")
        collection_resolution: dict[str, list[str]] = {}
        collect_kwargs = dict(
            query=query,
            file=file,
            out=None,
            theme=theme,
            review_filter=review_filter,
            review_strategy=review_strategy,
            max_review_criteria=max_review_criteria,
            prune_accessions=prune_accessions,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            reviewer=reviewer,
            collect_metadata=collect_metadata,
            generate_queries=generate_queries,
            max_generated_queries=max_generated_queries,
            review_before_metadata=review_before_metadata,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
            _resolution=collection_resolution,
            _thematic_review=thematic_review,
        )
        if stop_after == "metadata":
            collect_kwargs["stop_before_review"] = True
        if stop_after is not None:
            collect_kwargs["stop_after"] = stop_after
        if max_publications_per_query is not None:
            collect_kwargs["max_publications_per_query"] = (
                max_publications_per_query
            )
        if trace is not None:
            collect_kwargs["_trace_writer"] = trace
        try:
            datasets = context._collect_for_internal(collect_kwargs)
        except AtlasStagePause as pause:
            return context._pause_at_stage(
                trace=trace,
                stage=pause.stage,
                result=pause.result,
            )
        if trace is not None:
            trace.run_store.set_stage_state(run_id, "collection", "complete")
        if stop_after in {"metadata", "review"}:
            return context._pause_at_stage(
                trace=trace,
                stage=stop_after,
                result=datasets,
            )
        if trace is not None:
            trace.run_store.set_stage_state(run_id, "harmonization", "running")
        logger.info(
            "Atlas create_atlas progress stage=collect-datasets-complete accessions=%s publication_texts=%s",
            len(datasets.get("accessions", [])),
            len(datasets.get("publication_texts", {})),
        )
        logger.info("Atlas create_atlas progress stage=harmonize-datasets")
        if trace is not None:
            trace.checkpoint_store.set_meta(
                "pipeline_position",
                {"stage": "harmonization", "state": "running", "contract_version": "1.0"},
            )
            trace.write(
                "03_pre_harmonization_accession_metadata.json",
                trace.metadata(datasets.get("accessions", [])),
            )
            result, details = context._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
                **context._checkpoint_keyword(
                    context._harmonizer.harmonize_datasets,
                    trace.checkpoint_store,
                ),
            )
            trace.write("04_harmonization_details.json", details)
            trace.register_artifact(
                "harmonization_details", "04_harmonization_details.json"
            )
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
            trace.checkpoint_store.set_meta(
                "pipeline_position",
                {"stage": "harmonization", "state": "complete", "contract_version": "1.0"},
            )
        else:
            result, details = context._harmonize_for_internal(
                datasets=datasets,
                harmonization_details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
            )
        if stop_after == "harmonization":
            return context._pause_at_stage(
                trace=trace,
                stage="harmonization",
                result=result,
            )
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas create_atlas progress stage=harmonize-datasets-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        document = context._documents.assemble(
            result,
            atlas_metadata=context.metadata,
            run_id=run_id,
            created_at=run_id,
            theme=theme or "",
            config={
                "queries": collection_resolution.get("queries", list(query or ())),
                "metadata_repositories": list(metadata_repositories or ()),
                "query_file": file,
                "review_filter": review_filter,
                "review_strategy": review_strategy,
                    "max_review_criteria": max_review_criteria,
                "prune_accessions": prune_accessions,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
                "thematic_review": thematic_review,
                "harmonization_options": dict(harmonization_options or {}),
                "resource_profile": asdict(context._resource_profile),
                "runtime_provenance": context._runtime_provenance,
            },
            run_status=context._final_run_status(
                result,
                trace.checkpoint_store if trace is not None else None,
            ),
            harmonization_details=details,
        )
        result_mapping = document.to_mapping()
        unsupported_report = build_unsupported_accessions_report(
            list(result.get("unsupported_accessions", [])),
            atlas_id=document.atlas.atlas_id,
            run_id=document.run.run_id,
        )
        summary = context._documents.summary(
            document,
            atlas_path=out,
            unsupported_accessions_report=unsupported_report,
            unsupported_accessions_path=unsupported_accessions_out,
        )

        if out is not None:
            logger.info("Atlas create_atlas progress stage=write-output output_path=%s", out)
            context._documents.publish(
                document,
                out,
                include_summary=True,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_accessions_out,
            )
        elif unsupported_accessions_out is not None:
            context._documents.publish_unsupported_accessions(
                unsupported_report,
                unsupported_accessions_out,
            )

        if trace is not None:
            trace.write("06_final_atlas.json", result_mapping)
            trace.write("07_summary.json", summary)
            trace.write("08_retry_report.json", trace.checkpoint_store.retry_report())
            trace.write("unsupported_accessions.json", unsupported_report)
            trace.register_artifact("final_atlas", "06_final_atlas.json")
            trace.register_artifact("summary", "07_summary.json")
            trace.register_artifact("retry_report", "08_retry_report.json")
            trace.register_artifact(
                "unsupported_accessions", "unsupported_accessions.json"
            )
            trace.run_store.set_stage_state(
                run_id,
                "harmonization",
                "partial" if trace.checkpoint_store.has_incomplete() else "complete",
            )
            trace.run_store.set_run_status(run_id, document.run.status.value)
            trace.checkpoint_store.set_meta("pipeline_position", {"stage":"harmonization", "state":"complete", "published":True})
            trace.run_store.record_event(
                run_id,
                "run_published",
                detail={"artifact_role": "final_atlas"},
            )

        logger.info(
            "Atlas create_atlas stats final_accessions=%s publication_texts=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            out,
        )
        return result_mapping

