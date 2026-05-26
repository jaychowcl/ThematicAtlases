# codebase.md Index

Ranges point into `docs/codebase.md`. Command template: `sed -n '<Lines>p' docs/codebase.md`. Refresh ranges after editing `docs/codebase.md`.

## Main Sections

- id: project-purpose-and-layout
  title: Project Purpose And Layout
  lines: 11-62
  anchor: project-purpose-and-layout
  keywords: purpose, layout, tests

- id: runtime-behavior
  title: Runtime Behavior
  lines: 63-75
  anchor: runtime-behavior
  keywords: dependencies, network, outputs

- id: end-to-end-geo2ae-flow
  title: End-To-End geo2ae Flow
  lines: 76-110
  anchor: end-to-end-geo2ae-flow
  keywords: geo2ae, CLI, fetch, parse, MAGE-TAB

- id: parsed-miniml-data-shape
  title: Parsed MINiML Data Shape
  lines: 111-170
  anchor: parsed-miniml-data-shape
  keywords: MINiML, parser, singular keys

- id: workflow-details
  title: Workflow Details
  lines: 171-393
  anchor: workflow-details
  keywords: workflows, related series, IDF, SDRF

- id: public-api-and-callable-reference
  title: Public API And Callable Reference
  lines: 394-875
  anchor: public-api-and-callable-reference
  keywords: API, classes, methods

- id: maintenance-notes
  title: Maintenance Notes
  lines: 876-885
  anchor: maintenance-notes
  keywords: caveats, maintainers

- id: test-plan
  title: Test Plan
  lines: 886-914
  anchor: test-plan
  keywords: tests, acceptance

## Workflow Sections

- id: geo-parse-flow
  title: GEO Parse Flow
  lines: 174-203
  anchor: geo-parse-flow
  keywords: GEOParser, XML, references

- id: related-series-flow
  title: Related-Series Flow
  lines: 204-224
  anchor: related-series-flow
  keywords: related, superseries, subseries

- id: idf-and-mage-tab-construction-flow
  title: IDF And MAGE-TAB Construction Flow
  lines: 225-249
  anchor: idf-and-mage-tab-construction-flow
  keywords: IDF, AEConstructor, composition

- id: sdrf-graph-and-rendering-flow
  title: SDRF Graph And Rendering Flow
  lines: 250-275
  anchor: sdrf-graph-and-rendering-flow
  keywords: SDRF, graph, render

- id: technology-handler-selection
  title: Technology Handler Selection
  lines: 276-304
  anchor: technology-handler-selection
  keywords: technology, handlers

- id: sequencing-sdrf-flow
  title: Sequencing SDRF Flow
  lines: 305-332
  anchor: sequencing-sdrf-flow
  keywords: sequencing, SRA, FASTQ

- id: array-sdrf-flow
  title: Array SDRF Flow
  lines: 333-362
  anchor: array-sdrf-flow
  keywords: array, hybridization, files

- id: base-sdrf-behavior
  title: Base SDRF Behavior
  lines: 363-382
  anchor: base-sdrf-behavior
  keywords: base handler, factors, protocols

- id: sra-pubmed-and-ontology-enrichment
  title: SRA, PubMed, And Ontology Enrichment
  lines: 383-393
  anchor: sra-pubmed-and-ontology-enrichment
  keywords: SRA, PubMed, ontology

## API Sections

- id: cli
  title: CLI
  lines: 399-418
  anchor: cli
  keywords: cli_geo2ae, flags, main

- id: converter
  title: Converter
  lines: 419-449
  anchor: converter
  keywords: geo2ae, convert

- id: miniml-enricher
  title: MINiML enricher
  lines: 450-476
  anchor: miniml-enricher
  keywords: enrichment, PubMed, SRA

- id: geo-web-fetcher
  title: GEO web fetcher
  lines: 477-494
  anchor: geo-web-fetcher
  keywords: GEOWebFetcher, MINiML

- id: geo-parser
  title: GEO parser
  lines: 495-561
  anchor: geo-parser
  keywords: GEOParser, parse helpers

- id: ae-idf-handlers
  title: AE IDF handlers
  lines: 562-627
  anchor: ae-idf-handlers
  keywords: IDFConstructor, miniml2idf

- id: ae-constructor
  title: AE constructor
  lines: 628-677
  anchor: ae-constructor
  keywords: AEConstructor, ProtocolRegistry, composition, file writing

- id: sdrf-handlers
  title: SDRF handlers
  lines: 678-760
  anchor: sdrf-handlers
  keywords: SDRF, handlers, graph

- id: harmonizers
  title: Harmonizers
  lines: 761-795
  anchor: harmonizers
  keywords: Harmonizer, ontology

- id: json-helper
  title: JSON helper
  lines: 796-812
  anchor: json-helper
  keywords: JSONHandler, paths

- id: pubmed-fetcher
  title: PubMed fetcher
  lines: 813-828
  anchor: pubmed-fetcher
  keywords: PubMed, fetch, ESummary

- id: insdc-fetcher
  title: INSDC fetcher
  lines: 829-860
  anchor: insdc-fetcher
  keywords: SRA, INSDC, fetch

- id: metastore
  title: MetaStore
  lines: 861-875
  anchor: metastore
  keywords: MetaStore, validation

## Parser Callables

- id: geoparser-class-and-parse-methods
  title: GEOParser class and parse methods
  lines: 475-503
  anchor: geoparser-class-and-parse-methods
  keywords: repeated_children, parse, cleanup

- id: parser-reference-resolution
  title: reference resolution
  lines: 504-512
  anchor: parser-reference-resolution
  keywords: package, samples, platforms, contributors

- id: parser-generic-xml-mapping
  title: generic XML mapping
  lines: 514-521
  anchor: parser-generic-xml-mapping
  keywords: _parse_element, snake_case

- id: parser-related-series-helpers
  title: related-series helpers
  lines: 523-528
  anchor: parser-related-series-helpers
  keywords: queue, dedupe, fetch

- id: parser-cleanup-and-helpers
  title: cleanup and helpers
  lines: 530-537
  anchor: parser-cleanup-and-helpers
  keywords: remove_empty, namespace, text

## SDRF Callables

- id: sdrf-dataclasses
  title: SDRF dataclasses
  lines: 652-661
  anchor: sdrf-dataclasses
  keywords: SDRFAttr, SDRFAudit

- id: sdrfconstructor
  title: SDRFConstructor
  lines: 662-675
  anchor: sdrfconstructor
  keywords: technology, SRA lookup

- id: sdrf-file-helpers
  title: File helpers
  lines: 676-681
  anchor: sdrf-file-helpers
  keywords: classify_file, extension

- id: base-sdrf-handler
  title: Base SDRF handler
  lines: 682-696
  anchor: base-sdrf-handler
  keywords: paths, columns, source

- id: sequencing-handlers
  title: Sequencing handlers
  lines: 697-714
  anchor: sequencing-handlers
  keywords: sequencing, single-cell, droplet, spatial

- id: array-and-generic-handlers
  title: Array and generic handlers
  lines: 715-724
  anchor: array-and-generic-handlers
  keywords: array, files, hybridization

- id: legacy-fallback-notes
  title: Legacy fallback notes
  lines: 725-730
  anchor: legacy-fallback-notes
  keywords: fallback, disabled
