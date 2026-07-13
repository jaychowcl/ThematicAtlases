# ThematicAtlases

Tools for collecting, curating, and harmonizing biomedical dataset accessions into thematic atlases.

## Description

ThematicAtlases builds atlas-ready JSON from publication-driven dataset discovery. It searches Europe PMC, extracts dataset datalinks, filters them by selected metadata repositories, optionally enriches supported accessions with metadata, maps each accession back to publication provenance, and can run thematic publication review. `create_atlas()` is the end-to-end Python flow: it calls `collect_datasets()`, then passes those datasets to `harmonize_datasets()`.

The current workflow supports GEO and ArrayExpress routing. GEO accessions are normalized to GSE records, retain their source evidence in `original_datalinks`, deduplicate records that resolve to the same GSE, and are enriched with `geo2json` metadata through `meta-standards-converter`. ArrayExpress accessions are retained and marked with placeholder metadata so downstream JSON shapes can already include ArrayExpress records while a live ArrayExpress fetcher is still pending.

The filtering stage builds a shared `publication_texts` map, fetching open-access full text from Europe PMC when available and falling back to abstracts when full text is missing. Accession publication entries then receive `publication_text_ref` pointers into that shared map so full text is not duplicated on every accession. When a theme is supplied, ThematicAtlases can call `agentic-curator` to review publication text for thematic relevance and optionally remove not-relevant or unsure publications.

`create-atlas` now passes each accession's MINiML-style `accession_metadata` to `agentic-curator` ontology harmonization. Harmonized MINiML replaces the original metadata, while status fields preserve unavailable and per-accession error outcomes. ArrayExpress metadata remains placeholder-only.

## Installation

Install the package from the repository root:

```bash
python3 -m pip install -r requirements.txt
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
- Runtime dependencies: `requests`, `google-auth`, `agentic-curator`, and `meta-standards-converter`
- Optional development dependency: `pytest`

## Quickstart

### Full fibrosis atlas run

Prepare the repository environment, then configure Google Application Default Credentials and a quota project for the LLM-backed query, review, and ontology stages:

```bash
python3 -m venv .env
.env/bin/python -m pip install -e ".[dev]"
gcloud auth application-default login
.env/bin/python run_fibrosis_atlas.py
```

Resume the newest incomplete trace, or a specific run, without repeating its
latest valid completed stage:

```bash
.env/bin/python run_fibrosis_atlas.py --resume
.env/bin/python run_fibrosis_atlas.py --resume 20260712T215848
```

`run_fibrosis_atlas.py` prints its complete fixed configuration before making network or model calls. It removes `snomed`, eagerly downloads/parses/indexes every remaining ontology through `OntoStore.cache_all()`, then searches at most 50 Europe PMC publications using generated fibrosis queries, collects GEO metadata, drops reviewed `not_relevant` publications while retaining `unsure`, performs ontology harmonization, and enables the full development trace. Any ontology cache failure aborts before dataset collection.

Generated files are ignored under `.out/`: `fibrosis_atlas.json`, `fibrosis_atlas.summary.json`, `fibrosis_harmonization_details.json`, `fibrosis_atlas.log`, the ontology store, and timestamped trace bundles under `.out/dev_trace/`.

### Fibrosis discovery without harmonization

Run publication discovery, GEO metadata collection, and thematic review for up
to 1,000 publications without loading ontologies or starting harmonization:

```bash
.env/bin/python run_fibrosis_discovery.py
```

This writes `.out/fibrosis_discovery.json`, its summary, and a dedicated DEBUG
log. The output retains `relevant` and `unsure` datasets and removes reviewed
`not_relevant` publications.

Collect GEO datasets from a query:

```bash
thematic-atlas collect-datasets \
  --query "fibrosis RNA-seq human" \
  --out atlas_datasets.json
```

Collect both GEO and ArrayExpress records:

```bash
thematic-atlas collect-datasets \
  --query "fibrosis RNA-seq human" \
  --metadata-repository geo \
  --metadata-repository arrayexpress \
  --out atlas_datasets.json
```

Limit a smoke run to the first 25 searched publications:

```bash
thematic-atlas collect-datasets \
  --query "fibrosis RNA-seq human" \
  --max-publications 25 \
  --out atlas_datasets.json
```

Create a final atlas object in one command:

```bash
thematic-atlas create-atlas \
  --query "fibrosis RNA-seq human" \
  --harmonization-details-out harmonization_details.json \
  --dev-trace \
  --dev-out-dir .dev \
  --out atlas.json
```

Collect datasets with thematic review while skipping metadata enrichment:

```bash
thematic-atlas collect-datasets \
  --query "fibrosis RNA-seq human" \
  --theme "human fibrosis transcriptomics datasets" \
  --review-filter not-relevant \
  --skip-metadata \
  --out atlas_datasets.json
