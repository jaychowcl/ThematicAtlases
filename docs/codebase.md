# meta_standards_converter Codebase Handoff

This document describes the live `meta_standards_converter` package under `src/meta_standards_converter`. It is a development handoff for maintainers working on GEO MINiML parsing and ArrayExpress/MAGE-TAB IDF/SDRF generation.

The implemented conversion path is:

```text
GEO Series accession -> GEO MINiML XML -> parsed per-Series metadata packages -> MAGE-TAB IDF + SDRF -> optional .idf.txt/.sdrf.txt files
```

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`meta_standards_converter` converts biological study metadata between repository standards. The current package focuses on GEO MINiML to ArrayExpress/MAGE-TAB-style output.

```text
src/meta_standards_converter/
├── cli_geo2ae.py                 # geo2ae command-line entrypoint
├── cli_geo2json.py               # geo2json command-line entrypoint
├── cli_common.py                 # shared CLI logging helpers
├── converters/
│   ├── geo2ae.py                 # top-level GEO to AE orchestration
│   └── geo2json.py               # top-level GEO to JSON orchestration
├── geo_handlers/
│   ├── geo_webfetcher.py         # GEO MINiML URL building and download
│   └── geo_parser.py             # MINiML XML to JSON-ready per-Series packages
├── pubmed_handlers/
│   └── pubmed_webfetcher.py      # PubMed ESummary lookup and parsed publication metadata
├── enrichers/
│   └── miniml_enricher.py        # Adds PubMed/SRA records to parsed MINiML JSON
├── ae_handlers/
│   ├── ae_idf_handlers.py        # IDF row construction
│   ├── ae_constructor.py         # MAGE-TAB coordination, protocol registry, file writing
│   └── ae_sdrf_handlers.py       # SDRF graph model and technology handlers
├── harmonizers/
│   ├── geo2ols.py                # GEO protocol type ontology mapping
│   ├── pubmed2ols.py             # PubMed status ontology mapping
│   └── harmonizers.py            # combined harmonizer
├── helpers/
│   └── json_helper.py            # dotted-path JSON helpers
├── insdc_handlers/
│   └── insdc_webfetcher.py       # SRA accession extraction, NCBI lookup, and run parsing
└── meta_store/
    └── meta_store.py             # placeholder metadata validation store
```

Tests cover parser packaging, converter orchestration, CLI flags, AE constructor composition, IDF behavior, and SDRF rendering:

```text
tests/test_geo_parser.py
tests/test_geo2ae.py
tests/test_geo2json.py
tests/test_cli_geo2ae.py
tests/test_cli_geo2json.py
tests/test_ae_constructor.py
tests/test_ae_sdrf_handlers.py
tests/test_miniml_enricher.py
tests/test_insdc_webfetcher.py
tests/test_pubmed_webfetcher.py
tests/GSE328265_family.xml
```

<a id="runtime-behavior"></a>
## Runtime Behavior

- The package requires Python `>=3.8`.
- Runtime dependencies are `requests` and `python-dateutil`.
- The `geo2ae` console script points to `meta_standards_converter.cli_geo2ae:main`; `geo2json` points to `meta_standards_converter.cli_geo2json:main`.
- Network calls are owned by platform fetchers: `GEOWebFetcher` handles GEO FTP MINiML tarballs and related-series traversal, `INSDCWebfetcher` handles NCBI SRA EFetch run metadata, and `PubmedWebFetcher` handles NCBI PubMed ESummary publication metadata.
- `geo2ae.convert()` keeps parsed and enriched GEO metadata in memory for MAGE-TAB construction.
- `geo2json.convert()` returns parsed GEO package JSON, enriched by default, and can write `{accession}.json`.
- When `out` is supplied, `geo2ae.convert()` writes `{accession}.idf.txt` and `{accession}.sdrf.txt`.
- `geo2ae` `out` controls MAGE-TAB output only; use `geo2json` for parsed JSON snapshots.
- `MetaStore._validate_investigation_metadata_structure()` is a `pass` placeholder, so `validate_investigation_metadata()` currently asserts for normal input.

<a id="end-to-end-geo2ae-flow"></a>
## End-To-End geo2ae Flow

```text
main(argv)
  -> parse CLI args
  -> instantiate geo2ae()
  -> for each GSE accession:
       geo2ae.convert(gse, related_series, remove_empty, out)
       continue to the next accession if a conversion fails
  -> return 1 if any accession failed, else 0

geo2ae.convert(gse, related_series, remove_empty, out)
  -> GEOWebFetcher.fetch_gse_miniml(gse)
  -> GEOParser.parse(miniml, remove_empty=remove_empty, related_series=related_series)
  -> MINiMLEnricher.enrich(data) for each parsed package
  -> instantiate one shared AEConstructor()
  -> for each enriched metadata package:
       AEConstructor.miniml2magetab(data)
  -> if out:
       AEConstructor.magetab2file(magetab, out) for each MAGE-TAB payload
  -> return list of MAGE-TAB payloads
```

`geo2json.convert(gse, related_series, remove_empty, enrich, out)` follows the same GEO fetch and parse stages, optionally enriches each parsed package through `MINiMLEnricher`, writes `{gse}.json` when `out` is truthy, and returns the list of JSON packages without invoking AE/MAGE-TAB construction.

CLI behavior:

- Positional `gse` accepts one or more GEO Series accessions.
- `--related`, `--related-series`, and `--get-related-series` are aliases that enable related super/subseries traversal.
- `--remove-empty` is the default and removes empty parsed MINiML fields before conversion.
- `--keep-empty` preserves empty parsed MINiML fields.
- `--out DIR` defaults to the current directory.
- Failed accessions print an error and traceback to stderr, then later accessions still run.

<a id="parsed-miniml-data-shape"></a>
## Parsed MINiML Data Shape

`GEOParser.parse()` returns `list[dict]`, with one self-contained package per top-level MINiML `Series`.

