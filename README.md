# ThematicAtlases

Build publication-driven, reviewable, and ontology-harmonized atlases of biomedical datasets.

## Description

ThematicAtlases searches Europe PMC for publications, follows their dataset links, selects supported metadata repositories, and returns atlas-shaped JSON with publication provenance. GEO accessions are normalized to GSE records and enriched with MINiML metadata; ArrayExpress routing is supported with placeholder metadata while its live fetcher remains pending.

The pipeline can fetch open-access full text with abstract fallback, review publications against a theme with `agentic-curator`, filter review outcomes, and harmonize supported metadata against ontologies. Durable SQLite checkpoints support incremental discovery, metadata collection, review, harmonization, resume, and verified archival. An accompanying `benchmark_ThematicAtlases` package measures exact DOI/PMID recall against packaged or custom reference sets.

## Installation

From the repository root, create the project virtual environment and install the package:

```bash
python3 -m venv .env
.env/bin/python -m pip install -r requirements.txt
```

For development and tests, include the development dependency group:

```bash
.env/bin/python -m pip install -e ".[dev]"
.env/bin/python -m pytest
```

The editable install provides the `thematic-atlas` console command. The equivalent module entrypoint is `.env/bin/python -m ThematicAtlases.cli_atlas`.

### Requirements

- Python 3.10 or newer.
- Git and network access during installation because `agentic-curator` and `meta-standards-converter` are Git dependencies.
- Runtime packages: `requests`, `google-auth`, `agentic-curator`, and `meta-standards-converter`.
- Google Application Default Credentials and a Google Cloud quota project for model-backed features.
- `pytest>=8` only when installing the optional `dev` dependencies.

The project is licensed under [GPL-3.0-or-later](LICENSE).

## Configuration

There is no central application configuration file. Generic workflows are configured with CLI flags or Python arguments; purpose-built fibrosis runners use repository files and constants. Explicit CLI/Python values take precedence over library defaults. On the CLI, `--theme-file` takes precedence over `--theme`, and subcommand-local logging options take precedence over global logging options.

Important defaults and configuration sources:

- Omitting `metadata_repositories` or `--metadata-repository` selects the GEO-only path. Repeat the option or pass a list to include `arrayexpress`.
- Publication review defaults to strategy `direct` and filter `none`. A non-`none` filter and `review_before_metadata` require a theme.
- Query generation is opt-in and defaults to at most three generated queries. Explicit queries come first, query-file entries follow, and generated queries are appended.
- `docs/theme_fibrosis.txt` is the fixed fibrosis theme. `config/fibrosis_discovery_queries.json` is the ordered, versioned static-query catalog used by the discovery runner.
- CLI result data is written with `--out`; logging goes to stdout unless `--log-file` is supplied. Development traces default to `.dev/`, while fixed runner artifacts are written under `.out/`.
- The repository's `.env/` directory is the Python virtual environment required by the purpose-built runners; it is not a dotenv file and is not automatically loaded as environment configuration.

Model-backed query generation, thematic review, ontology caching, semantic lookup, and judge/assignment stages require Google Application Default Credentials. Configure user credentials with:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
```

A service-account credential may be used instead. Static collection without query generation, offline benchmarking, and deterministic/offline harmonization controls do not require model credentials. There is no Docker interface or Docker configuration in this repository.

## Quickstart

The two major interfaces are the installed CLI and the Python API.

<a id="quickstart-cli"></a>
### CLI

Collect GEO datasets and publication text:

```bash
thematic-atlas collect-datasets \
  --query "human fibrosis transcriptomics" \
  --max-publications 25 \
  --out atlas_datasets.json
```

Create and harmonize an atlas end to end:

```bash
thematic-atlas create-atlas \
  --query "human fibrosis transcriptomics" \
  --out atlas.json
```

See the complete [CLI guide](#cli-guide).

<a id="quickstart-python"></a>
### Python

```python
from ThematicAtlases.atlas import Atlas

