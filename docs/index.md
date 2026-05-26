# codebase.md Index

Ranges point into `docs/codebase.md`. Command template: `sed -n '<Lines>p' docs/codebase.md`. Refresh ranges after editing `docs/codebase.md`.

## Main Sections

- id: project-purpose-and-layout
  title: Project Purpose And Layout
  lines: 14-53
  anchor: project-purpose-and-layout
  keywords: purpose, layout, src, docs, tests, package files, queries

- id: runtime-and-packaging
  title: Runtime And Packaging
  lines: 54-66
  anchor: runtime-and-packaging
  keywords: pyproject, setuptools, version, requests, dependencies, pytest, console script

- id: public-api
  title: Public API
  lines: 67-77
  anchor: public-api
  keywords: import, __init__, exports, Atlas

- id: cli-atlas
  title: CLI Atlas
  lines: 154-174
  anchor: cli-atlas
  keywords: cli_atlas, argparse, query, file, out, collect-jsons, filter-jsons, harmonize-jsons

- id: archive-reference
  title: Archive Reference
  lines: 175-181
  anchor: archive-reference
  keywords: oldd, archive, reference, porting

- id: test-and-verification-status
  title: Test And Verification Status
  lines: 182-200
  anchor: test-and-verification-status
  keywords: tests, py_compile, pytest, smoke check, mocked network

## API Sections

- id: atlas-workflow
  title: Atlas Workflow
  lines: 78-96
  anchor: atlas-workflow
  keywords: Atlas, collect_jsons, query, file, out, default queries, filter_jsons, harmonize_jsons

- id: epmc-wrapper
  title: EuropePMC Wrapper
  lines: 97-140
  anchor: epmc-wrapper
  keywords: EuropePMCWrapper, collect_accessions, collect_publications, Europe PMC, requests, publication metadata

- id: rate-handling
  title: Rate Handling
  lines: 141-153
  anchor: rate-handling
  keywords: rate limits, retry, Retry-After, timeout, page_limit, page_size, request_delay
