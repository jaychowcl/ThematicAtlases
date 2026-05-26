# ThematicAtlases Codebase Handoff

This document describes the current live package at the repository root. The previous implementation is archived under `oldd/` and is reference-only until behavior is deliberately ported into the live package.

The current implemented path collects Europe PMC publication metadata from keyword queries:

```text
python3 -m ThematicAtlases.cli_atlas collect-jsons
python3 -m ThematicAtlases.cli_atlas collect-jsons --query fibrosis --out atlas.json
```

`collect-jsons` is the first real workflow slice. It currently returns publication dictionaries, not final dataset accession records.

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

Development docs, query input, and tests:

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
- `collect_jsons(query=None, file=None, out=None)`: builds a query list, calls `EuropePMCWrapper.collect_accessions(queries=...)`, optionally writes the result list to `out`, and returns the result.
- `filter_jsons()`: placeholder, returns `None`.
- `harmonize_jsons()`: placeholder, returns `None`.

Query loading behavior:

- Repeated CLI `--query` values are preserved in order.
- `file` values are read as UTF-8 text.
- Query files ignore blank lines and lines starting with `#`.
- If neither `query` nor `file` is provided, `.dev/queries.txt` is used.

<a id="epmc-wrapper"></a>
### EuropePMC Wrapper

`ThematicAtlases.wrappers.epmc.EuropePMCWrapper` handles Europe PMC publication search.

Current public methods:

- `collect_accessions(queries: list[str]) -> list[dict]`: currently delegates to `collect_publications(queries=queries)` and returns publication metadata dictionaries.
- `collect_publications(queries: list[str]) -> list[dict]`: searches Europe PMC for each query and returns normalized publication rows.

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

This is a temporary return shape for the first implementation slice. Dataset datalink and accession extraction are not implemented yet.

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

- `collect-jsons [--query QUERY] [--file FILE] [--out OUT]`
- `filter-jsons`
- `harmonize-jsons`

`--query` may be repeated. When `--query` and `--file` are both provided, explicit query values come before file query lines. `--out` writes the raw final result list, not the CLI envelope.

Each command instantiates `Atlas(metadata={})`, calls the matching method, and prints compact JSON:

```json
{"command":"collect-jsons","status":"placeholder","result":[...]}
```

The status remains `placeholder` because filtering, harmonization, and true accession extraction are still incomplete.

<a id="archive-reference"></a>
## Archive Reference

`oldd/` contains the archived previous implementation, generated outputs, old docs, and old environment artifacts. Treat it as source material to inspect and cannibalize deliberately, not as live package code.

Live code should not import from `oldd/`. If behavior is restored from the archive, port it into `src/ThematicAtlases/` with tests and updated docs.

<a id="test-and-verification-status"></a>
## Test And Verification Status

Live tests cover atlas query loading, CLI behavior, Europe PMC request parameter construction, cursor pagination, retry handling, and publication field normalization. Wrapper and CLI tests mock network access.

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
