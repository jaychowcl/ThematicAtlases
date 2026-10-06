<img width="375" height="250" alt="ChatGPT Image Jul 27, 2026, 10_33_57 AM" src="https://github.com/user-attachments/assets/ea6a1467-8555-4493-8523-a2edb0ed22ff" />

# ThematicAtlases

Build publication-driven, reviewable, and ontology-harmonized atlases of biomedical datasets.

## Description

ThematicAtlases searches Europe PMC for publications, follows their dataset links, selects supported metadata repositories, and returns a validated Atlas v1 document with publication provenance. New output uses Atlas document schema 1.1; readers accept 1.0 and 1.1. downstream H5AD conversion uses H5AD metadata schema 1.0. GEO accessions are normalized to GSE records and enriched with MINiML metadata. ArrayExpress accessions are resolved through BioStudies and parsed in memory by MSC from IDF/SDRF into the same MSC MINiML 3.1 model, including native `series.protocols` and `series.assay_paths`. MSC owns the nested package model and its independent `miniml_schema_version: "3.1"`; ThematicAtlases validates each package and transports its canonical JSON representation. MSC MINiML 3.0 and 3.1 are accepted and new output is normalized to 3.1; older package versions must be regenerated or converted before loading.

The pipeline fetches open-access Europe PMC XML or supported bioRxiv/medRxiv JATS, deterministically discovers repository accessions from that text by default, scans abstracts when full text is unavailable, filters review outcomes, and harmonizes supported metadata against ontologies. Durable SQLite checkpoints support incremental discovery, metadata collection, review, harmonization, resume, and verified archival. An accompanying `benchmark_ThematicAtlases` package separately measures raw query-result recall, post-discovery/review recall, and labeled thematic-review classification.

Europe PMC Datalinks discovery starts with the default XML representation. A
failed XML attempt waits for the configured request interval before trying
JSON; when both formats fail retryably, bounded backoff restarts the next round
at XML. Provider `Retry-After` and throttle responses can lengthen, but never
shorten, the configured interval. Valid empty XML is authoritative, while XML
security and size failures remain fail closed.

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
- Installable `agentic-curator>=4.4,<5` and `meta-standards-converter>=6,<7`
  distributions. The package does not depend on sibling source checkouts or Git
  URLs at runtime or build time.
- Runtime packages: `requests`, `google-auth`, `agentic-curator`, and `meta-standards-converter`.
- Google Application Default Credentials and a Google Cloud quota project for model-backed features.
- `pytest>=8` only when installing the optional `dev` dependencies.

`dependency-provenance/` contains the exact Python 3.12/Linux x86_64 PEP 751
lock for external runtime distributions and its deterministic CycloneDX 1.6
SBOM; every selected artifact has a real SHA-256. Internal Agentic Curator and
MSC wheels remain separately revision/hash/signature governed. The composing
adapter validates these artifacts and persists their digests in fibrosis-run
provenance. Release policy requires a verified signed artifact manifest and an
approved offline advisory snapshot no older than seven days; it remains
fail-closed until a trusted operator supplies them. Security-update SLAs are
2/7/30/90 days for critical/high/medium/low findings.

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
- For resume and benchmark workflows, a trace directory, atlas JSON file,
  recall-reference TSV, or labeled publication-identifier CSV as appropriate.

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
- One-shot text/scrape, PubMed-GDS graph, metadata, and review worker snapshots.
- Reference-publication recall and reference-review reports under `.out/`.

`ThematicAtlases.domain.AtlasDocument` is the strict exchange contract and
`ThematicAtlases.run_store.AtlasRunStore` is the normalized lifecycle and
artifact authority. The public workflow cutover is complete: v1 mappings are
not accepted by `harmonize-datasets`, and traces without `atlas_run.sqlite3`
are not silently upgraded by `resume`.

## Guide

<a id="cli-guide"></a>
### CLI guide

`--max-review-criteria N` sets the positive maximum catalogue size (default 12).

