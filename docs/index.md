# codebase.md Index

Ranges point into `docs/codebase.md`. Command template: `sed -n '<Lines>p' docs/codebase.md`. Refresh ranges after editing `docs/codebase.md`.

## Main Sections

- id: project-purpose-and-layout
  title: Project Purpose And Layout
  lines: 14-55
  anchor: project-purpose-and-layout
  keywords: purpose, layout, src, docs, tests, package files, debug queries

- id: runtime-and-packaging
  title: Runtime And Packaging
  lines: 56-68
  anchor: runtime-and-packaging
  keywords: pyproject, setuptools, version, requests, dependencies, pytest, console script

- id: public-api
  title: Public API
  lines: 69-79
  anchor: public-api
  keywords: import, __init__, exports, Atlas

- id: cli-atlas
  title: CLI Atlas
  lines: 282-301
  anchor: cli-atlas
  keywords: cli_atlas, argparse, query, file, out, collect-jsons, verbose, log-file, stderr logging, quiet stdout

- id: archive-reference
  title: Archive Reference
  lines: 302-308
  anchor: archive-reference
  keywords: oldd, archive, reference, porting

- id: test-and-verification-status
  title: Test And Verification Status
  lines: 309-327
  anchor: test-and-verification-status
  keywords: tests, py_compile, pytest, smoke check, mocked network, publication text, section parsing, GEO wrapper

## API Sections

- id: atlas-workflow
  title: Atlas Workflow
  lines: 80-111
  anchor: atlas-workflow
  keywords: Atlas, collect_jsons, query, file, out, empty queries, _filter_jsons, _is_handled_accession, _collect_accession_metadata, _metadata_repository, _metadata_handler, _collect_publication_texts, handled accessions, GEO, GSE normalization, publication text, original_datalinks, filter_jsons, harmonize_jsons

- id: epmc-wrapper
  title: EuropePMC Wrapper
  lines: 112-233
  anchor: epmc-wrapper
  keywords: EuropePMCWrapper, collect_accessions, collect_publications, collect_publication_texts, publication_text_sections, collect_datalinks, fullTextXML, section delimiters, abstract fallback, deduplicate, publications, abstractText, original_datalinks, Europe PMC, datalinks, accession records, search stats

- id: rate-handling
  title: Rate Handling
  lines: 234-246
  anchor: rate-handling
  keywords: rate limits, retry, Retry-After, timeout, page_limit, page_size, request_delay

- id: geo-wrapper
  title: GEO Wrapper
  lines: 247-281
  anchor: geo-wrapper
  keywords: GEOWrapper, collect_accession_metadata, get_gse, GSE, GSM, GDS, GPL, GSE normalization, MINiML JSON, NCBI E-utilities, ESearch, ESummary, api_key, tool, email
