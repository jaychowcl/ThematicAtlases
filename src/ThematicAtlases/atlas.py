import logging
import json
import hashlib
import inspect
from collections.abc import Mapping
from dataclasses import asdict
from functools import partial
from pathlib import Path

from agentic_curator.review_decisions import ReviewDecisionFile
from ThematicAtlases.checkpoint import (
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.application import AtlasDocumentService
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.discovery_trace_migration import (
    migrate_pre_graph_discovery_trace,
)
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry
from ThematicAtlases.run_lifecycle import AtlasRunLifecycle
from ThematicAtlases.runtime_contracts import safe_error_json
from meta_standards_converter.runtime_contracts import (
    ResourceProfile,
    get_resource_profile,
)
from ThematicAtlases.summary import build_atlas_summary
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.trace_fork import fork_metadata_trace
from ThematicAtlases.unsupported_accessions import (
    build_unsupported_accessions_report,
    partition_unsupported_accessions,
)
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper
from ThematicAtlases.wrappers.pubmed_gds import (
    PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
)

logger = logging.getLogger(__name__)


def _configured_factory(factory, **configuration):
    parameters = inspect.signature(factory).parameters.values()
    if not any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    ):
        accepted = {parameter.name for parameter in parameters}
        configuration = {
            key: value
            for key, value in configuration.items()
            if key in accepted
        }
    return partial(factory, **configuration)


