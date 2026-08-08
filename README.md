<img width="375" height="250" alt="ChatGPT Image Jul 27, 2026, 10_33_57 AM" src="https://github.com/user-attachments/assets/ea6a1467-8555-4493-8523-a2edb0ed22ff" />

# ThematicAtlases

Build publication-driven, reviewable, and ontology-harmonized atlases of biomedical datasets.

## Description

ThematicAtlases searches Europe PMC for publications, follows their dataset links, selects supported metadata repositories, and returns a validated Atlas v1 document with publication provenance. The Atlas document schema 1.0 is the public wire contract; downstream H5AD conversion uses H5AD metadata schema 1.0. GEO accessions are normalized to GSE records and enriched with MINiML metadata. ArrayExpress accessions are resolved through BioStudies and parsed in memory by MSC from IDF/SDRF into the same core plus the enriched `mage_tab.model` contract. MSC owns the nested MINiML package model and its independent `miniml_schema_version: "1.0"`; Atlas dataset metadata preserves that package unchanged.

The pipeline fetches open-access Europe PMC XML or supported bioRxiv/medRxiv JATS, deterministically discovers repository accessions from that text by default, scans abstracts when full text is unavailable, filters review outcomes, and harmonizes supported metadata against ontologies. Durable SQLite checkpoints support incremental discovery, metadata collection, review, harmonization, resume, and verified archival. An accompanying `benchmark_ThematicAtlases` package measures exact DOI/PMID recall against packaged or custom reference sets.

## Installation

From the repository root, create the project virtual environment and install the package:

```bash
python3 -m venv .env
.env/bin/python -m pip install -r requirements.txt
```

For development and tests, include the development dependency group:

```bash
.env/bin/python -m pip install -e ".[dev]"
.env/bin/python -m pytest -q
```

Public provider contracts are owned by this repository and skipped normally:

```bash
RUN_LIVE_API_TESTS=1 .env/bin/python -m pytest tests/live_api -m live_api -vv
```

The editable install provides the `thematic-atlas` console command. The equivalent module entrypoint is `.env/bin/python -m ThematicAtlases.cli_atlas`.

### Requirements

- Python 3.10 or newer.
- Installable `agentic-curator>=1.1,<2` and `meta-standards-converter>=2,<3`
  distributions. The package does not depend on sibling source checkouts or Git
  URLs at runtime or build time.
- Runtime packages: `requests`, `google-auth`, `agentic-curator`, and `meta-standards-converter`.
- Google Application Default Credentials and a Google Cloud quota project for model-backed features.
- `pytest>=8` only when installing the optional `dev` dependencies.

The project is licensed under [GPL-3.0-or-later](LICENSE).

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
  --theme "human fibrosis transcriptomics" \
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
    theme="human fibrosis transcriptomics",
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
- For standalone harmonization, a strict Atlas v1 JSON document with
  `schema_version`, `atlas`, `run`, `datasets`, `publications`, and `summary`.
- For resume and benchmark workflows, a trace directory, atlas JSON file, or reference-set JSON as appropriate.

Every public Atlas workflow returns or writes the same versioned document
shape (nested fields are abbreviated here):

```json
{
  "schema_version": "1.0",
  "atlas": {"atlas_id": "...", "title": "...", "theme": "..."},
  "run": {"run_id": "...", "created_at": "...", "config": {}, "status": "complete"},
  "datasets": [],
  "publications": [],
  "summary": {}
}
```

Atlas title and theme are always nonblank. When no explicit theme is supplied,
the producer uses the configured metadata theme, the first nonblank query, or
the title in that order.

Each dataset retains its identity, repository, lifecycle status, metadata,
publication references, reviews, harmonization records, diagnostics, and
artifacts. Publication text is normalized into `publications` and referenced by
`publication_ids`. The legacy internal stage keys `accessions` and
`publication_texts` do not cross the public workflow boundary.

Depending on the workflow, additional outputs include:

- `atlas.summary.json`, written beside a successful `create-atlas --out atlas.json` result.
- Aggregate unsupported-accession counts in Atlas summaries, plus an explicit
  detailed inventory when `--unsupported-accessions-out` is supplied.