```python
[
    {
        "version": str | None,
        "database": list[dict],
        "organization": list[dict],
        "contributor": list[dict],
        "platform": list[dict],
        "sample": list[dict],
        "series": dict,
    }
]
```

Top-level package keys are singular. Parser keys inside each parsed XML element are original XML names converted to snake_case. Repeated XML elements also keep the singular snake_case key and point to a list.

Examples:

```text
Sample-Ref          -> sample_ref
Pubmed-ID           -> pubmed_id
Data-Table          -> data_table
Supplementary-Data  -> supplementary_data
Raw-Data            -> raw_data
```

Element text mapping is generic:

- Plain leaf elements with no attributes or child elements become strings.
- Elements with attributes become dictionaries containing those attributes.
- When an attribute-bearing or child-bearing element also has text, the text is stored as `value`.
- Values remain strings; the parser does not coerce dates, numbers, booleans, or ontology identifiers.
- Namespaces are stripped to local names.
- Non-`version` root attributes are attached to each package under snake_case keys.

Example:

```xml
<Characteristics>whole larval tissue</Characteristics>
<Characteristics tag="time">30 Days</Characteristics>
```

parses as:

```python
{"characteristics": ["whole larval tissue", {"tag": "time", "value": "30 Days"}]}
```

`MINiMLEnricher` adds remote lookup results without changing the raw parsed GEO fields:

- `series.pubmed_publication`: one dict per `series.pubmed_id`, with `pubmed_id`, `doi`, `author_list`, `title`, `status`, `status_term_source_ref`, and `status_term_accession_number`.
- `sample.*.sra_accession`: SRA/ENA/DDBJ accessions extracted from SRA sample relations.
- `sample.*.ena_accession`: deduplicated study/project accessions such as `ERP137216` collected from SRA run enrichment.
- `sample.*.sra_run`: run dicts returned by `INSDCWebfetcher.fetch_sra_runs()`, including study accession, library metadata, run/sample IDs, read lengths, instrument model, and per-FASTQ `filename`/`uri`/`md5`.

<a id="workflow-details"></a>
## Workflow Details

<a id="geo-parse-flow"></a>
### GEO Parse Flow

```text
GEOParser.parse(miniml, remove_empty, related_series)
  -> _parse(miniml)
       -> ET.fromstring(miniml)
       -> _top_level_nodes(root)
       -> _parse_element(each top-level node)
       -> _build_indexes(parsed_top_level)
       -> _series_package(root, each series, indexes)
  -> if related_series:
       _parse_with_related_series(parsed)
  -> if remove_empty:
       remove_empty_fields(each package)
  -> return parsed package list
```

Per-Series packages include only records relevant to that series:

- Samples referenced by `series.sample_ref[*].ref`.
- Platforms referenced by included sample `platform_ref.ref`.
- Contributors referenced by series, sample, or platform `contributor_ref` and `contact_ref`.
- Organizations referenced by included contributors or databases through `organization_ref.ref`.
- Databases referenced by included `accession[*].database` or `status[*].database`.

Missing references are tolerated. The original reference remains in place, and the unresolved target record is omitted from package lists.

The parser uses an XSD-inspired `repeated_children` map for known repeated MINiML fields. Unknown repeated sibling tags still become lists if they occur more than once.

<a id="related-series-flow"></a>
### Related-Series Flow

```text
parse(miniml, related_series=True)
  -> _parse input MINiML into root packages
  -> _parse_with_related_series(root packages)
       -> seed seen_gses from series.accession[*].value
       -> seed queue from superseries/subseries relation entries
       -> fetch unseen related GSE MINiML
       -> _parse related MINiML
       -> append related packages
       -> enqueue newly discovered related GSEs
       -> stop when queue is empty
  -> return root packages plus related packages
```

`GEOParser.parse_related_series(miniml, remove_empty=False, strict=True)` uses the same traversal logic but returns only related packages, excluding the input packages. When `strict=True`, fetch or parse failures raise. When `strict=False`, failed related accessions are skipped.

Related GSE accessions are discovered from `series.relation` entries only when relation `type`, `target`, or `comment` mentions superseries/subseries and contains `GSE` followed by digits.

<a id="idf-and-mage-tab-construction-flow"></a>
### IDF And MAGE-TAB Construction Flow

`AEConstructor` is a coordinator, not an SDRF subclass. It owns an `IDFConstructor` and an `SDRFConstructor`, supplied as optional dependencies or created by default.

```text
AEConstructor.miniml2magetab(data)
  -> create one ProtocolRegistry for the series accession
  -> detect one shared AE technology key
  -> SDRFConstructor._miniml2sdrf(data, protocol_registry, technology_type)
       -> generate SDRF table
       -> register actual non-empty Protocol REF values and required placeholder refs
  -> IDFConstructor.miniml2idf(data, protocol_registry, technology_type)
       -> build IDF rows
       -> emit Protocol rows from the same registry
       -> include empty ["SDRF File"] placeholder after protocol rows
       -> infer term source rows
  -> replace existing SDRF File placeholder with ["SDRF File", sdrf_table]
  -> return MAGE-TAB payload
```

`ProtocolRegistry` normalizes protocol text, reuses refs for identical `(kind, text)` pairs, and names refs as `P-{series_accession}-{n}`. Known protocol kinds map to MAGE-TAB labels such as `Extract-Protocol`, `Hybridization-Protocol`, `Scan-Protocol`, and `Data-Processing`. Required placeholder refs can be created with empty protocol text for protocols that must be present in IDF and SDRF.

`AEConstructor.magetab2file()` normalizes legacy mixed payloads, finds the SDRF row, validates the SDRF payload is a non-empty row table, chooses filenames from `Comment[ArrayExpressAccession]`, `Investigation Accession`, or `Comment[SecondaryAccession]`, writes IDF/SDRF TSV files, and returns the IDF path.

<a id="sdrf-graph-and-rendering-flow"></a>
### SDRF Graph And Rendering Flow

The SDRF code models each rendered row as an `SDRFPath`, an ordered list of nodes and protocol edges.

