# codebase.md Index

Stable anchors route into `docs/codebase.md`. Read this file first, choose the relevant section id or keyword, then retrieve only the anchored section.

Agent retrieval template:

```bash
$HOME/.codex/retrieve_codebase_section.py --id <section-id>
```

Use `--query <keyword>` when the section id is not known. Anchors are stable and do not require index maintenance when surrounding text changes.

## Main Sections

- id: project-purpose-and-layout
  title: Project Purpose And Layout
  anchor: project-purpose-and-layout
  keywords: purpose, layout, src, docs, tests, package files, collector, filterer, harmonizer, wrappers, ae, arrayexpress

- id: runtime-and-packaging
  title: Runtime And Packaging
  anchor: runtime-and-packaging
  keywords: pyproject, requirements.txt, setuptools, version, agentic-curator, google-auth, requests, meta_standards_converter, dependencies, pytest, editable install, console script, thematic-atlas

- id: public-api
  title: Public API
  anchor: public-api
  keywords: import, __init__, exports, Atlas, archive_existing_runs, whole-run archive, directly resumable archive, agentic_curator, agentic-curator, ThematicReviewer, theme, collect_datasets, no ThematicAtlases.curator, no curator CLI, separate package

- id: benchmark-package
  title: Benchmark Package
  anchor: benchmark-package
  keywords: benchmark_ThematicAtlases, thematic_reviewer, ontology_harmonizer, ThematicReviewerBenchmark, benchmark_reference_publication_recall, available_reference_sets, load_reference_set, leonie_2026_fibrosis, taylor_2020_nafld_fibrosis, run_reference_publication_recall.py, run_reference_set_review.py, exact DOI resolution, GEO-linked reference review, reference audit, aggregate report, reference-set-file, custom reference set, packaged JSON, reference set, publication recall, golden example, complete input output, mixed outcomes, DOI, PMID, statistics, atlas output, dev trace, resume_review_progress, reviewed datasets, discovery recall, relevant recall, candidate recall, judgement counts, duplicate publications, conflicts

- id: fibrosis-curation-theme
  title: Fibrosis Curation Theme
  anchor: fibrosis-curation-theme
  keywords: fibrosis, theme_fibrosis, human, bulk, single-cell, single-nucleus, spatial, transcriptomics, comprehensive query, AND concepts, OR synonyms, unbridgeable gap, relevant, unsure, not relevant, induced model, controls, review-filter

- id: fibrosis-run-script
  title: Fibrosis Run Script
  anchor: fibrosis-run-script
  keywords: run_fibrosis_atlas.py, run_fibrosis_discovery.py, config/fibrosis_discovery_queries.json, query catalog, discovery only, collection only, stop before review, publication text snapshot, separate reviewer, static query, complementary queries, per-query limits, cross-query deduplication, --amend-queries, query archive, automatic whole-run archive, previous_runs, workflow activity lock, orphan artifacts, --generate-query, LLM query generation, no harmonization, --resume, resume_state.sqlite, incremental resume, DEBUG, verbose, safe telemetry, periodic progress, request duration, full run, max publications, GEO, dev trace, checkpoints, OntoStore, snomed, ADC, .env, .out, summary

- id: cli-atlas
  title: CLI Atlas
  anchor: cli-atlas
  keywords: cli_atlas, argparse, query, file, query-generator, max-generated-queries, method-owned generation, out, create-atlas, collect-datasets, harmonize-datasets, metadata-repository, theme, review-filter, review-strategy, direct, evidence_then_judgement, dev-trace, summary, logging

- id: archive-reference
  title: Archive Reference
  anchor: archive-reference
  keywords: oldd, archive, reference, porting

- id: test-and-verification-status
  title: Test And Verification Status
  anchor: test-and-verification-status
  keywords: tests, fixtures, golden report, complete benchmark example, py_compile, pytest, .env, smoke check, mocked network, README, documentation, atlas orchestration, collector, query generator, query ordering, repository selection, arrayexpress, filterer, harmonizer, publication text, section parsing, thematic review, filterer.review, GEO wrapper, atlas CLI

## API Sections

