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
  purpose: Historical source boundary and porting warning.
  keywords: oldd, archive, reference, porting

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