- `SDRFAttr`: companion column label, value, nested attrs, and required flag.
- `SDRFNode`: primary SDRF column such as `Source Name`, `Extract Name`, `Assay Name`, `Scan Name`, or file columns.
- `SDRFEdge`: `Protocol REF` column with optional attrs.
- `SDRFPath`: one rendered row path.
- `ColumnGroup`: planned primary column plus companion columns.
- `SDRFAudit`: warnings, dropped values, and validation errors.

```text
SDRFConstructor._miniml2sdrf(data, protocol_registry, technology_type=None)
  -> use supplied technology_type, or fall back to _detect_sdrf_technology(data)
  -> select handler class
  -> handler.build()
       -> build_paths()
       -> plan_columns(paths)
       -> render_paths(columns, paths)
  -> store handler.audit as self.last_sdrf_audit
  -> return SDRF table rows
```

Column planning scans every path before rendering rows. Repeated visible labels are disambiguated internally with occurrence keys such as `Array Data File#1`; visible labels can repeat when MAGE-TAB expects repeated columns.

<a id="technology-handler-selection"></a>
### Technology Handler Selection

`AEConstructor._detect_ae_technology()` reads platform technology/title, library source/strategy/selection, sample type, series text, sample text, channel text, file extensions, and SRA relations. `SDRFConstructor._detect_sdrf_technology()` remains available for direct SDRF callers, but delegates to the AE constructor detector.

Detected handler keys:

```text
plate_single_cell_sequencing
droplet_single_cell_sequencing
single_cell_sequencing
spatial_sequencing
bulk_sequencing
array
generic
```

Detection rules in broad order:

- High-throughput sequencing platform text, SRA relations, library strategy, or sample type `SRA` choose bulk sequencing.
- Single-cell text chooses single-cell sequencing variants.
- `visium` or `spatial` text takes spatial precedence.
- `10x`, `droplet`, or `chromium` text chooses droplet single-cell.
- Single-cell text without droplet hints chooses plate single-cell.
- Array platform technology or array-like files choose array.
- Everything else uses the generic handler.

Assay terms such as ChIP-seq, ATAC-seq, multiome, methylation, or array assay names do not by themselves create special technology handlers beyond sequencing or array.

<a id="sequencing-sdrf-flow"></a>
### Sequencing SDRF Flow

Sequencing paths use:

```text
Source Name
Protocol REFs for treatment/growth/extraction
Extract Name
Protocol REF for library construction
Assay Name
Scan Name
Factor Value[...] columns
```

Sequencing behavior:

- SRA accessions are extracted from sample relations and cached per handler.
- SRA records contribute library layout/source/strategy/selection, run/experiment/sample accessions, submitted file names, MD5, instrument model, read lengths, and FASTQ metadata.
- GEO values take precedence over conflicting SRA values, and warnings are recorded in `SDRFAudit`.
- Shared sequencing paths render FASTQs as `Comment[readN file]`, `Comment[FASTQ_URI]`, and `Comment[MD5]` companion columns.
- Bulk and plate sequencing paths emit one SDRF row per FASTQ URI, with duplicate sample/source metadata allowed across rows.
- More than two FASTQs are preserved; shared sequencing uses additional read comments, while bulk and plate sequencing use additional rows.
- When no SRA FASTQs exist, sequencing raw files from GEO supplementary/raw data can become read comments.
- Derived files render as `Comment[derived data file]`.
- Sequencing handlers intentionally do not emit `Array Data File`, `Derived Array Data Matrix File`, or `Derived Array Data File` columns.
- Single-cell handlers add library construction, technical replicate, read geometry, isolation, or spatial read-index comments where their subclass supports it.

<a id="array-sdrf-flow"></a>
### Array SDRF Flow

Array paths use:

```text
Source Name
Protocol REFs for treatment/growth/extraction
Extract Name
optional labeling Protocol REF
optional Labeled Extract Name
Hybridization Protocol REF
Assay Name
optional Scan Protocol REF
Scan Name
file nodes
Factor Value[...] columns
```

Array behavior:

- Two-channel samples emit one path per channel and warn through the audit object.
- Channel `label` creates a `Labeled Extract Name` with a `Label` companion.
- `Array Design REF` is taken from the sample platform accession and has nested `Term Source REF = ArrayExpress`.
- `.tif` and `.tiff` files render as `Image File`.
- `.cel`, `.gpr`, `.idat`, `.exp`, `.rpt`, `.cab`, and similar raw array files render as `Array Data File`.
- `.txt`, `.tsv`, `.csv`, `.mtx`, `.h5`, and `.h5ad` files render as `Derived Array Data Matrix File`.
- Other supplementary files render as `Derived Array Data File`.
- Repeated raw or derived files are preserved as repeated columns and recorded as warnings.

<a id="base-sdrf-behavior"></a>
### Base SDRF Behavior

Base handler behavior shared by generic, sequencing, and array handlers:

- Sample ordering follows `series.sample_ref` first, then any remaining samples.
- A sample with multiple channels emits multiple channel paths and records a warning.
- `Source Name` uses the GSM accession when available, falling back to sample `iid`.
- GEO channel source is preserved as `Comment[Sample_source_name]`.
- Sample title and description render as mapped sample comment columns when present.
- `Characteristics[organism part]` is always planned for source nodes and may be blank.
- Explicit `organism part` wins; otherwise `tissue` wins; otherwise channel `source` is used as fallback.
- Repeated characteristics with the same tag are preserved as repeated columns and recorded as warnings.
- Provider and material type are mapped from channel biomaterial provider and molecule/source context.
- Factor values come from series variables when present, otherwise from characteristic tags with more than one value.
- Required blank protocol refs are emitted as blank cells with audit warnings but do not create IDF protocol rows.
- `normalized_extension()` strips archive suffixes such as `.gz`, `.zip`, `.bz2`, and `.xz` before classifying the underlying extension.

Legacy greedy GEO and SRA fallback comment classes are kept only as commented reference code at the bottom of `ae_sdrf_handlers.py`. They have no runtime effect.

