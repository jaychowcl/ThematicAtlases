# codebase.md Index

Stable anchors route into `docs/codebase.md`. Read this file first, choose the
relevant section id or keyword, then retrieve only that anchored section.

```bash
$HOME/.codex/retrieve_codebase_section.py --id <section-id>
```

Use `--query <keyword>` when the id is unknown.

## Canonical architecture routes

- id: architecture
  title: [Architecture](codebase.md#architecture)
  anchor: architecture
  purpose: High-level purpose, runtime topology, subsystem ownership, and whole-codebase navigation.
  keywords: architecture, Atlas, CLI, collector, filterer, harmonizer, checkpoint, benchmark

- id: system-context-and-boundaries
  title: [System Context And Boundaries](codebase.md#system-context-and-boundaries)
  anchor: system-context-and-boundaries
  purpose: External actors, delegated packages, persistence, network, trust, privacy, and failure ownership.
  keywords: Europe PMC, NCBI, ENA, BioStudies, Google ADC, agentic-curator 3.x, meta-standards-converter 4.x, MSC MINiML 2.0, Atlas document schema 1.0, H5AD metadata schema 1.0, SQLite schema 2, privacy, safe errors

- id: architectural-decisions
  title: [Architectural Decisions](codebase.md#architectural-decisions)
  anchor: architectural-decisions
  purpose: Evidence-safe documented and observed design choices, consequences, and affected components.
  keywords: AD-001, AD-002, AD-003, AD-004, AD-005, AD-006, Atlas v1, observed, documented, decisions

- id: design-invariants-and-expectations
  title: [Design Invariants And Expectations](codebase.md#design-invariants-and-expectations)
  anchor: design-invariants-and-expectations
  purpose: Atlas v1 validation, state authority, transaction, compatibility, retry, archive, logging, and privacy rules future changes must preserve.
  keywords: AtlasDocument, schema_version, atlas_run.sqlite3, run ID, UTC, entropy, rollback, fingerprint, retryable, archive

- id: component-relationships-and-data-flow
  title: [Component Relationships And Data Flow](codebase.md#component-relationships-and-data-flow)
  anchor: component-relationships-and-data-flow
  purpose: Directional contracts, lifecycle ownership, exchanged data, and failure propagation between components.
  keywords: AtlasCollector, AtlasFilterer, PublicationTextReviewer, AtlasHarmonizer, CheckpointStore, data flow

- id: entrypoints-and-interfaces
  title: [Entrypoints And Interfaces](codebase.md#entrypoints-and-interfaces)
  anchor: entrypoints-and-interfaces
  purpose: Installed CLI, Python imports, focused scripts, supported inputs, and emitted artifacts.
  keywords: thematic-atlas, collect-datasets, create-atlas, harmonize-datasets, resume, run scripts

- id: orchestrators-and-core-types
  title: [Orchestrators And Core Types](codebase.md#orchestrators-and-core-types)
  anchor: orchestrators-and-core-types
  purpose: Responsibilities, dependencies, state ownership, and failure behavior of the main implementation types.
  keywords: Atlas, AtlasCollector, AtlasFilterer, AtlasHarmonizer, CheckpointStore, DevTraceWriter

- id: public-api-reference
  title: [Public API Reference](codebase.md#public-api-reference)
  anchor: public-api-reference
  purpose: Exhaustive exported symbols, supported workflow methods, signatures, outputs, failures, side effects, and sources.
  keywords: exports, __all__, methods, signatures, wrappers, benchmark_ThematicAtlases, CheckpointStore

- id: principal-workflows
  title: [Principal Workflows](codebase.md#principal-workflows)
  anchor: principal-workflows
  purpose: Branch-complete diagrams, stages, pseudocode, and call labels for the eight supported workflows plus the archived-runner tombstone.
  keywords: collection, creation, harmonization, resume, retry, amendment, archive, review, metadata repair, benchmark

- id: extension-and-change-guidance
  title: [Extension And Change Guidance](codebase.md#extension-and-change-guidance)
  anchor: extension-and-change-guidance
  purpose: Supported extension patterns, compatibility impact, tests, docs, and coupling to avoid.
  keywords: extension points, repository adapter, CLI option, checkpoint stage, provider, schema, tests

## Individual interface, decision, type, and workflow routes

- id: repository-capabilities-v1
  title: [Repository capability contract 1.0](codebase.md#repository-capabilities-v1)
  anchor: repository-capabilities-v1
  purpose: Canonical immutable GEO/ArrayExpress grammar, review identity, adapter/provider, harmonization, and end-to-end capability rules.
  keywords: RepositoryCapabilityRegistry, GEO, ArrayExpress, accession grammar, review identity, harmonization support, capability contract 1.0

- id: runtime-contracts-v2
  title: [Runtime status and safe-error contracts](codebase.md#runtime-contracts-v2)
  anchor: runtime-contracts-v2
  purpose: Authoritative status 2.0 axes and persistence-safe error envelope semantics.
  keywords: OperationStatusV2, execution, completeness, evidence confidence, validation, publication disposition, SafeErrorEnvelope, correlation ID

- id: request-policy
  title: [Typed resource and request policy](codebase.md#request-policy)
  anchor: request-policy
  purpose: Standard/large ceilings, explicit overrides, HTTPS/redirect/decoded-response/aggregate boundaries, compressed transport handling, worker limits, and delegated disk preflight.
  keywords: ResourceProfile, standard, large, resource override, 10% headroom, RequestPolicy, HTTPS, redirects, Content-Encoding, Content-Length, compressed response, decoded body, max_xml_bytes, aggregate download, ontology file, not RAM

- id: interface-thematic-atlas-cli
  title: [Installed thematic-atlas CLI](codebase.md#interface-thematic-atlas-cli)
  anchor: interface-thematic-atlas-cli
  purpose: Installed command registration, subcommands, theme-first creation defaults, option forwarding, outputs, and failures.
  keywords: thematic-atlas, collect-datasets, create-atlas, theme, query generation, thematic review, harmonize-datasets, resume, fork-run, stop-after, metadata, argparse

- id: interface-python-atlas
  title: [Python Atlas interface](codebase.md#interface-python-atlas)
  anchor: interface-python-atlas
  purpose: Supported Python import, workflow methods, and specialist package exports.
  keywords: Python, Atlas, import, workflow API, public symbols

- id: interface-focused-runners
  title: [Archived focused runner interfaces](codebase.md#interface-focused-runners)
  anchor: interface-focused-runners
  purpose: Tombstone for removed repository-root runners and route to the canonical GSK adapter workflow.
  keywords: archived, fibrosis, canonical GSK, adapter, local recovery

- id: decision-checkpointed-traces
  title: [Checkpointed trace decision](codebase.md#decision-checkpointed-traces)
  anchor: decision-checkpointed-traces
  purpose: Observed decision to combine readable artifacts with fingerprinted item checkpoints.
  keywords: AD-002, SQLite, checkpoints, fingerprints, retry, trace

- id: decision-shared-publication-texts
  title: [Shared publication text decision](codebase.md#decision-shared-publication-texts)
  anchor: decision-shared-publication-texts
  purpose: Observed normalization of publication text into one referenced shared map.
  keywords: AD-003, publication_texts, publication_text_ref, deduplication

- id: decision-delegated-model-work
  title: [Delegated stage and model work decision](codebase.md#decision-delegated-model-work)
  anchor: decision-delegated-model-work
  purpose: Observed root-orchestrator delegation to stage components and external model packages.
  keywords: AD-001, Atlas, delegation, agentic-curator, components

- id: decision-safe-run-archival
  title: [Verified run archival decision](codebase.md#decision-safe-run-archival)
  anchor: decision-safe-run-archival
  purpose: Observed lock, SQLite checkpoint, stable-snapshot, verification, and atomic-publication rules for whole-run archives.
  keywords: AD-005, archive, activity lock, WAL, SHM, snapshot, checksum, atomic, fsync, ArchiveDurabilityError, symlink

- id: decision-central-atlas-document
  title: [Central Atlas document and run authority](codebase.md#decision-central-atlas-document)
  anchor: decision-central-atlas-document
  purpose: Observed Atlas v1 public-boundary, normalized lifecycle authority, and fail-closed compatibility decision.
  keywords: AD-006, AtlasDocument, AtlasDocumentAdapter, atlas_run.sqlite3, single database, v1, legacy unversioned

- id: type-atlas
  title: [Atlas orchestrator](codebase.md#type-atlas)
  anchor: type-atlas
  purpose: Root workflow ownership and delegation to injected stage and run-lifecycle collaborators.
  keywords: Atlas, create_atlas, collect_datasets, resume, harmonize, AtlasRunLifecycle, dependency injection

- id: type-atlas-run-lifecycle
  title: [AtlasRunLifecycle](codebase.md#type-atlas-run-lifecycle)
  anchor: type-atlas-run-lifecycle
  purpose: Run identity, status aggregation, public exact resume selection, checkpoint-contract reconciliation, archival, and resumed publication.
  keywords: AtlasRunLifecycle, resolve_resume_run_directory, run ID, resume directory, checkpoint contract, publication, archive

- id: type-atlas-document
  title: [AtlasDocument v1](codebase.md#type-atlas-document)
  anchor: type-atlas-document
  purpose: Versioned domain dataclasses, owner-produced golden fixture, strict validation, deterministic JSON, cross-reference invariants, and preservation of MSC-owned MINiML package metadata.
  keywords: AtlasDocument, schema_version, miniml_schema_version, MINiMLPackage, metadata, golden fixture, downstream contract, dataclass, codec, validation, atomic JSON

- id: type-atlas-document-service
  title: [AtlasDocumentService](codebase.md#type-atlas-document-service)
  anchor: type-atlas-document-service
  purpose: Application use case for Atlas v1 assembly, internal projection, summary derivation, and publication.
  keywords: AtlasDocumentService, application, assemble, to_legacy, summary, publish

- id: type-atlas-ports
  title: [Atlas application ports](codebase.md#type-atlas-ports)
  anchor: type-atlas-ports
  purpose: Runtime-checkable collaborator protocols and dependency direction for extensible application composition.
  keywords: CollectorPort, FiltererPort, HarmonizerPort, ArtifactPublisherPort, Protocol, dependency injection

- id: type-atlas-document-adapter
  title: [AtlasDocumentAdapter](codebase.md#type-atlas-document-adapter)
  anchor: type-atlas-document-adapter
  purpose: Internal anti-corruption boundary for strict Atlas v1 projection, lossless MINiML metadata transport, evidence envelopes, and provider harmonization targets.
  keywords: AtlasDocumentAdapter, assemble, to_legacy, accessions, MSC MINiML 2.0, canonical JSON, strict validation, publication_texts, annotations, ontology_lookup, v1 projection

- id: type-atlas-run-store
  title: [AtlasRunStore](codebase.md#type-atlas-run-store)
  anchor: type-atlas-run-store
  purpose: Versioned normalized Atlas v1 run, stage, work, attempt, metadata, artifact, and event persistence.
  keywords: AtlasRunStore, atlas_run.sqlite3, schema version 2, work_items, attempts, run_metadata, triggers, artifacts, events

- id: type-json-artifact-bundle-publisher
  title: [JsonArtifactBundlePublisher](codebase.md#type-json-artifact-bundle-publisher)
  anchor: type-json-artifact-bundle-publisher
  purpose: Crash-durable immutable JSON generations, atomic current pointer, compatibility views, recovery, and resolution.
  keywords: JsonArtifactBundlePublisher, generation, current.json, fsync, manifest, compatibility, recovery, atomic

- id: type-atlas-collector
  title: [AtlasCollector](codebase.md#type-atlas-collector)
  anchor: type-atlas-collector
  purpose: Discovery, repository routing, metadata collection, and metadata-resume ownership.
  keywords: AtlasCollector, TraceMetadataResumer, GEO, ArrayExpress

- id: type-publication-text-reviewer
  title: [Publication text review types](codebase.md#type-publication-text-reviewer)
  anchor: type-publication-text-reviewer
  purpose: Text mapping, generic theme-derived review dispatch, filtering, trace persistence, and independent-review ownership.
  keywords: AtlasFilterer, PublicationTextReviewer, TracePublicationReviewResumer, criteria, exclusion_basis, grounded evidence, accessions_to_remove, prune_accessions, review revision 3, contract version 7

- id: type-atlas-harmonizer
  title: [AtlasHarmonizer](codebase.md#type-atlas-harmonizer)
  anchor: type-atlas-harmonizer
  purpose: Eligible metadata selection, work caching, provider delegation, and fallback behavior.
  keywords: AtlasHarmonizer, ontology, work key, execution identity, model, prompt digest, embedding, ontology source, checkpoint invalidation, degraded, details

- id: type-checkpoint-store
  title: [CheckpointStore](codebase.md#type-checkpoint-store)
  anchor: type-checkpoint-store
  purpose: SQLite schema, fingerprints, item history, retry selection, and comparison archives.
  keywords: CheckpointStore, SQLite, request_retries, atomic batch, status index, history index, item lock

- id: type-europe-pmc-wrapper
  title: [EuropePMCWrapper](codebase.md#type-europe-pmc-wrapper)
  anchor: type-europe-pmc-wrapper
  purpose: Europe PMC network boundary with injected pure publication identity, limit, merge, deduplication, and projection policy.
  keywords: EuropePMCWrapper, PublicationRecordPolicy, search, datalinks, fullTextXML, abstract, identity, deduplication

- id: type-geo-wrapper
  title: [GEOWrapper](codebase.md#type-geo-wrapper)
  anchor: type-geo-wrapper
  purpose: GEO network/enrichment boundary with injected canonical package projection and deterministic GSE record policy.
  keywords: GEOWrapper, GEORecordPolicy, NCBI, GEO, MINiML, projection, deduplication, SRA, ENA

- id: type-fibrosis-meta-pubs-recall-benchmark
  title: [Fibrosis meta-publication recall benchmark](codebase.md#type-fibrosis-meta-pubs-recall-benchmark)
  anchor: type-fibrosis-meta-pubs-recall-benchmark
  purpose: Direct offline trace/CSV runner with aggregate and per-reference-set exact DOI/PMID recall.
  keywords: benchmark_fibrosis_meta_pubs_recall, CSV, trace, DOI, PMID, aggregate, recall

- id: workflow-collection
  title: [Collection workflow](codebase.md#workflow-collection)
  anchor: workflow-collection
  purpose: Query validation and resolution through discovery, metadata routing, text mapping, review, provenance, and atlas output.
  keywords: collection, query, resolved_queries, provenance, datalink, full text, unsupported accessions, metadata handler status, review, empty result

- id: workflow-atlas-creation
  title: [Atlas creation workflow](codebase.md#workflow-atlas-creation)
  anchor: workflow-atlas-creation
  purpose: Theme-first query generation/review, collection, harmonization, Atlas v1 assembly, rollback-safe bundle publication, normalized tracing, and outputs.
  keywords: create_atlas, required theme, generated queries, thematic_review, AtlasDocumentAdapter, JsonArtifactBundlePublisher, unsupported inventory, atlas_run.sqlite3, summary, rollback, trace

- id: workflow-harmonization
  title: [Harmonization workflow](codebase.md#workflow-harmonization)
  anchor: workflow-harmonization
  purpose: Eligible work selection, memoization, adapter controls, checkpoint replay, ontology calls, fallback, and details.
  keywords: harmonization, work key, execution identity, model, prompt digest, embedding, ontology source, checkpoint invalidation, controls, terminal, retryable, status 2.0, not_run, degraded, failed, safe error

- id: workflow-resume-and-retry
  title: [Resume and retry workflow](codebase.md#workflow-resume-and-retry)
  anchor: workflow-resume-and-retry
  purpose: Trace selection, fingerprint validation, selective requeue, reuse, and continuation.
  keywords: resume, retry-stage, retry-item, degraded, metadata pause, fork-run, CheckpointStore

- id: workflow-query-amendment-and-archive
  title: [Query amendment and archive workflow](codebase.md#workflow-query-amendment-and-archive)
  anchor: workflow-query-amendment-and-archive
  purpose: Safe query-fingerprint replacement and stable durable-snapshot whole-run relocation.
  keywords: amend_queries, archive_existing_runs, checkpoint, WAL, snapshot, checksum, activity lock

- id: workflow-independent-review
  title: [Independent review workflow](codebase.md#workflow-independent-review)
  anchor: workflow-independent-review
  purpose: Stable-snapshot text collection, review_relevancy dispatch, checkpointing, and progress.
  keywords: publication reviewer, TracePublicationReviewResumer, review_relevancy, reviewer identity, provider, model, generation, prompt digest, direct

- id: workflow-metadata-repair
  title: [Metadata resume, audit, and repair workflow](codebase.md#workflow-metadata-repair)
  anchor: workflow-metadata-repair
  purpose: Default metadata resume, offline audit, explicit tag repair, and checkpoint reuse.
  keywords: metadata worker, audit-enrichment-only, retry-tags, GEO, repair summary, partial, safe error

- id: workflow-fixed-runners
  title: [Archived fixed fibrosis runners](codebase.md#workflow-fixed-runners)
  anchor: workflow-fixed-runners
  purpose: Historical workflow boundary, retained assets, and canonical adapter replacement.
  keywords: archived, fibrosis, canonical GSK, retained theme, query catalog

- id: workflow-benchmarking
  title: [Benchmarking workflow](codebase.md#workflow-benchmarking)
  anchor: workflow-benchmarking
  purpose: Offline exact recall from a trace directory and one combined packaged or custom CSV.
  keywords: benchmark, offline, trace directory, CSV, DOI, PMID, exact match, report

## Detailed and legacy-stable routes

- id: project-purpose-and-layout
  title: [Project Purpose And Layout](codebase.md#project-purpose-and-layout)
  anchor: project-purpose-and-layout
  purpose: Detailed package, interface, documentation, and test layout.
  keywords: purpose, layout, src, docs, tests, collector, filterer, harmonizer, wrappers

- id: runtime-and-packaging
  title: [Runtime And Packaging](codebase.md#runtime-and-packaging)
  anchor: runtime-and-packaging
  purpose: Python, setuptools, exact-platform hashed runtime lock, deterministic CycloneDX SBOM, fail-closed release evidence, independent v1 dependencies, editable install, tests, and console command.
  keywords: pyproject, Python 3.10, version 3.0.0, pylock, SHA-256, CycloneDX, SBOM, advisory snapshot, signed artifact, security SLA, MSC MINiML 2.0, pytest, thematic-atlas

- id: public-api
  title: [Public API Route](codebase.md#public-api)
  anchor: public-api
  purpose: Preserved compatibility route for the package-root and Atlas import guidance.
  keywords: Atlas import, __version__, agentic-curator, archive_existing_runs

- id: live-api-provider-contracts
  title: [Live API Provider Contracts](codebase.md#live-api-provider-contracts)
  anchor: live-api-provider-contracts
  purpose: Owns opt-in Europe PMC, bioRxiv, and GEO provider checks.
  keywords: live_api, Europe PMC, bioRxiv, GEO, host allowlist, no retries

- id: benchmark-package
  title: [Benchmark Package](codebase.md#benchmark-package)
  anchor: benchmark-package
  purpose: Combined fibrosis reference CSV, direct runner, exact matching, aggregate/per-set reports, and generated output policy.
  keywords: benchmark_fibrosis_meta_pubs_recall, CSV, DOI, PMID, reference set, aggregate, recall, conflict, benchmarks directory

- id: fibrosis-curation-theme
  title: [Fibrosis Curation Theme](codebase.md#fibrosis-curation-theme)
  anchor: fibrosis-curation-theme
  purpose: Fixed fibrosis scope, inclusion concepts, and review expectations.
  keywords: fibrosis, theme_fibrosis, transcriptomics, human, review-filter

- id: fibrosis-run-script
  title: [Archived Fibrosis Run Scripts](codebase.md#fibrosis-run-script)
  anchor: fibrosis-run-script
  purpose: Archive record and redirect to the canonical GSK workflow, with retained theme and query references.
  keywords: archived, canonical GSK, fibrosis, query catalog, theme

- id: cli-atlas
  title: [CLI Atlas](codebase.md#cli-atlas)
  anchor: cli-atlas
  purpose: Parser wiring, commands, options, logging precedence, and output behavior.
  keywords: argparse, collect-datasets, create-atlas, harmonize-datasets, resume, logging

- id: archive-reference
  title: [Archive Reference](codebase.md#archive-reference)
  anchor: archive-reference
  purpose: Clarifies that no source archive is tracked and distinguishes ignored resumable run archives.
  keywords: archive, previous_runs, runtime artifacts, version control, resumable

- id: test-and-verification-status
  title: [Test And Verification Status](codebase.md#test-and-verification-status)
  anchor: test-and-verification-status
  purpose: Current automated coverage and verification commands.
  keywords: pytest, 541 passed, 4 skipped, py_compile, mocked network, documentation, CLI, workflows

- id: atlas-workflow
  title: [Atlas Workflow](codebase.md#atlas-workflow)
  anchor: atlas-workflow
  purpose: Detailed Atlas signatures, tracing, resume, retries, amendments, outputs, and archival.
  keywords: Atlas, create_atlas, collect_datasets, harmonize_datasets, resume, retry, amend_queries

- id: collector
  title: [Collector](codebase.md#collector)
  anchor: collector
  purpose: Discovery, repository routing, metadata collection, independent resume, and repair detail.
  keywords: AtlasCollector, TraceMetadataResumer, metadata_repository, GEO, ArrayExpress, retry tags

- id: filterer
  title: [Filterer](codebase.md#filterer)
  anchor: filterer
  purpose: Publication text mapping, direct and legacy review, filtering, and independent resume detail.
  keywords: AtlasFilterer, PublicationTextReviewer, review_strategy, publication_text_ref, review_filter

- id: harmonizer
  title: [Harmonizer](codebase.md#harmonizer)
  anchor: harmonizer
  purpose: Ontology workflow controls, work-key caching, degradation, concurrency, and fallback detail.
  keywords: AtlasHarmonizer, local_rag_ols, OperationStatusV2, degraded_stages, preferred ontology

- id: epmc-wrapper
  title: [Europe PMC Wrapper](codebase.md#epmc-wrapper)
  anchor: epmc-wrapper
  purpose: Search, pagination, deduplication, XML-primary datalinks with bounded JSON fallback, publication text, checkpoint, and endpoint detail.
  keywords: EuropePMCWrapper, search, datalinks, XML primary, JSON fallback, Scholix, fail closed, fullTextXML, preprintJATSXML, bioRxiv, medRxiv, accession extraction, abstract_regex, max_publications_per_query

- id: fulltext-accession-discovery
  title: [Publication-text Accession Discovery](codebase.md#fulltext-accession-discovery)
  anchor: fulltext-accession-discovery
  purpose: Default-on deterministic publication-text accession extraction, registry families, provenance merging, checkpointing, and repository filtering.
  keywords: scrape_fulltext_accessions, fulltext_regex, abstract_regex, preprint JATS, discovery_sources, GEO, ArrayExpress, BioStudies, BioProject, INSDC, BioSample

- id: rate-handling
  title: [Rate Handling](codebase.md#rate-handling)
  anchor: rate-handling
  purpose: Shared injectable HTTP policy for profile timeouts, egress/redirect/body/aggregate ceilings, endpoint cadence, bounded retry, and Retry-After behavior.
  keywords: RequestPolicy, ResourceProfile, HTTPS, host allowlist, redirects, aggregate bytes, retry, Retry-After, HTTP-date, bounded delay, timeout, EuropePMCWrapper, GEOWrapper

- id: arrayexpress-wrapper
  title: [ArrayExpress Wrapper](codebase.md#arrayexpress-wrapper)
  anchor: arrayexpress-wrapper
  purpose: In-memory BioStudies MAGE-TAB collection through the strict MSC MINiML 2.0 transport boundary, versioned checkpoints, and offline availability overlay.
  keywords: ArrayExpressWrapper, E-MTAB, E-GEOD, E-MEXP, BioStudies, ae2json, MINiMLPackage, series.protocols, series.assay_paths, checkpoint version 2, arrayexpress_metadata

- id: geo-wrapper
  title: [GEO Wrapper](codebase.md#geo-wrapper)
  anchor: geo-wrapper
  purpose: GEO normalization, NCBI lookup, MINiML conversion, enrichment, checkpoints, repair, and record shape.
  keywords: GEOWrapper, GSE, GSM, GDS, GPL, NCBI, MINiML, PubMed, SRA, ENA

- id: operational-events-v1
  title: [Operational Events V1](codebase.md#operational-events-v1)
  anchor: operational-events-v1
  purpose: Shared redacted event envelope, SQLite authority, JSONL/logging sinks, and JSON/Prometheus metric export.
  keywords: OperationalEventEmitter, schema 1.0, JSONL, structured logging, redaction, metrics, Prometheus, AtlasRunStore

- id: resume-dependency-wiring
  title: [Resume Dependency Wiring](codebase.md#resume-dependency-wiring)
  anchor: resume-dependency-wiring
  purpose: One-way injected factory registration that removes collector/filterer mutual and method-local imports.
  keywords: TraceMetadataResumer, TracePublicationReviewResumer, dependency direction, factory, import cycle, injection
