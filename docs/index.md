# codebase.md Index

Ranges point into `docs/codebase.md`. Read this file first, choose relevant section ids, then retrieve only those ranges.

Agent retrieval template:

```bash
sed -n '<Lines>p' docs/codebase.md
```

Example:

```bash
sed -n '102,183p' docs/codebase.md
```

Refresh ranges after editing `docs/codebase.md`.

## Main Sections

- id: project-purpose-and-layout
  title: Project Purpose And Layout
  lines: 14-70
  anchor: project-purpose-and-layout
  keywords: purpose, layout, src, docs, tests, package files, collector, filterer, harmonizer, wrappers, ae, arrayexpress

- id: runtime-and-packaging
  title: Runtime And Packaging
  lines: 72-83
  anchor: runtime-and-packaging
  keywords: pyproject, setuptools, version, agentic-curator, requests, meta_standards_converter, dependencies, pytest, console script, thematic-atlas

- id: public-api
  title: Public API
  lines: 85-102
  anchor: public-api
  keywords: import, __init__, exports, Atlas, agentic_curator, agentic-curator, ThematicReviewer, theme, collect_datasets, no ThematicAtlases.curator, no curator CLI, separate package

- id: cli-atlas
  title: CLI Atlas
  lines: 414-432
  anchor: cli-atlas
  keywords: cli_atlas, argparse, query, file, query-generator, QueryGenerator, generated queries, agentic_curator, max_queries, out, create-atlas, collect-datasets, harmonize-datasets, skip-metadata, dev-out-dir, no-dev-output, metadata-repository, max-publications, geo, arrayexpress, theme, theme-file, review-filter, not-relevant, unsure, publication_texts, .env, verbose, log-file, after subcommand, stdout logging, progress logs, stats logs, debug logs, quiet stdout

- id: archive-reference
  title: Archive Reference
  lines: 434-439
  anchor: archive-reference
  keywords: oldd, archive, reference, porting

- id: test-and-verification-status
  title: Test And Verification Status
  lines: 441-459
  anchor: test-and-verification-status
  keywords: tests, py_compile, pytest, .env, smoke check, mocked network, README, documentation, atlas orchestration, collector, query generator, query ordering, repository selection, arrayexpress, filterer, harmonizer, publication text, section parsing, thematic review, filterer.review, GEO wrapper, atlas CLI

## API Sections

- id: atlas-workflow
  title: Atlas Workflow
  lines: 104-118
  anchor: atlas-workflow
  keywords: Atlas, orchestrator, dependency injection, collector, filterer, harmonizer, epmc_wrapper_factory, metadata_handlers, metadata_repositories, max_publications, publication_text_reviewer, create_atlas, collect_datasets, harmonize_datasets, collect_metadata, dev_out_dir, .dev, development snapshots, timestamped snapshots

- id: collector
  title: Collector
  lines: 120-156
  anchor: collector
  keywords: AtlasCollector, query loading, collect_jsons, collect_metadata, skip metadata, EuropePMCWrapper, collect_accessions, max_publications, filter_accessions, is_handled_accession, collect_accession_metadata, metadata_repository, metadata_handler, metadata_repositories, GEO, GSE, GSM, GDS, GPL, arrayexpress, E-MTAB, E-GEOD, E-MEXP, original_datalinks, accession_metadata

- id: filterer
  title: Filterer
  lines: 158-188
  anchor: filterer
  keywords: AtlasFilterer, internal filter_jsons, collect_datasets, atlas_parts, publication_texts, publication_text_ref, collect_publication_texts, accessions_with_publication_text_refs, publication_with_text_ref, review_and_filter_publications, PublicationTextReviewer, filterer.review, agentic_curator, thematic reviewer, review_filter, not_relevant, unsure, abstractText, fullTextXML, text_source, fallback

- id: harmonizer
  title: Harmonizer
  lines: 190-195
  anchor: harmonizer
  keywords: AtlasHarmonizer, harmonize_datasets, OntologyHarmonizer, harmonize_miniml_json, accession_metadata, publication context, harmonization details, strategy, target_paths, failure isolation

- id: epmc-wrapper
  title: EuropePMC Wrapper
  lines: 197-335
  anchor: epmc-wrapper
  keywords: EuropePMCWrapper, collect_accessions, collect_publications, max_publications, collect_publication_texts, publication_text_sections, collect_datalinks, fullTextXML, section delimiters, abstract fallback, deduplicate, publications, abstractText, text_source, publication_texts, publication_text_ref, original_datalinks, accession_metadata, Europe PMC, search response, datalinks, XML fallback, failed publications, Scholix, accession records, progress logs, stats logs, search stats

- id: rate-handling
  title: Rate Handling
  lines: 337-348
  anchor: rate-handling
  keywords: rate limits, retry, Retry-After, timeout, page_limit, page_size, request_delay

- id: arrayexpress-wrapper
  title: ArrayExpress Wrapper
  lines: 350-362
  anchor: arrayexpress-wrapper
  keywords: ArrayExpressWrapper, arrayexpress, placeholder, metadata_repository, metadata_source, metadata_status, accession_metadata, E-MTAB, E-GEOD, E-MEXP

- id: geo-wrapper
  title: GEO Wrapper
  lines: 364-412
  anchor: geo-wrapper
  keywords: GEOWrapper, collect_accession_metadata, get_gse, GSE, GSM, GDS, GPL, GSE normalization, MINiML JSON, geo2json, related_series, metadata_status, accession_metadata, NCBI E-utilities, ESearch, ESummary, api_key, tool, email, progress logs, stats logs, debug logs