```

Generate up to three Europe PMC queries from a theme with `agentic-curator`,
then collect datasets using those generated queries:

```bash
thematic-atlas collect-datasets \
  --theme-file docs/theme_fibrosis.txt \
  --query-generator \
  --review-filter not-relevant \
  --out atlas_datasets.json
```

The generator defaults to one comprehensive domain-neutral query: independent
mandatory theme concepts are AND-joined, while relevant synonyms and variants
within each concept are OR-joined. It uses additional queries only when one
query cannot bridge a genuine logical, semantic, syntax, or length gap.

When manual `--query` values or a query `--file` are also supplied, generated
queries are appended after them.

## CLI

Logging options may appear before or after the subcommand:

- `-v`, `--verbose`: enable INFO progress and stats logs.
- `-vv`: enable DEBUG logs, including request/retry/routing details.
- `--log-file PATH`: write UTF-8 logs to a file instead of stdout.

Examples:

```bash
thematic-atlas --verbose collect-datasets --query "fibrosis RNA-seq human"
thematic-atlas collect-datasets --verbose --query "fibrosis RNA-seq human"
```

Commands:

- `collect-datasets`: searches Europe PMC, collects datalinks, filters selected repositories, optionally enriches accession metadata, builds `publication_texts`, attaches `publication_text_ref`, optionally runs thematic review, and returns/writes an atlas object.
- `create-atlas`: orchestrates `collect-datasets` followed by `harmonize-datasets`, then returns/writes the final atlas object.
- `harmonize-datasets`: reads an existing atlas JSON, harmonizes accession MINiML metadata, and writes the transformed atlas.

The CLI is a thin adapter over the Python API. It parses command arguments, normalizes CLI spellings such as `not-relevant` to API values such as `not_relevant`, instantiates `Atlas(metadata={})`, and calls the matching orchestrator method. Result JSON is written only when `--out` is supplied; successful commands keep stdout free of result data so progress logging and data output stay separate.

Collection options:

- `--query TEXT`: query string; may be repeated.
- `--file PATH`: UTF-8 query file for `collect-datasets`/`create-atlas`.
- `--query-generator`: use the theme to generate up to three additional Europe PMC queries with `agentic-curator`; requires `--theme` or `--theme-file`.
- `--max-generated-queries N`: generated-query limit from 1 to 3; defaults to 3.
- `--out PATH`: write JSON output.
- `--metadata-repository {geo,arrayexpress}`: repository to keep and enrich; repeatable. Omitted means GEO-only.
- `--max-publications N`: positive integer cap on searched Europe PMC publications before datalink fetching.
- `--skip-metadata`: keep repository-filtered accessions but skip metadata handler enrichment.
- `create-atlas --dev-trace`: write a complete timestamped development trace bundle.
- `--dev-out-dir` `PATH`: choose the `create-atlas` trace root directory; defaults to `.dev` and is used only with `--dev-trace`.

Filtering options:

- `--theme TEXT`: theme passed to `agentic-curator` for publication relevance review.
- `--theme-file PATH`: read the theme from a UTF-8 file; takes precedence over `--theme`.
- `--review-filter {none,not-relevant,not-relevant-and-unsure}`: choose whether reviewed not-relevant and unsure publications are removed. Non-`none` filters require a theme.

Harmonization options:

- `create-atlas --harmonization-details-out PATH`: optionally write target, strategy, path, status, and error details separately from the atlas.
- `harmonize-datasets --file INPUT --out OUTPUT [--harmonization-details-out PATH]`: transform an existing atlas file. Input and output paths are required.

Output shapes:

- `collect-datasets` and `create-atlas` write an atlas object with `accessions` and `publication_texts`.
- Successful commands do not print result JSON to stdout; use `--out` for data and logging options for progress.
- `create-atlas --out atlas.json` also writes `atlas.summary.json` with operational counts and a deterministic scientific metadata profile.
- `create-atlas --dev-trace` writes `00_run_manifest.json` through `07_summary.json` under `.dev/YYYYMMDDTHHMMSS/`, including collected/reviewed stages, pre/post harmonization metadata, targets/details, the final atlas, and summary.
- The trace includes `03_pre_harmonization_accession_metadata.json`, `04_harmonization_details.json`, and `05_post_harmonization_accession_metadata.json` for accession-level comparison and target inspection.

## Python API

Use the root orchestrator:

```python
from ThematicAtlases.atlas import Atlas