The installed interface is `thematic-atlas COMMAND [OPTIONS]`. It is a thin adapter over `Atlas`; successful commands do not print result JSON, so use `--out` for data and logging options for operational messages. Its wiring is documented in the [CLI codebase entry](docs/codebase.md#cli-atlas).

Global logging options may appear before or after a command:

| Option | Behavior |
| --- | --- |
| `-v`, `--verbose` | Repeatable verbosity: once enables INFO progress/statistics; twice (`-vv`) enables DEBUG request/retry/routing logs. Default: warnings only. |
| `--log-file LOG_FILE` | Write UTF-8 logs to the file instead of stdout. A command-local value overrides a global value. |

Every command also accepts the shared resource controls:

| Option | Behavior |
| --- | --- |
| `--resource-profile {standard,large}` | Select typed network, file, cache, and worker ceilings. Default: `standard`. |
| `--resource-override FIELD=VALUE` | Override one numeric profile field explicitly; repeat for multiple fields. Unknown fields and non-positive values fail before workflow work. |

The standard profile allows 3 redirects, 10-second connect/60-second read
timeouts, 128 MiB XML, 256 MiB compressed archives, 1 GiB expanded archives,
3 GiB per ontology file, 100 GiB matrices/H5AD, 200 GiB aggregate downloads,
250 GiB cache, four network workers, and one ontology-build worker. The large
profile allows 5 redirects, 30/300-second timeouts, 512 MiB XML, 1 GiB
compressed archives, 4 GiB expanded archives, 5 GiB per ontology file,
500 GiB matrices/H5AD, 1 TiB aggregate downloads, 500 GiB cache, eight network
workers, and two ontology-build workers. Byte ceilings limit stored objects,
files, decoded payloads, or transfer totals at the component that consumes
them; they do not reserve that amount of RAM. Disk-writing delegated
components preflight the required capacity with at least 10% headroom.
For non-identity `Content-Encoding`, the transport `Content-Length` bounds the
encoded response but is not compared with the decoded bytes produced by
`requests`; decoded response and aggregate limits still apply. This keeps
compressed Europe PMC and bioRxiv/medRxiv full text both usable and bounded.

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
| `--scrape-fulltext-accessions`, `--no-scrape-fulltext-accessions` | Enable or disable deterministic accession discovery from Europe PMC XML, supported bioRxiv/medRxiv JATS, or abstract fallback. Enabled by default. Official PubMed→GDS→GSE discovery remains enabled in either mode. |
| `--metadata-repository {geo,arrayexpress}` | Select a repository; repeat as needed. Default: GEO and ArrayExpress. |
| `--theme TEXT` | Inline thematic-review theme. |
| `--theme-file PATH` | Read the theme from UTF-8 text; takes precedence over `--theme`. |
| `--query-generator` | Generate additional queries from the theme; requires a theme and model credentials. |
| `--max-generated-queries N` | Positive generated-query limit; default `3` and maximum supported by `Atlas` is `3`. |
| `--review-filter {none,not-relevant,not-relevant-and-unsure}` | Remove selected review outcomes. Default `none`; removal requires a theme. |
| `--review-strategy direct` | Review contract. Direct grounded review is the only supported strategy. |

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
memory through MSC `Converter.convert()`, checkpoints the completed conversion, and passes the
common and enriched metadata into harmonization. It creates no temporary IDF,
SDRF, or JSON files. The selected typed resource profile is propagated into
MSC, whose fetcher enforces HTTPS/public-host egress, bounded redirects,
per-file and aggregate transfer ceilings, and bounded parsing.

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
| `--prune-accessions` | Explicitly apply grounded accession-level exclusions returned by thematic review. Destructive pruning is disabled by default. |
| `--dev-trace` | Write a manifest, SQLite checkpoints, final atlas and lightweight reports using workflow contract 2.0. |
| `--debug-snapshots` | Also write intermediate JSON views; default off. Resume uses SQLite. |
| `--dev-out-dir PATH` | Trace root used with `--dev-trace`; default `.dev`. |
| `--harmonization-details-out PATH` | Write per-accession harmonization status, targets, workflow, controls, execution identity, paths, and errors. |
| `--stop-after STAGE` | Require a development trace and pause after `query-results`, `datalinks`, `publication-text`, `fulltext-accessions`, `accession-graph`, `metadata`, `review`, or `harmonization`. Each pause writes canonical SQLite state plus `pause_<stage>_summary.json`. |

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
| `--review-decisions-file PATH` | Optional validated prune-only review-decision JSON. Only the matching MINiML source fingerprint is rerun. |

New traces use [workflow checkpoint contract 2.0](docs/codebase.md#workflow-checkpoints-v2).
GEO and ArrayExpress call MSC `Converter.convert()` with standard enrichment and
related-study expansion. Valid partial results are retained; retry a study explicitly
with `--retry-item metadata_conversion:geo:GSE123` (or `arrayexpress:E-MTAB-123`).
`fulltext-accessions` aliases the completed `publication-text` boundary. Old traces
require a separate migration and are rejected before writes. Worker paths are
`<dev_out_dir>/<run_id>`, including roots explicitly named `runs`.

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
| `--stop-after STAGE` | Advance to any of the eight durable boundaries accepted by `create-atlas`. A target already passed is a successful no-op; it never rolls state back. |
| `--retry-stage STAGE` | Requeue all retryable items at a registered stage; repeat for multiple stages. |
| `--retry-item STAGE:ITEM_ID` | Requeue one checkpoint item; repeat for multiple items. |
| `--retry-degraded-stage STAGE` | Requeue harmonization items degraded at the named internal stage; repeat as needed. |
| `--review-decisions-file PATH` | Apply review decisions for this run. A mismatched run ID or stale MINiML source fingerprint fails before publication. |

`worker-snapshot` advances one bounded actionable sidecar frontier and prints a
JSON summary:

```bash
thematic-atlas worker-snapshot \
  --dev-out-dir .dev --run-id RUN_ID \
  --stage {text,graph,metadata,review} [--item-limit N]
```

| Option | Behavior |
| --- | --- |
| `--dev-out-dir PATH` | Trace root containing the run. |
| `--run-id ID` | Required exact trace identity. |
| `--stage {text,graph,metadata,review}` | Run one stage-specific one-shot frontier. |
| `--item-limit N` | Positive cap applied to actionable work, not the scanned prefix. |

The limit is applied after compatible, completed, prerequisite-blocked, and
future-cooldown items are removed. Exit `0` means complete/no work, `2` means
busy, yielded, interrupted, or deferred work, and `1` means a safe outer
failure. SIGINT and SIGTERM request cooperative cancellation: the current
atomic item or model call finishes, an interruption event and progress summary
are committed, and all locks are released. Cancellation observed while a
frontier or merged-accession snapshot is still being built stops before any
provider item or model action is claimed.

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

`collect_datasets` and `create_atlas` accept `max_review_criteria=12`; it is a maximum, not a requested count.

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
    capability_registry=None,
    resource_profile="standard",
    resource_overrides=None,
    runtime_provenance=None,
    run_lifecycle=None,
    ncbi_api_key=None,
    ncbi_tool="ThematicAtlases",
    ncbi_email=None,
)
```

`debug_snapshots=False` is an optional constructor argument; set it to `True` to write intermediate JSON views. `metadata` is retained on the instance. The factory/component arguments replace the default Europe PMC, metadata, review, collection, filtering, or harmonization collaborators. `metadata_handlers=None` selects the built-in handlers, while an explicit empty mapping disables all handlers. `metadata_repositories` sets the collector default. `capability_registry` supplies the immutable GEO/ArrayExpress routing and review-identity contract. `resource_profile` selects the typed `standard`/`large` ceiling set and `resource_overrides` applies explicit numeric changes before the same profile object is propagated to default wrappers, the harmonizer, and ontology store. Traced creation stores the fully resolved profile in its manifest and Atlas run options. `runtime_provenance` accepts a JSON-compatible mapping for composing applications to persist script, dependency, and authorization identity through the same trace and Atlas boundaries. `ontostore` is shared with the default harmonizer; `cache_ontologies=True` eagerly caches it on the first full atlas run. A custom `harmonizer` cannot be combined with Atlas-managed `ontostore`/cache options. `query_generator` and `credential_checker` replace their model-facing policies. `document_adapter` isolates mature stage mappings from Atlas v1, while `artifact_publisher` provides an injectable crash-durable generation boundary for JSON bundles. `run_lifecycle` is an internal extension/test seam for run identity, resume selection, checkpoint-contract reconciliation, archival, and resumed publication. The public `resolve_resume_run_directory(dev_out_dir, run_id)` helper gives external runners the same explicit-or-latest-incomplete trace selection used by `Atlas.resume`. The default Europe PMC and GEO wrappers similarly delegate pure record rules to injectable `PublicationRecordPolicy` and `GEORecordPolicy` collaborators while retaining all existing wrapper methods. These collaborators implement or support the boundaries in `ThematicAtlases.ports`; `AtlasDocumentService` owns the application-level assembly, projection, summary, and publication use case. See the [Atlas workflow](docs/codebase.md#atlas-workflow).

The optional NCBI identity is forwarded to every Atlas-owned E-utilities
caller. If `ncbi_api_key` is omitted, `NCBI_API_KEY` may supply it without
changing conservative throughput; the key and request parameters are never
logged. Missing contact email warns once and retains unauthenticated pacing.

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
    prune_accessions=False,
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
- `theme`, `review_filter`, `review_strategy`, `prune_accessions`, and an optional injected `reviewer` control thematic review. The default direct strategy uses agentic-curator revision 5 and evidence contract 2: it derives one theme-level criterion catalogue, caches that catalogue by reviewer identity, and passes it unchanged to every publication review. Each publication returns one assessment per associated accession and exact caller-verified quote evidence containing only source kind and source ID. An applied accession exclusion requires high confidence and a verified failed criterion tied to that accession. Pruning defaults off; explicit `prune_accessions=True` removes a rejected publication–accession association and drops the accession only when no publication associations remain. `review_filter` independently controls whole-publication judgements. Review contract 11 fingerprints the fixed catalogue, criterion cap and policy implementation; trace output retains it with assessments and the evidence contract version, while Atlas 1.1 retains publication confidence/policy and projects weak negative judgements as unknown.
- `metadata_repositories` selects handlers; `collect_metadata=False` skips enrichment. `review_before_metadata=True` reverses review/enrichment ordering and requires a theme.
- `generate_queries` appends up to `max_generated_queries`; generated queries and reviews require credential preflight.
- `dev_trace`, `dev_out_dir`, and optional `run_id` enable resumable checkpoints. `stop_before_review=True` writes and returns an unreviewed publication snapshot without metadata deferred by that mode.
- `scrape_fulltext_accessions=True` supplements Europe PMC Datalinks with registry accessions discovered in available publication text. Official PubMed→GDS links are also resolved to exact GEO Series by default. Setting this option to `False` disables only text scanning; Datalinks and the PubMed→GDS graph remain active.
- `unsupported_accessions_out` optionally writes the terminal unsupported inventory; omitting it keeps normal collection output limited to Atlas v1 while traced runs retain the inventory internally.
- `out` transactionally writes the same Atlas v1 mapping returned in memory.

`Atlas.create_atlas(...)` runs collection and then harmonization:

```python
Atlas.create_atlas(
    query=None, file=None, out=None, theme=None,
    review_filter="none", review_strategy="direct",
    prune_accessions=False,
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

Set `stop_after` with `dev_trace=True` to pause at `query-results`, `datalinks`,
`publication-text`, `fulltext-accessions`, `accession-graph`, `metadata`,
`review`, or `harmonization`. Metadata and later targets require
`collect_metadata=True`; the metadata target also requires metadata-first
ordering. The trace registers `collection_snapshot.json`, records a
`run_paused` event, and writes an atomic `pause_<stage>_summary.json` while
SQLite remains canonical. A later `resume(..., stop_after=...)` may advance to
another boundary without repeating compatible checkpoints.

`Atlas.harmonize_datasets(...)` accepts an Atlas v1 mapping and returns a
validated Atlas v1 copy with supported metadata harmonized. Legacy unversioned stage
mappings fail closed:

```python
Atlas.harmonize_datasets(
    datasets,
    harmonization_details_out=None,
    harmonization_options=None,
    review_decisions=None,
)
```

The default Agentic Curator 4.3 path emits an MSC-owned, source-bound
`MINiMLHarmonizationPatch` 3.1. Applying it preserves raw metadata, writes
occurrence-local `hz_*` groups, and retains package-local applied fragments
under `extensions.msc_harmonization`; `annotations` arrays are not emitted.
The extension is transported unchanged through Atlas documents, checkpoints,
resume, trace artifacts, and publication, while detailed target/resolution
traces remain separate. Semantic
candidate labels are the model's primary decision surface, optional ontology
and accession values disambiguate only collisions, split-derived targets are
additive, extension fields remain run-local, and hierarchy enrichment is on
through depth two for every matched ontology.
Semantic retrieval aliases remain attached to their source targets in the
readable details sidecar and canonical harmonization checkpoint; they expand
lookup only and never directly create a harmonized value. Harmonization and
projection durations are emitted as structured INFO logs rather than persisted
checkpoint fields, preserving deterministic work identities while allowing
stage-level runtime analysis.

Every accession receives `ontology_harmonization_status`, a status contract
2.0 envelope with independent `execution`, `completeness`,
`evidence_confidence`, `validation`, and `publication` axes. Unsupported or
null metadata is retained with execution `not_run`; per-accession failures
retain original metadata with execution `failed` and a persistence-safe error
envelope while later items continue. The legacy
`ontology_harmonization_run_status` projection remains `not_run`, `error`, or
`completed` for compatibility, but it is not the authoritative quality or
publication decision.

Eligible harmonization work keys and completed details bind the upstream
execution identity: model/generation configuration, prompt digests, embedding
model, ontology sources and indexes, strategy settings, and preprocessing
revision. A change to any of these scientifically material inputs invalidates
the prior checkpoint. Injected legacy adapters receive a best-effort identity
based on their implementation and declared store preferences.

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
    review_decisions=None,
    stop_after=None,
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
items whose status 2.0 execution is `degraded` and whose recorded workflow
names the selected internal stage.
`review_decisions` is the validated JSON contract written for pending
prune-only fields. Its run ID must equal the resumed run, and its source
fingerprint changes only the matching harmonization work key; unaffected
datasets continue to reuse their checkpoints. Partial decisions leave the
remaining items pending and publication disposition review-required.

`TraceStageWorker` advances one fixed frontier in a traced run without owning
harmonization or publication:

```python
from ThematicAtlases.stage_worker import TraceStageWorker

result = TraceStageWorker(
    epmc_wrapper_factory=epmc_wrapper_factory,
    collector_factory=collector_factory,
    publication_text_reviewer_factory=reviewer_factory,
).resume(trace_dir, stage="graph", item_limit=100)
```

The four stages are `text` (publication retrieval plus deterministic accession
scraping), `graph` (PubMed ELink plus GDS summaries), `metadata`, and `review`.
Workers are one-shot and share canonical item checkpoints with the main Atlas.
They may run while the main process remains in Datalinks, or against an
explicitly paused trace; they finish one in-flight item and then yield when the
main stage advances. Per-run/stage singleton locks and ordered per-item locks
prevent duplicate provider calls. Review admits only publications whose
text/scrape and graph frontiers are terminal and whose supported metadata is
available, partial, or authoritatively unavailable.
Each worker first builds a due-retry/missing/stale actionable frontier and only
then applies `item_limit`, so completed prefixes cannot starve later work.
Frontier and merged-evidence scans check cooperative cancellation between
records, avoiding a long pre-claim shutdown delay on large traces.
Summaries preserve the legacy selected/completed/deferred keys and add scanned,
actionable, claimed, reused, prerequisite/cooldown deferred, remaining,
provider-attempt, retry, rate-wait, and interruption fields.
Metadata counters include nested MSC GEO download and PubMed/SRA/ENA enrichment
attempts and count each cumulative requester delta once. Europe PMC
fullTextXML 404 responses retain abstract fallback text but are terminal
authoritative unavailability, so they cannot consume later worker limits.

All HTTP clients share MSC's per-user, cross-process `HostRequestGate` for every
actual attempt and redirect. NCBI and Europe PMC starts are spaced by 0.5
seconds; bioRxiv/medRxiv, GEO FTP, ENA, and BioStudies use one second. Numeric
or HTTP-date `Retry-After` cooldowns persist across processes. Cooldowns beyond
the inline worker budget become retryable checkpoints with `next_retry_at`
instead of long sleeps. Transport errors, 403/429, and 5xx responses use bounded
exponential full jitter. The model boundary additionally permits one concurrent
call and one start per second for each provider/project/location/model identity.

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

`Atlas.migrate_discovery_run(...)` is the narrow upgrade path for a stopped
pre-PubMed-GDS trace that is still in its Datalinks phase:

```python
Atlas.migrate_discovery_run(
    dev_out_dir=".dev", run_id="source", new_run_id="graph-aware",
)
```

Migration always creates a new trace, verifies SQLite integrity and discovery
configuration, retains existing search/Datalinks/text/metadata and historical
review checkpoints, isolates output paths, and atomically adds graph discovery
contract `1.0` to the cloned fingerprint. It rejects active callers through the
composing workflow's exclusive activity lock, graph-aware or post-collection
sources, and existing destinations. Normal `resume()` then checkpoints ELink by
PMID and ESummary by GDS UID, so a later stop repeats at most an unfinished
batch. The original trace and outputs remain unchanged.

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

Specialized workflow surfaces are available when independently advancing or evaluating a trace:

- `PublicationTextReviewer.resume(...)`: `resume(trace_dir, theme=None, reviewer=None, strategy="direct", allow_theme_override=False, require_resolved_metadata=False, collect_metadata=False, defer_metadata_errors=False, require_main_datalinks_phase=False, publication_limit=None, review_action_limit=None, cancelled=None, snapshot_accessions=None, publication_keys=None, item_lock_timeout_seconds=None, metadata_item_timeout_seconds=None, publication_text_item_timeout_seconds=None, review_item_timeout_seconds=None) -> dict` reviews one fixed Datalinks snapshot. A stage worker can pass the current merged accession evidence and its terminal-frontier publication keys through the public façade; omitting both preserves full-snapshot behavior. `collect_metadata=True` first downloads or reuses supported GEO/ArrayExpress metadata one accession at a time, isolates provider failures, and returns a `metadata_summary`; item locks prevent duplicate work with another collector. `publication_limit` retains its pre-metadata snapshot meaning, while positive `review_action_limit` counts only actual review attempts after prerequisites, compatible reuse, and cooldown deferral. `cancelled` stops before the next item without falsely reporting a main-phase yield. Progress is isolated in `incremental_review_progress.json`; completed metadata, publication-text, and thematic-review rows remain canonical SQLite checkpoints that normal resume reuses. Model cooldowns and shared-criteria failures become retryable review checkpoints with `next_retry_at`; invalid structured output and ordinary non-throttling 4xx failures remain terminal. See the [filterer flow](docs/codebase.md#filterer).
- `AtlasCollector.resume_metadata(...)`: `resume_metadata(trace_dir, audit_enrichment_only=False, retry_tags=None) -> dict` collects, audits, or explicitly repairs GEO metadata enrichment for one stable snapshot. See the [collector flow](docs/codebase.md#collector).
- `benchmark_fibrosis_meta_pubs_recall.py TRACE_DIR [--references TSV] [--out DIRECTORY]` runs the offline fibrosis meta-publication recall benchmark directly. It defaults to the packaged combined TSV for the Leonie 2026, Taylor 2020, He 2025, and Jaimes Campos 2025 fibrosis reference sets and writes `fibrosis_meta_pubs_recall_report.json` under the Git-ignored `benchmarks/` directory. See the [benchmark package](docs/codebase.md#benchmark-package).
- `benchmark_fibrosis_meta_pubs_query_recall.py TRACE_DIR [--references TSV] [--out DIRECTORY]` reads the same reference TSV and the trace's read-only `search_pages` checkpoints to score publications returned before accession discovery or review. Complete searches receive final scores; incomplete searches produce explicitly lower-bound reports in `fibrosis_meta_pubs_query_recall_report.json`. See the [benchmark package](docs/codebase.md#benchmark-package).
- `benchmark_fibrosis_meta_pubs_review.py [DATASET_CSV] [--out DIRECTORY] [--cache CSV] [--raw-cache SQLITE] [--hydrate-only] [--retry-terminal-metadata] [--refresh-cache] [--include-text-only] [--verbose]` resolves labeled DOI/PMID rows through public TA retrieval components, checkpoints raw provider results in benchmark-owned SQLite, derives the existing compact CSV, and optionally scores the production thematic reviewer as relevant, not relevant, or unsure. Accession discovery merges Europe PMC Datalinks, publication-text matches, and exact official NCBI PubMed→GDS links in that order. Linked GDS UIDs are summarized and accepted only as registry-supported `GSE` records; textual corroboration is unnecessary, but a non-empty valid metadata package is still required for normal review suitability. `--hydrate-only` fills and audits both caches without importing reviewer credentials or making model calls, and it leaves any existing reviewer report unchanged. SQLite retains Europe PMC search/text/Datalinks, PubMed→GDS links and GDS summaries, checksum-verified compressed GEO MINiML XML and ArrayExpress IDF/SDRF source resources, pre-canonical parser mappings, structured strict-validation diagnostics, canonical packages, PubMed/SRA/ENA enrichment stages, terminal negatives, sanitized failures, and attempt history. Evidence is captured before parsing/canonicalization and reused after deterministic failures. MSC policy `miniml-3.0-source-compat-v1` preserves source-authored duplicate sample titles when unique non-empty iids retain identity; accepted warnings remain visible in the privacy-safe audit and every other strict diagnostic remains blocking. Interrupted fills resume from a hidden staging database and publish only after every row is terminal. `--retry-terminal-metadata` is hydrate-only and retries just terminal GEO/ArrayExpress construction twice per accession; it does not requery publications, text, Datalinks, PubMed→GDS, PubMed, SRA, ENA, or enrichment stages. Benchmark GEO hydration uses the ordinary fully enriched MINiML path. If supplementary enrichment exhausts its allowance after the base GEO package was downloaded, the raw package is retained and derived as `partial`. By default, a row is reviewer-eligible when non-empty full text, preprint text, or abstract text is available and every supported accession has non-empty metadata with status exactly `available`; incomplete or failed hydration is skipped. The benchmark-only `--include-text-only` flag additionally reviews non-empty-text rows with zero supported accessions, passing title/text plus empty accession and metadata arrays. It never admits a row with known partial/error accession metadata and does not change production Atlas eligibility. Schema 1.1 labels rows `full_context`, `text_only`, or `ineligible` and reports overall plus per-tier metrics. Terminal outcomes are reused until an explicit targeted retry or `--refresh-cache`. `fibrosis_meta_pubs_review_cache_audit.json` contains identifiers, stage outcomes, attempts, coverage, accepted/blocking diagnostic codes/paths/severities, compatibility-policy identity, and link-graph query/UID/GSE/merge/rejection/failure counts only—never publication text, source resources, raw provider responses, metadata contents, or diagnostic messages. `--verbose` reports each hydration attempt, cache action, skip, and review stage. The packaged CSV projects all 92 shared recall-reference rows into 90 distinct connected DOI/PMID identities and labels every publication `relevant`, making the default run a reviewer positive-control benchmark. Recall and query-recall read the shared TSV directly; reviewer classification uses this separate labeled CSV. See the [benchmark package](docs/codebase.md#benchmark-package).

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

This repository continues to support the installed `thematic-atlas` CLI,
importable Python APIs, and the direct benchmark script. The retained
fibrosis theme, discovery-query catalog, benchmark implementation, and combined
reference TSV remain available as
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
- `resource_profile`/`--resource-profile` selects `standard` or `large` typed
  ceilings. `resource_overrides`/repeatable `--resource-override FIELD=VALUE`
  changes only named numeric fields and is fingerprinted through constructed
  dependencies. Delegated disk consumers enforce the profile's 10% headroom.
- Publication review defaults to strategy `direct` and filter `none`. A
  non-`none` filter and `review_before_metadata` require a theme.
- Query generation is opt-in for collection and default-on for atlas creation;
  both modes allow at most three generated queries. Explicit queries come
  first, query-file entries follow, and generated queries are appended.
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

The deterministic, network-blocked suite was last verified on 2026-08-10:
`545 passed, 4 skipped`. The skipped tests are the explicitly opt-in live API
provider contracts. Normal tests inject all HTTP, LLM, embedding, ontology,
and metadata collaborators and do not make external calls.

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python -m pytest -p no:cacheprovider
```

**MSC 7 export migration**

MSC 7 and Curator/ThematicAtlases/GSK adapter 5 make export policy converter-owned.
Curator produces source-bound patches; MSC applies patches to canonical MINiML,
which retains source values, `hz_*` evidence and provenance. ThematicAtlases
publishes that canonical metadata in Atlas v1. GSK's own field names and
scientific selection rules remain unchanged.

Pass `replacement_profile=profile` directly to MSC JSON2AE, JSON2TSV,
JSON2H5AD or JSON2OBS conversion methods (including manifest/batch methods).
The CLI equivalents are mutually exclusive `--replacement-profile JSON` and
`--replacement-profile-file PATH`. Supplying a profile activates replacement.
No profile preserves ordinary destination values. Profiles retain schema `1.0`,
ordered source fallback, multiple values and preservation when no source matches.
Semantic-invalid profiles warn and disable replacement; malformed CLI JSON,
non-object inputs and unreadable files fail before output creation.

Curator's `harmonization_overrides` arguments, validation, CLI flags and result
forwarding are removed. Old MSC `use_harmonization_overrides` is removed.
An envelope containing `harmonization_overrides` is rejected: pass that mapping
as the explicit converter argument instead. Profile-free `miniml_json`
envelopes remain supported, as do native MINiML and Atlas v1 inputs.

MSC exports `hz_*` evidence by default even when replacements are active:
MAGE-TAB uses characteristic/factor/parameter groups with standard ontology
companions; units use local `Comment[hz_unit]`. Tables and AnnData use
`msc.characteristics.hz_*` and assay `hz_value` / `hz_unit` with `_id` and
`_onto` companions. H5AD metadata is version `2.0` and exported assay metadata
is `3.0`. MINiML 3, patch 3.1 and MINiML transport versions
are unchanged. Conversion copies protect the canonical input and patch evidence.
MSC 7 checkpoint identity includes normalized policy and writes in a separate
version directory from historical checkpoints.

```python
profile = {"schema_version": "1.0", "replacements": {"organism_part": ["tissue_name", "high_level_tissue"]}}
JSON2TSVConverter().export_manifest("atlas.json", outdir="tables", replacement_profile=profile)
```

```bash
json2tsv atlas.json --replacement-profile-file export-policy.json --out tables
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

MSC MINiML v2 input support has been removed. Supply v3 or regenerate from source; see [v3-only migration guidance](docs/codebase.md#miniml-v3-only-cutover).