<a id="sra-pubmed-and-ontology-enrichment"></a>
### SRA, PubMed, And Ontology Enrichment

- Normal `geo2ae.convert()` enrichment happens after `GEOParser.parse()` and before `AEConstructor.miniml2magetab()`.
- `MINiMLEnricher` writes PubMed metadata to `series.pubmed_publication` and SRA metadata to `sample.sra_accession`/`sample.sra_run`.
- IDF construction prefers `series.pubmed_publication`; `_lookup_pubmed_id()` remains as a compatibility fallback.
- SDRF construction prefers `sample.sra_run`; relation-based `_lookup_sra()` remains as a compatibility fallback.
- GEO protocol labels map through `Harmonizer().geoprotocols2efo()`.
- PubMed status maps through `Harmonizer().pubstatus2efo()`.
- Term source rows are inferred from non-empty rows whose label contains `source ref`.

<a id="public-api-and-callable-reference"></a>
## Public API And Callable Reference

This section lists public and semi-public callables used by tests or by package orchestration. Many helper methods are intentionally private but documented here because this project currently relies on direct helper behavior in tests and internal composition.

<a id="cli"></a>
### `cli_geo2ae.py` and `cli_geo2json.py`

`_parser() -> argparse.ArgumentParser`

- Build command-line parsers for one or more GSE accessions.
- Adds `--related`, `--related-series`, and `--get-related-series` aliases.
- Adds mutually exclusive `--remove-empty` and `--keep-empty` options.
- Adds `--out`, defaulting to `"."`.
- Adds logging controls: repeatable `-v`/`--verbose`, `-q`/`--quiet`, and `--log-file`.
- `geo2json` also adds `--no-enrich`, which skips PubMed/SRA enrichment and writes parsed-only JSON.

`main(argv=None) -> int`

- Parses arguments, configures `meta_standards_converter` logging to stdout and optional file output, creates the command's converter, and converts each accession in order.
- Default logging emits `WARNING+`; `-v` emits `INFO+`, `-vv` emits `DEBUG+`, and `--quiet` emits `ERROR+`.
- On conversion failure, logs the exception traceback, marks the run failed, and continues.
- Success/progress messages are logged rather than printed; normal success output appears with `-v`.
- Returns `1` if any accession failed, otherwise `0`.

<a id="converter"></a>
### `converters/geo2ae.py` and `converters/geo2json.py`

`class geo2ae(JSONHandler)`

- Main programmatic converter.
- The class inherits `JSONHandler`, though the converter path does not currently rely on inherited helper methods.
- `__init__(enricher=None)` accepts an enrichment dependency and defaults to `MINiMLEnricher()`.

`convert(gse, related_series=False, remove_empty=True, out=None)`

- Fetches MINiML with `GEOWebFetcher().fetch_gse_miniml(gse=gse)`.
- Parses with `GEOParser().parse(miniml, remove_empty=remove_empty, related_series=related_series)`.
- Enriches each parsed package with `self.enricher.enrich(data=meta_json)`.
- Instantiates one `AEConstructor`.
- Converts each enriched package to a MAGE-TAB payload.
- Writes each payload when `out` is truthy.
- Returns the list of MAGE-TAB payloads.

`class geo2json(JSONHandler)`

- Main programmatic GEO-to-JSON converter.
- `__init__(enricher=None)` accepts an enrichment dependency and defaults to `MINiMLEnricher()`.

`convert(gse, related_series=False, remove_empty=True, enrich=True, out=None)`

- Fetches and parses MINiML using the same GEO fetcher/parser path as `geo2ae`.
- Enriches each parsed package by default; `enrich=False` returns parsed-only GEO JSON.
- Writes one `{gse}.json` file containing the full package list when `out` is truthy.
- Returns the list of JSON packages.

<a id="miniml-enricher"></a>
### `enrichers/miniml_enricher.py`

`class MINiMLEnricher`

`__init__(pubmed_fetcher=None, insdc_fetcher=None)`

- Accepts PubMed and INSDC fetcher dependencies for tests or custom network behavior.
- Defaults to `PubmedWebFetcher()` and `INSDCWebfetcher()`.

`enrich(data: dict) -> dict`

- Mutates and returns one parsed MINiML package.
- Calls `enrich_pubmed()` and `enrich_sra()`.

`enrich_pubmed(data: dict) -> dict`

- Deduplicates `series.pubmed_id` values while preserving first-seen order.
- Adds `series.pubmed_publication` records with the fields consumed by `IDFConstructor`.
- On request or XML parse errors, records the PubMed ID with `None` metadata values so late IDF rendering does not retry the lookup.

`enrich_sra(data: dict) -> dict`

- Extracts SRA accessions from `sample.relation` entries whose type is `SRA`.
- Adds `sample.sra_accession`, `sample.sra_run`, and `sample.ena_accession` when fetched runs contain study accessions.
- On request or XML parse errors, keeps the accession and leaves that accession's run contribution empty.

<a id="geo-web-fetcher"></a>
### `geo_handlers/geo_webfetcher.py`

`class GEOWebFetcher`

`url_gse_miniml(gse: str) -> str`

- Requires an accession starting with `GSE`, case-insensitive.
- Converts accessions to the GEO FTP bucket pattern. For example, `GSE234602` becomes bucket `GSE234nnn`.
- Returns the GEO FTP HTTPS URL ending in `{gse}_family.xml.tgz`.

`fetch_gse_miniml(gse) -> str`

- Builds the URL with `url_gse_miniml()`.
- Sleeps one second to reduce rate-limit pressure.
- Downloads the `.tgz` archive with `requests.get()` and `raise_for_status()`.
- Extracts `{gse}_family.xml` from the tarball and returns it as UTF-8 text.

<a id="geo-parser"></a>
### `geo_handlers/geo_parser.py`

<a id="geoparser-class-and-parse-methods"></a>
`class GEOParser`

