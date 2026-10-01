"""CollectDatasetsWorkflow: application orchestration behind the Atlas facade.

The injected context preserves existing subclass hooks; workflow instances are
operation-local and do not own shared clients or persistent state.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ThematicAtlases.atlas import Atlas

import json
import hashlib
from dataclasses import asdict
from pathlib import Path
from ThematicAtlases.checkpoint import failure_category, is_retryable_error
from ThematicAtlases.pipeline import AtlasStagePause
from ThematicAtlases.domain import RunStatus
from ThematicAtlases.runtime_contracts import safe_error_json
from ThematicAtlases.summary import build_atlas_summary
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.unsupported_accessions import build_unsupported_accessions_report, partition_unsupported_accessions
from ThematicAtlases.wrappers.pubmed_gds import PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
import logging
logger = logging.getLogger("ThematicAtlases.atlas")


class CollectDatasetsWorkflow:
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
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        dev_trace: bool = False,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        review_before_metadata: bool = False,
        stop_before_review: bool = False,
        scrape_fulltext_accessions: bool = True,
        unsupported_accessions_out: str | None = None,
        prune_accessions: bool = False,
        _trace_writer: DevTraceWriter | None = None,
    ) -> dict:
        context = self.context
        """Collect datasets and expose the result as an Atlas v1 document."""
        effective_run_id = run_id or (
            _trace_writer.directory.name
            if _trace_writer is not None
            else context._dev_run_id()
        )
        collection_resolution: dict[str, list[str]] = {}
        legacy = context._collect_datasets_legacy(
            query=query,
            file=file,
            out=None,
            theme=theme,
            review_filter=review_filter,
            review_strategy=review_strategy,
            prune_accessions=prune_accessions,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            max_publications_per_query=max_publications_per_query,
            reviewer=reviewer,
            collect_metadata=collect_metadata,
            generate_queries=generate_queries,
            max_generated_queries=max_generated_queries,
            dev_trace=dev_trace,
            dev_out_dir=dev_out_dir,
            run_id=effective_run_id,
            review_before_metadata=review_before_metadata,
            stop_before_review=stop_before_review,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
            unsupported_accessions_out=unsupported_accessions_out,
            _trace_writer=_trace_writer,
            _finalize_trace=False,
            _resolution=collection_resolution,
        )
        document = context._documents.assemble(
            legacy,
            atlas_metadata=context.metadata,
            run_id=effective_run_id,
            created_at=effective_run_id,
            theme=theme or "",
            config={
                "queries": collection_resolution.get("queries", list(query or ())),
                "metadata_repositories": list(metadata_repositories or ()),
                "query_file": file,
                "review_filter": review_filter,
                "review_strategy": review_strategy,
                "prune_accessions": prune_accessions,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "stop_before_review": stop_before_review,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
                "resource_profile": asdict(context._resource_profile),
                "runtime_provenance": context._runtime_provenance,
            },
            run_status=RunStatus.RUNNING,
        )
        result = document.to_mapping()
        unsupported_report = build_unsupported_accessions_report(
            list(legacy.get("unsupported_accessions", [])),
            atlas_id=document.atlas.atlas_id,
            run_id=document.run.run_id,
        )
        if out is not None:
            context._documents.publish(
                document,
                out,
                include_summary=False,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_accessions_out,
            )
        elif unsupported_accessions_out is not None:
            context._documents.publish_unsupported_accessions(
                unsupported_report,
                unsupported_accessions_out,
            )
        if dev_trace and _trace_writer is None:
            trace = DevTraceWriter.existing(Path(dev_out_dir) / effective_run_id)
            trace.write("collection_snapshot.json", result)
            trace.write(
                "collection_snapshot.summary.json",
                context._documents.summary(
                    document,
                    out,
                    unsupported_accessions_report=unsupported_report,
                    unsupported_accessions_path=unsupported_accessions_out,
                ),
            )
            trace.write("unsupported_accessions.json", unsupported_report)
            trace.register_artifact(
                "collection_snapshot", "collection_snapshot.json"
            )
            trace.register_artifact(
                "summary", "collection_snapshot.summary.json"
            )
            trace.register_artifact(
                "unsupported_accessions", "unsupported_accessions.json"
            )
            trace.run_store.set_stage_state(
                effective_run_id, "collection", "complete"
            )
            trace.run_store.set_run_status(effective_run_id, "running")
            trace.run_store.record_event(
                effective_run_id,
                "snapshot_published",
                detail={"artifact_role": "collection_snapshot"},
            )
        return result

    def run_stage(
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
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        dev_trace: bool = False,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        review_before_metadata: bool = False,
        stop_before_review: bool = False,
        scrape_fulltext_accessions: bool = True,
        unsupported_accessions_out: str | None = None,
        prune_accessions: bool = False,
        _trace_writer: DevTraceWriter | None = None,
        _finalize_trace: bool = True,
        _resolution: dict[str, list[str]] | None = None,
        _thematic_review: bool = True,
        stop_after: str | None = None,
    ) -> dict:
        context = self.context
        if review_before_metadata and theme is None:
            raise ValueError("review_before_metadata requires a theme")
        owned_trace = dev_trace and _trace_writer is None
        if owned_trace:
            effective_run_id = run_id or context._dev_run_id()
            _trace_writer = DevTraceWriter(
                root=dev_out_dir,
                run_id=effective_run_id,
                manifest={
                    "debug_snapshots": context._debug_snapshots,
                    "command": "collect-datasets",
                    "created_at": effective_run_id,
                    "atlas_id": str(
                        context.metadata.get("atlas_id")
                        or f"atlas-{effective_run_id}"
                    ),
                    "atlas_out": out,
                    "artifacts": [
                        "00_run_manifest.json",
                        "atlas_run.sqlite3",
                        "01_collected_accessions.json",
                        "resume_publication_collection.json",
                        "resume_publication_collection.summary.json",
                        "resume_metadata_progress.json",
                        "02_reviewed_datasets.json",
                        "resume_metadata_enriched_datasets.json",
                        "06_final_atlas.json",
                        "07_summary.json",
                        "unsupported_accessions.json",
                    ],
                    "query": query,
                    "query_file": file,
                    "theme": theme,
                    "review_filter": review_filter,
                    "review_strategy": review_strategy,
                    "prune_accessions": prune_accessions,
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "max_publications_per_query": max_publications_per_query,
                    "collect_metadata": collect_metadata,
                    "generate_queries": generate_queries,
                    "max_generated_queries": max_generated_queries,
                    "review_before_metadata": review_before_metadata,
                    "stop_before_review": stop_before_review,
                    "scrape_fulltext_accessions": scrape_fulltext_accessions,
                    "pubmed_gds_discovery_contract": (
                        PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
                    ),
                    "unsupported_accessions_out": unsupported_accessions_out,
                    "resource_profile": asdict(context._resource_profile),
                    "runtime_provenance": context._runtime_provenance,
                },
            )
            _trace_writer.run_store.set_run_status(effective_run_id, "running")
            _trace_writer.run_store.set_stage_state(
                effective_run_id, "collection", "running"
            )
        checkpoint_store = (
            _trace_writer.checkpoint_store if _trace_writer is not None else None
        )
        trace_run_id = (
            _trace_writer.directory.name if _trace_writer is not None else None
        )
        if generate_queries or (
            _thematic_review and theme is not None and not stop_before_review
        ):
            context._preflight_credentials()
        if generate_queries:
            generation_input = {
                "query": list(query or []),
                "file_queries": context._load_queries(file=file)
                if file is not None
                else [],
                "theme": theme,
                "max_generated_queries": max_generated_queries,
                "contract_version": 1,
            }
            generation_key = hashlib.sha256(
                json.dumps(
                    generation_input,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            generation_checkpoint = (
                checkpoint_store.get("query_generation", generation_key)
                if checkpoint_store is not None
                else None
            )
            if (
                generation_checkpoint
                and generation_checkpoint["status"] == "available"
            ):
                query = (generation_checkpoint.get("payload") or {}).get(
                    "queries", []
                )
            elif (
                generation_checkpoint
                and generation_checkpoint["status"] == "terminal_error"
            ):
                raise RuntimeError(
                    generation_checkpoint.get("error")
                    or "query generation failed"
                )
            else:
                try:
                    query = context._queries_with_generated(
                        query=query,
                        file=file,
                        theme=theme,
                        max_generated_queries=max_generated_queries,
                    )
                except Exception as error:
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "query_generation",
                            generation_key,
                            0,
                            "retryable_error"
                            if is_retryable_error(error)
                            else "terminal_error",
                            error=safe_error_json(
                                error,
                                provider="agentic_curator",
                                stage="query_generation",
                                item_id=generation_key,
                                retryable=is_retryable_error(error),
                            ),
                            error_type=type(error).__name__,
                            failure_category=failure_category(error),
                        )
                    raise
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        "query_generation",
                        generation_key,
                        0,
                        "available",
                        payload={
                            "queries": query,
                            "input": generation_input,
                        },
                    )
            file = None
        elif checkpoint_store is not None:
            query = list(query or ()) + (context._load_queries(file=file) if file is not None else [])
            generation_input = {"query": query, "generate_queries": False}
            generation_key = hashlib.sha256(json.dumps(generation_input, sort_keys=True).encode()).hexdigest()
            if checkpoint_store.get("query_generation", generation_key) is None:
                checkpoint_store.put("query_generation", generation_key, 0, "available", payload={"queries": query, "input": generation_input})
            file = None
        if checkpoint_store is not None:
            checkpoint_store.set_meta("resolved_query_key", generation_key)
        if _resolution is not None:
            _resolution["queries"] = list(query or ())
        if checkpoint_store is not None:
            fingerprint_configuration = {
                "query": query,
                "query_file": file,
                "theme": theme,
                "review_filter": review_filter,
                "metadata_repositories": metadata_repositories,
                "max_publications": max_publications,
                "collect_metadata": collect_metadata,
                "pubmed_gds_discovery_contract": (
                    PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
                ),
            }
            if prune_accessions:
                fingerprint_configuration["prune_accessions"] = True
            if max_publications_per_query is not None:
                fingerprint_configuration["max_publications_per_query"] = (
                    max_publications_per_query
                )
            # Preserve compatibility with traces created before review strategies
            # existed while still separating explicitly selected legacy runs.
            if review_strategy != "direct":
                fingerprint_configuration["review_strategy"] = review_strategy
            if review_before_metadata:
                fingerprint_configuration["review_before_metadata"] = True
            if scrape_fulltext_accessions:
                fingerprint_configuration["scrape_fulltext_accessions"] = True
            if not _thematic_review:
                fingerprint_configuration["thematic_review"] = False
            checkpoint_store.validate_fingerprint(fingerprint_configuration)
        logger.info("Atlas collect_datasets progress stage=collect-accessions")
        accessions = context._collect_jsons(
            query=query,
            file=file,
            out=None,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            max_publications_per_query=max_publications_per_query,
            collect_metadata=collect_metadata and not review_before_metadata,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
            checkpoint_store=checkpoint_store,
            stop_after=stop_after,
        )
        accessions, unsupported_accessions = partition_unsupported_accessions(
            accessions
        )
        if _trace_writer is not None:
            _trace_writer.write("01_collected_accessions.json", accessions)
            unsupported_report = build_unsupported_accessions_report(
                unsupported_accessions,
                atlas_id=str(
                    context.metadata.get("atlas_id")
                    or f"atlas-{trace_run_id}"
                ),
                run_id=str(trace_run_id),
            )
            _trace_writer.write(
                "unsupported_accessions.json", unsupported_report
            )
            _trace_writer.register_artifact(
                "unsupported_accessions", "unsupported_accessions.json"
            )
        logger.info(
            "Atlas collect_datasets progress stage=collect-accessions-complete accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_datasets progress stage=map-publication-texts")
        review_progress_callback = None
        if _trace_writer is not None:
            review_progress_callback = lambda texts: _trace_writer.write(
                "resume_review_progress.json",
                {
                    "accessions": context._filterer.accessions_with_publication_text_refs(
                        accessions, texts
                    ),
                    "publication_texts": texts,
                },
            )
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                "pipeline_position",
                {"stage": "review", "state": "running", "contract_version": "1.0"},
            )
        result = context._filter_jsons(
            jsons=accessions,
            theme=(
                theme
                if _thematic_review and not stop_before_review
                else None
            ),
            review_filter=(
                review_filter
                if _thematic_review and not stop_before_review
                else "none"
            ),
            review_strategy=review_strategy,
            prune_accessions=prune_accessions,
            reviewer=reviewer,
            _review_progress_callback=review_progress_callback,
            _checkpoint_store=checkpoint_store,
        )
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                "pipeline_position",
                {"stage": "review", "state": "complete", "contract_version": "1.0"},
            )
        result = {
            **result,
            "unsupported_accessions": unsupported_accessions,
        }
        if stop_before_review:
            if _trace_writer is not None:
                _trace_writer.write("resume_publication_collection.json", result)
            final_accessions = result.get("accessions", [])
            publication_texts = result.get("publication_texts", {})
            if out is not None:
                logger.info(
                    "Atlas collect_datasets progress stage=write-collection-output "
                    "output_path=%s",
                    out,
                )
                context._write_json(result=result, out=out)
            if owned_trace and _trace_writer is not None and _finalize_trace:
                summary = build_atlas_summary(atlas=result, atlas_path=out)
                _trace_writer.write(
                    "resume_publication_collection.summary.json", summary
                )
            logger.info(
                "Atlas collect_datasets stats workflow=collection-only "
                "accessions=%s publication_texts=%s output_path=%s",
                len(final_accessions),
                len(publication_texts),
                out,
            )
            return result
        if _trace_writer is not None:
            _trace_writer.write("02_reviewed_datasets.json", result)
        if stop_after == "review":
            raise AtlasStagePause("review", result)
        if review_before_metadata and collect_metadata:
            logger.info("Atlas collect_datasets progress stage=collect-accession-metadata")
            result = context._metadata_for_reviewed_datasets(
                datasets=result,
                metadata_repositories=metadata_repositories,
                checkpoint_store=checkpoint_store,
            )
            if _trace_writer is not None:
                _trace_writer.write("resume_metadata_enriched_datasets.json", result)
            logger.info(
                "Atlas collect_datasets progress stage=collect-accession-metadata-complete accessions=%s",
                len(result.get("accessions", [])),
            )
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas collect_datasets progress stage=map-publication-texts-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        if out is not None:
            logger.info("Atlas collect_datasets progress stage=write-output output_path=%s", out)
            context._write_json(result=result, out=out)

        if owned_trace and _trace_writer is not None and _finalize_trace:
            summary = build_atlas_summary(atlas=result, atlas_path=out)
            _trace_writer.write("06_final_atlas.json", result)
            _trace_writer.write("07_summary.json", summary)

        logger.info(
            "Atlas collect_datasets stats final_accessions=%s publication_texts=%s collect_metadata=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            collect_metadata,
            out,
        )
        return result