- A harmonization-details JSON sidecar when requested.
- Timestamped trace artifacts and one `atlas_run.sqlite3` when tracing is
  enabled. Lifecycle, artifact roles, item results, retry history, and run
  metadata share that database and its transaction/checkpoint policy.
- Incremental review and metadata snapshots for standalone workers.
- Reference-publication recall and reference-review reports under `.out/`.

`ThematicAtlases.domain.AtlasDocument` is the strict exchange contract and
`ThematicAtlases.run_store.AtlasRunStore` is the normalized lifecycle and
artifact authority. The public workflow cutover is complete: v1 mappings are
not accepted by `harmonize-datasets`, and traces without `atlas_run.sqlite3`
are not silently upgraded by `resume`.

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
| `--unsupported-accessions-out PATH` | Write the separate detailed inventory of detected accessions whose repository has no supported metadata handler. If omitted, only aggregate counts are retained in a create-atlas summary or development trace. |
| `--max-publications N` | Positive global cap on raw searched publications before datalink fetching. |
| `--skip-metadata` | Keep repository-filtered accessions without calling metadata handlers. |
| `--review-before-metadata` | Review repository-filtered publications first and enrich only survivors; requires a theme. |
| `--scrape-fulltext-accessions`, `--no-scrape-fulltext-accessions` | Enable or disable deterministic accession discovery from Europe PMC XML, supported bioRxiv/medRxiv JATS, or abstract fallback. Enabled by default. |
| `--metadata-repository {geo,arrayexpress}` | Select a repository; repeat as needed. Default: GEO and ArrayExpress. |
| `--theme TEXT` | Inline thematic-review theme. |
| `--theme-file PATH` | Read the theme from UTF-8 text; takes precedence over `--theme`. |
| `--query-generator` | Generate additional queries from the theme; requires a theme and model credentials. |
| `--max-generated-queries N` | Positive generated-query limit; default `3` and maximum supported by `Atlas` is `3`. |
| `--review-filter {none,not-relevant,not-relevant-and-unsure}` | Remove selected review outcomes. Default `none`; removal requires a theme. |
| `--review-strategy {direct,evidence_then_judgement}` | Review contract. Default `direct`; the other choice is the legacy two-stage strategy. |

Publication-text discovery recognizes GEO, ArrayExpress/BioStudies, BioProject,
INSDC/SRA/ENA/DRA, BioSample, EGA, dbGaP, Broad Single Cell Portal, Synapse,
PRIDE, MetaboLights, ImmPort, and NGDC object-level accessions. It also scans
JATS link targets for curated CELLxGENE, Zenodo, Figshare, Dryad, Mendeley Data,
and Dataverse identifiers while ignoring generic cloud/file-sharing URLs. It records
`discovery_sources` and per-publication `accession_discovery_sources`, merges
case-insensitive duplicates with Europe PMC Datalinks, and then applies metadata
handler routing. Unsupported identifier families are retained in a terminal
inventory, excluded before review and harmonization, and remain absent from the
Atlas v1 datasets until a supported metadata handler is added.

The default ArrayExpress wrapper downloads BioStudies MAGE-TAB content into
memory through MSC `ae2json`, checkpoints the parsed package, and passes the
common and enriched metadata into harmonization. It creates no temporary IDF,
SDRF, or JSON files.

`create-atlas` requires a non-empty theme, defaults theme-derived query
generation and thematic review on, then harmonizes the result. Explicit
queries are followed by query-file entries and then generated queries:

```bash
thematic-atlas create-atlas [OPTIONS]
```

It additionally supports:

| Option | Behavior |
| --- | --- |
| `--query-generator`, `--no-query-generator` | Enable or disable theme-derived query generation. Enabled by default for creation. Disabling it requires at least one nonblank `--query` or query-file entry. |
| `--thematic-review`, `--no-thematic-review` | Enable or disable publication thematic review. Enabled by default. Disabling it is incompatible with a non-`none` review filter or `--review-before-metadata`. |
| `--prune-accessions`, `--no-prune-accessions` | Apply or retain accession-level exclusions returned by thematic review. Pruning is enabled by default for collection and creation. |
| `--dev-trace` | Write a timestamped manifest, SQLite checkpoints, readable stage artifacts, final atlas, and summary. |
| `--dev-out-dir PATH` | Trace root used with `--dev-trace`; default `.dev`. |
| `--harmonization-details-out PATH` | Write per-accession harmonization status, targets, workflow, controls, paths, and errors. |
| `--stop-after metadata` | Require a metadata-first development trace, publish a collection snapshot, and return before thematic review or harmonization. |