atlas = Atlas(metadata={})
result = atlas.create_atlas(
    query=["human fibrosis transcriptomics"],
    max_publications=25,
    out="atlas.json",
)
```

`result` is the same atlas object written to `atlas.json`. See the complete [Python API guide](#python-api-guide).

### Inputs & Outputs

High-level inputs are:

- One or more Europe PMC query strings, or a UTF-8 file containing one query per non-comment line.
- An optional review theme supplied inline or from a UTF-8 file.
- Repository selection (`geo` and/or `arrayexpress`), publication limits, review controls, and metadata/harmonization controls.
- For standalone harmonization, an existing atlas JSON object containing `accessions` and `publication_texts`.
- For resume and benchmark workflows, a trace directory, atlas JSON file, or reference-set JSON as appropriate.

The primary output shape is:

```json
{
  "accessions": [],
  "publication_texts": {}
}
```

Each accession retains dataset identifiers, publication provenance, repository status, and optional `accession_metadata`. The shared `publication_texts` map stores full text or abstract fallback once and is referenced by nested publications through `publication_text_ref`.

Depending on the workflow, additional outputs include:

- `atlas.summary.json`, written beside a successful `create-atlas --out atlas.json` result.
- A harmonization-details JSON sidecar when requested.
- Timestamped trace artifacts and `resume_state.sqlite` when tracing is enabled.
- Incremental review and metadata snapshots for standalone workers.
- Reference-publication recall and reference-review reports under `.out/`.

## Guide

<a id="cli-guide"></a>
### CLI guide

The installed interface is `thematic-atlas COMMAND [OPTIONS]`. It is a thin adapter over `Atlas`; successful commands do not print result JSON, so use `--out` for data and logging options for operational messages. Its wiring is documented in the [CLI codebase entry](docs/codebase.md#cli-atlas).

Global logging options may appear before or after a command:

| Option | Behavior |
| --- | --- |
| `-v`, `--verbose` | Repeatable verbosity: once enables INFO progress/statistics; twice (`-vv`) enables DEBUG request/retry/routing logs. Default: warnings only. |
| `--log-file LOG_FILE` | Write UTF-8 logs to the file instead of stdout. A command-local value overrides a global value. |

`collect-datasets` searches, filters, optionally enriches/reviews, and writes an atlas object:

```bash
thematic-atlas collect-datasets [OPTIONS]
```

| Option | Behavior |
| --- | --- |
| `--query TEXT` | Europe PMC query; repeat to preserve multiple queries in order. |
| `--file PATH` | UTF-8 query file. Blank lines and lines beginning with `#` are ignored. |
| `--out PATH` | Write the atlas JSON. If omitted, the method still runs but CLI result data is not printed. |
| `--max-publications N` | Positive global cap on raw searched publications before datalink fetching. |
| `--skip-metadata` | Keep repository-filtered accessions without calling metadata handlers. |
| `--review-before-metadata` | Review repository-filtered publications first and enrich only survivors; requires a theme. |
| `--metadata-repository {geo,arrayexpress}` | Select a repository; repeat to select both. Default: GEO only. |
| `--theme TEXT` | Inline thematic-review theme. |
| `--theme-file PATH` | Read the theme from UTF-8 text; takes precedence over `--theme`. |
| `--query-generator` | Generate additional queries from the theme; requires a theme and model credentials. |
| `--max-generated-queries N` | Positive generated-query limit; default `3` and maximum supported by `Atlas` is `3`. |
| `--review-filter {none,not-relevant,not-relevant-and-unsure}` | Remove selected review outcomes. Default `none`; removal requires a theme. |
| `--review-strategy {direct,evidence_then_judgement}` | Review contract. Default `direct`; the other choice is the legacy two-stage strategy. |

`create-atlas` accepts every collection option above, then harmonizes the result:

```bash
thematic-atlas create-atlas [OPTIONS]
```

It additionally supports:

| Option | Behavior |
| --- | --- |
| `--dev-trace` | Write a timestamped manifest, SQLite checkpoints, readable stage artifacts, final atlas, and summary. |
| `--dev-out-dir PATH` | Trace root used with `--dev-trace`; default `.dev`. |
| `--harmonization-details-out PATH` | Write per-accession harmonization status, targets, workflow, controls, paths, and errors. |

`harmonize-datasets` transforms an existing atlas file without discovery or review:

```bash
thematic-atlas harmonize-datasets \
  --file atlas_datasets.json \
  --out atlas.json \
  --harmonization-details-out harmonization_details.json
```

| Option | Behavior |
| --- | --- |
| `--file INPUT` | Required input atlas JSON. |
| `--out OUTPUT` | Required output atlas JSON. |
| `--harmonization-details-out PATH` | Optional details sidecar. |

<a id="python-api-guide"></a>
### Python API guide

Import the orchestrator directly; the package root does not re-export it:

```python
from ThematicAtlases.atlas import Atlas
```

`Atlas(...)` is the dependency-injection boundary:

```python
Atlas(
    metadata,
    epmc_wrapper_factory=None,
    metadata_handlers=None,
    metadata_repositories=None,
    publication_text_reviewer=None,
    collector=None,
    filterer=None,
    harmonizer=None,
    ontostore=None,
    cache_ontologies=False,
    query_generator=None,
    credential_checker=None,
)
```

`metadata` is retained on the instance. The factory/component arguments replace the default Europe PMC, metadata, review, collection, filtering, or harmonization collaborators. `metadata_repositories` sets the collector default. `ontostore` is shared with the default harmonizer; `cache_ontologies=True` eagerly caches it on the first full atlas run. A custom `harmonizer` cannot be combined with Atlas-managed `ontostore`/cache options. `query_generator` and `credential_checker` replace their model-facing policies. See the [Atlas workflow](docs/codebase.md#atlas-workflow).

`Atlas.collect_datasets(...)` runs discovery, metadata routing, text collection, and optional review:

```python
Atlas.collect_datasets(
    query=None, file=None, out=None, theme=None,
    review_filter="none", review_strategy="direct",
    metadata_repositories=None, max_publications=None,
    max_publications_per_query=None, reviewer=None,
    collect_metadata=True, generate_queries=False,
    max_generated_queries=3, dev_trace=False,
    dev_out_dir=".dev", run_id=None,
    review_before_metadata=False, stop_before_review=False,
)
```

- `query` is an ordered list; `file` adds queries from UTF-8 text. `max_publications` is a global raw-hit cap, while `max_publications_per_query` must align one positive integer or `None` with each ordered query.
- `theme`, `review_filter`, `review_strategy`, and an optional injected `reviewer` control thematic review.
- `metadata_repositories` selects handlers; `collect_metadata=False` skips enrichment. `review_before_metadata=True` reverses review/enrichment ordering and requires a theme.
- `generate_queries` appends up to `max_generated_queries`; generated queries and reviews require credential preflight.
- `dev_trace`, `dev_out_dir`, and optional `run_id` enable resumable checkpoints. `stop_before_review=True` writes and returns an unreviewed publication snapshot without metadata deferred by that mode.
- `out` writes the atlas-shaped return value.

`Atlas.create_atlas(...)` runs collection and then harmonization:

```python
Atlas.create_atlas(
    query=None, file=None, out=None, theme=None,
    review_filter="none", review_strategy="direct",
    metadata_repositories=None, max_publications=None,
    max_publications_per_query=None, reviewer=None,
    collect_metadata=True, dev_trace=False,
    dev_out_dir=".dev", harmonization_details_out=None,
    generate_queries=False, max_generated_queries=3,
    harmonization_options=None, review_before_metadata=False,
)
```

Collection parameters behave as above. `harmonization_options` is forwarded to the ontology workflow, and `harmonization_details_out` writes its sidecar. When `out` is provided, a summary is also written. See the [harmonizer internals](docs/codebase.md#harmonizer).

`Atlas.harmonize_datasets(...)` accepts an atlas object and returns a copy with supported metadata harmonized:

```python
Atlas.harmonize_datasets(
    datasets,
    harmonization_details_out=None,
    harmonization_options=None,
)
```

Unsupported/null metadata is retained with status `not_run`; per-accession failures retain original metadata with status `error` while later items continue.

`Atlas.resume(...)` selects a traced workflow and reuses its latest valid stage:

```python
Atlas.resume(
    dev_out_dir=".dev",
    run_id=None,
    out=None,
    stop_before_review=False,
)
```

`run_id=None` selects the newest incomplete valid trace. `out` overrides the manifest output. `stop_before_review=True` resumes only the collection snapshot.

`Atlas.amend_queries(...)` replaces one trace's query fingerprint without discarding completed item checkpoints:

```python
Atlas.amend_queries(
    dev_out_dir=TRACE_ROOT,
    run_id=RUN_ID,
    queries=QUERIES,
    max_publications_per_query=LIMITS,
)
```

The query and limit lists must be non-empty, aligned, and contain positive limits or `None`.

`Atlas.archive_existing_runs(...)` moves inactive traces and fixed artifacts into verified archives:

```python
Atlas.archive_existing_runs(
    dev_out_dir=TRACE_ROOT,
    archive_root=ARCHIVE_ROOT,
    workflow="workflow_name",
    artifact_paths=(),
)
```

It returns ordered archive paths and rejects active workflows, unsafe names, symlinks, destination collisions, and archive roots nested inside the active trace root.

Specialized public APIs are available when independently advancing or evaluating a trace:

- `PublicationTextReviewer.resume(...)`: `resume(trace_dir, theme=None, reviewer=None, strategy="direct", allow_theme_override=False) -> dict` reviews one stable datalink snapshot. See the [filterer flow](docs/codebase.md#filterer).
- `AtlasCollector.resume_metadata(...)`: `resume_metadata(trace_dir, audit_enrichment_only=False, retry_tags=None) -> dict` collects, audits, or explicitly repairs GEO metadata enrichment for one stable snapshot. See the [collector flow](docs/codebase.md#collector).
- `ThematicReviewerBenchmark`: `benchmark_reference_publication_recall(reference_set=None, reference_set_file=None, thematic_output=...) -> dict` requires exactly one packaged name or custom reference file; `available_reference_sets()` lists packaged sets and `load_reference_set(name)` returns a defensive copy. See the [benchmark package](docs/codebase.md#benchmark-package).

Library modules define loggers without configuring global logging. Applications should configure their preferred handlers and levels.

### Workflow scripts

The repository includes focused scripts built on the same Python API. They require `.env/bin/python` unless noted:

- `run_fibrosis_atlas.py [--resume [RUN_ID]]` runs or resumes the fixed full fibrosis atlas, including ontology caching, review, harmonization, summaries, and trace archival.
- `run_fibrosis_discovery.py [--generate-query | --resume [RUN_ID]] [--amend-queries]` runs collection-only discovery; query amendment requires an explicit resume ID.
- `run_publication_reviewer.py TRACE_DIR [--theme-file PATH] [--strategy {direct,evidence_then_judgement}] [--allow-theme-override] [-v|-vv]` reviews a stable growing-trace snapshot.
- `run_accession_metadata_collector.py TRACE_DIR [-v|-vv] [--audit-enrichment-only | --retry-tags PATH]` advances or audits GEO metadata independently.
- `run_reference_publication_recall.py THEMATIC_OUTPUT [--reference-set-file JSON ...] [--out PATH]` runs offline recall against all packaged sets plus optional custom sets.
- `run_reference_set_review.py [--reference-set NAME]` resolves and reviews one packaged reference set through a checkpointed diagnostic workflow.

Use `.env/bin/python SCRIPT --help` for the parser-generated command reference. Fixed fibrosis behavior and output locations are documented under [fibrosis run scripts](docs/codebase.md#fibrosis-run-script).

### Code flow

```text
CLI or Python input
  -> Atlas (query ordering, credentials, trace orchestration)
     -> `AtlasCollector`
        -> EuropePMCWrapper (search, datalinks)
        -> GEOWrapper / ArrayExpressWrapper (metadata routing)
     -> `AtlasFilterer`
        -> EuropePMCWrapper (full text or abstract fallback)
        -> `PublicationTextReviewer` (optional thematic review/filter)
     -> `AtlasHarmonizer` (optional ontology harmonization)
  -> atlas JSON + summary/details
  -> optional readable trace artifacts + resume_state.sqlite
```

The collector, filterer, and harmonizer isolate the main stages while `Atlas` owns their ordering, dependency injection, output, and resume policy. External requests are checkpointed at item boundaries during traced runs, so successful/no-data and terminal outcomes are reused while transient errors can be retried.

Implementation details: [collector](docs/codebase.md#collector), [filterer](docs/codebase.md#filterer), [Europe PMC](docs/codebase.md#epmc-wrapper), [GEO](docs/codebase.md#geo-wrapper), [ArrayExpress](docs/codebase.md#arrayexpress-wrapper), and [harmonizer](docs/codebase.md#harmonizer).

## Docs

- [Documentation index](docs/index.md) — routing index for stable codebase sections.
- [Codebase handoff](docs/codebase.md) — canonical architecture, API, workflow, and verification reference.
- [Project layout and purpose](docs/codebase.md#project-purpose-and-layout)
- [Runtime and packaging](docs/codebase.md#runtime-and-packaging)
- [Public API](docs/codebase.md#public-api)
- [Atlas workflow](docs/codebase.md#atlas-workflow)
- [CLI](docs/codebase.md#cli-atlas)
- [Test and verification status](docs/codebase.md#test-and-verification-status)

## Authors

Created by [jaychowcl](https://github.com/jaychowcl) @ [Saez-Rodriguez Group](https://saezlab.org) & [EMBL-EBI Functional Genomics Team](https://www.ebi.ac.uk/about/teams/functional-genomics/) on May 2026
