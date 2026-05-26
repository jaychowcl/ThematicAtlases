# ThematicAtlases Codebase Handoff

This document describes the current live package at the repository root. The previous implementation is archived under `oldd/` and is reference-only until behavior is deliberately ported into the live package.

The current implemented path collects Europe PMC dataset datalinks from keyword-driven publication searches:

```text
python3 -m ThematicAtlases.cli_atlas create-atlas
python3 -m ThematicAtlases.cli_atlas create-atlas --query fibrosis --out atlas.json
```

`create-atlas` is the preferred end-to-end workflow entrypoint. It collects GEO-filtered, deduplicated accession records with publication provenance and accession metadata, then runs the publication text mapping stage and writes the final atlas object when `--out` is provided.

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`ThematicAtlases` will provide tools for building thematic atlases of biomedical datasets. The live package is a fresh foundation, with only the Europe PMC publication-search path restored so far.

Live package files:

```text
src/ThematicAtlases/
├── __init__.py
├── atlas.py
├── cli_atlas.py
└── wrappers/
    ├── __init__.py
    ├── epmc.py
    └── geo.py
```

Root project files:

```text
pyproject.toml
README.md
LICENSE
.gitignore
```

Development docs, local debug query input, and tests:

```text
.dev/queries.txt
docs/codebase.md
docs/index.md
docs/dev.md
docs/memory.md
docs/burndown.md
tests/test_atlas.py
tests/test_cli_atlas.py
tests/test_epmc_wrapper.py
tests/test_geo_wrapper.py
```

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Version metadata is `0.1.0`.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies contain `requests>=2.31` and `meta-standards-converter` from `jaychowcl/meta_standards_converter`.
- The `dev` optional dependency group contains `pytest>=8`.
- The package uses a `src/` layout with setuptools package discovery.
- The installed console command is `thematic-atlas`, pointing to `ThematicAtlases.cli_atlas:main`.

<a id="public-api"></a>
## Public API

`src/ThematicAtlases/__init__.py` is currently empty. It does not export `Atlas`, `ThematicAtlas`, `__version__`, or any other symbol.

The live atlas class is `Atlas` in `src/ThematicAtlases/atlas.py`. Import callers must use:

```python
from ThematicAtlases.atlas import Atlas
```

<a id="atlas-workflow"></a>
### Atlas Workflow

`class Atlas` is the workflow object currently used by the CLI.

Current methods:

- `__init__(metadata: dict)`: accepts metadata but does not store it yet.
- `create_atlas(query=None, file=None, out=None)`: runs `collect_jsons(..., out=None)`, passes the collected records into `filter_jsons(jsons=...)`, optionally writes the final atlas object to `out`, and returns that object.
- `collect_jsons(query=None, file=None, out=None)`: builds a query list, calls `EuropePMCWrapper.collect_accessions(queries=...)`, filters collected datalinks to currently handled accessions, routes them through metadata repository handlers, optionally writes the intermediate collected accession list to `out`, and returns that list.
- `filter_jsons(jsons=None)`: accepts collected accession records, gathers unique publication text, adds lightweight publication text references under nested publication metadata, and returns a top-level filtered JSON object.
- `harmonize_jsons()`: placeholder, returns `None`.

Query loading behavior:

- Repeated CLI `--query` values are preserved in order.
- `file` values are read as UTF-8 text.
- Query files ignore blank lines and lines starting with `#`.
- If neither `query` nor `file` is provided, the wrapper receives an empty query list.

Filtering behavior:

- `_filter_accessions(accessions)` is an internal filter used by `collect_jsons()` to keep accessions handled by the live workflow.
- `_is_handled_accession(record)` currently uses the GEO rules: records are handled when `datalink_id_scheme` equals `GEO`, case-insensitive, or `datalink_id` starts with `GSE`, `GSM`, `GPL`, or `GDS`, case-insensitive.
- Future platform support should extend `_is_handled_accession(record)` with additional platform checks.
- `_collect_accession_metadata(jsons)` is the metadata repository routing step used after filtering.
- `_metadata_repository(record)` currently returns `geo` for handled GEO records and `None` for unhandled records.
- `_metadata_handler(repository)` currently routes `geo` records to `GEOWrapper`.
- GSE normalization happens inside `GEOWrapper.collect_accession_metadata()`: GSE records remain GSE, GSM/GDS records resolve to their parent GSE, and GPL or unresolved records are removed.
- Metadata repository handlers append repository metadata under each returned accession/project record. GEO stores parsed MINiML JSON in `accession_metadata`.
- Multiple filtered records resolving to the same GSE collapse into one result. The merged result keeps first-seen GSE-level top-level values, deduplicates publications, records original datalink evidence in `original_datalinks`, and keeps the first available metadata package.
- `_collect_publication_texts(jsons)` is used by `filter_jsons()`. It extracts unique surviving nested publications, calls `EuropePMCWrapper.collect_publication_texts(publications=...)`, and returns a shared `publication_texts` map keyed by PMID, then PMCID, DOI, or `source:epmc_id`.
- `_accessions_with_publication_text_refs(jsons, publication_texts)` adds `publication_text_ref` to nested publication metadata when text is available. Full text is not duplicated inside accession records.
- Raw non-GEO datalinks are not preserved by `collect_jsons()`.

<a id="epmc-wrapper"></a>
### EuropePMC Wrapper

`ThematicAtlases.wrappers.epmc.EuropePMCWrapper` handles Europe PMC publication search.

Current public methods:

- `collect_accessions(queries: list[str]) -> list[dict]`: searches publications, fetches Europe PMC datalinks for each publication, deduplicates by normalized `datalink_id`, and returns accession records before publication text enrichment.
- `collect_publications(queries: list[str]) -> list[dict]`: searches Europe PMC for each query and returns normalized publication rows.
- `collect_publication_texts(publications: list[dict]) -> list[dict]`: fetches open-access full text when available and falls back to abstracts.
- `collect_datalinks(publications: list[dict]) -> list[dict]`: calls the Europe PMC datalinks API for publication rows, flattens datalink rows internally, deduplicates by accession, and returns accession records.
- `publication_text_sections(text: str) -> list[dict]`: parses section-delimited publication text into ordered section dictionaries.

The wrapper uses `requests.get()` against:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/search
```

Search parameters:

- `query`: the keyword query string.
- `format=json`
- `resultType=core`
- `pageSize=1000`
- `cursorMark=*` initially, then the returned `nextCursorMark`.
- `synonym=TRUE`

Returned publication fields:

```text
query
epmc_id
source
pmid
pmcid
doi
title
authorString
abstractText
affiliation
fullTextUrls
firstPublicationDate
```

`collect_publications()` and `collect_datalinks()` are intermediate stages inside `collect_accessions()`. `collect_datalinks()` owns the flattened datalink row collection and internal `_deduplicate_accessions()` pass. `collect_publication_texts()` remains a reusable enrichment stage and is called by `Atlas.filter_jsons()` after accession collection and metadata routing. `collect_accessions()` returns deduplicated accession records with:

```text
datalink_id
datalink_id_scheme
datalink_url
datalink_category
publications
```

`Atlas.collect_jsons()` then normalizes these records to GSE accessions. Final atlas records add:

```text
original_datalinks
metadata_repository
metadata_source
metadata_status
accession_metadata
source_datalink_id
```

Each `original_datalinks` item keeps the original evidence that resolved to the final GSE:

```text
datalink_id
datalink_id_scheme
datalink_url
datalink_category
```

Each `publications` item keeps the publication/query provenance that pointed to the accession:

```text
query
epmc_id
source
pmid
pmcid
doi
title
abstractText
publication_text_ref
```

Duplicate accessions are grouped by stripped uppercase `datalink_id`. Accession-level fields keep the first encountered values when duplicate rows conflict. Repeated publication entries under the same accession are collapsed by `source`, `epmc_id`, `pmid`, `pmcid`, and `doi`.

`create_atlas()` returns and writes the current final atlas object. Internally it calls `filter_jsons()`, which returns a top-level object with collected accession records and a shared publication text map:

```text
accessions
publication_texts
```

Each `publication_texts` entry contains `text`, `text_source`, and `full_text_status`. Publications attached only to non-GEO, GPL, or unresolved records are not sent through the fullTextXML enrichment stage.

Publication text enrichment uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{id}/fullTextXML
```

The full-text ID is the publication `pmcid` when present, or `epmc_id` when it is PMC-style. Successful fullTextXML responses are parsed into section-delimited plain text and stored as `text` with `text_source="fullTextXML"` and `full_text_status="available"`. Section delimiters use this exact sentinel, which downstream parsers may split on:

```text
<<<THEMATIC_ATLASES_SECTION:title=Methods>>>
```

`publication_text_sections(text)` converts delimited text back into ordered dictionaries such as `{"title": "Methods", "text": "..."}`. For plain fallback text without sentinels, it returns one `Text` section when text is non-empty.

If full text is unavailable, non-open-access, missing a PMC identifier, or fails with an unrecoverable error, the publication remains in provenance and the shared publication text map falls back to `abstractText` when present. In that fallback path, `text_source` is `abstractText` or `none`, `full_text_status` is `unavailable`, `missing_pmcid`, or `error`, and the fallback text is not delimiter-wrapped. Publisher pages and `fullTextUrls` are not fetched.

The datalink request uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
```

with `format=json`. The current dataset category filter keeps `GEO`, `BioProject`, `BioStudies`, `Nucleotide Sequences`, `BioStudies: supplemental material and supporting data`, and `Functional Genomics Experiments`.

Atlas, EuropePMC, and GEO library modules define loggers but do not configure global logging. The CLI is responsible for logging configuration.

Atlas emits INFO-level progress logs for collection stages, including query loading, Europe PMC accession collection, accession filtering, metadata collection, output writing, publication text collection, and publication text-reference attachment. Atlas also emits INFO-level stats for query count, raw accession count, filtered accession count, metadata output count, publication text map count, and accessions with publication text references.

Each EuropePMC query logs one INFO-level search stats message with the query, total hits from `hitCount` when present, collected hits, fetched pages, page limit, whether the page limit stopped pagination, and final cursor.

Each publication text enrichment pass logs one INFO-level stats message with publications checked, full text available, abstract fallbacks, and missing text.

Each datalink collection pass logs one INFO-level stats message with publications checked, datalinks collected, and skipped categories.

Each accession deduplication pass logs one INFO-level stats message with input datalink rows, output accessions, duplicate rows collapsed, and skipped rows.

<a id="rate-handling"></a>
### Rate Handling

`EuropePMCWrapper` has conservative defaults:

- `page_limit=5`
- `page_size=1000`
- `timeout=30`
- `request_delay=0.1`
- `max_retries=3`

These request tuning values are stored together in an internal settings dictionary. Transient response statuses `429`, `500`, `502`, `503`, and `504` are retried. `Retry-After` is honored when present; otherwise retry delay uses short exponential backoff. Pagination is sequential, with no parallel requests.

<a id="geo-wrapper"></a>
### GEO Wrapper

`ThematicAtlases.wrappers.geo.GEOWrapper` resolves GEO accessions to GEO Series accessions through NCBI E-utilities and appends parsed GEO MINiML JSON through `meta_standards_converter`. `Atlas.collect_jsons()` routes GEO records to it through `_collect_accession_metadata()`.

Current public methods:

- `collect_accession_metadata(jsons: list[dict]) -> list[dict]`: normalizes GEO records to GSE-level accession records, preserves `original_datalinks` and `publications`, drops GPL or unresolved records, and appends parsed GEO MINiML JSON metadata under each final record's `accession_metadata`.
- `get_gse(accession: str) -> str | None`: returns a normalized `GSE...` accession or `None`.

Resolution behavior:

- `GSE...` returns itself without network access.
- `GPL...` returns `None`, representing an entry that downstream callers should remove.
- `GDS...` and `GSM...` use NCBI ESearch and ESummary against `db=gds`.
- Unknown, empty, malformed, not found, missing-GSE, or no exact summary match returns `None`.
- If an exact GDS/GSM summary has multiple semicolon-separated GSE values, the first non-empty value is returned.
- GEO MINiML JSON metadata comes from `geo2json().convert(gse=..., related_series=True, remove_empty=True, enrich=True, out=None)` and is appended directly to each output record as `accession_metadata`.
- Related GEO super/subseries packages returned by `geo2json` become separate records, inherit the source record's `publications` and `original_datalinks`, and receive their own `accession_metadata` package.

GEO metadata records add:

```text
metadata_repository
metadata_source
metadata_status
accession_metadata
source_datalink_id
```

`metadata_repository` is `geo`, `metadata_source` is `geo2json`, and `metadata_status` is `available` when metadata collection succeeds. If `geo2json` raises for a GSE, the normalized GSE record is retained with `metadata_status="error"` and `accession_metadata=null`. When duplicate records collapse to the same GSE, the first available `accession_metadata` package is kept. `source_datalink_id` is only present on related-series records where the package accession differs from the source GSE.

The ESearch request uses:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
```