- Owns `repeated_children`, an XSD-inspired map of repeated MINiML children by parent tag.
- Parses only recognized top-level package categories: organization, contributor, database, platform, sample, and series.

`parse(miniml, remove_empty=False, related_series=False) -> list[dict]`

- Parses the input MINiML into per-series packages.
- Optionally traverses related super/subseries.
- Optionally removes empty fields after all parsing/traversal.

`_parse(miniml) -> list[dict]`

- Parses one MINiML XML string without related-series fetching or cleanup.
- Builds top-level parsed records, indexes them by `iid`, and creates one package per series.

`parse_related_series(miniml, remove_empty=False, strict=True) -> list[dict]`

- Parses the input MINiML, seeds a queue from related-series relations, and returns only fetched related packages.
- Deduplicates GSE accessions.
- Raises on fetch/parse failures in strict mode; skips failures in non-strict mode.
- Applies empty cleanup to related packages when requested.

`remove_empty_fields(data)`

- Public wrapper around `_remove_empty_fields()`.
- Removes `None`, empty strings, empty lists, and empty dicts recursively.

<a id="parser-reference-resolution"></a>
Reference resolution helpers:

- `_top_level_nodes(root)` collects known top-level MINiML elements.
- `_build_indexes(parsed_top_level)` creates `iid` lookup maps.
- `_series_package(root, series, indexes)` assembles a scoped package and attaches root attributes.
- `_resolve_samples()`, `_resolve_platforms()`, `_resolve_contributors()`, `_resolve_databases()`, and `_resolve_organizations()` resolve package records from references.
- `_items_for_refs()` preserves first-seen order and deduplicates refs.
- `_reference_values()` walks nested dicts for ref-bearing keys.

<a id="parser-generic-xml-mapping"></a>
Generic XML mapping helpers:

- `_parse_element(node)` converts XML recursively to strings, dicts, and lists.
- `_child_key(parent_name, child_name)` currently returns singular snake_case child names.
- `_normalized_text(text)` collapses whitespace.
- `_local_name(tag)` strips XML namespaces.
- `_to_snake_case(value)` normalizes tag/attribute names.

<a id="parser-related-series-helpers"></a>
Related-series helpers:

- `_extract_series_accessions()` returns normalized `GSE` accessions from package series accessions.
- `_extract_related_gse_accessions()` extracts related `GSE` accessions from relation type/target/comment text.
- `_is_related_series_relation()` recognizes superseries/subseries relation text.

<a id="parser-cleanup-and-helpers"></a>
Cleanup and walk helpers:

- `_remove_empty_fields(value)` recursively removes empty values.
- `_is_empty_value(value)` defines empty values as `None`, `""`, `[]`, or `{}`.
- `_walk_dicts(value)` recursively yields nested dicts.
- `_as_list(value)` normalizes scalars and `None` to list handling.
- `_attach_namespaced_root_attributes(root, package)` copies non-version root attributes into packages.

<a id="ae-idf-handlers"></a>
### `ae_handlers/ae_idf_handlers.py`

`class IDFConstructor`

`__init__(pubmed_fetcher=None)`

- Accepts a PubMed fetcher dependency for tests or custom network behavior.
- Defaults to `PubmedWebFetcher()`.

`miniml2idf(data, protocol_registry=None, technology_type=None) -> list`

- Builds IDF rows in this order: MAGE-TAB version, investigation rows, experimental design/factor rows, person rows, QC/replicate/normalization rows, date rows, publication rows, experiment description, protocol rows, `SDRF File` placeholder, term source rows, then platform-specific rows.

Investigation and experimental rows:

- `_idf_investigations()` uses series title, series accessions, accession databases, converted ArrayExpress-style accessions, and related super/subseries GSE accessions.
- `_to_arrayexpress_accessions()` replaces `GSE` with `E-GEOD-`.
- `Comment[RelatedExperiment]` is emitted when `series.relation` contains superseries/subseries relation text and related `GSE...` accessions. This row records parsed relationships and does not depend on fetching related packages with `--related`.
- `_idf_experimental()` derives experimental factor names from sample channel characteristics whose normalized tag has more than one distinct normalized value.
- `_idf_platform_specific(data, technology_type)` dispatches to a private platform IDF handler.

Platform IDF handler inheritance mirrors the SDRF platform tree:

```text
_BasePlatformIDFHandler
├── _SequencingPlatformIDFHandler
│   ├── _BulkSequencingPlatformIDFHandler
│   │   └── _PlateSingleCellSequencingPlatformIDFHandler
│   └── _SingleCellSequencingPlatformIDFHandler
│       ├── _DropletSingleCellSequencingPlatformIDFHandler
│       └── _SpatialSequencingPlatformIDFHandler
├── _ArrayPlatformIDFHandler
└── _GenericPlatformIDFHandler
```

The dispatch keys match SDRF: `plate_single_cell_sequencing`, `droplet_single_cell_sequencing`, `single_cell_sequencing`, `spatial_sequencing`, `bulk_sequencing`, `sequencing`, and `array`; unknown or missing keys use `_GenericPlatformIDFHandler`.

Sequencing platform IDF handlers emit empty label-only `Comment[AEExperiment]`, `Comment[AEExperimentType]`, and `Comment[AECurator]` rows. They emit a platform-specific `Comment[SecondaryAccession]` row from enriched `sample.*.ena_accession` values when present. They also emit `Comment[SequenceDataURI]` from enriched `sample.*.sra_run[*].run` accessions when valid runs exist. Runs are deduplicated, grouped by prefix such as `ERR` or `SRR`, sorted numerically, and collapsed to one ENA data/view URL per prefix group using min-max ranges, for example `http://www.ebi.ac.uk/ena/data/view/ERR5385036-ERR5385041`. Droplet single-cell IDF handlers append empty label-only `Comment[AEExpectedClusters]`, `Comment[AEAdditionalAttributes]`, and `Comment[AEBatchEffect]` rows. Array, generic, and unknown handlers do not emit these rows.

Person, QC, and date rows:

- `_idf_persons()` uses contributors for names, email, phone, fax, organization-based affiliation, and flattened addresses prefixed with organization when available.
- `_idf_qc_rep_norm()` emits label-only placeholder rows for quality control, replicate, and normalization.
- `_idf_dates()` normalizes parseable status dates to `YYYY-MM-DD`.
- `_normalized_idf_date()` preserves unparseable values and empty strings.
- `Public Release Date` uses the earliest parseable normalized GEO release date; `Comment[GEOReleaseDate]` preserves all GEO release date values.
- `Comment[ArrayExpressSubmissionDate]` uses the current conversion date as one `YYYY-MM-DD` value while GEO update dates are comments.

Publication, experiment, protocol, and term source rows:

- `_idf_publications()` prefers `series.pubmed_publication`; if absent, it reads `series.pubmed_id`, enriches each ID through PubMed ESummary, and maps publication status.
- `_lookup_pubmed_id()` delegates to `self.pubmed_fetcher.pubmed_summary()` and returns DOI, author string, title, status term, source ref, and accession.
- `_idf_experiments()` combines series summary and overall design into `Experiment Description`.
- `_idf_protocols()` uses a supplied `ProtocolRegistry` when present; otherwise it falls back to scanning known GEO protocol paths.
- `_idf_protocols_from_registry()` emits protocols registered by the SDRF build and appends missing required protocol definitions.
- Required protocol definitions are deduped by harmonized protocol type: `sample collection protocol` is required for all IDFs, while `nucleic acid sequencing protocol` is required for sequencing IDFs.
- `_idf_term_source()` scans rows containing `source ref` and emits source name/file/version rows from `Harmonizer().ontologies`.

Current caveats:

- PubMed lookup is fetcher-owned and normally invoked by `MINiMLEnricher`; direct IDF construction can still invoke it as a fallback when enriched records are absent.
- Unknown PubMed statuses are preserved as literal publication-status labels with blank ontology refs.
- Some date rows are intentionally blank placeholders for internal curation.
- Platform-specific IDF rows are intentionally appended after term source rows; future rows with term-source refs will need explicit term-source handling or a row-order change.

<a id="ae-constructor"></a>
### `ae_handlers/ae_constructor.py`

`class ProtocolRegistry`

- Maps protocol kind/text pairs to stable `P-{series_accession}-{n}` refs.
- Reuses the same ref for identical cleaned text under the same kind.
- Tracks kind, MAGE-TAB label, and cleaned description.
- `ensure_required(kind, label)` creates or reuses a required placeholder ref even when protocol text is empty.
- `records()` returns records in insertion order.

`class AEConstructor`

`__init__(idf_constructor=None, sdrf_constructor=None)`

- Accepts dependency injection for tests or custom constructors.
- Defaults to `IDFConstructor()` and `SDRFConstructor()`.

`miniml2magetab(data) -> list`

- Creates a `ProtocolRegistry` from `_series_accession(data)`.
- Detects the shared MAGE-TAB technology key with `_detect_ae_technology(data)`.
- Builds SDRF first so protocol refs are registered.
- Builds IDF with the same registry and technology key.
- Replaces the first `SDRF File` row with the in-memory SDRF table.
- Strips straight quote characters from rendered IDF and nested SDRF values before returning.
- Raises `ValueError` if the IDF lacks an SDRF row.

`magetab2file(magetab, out=None) -> str`

- Creates the output directory.
- Normalizes row shapes with `_normalize_magetab_rows()`.
- Strips straight quote characters from IDF and SDRF cell values.
- Validates and extracts the embedded SDRF table.
- Chooses IDF and SDRF filenames from the MAGE-TAB accession rows.
- Replaces the embedded SDRF table with the SDRF filename in the IDF.
- Writes both files as tab-delimited UTF-8 text and returns the IDF path.

Other helpers:

- `_detect_ae_technology()` chooses `bulk_sequencing`, `plate_single_cell_sequencing`, `droplet_single_cell_sequencing`, `spatial_sequencing`, `array`, or `generic`.
- `_has_array_files()` detects array-like files from platform/sample/series supplementary data and raw data.
- `_normalize_magetab_rows()` accepts row lists, comma-delimited legacy strings, and legacy `"SDRF file", sdrf` pairs.
- `_strip_quotes()` recursively removes straight single and double quote characters from rendered cell values.
- `_sdrf_row_index()` finds the SDRF row case-insensitively.
- `_magetab_accession()` searches ArrayExpress, investigation, then secondary accession rows.
- `_safe_filename_token()` removes path separators from accession-derived filenames.
- `_is_table()` validates row-table shape.
- `_write_tsv()` writes `None` as blank cells.

<a id="sdrf-handlers"></a>
### `ae_handlers/ae_sdrf_handlers.py`

<a id="sdrf-dataclasses"></a>
Core data structures:

- `SDRFAttr`: companion attributes, including nested companion attributes.
- `SDRFNode`: visible primary SDRF node columns.
- `SDRFEdge`: visible `Protocol REF` columns.
- `SDRFPath`: one logical row path.
- `ColumnGroup`: planned column plus companions.
- `SDRFAudit`: warnings, dropped values, validation errors.

<a id="sdrfconstructor"></a>
`class SDRFConstructor`

`__init__(insdc_fetcher=None)`

- Accepts an INSDC fetcher dependency for tests or custom network behavior.
- Defaults to `INSDCWebfetcher()`.

- `_add_sdrf_to_idf()` appends an in-memory SDRF row to IDF rows; this remains for compatibility but `AEConstructor` now coordinates insertion.
- `_miniml2sdrf(data, protocol_registry=None, technology_type=None)` uses the supplied AE technology key or detects one for compatibility, selects a handler, builds the table, stores `last_sdrf_audit`, and returns rows.
- `_detect_sdrf_technology(data)` delegates to `AEConstructor._detect_ae_technology(data)`.
- `_has_array_files(data)` delegates to `AEConstructor._has_array_files(data)`.
- `_lookup_sra(sra)` delegates SRA fetching/parsing to `self.insdc_fetcher.fetch_sra_runs()` and returns `[]` on request or XML parse errors.