def _json_runtime_provenance(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("runtime_provenance must be a mapping or None")
    try:
        normalized = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"))
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "runtime_provenance must be JSON-compatible"
        ) from error
    if not isinstance(normalized, dict):
        raise TypeError("runtime_provenance must normalize to an object")
    return normalized


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
        capability_registry: RepositoryCapabilityRegistry | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides: dict[str, int | float] | None = None,
        runtime_provenance: Mapping[str, object] | None = None,
        run_lifecycle: AtlasRunLifecycle | None = None,
    ):
        self.metadata = metadata
        self._resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(
                resource_profile,
                overrides=resource_overrides,
            )
        )
        self._runtime_provenance = _json_runtime_provenance(runtime_provenance)
        self._capability_registry = (
            capability_registry or RepositoryCapabilityRegistry()
        )
        epmc_wrapper_factory = epmc_wrapper_factory or _configured_factory(
            EuropePMCWrapper,
            resource_profile=self._resource_profile,
        )
        if metadata_handlers is None:
            metadata_handlers = {
                "arrayexpress": _configured_factory(
                    ArrayExpressWrapper,
                    resource_profile=self._resource_profile,
                ),
                "geo": _configured_factory(
                    GEOWrapper,
                    resource_profile=self._resource_profile,
                ),
            }
        publication_text_reviewer = (
            publication_text_reviewer
            or PublicationTextReviewer(
                capability_registry=self._capability_registry
            )
        )
        self._collector = collector or AtlasCollector(
            epmc_wrapper_factory=epmc_wrapper_factory,
            metadata_handlers=metadata_handlers,
            metadata_repositories=metadata_repositories,
            capability_registry=self._capability_registry,
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

            ontostore = OntoStore(resource_profile=self._resource_profile)
        self._ontostore = ontostore
        self._cache_ontologies = cache_ontologies
        self._ontologies_cached = False
        self.ontology_cache_result = None
        self._harmonizer = harmonizer or AtlasHarmonizer(
            ontostore=ontostore,
            credential_checker=credential_checker,
            capability_registry=self._capability_registry,
            max_workers=self._resource_profile.network_workers,
            resource_profile=self._resource_profile,
        )
        self._query_generator_instance = query_generator
        self._credential_checker = credential_checker
        self._credentials_checked = False
        self._documents = AtlasDocumentService(
            adapter=document_adapter or AtlasDocumentAdapter(),
            publisher=artifact_publisher or JsonArtifactBundlePublisher(),
        )
        self._run_lifecycle = run_lifecycle or AtlasRunLifecycle(
            metadata=self.metadata,
            documents=self._documents,
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
        prune_accessions: bool = False,
        stop_after: str | None = None,
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
        if stop_after not in {None, "metadata"}:
            raise ValueError("stop_after must be None or 'metadata'")
        if stop_after == "metadata" and not collect_metadata:
            raise ValueError("stop_after='metadata' requires collect_metadata=True")
        if stop_after == "metadata" and review_before_metadata:
            raise ValueError(
                "stop_after='metadata' requires review_before_metadata=False"
            )
        if stop_after == "metadata" and not dev_trace:
            raise ValueError("stop_after='metadata' requires dev_trace=True")
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
                    "resource_profile": asdict(self._resource_profile),
                    "runtime_provenance": self._runtime_provenance,
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
        if max_publications_per_query is not None:
            collect_kwargs["max_publications_per_query"] = (
                max_publications_per_query
            )
        if trace is not None:
            collect_kwargs["_trace_writer"] = trace
        datasets = self._collect_for_internal(collect_kwargs)
        if trace is not None:
            trace.run_store.set_stage_state(run_id, "collection", "complete")
        if stop_after == "metadata":
            published = self._write_resumed_outputs(
                result=datasets,
                out=None,
                trace=trace,
                artifact_role="collection_snapshot",
            )
            trace.run_store.record_event(
                run_id,
                "run_paused",
                stage="collection",
                detail={"stop_after": "metadata"},
            )
            logger.info(
                "Atlas create_atlas paused stop_after=metadata accessions=%s",
                len(datasets.get("accessions", [])),
            )
            return published
        if trace is not None:
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
                "prune_accessions": prune_accessions,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
                "thematic_review": thematic_review,
                "harmonization_options": dict(harmonization_options or {}),
                "resource_profile": asdict(self._resource_profile),
                "runtime_provenance": self._runtime_provenance,
            },
            run_status=self._final_run_status(
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

    def fork_run(
        self,
        *,
        dev_out_dir: str,
        run_id: str,
        new_run_id: str,
        overrides: dict | None = None,
    ) -> Path:
        """Fork a completed metadata checkpoint for alternate downstream work."""

        return fork_metadata_trace(
            dev_out_dir=dev_out_dir,
            run_id=run_id,
            new_run_id=new_run_id,
            overrides=overrides,
        )

    def migrate_discovery_run(
        self,
        *,
        dev_out_dir: str,
        run_id: str,
        new_run_id: str,
    ) -> Path:
        """Clone a stopped pre-graph discovery trace into contract 1.0."""

        return migrate_pre_graph_discovery_trace(
            dev_out_dir=dev_out_dir,
            run_id=run_id,
            new_run_id=new_run_id,
        )

    def resume(
        self,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        out: str | None = None,
        stop_before_review: bool = False,
        retry_stages=None,
        retry_items=None,
        retry_degraded_stages=None,
        review_decisions: dict | None = None,
    ) -> dict:
        """Resume an incomplete development trace from its latest valid stage."""
        run_dir = self._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
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
                "review_decisions_run_id": (
                    review_decisions.get("run_id")
                    if isinstance(review_decisions, dict)
                    else None
                ),
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
        self._reconcile_checkpoint_contracts(checkpoint_store)
        if self._cache_ontologies:
            self._preflight_credentials()
        self._prepare_ontology_cache()
        if manifest.get("generate_queries", False) or thematic_review:
            self._preflight_credentials()
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
            and review_decisions is None
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
                    review_accessions = accessions
                    if progress_path.exists() and review_before_metadata:
                        if hasattr(self._collector, "available_accession_metadata"):
                            review_accessions = self._collector.available_accession_metadata(
                                jsons=accessions,
                                metadata_repositories=manifest.get("metadata_repositories"),
                                checkpoint_store=checkpoint_store,
                            )
                    if progress_path.exists():
                        progress = self._read_checkpoint(progress_path)
                        review_input = {
                            **progress,
                            "accessions": review_accessions,
                        }
                    else:
                        review_input = review_accessions
                    datasets = self._filter_jsons(
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
                                "accessions": self._filterer.accessions_with_publication_text_refs(
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
                    datasets = self._collect_for_internal(dict(
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
                **(
                    {"review_decisions": review_decisions}
                    if review_decisions is not None
                    else {}
                ),
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
        prune_accessions: bool = False,
        _trace_writer: DevTraceWriter | None = None,
    ) -> dict:
        """Collect datasets and expose the result as an Atlas v1 document."""
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
                "prune_accessions": prune_accessions,
                "collect_metadata": collect_metadata,
                "generate_queries": generate_queries,
                "review_before_metadata": review_before_metadata,
                "stop_before_review": stop_before_review,
                "scrape_fulltext_accessions": scrape_fulltext_accessions,
                "resource_profile": asdict(self._resource_profile),
                "runtime_provenance": self._runtime_provenance,
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
        prune_accessions: bool = False,
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
                    "resource_profile": asdict(self._resource_profile),
                    "runtime_provenance": self._runtime_provenance,
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
            prune_accessions=prune_accessions,
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
        review_decisions: dict | None = None,
    ) -> dict:
        document = AtlasDocument.from_mapping(datasets)
        legacy = self._documents.to_legacy(document)
        result, details = self._harmonizer.harmonize_datasets(
            datasets=legacy,
            details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
            **(
                {"review_decisions": review_decisions}
                if review_decisions is not None
                else {}
            ),
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
        prune_accessions: bool = False,
        _review_progress_callback=None,
        _checkpoint_store=None,
    ) -> dict:
        options = dict(
            jsons=jsons,
            file=file,
            theme=theme,
            review_filter=review_filter,
            review_strategy=review_strategy,
            prune_accessions=prune_accessions,
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
        if isinstance(result, dict) and result.get("schema_version") == "1.0":
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

    def _final_run_status(self, result: dict, checkpoint_store=None) -> RunStatus:
        return self._run_lifecycle.final_run_status(result, checkpoint_store)

    @staticmethod
    def _checkpoint_keyword(callable_object, checkpoint_store, name="checkpoint_store"):
        return AtlasRunLifecycle.checkpoint_keyword(
            callable_object,
            checkpoint_store,
            name,
        )

    def _write_resumed_outputs(
        self,
        result: dict,
        out: str | None,
        trace: DevTraceWriter,
        artifact_role: str = "final_atlas",
    ) -> dict:
        return self._run_lifecycle.write_resumed_outputs(
            result,
            out,
            trace,
            artifact_role,
        )

    def _resume_run_directory(self, dev_out_dir: str, run_id: str | None) -> Path:
        return self._run_lifecycle.resume_run_directory(dev_out_dir, run_id)

    @staticmethod
    def _reconcile_checkpoint_contracts(checkpoint_store) -> None:
        AtlasRunLifecycle.reconcile_checkpoint_contracts(checkpoint_store)

    def _read_checkpoint(self, path: Path):
        return self._run_lifecycle.read_checkpoint(path)

    def _dev_run_id(self) -> str:
        return self._run_lifecycle.dev_run_id()

    @staticmethod
    def archive_existing_runs(
        *,
        dev_out_dir: str,
        archive_root: str,
        workflow: str,
        artifact_paths: list[str] | tuple[str, ...] = (),
    ) -> list[Path]:
        """Archive every inactive trace and fixed artifact for one workflow."""
        return AtlasRunLifecycle.archive_existing_runs(
            dev_out_dir=dev_out_dir,
            archive_root=archive_root,
            workflow=workflow,
            artifact_paths=artifact_paths,
        )
