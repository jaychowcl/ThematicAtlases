# ThematicAtlases

Tools for collecting, filtering, and organizing biomedical dataset accessions into thematic atlases.

## Longer description

ThematicAtlases builds atlas-ready JSON from publication-driven dataset discovery. It searches Europe PMC, extracts dataset datalinks, filters them by selected metadata repositories, enriches supported accessions with metadata, and maps each accession back to publication provenance.

The current workflow supports GEO and ArrayExpress routing. GEO accessions are normalized to GSE records and enriched with `geo2json` metadata through `meta-standards-converter`. ArrayExpress accessions are retained and marked with placeholder metadata so downstream JSON shapes can already include ArrayExpress records while a live ArrayExpress fetcher is still pending.

The filtering stage builds a shared `publication_texts` map, fetching open-access full text from Europe PMC when available and falling back to abstracts when full text is missing. When a theme is supplied, ThematicAtlases can call `agentic-curator` to review publication text for thematic relevance and optionally remove not-relevant or unsure publications.

Current limitations: ArrayExpress metadata is placeholder-only, and `harmonize_jsons()` is currently a placeholder extension point.

## Installation

Install the package from the repository root:

```bash
python3 -m pip install -e .
```

For development and tests:

```bash
python3 -m pip install -e ".[dev]"
```

After installation, use the console command:

```bash
thematic-atlas --help
```

You can also run the CLI as a module:

```bash
python3 -m ThematicAtlases.cli_atlas --help
```

### Requirements

- Python `>=3.10`
- Runtime dependencies: `requests`, `agentic-curator`, and `meta-standards-converter`
- Optional development dependency: `pytest`

## Quickstart

Collect GEO accession JSONs from a query:

```bash
thematic-atlas collect-jsons \
  --query "fibrosis RNA-seq human" \
  --out atlas_collect.json
```

Collect both GEO and ArrayExpress records:

```bash
thematic-atlas collect-jsons \
  --query "fibrosis RNA-seq human" \
  --metadata-repository geo \
  --metadata-repository arrayexpress \
  --out atlas_collect.json
```

Limit a smoke run to the first 25 searched publications:

```bash
thematic-atlas collect-jsons \
  --query "fibrosis RNA-seq human" \
  --max-publications 25 \
  --out atlas_collect.json
```

Create a final atlas object in one command:

```bash
thematic-atlas create-atlas \
  --query "fibrosis RNA-seq human" \
  --out atlas.json
```

Filter an existing collected JSON file and run thematic review:

```bash
thematic-atlas filter-jsons \
  --file atlas_collect.json \
  --theme "human fibrosis transcriptomics datasets" \
  --review-filter not-relevant \
  --out atlas_filtered.json
```

## CLI

Global options must appear before the subcommand:

- `-v`, `--verbose`: enable INFO progress and stats logs.
- `-vv`: enable DEBUG logs, including request/retry/routing details.
- `--log-file PATH`: write UTF-8 logs to a file instead of stdout.

Commands:

- `collect-jsons`: searches Europe PMC, collects datalinks, filters selected repositories, enriches accession metadata, and returns/writes an intermediate list of accession records.
- `filter-jsons`: reads collected accession records or an atlas-shaped object, builds `publication_texts`, attaches `publication_text_ref`, optionally runs thematic review, and returns/writes an atlas object.
- `create-atlas`: orchestrates `collect-jsons` followed by `filter-jsons`, then returns/writes the final atlas object.
- `harmonize-jsons`: placeholder command for future harmonization behavior.

Collection options:

- `--query TEXT`: query string; may be repeated.
- `--file PATH`: UTF-8 query file for `collect-jsons`/`create-atlas`, or JSON input file for `filter-jsons`.
- `--out PATH`: write JSON output.
- `--metadata-repository {geo,arrayexpress}`: repository to keep and enrich; repeatable. Omitted means GEO-only.
- `--max-publications N`: positive integer cap on searched Europe PMC publications before datalink fetching.

Filtering options:

- `--theme TEXT`: theme passed to `agentic-curator` for publication relevance review.
- `--theme-file PATH`: read the theme from a UTF-8 file; takes precedence over `--theme`.
- `--review-filter {none,not-relevant,not-relevant-and-unsure}`: choose whether reviewed not-relevant and unsure publications are removed. Non-`none` filters require a theme.

Output shapes:

- `collect-jsons` writes a JSON list of accession records.
- `filter-jsons` and `create-atlas` write an atlas object with `accessions` and `publication_texts`.
- Successful commands do not print result JSON to stdout; use `--out` for data and logging options for progress.

## Python API

Use the root orchestrator:

```python
from ThematicAtlases.atlas import Atlas

atlas = Atlas(metadata={})
```

Major orchestrator methods:

- `Atlas.collect_jsons(query=None, file=None, out=None, metadata_repositories=None, max_publications=None) -> list[dict]`
  - Inputs: repeated query strings, optional query file, optional output path, repository selection, and publication cap.
  - Output: intermediate accession records with publication provenance and repository metadata.
- `Atlas.filter_jsons(jsons=None, file=None, theme=None, review_filter="none", reviewer=None) -> dict`
  - Inputs: collected accession list or atlas object, optional JSON file, optional theme/review filter, optional reviewer injection.
  - Output: atlas object with `accessions` and `publication_texts`.
- `Atlas.create_atlas(query=None, file=None, out=None, theme=None, review_filter="none", metadata_repositories=None, max_publications=None, reviewer=None) -> dict`
  - Inputs: collection and filtering options.
  - Output: final atlas object, optionally written to `out`.
- `Atlas.harmonize_jsons() -> list[dict] | None`
  - Output: currently `None`.

Major components:

- `AtlasCollector`: query loading, Europe PMC accession collection, repository filtering, metadata-handler routing, and optional intermediate JSON output.
- `AtlasFilterer`: publication text collection, `publication_text_ref` attachment, thematic review, review-based filtering, and atlas object construction.
- `AtlasHarmonizer`: placeholder harmonization extension point.
- `EuropePMCWrapper`: publication search, datalink collection, full-text/abstract text enrichment, retry handling, and datalink XML fallback.
- `GEOWrapper`: GEO accession normalization to GSE and `geo2json` metadata enrichment.
- `ArrayExpressWrapper`: placeholder ArrayExpress metadata enrichment.
- `PublicationTextReviewer`: thematic review integration, review reuse, judgement parsing, and review-filter application.

Python logging is library-style: modules define loggers but do not configure global logging. Applications should configure logging themselves. The CLI configures logging from `-v`, `-vv`, and `--log-file`.

## More information

- [Codebase handoff](docs/codebase.md)
- [Codebase index](docs/index.md)
- [Atlas workflow](docs/codebase.md#atlas-workflow)
- [Collector flow](docs/codebase.md#collector)
- [Filterer flow](docs/codebase.md#filterer)
- [Europe PMC wrapper flow](docs/codebase.md#epmc-wrapper)
- [GEO wrapper flow](docs/codebase.md#geo-wrapper)
- [ArrayExpress wrapper flow](docs/codebase.md#arrayexpress-wrapper)
- [CLI flow](docs/codebase.md#cli-atlas)

## Authors

Created by [jaychowcl](https://github.com/jaychowcl) @ [Saez-Rodriguez Group](https://saezlab.org) & [EMBL-EBI Functional Genomics Team](https://www.ebi.ac.uk/about/teams/functional-genomics/) on May 2026
