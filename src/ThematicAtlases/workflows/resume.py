"""ResumeAtlasWorkflow: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

from agentic_curator.review_decisions import ReviewDecisionFile
from ThematicAtlases.pipeline import AtlasStagePause, validate_stop_after
from ThematicAtlases.domain import AtlasDocument
from ThematicAtlases.trace import DevTraceWriter
import logging
logger = logging.getLogger("ThematicAtlases.atlas")


class ResumeAtlasWorkflow:
    def __init__(self, context: Atlas):
        self.context = context

    def run(
        self,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        out: str | None = None,
        stop_before_review: bool = False,
        retry_stages=None,
        retry_items=None,
        retry_degraded_stages=None,
        review_decisions: dict | None = None,
        stop_after: str | None = None,
    ) -> dict:
        context = self.context
        """Resume an incomplete development trace from its latest valid stage."""
        stop_after = validate_stop_after(stop_after)
        run_dir = context._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
        if review_decisions is not None:
            typed_review_decisions = ReviewDecisionFile.from_mapping(
                review_decisions
            )
            if typed_review_decisions.run_id != run_dir.name:
                raise ValueError(
                    "review decision file belongs to run "
                    f"{typed_review_decisions.run_id!r}, not {run_dir.name!r}"
                )
            review_decisions = typed_review_decisions.to_mapping()
        manifest = context._read_checkpoint(run_dir / "00_run_manifest.json")
        if stop_after in {"publication-text", "fulltext-accessions"} and not (
            manifest.get("scrape_fulltext_accessions", False)
        ):
            raise ValueError(
                f"stop_after={stop_after!r} requires a trace with "
                "scrape_fulltext_accessions=True"
            )
        thematic_review = manifest.get(
            "thematic_review", manifest.get("theme") is not None
        )
        trace = DevTraceWriter.existing(run_dir)
        run_store = trace.run_store
        already_paused = context._already_completed_pause(trace, stop_after)
        if already_paused is not None:
            return already_paused
        run_store.set_run_status(run_dir.name, "running")
        checkpoint_store = trace.checkpoint_store
        checkpoint_store.request_retries(
            stages=retry_stages or (),
            items=retry_items,
            degraded_stages=retry_degraded_stages or (),
        )
        run_store.record_event(
            run_dir.name,
            "resume_started",
            detail={
                "retry_stages": list(retry_stages or ()),
                "retry_items": retry_items or {},
                "retry_degraded_stages": list(retry_degraded_stages or ()),
                "review_decisions_run_id": (
                    review_decisions.get("run_id")
                    if isinstance(review_decisions, dict)
                    else None
                ),
                "stop_after": stop_after,
            },
        )
        output_path = out if out is not None else manifest.get("atlas_out")
        if stop_before_review:
            logger.info(
                "Atlas resume progress stage=collection-only run_id=%s",
                run_dir.name,
            )
            result = context._collect_for_internal(dict(
                query=manifest.get("query"),
                file=manifest.get("query_file"),
                out=None,
                theme=manifest.get("theme"),
                review_filter=manifest.get("review_filter", "none"),
                review_strategy=manifest.get("review_strategy", "direct"),
                prune_accessions=manifest.get("prune_accessions", False),
                metadata_repositories=manifest.get("metadata_repositories"),
                max_publications=manifest.get("max_publications"),
                max_publications_per_query=manifest.get(
                    "max_publications_per_query"
                ),
                collect_metadata=manifest.get("collect_metadata", True),
                generate_queries=manifest.get("generate_queries", False),
                max_generated_queries=manifest.get("max_generated_queries", 3),
                review_before_metadata=manifest.get("review_before_metadata", False),
                scrape_fulltext_accessions=manifest.get(
                    "scrape_fulltext_accessions",
                    False,
                ),
                stop_before_review=True,
                _trace_writer=trace,
                _thematic_review=thematic_review,
            ))
            published = context._write_resumed_outputs(
                result=result,
                out=output_path,
                trace=trace,
                artifact_role="collection_snapshot",
            )
            trace.write(
                "resume_publication_collection.summary.json",
                context._documents.summary(
                    AtlasDocument.from_mapping(published), output_path
                ),
            )
            logger.info(
                "Atlas resume stats run_id=%s workflow=collection-only "
                "accessions=%s publication_texts=%s",
                run_dir.name,
                len(result.get("accessions", [])),
                len(result.get("publication_texts", {})),
            )
            return published
        context._reconcile_checkpoint_contracts(checkpoint_store)
        if context._cache_ontologies:
            context._preflight_credentials()
        context._prepare_ontology_cache()
        if manifest.get("generate_queries", False) or thematic_review:
            context._preflight_credentials()
        logger.info("Atlas resume selected run_id=%s run_dir=%s", run_dir.name, run_dir)

        discovery_retryable = checkpoint_store.has_actionable_boundary("discovery")
        review_retryable = checkpoint_store.has_actionable_boundary("review")
        metadata_retryable = checkpoint_store.has_actionable_boundary("metadata")
        collection_retryable = any(
            (discovery_retryable, review_retryable, metadata_retryable)
        )
        harmonization_retryable = checkpoint_store.has_actionable_boundary(
            "harmonization"
        )
        review_before_metadata = manifest.get("review_before_metadata", False)
        final_path = run_dir / "06_final_atlas.json"
        if (
            final_path.exists()
            and not collection_retryable
            and not harmonization_retryable
            and review_decisions is None
        ):
            result = context._read_checkpoint(final_path)
            logger.info("Atlas resume progress stage=final-atlas-complete")
            return context._write_resumed_outputs(
                result=result, out=output_path, trace=trace
            )

        harmonized_path = run_dir / "resume_harmonized_datasets.json"
        if (
            harmonized_path.exists()
            and not collection_retryable
            and not harmonization_retryable
            and review_decisions is None
        ):
            result = context._read_checkpoint(harmonized_path)
            logger.info("Atlas resume progress stage=harmonization-complete")
        else:
            if harmonization_retryable:
                logger.info(
                    "Atlas resume progress stage=harmonization-retry-required"
                )
            reviewed_path = run_dir / "02_reviewed_datasets.json"
            metadata_enriched_path = run_dir / "resume_metadata_enriched_datasets.json"
            if (
                review_before_metadata
                and manifest.get("collect_metadata", True)
                and metadata_enriched_path.exists()
                and not metadata_retryable
                and not discovery_retryable
                and not review_retryable
            ):
                datasets = context._read_checkpoint(metadata_enriched_path)
                logger.info("Atlas resume progress stage=metadata-enrichment-complete")
            elif reviewed_path.exists() and not (
                discovery_retryable
                or review_retryable
                or (metadata_retryable and not review_before_metadata)
            ):
                datasets = context._read_checkpoint(reviewed_path)
                logger.info("Atlas resume progress stage=review-complete")
                if review_before_metadata and manifest.get("collect_metadata", True):
                    datasets = context._metadata_for_reviewed_datasets(
                        datasets=datasets,
                        metadata_repositories=manifest.get("metadata_repositories"),
                        checkpoint_store=checkpoint_store,
                    )
                    trace.write("resume_metadata_enriched_datasets.json", datasets)
            else:
                collected_path = run_dir / "01_collected_accessions.json"
                can_reuse_collected = not discovery_retryable and not review_retryable
                if not review_before_metadata:
                    can_reuse_collected = can_reuse_collected and not metadata_retryable
                if collected_path.exists() and can_reuse_collected:
                    accessions = context._read_checkpoint(collected_path)
                    logger.info("Atlas resume progress stage=collection-complete")
                    progress_path = run_dir / "resume_review_progress.json"
                    review_accessions = accessions
                    if progress_path.exists() and review_before_metadata:
                        if hasattr(context._collector, "available_accession_metadata"):
                            review_accessions = context._collector.available_accession_metadata(
                                jsons=accessions,
                                metadata_repositories=manifest.get("metadata_repositories"),
                                checkpoint_store=checkpoint_store,
                            )
                    if progress_path.exists():
                        progress = context._read_checkpoint(progress_path)
                        review_input = {
                            **progress,
                            "accessions": review_accessions,
                        }
                    else:
                        review_input = review_accessions
                    datasets = context._filter_jsons(
                        jsons=review_input,
                        theme=(manifest.get("theme") if thematic_review else None),
                        review_filter=(
                            manifest.get("review_filter", "none")
                            if thematic_review
                            else "none"
                        ),
                        review_strategy=manifest.get("review_strategy", "direct"),
                        prune_accessions=manifest.get("prune_accessions", False),
                        _review_progress_callback=lambda texts: trace.write(
                            "resume_review_progress.json",
                            {
                                "accessions": context._filterer.accessions_with_publication_text_refs(
                                    review_accessions,
                                    texts,
                                ),
                                "publication_texts": texts,
                            },
                        ),
                        _checkpoint_store=checkpoint_store,
                    )
                    trace.write("02_reviewed_datasets.json", datasets)
                else:
                    logger.info("Atlas resume progress stage=collection-required")
                    try:
                        datasets = context._collect_for_internal(dict(
                        query=manifest.get("query"),
                        file=manifest.get("query_file"),
                        theme=manifest.get("theme"),
                        review_filter=manifest.get("review_filter", "none"),
                        review_strategy=manifest.get("review_strategy", "direct"),
                        prune_accessions=manifest.get("prune_accessions", False),
                        metadata_repositories=manifest.get("metadata_repositories"),
                        max_publications=manifest.get("max_publications"),
                        max_publications_per_query=manifest.get(
                            "max_publications_per_query"
                        ),
                        collect_metadata=manifest.get("collect_metadata", True),
                        generate_queries=manifest.get("generate_queries", False),
                        max_generated_queries=manifest.get("max_generated_queries", 3),
                        review_before_metadata=review_before_metadata,
                        scrape_fulltext_accessions=manifest.get(
                            "scrape_fulltext_accessions",
                            False,
                        ),
                        _trace_writer=trace,
                        _thematic_review=thematic_review,
                        **({"stop_after": stop_after} if stop_after is not None else {}),
                    ))
                    except AtlasStagePause as pause:
                        return context._pause_at_stage(
                            trace=trace,
                            stage=pause.stage,
                            result=pause.result,
                        )

            if stop_after in {"metadata", "review"}:
                return context._pause_at_stage(
                    trace=trace,
                    stage=stop_after,
                    result=datasets,
                )

            if manifest.get("command") == "collect-datasets":
                published = context._write_resumed_outputs(
                    result=datasets,
                    out=output_path,
                    trace=trace,
                    artifact_role="collection_snapshot",
                )
                logger.info(
                    "Atlas resume stats run_id=%s workflow=collect-datasets accessions=%s",
                    run_dir.name,
                    len(datasets.get("accessions", [])),
                )
                return published

            trace.write(
                "03_pre_harmonization_accession_metadata.json",
                trace.metadata(datasets.get("accessions", [])),
            )
            checkpoint_store.set_meta(
                "main_pipeline_stage",
                {"stage": "harmonization", "state": "running", "contract_version": "1.0"},
            )
            result, details = context._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=manifest.get("harmonization_details_out"),
                harmonization_options=manifest.get("harmonization_options"),
                **(
                    {"review_decisions": review_decisions}
                    if review_decisions is not None
                    else {}
                ),
                **context._checkpoint_keyword(
                    context._harmonizer.harmonize_datasets,
                    checkpoint_store,
                ),
            )
            trace.write("04_harmonization_details.json", details)
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
            trace.write("resume_harmonized_datasets.json", result)
            checkpoint_store.set_meta(
                "main_pipeline_stage",
                {"stage": "harmonization", "state": "complete", "contract_version": "1.0"},
            )

            if stop_after == "harmonization":
                return context._pause_at_stage(
                    trace=trace,
                    stage="harmonization",
                    result=result,
                )

        published = context._write_resumed_outputs(
            result=result, out=output_path, trace=trace
        )
        logger.info("Atlas resume stats run_id=%s accessions=%s", run_dir.name, len(result.get("accessions", [])))
        return published