<a id="sdrf-file-helpers"></a>
File helpers:

- `normalized_extension(path)` parses URLs/paths, strips one compression suffix, and returns the lowercase extension.
- `classify_file(path)` returns `sequencing_raw`, `array_raw`, `matrix_or_derived`, or `supplementary`.

<a id="base-sdrf-handler"></a>
`class _BaseSDRFHandler`

- Initializes samples, platform lookup, sample lookup, series accession, protocol registry, audit object, and factor tags.
- Uses enriched `sample.sra_run` when present; otherwise uses the parent constructor's injected `insdc_fetcher` for SRA accession extraction and run lookup.
- `build()` orchestrates path building, column planning, and rendering.
- `build_paths()` creates generic source/factor paths.
- `plan_columns()`, `merge_column_group()`, `render_paths()`, `column_labels()`, `column_values()`, `path_groups()`, `group_with_values()`, `attr_columns()`, `occurrence_key()`, and `render_value()` handle table planning and rendering; `render_value()` quote-strips direct SDRF output.
- `ordered_samples()` respects series sample refs before remaining samples.
- `channels()` normalizes missing channels to `[{}]` and warns for multi-channel samples.
- `source_node()`, `sample_comment_attrs()`, `characteristic_attrs()`, `organism_part_value()`, `provider()`, and `material_type()` build mapped source columns.
- `factor_nodes()`, `_factor_tags()`, `factor_value()`, `characteristic_values()`, and `characteristic_value()` handle experimental factors.
- `extraction_edges()` and `protocol_edge()` register protocol refs and warn for required blank refs.
- All SDRF handlers add a required sample collection `Protocol REF`; sequencing handlers also add a required nucleic acid sequencing `Protocol REF`.
- `sample_accession()`, `biosample_accessions()`, `biosample_accession()`, `platform()`, `platform_accession()`, `instrument_model()`, `supplementary_files()`, `raw_files()`, `derived_files()`, `arrayexpress_ftp()`, `file_node()`, `sra_runs()`, and `clean()` provide common extraction utilities.

<a id="sequencing-handlers"></a>
Sequencing handlers:

- `_SequencingSDRFHandler.build_paths()` builds source, sample collection protocol, extraction, extract, library protocol, assay, nucleic acid sequencing protocol, scan, and factor nodes for each sample/channel/run.
- `extract_node()` maps material type and library attributes.
- `library_attrs()` maps library layout, selection, source, and strategy.
- `geo_first_value()` prefers GEO over conflicting SRA values and records warnings.
- `library_protocol_text()` combines extraction/library/SRA fields for protocol descriptions.
- `assay_node()` maps technology type, ENA/SRA identifiers, submitted file, MD5, and instrument model.
- `geo_first_instrument_model()` prefers GEO instrument model over SRA.
- `scan_node()` maps scan name and sequencing file attrs.
- `sequencing_file_attrs()` maps FASTQs, raw sequencing files, and derived data comments.
- `_BulkSequencingSDRFHandler` is selected for ordinary non-single-cell sequencing and expands each sample/channel/run into one path per FASTQ URI.
- `_SingleCellSequencingSDRFHandler` adds library construction, cDNA read size, technical replicate group, and study text helpers.
- `_DropletSingleCellSequencingSDRFHandler` adds 10x/droplet read geometry and isolation comments.
- `_PlateSingleCellSequencingSDRFHandler` inherits the bulk per-FASTQ row behavior and adds source-level index and description comments.
- `_SpatialSequencingSDRFHandler` adds Visium library construction, read geometry, and read type/read index comments based on submitted filenames.

<a id="array-and-generic-handlers"></a>
Array and generic handlers:

- `_ArraySDRFHandler.build_paths()` builds source, extraction, labeled extract, hybridization, assay, scan, file, and factor nodes.
- `array_extract_node()` builds array extract nodes.
- `labeled_extract_node()` maps channel labels.
- `array_assay_node()` maps array assay technology and Array Design REF.
- `array_file_nodes()` maps raw image/data files, derived matrix files, and supplementary files.
- `_GenericSDRFHandler` uses the base source/factor path behavior.

<a id="legacy-fallback-notes"></a>
Legacy fallback notes:

- `_GEOFallbackComments` and `_SRAFallbackComments` are commented out as reference code.
- No greedy fallback comments are emitted at runtime.

<a id="harmonizers"></a>
### `harmonizers/geo2ols.py`

`class GEO2OLS`

- Ensures an `ontologies` dict exists.
- Registers EFO and OBI term source metadata.

`geoprotocols2efo(protocol_type: str) -> list`

- Maps known MAGE-TAB/GEO protocol labels to ontology term, source ref, and accession.
- Raises `ValueError` for blank protocol type.
- Returns `[protocol_type, None, None]` for unknown non-blank protocol labels, allowing custom protocol labels to survive in IDF output.

### `harmonizers/pubmed2ols.py`

`class Pubmed2OLS`

- Ensures an `ontologies` dict exists.
- Registers EFO and MeSH term source metadata.

`pubstatus2efo(pub_status: str) -> list`

- Returns `[None, None, None]` for blank status.
- Splits composite statuses on `+` and maps the first token.
- Maps common PubMed statuses such as `ppublish`, `epublish`, `pubmed`, `medline`, and `retracted`.
- Returns `[original_status_label, None, None]` for unknown non-blank statuses.

### `harmonizers/harmonizers.py`

`class Harmonizer(Pubmed2OLS, GEO2OLS)`

- Combines PubMed and GEO ontology mappings through multiple inheritance.
- Initializes a shared `ontologies` dictionary before calling parent initializers.

<a id="json-helper"></a>
### `helpers/json_helper.py`

`class JSONHandler`

`_from_path(obj, path_str)`

