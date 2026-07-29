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
  keywords: Europe PMC, NCBI, ENA, Google ADC, agentic-curator, meta-standards-converter, SQLite, privacy

- id: architectural-decisions
  title: [Architectural Decisions](codebase.md#architectural-decisions)
  anchor: architectural-decisions
  purpose: Evidence-safe documented and observed design choices, consequences, and affected components.
  keywords: AD-001, AD-002, AD-003, AD-004, observed, documented, rationale, decisions

- id: design-invariants-and-expectations
  title: [Design Invariants And Expectations](codebase.md#design-invariants-and-expectations)
  anchor: design-invariants-and-expectations
  purpose: Compatibility, ordering, validation, state, retry, archive, logging, and privacy rules future changes must preserve.
  keywords: query order, publication_text_ref, fingerprint, retryable, terminal, archive, logging, schema

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
  purpose: Branch-complete diagrams, stages, pseudocode, and call labels for all nine production workflows.
  keywords: collection, creation, harmonization, resume, retry, amendment, archive, review, metadata repair, runners, benchmark

- id: extension-and-change-guidance
  title: [Extension And Change Guidance](codebase.md#extension-and-change-guidance)
  anchor: extension-and-change-guidance
  purpose: Supported extension patterns, compatibility impact, tests, docs, and coupling to avoid.
  keywords: extension points, repository adapter, CLI option, checkpoint stage, provider, schema, tests

## Individual interface, decision, type, and workflow routes

- id: interface-thematic-atlas-cli
  title: [Installed thematic-atlas CLI](codebase.md#interface-thematic-atlas-cli)
  anchor: interface-thematic-atlas-cli
  purpose: Installed command registration, subcommands, option forwarding, outputs, and failures.
  keywords: thematic-atlas, collect-datasets, create-atlas, harmonize-datasets, resume, argparse

- id: interface-python-atlas
  title: [Python Atlas interface](codebase.md#interface-python-atlas)
  anchor: interface-python-atlas
  purpose: Supported Python import, workflow methods, and specialist package exports.
  keywords: Python, Atlas, import, workflow API, public symbols

- id: interface-focused-runners
  title: [Focused runner interfaces](codebase.md#interface-focused-runners)
  anchor: interface-focused-runners
  purpose: Directly executable repository scripts and their fixed workflow contracts.
  keywords: run_fibrosis_atlas, run_fibrosis_discovery, reviewer, metadata collector, benchmark

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
  purpose: Observed lock, verification, and atomic-publication rules for whole-run archives.
  keywords: AD-005, archive, activity lock, checksum, atomic, symlink

- id: type-atlas
  title: [Atlas orchestrator](codebase.md#type-atlas)
  anchor: type-atlas
  purpose: Root workflow ownership, dependency injection, output, resume, and archive responsibilities.
  keywords: Atlas, create_atlas, collect_datasets, resume, harmonize

- id: type-atlas-collector
  title: [AtlasCollector](codebase.md#type-atlas-collector)
  anchor: type-atlas-collector
  purpose: Discovery, repository routing, metadata collection, and metadata-resume ownership.
  keywords: AtlasCollector, TraceMetadataResumer, GEO, ArrayExpress

- id: type-publication-text-reviewer
  title: [Publication text review types](codebase.md#type-publication-text-reviewer)
  anchor: type-publication-text-reviewer
  purpose: Text mapping, review dispatch, filtering, and independent-review ownership.
  keywords: AtlasFilterer, PublicationTextReviewer, TracePublicationReviewResumer

- id: type-atlas-harmonizer
  title: [AtlasHarmonizer](codebase.md#type-atlas-harmonizer)
  anchor: type-atlas-harmonizer
  purpose: Eligible metadata selection, work caching, provider delegation, and fallback behavior.
  keywords: AtlasHarmonizer, ontology, work key, degraded, details

- id: type-checkpoint-store
  title: [CheckpointStore](codebase.md#type-checkpoint-store)
  anchor: type-checkpoint-store
  purpose: SQLite schema, fingerprints, item history, retry selection, and comparison archives.
  keywords: CheckpointStore, SQLite, request_retries, history, item lock

- id: type-europe-pmc-wrapper
  title: [EuropePMCWrapper](codebase.md#type-europe-pmc-wrapper)
  anchor: type-europe-pmc-wrapper
  purpose: Europe PMC search, datalink, text, retry, fallback, and normalization boundary.
  keywords: EuropePMCWrapper, search, datalinks, fullTextXML, abstract

- id: type-geo-wrapper
  title: [GEOWrapper](codebase.md#type-geo-wrapper)
  anchor: type-geo-wrapper
  purpose: GEO resolution, MINiML metadata, enrichment, checkpoint, and repair boundary.
  keywords: GEOWrapper, NCBI, GEO, MINiML, SRA, ENA

- id: type-thematic-reviewer-benchmark
  title: [ThematicReviewerBenchmark](codebase.md#type-thematic-reviewer-benchmark)
  anchor: type-thematic-reviewer-benchmark
  purpose: Offline exact DOI/PMID comparison and reference-set validation.
  keywords: ThematicReviewerBenchmark, DOI, PMID, recall, reference set

- id: workflow-collection
  title: [Collection workflow](codebase.md#workflow-collection)
  anchor: workflow-collection
  purpose: Query validation through discovery, metadata routing, text mapping, review, and atlas output.
  keywords: collection, query, datalink, metadata, review, empty result

- id: workflow-atlas-creation
  title: [Atlas creation workflow](codebase.md#workflow-atlas-creation)
  anchor: workflow-atlas-creation
  purpose: End-to-end collection, harmonization, output, summary, details, and tracing.
  keywords: create_atlas, preflight, cache, summary, trace

- id: workflow-harmonization
  title: [Harmonization workflow](codebase.md#workflow-harmonization)
  anchor: workflow-harmonization
  purpose: Eligible work selection, memoization, ontology calls, fallback, and details.
  keywords: harmonization, work key, ontology, not_run, degraded, error

- id: workflow-resume-and-retry
  title: [Resume and retry workflow](codebase.md#workflow-resume-and-retry)
  anchor: workflow-resume-and-retry
  purpose: Trace selection, fingerprint validation, selective requeue, reuse, and continuation.
  keywords: resume, retry-stage, retry-item, degraded, CheckpointStore

- id: workflow-query-amendment-and-archive
  title: [Query amendment and archive workflow](codebase.md#workflow-query-amendment-and-archive)
  anchor: workflow-query-amendment-and-archive
  purpose: Safe query-fingerprint replacement and verified whole-run relocation.
  keywords: amend_queries, archive_existing_runs, checksum, activity lock

- id: workflow-independent-review
  title: [Independent review workflow](codebase.md#workflow-independent-review)
  anchor: workflow-independent-review
  purpose: Stable-snapshot text collection, review_relevancy dispatch, checkpointing, and progress.
  keywords: publication reviewer, TracePublicationReviewResumer, review_relevancy

- id: workflow-metadata-repair
  title: [Metadata resume, audit, and repair workflow](codebase.md#workflow-metadata-repair)
  anchor: workflow-metadata-repair
  purpose: Default metadata resume, offline audit, explicit tag repair, and checkpoint reuse.
  keywords: metadata worker, audit-enrichment-only, retry-tags, GEO

- id: workflow-fixed-runners
  title: [Fixed fibrosis runner workflow](codebase.md#workflow-fixed-runners)
  anchor: workflow-fixed-runners
  purpose: Full-atlas and discovery-only configuration, limits, resume, retries, and artifacts.
  keywords: fibrosis, 50000, static queries, generated queries, .out

- id: workflow-benchmarking
  title: [Benchmarking and reference-review workflow](codebase.md#workflow-benchmarking)
  anchor: workflow-benchmarking
  purpose: Offline exact recall and checkpointed live reference-review diagnostics.
  keywords: benchmark, reference review, DOI, PMID, exact match

## Detailed and legacy-stable routes

- id: project-purpose-and-layout
  title: [Project Purpose And Layout](codebase.md#project-purpose-and-layout)
  anchor: project-purpose-and-layout
  purpose: Detailed package, runner, documentation, and test layout.
  keywords: purpose, layout, src, docs, tests, collector, filterer, harmonizer, wrappers

- id: runtime-and-packaging
  title: [Runtime And Packaging](codebase.md#runtime-and-packaging)
  anchor: runtime-and-packaging
  purpose: Python, setuptools, dependency, editable-install, and console-command contract.
  keywords: pyproject, Python 3.10, requirements, dependencies, pytest, thematic-atlas

- id: public-api
  title: [Legacy Public API Route](codebase.md#public-api)
  anchor: public-api
  purpose: Preserved compatibility route for the package-root and Atlas import guidance.
  keywords: Atlas import, empty __init__, agentic-curator, archive_existing_runs

- id: benchmark-package
  title: [Benchmark Package](codebase.md#benchmark-package)
  anchor: benchmark-package
  purpose: Reference-set schemas, exact matching, reports, runners, and packaged fixtures.
  keywords: ThematicReviewerBenchmark, DOI, PMID, reference set, recall, conflict, fixtures

- id: fibrosis-curation-theme
  title: [Fibrosis Curation Theme](codebase.md#fibrosis-curation-theme)
  anchor: fibrosis-curation-theme
  purpose: Fixed fibrosis scope, inclusion concepts, and review expectations.
  keywords: fibrosis, theme_fibrosis, transcriptomics, human, review-filter

- id: fibrosis-run-script
  title: [Fibrosis Run Scripts](codebase.md#fibrosis-run-script)
  anchor: fibrosis-run-script
  purpose: Full-atlas and discovery-only fixed configuration, resume, amendment, archival, and artifacts.
  keywords: run_fibrosis_atlas.py, run_fibrosis_discovery.py, query catalog, OntoStore, .out

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
  keywords: pytest, py_compile, mocked network, documentation, CLI, workflows

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
  keywords: AtlasHarmonizer, local_rag_ols, quality_status, degraded_stages, preferred ontology

- id: epmc-wrapper
  title: [Europe PMC Wrapper](codebase.md#epmc-wrapper)
  anchor: epmc-wrapper
  purpose: Search, pagination, deduplication, datalinks, full text, fallback, checkpoint, and endpoint detail.
  keywords: EuropePMCWrapper, search, datalinks, fullTextXML, abstract, max_publications_per_query

- id: rate-handling
  title: [Rate Handling](codebase.md#rate-handling)
  anchor: rate-handling
  purpose: Remote request cadence, retry, timeout, and Retry-After behavior.
  keywords: retry, Retry-After, timeout, request_delay, page_limit

- id: arrayexpress-wrapper
  title: [ArrayExpress Wrapper](codebase.md#arrayexpress-wrapper)
  anchor: arrayexpress-wrapper
  purpose: Current placeholder behavior and record status contract for ArrayExpress accessions.
  keywords: ArrayExpressWrapper, E-MTAB, E-GEOD, metadata_status, placeholder

- id: geo-wrapper
  title: [GEO Wrapper](codebase.md#geo-wrapper)
  anchor: geo-wrapper
  purpose: GEO normalization, NCBI lookup, MINiML conversion, enrichment, checkpoints, repair, and record shape.
  keywords: GEOWrapper, GSE, GSM, GDS, GPL, NCBI, MINiML, PubMed, SRA, ENA
