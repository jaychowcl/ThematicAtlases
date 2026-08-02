import json
import logging
from datetime import datetime, timezone
import hashlib
import inspect
from pathlib import Path
import secrets

from ThematicAtlases.checkpoint import (
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.application import AtlasDocumentService
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.summary import build_atlas_summary
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.unsupported_accessions import (
    build_unsupported_accessions_report,
    partition_unsupported_accessions,
)
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper
from ThematicAtlases.run_archive import archive_existing_runs

logger = logging.getLogger(__name__)


class Atlas:
    def __init__(
        self,
        metadata: dict,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
        metadata_repositories: list[str] | None = None,
        publication_text_reviewer: PublicationTextReviewer | None = None,
        collector: AtlasCollector | None = None,
        filterer: AtlasFilterer | None = None,
        harmonizer: AtlasHarmonizer | None = None,
        ontostore=None,
        cache_ontologies: bool = False,
        query_generator=None,
        credential_checker=None,
        document_adapter: AtlasDocumentAdapter | None = None,
        artifact_publisher: JsonArtifactBundlePublisher | None = None,
    ):
        self.metadata = metadata
        epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        metadata_handlers = metadata_handlers or {
            "arrayexpress": ArrayExpressWrapper,
            "geo": GEOWrapper,
        }
        publication_text_reviewer = (
            publication_text_reviewer or PublicationTextReviewer()
        )
        self._collector = collector or AtlasCollector(
            epmc_wrapper_factory=epmc_wrapper_factory,
            metadata_handlers=metadata_handlers,
            metadata_repositories=metadata_repositories,
        )
        self._filterer = filterer or AtlasFilterer(
            epmc_wrapper_factory=epmc_wrapper_factory,
            publication_text_reviewer=publication_text_reviewer,
        )
        if harmonizer is not None and (ontostore is not None or cache_ontologies):
            raise ValueError(
                "ontostore/cache_ontologies cannot be combined with a custom harmonizer"
            )
        if cache_ontologies and ontostore is None:
            from agentic_curator.curators.ontology_harmonizer import OntoStore

            ontostore = OntoStore()
        self._ontostore = ontostore
        self._cache_ontologies = cache_ontologies
        self._ontologies_cached = False
        self.ontology_cache_result = None
        self._harmonizer = harmonizer or AtlasHarmonizer(
            ontostore=ontostore,
            credential_checker=credential_checker,
        )
        self._query_generator_instance = query_generator
        self._credential_checker = credential_checker
        self._credentials_checked = False
        self._documents = AtlasDocumentService(
            adapter=document_adapter or AtlasDocumentAdapter(),
            publisher=artifact_publisher or JsonArtifactBundlePublisher(),
        )

    def create_atlas(
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
    ) -> dict:
        if theme is None or not theme.strip():
            raise ValueError("create_atlas requires a non-empty theme")
        if not generate_queries and not self._has_input_queries(query, file):
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
        if self._cache_ontologies:
            self._preflight_credentials()
        self._prepare_ontology_cache()
        run_id = self._dev_run_id()
        trace = None
        if dev_trace:
            trace = DevTraceWriter(
                root=dev_out_dir,
                run_id=run_id,
                manifest={
                    "command": "create-atlas",
                    "created_at": run_id,
                    "atlas_id": str(
                        self.metadata.get("atlas_id") or f"atlas-{run_id}"
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
                    "unsupported_accessions_out": unsupported_accessions_out,
                    "thematic_review": thematic_review,
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
        if max_publications_per_query is not None:
            collect_kwargs["max_publications_per_query"] = (
                max_publications_per_query
            )
        if trace is not None:
            collect_kwargs["_trace_writer"] = trace
        datasets = self._collect_for_internal(collect_kwargs)
        if trace is not None:
            trace.run_store.set_stage_state(run_id, "collection", "complete")
            trace.run_store.set_stage_state(run_id, "harmonization", "running")
        logger.info(
            "Atlas create_atlas progress stage=collect-datasets-complete accessions=%s publication_texts=%s",
            len(datasets.get("accessions", [])),
            len(datasets.get("publication_texts", {})),
        )
        logger.info("Atlas create_atlas progress stage=harmonize-datasets")
        if trace is not None:
            trace.write(
                "03_pre_harmonization_accession_metadata.json",
                trace.metadata(datasets.get("accessions", [])),
            )
            result, details = self._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
                **self._checkpoint_keyword(
                    self._harmonizer.harmonize_datasets,
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
        else:
            result, details = self._harmonize_for_internal(
                datasets=datasets,
                harmonization_details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
            )
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas create_atlas progress stage=harmonize-datasets-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        document = self._documents.assemble(
            result,
            atlas_metadata=self.metadata,
            run_id=run_id,
            created_at=run_id,
            theme=theme or "",
            config={
                "queries": collection_resolution.get("queries", list(query or ())),
                "metadata_repositories": list(metadata_repositories or ()),
                "query_file": file,
                "review_filter": review_filter,
                "review_strategy": review_strategy,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
                "thematic_review": thematic_review,
                "harmonization_options": dict(harmonization_options or {}),
            },
            run_status=self._final_run_status(result),
            harmonization_details=details,
        )
        result_mapping = document.to_mapping()
        unsupported_report = build_unsupported_accessions_report(
            list(result.get("unsupported_accessions", [])),
            atlas_id=document.atlas.atlas_id,
            run_id=document.run.run_id,
        )
        summary = self._documents.summary(
            document,
            atlas_path=out,
            unsupported_accessions_report=unsupported_report,
            unsupported_accessions_path=unsupported_accessions_out,
        )

        if out is not None:
            logger.info("Atlas create_atlas progress stage=write-output output_path=%s", out)
            self._documents.publish(
                document,
                out,
                include_summary=True,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_accessions_out,
            )
        elif unsupported_accessions_out is not None:
            self._documents.publish_unsupported_accessions(
                unsupported_report,
                unsupported_accessions_out,
            )

        if trace is not None:
            trace.write("06_final_atlas.json", result_mapping)
            trace.write("07_summary.json", summary)
            trace.write("unsupported_accessions.json", unsupported_report)
            trace.register_artifact("final_atlas", "06_final_atlas.json")
            trace.register_artifact("summary", "07_summary.json")
            trace.register_artifact(
                "unsupported_accessions", "unsupported_accessions.json"
            )
            trace.run_store.set_stage_state(
                run_id, "harmonization", "complete"
            )
            trace.run_store.set_run_status(run_id, document.run.status.value)
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

    def resume(
        self,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        out: str | None = None,
        stop_before_review: bool = False,
        retry_stages=None,
        retry_items=None,
        retry_degraded_stages=None,
    ) -> dict:
        """Resume an incomplete development trace from its latest valid stage."""
        run_dir = self._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
        manifest = self._read_checkpoint(run_dir / "00_run_manifest.json")
        thematic_review = manifest.get(
            "thematic_review", manifest.get("theme") is not None
        )
        trace = DevTraceWriter.existing(run_dir)
        run_store = trace.run_store
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
            },
        )
        output_path = out if out is not None else manifest.get("atlas_out")
        if stop_before_review:
            logger.info(
                "Atlas resume progress stage=collection-only run_id=%s",
                run_dir.name,
            )
            result = self._collect_for_internal(dict(
                query=manifest.get("query"),
                file=manifest.get("query_file"),
                out=None,
                theme=manifest.get("theme"),
                review_filter=manifest.get("review_filter", "none"),
                review_strategy=manifest.get("review_strategy", "direct"),
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
            published = self._write_resumed_outputs(
                result=result,
                out=output_path,
                trace=trace,
                artifact_role="collection_snapshot",
            )
            trace.write(
                "resume_publication_collection.summary.json",
                self._documents.summary(
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
        if self._cache_ontologies:
            self._preflight_credentials()
        self._prepare_ontology_cache()
        if manifest.get("generate_queries", False) or thematic_review:
            self._preflight_credentials()
        logger.info("Atlas resume selected run_id=%s run_dir=%s", run_dir.name, run_dir)

        discovery_retryable = checkpoint_store.has_retryable_boundary("discovery")
        review_retryable = checkpoint_store.has_retryable_boundary("review")
        metadata_retryable = checkpoint_store.has_retryable_boundary("metadata")
        collection_retryable = any(
            (discovery_retryable, review_retryable, metadata_retryable)
        )
        harmonization_retryable = checkpoint_store.has_retryable_boundary(
            "harmonization"
        )
        review_before_metadata = manifest.get("review_before_metadata", False)
        final_path = run_dir / "06_final_atlas.json"
        if (
            final_path.exists()
            and not collection_retryable
            and not harmonization_retryable
        ):
            result = self._read_checkpoint(final_path)
            logger.info("Atlas resume progress stage=final-atlas-complete")
            return self._write_resumed_outputs(
                result=result, out=output_path, trace=trace
            )

        harmonized_path = run_dir / "resume_harmonized_datasets.json"
        if (
            harmonized_path.exists()
            and not collection_retryable
            and not harmonization_retryable
        ):
            result = self._read_checkpoint(harmonized_path)
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
                datasets = self._read_checkpoint(metadata_enriched_path)
                logger.info("Atlas resume progress stage=metadata-enrichment-complete")
            elif reviewed_path.exists() and not (
                discovery_retryable
                or review_retryable
                or (metadata_retryable and not review_before_metadata)
            ):
                datasets = self._read_checkpoint(reviewed_path)
                logger.info("Atlas resume progress stage=review-complete")
                if review_before_metadata and manifest.get("collect_metadata", True):
                    datasets = self._metadata_for_reviewed_datasets(
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
                    accessions = self._read_checkpoint(collected_path)
                    logger.info("Atlas resume progress stage=collection-complete")
                    progress_path = run_dir / "resume_review_progress.json"
                    review_input = (
                        self._read_checkpoint(progress_path)
                        if progress_path.exists()
                        else accessions
                    )
                    if progress_path.exists() and review_before_metadata:
                        progress_accessions = review_input.get("accessions", [])
                        if hasattr(self._collector, "available_accession_metadata"):
                            review_input = {
                                **review_input,
                                "accessions": self._collector.available_accession_metadata(
                                    jsons=progress_accessions,
                                    metadata_repositories=manifest.get("metadata_repositories"),
                                    checkpoint_store=checkpoint_store,
                                ),
                            }
                    datasets = self._filter_jsons(
                        jsons=review_input,
                        theme=(manifest.get("theme") if thematic_review else None),
                        review_filter=(
                            manifest.get("review_filter", "none")
                            if thematic_review
                            else "none"
                        ),
                        review_strategy=manifest.get("review_strategy", "direct"),
                        _review_progress_callback=lambda texts: trace.write(
                            "resume_review_progress.json",
                            {"accessions": self._filterer.accessions_with_publication_text_refs(accessions, texts), "publication_texts": texts},
                        ),
                        _checkpoint_store=checkpoint_store,
                    )
                    trace.write("02_reviewed_datasets.json", datasets)
                else:
                    logger.info("Atlas resume progress stage=collection-required")
                    datasets = self._collect_for_internal(dict(
                        query=manifest.get("query"),
                        file=manifest.get("query_file"),
                        theme=manifest.get("theme"),
                        review_filter=manifest.get("review_filter", "none"),
                        review_strategy=manifest.get("review_strategy", "direct"),
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
                    ))

            if manifest.get("command") == "collect-datasets":
                published = self._write_resumed_outputs(
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
            result, details = self._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=manifest.get("harmonization_details_out"),
                harmonization_options=manifest.get("harmonization_options"),
                **self._checkpoint_keyword(
                    self._harmonizer.harmonize_datasets,
                    checkpoint_store,
                ),
            )
            trace.write("04_harmonization_details.json", details)
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
            trace.write("resume_harmonized_datasets.json", result)

        published = self._write_resumed_outputs(
            result=result, out=output_path, trace=trace
        )
        logger.info("Atlas resume stats run_id=%s accessions=%s", run_dir.name, len(result.get("accessions", [])))
        return published

    def amend_queries(
        self,
        *,
        dev_out_dir: str,
        run_id: str,
        queries: list[str],
        max_publications_per_query: list[int | None],
    ) -> Path:
        """Amend one trace's queries without discarding completed work."""
        if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
            raise ValueError("queries must contain non-empty strings")
        if len(queries) != len(max_publications_per_query):
            raise ValueError(
                "max_publications_per_query must contain one limit per query"
            )
        if any(
            limit is not None and limit < 1
            for limit in max_publications_per_query
        ):
            raise ValueError(
                "max_publications_per_query limits must be positive integers or None"
            )

        run_dir = self._resume_run_directory(
            dev_out_dir=dev_out_dir,
            run_id=run_id,
        )
        manifest_path = run_dir / "00_run_manifest.json"
        manifest = self._read_checkpoint(manifest_path)
        trace = DevTraceWriter.existing(run_dir)
        store = trace.checkpoint_store
        current = store.get_meta("run_fingerprint")
        if current is None:
            raise ValueError("trace does not contain a run fingerprint")
        current_configuration = current["configuration"]
        current_queries = current_configuration.get("query") or []
        normalized_current = [" ".join(query.split()) for query in current_queries]
        normalized_requested = [" ".join(query.split()) for query in queries]
        if (
            normalized_current == normalized_requested
            and current_configuration.get("max_publications_per_query")
            == list(max_publications_per_query)
            and current_configuration.get("max_publications") is None
            and current_configuration.get("query_file") is None
        ):
            archive = manifest.get("query_archive")
            return run_dir / archive if archive else run_dir
        replacement_configuration = dict(current_configuration)
        replacement_configuration.update(
            {
                "query": list(queries),
                "query_file": None,
                "max_publications": None,
                "max_publications_per_query": list(max_publications_per_query),
            }
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "queries": queries,
                    "limits": max_publications_per_query,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        amendment_id = f"query-expansion-{digest}"
        previous = store.amend_fingerprint(
            replacement_configuration,
            amendment_id=amendment_id,
            metadata={"run_id": run_dir.name, "reason": "append complementary searches"},
        )

        archive_directory = run_dir / "query_archives" / amendment_id
        if archive_directory.exists():
            archive_writer = DevTraceWriter.existing(archive_directory)
        else:
            archive_writer = DevTraceWriter(
                root=str(run_dir / "query_archives"),
                run_id=amendment_id,
                manifest={
                    "archive_id": amendment_id,
                    "source_run_id": run_dir.name,
                    "previous_manifest": manifest,
                    "previous_fingerprint": previous,
                },
            )
            archive_writer.write(
                "query_configuration.json",
                {
                    "previous": previous,
                    "replacement": store.get_meta("run_fingerprint"),
                },
            )
        amended_manifest = {
            **manifest,
            "query": list(queries),
            "query_file": None,
            "max_publications": None,
            "max_publications_per_query": list(max_publications_per_query),
            "query_amendment_id": amendment_id,
            "query_archive": str(archive_writer.directory.relative_to(run_dir)),
        }
        trace.write("00_run_manifest.json", amended_manifest)
        logger.info(
            "Atlas query amendment run_id=%s amendment_id=%s queries=%s limits=%s",
            run_dir.name,
            amendment_id,
            len(queries),
            max_publications_per_query,
        )
        return archive_writer.directory

    def collect_datasets(
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
        _trace_writer: DevTraceWriter | None = None,
    ) -> dict:
        """Collect datasets and expose the result as an Atlas v2 document."""
        effective_run_id = run_id or (
            _trace_writer.directory.name
            if _trace_writer is not None
            else self._dev_run_id()
        )
        collection_resolution: dict[str, list[str]] = {}
        legacy = self._collect_datasets_legacy(
            query=query,
            file=file,
            out=None,
            theme=theme,
            review_filter=review_filter,
            review_strategy=review_strategy,
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
        document = self._documents.assemble(
            legacy,
            atlas_metadata=self.metadata,
            run_id=effective_run_id,
            created_at=effective_run_id,
            theme=theme or "",
            config={
                "queries": collection_resolution.get("queries", list(query or ())),
                "metadata_repositories": list(metadata_repositories or ()),
                "query_file": file,
                "review_filter": review_filter,
                "review_strategy": review_strategy,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "stop_before_review": stop_before_review,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
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
            self._documents.publish(
                document,
                out,
                include_summary=False,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_accessions_out,
            )
        elif unsupported_accessions_out is not None:
            self._documents.publish_unsupported_accessions(
                unsupported_report,
                unsupported_accessions_out,
            )
        if dev_trace and _trace_writer is None:
            trace = DevTraceWriter.existing(Path(dev_out_dir) / effective_run_id)
            trace.write("collection_snapshot.json", result)
            trace.write(
                "collection_snapshot.summary.json",
                self._documents.summary(
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

    def _collect_datasets_legacy(
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
        _trace_writer: DevTraceWriter | None = None,
        _finalize_trace: bool = True,
        _resolution: dict[str, list[str]] | None = None,
        _thematic_review: bool = True,
    ) -> dict:
        if review_before_metadata and theme is None:
            raise ValueError("review_before_metadata requires a theme")
        owned_trace = dev_trace and _trace_writer is None
        if owned_trace:
            effective_run_id = run_id or self._dev_run_id()
            _trace_writer = DevTraceWriter(
                root=dev_out_dir,
                run_id=effective_run_id,
                manifest={
                    "command": "collect-datasets",
                    "created_at": effective_run_id,
                    "atlas_id": str(
                        self.metadata.get("atlas_id")
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
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "max_publications_per_query": max_publications_per_query,
                    "collect_metadata": collect_metadata,
                    "generate_queries": generate_queries,
                    "max_generated_queries": max_generated_queries,
                    "review_before_metadata": review_before_metadata,
                    "stop_before_review": stop_before_review,
                    "scrape_fulltext_accessions": scrape_fulltext_accessions,
                    "unsupported_accessions_out": unsupported_accessions_out,
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
            self._preflight_credentials()
        if generate_queries:
            generation_input = {
                "query": list(query or []),
                "file_queries": self._load_queries(file=file)
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
            resolved_queries = (
                checkpoint_store.get_meta("resolved_queries")
                if checkpoint_store is not None
                else None
            )
            generation_checkpoint = (
                checkpoint_store.get("query_generation", generation_key)
                if checkpoint_store is not None
                else None
            )
            if resolved_queries is not None:
                query = resolved_queries
            elif (
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
                    query = self._queries_with_generated(
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
                            error=str(error),
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
            if checkpoint_store is not None:
                checkpoint_store.set_meta("resolved_queries", query)
            file = None
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
            }
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
        accessions = self._collect_jsons(
            query=query,
            file=file,
            out=None,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            max_publications_per_query=max_publications_per_query,
            collect_metadata=collect_metadata and not review_before_metadata,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
            checkpoint_store=checkpoint_store,
        )
        accessions, unsupported_accessions = partition_unsupported_accessions(
            accessions
        )
        if _trace_writer is not None:
            _trace_writer.write("01_collected_accessions.json", accessions)
            unsupported_report = build_unsupported_accessions_report(
                unsupported_accessions,
                atlas_id=str(
                    self.metadata.get("atlas_id")
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
                    "accessions": self._filterer.accessions_with_publication_text_refs(
                        accessions, texts
                    ),
                    "publication_texts": texts,
                },
            )
        result = self._filter_jsons(
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
            reviewer=reviewer,
            _review_progress_callback=review_progress_callback,
            _checkpoint_store=checkpoint_store,
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
                self._write_json(result=result, out=out)
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
        if review_before_metadata and collect_metadata:
            logger.info("Atlas collect_datasets progress stage=collect-accession-metadata")
            result = self._metadata_for_reviewed_datasets(
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
            self._write_json(result=result, out=out)

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

    def _metadata_for_reviewed_datasets(
        self,
        datasets: dict,
        metadata_repositories: list[str] | None,
        checkpoint_store=None,
    ) -> dict:
        options = {
            "jsons": datasets.get("accessions", []),
            "metadata_repositories": metadata_repositories,
        }
        options.update(
            self._checkpoint_keyword(
                self._collector.collect_accession_metadata,
                checkpoint_store,
            )
        )
        accessions = self._collector.collect_accession_metadata(**options)
        used_refs = {
            publication.get("publication_text_ref")
            for record in accessions
            for publication in record.get("publications", [])
            if publication.get("publication_text_ref")
        }
        publication_texts = {
            ref: value
            for ref, value in datasets.get("publication_texts", {}).items()
            if ref in used_refs
        }
        return {
            **datasets,
            "accessions": accessions,
            "publication_texts": publication_texts,
        }

    def harmonize_datasets(
        self,
        datasets: dict,
        harmonization_details_out: str | None = None,
        harmonization_options: dict | None = None,
    ) -> dict:
        document = AtlasDocument.from_mapping(datasets)
        legacy = self._documents.to_legacy(document)
        result, details = self._harmonizer.harmonize_datasets(
            datasets=legacy,
            details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
        )
        updated = self._documents.assemble(
            result,
            atlas_metadata={
                "atlas_id": document.atlas.atlas_id,
                "title": document.atlas.title,
                "theme": document.atlas.theme,
            },
            run_id=document.run.run_id,
            created_at=document.run.created_at,
            theme=document.atlas.theme,
            config={
                "queries": list(document.run.config.queries),
                "metadata_repositories": list(
                    document.run.config.metadata_repositories
                ),
                **dict(document.run.config.options),
            },
            run_status=self._final_run_status(result),
            harmonization_details=details,
        )
        return updated.to_mapping()

    def _collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        collect_metadata: bool = True,
        scrape_fulltext_accessions: bool = True,
        checkpoint_store=None,
    ) -> list[dict]:
        options = dict(
            query=query,
            file=file,
            out=out,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            collect_metadata=collect_metadata,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
        )
        if max_publications_per_query is not None:
            options["max_publications_per_query"] = max_publications_per_query
        options.update(
            self._checkpoint_keyword(
                self._collector.collect_jsons,
                checkpoint_store,
            )
        )
        return self._collector.collect_jsons(**options)

    def _filter_jsons(
        self,
        jsons: dict | list[dict] | None = None,
        file: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        review_strategy: str = "direct",
        reviewer=None,
        _review_progress_callback=None,
        _checkpoint_store=None,
    ) -> dict:
        options = dict(
            jsons=jsons,
            file=file,
            theme=theme,
            review_filter=review_filter,
            review_strategy=review_strategy,
            reviewer=reviewer,
        )
        if _review_progress_callback is not None:
            options["_review_progress_callback"] = _review_progress_callback
        options.update(
            self._checkpoint_keyword(
                self._filterer.filter_jsons,
                _checkpoint_store,
                name="_checkpoint_store",
            )
        )
        return self._filterer.filter_jsons(**options)

    def _harmonize_jsons(self, datasets: dict) -> dict:
        return self._harmonizer.harmonize_jsons(datasets=datasets)

    def _queries_with_generated(
        self,
        query: list[str] | None,
        file: str | None,
        theme: str | None,
        max_generated_queries: int,
    ) -> list[str]:
        if theme is None or not theme.strip():
            raise ValueError("generate_queries requires a non-empty theme")

        queries = list(query or [])
        if file is not None:
            queries.extend(self._load_queries(file=file))

        generated = self._query_generator().generate_queries(
            theme,
            max_queries=max_generated_queries,
        )
        generated_queries = generated.get("queries")
        if not isinstance(generated_queries, list) or not all(
            isinstance(value, str) and value.strip() for value in generated_queries
        ):
            raise ValueError("query generator returned an invalid queries list")

        queries.extend(generated_queries)
        return queries

    def _has_input_queries(
        self,
        query: list[str] | None,
        file: str | None,
    ) -> bool:
        if any(isinstance(value, str) and value.strip() for value in query or ()):
            return True
        return bool(file is not None and self._load_queries(file=file))

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _query_generator(self):
        if self._query_generator_instance is None:
            from agentic_curator import QueryGenerator

            self._query_generator_instance = QueryGenerator()
        return self._query_generator_instance

    def _preflight_credentials(self) -> None:
        if self._credential_checker is None or self._credentials_checked:
            return
        self._credential_checker.check()
        self._credentials_checked = True

    def _prepare_ontology_cache(self) -> None:
        if not self._cache_ontologies or self._ontologies_cached:
            return
        self.ontology_cache_result = self._ontostore.cache_all()
        self._ontologies_cached = True

    def _collect_for_internal(self, options: dict) -> dict:
        """Run collection in the stage shape while honoring test/integration subclasses."""
        if type(self).collect_datasets is Atlas.collect_datasets:
            return self._collect_datasets_legacy(**options)
        resolution = options.pop("_resolution", None)
        thematic_review = options.pop("_thematic_review", True)
        if not thematic_review:
            options["theme"] = None
            options["review_filter"] = "none"
        result = self.collect_datasets(**options)
        if isinstance(result, dict) and result.get("schema_version") == "2.0":
            document = AtlasDocument.from_mapping(result)
            if resolution is not None:
                resolution["queries"] = list(document.run.config.queries)
            return self._documents.to_legacy(document)
        return result

    def _harmonize_for_internal(
        self,
        *,
        datasets: dict,
        harmonization_details_out: str | None,
        harmonization_options: dict | None,
    ) -> tuple[dict, list[dict]]:
        """Run harmonization in the stage shape while honoring subclasses."""
        if type(self).harmonize_datasets is Atlas.harmonize_datasets:
            return self._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
            )
        result = self.harmonize_datasets(
            datasets=datasets,
            harmonization_details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
        )
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[0], dict)
        ):
            return result
        return result, []

    @staticmethod
    def _final_run_status(result: dict) -> RunStatus:
        failed = any(
            record.get("ontology_harmonization_run_status") == "error"
            or str(record.get("metadata_status") or "").lower()
            in {"error", "failed"}
            for record in result.get("accessions", [])
            if isinstance(record, dict)
        )
        return RunStatus.PARTIAL if failed else RunStatus.COMPLETE

    def _write_json(self, result: dict | list[dict], out: str) -> None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)

    @staticmethod
    def _checkpoint_keyword(callable_object, checkpoint_store, name="checkpoint_store"):
        if checkpoint_store is None:
            return {}
        parameters = inspect.signature(callable_object).parameters
        if name in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return {name: checkpoint_store}
        return {}

    def _write_resumed_outputs(
        self,
        result: dict,
        out: str | None,
        trace: DevTraceWriter,
        artifact_role: str = "final_atlas",
    ) -> dict:
        manifest = self._read_checkpoint(
            trace.directory / "00_run_manifest.json"
        )
        if result.get("schema_version") == "2.0":
            document = AtlasDocument.from_mapping(result)
        else:
            details_path = trace.directory / "04_harmonization_details.json"
            details = (
                self._read_checkpoint(details_path)
                if details_path.exists()
                else None
            )
            run_status = (
                RunStatus.RUNNING
                if manifest.get("command") == "collect-datasets"
                else self._final_run_status(result)
            )
            document = self._documents.assemble(
                result,
                atlas_metadata=self.metadata,
                run_id=trace.directory.name,
                created_at=str(
                    manifest.get("created_at") or trace.directory.name
                ),
                theme=str(manifest.get("theme") or ""),
                config={
                    "queries": list(
                        trace.checkpoint_store.get_meta("resolved_queries")
                        or manifest.get("query")
                        or ()
                    ),
                    "metadata_repositories": list(
                        manifest.get("metadata_repositories") or ()
                    ),
                    **{
                        key: value
                        for key, value in manifest.items()
                        if key
                        not in {
                            "query",
                            "metadata_repositories",
                            "artifacts",
                        }
                    },
                },
                run_status=run_status,
                harmonization_details=details,
            )
        unsupported_report_path = trace.directory / "unsupported_accessions.json"
        unsupported_report = (
            self._read_checkpoint(unsupported_report_path)
            if unsupported_report_path.exists()
            else build_unsupported_accessions_report(
                list(result.get("unsupported_accessions", [])),
                atlas_id=document.atlas.atlas_id,
                run_id=document.run.run_id,
            )
        )
        unsupported_output_path = manifest.get("unsupported_accessions_out")
        published = document.to_mapping()
        if out is not None:
            summary = self._documents.publish(
                document,
                out,
                include_summary=True,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_output_path,
            )
        else:
            summary = self._documents.summary(
                document,
                None,
                unsupported_accessions_report=unsupported_report,
                unsupported_accessions_path=unsupported_output_path,
            )
            if unsupported_output_path is not None:
                self._documents.publish_unsupported_accessions(
                    unsupported_report,
                    unsupported_output_path,
                )
        atlas_name = (
            "collection_snapshot.json"
            if artifact_role == "collection_snapshot"
            else "06_final_atlas.json"
        )
        summary_name = (
            "collection_snapshot.summary.json"
            if artifact_role == "collection_snapshot"
            else "07_summary.json"
        )
        trace.write(atlas_name, published)
        trace.write(summary_name, summary)
        trace.write("unsupported_accessions.json", unsupported_report)
        trace.register_artifact(artifact_role, atlas_name)
        trace.register_artifact("summary", summary_name)
        trace.register_artifact(
            "unsupported_accessions", "unsupported_accessions.json"
        )
        if artifact_role == "collection_snapshot":
            trace.run_store.set_stage_state(
                trace.directory.name, "collection", "complete"
            )
            trace.run_store.set_run_status(trace.directory.name, "running")
        else:
            trace.run_store.set_stage_state(
                trace.directory.name, "harmonization", "complete"
            )
            trace.run_store.set_run_status(
                trace.directory.name, document.run.status.value
            )
        trace.run_store.record_event(
            trace.directory.name,
            "artifact_published",
            detail={"artifact_role": artifact_role},
        )
        return published

    def _resume_run_directory(self, dev_out_dir: str, run_id: str | None) -> Path:
        root = Path(dev_out_dir)
        if run_id is not None:
            candidate = Path(run_id)
            run_dir = candidate if candidate.is_dir() else root / run_id
            self._read_checkpoint(run_dir / "00_run_manifest.json")
            return run_dir

        candidates = []
        for run_dir in root.iterdir() if root.is_dir() else []:
            manifest_path = run_dir / "00_run_manifest.json"
            final_path = run_dir / "06_final_atlas.json"
            if not run_dir.is_dir() or not manifest_path.exists():
                continue
            if final_path.exists():
                try:
                    checkpoint_store = DevTraceWriter.existing(
                        run_dir
                    ).checkpoint_store
                except (OSError, ValueError):
                    continue
                if not checkpoint_store.has_retryable():
                    continue
            try:
                self._read_checkpoint(manifest_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            candidates.append(run_dir)
        if not candidates:
            raise FileNotFoundError(f"No incomplete valid trace found under {root}")
        return max(candidates, key=lambda path: path.name)

    def _read_checkpoint(self, path: Path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _dev_run_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{timestamp}-{secrets.token_hex(4)}"
    @staticmethod
    def archive_existing_runs(
        *,
        dev_out_dir: str,
        archive_root: str,
        workflow: str,
        artifact_paths: list[str] | tuple[str, ...] = (),
    ) -> list[Path]:
        """Archive every inactive trace and fixed artifact for one workflow."""
        return archive_existing_runs(
            dev_out_dir=dev_out_dir,
            archive_root=archive_root,
            workflow=workflow,
            artifact_paths=artifact_paths,
        )