`harmonize-datasets` transforms an existing Atlas v1 file without discovery or review:

```bash
thematic-atlas harmonize-datasets \
  --file atlas_datasets.json \
  --out atlas.json \
  --harmonization-details-out harmonization_details.json
```

| Option | Behavior |
| --- | --- |
| `--file INPUT` | Required strict Atlas v1 JSON; legacy unversioned accessions envelopes fail validation. |
| `--out OUTPUT` | Required deterministic, atomically replaced Atlas v1 JSON. |
| `--harmonization-details-out PATH` | Optional details sidecar. |

`resume` continues a traced run and can first requeue selected checkpoint
boundaries:

```bash
thematic-atlas resume --dev-out-dir .dev --run-id RUN_ID [OPTIONS]
```

| Option | Behavior |
| --- | --- |
| `--dev-out-dir PATH` | Trace root containing the run; default `.dev`. |
| `--run-id ID` | Run to resume. If omitted, the most recent run is used. |
| `--out PATH` | Write the resumed atlas JSON. |
| `--stop-before-review` | Resume collection only and stop before thematic review. |
| `--retry-stage STAGE` | Requeue all retryable items at a registered stage; repeat for multiple stages. |
| `--retry-item STAGE:ITEM_ID` | Requeue one checkpoint item; repeat for multiple items. |
| `--retry-degraded-stage STAGE` | Requeue harmonization items degraded at the named internal stage; repeat as needed. |

`fork-run` safely clones a trace paused after metadata for different downstream
review or harmonization configuration:

```bash
thematic-atlas fork-run \
  --dev-out-dir .dev \
  --run-id SOURCE \
  --new-run-id ALTERNATE \
  --config fork.json
```