- Resolves dotted paths through dict/list structures.
- Numeric path components are treated as list indexes.
- `*` expands over lists.
- Missing branches return `[None]`, preserving positional behavior for callers.

`_flatten_values(value)`

- Recursively flattens nested lists and dict values.
- Returns scalar values as a one-item list.

<a id="pubmed-fetcher"></a>
### `pubmed_handlers/pubmed_webfetcher.py`

`class PubmedWebFetcher`

`fetch_pubmed_summary(pubmed_id: str) -> ET.Element`

- Calls NCBI PubMed ESummary for one PubMed ID.
- Raises for HTTP errors and returns the parsed XML root.

`pubmed_summary(pubmed_id: str) -> tuple`

- Parses DOI, author list, title, and PubMed publication status from ESummary XML.
- Maps publication status through `Harmonizer().pubstatus2efo()`.
- Returns the existing IDF tuple shape: DOI, author string, title, mapped status, term source ref, and term accession.

<a id="insdc-fetcher"></a>
### `insdc_handlers/insdc_webfetcher.py`

`class INSDCWebfetcher`

`_extract_sra(sra: str)`

- Extracts SRA/ENA/DDBJ-style accessions matching `[SED]R[RXSP]` plus digits.
- Matching is case-insensitive.

`_ncbi_nrx(nrx: str)`

- Sleeps one second to reduce rate-limit pressure.
- Calls NCBI SRA EFetch with `retmode=xml`.
- Raises for HTTP errors and returns the parsed XML root.

`fetch_sra_runs(accession: str) -> list`

- Calls `_ncbi_nrx()` and ENA Portal `filereport`, then parses and merges run metadata into the run dictionaries consumed by SDRF handlers.
- Preserves the existing run record shape and adds `study`: library layout/source/strategy/selection, SRA/ENA study/sample/run IDs, GEO sample ID, BioSample ID, instrument model, submitted FASTQ filename, MD5, read lengths, and per-FASTQ `filename`/`uri`/`md5` records.
- ENA `fastq_ftp` links are preferred for FASTQ `uri`; if ENA links are absent or unavailable, original NCBI SRA XML `url`/`Alternatives` links are used as fallback.

ENA file report helpers:

- `fetch_ena_file_report()` calls `https://www.ebi.ac.uk/ena/portal/api/filereport` with `result=read_run`, FASTQ fields, and JSON output.
- `fetch_ena_fastq_files()` groups parsed ENA FASTQ records by `run_accession`.
- `_parse_ena_fastq_report()`, `_split_ena_file_field()`, `_normalize_ena_ftp_uri()`, and `_filename_from_uri()` parse semicolon-delimited ENA file fields.

SRA XML helper methods:

- `_parse_sra_library()`, `_parse_sra_sample_ids()`, `_parse_sra_instrument_model()`, `_parse_sra_fastqs()`, `_element_accession()`, `_find_text()`, `_strip_ns()`, and `_clean_sdrf_text()` support SRA parsing.

<a id="metastore"></a>
### `meta_store/meta_store.py`

`class MetaStore`

`validate_investigation_metadata(investigation_metadata: dict) -> bool`

- Calls `_validate_investigation_metadata_structure()` and asserts it is truthy.
- Returns `True` only if validation passes.

`_validate_investigation_metadata_structure(investigation_metadata: dict) -> bool`

- Placeholder with `pass`.
- Because it returns `None`, normal validation currently raises `AssertionError`.

<a id="maintenance-notes"></a>
## Maintenance Notes

- Documentation should describe implemented behavior, not planned burndown items.
- The SDRF system intentionally maps known GEO/SRA values and leaves the old greedy fallback comment code disabled.
- Protocol rows in the IDF should be driven by the same `ProtocolRegistry` used while building SDRF paths.
- PubMed and SRA lookups normally happen during parsed MINiML enrichment through injected fetchers, so unit tests should mock or fake `MINiMLEnricher`, `PubmedWebFetcher`, and `INSDCWebfetcher` when exercising conversion behavior.
- `docs/geo_parser.md` is parser-specific supporting documentation and should be kept consistent if parser behavior changes.
- Generated outputs under `.dev/` and `output/` are examples/debug artifacts, not package code.

<a id="test-plan"></a>
## Test Plan

Run the full suite:

```bash
python -m pytest
```

Important test coverage:

- `tests/test_geo_parser.py`: parser package scoping, cardinality, namespace handling, empty cleanup, related-series traversal, and fixture-backed parsing with `tests/GSE328265_family.xml`.
- `tests/test_geo2ae.py`: converter orchestration, related-series forwarding, enrichment, stage logging, and `remove_empty` forwarding.
- `tests/test_geo2json.py`: JSON converter orchestration, optional enrichment, JSON file writing, and stage logging.
- `tests/test_cli_geo2ae.py`: CLI defaults, multiple accession order, aliases, keep-empty behavior, out directory forwarding, logging controls, file logging, and failure continuation.
- `tests/test_cli_geo2json.py`: JSON CLI defaults, enrichment toggle, aliases, logging controls, file logging, and failure continuation.
- `tests/test_ae_constructor.py`: IDF rows, protocol registry behavior, AE constructor sequencing, SDRF row insertion, file normalization, and protocol ref consistency.
- `tests/test_ae_sdrf_handlers.py`: SDRF graph rendering, source/comment/characteristic behavior, file classification, sequencing/array/single-cell/spatial handlers, SRA precedence warnings, and disabled greedy fallback comments.
- `tests/test_miniml_enricher.py`: additive PubMed/SRA enrichment fields, deduplication, and fetch error tolerance.
- `tests/test_insdc_webfetcher.py`: SRA accession extraction and parsed SRA run records.
- `tests/test_pubmed_webfetcher.py`: PubMed ESummary parsing, publication status mapping, and IDF constructor delegation.

After documentation edits, also check:

```bash
rg -n "^(#|##|###) " docs/codebase.md docs/index.md
```

Then run representative `sed -n` commands from `docs/index.md` to confirm the index ranges land on the intended sections.