- id: atlas-workflow
  title: Atlas Workflow
  anchor: atlas-workflow
  keywords: Atlas, resume, stop_before_review, collection-only resume, resume_publication_collection, review_before_metadata, resume_metadata_enriched_datasets, resume_state.sqlite, CheckpointStore, archive_existing_runs, whole-run archive, archive_stage, archive_items, selected checkpoint keys, comparison archive, archive id, archive manifest, SHA-256, workflow activity lock, previous_runs, directly resumable, retryable_error, terminal_error, run fingerprint, orchestrator, dependency injection, query_generator, credential_checker, ontostore, cache_ontologies, cache_all, force_frameworks, streaming OWL, SQLite staging, eager ontology cache, generate_queries, max_generated_queries, harmonization_options, create_atlas, collect_datasets, harmonize_datasets, summary, dev trace, checkpoints

- id: collector
  title: Collector
  anchor: collector
  keywords: AtlasCollector, query loading, collect_jsons, collect_metadata, skip metadata, resume_metadata, TraceMetadataResumer, run_accession_metadata_collector.py, resume_metadata_progress, resume_metadata.log, metadata logging, checkpoint stats, metadata snapshot, concurrent metadata, EuropePMCWrapper, collect_accessions, max_publications, filter_accessions, is_handled_accession, collect_accession_metadata, metadata_repository, metadata_handler, metadata_repositories, GEO, GSE, GSM, GDS, GPL, arrayexpress, E-MTAB, E-GEOD, E-MEXP, original_datalinks, accession_metadata

- id: filterer
  title: Filterer
  anchor: filterer
  keywords: AtlasFilterer, internal filter_jsons, collect_datasets, atlas_parts, publication_texts, publication_text_ref, compact metadata context, metadata_context, metadata coverage, metadata-aware rereview, build_miniml_metadata_context, GSE accessions, direct review, review_revision, revision 2, low confidence uncertain, accession assessments, human samples, transcriptomics assay, established fibrosis, accession linkage, derived judgement, contract version 4, evidence_then_judgement, review_strategy, theme override, allow_theme_override, allow-theme-override, accession exclusions, trace only, PublicationTextReviewer, PublicationTextReviewer.resume, TracePublicationReviewResumer, run_publication_reviewer.py, incremental review, strategy checkpoint, active trace, datalink checkpoint snapshot, resume_review_progress, item lock, filterer.review, agentic_curator, thematic reviewer, review_filter, not_relevant, unsure, abstractText, fullTextXML, text_source, fallback

- id: harmonizer
  title: Harmonizer
  anchor: harmonizer
  keywords: AtlasHarmonizer, OntologyHarmonizer, OntoStore, harmonization_options, max_workers, memoization, credential preflight, ArrayExpress no-call, accession_metadata, failure isolation

- id: epmc-wrapper
  title: EuropePMC Wrapper
  anchor: epmc-wrapper
  keywords: EuropePMCWrapper, collect_accessions, collect_publications, max_publications, max_publications_per_query, multiple queries, publication provenance, cross-query deduplication, collect_publication_texts, collect_datalinks, search_pages, datalinks, publication_text, SQLite checkpoint, first every tenth final, periodic progress, request duration, DEBUG, fullTextXML, abstract fallback, deduplicate, publication_texts, XML fallback, failed publications, stats logs, search stats

- id: rate-handling
  title: Rate Handling
  anchor: rate-handling
  keywords: rate limits, retry, Retry-After, timeout, page_limit, page_size, request_delay, 0.5-second cadence, explicit override

- id: arrayexpress-wrapper
  title: ArrayExpress Wrapper
  anchor: arrayexpress-wrapper
  keywords: ArrayExpressWrapper, arrayexpress, placeholder, metadata_repository, metadata_source, metadata_status, accession_metadata, E-MTAB, E-GEOD, E-MEXP

- id: geo-wrapper
  title: GEO Wrapper
  anchor: geo-wrapper
  keywords: GEOWrapper, collect_accession_metadata, get_gse, GSE, GSM, GDS, GPL, GSE normalization, MINiML JSON, geo2json, related_series, metadata_status, accession_metadata, NCBI E-utilities, ESearch, ESummary, api_key, tool, email, progress logs, stats logs, debug logs