atlas = Atlas(metadata={})
```

Major orchestrator methods:

- `Atlas.collect_datasets(query=None, file=None, out=None, theme=None, review_filter="none", metadata_repositories=None, max_publications=None, reviewer=None, collect_metadata=True, generate_queries=False, max_generated_queries=3) -> dict`
  - Inputs: repeated query strings, optional query file, optional output path, repository selection, publication cap, metadata collection switch, and optional thematic review settings.
  - Output: atlas object with `accessions` and `publication_texts`.
- `Atlas.harmonize_datasets(datasets, harmonization_details_out=None, harmonization_options=None) -> dict`
  - Inputs: a `collect_datasets()` atlas object.
  - Output: an atlas whose supported `accession_metadata` values have been replaced by harmonized MINiML JSON.
- `Atlas.create_atlas(query=None, file=None, out=None, theme=None, review_filter="none", metadata_repositories=None, max_publications=None, reviewer=None, collect_metadata=True, dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=False, max_generated_queries=3, harmonization_options=None) -> dict`
  - Inputs: collection, filtering, and harmonization options.
  - Output: final atlas object, optionally written to `out`.

`Atlas` is the root orchestrator and dependency-injection boundary. Its constructor wires the collector, filterer, harmonizer, Europe PMC wrapper factory, metadata handlers, and publication text reviewer; tests and downstream applications can replace those components without changing the public workflow methods.

Query loading, generation, ordering, and validation are method-owned; the CLI only forwards `generate_queries` and `max_generated_queries`. Applications may inject `query_generator` and `credential_checker` into `Atlas`.

Advanced ontology configuration can use one Atlas-managed store:

```python
from agentic_curator.curators.ontology_harmonizer import OntoStore

store = OntoStore(storage_dir=".cache/ontologies")
store.configure_framework("snomed", remove=True)
atlas = Atlas(
    metadata={},
    ontostore=store,
    cache_ontologies=True,
)
```

`Atlas(..., ontostore=None, cache_ontologies=False)` retains lazy behavior by default. With eager caching enabled, `create_atlas()` calls `store.cache_all()` once before query generation or collection and passes the same store to the default ontology harmonizer. A custom harmonizer cannot be combined with Atlas-managed store options.

The fixed fibrosis runner enables DEBUG logging to both stdout and
`.out/fibrosis_atlas.log`. Cross-package logs expose safe stage, identifier,
attempt, status, duration, count, and periodic progress fields without logging
prompt/response bodies, publication or MINiML payloads, credentials, headers,
or request parameters.

`harmonization_options` forwards upstream controls such as `strategy`, `target_paths`, `llm`, and judge thresholds. Identical metadata/context/options are harmonized once per run. `max_workers=1` is the safe default; higher values opt into bounded parallel calls while preserving accession order. Inject `GoogleCredentialPreflight` to validate ADC/project configuration and refresh the token once without a model-generation request.

Code flow:

1. `Atlas.create_atlas()` optionally generates and merges theme queries inside the method, calls `Atlas.collect_datasets()` with collection/filtering options, then calls `Atlas.harmonize_datasets()` with the collected atlas object.
2. `AtlasCollector` loads query strings from `query` and/or a UTF-8 query file, asks `EuropePMCWrapper` to search publications and collect dataset datalinks, filters records to the selected metadata repositories, and routes each repository group to its metadata handler.
3. When metadata collection is enabled, `GEOWrapper` normalizes GEO rows to GSE-level records, drops GPL or unresolved records, preserves source datalink evidence in `original_datalinks`, deduplicates repeated GSEs, and stores `geo2json` metadata in `accession_metadata`.
4. `ArrayExpressWrapper` preserves selected ArrayExpress rows and adds placeholder repository metadata until live ArrayExpress enrichment is implemented.
5. `AtlasFilterer` accepts collected rows or an atlas-shaped object, reuses existing publication text entries, fetches missing full text or abstract fallback text through `EuropePMCWrapper`, attaches `publication_text_ref`, and returns the final object with `accessions` and `publication_texts`.
6. `PublicationTextReviewer` validates review options, reuses matching prior `agentic_curator` reviews, calls the reviewer when a theme is supplied, normalizes judgements, and removes not-relevant or unsure publications when requested.
7. `AtlasHarmonizer` builds publication context from nested titles and abstracts, calls `OntologyHarmonizer.harmonize_miniml_json()`, replaces successful `accession_metadata`, annotates unavailable/error outcomes, and optionally writes detailed target/strategy results.

Major components:

- `AtlasCollector`: query loading, Europe PMC accession collection, repository filtering, metadata-handler routing, and optional intermediate JSON output.
- `AtlasFilterer`: publication text collection, `publication_text_ref` attachment, thematic review, review-based filtering, and atlas object construction.
- `AtlasHarmonizer`: per-accession MINiML ontology harmonization, publication-context construction, failure isolation, and optional detail output.
- `EuropePMCWrapper`: publication search, datalink collection, full-text/abstract text enrichment, retry handling, and datalink XML fallback.
- `GEOWrapper`: GEO accession normalization to GSE and `geo2json` metadata enrichment.
- `ArrayExpressWrapper`: placeholder ArrayExpress metadata enrichment.
- `PublicationTextReviewer`: thematic review integration, compact 500-character MINiML context construction, review reuse, judgement parsing, and review-filter application. Full accession metadata remains stored but is not sent to the thematic-review LLM.

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
