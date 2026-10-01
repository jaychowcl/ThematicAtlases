"""Construct Atlas services and define provider and operation lifetimes."""
from __future__ import annotations
import json
import inspect
from collections.abc import Mapping
from functools import partial
from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.application import AtlasDocumentService
from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry
from ThematicAtlases.run_lifecycle import AtlasRunLifecycle
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

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


def initialize_atlas(
    atlas,
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
    atlas.metadata = metadata
    atlas._debug_snapshots = bool(debug_snapshots)
    atlas._resource_profile = (
        resource_profile.with_overrides(resource_overrides)
        if isinstance(resource_profile, ResourceProfile) and resource_overrides
        else resource_profile
        if isinstance(resource_profile, ResourceProfile)
        else get_resource_profile(
            resource_profile,
            overrides=resource_overrides,
        )
    )
    atlas._runtime_provenance = _json_runtime_provenance(runtime_provenance)
    atlas._capability_registry = (
        capability_registry or RepositoryCapabilityRegistry()
    )
    factory = AtlasRuntimeFactory(
        resource_profile=atlas._resource_profile,
        capability_registry=atlas._capability_registry,
        epmc_wrapper_factory=epmc_wrapper_factory,
        metadata_handlers=metadata_handlers,
        metadata_repositories=metadata_repositories,
        ncbi_api_key=ncbi_api_key, ncbi_tool=ncbi_tool, ncbi_email=ncbi_email,
    )
    atlas._runtime_factory = factory
    publication_text_reviewer = publication_text_reviewer or factory.build_reviewer()
    atlas._collector = collector or factory.build_collector()
    atlas._filterer = filterer or factory.build_filterer(publication_text_reviewer)
    if harmonizer is not None and (ontostore is not None or cache_ontologies):
        raise ValueError(
            "ontostore/cache_ontologies cannot be combined with a custom harmonizer"
        )
    if cache_ontologies and ontostore is None:
        from agentic_curator.curators.ontology_harmonizer import OntoStore

        ontostore = OntoStore(resource_profile=atlas._resource_profile)
    atlas._ontostore = ontostore
    atlas._cache_ontologies = cache_ontologies
    atlas._ontologies_cached = False
    atlas.ontology_cache_result = None
    atlas._harmonizer = harmonizer or AtlasHarmonizer(
        ontostore=ontostore,
        credential_checker=credential_checker,
        capability_registry=atlas._capability_registry,
        max_workers=atlas._resource_profile.network_workers,
        resource_profile=atlas._resource_profile,
    )
    atlas._query_generator_instance = query_generator
    atlas._credential_checker = credential_checker
    atlas._credentials_checked = False
    atlas._documents = AtlasDocumentService(
        adapter=document_adapter or AtlasDocumentAdapter(),
        publisher=artifact_publisher or JsonArtifactBundlePublisher(),
    )
    atlas._run_lifecycle = run_lifecycle or AtlasRunLifecycle(
        metadata=atlas.metadata,
        documents=atlas._documents,
    )


class AtlasRuntimeFactory:
    """Reusable construction policy; builds fresh continuation services.

    Factories construct objects only. Retrieval/model work is performed by the
    workflows. GSK can supply classified Curator factories and private services.
    """

    def __init__(
        self, *, resource_profile: str | ResourceProfile = 'standard',
        resource_overrides=None, metadata_repositories=None,
        epmc_wrapper_factory=None, metadata_handlers=None, reviewer_factory=None,
        capability_registry=None, ncbi_api_key=None, ncbi_tool='ThematicAtlases',
        ncbi_email=None,
    ):
        self.resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(resource_profile, overrides=resource_overrides)
        )
        self.capability_registry = capability_registry or RepositoryCapabilityRegistry()
        self.metadata_repositories = metadata_repositories
        self.reviewer_factory = reviewer_factory
        self.epmc_wrapper_factory = epmc_wrapper_factory or _configured_factory(
            EuropePMCWrapper, resource_profile=self.resource_profile,
            ncbi_api_key=ncbi_api_key, ncbi_tool=ncbi_tool, ncbi_email=ncbi_email,
        )
        self.metadata_handlers = dict(metadata_handlers) if metadata_handlers is not None else {
            'arrayexpress': _configured_factory(ArrayExpressWrapper, resource_profile=self.resource_profile),
            'geo': _configured_factory(GEOWrapper, resource_profile=self.resource_profile,
                                       api_key=ncbi_api_key, tool=ncbi_tool, email=ncbi_email),
        }

    def build_collector(self):
        return AtlasCollector(
            epmc_wrapper_factory=self.epmc_wrapper_factory,
            metadata_handlers=self.metadata_handlers,
            metadata_repositories=self.metadata_repositories,
            capability_registry=self.capability_registry,
        )

    def build_filterer(self, publication_text_reviewer=None):
        return AtlasFilterer(
            epmc_wrapper_factory=self.epmc_wrapper_factory,
            publication_text_reviewer=publication_text_reviewer or self.build_reviewer(),
        )

    def build_reviewer(self, *, cancelled=None):
        from ThematicAtlases.filterer.resume import TracePublicationReviewResumer

        def continuation(publication_text_reviewer):
            return TracePublicationReviewResumer(
                publication_text_reviewer=publication_text_reviewer,
                collector_factory=self.build_collector,
                filterer_factory=self.build_filterer,
                epmc_wrapper_factory=self.epmc_wrapper_factory,
            )

        reviewer_factory = (
            _configured_factory(self.reviewer_factory, cancelled=cancelled)
            if self.reviewer_factory is not None else None
        )
        return PublicationTextReviewer(
            reviewer_factory=reviewer_factory, resume_orchestrator_factory=continuation,
            capability_registry=self.capability_registry, cancelled=cancelled,
        )

    def build_worker(self, *, cancelled=None):
        from ThematicAtlases.stage_worker import TraceStageWorker
        return TraceStageWorker(
            epmc_wrapper_factory=self.epmc_wrapper_factory,
            collector_factory=self.build_collector,
            publication_text_reviewer_factory=partial(self.build_reviewer, cancelled=cancelled),
        )

    def build_atlas(self, *, metadata: dict, **services):
        from ThematicAtlases.atlas import Atlas
        configuration = {
            'resource_profile': self.resource_profile,
            'capability_registry': self.capability_registry,
            'metadata_repositories': self.metadata_repositories,
            'epmc_wrapper_factory': self.epmc_wrapper_factory,
            'metadata_handlers': self.metadata_handlers,
        }
        configuration.update(services)
        # Create a configured reviewer only if the caller has not supplied one.
        # In particular never replace a caller's explicitly injected services.
        if configuration.get('publication_text_reviewer') is None:
            configuration['publication_text_reviewer'] = self.build_reviewer()
        return Atlas(metadata=metadata, **configuration)


def runtime_factory_for_manifest(manifest):
    """Restore the saved resource limits when constructing default continuations."""
    profile = dict(manifest.get("resource_profile") or {})
    name = profile.pop("name", "standard")
    return AtlasRuntimeFactory(resource_profile=name, resource_overrides=profile,
                               metadata_repositories=manifest.get("metadata_repositories"))