| Option | Behavior |
| --- | --- |
| `--dev-out-dir PATH` | Trace root containing the source and destination runs. |
| `--run-id ID` | Required metadata-paused source run. |
| `--new-run-id ID` | Required unused destination identity. |
| `--config PATH` | Required JSON object containing downstream-only overrides. |

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
    document_adapter=None,
    artifact_publisher=None,
)
```

`metadata` is retained on the instance. The factory/component arguments replace the default Europe PMC, metadata, review, collection, filtering, or harmonization collaborators. `metadata_handlers=None` selects the built-in handlers, while an explicit empty mapping disables all handlers. `metadata_repositories` sets the collector default. `ontostore` is shared with the default harmonizer; `cache_ontologies=True` eagerly caches it on the first full atlas run. A custom `harmonizer` cannot be combined with Atlas-managed `ontostore`/cache options. `query_generator` and `credential_checker` replace their model-facing policies. `document_adapter` isolates mature stage mappings from Atlas v1, while `artifact_publisher` provides an injectable crash-durable generation boundary for JSON bundles. These collaborators implement the protocols in `ThematicAtlases.ports`; `AtlasDocumentService` owns the application-level assembly, projection, summary, and publication use case. See the [Atlas workflow](docs/codebase.md#atlas-workflow).

For new integrations, construct or load `AtlasDocument` rather than assembling
fragmented dictionaries. `AtlasDocument.load(path)` validates the v1 wire
contract; `document.dump(path)` performs deterministic atomic JSON publication.
The owner-produced golden wire fixture at
`tests/fixtures/contracts/atlas-document-v1.json` is the compatibility input
downstream repositories should copy and consume in their contract tests.
`AtlasRunStore(path)` creates a normalized `atlas_run.sqlite3` and rejects a
legacy `resume_state.sqlite` instead of silently converting it. New traced
runs create only `atlas_run.sqlite3`; `DevTraceWriter.checkpoint_store` binds
the mature item/retry API to that same database. Transactional compatibility
triggers project current work, replaced attempts, and run metadata into the
normalized `work_items`, `attempts`, and `run_metadata` tables, so lifecycle
and work cannot drift across files or representations. The standalone
reference-review runner is not an Atlas run and retains its own local
checkpoint database.

`Atlas.collect_datasets(...)` runs discovery, metadata routing, text collection, and optional review:

```python
Atlas.collect_datasets(
    query=None, file=None, out=None, theme=None,
    review_filter="none", review_strategy="direct",
    prune_accessions=True,
    metadata_repositories=None, max_publications=None,
    max_publications_per_query=None, reviewer=None,
    collect_metadata=True, generate_queries=False,
    max_generated_queries=3, dev_trace=False,
    dev_out_dir=".dev", run_id=None,
    review_before_metadata=False, stop_before_review=False,
    scrape_fulltext_accessions=True,
    unsupported_accessions_out=None,
)
```

- `query` is an ordered list; `file` adds queries from UTF-8 text. `max_publications` is a global raw-hit cap, while `max_publications_per_query` must align one positive integer or `None` with each ordered query.
- `theme`, `review_filter`, `review_strategy`, `prune_accessions`, and an optional injected `reviewer` control thematic review. The default direct strategy uses agentic-curator revision 2: one model-authored criterion catalog derived from the theme, one assessment per associated accession, and model-authored accession/publication decisions with explicit exclusion bases and accession-specific evidence for qualifying calls. `prune_accessions=True` removes a rejected publication–accession association and drops the accession only when no publication associations remain; `review_filter` independently controls whole-publication judgements. Trace output retains the catalog and assessments; Atlas v1 keeps its stable publication-level relevance projection.
- `metadata_repositories` selects handlers; `collect_metadata=False` skips enrichment. `review_before_metadata=True` reverses review/enrichment ordering and requires a theme.
- `generate_queries` appends up to `max_generated_queries`; generated queries and reviews require credential preflight.
- `dev_trace`, `dev_out_dir`, and optional `run_id` enable resumable checkpoints. `stop_before_review=True` writes and returns an unreviewed publication snapshot without metadata deferred by that mode.
- `scrape_fulltext_accessions=True` supplements Europe PMC Datalinks with registry accessions discovered in available full text; set it to `False` for Datalinks-only discovery.
- `unsupported_accessions_out` optionally writes the terminal unsupported inventory; omitting it keeps normal collection output limited to Atlas v1 while traced runs retain the inventory internally.
- `out` transactionally writes the same Atlas v1 mapping returned in memory.

`Atlas.create_atlas(...)` runs collection and then harmonization:

```python
Atlas.create_atlas(
    query=None, file=None, out=None, theme=None,
    review_filter="none", review_strategy="direct",
    prune_accessions=True,
    metadata_repositories=None, max_publications=None,
    max_publications_per_query=None, reviewer=None,
    collect_metadata=True, dev_trace=False,
    dev_out_dir=".dev", harmonization_details_out=None,
    generate_queries=True, max_generated_queries=3,
    harmonization_options=None, review_before_metadata=False,
    scrape_fulltext_accessions=True,
    unsupported_accessions_out=None,
    thematic_review=True,
    stop_after=None,
)
```

Creation requires a nonblank `theme`. Query generation defaults on; when it
is disabled, `query` and/or `file` must provide at least one nonblank query.
`thematic_review=True` is independent of generation and may be disabled to
avoid review model calls; disabled review requires `review_filter="none"` and
`review_before_metadata=False`. `harmonization_options` is forwarded to the
ontology workflow, and `harmonization_details_out` writes its sidecar. When
`out` is provided, the Atlas v1 document and derived summary are staged,
validated, and published as one immutable generation selected by an atomically
replaced `.artifact-bundles/<bundle>/current.json` pointer. Direct output files
remain compatibility views and are restored on failed publication. The summary
always reports unsupported counts; the detailed report is published only for
`unsupported_accessions_out` or retained in a development trace. See the
[harmonizer internals](docs/codebase.md#harmonizer).

Set `stop_after="metadata"` with `dev_trace=True`, `collect_metadata=True`, and
`review_before_metadata=False` to search, collect publication text, download
repository metadata, and return before thematic review or harmonization. The
trace registers `collection_snapshot.json`; a normal `resume()` continues the
same `create-atlas` run without repeating completed collection work.

`Atlas.harmonize_datasets(...)` accepts an Atlas v1 mapping and returns a
validated Atlas v1 copy with supported metadata harmonized. Legacy unversioned stage
mappings fail closed:

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
    retry_stages=None,
    retry_items=None,
    retry_degraded_stages=None,
)
```