with `db=gds`, `term={accession}[ACCN]`, `retmode=json`, and `retmax=20`. The ESummary request uses:

```text
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
```

with `db=gds`, comma-separated UIDs in `id`, and `retmode=json`. When ESearch returns related records, the wrapper only accepts the ESummary record whose `accession` exactly matches the requested GEO accession.

`GEOWrapper` accepts optional `api_key`, `tool`, and `email` constructor values and includes them in E-utilities parameters when present. Request settings default to `timeout=30`, `request_delay=0.34`, and `max_retries=3`; the delay keeps the default path below the no-key E-utilities guideline of 3 requests per second.

GEO emits INFO-level progress logs while resolving accessions and collecting metadata for each GSE. GEO emits INFO-level stats for resolved records, dropped records, metadata packages, related records, error/unavailable records, deduplicated output rows, publication links, and original datalink links. GEO DEBUG logs include ESearch/ESummary request details, retry status/attempt/delay, `geo2json` calls, and accession routing decisions.

<a id="cli-atlas"></a>
## CLI Atlas

`ThematicAtlases.cli_atlas` provides a standard-library `argparse` CLI with `main(argv: list[str] | None = None) -> int`.

Commands:

- `[-v | --verbose] [--log-file LOG_FILE]`
- `create-atlas [--query QUERY] [--file FILE] [--out OUT]`
- `collect-jsons [--query QUERY] [--file FILE] [--out OUT]`
- `filter-jsons`
- `harmonize-jsons`

Logging options are global and must appear before the subcommand. Default logging level is `WARNING`; `-v` or `--verbose` enables INFO progress and stats logs, and `-vv` enables DEBUG request, retry, and routing logs. Without `--log-file`, logs go to stdout. With `--log-file`, logs are written to that UTF-8 file only.

`--query` may be repeated. When `--query` and `--file` are both provided, explicit query values come before file query lines. For `collect-jsons`, `--out` writes the intermediate collected accession list. For `create-atlas`, `--out` writes the final atlas object with `accessions` and `publication_texts`. The local VS Code launch config passes `--verbose --log-file .dev/atlas.log collect-jsons --file .dev/queries.txt --out .dev/atlas.json`.

Each command instantiates `Atlas(metadata={})`, calls the matching method, and configures logging from CLI options. Successful commands do not print result data to stdout, though stdout may contain logs when verbose console logging is enabled. Use `--out` as the JSON result channel and logging as the stats channel.

The CLI `filter-jsons` command still has no file input options, so it calls `Atlas.filter_jsons()` with no records and exits quietly. The Python API `filter_jsons(jsons=...)` is implemented as the publication text mapping stage.

<a id="archive-reference"></a>
## Archive Reference

`oldd/` contains the archived previous implementation, generated outputs, old docs, and old environment artifacts. Treat it as source material to inspect and cannibalize deliberately, not as live package code.

Live code should not import from `oldd/`. If behavior is restored from the archive, port it into `src/ThematicAtlases/` with tests and updated docs.

<a id="test-and-verification-status"></a>
## Test And Verification Status

Live tests cover atlas query loading, GEO filtering, CLI behavior, Europe PMC request parameter construction, cursor pagination, retry handling, publication field normalization, publication text enrichment and section parsing, datalink flattening, accession deduplication, and GEO-to-GSE resolution. Wrapper and CLI tests mock network access.

Useful checks:

```bash
python3 -m py_compile src/ThematicAtlases/__init__.py src/ThematicAtlases/atlas.py src/ThematicAtlases/cli_atlas.py src/ThematicAtlases/wrappers/__init__.py src/ThematicAtlases/wrappers/epmc.py src/ThematicAtlases/wrappers/geo.py
python3 -m pytest
```

If `pytest` is unavailable in the active environment, use a direct smoke check:

```bash
PYTHONPATH=src python3 -m ThematicAtlases.cli_atlas collect-jsons --query fibrosis
```

The smoke check performs a live Europe PMC request when `requests` is installed and network access is available.
