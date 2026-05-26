# ThematicAtlases Codebase Handoff

This document describes the current live package at the repository root. The previous implementation is archived under `oldd/` and is reference-only until behavior is deliberately ported into the live package.

The current implemented path collects Europe PMC dataset datalinks from keyword-driven publication searches:

```text
python3 -m ThematicAtlases.cli_atlas collect-jsons
python3 -m ThematicAtlases.cli_atlas collect-jsons --query fibrosis --out atlas.json
```

`collect-jsons` is the first real workflow slice. It currently returns GEO-filtered, deduplicated accession records with publication provenance.

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
    └── epmc.py
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
```

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Version metadata is `0.1.0`.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies contain `requests>=2.31`.
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
- `collect_jsons(query=None, file=None, out=None)`: builds a query list, calls `EuropePMCWrapper.collect_accessions(queries=...)`, filters collected datalinks to allowed GEO records, optionally writes the filtered result list to `out`, and returns the filtered result.
- `filter_jsons()`: placeholder, returns `None`.
- `harmonize_jsons()`: placeholder, returns `None`.

Query loading behavior:

- Repeated CLI `--query` values are preserved in order.
- `file` values are read as UTF-8 text.
- Query files ignore blank lines and lines starting with `#`.
- If neither `query` nor `file` is provided, the wrapper receives an empty query list.

Filtering behavior:

- `_filter_jsons(jsons)` is an internal filter used by `collect_jsons()`.
- Allowed records have `datalink_id_scheme` equal to `GEO`, case-insensitive, or a `datalink_id` starting with `GSE`, `GSM`, `GPL`, or `GDS`, case-insensitive.
- Raw non-GEO datalinks are not preserved by `collect_jsons()` in this step.

<a id="epmc-wrapper"></a>
### EuropePMC Wrapper

`ThematicAtlases.wrappers.epmc.EuropePMCWrapper` handles Europe PMC publication search.

Current public methods:

- `collect_accessions(queries: list[str]) -> list[dict]`: searches publications, fetches Europe PMC datalinks for each publication, deduplicates by normalized `datalink_id`, and returns accession records.
- `collect_publications(queries: list[str]) -> list[dict]`: searches Europe PMC for each query and returns normalized publication rows.
- `collect_datalinks(publications: list[dict]) -> list[dict]`: calls the Europe PMC datalinks API for publication rows and returns flattened dataset datalinks.

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

`collect_publications()` and `collect_datalinks()` are intermediate stages. `collect_accessions()` returns deduplicated accession records with:

```text
datalink_id
datalink_id_scheme
datalink_url
datalink_category
publications
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
```

Duplicate accessions are grouped by stripped uppercase `datalink_id`. Accession-level fields keep the first encountered values when duplicate rows conflict. Repeated publication entries under the same accession are collapsed by `source`, `epmc_id`, `pmid`, `pmcid`, and `doi`.

The datalink request uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
```

with `format=json`. The current dataset category filter keeps `GEO`, `BioProject`, `BioStudies`, `Nucleotide Sequences`, `BioStudies: supplemental material and supporting data`, and `Functional Genomics Experiments`.

Each query logs one INFO-level search stats message with the query, total hits from `hitCount` when present, collected hits, fetched pages, page limit, whether the page limit stopped pagination, and final cursor. Library code defines the logger but does not configure global logging.

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

<a id="cli-atlas"></a>
## CLI Atlas

`ThematicAtlases.cli_atlas` provides a standard-library `argparse` CLI with `main(argv: list[str] | None = None) -> int`.

Commands:

- `[-v | --verbose] [--log-file LOG_FILE]`
- `collect-jsons [--query QUERY] [--file FILE] [--out OUT]`
- `filter-jsons`
- `harmonize-jsons`

Logging options are global and must appear before the subcommand. Default logging level is `WARNING`; `-v` or `--verbose` enables `INFO`, and `-vv` enables `DEBUG`. Without `--log-file`, logs go to stderr. With `--log-file`, logs are written to that UTF-8 file only.

`--query` may be repeated. When `--query` and `--file` are both provided, explicit query values come before file query lines. `--out` writes the raw final result list, not the CLI envelope. The local VS Code launch config passes `--verbose --log-file .dev/atlas.log collect-jsons --file .dev/queries.txt --out .dev/atlas.json`.

Each command instantiates `Atlas(metadata={})`, calls the matching method, and configures logging from CLI options. Successful commands do not print result data to stdout. Use `--out` as the JSON result channel and logging as the stats channel.

`filter-jsons` and `harmonize-jsons` remain placeholders. `collect-jsons` is implemented through Europe PMC publication search, datalink collection, accession deduplication, and GEO filtering.

<a id="archive-reference"></a>
## Archive Reference

`oldd/` contains the archived previous implementation, generated outputs, old docs, and old environment artifacts. Treat it as source material to inspect and cannibalize deliberately, not as live package code.

Live code should not import from `oldd/`. If behavior is restored from the archive, port it into `src/ThematicAtlases/` with tests and updated docs.

<a id="test-and-verification-status"></a>
## Test And Verification Status

Live tests cover atlas query loading, GEO filtering, CLI behavior, Europe PMC request parameter construction, cursor pagination, retry handling, publication field normalization, and datalink flattening. Wrapper and CLI tests mock network access.

Useful checks:

```bash
python3 -m py_compile src/ThematicAtlases/__init__.py src/ThematicAtlases/atlas.py src/ThematicAtlases/cli_atlas.py src/ThematicAtlases/wrappers/__init__.py src/ThematicAtlases/wrappers/epmc.py
python3 -m pytest
```

If `pytest` is unavailable in the active environment, use a direct smoke check:

```bash
PYTHONPATH=src python3 -m ThematicAtlases.cli_atlas collect-jsons --query fibrosis
```

The smoke check performs a live Europe PMC request when `requests` is installed and network access is available.
