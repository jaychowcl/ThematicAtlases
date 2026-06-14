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
  keywords: import, __init__, exports, Atlas, agentic_curator, agentic-curator, ThematicReviewer, theme, filter_jsons, no ThematicAtlases.curator, no curator CLI, separate package

- id: cli-atlas
  title: CLI Atlas
  lines: 403-422
  anchor: cli-atlas
  keywords: cli_atlas, argparse, query, file, out, create-atlas, collect-jsons, filter-jsons, metadata-repository, geo, arrayexpress, theme, theme-file, review-filter, not-relevant, unsure, reuse publication_texts, .env, VS Code launch, verbose, log-file, stdout logging, progress logs, stats logs, debug logs, quiet stdout

- id: archive-reference
  title: Archive Reference
  lines: 424-429
  anchor: archive-reference
  keywords: oldd, archive, reference, porting

- id: test-and-verification-status
  title: Test And Verification Status
  lines: 431-449
  anchor: test-and-verification-status
  keywords: tests, py_compile, pytest, .env, smoke check, mocked network, atlas orchestration, collector, repository selection, arrayexpress, filterer, harmonizer, publication text, section parsing, thematic review, filterer.review, GEO wrapper, atlas CLI

## API Sections

- id: atlas-workflow
  title: Atlas Workflow
  lines: 104-117
  anchor: atlas-workflow
  keywords: Atlas, orchestrator, dependency injection, collector, filterer, harmonizer, epmc_wrapper_factory, metadata_handlers, metadata_repositories, publication_text_reviewer, create_atlas, collect_jsons, filter_jsons, harmonize_jsons

- id: collector
  title: Collector
  lines: 119-153
  anchor: collector
  keywords: AtlasCollector, query loading, collect_jsons, EuropePMCWrapper, collect_accessions, filter_accessions, is_handled_accession, collect_accession_metadata, metadata_repository, metadata_handler, metadata_repositories, GEO, GSE, GSM, GDS, GPL, arrayexpress, E-MTAB, E-GEOD, E-MEXP, original_datalinks, accession_metadata

- id: filterer
  title: Filterer
  lines: 155-183
  anchor: filterer
  keywords: AtlasFilterer, filter_jsons, atlas_parts, publication_texts, publication_text_ref, collect_publication_texts, accessions_with_publication_text_refs, publication_with_text_ref, review_and_filter_publications, PublicationTextReviewer, filterer.review, agentic_curator, review_filter, not_relevant, unsure

- id: harmonizer
  title: Harmonizer
  lines: 185-188
  anchor: harmonizer
  keywords: AtlasHarmonizer, harmonize_jsons, placeholder, None

- id: epmc-wrapper
  title: EuropePMC Wrapper
  lines: 190-324
  anchor: epmc-wrapper
  keywords: EuropePMCWrapper, collect_accessions, collect_publications, collect_publication_texts, publication_text_sections, collect_datalinks, fullTextXML, section delimiters, abstract fallback, deduplicate, publications, abstractText, publication_texts, publication_text_ref, original_datalinks, accession_metadata, Europe PMC, datalinks, XML fallback, failed publications, Scholix, accession records, progress logs, stats logs, search stats

- id: rate-handling
  title: Rate Handling
  lines: 326-337
  anchor: rate-handling
  keywords: rate limits, retry, Retry-After, timeout, page_limit, page_size, request_delay

- id: arrayexpress-wrapper
  title: ArrayExpress Wrapper
  lines: 339-351
  anchor: arrayexpress-wrapper
  keywords: ArrayExpressWrapper, arrayexpress, placeholder, metadata_repository, metadata_source, metadata_status, accession_metadata, E-MTAB, E-GEOD, E-MEXP

- id: geo-wrapper
  title: GEO Wrapper
  lines: 353-401
  anchor: geo-wrapper
  keywords: GEOWrapper, collect_accession_metadata, get_gse, GSE, GSM, GDS, GPL, GSE normalization, MINiML JSON, geo2json, related_series, metadata_status, accession_metadata, NCBI E-utilities, ESearch, ESummary, api_key, tool, email, progress logs, stats logs, debug logs
