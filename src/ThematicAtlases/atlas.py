import json
import logging
from datetime import datetime
import hashlib
import inspect
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.summary import build_atlas_summary, summary_path
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

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
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        harmonization_options: dict | None = None,
        review_before_metadata: bool = False,
    ) -> dict:
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
                    "atlas_out": out,
                    "artifacts": [
                        "00_run_manifest.json",
                        "resume_state.sqlite",
                        "01_collected_accessions.json",
                        "02_reviewed_datasets.json",
                        "03_pre_harmonization_accession_metadata.json",
                        "04_harmonization_details.json",
                        "05_post_harmonization_accession_metadata.json",
                        "06_final_atlas.json",
                        "07_summary.json",
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
                },
            )
        logger.info("Atlas create_atlas progress stage=collect-datasets")
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
        )
        if max_publications_per_query is not None:
            collect_kwargs["max_publications_per_query"] = (
                max_publications_per_query
            )
        if trace is not None:
            collect_kwargs["_trace_writer"] = trace
        datasets = self.collect_datasets(**collect_kwargs)
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
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
        else:
            result = self.harmonize_datasets(
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

        if out is not None:
            logger.info("Atlas create_atlas progress stage=write-output output_path=%s", out)
            self._write_json(result=result, out=out)
            summary = build_atlas_summary(atlas=result, atlas_path=out)
            self._write_json(result=summary, out=str(summary_path(out)))
        else:
            summary = build_atlas_summary(atlas=result)

        if trace is not None:
            trace.write("06_final_atlas.json", result)
            trace.write("07_summary.json", summary)

        logger.info(
            "Atlas create_atlas stats final_accessions=%s publication_texts=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            out,
        )
        return result

    def resume(
        self,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        out: str | None = None,
        stop_before_review: bool = False,
    ) -> dict:
        """Resume an incomplete development trace from its latest valid stage."""
        run_dir = self._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
        manifest = self._read_checkpoint(run_dir / "00_run_manifest.json")
        trace = DevTraceWriter.existing(run_dir)
        checkpoint_store = trace.checkpoint_store
        output_path = out if out is not None else manifest.get("atlas_out")
        if stop_before_review:
            logger.info(
                "Atlas resume progress stage=collection-only run_id=%s",
                run_dir.name,
            )
            result = self.collect_datasets(
                query=manifest.get("query"),
                file=manifest.get("query_file"),
                out=output_path,
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
                stop_before_review=True,
                _trace_writer=trace,
            )
            summary = build_atlas_summary(atlas=result, atlas_path=output_path)
            if output_path is not None:
                self._write_json(result=summary, out=str(summary_path(output_path)))
            trace.write("resume_publication_collection.summary.json", summary)
            logger.info(
                "Atlas resume stats run_id=%s workflow=collection-only "
                "accessions=%s publication_texts=%s",
                run_dir.name,
                len(result.get("accessions", [])),
                len(result.get("publication_texts", {})),
            )
            return result
        self._prepare_ontology_cache()
        if manifest.get("theme") is not None:
            self._preflight_credentials()
        logger.info("Atlas resume selected run_id=%s run_dir=%s", run_dir.name, run_dir)

        collection_retryable = any(
            checkpoint_store.has_retryable(stage)
            for stage in (
                "datalinks",
                "geo_resolution",
                "geo_metadata",
                "publication_text",
            )
        )
        harmonization_retryable = checkpoint_store.has_retryable("harmonization")
        discovery_retryable = checkpoint_store.has_retryable("datalinks")
        review_retryable = checkpoint_store.has_retryable("publication_text")
        metadata_retryable = any(
            checkpoint_store.has_retryable(stage)
            for stage in ("geo_resolution", "geo_metadata")
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
            self._write_resumed_outputs(result=result, out=output_path, trace=trace)
            return result

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
                    datasets = self._filter_jsons(
                        jsons=review_input,
                        theme=manifest.get("theme"),
                        review_filter=manifest.get("review_filter", "none"),
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
                    datasets = self.collect_datasets(
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
                        _trace_writer=trace,
                    )

            if manifest.get("command") == "collect-datasets":
                self._write_resumed_outputs(
                    result=datasets,
                    out=output_path,
                    trace=trace,
                )
                logger.info(
                    "Atlas resume stats run_id=%s workflow=collect-datasets accessions=%s",
                    run_dir.name,
                    len(datasets.get("accessions", [])),
                )
                return datasets

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

        self._write_resumed_outputs(result=result, out=output_path, trace=trace)
        logger.info("Atlas resume stats run_id=%s accessions=%s", run_dir.name, len(result.get("accessions", [])))
        return result

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
        replacement_configuration = dict(current["configuration"])
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
        _trace_writer: DevTraceWriter | None = None,
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
                    "atlas_out": out,
                    "artifacts": [
                        "00_run_manifest.json",
                        "resume_state.sqlite",
                        "01_collected_accessions.json",
                        "resume_publication_collection.json",
                        "resume_publication_collection.summary.json",
                        "02_reviewed_datasets.json",
                        "resume_metadata_enriched_datasets.json",
                        "06_final_atlas.json",
                        "07_summary.json",
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
                },
            )
        checkpoint_store = (
            _trace_writer.checkpoint_store if _trace_writer is not None else None
        )
        if generate_queries or (theme is not None and not stop_before_review):
            self._preflight_credentials()
        if generate_queries:
            resolved_queries = (
                checkpoint_store.get_meta("resolved_queries")
                if checkpoint_store is not None
                else None
            )
            if resolved_queries is not None:
                query = resolved_queries
            else:
                query = self._queries_with_generated(
                    query=query,
                    file=file,
                    theme=theme,
                    max_generated_queries=max_generated_queries,
                )
                if checkpoint_store is not None:
                    checkpoint_store.set_meta("resolved_queries", query)
            file = None
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
            checkpoint_store=checkpoint_store,
        )
        if _trace_writer is not None:
            _trace_writer.write("01_collected_accessions.json", accessions)
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
            theme=None if stop_before_review else theme,
            review_filter="none" if stop_before_review else review_filter,
            review_strategy=review_strategy,
            reviewer=reviewer,
            _review_progress_callback=review_progress_callback,
            _checkpoint_store=checkpoint_store,
        )
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
            if owned_trace and _trace_writer is not None:
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

        if owned_trace and _trace_writer is not None:
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
        result, _ = self._harmonizer.harmonize_datasets(
            datasets=datasets,
            details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
        )
        return result

    def _collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        collect_metadata: bool = True,
        checkpoint_store=None,
    ) -> list[dict]:
        options = dict(
            query=query,
            file=file,
            out=out,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            collect_metadata=collect_metadata,
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

    def _write_json(self, result: dict | list[dict], out: str) -> None:
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

    def _write_resumed_outputs(self, result: dict, out: str | None, trace: DevTraceWriter) -> None:
        if out is not None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            self._write_json(result=result, out=out)
            summary = build_atlas_summary(atlas=result, atlas_path=out)
            self._write_json(result=summary, out=str(summary_path(out)))
        else:
            summary = build_atlas_summary(atlas=result)
        trace.write("06_final_atlas.json", result)
        trace.write("07_summary.json", summary)

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
                state_path = run_dir / "resume_state.sqlite"
                if not state_path.exists() or not CheckpointStore(
                    state_path
                ).has_retryable():
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
        return datetime.now().strftime("%Y%m%dT%H%M%S")