`run_id=None` selects the newest incomplete valid v1 trace. New run IDs combine
UTC microsecond time with random entropy, so concurrently started runs do not
collide while directory names remain chronologically sortable. `out` overrides
the manifest output. `stop_before_review=True` resumes only the collection
snapshot. A trace without authoritative `atlas_run.sqlite3` is incompatible
and must be handled explicitly rather than silently migrated.
`retry_stages` requeues complete registered boundaries, `retry_items` maps
stage names to item IDs, and `retry_degraded_stages` requeues harmonization
items whose recorded quality status names the selected internal stage.

`Atlas.fork_run(...)` safely branches a metadata-paused trace for alternate
downstream processing:

```python
Atlas.fork_run(
    dev_out_dir=".dev", run_id="source", new_run_id="alternate",
    overrides={"theme": "alternate theme", "harmonization_options": {}},
)
```

Only theme/review controls, harmonization controls, and output paths may change.
Queries, limits, repositories, and collection settings remain immutable. Use
`thematic-atlas fork-run --run-id SOURCE --new-run-id DEST --config fork.json`
for the equivalent CLI workflow; manual trace copying is unsupported because
the SQLite ledger embeds the run identity and fingerprint.

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

It returns ordered archive paths and rejects active workflows, unsafe names, symlinks, destination collisions, and archive roots nested inside the active trace root. Published directories and their parent are fsynced before sources are removed. If publication succeeds but durability or cleanup finalization fails, `ArchiveDurabilityError.destination` identifies the already-published archive and the original sources are retained whenever cleanup has not begun.

Specialized public APIs are available when independently advancing or evaluating a trace:

- `PublicationTextReviewer.resume(...)`: `resume(trace_dir, theme=None, reviewer=None, strategy="direct", allow_theme_override=False) -> dict` reviews one stable datalink snapshot. See the [filterer flow](docs/codebase.md#filterer).
- `AtlasCollector.resume_metadata(...)`: `resume_metadata(trace_dir, audit_enrichment_only=False, retry_tags=None) -> dict` collects, audits, or explicitly repairs GEO metadata enrichment for one stable snapshot. See the [collector flow](docs/codebase.md#collector).
- `ThematicReviewerBenchmark`: `benchmark_reference_publication_recall(reference_set=None, reference_set_file=None, thematic_output=...) -> dict` requires exactly one packaged name or custom reference file; `available_reference_sets()` lists packaged sets and `load_reference_set(name)` returns a defensive copy. See the [benchmark package](docs/codebase.md#benchmark-package).

Lower-level supported types are documented exhaustively in the
[public API reference](docs/codebase.md#public-api-reference):
`CheckpointStore`, `EuropePMCWrapper`, `GEOWrapper`, `ArrayExpressWrapper`,
`AtlasFilterer`, `AtlasHarmonizer`, trace helpers, enrichment helpers, and all
formally exported constants and methods.

Library modules define loggers without configuring global logging. Applications should configure their preferred handlers and levels.

### Workflow scripts

Non-canonical fibrosis runners are archived locally under the ignored
`.dev/archive/fibrosis-workflows-2026-08-03/` directory. They are no longer
supported repository-root entry points and are intentionally absent from
version control. The canonical production workflow is
`gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py` in the parent
adapter repository.

This repository continues to support the installed `thematic-atlas` CLI and
the importable Python APIs. The retained fibrosis theme, discovery-query
catalog, benchmark implementation, and reference sets remain available as
reusable inputs. See the [archived fibrosis runner record](docs/codebase.md#fibrosis-run-script).

### Configuration

There is no central application configuration file. Generic workflows are
configured with CLI flags or Python arguments. Explicit CLI/Python values take
precedence over library defaults. On the CLI, `--theme-file` takes precedence over
`--theme`, and subcommand-local logging options take precedence over global
logging options.

Important defaults and configuration sources:

- Omitting `metadata_repositories` or `--metadata-repository` selects both GEO
  and ArrayExpress. Pass an explicit list to restrict collection.
- Publication review defaults to strategy `direct` and filter `none`. A
  non-`none` filter and `review_before_metadata` require a theme.
- Query generation is opt-in and defaults to at most three generated queries.
  Explicit queries come first, query-file entries follow, and generated queries
  are appended.
- `docs/theme_fibrosis.txt` is a retained fibrosis reference theme.
  `config/fibrosis_discovery_queries.json` is the ordered, versioned static
  query catalog retained from the archived discovery workflow. All four per-query caps are
  10,000: at most 40,000 raw hits before cross-query deduplication. The static
  queries do not require Europe PMC data- or lablink flags.
  Generated-query mode does not use those four static caps; it
  generates at most three queries and leaves the global publication cap unset.
- CLI data is written with `--out`; logging goes to stdout unless `--log-file`
  is supplied. Traces default to `.dev/`.
- `.env/`, when present, is a Python virtual environment, not a dotenv file,
  and is not loaded as environment configuration.

Model-backed query generation, thematic review, ontology caching, semantic
lookup, and judge/assignment stages require Google Application Default
Credentials:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
```

A service-account credential may be used instead. Static collection without
query generation, offline benchmarking, and deterministic/offline
harmonization controls do not require model credentials. There is no Docker interface
or Docker configuration in this repository.

### Code flow

```text
CLI or Python input
  -> Atlas (query ordering, credentials, trace orchestration)
     -> `AtlasCollector`
        -> EuropePMCWrapper (search, datalinks, publication-text accession scan)
        -> GEOWrapper / ArrayExpressWrapper (metadata routing)
     -> `AtlasFilterer`
        -> EuropePMCWrapper (full text or abstract fallback)
        -> `PublicationTextReviewer` (optional thematic review/filter)
     -> `AtlasHarmonizer` (optional ontology harmonization)
  -> AtlasDocumentAdapter -> validated AtlasDocument v1
  -> AtlasDocumentService
     -> JsonArtifactBundlePublisher -> Atlas JSON + derived summary/details
  -> optional readable trace artifacts
     + atlas_run.sqlite3 (lifecycle, artifacts, item results, retries)
```

The [Atlas orchestrator](docs/codebase.md#orchestrators-and-core-types) owns
ordering, dependency injection, output, and resume policy. External requests
are checkpointed at item boundaries during traced runs, so successful/no-data
and terminal outcomes are reused while transient errors can be retried. See all
[eight supported workflows and the archived-runner record](docs/codebase.md#principal-workflows).

Implementation details: [collector](docs/codebase.md#collector), [filterer](docs/codebase.md#filterer), [Europe PMC](docs/codebase.md#epmc-wrapper), [GEO](docs/codebase.md#geo-wrapper), [ArrayExpress](docs/codebase.md#arrayexpress-wrapper), and [harmonizer](docs/codebase.md#harmonizer).

## Testing

The deterministic, network-blocked suite was last verified on 2026-08-04:
`486 passed, 4 skipped`. The skipped tests are the explicitly opt-in live API
provider contracts. Normal tests inject all HTTP, LLM, embedding, ontology,
and metadata collaborators and do not make external calls.

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python -m pytest -p no:cacheprovider
```

## Docs

- [Documentation index](docs/index.md) — routing index for stable codebase sections.
- [Codebase handoff](docs/codebase.md) — canonical architecture, API, workflow, and verification reference.
- [Architecture and boundaries](docs/codebase.md#architecture)
- [Public API reference](docs/codebase.md#public-api-reference)
- [Principal workflows](docs/codebase.md#principal-workflows)
- [Extension guidance](docs/codebase.md#extension-and-change-guidance)

## Authors

Created by [jaychowcl](https://github.com/jaychowcl) @ [Saez-Rodriguez Group](https://saezlab.org) & [EMBL-EBI Functional Genomics Team](https://www.ebi.ac.uk/about/teams/functional-genomics/) on May 2026
