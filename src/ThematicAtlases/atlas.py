from ThematicAtlases.bootstrap import initialize_atlas, _configured_factory, _json_runtime_provenance
from ThematicAtlases.workflows.create import CreateAtlasWorkflow
from ThematicAtlases.workflows.collect import CollectDatasetsWorkflow
from ThematicAtlases.workflows.resume import ResumeAtlasWorkflow
from ThematicAtlases.workflows.harmonize import HarmonizeDatasetsWorkflow
from ThematicAtlases.workflows.amend import AmendQueriesWorkflow
from ThematicAtlases.runtime.pauses import AtlasPauseController
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
    STAGE_POLICIES,
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.pipeline import (
    AtlasStagePause,
    STOP_AFTER_STAGES,
    validate_stop_after,
)
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
        ncbi_api_key: str | None = None,
        ncbi_tool: str = "ThematicAtlases",
        ncbi_email: str | None = None,
        debug_snapshots: bool = False,
    ):
        initialize_atlas(
            self,
            metadata=metadata,
            epmc_wrapper_factory=epmc_wrapper_factory,
            metadata_handlers=metadata_handlers,
            metadata_repositories=metadata_repositories,
            publication_text_reviewer=publication_text_reviewer,
            collector=collector,
            filterer=filterer,
            harmonizer=harmonizer,
            ontostore=ontostore,
            cache_ontologies=cache_ontologies,
            query_generator=query_generator,
            credential_checker=credential_checker,
            document_adapter=document_adapter,
            artifact_publisher=artifact_publisher,
            capability_registry=capability_registry,
            resource_profile=resource_profile,
            resource_overrides=resource_overrides,
            runtime_provenance=runtime_provenance,
            run_lifecycle=run_lifecycle,
            ncbi_api_key=ncbi_api_key,
            ncbi_tool=ncbi_tool,
            ncbi_email=ncbi_email,
            debug_snapshots=debug_snapshots,
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
        max_review_criteria: int = 12,
    ) -> dict:
        return CreateAtlasWorkflow(self).run(
            query,
            file,
            out,
            theme,
            review_filter,
            review_strategy,
            metadata_repositories,
            max_publications,
            max_publications_per_query,
            reviewer,
            collect_metadata,
            dev_trace,
            dev_out_dir,
            harmonization_details_out,
            generate_queries,
            max_generated_queries,
            harmonization_options,
            review_before_metadata,
            scrape_fulltext_accessions,
            unsupported_accessions_out,
            thematic_review,
            prune_accessions,
            stop_after,
            max_review_criteria=max_review_criteria,
        )

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
        stop_after: str | None = None,
    ) -> dict:
        return ResumeAtlasWorkflow(self).run(
            dev_out_dir,
            run_id,
            out,
            stop_before_review,
            retry_stages,
            retry_items,
            retry_degraded_stages,
            review_decisions,
            stop_after,
        )

    def amend_queries(
        self,
        *,
        dev_out_dir: str,
        run_id: str,
        queries: list[str],
        max_publications_per_query: list[int | None],
    ) -> Path:
        return AmendQueriesWorkflow(self).run(
            dev_out_dir=dev_out_dir,
            run_id=run_id,
            queries=queries,
            max_publications_per_query=max_publications_per_query,
        )

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
        max_review_criteria: int = 12,
    ) -> dict:
        return CollectDatasetsWorkflow(self).run(
            query,
            file,
            out,
            theme,
            review_filter,
            review_strategy,
            metadata_repositories,
            max_publications,
            max_publications_per_query,
            reviewer,
            collect_metadata,
            generate_queries,
            max_generated_queries,
            dev_trace,
            dev_out_dir,
            run_id,
            review_before_metadata,
            stop_before_review,
            scrape_fulltext_accessions,
            unsupported_accessions_out,
            prune_accessions,
            _trace_writer,
            max_review_criteria=max_review_criteria,
        )

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
        stop_after: str | None = None,
        max_review_criteria: int = 12,
    ) -> dict:
        return CollectDatasetsWorkflow(self).run_stage(
            query,
            file,
            out,
            theme,
            review_filter,
            review_strategy,
            metadata_repositories,
            max_publications,
            max_publications_per_query,
            reviewer,
            collect_metadata,
            generate_queries,
            max_generated_queries,
            dev_trace,
            dev_out_dir,
            run_id,
            review_before_metadata,
            stop_before_review,
            scrape_fulltext_accessions,
            unsupported_accessions_out,
            prune_accessions,
            _trace_writer,
            _finalize_trace,
            _resolution,
            _thematic_review,
            stop_after,
            max_review_criteria=max_review_criteria,
        )

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
        return HarmonizeDatasetsWorkflow(self).run(
            datasets,
            harmonization_details_out,
            harmonization_options,
            review_decisions,
        )

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
        stop_after: str | None = None,
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
        if stop_after is not None:
            options["stop_after"] = stop_after
        options.update(
            self._checkpoint_keyword(
                self._collector.collect_jsons,
                checkpoint_store,
            )
        )
        return self._collector.collect_jsons(**options)

    def _pause_at_stage(
        self,
        *,
        trace: DevTraceWriter | None,
        stage: str,
        result: dict,
    ) -> dict:
        return AtlasPauseController(self).pause(trace=trace, stage=stage, result=result)

    def _already_completed_pause(
        self,
        trace: DevTraceWriter,
        stop_after: str | None,
    ) -> dict | None:
        return AtlasPauseController(self).completed(trace, stop_after)

    @staticmethod
    def _checkpoint_status_counts(checkpoint_store) -> dict[str, dict[str, int]]:
        return checkpoint_store.stage_status_counts()

    @staticmethod
    def _pause_frontier_counts(
        stage: str,
        status_counts: dict[str, dict[str, int]],
    ) -> dict[str, int]:
        return AtlasPauseController.frontier_counts(stage, status_counts)

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
        max_review_criteria: int = 12,
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
        if max_review_criteria != 12:
            options["max_review_criteria"] = max_review_criteria
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
        if isinstance(result, dict) and result.get("schema_version") in {"1.0", "1.1"}:
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
