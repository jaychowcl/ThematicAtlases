# ThematicAtlases Codebase Handoff

Current organization: [package boundaries](#package-boundaries-and-compatibility),
[workflow ownership](#workflow-ownership), [typed stages](#typed-stage-operations),
and [runtime construction](#runtime-construction-and-management). Public symbols
below remain compatibility entrypoints; their implementations now live in the
owning packages described in those sections.


This is the canonical architecture, interface, and workflow handoff for the
implemented package. It is evidence-backed by the production modules, package
metadata, supported interfaces, and tests in this repository.

<a id="workflow-checkpoints-v2"></a>
## Workflow checkpoint contract 2.0

This is the current recovery contract for **new runs**. It is independent of
Atlas document schema 1.0, MSC MINiML schema 3.0, and the existing SQLite table
schema. Historical notes about provider-specific metadata substages and JSON
snapshot recovery below are superseded by this section.

### Design and boundaries

SQLite stores completed external work. Pure filtering, pruning, merging and
summaries are recomputed. `runtime/views.py::CheckpointViews` supplies deterministic
read-only discovery, metadata, review and harmonization projections;
`SnapshotStore` reads a consistent SQLite snapshot. Neither reconstruction method
calls a provider or a model. A read-only SQLite open may create SQLite-managed
WAL/SHM bookkeeping files; it never changes checkpoint data.

`runtime/contracts.py::validate_trace` requires the manifest marker
`workflow_checkpoint_contract: "2.0"` before any writable trace open. Legacy
traces receive a migration-required error; they are neither upgraded nor modified.
The old graph-only migration command is disabled because it cannot produce this
new contract. Dependency acceptance promotion and trace migration are separate work.

### Completed-work sequence

1. Resolve manual/generated queries once: `query_generation -> resolved_query_key`.
2. Save each search page and compact cursor progress: `search_pages + search_queries`.
3. Save publication dataset links: `datalinks[publication]`.
4. Retrieve text and optionally extract accessions together: `publication_text[publication]`.
5. Save PubMed links and GDS summaries independently: `pubmed_gds_links + gds_summaries`.
6. Resolve remote GSM/GDS identities: `geo_resolution[accession]`; normalize GSE locally.
7. Convert one study through MSC: `metadata_conversion[repository:accession]`.
8. Save thematic criteria and each publication decision: `thematic_review[publication]`.
9. Save each whole dataset harmonization: `harmonization[work_key]`.
10. Recompute derived views and publish final Atlas output: `assemble(saved_outcomes)`.

Review-before-metadata runs perform step 8 before step 7 and convert only the
retained datasets. Empty discovery still checkpoints a successful empty search.
`publication-text` is the canonical pause; `fulltext-accessions` is an alias for
the same completed text/extraction boundary. Extraction can be disabled without
preventing review. `publication_text` stores the body, extracted records and
`extraction_complete`/`extraction_enabled`; reviews store a versioned `text_ref`,
content hash, full review-input hash and decision, rather than another body.

### MSC interface and failures

Ordinary `Atlas.resume()` retries partial metadata only when the latest MSC
attempt contains unresolved, structured retryable `provider_issue` diagnostics.
Invalid remote responses, transport failures and HTTP failures remain distinct
reasons; scientific disagreements and warning text never select retries.
`runtime/metadata_recovery.py` shares eligibility between checkpoint reports,
implicit published-run discovery and resume. Selection snapshots the current
attempt, honors cooldowns and uses existing item locks. Each study is attempted
at most once per resume call; a newer concurrent attempt takes precedence.
Partial packages remain usable during failures. A completed retry clears the
reasons, while a failed retry records its own reasons without borrowing stale
ones. Source/settings hashes remain mandatory for checkpoint reuse. Legacy
untagged partials still require explicit whole-conversion retry selection.
Safe reason/provider/operation summaries appear in final dataset diagnostics;
the full structured facts and retry trigger remain in SQLite attempt history.
No checkpoint table or Atlas document schema migration is required.
Coverage includes `tests/test_provider_recovery.py` and the existing checkpoint
end-to-end tests.

Both GEO and ArrayExpress use `integrations/conversion.py::MetadataConversionAdapter`:
`Converter.convert(accession, out_type="json", enrichment="standard",
options={"expand_studies": True, ...saved_resource_limits})`. No output file is
requested. Every returned canonical package becomes a record with its original
publication associations, including related studies. Metadata-handler injection
remains supported; conversion tests/providers inject `converter=` into wrappers.
The previous ArrayExpress source/parser injection now explains this replacement.

Each conversion item records canonical packages, MSC version/source identity,
settings, provenance, diagnostics, and execution/completeness/validation statuses.
TA consumes MSC's structured safe error and retry timestamp; it does not guess
retryability from diagnostic prose. Actual provider attempts/retries/waits come
from the unified converter's metrics. Parsing, scientific enrichment and validation
remain MSC-owned. Raw source, pre-canonical, validation and identifier-enrichment
substage recovery is removed from TA production traces; benchmark-only raw evidence
utilities remain separate.

Complete and valid-partial packages are reusable. Partial metadata reaches review
and harmonization and makes the run partial. Unresolved structured provider
failures are automatically selected on resume; other partials require explicit
selection. Failed retries retain the prior usable package. Transport
failures without a usable package remain retryable; invalid/terminal conversion
outcomes remain failures. Only a successful valid complete empty result is `no_data`.
Item locks, attempt history, cooldowns and input/runtime identities still apply.

### Resume, workers, forks and diagnostics

Resume replays shared stages over completed SQLite outcomes; intermediate JSON
existence never selects recovery work. Workers and independent metadata/review
continuations reconstruct discovery from all three sources. Metadata forks clone
SQLite from a metadata pause and resume downstream without JSON snapshots.
Trace-reading query/review benchmarks use the same reconstruction service for
contract 2.0. Review reuse checks input hashes, including changed text/metadata.
Whole harmonization reuse checks source, publication context, options and execution
identity. Read-only views select the latest matching outcome, preserve failed and
not-run statuses, and omit review decisions whose metadata/text input hash changed.
Partial conversion outputs carry the `metadata_conversion_partial` diagnostic.

`run_metadata.pipeline_position` is the single current workflow-position record.
Stage/item states and its current position supply progress/pause reports. Small
reports, explicitly requested reports and final outputs remain available.
Intermediate snapshots default off; `Atlas(..., debug_snapshots=True)` or CLI
`--debug-snapshots` opts in. A worker resolves exactly `<dev_out_dir>/<run_id>`;
passing a root named `runs` is equally valid.

### Commands and tests

```bash
thematic-atlas create-atlas --theme fibrosis --query fibrosis --no-generate-queries --dev-trace --dev-out-dir .dev --stop-after metadata
thematic-atlas resume --dev-out-dir .dev --run-id RUN --retry-item metadata_conversion:geo:GSE123
thematic-atlas worker-snapshot --dev-out-dir .dev --run-id RUN --stage text
python -m pytest tests/test_checkpoint_v2_e2e.py tests/test_metadata_conversion.py tests/test_combined_publication_evidence.py tests/test_checkpoint_contract_v2.py tests/test_checkpoint_views.py
```

Identifier retry-tag and enrichment-audit arguments fail with study-level retry
guidance. Offline acceptance covers both stage orders, successful empty discovery,
partial conversions, interrupted publication, worker roots, pause aliases, text
references, invalidation, locks, fork/continuation reconstruction and byte-preserving
legacy rejection. `tests/fixtures/contracts/checkpoint-v2-workflows.json` pins final
datasets/publications, run statuses, work-item states and provider-call counts for
default/review-first/partial/empty/interrupted-publication scenarios. Controlled providers are used; this is not live provider/model
validation.

<a id="architecture"></a>
## Architecture

ThematicAtlases builds biomedical dataset atlases from publication queries. Its
primary users enter through the `thematic-atlas` CLI, the `Atlas` Python
orchestrator, or component APIs. The package owns orchestration,
checkpointing, repository routing, review filtering, and output assembly; it
delegates model review to `agentic-curator`, metadata conversion to
`meta-standards-converter`, and remote records to Europe PMC, NCBI, ENA, and
model/ontology providers.

```text
CLI / Python APIs
              |
              v
         Atlas facade
       /        |          \
AtlasCollector AtlasFilterer AtlasHarmonizer
   |              |              |
   v              v              v
Europe PMC   publication text   agentic-curator
GEO/AE       thematic review    ontology services
   \              |              /
    +---- legacy stage maps -----+
              |
      AtlasDocumentService
              |
      AtlasDocumentAdapter
              |
      validated AtlasDocument v1
              |
    JSON bundle / trace artifacts
 atlas_run.sqlite3 + item checkpoints
```

The runtime is a Python 3.10+ `src/` package. `Atlas` coordinates three stage
components; `AtlasRunStore` owns run lifecycle and artifact identity, while
`CheckpointStore` retains internal item-result/retry state and
`DevTraceWriter` owns their traced layout.
The sibling `benchmark_ThematicAtlases` package evaluates saved outputs without
being on the production atlas path. See [runtime packaging](#runtime-and-packaging)
and [project layout](#project-purpose-and-layout).

<a id="system-context-and-boundaries"></a>
## System context and boundaries

- **User/process boundary:** CLI arguments, Python mappings, JSON/query/theme
  files, and trace directories enter the process. Callers own valid paths and
  credentials; parsers and orchestrators own option and fingerprint validation.
- **Network boundary:** `EuropePMCWrapper` calls Europe PMC search, datalinks,
  and full-text APIs. `GEOWrapper` calls NCBI E-utilities and delegates MINiML,
  PubMed/SRA, and ENA retrieval through `meta-standards-converter`. Provider
  status and request failures remain item-local where checkpointing supports it.
  `ArrayExpressWrapper` delegates BioStudies MAGE-TAB retrieval to MSC.
- **Model/ontology boundary:** query generation, thematic review, and enabled
  ontology judgement stages are delegated to `agentic-curator`. Google ADC is
  checked before eligible model-backed work; this repository does not own model
  responses or external ontology availability.
- **Persistence boundary:** output JSON and sidecars are caller-visible.
  `JsonArtifactBundlePublisher` stages and validates related JSON before
  publishing an immutable generation through one atomic current pointer. Direct
  outputs remain rollback-safe compatibility views. `DevTraceWriter` owns
  readable trace artifacts;
  `AtlasRunStore` owns lifecycle/stage/artifact/event truth, while
  `CheckpointStore` owns internal item results, fingerprints, retry history,
  and atomic amendments.
- **Package boundary:** `ThematicAtlases` owns atlas workflow policy.
  Agentic Curator 6.x owns typed MSC MINiML 3.1 harmonization patches and
  Meta Standards Converter 8.x owns strict v3-only package decoding; this repository transports canonical 3.0 packages
  without weakening either boundary.
  `benchmark_ThematicAtlases` reads query and reviewed-output recall traces
  without workflow mutation; its review runner instead resolves public
  identifiers into a separate Git-ignored cache and never reads or mutates a
  trace. Repository capabilities are explicit and immutable: GEO and
  ArrayExpress are supported end to end; scanner-only curated repositories are
  retained as terminal inventory until a supported capability and handler are
  registered together.
- **Privacy/trust boundary:** credentials, authorization headers, provider
  payloads, prompts, and responses must not be written to operational logs.
  Safe logs contain identifiers, status, duration, counts, and stage summaries.

<a id="repository-capabilities-v1"></a>
### Repository capability contract 1.0

`RepositoryCapabilityRegistry` is the single immutable source of truth for
repository accession grammar, review identity, provider/adapter name,
harmonization eligibility, and required end-to-end contract categories. GEO
accepts GSE/GSM/GPL/GDS discovery identities but only GSE review identities;
ArrayExpress accepts and reviews E-MTAB/E-GEOD/E-MEXP experiment identities.
The collector, reviewer, harmonizer, and document boundary share the registry,
so a scheme label without a valid accession cannot manufacture support and a
repository mismatch fails or becomes an explicit not-run reason.

<a id="runtime-contracts-v2"></a>
### Runtime status and safe-error contracts

`OperationStatusV2` separates execution, completeness, evidence confidence,
validation, and publication disposition. Harmonization persists that envelope
under `ontology_harmonization_status`; the older run-status scalar is only a
compatibility projection. `SafeErrorEnvelope` persists exception type,
sanitized provider/location, HTTP status, retry category, stage/item identity,
and correlation ID without raw exception messages, response bodies, prompts,
credentials, or local absolute paths.

<a id="request-policy"></a>
### Typed resource and request policy

`ResourceProfile` provides standard and large typed ceilings. Standard is 3
redirects, 10/60-second connect/read timeouts, 128 MiB XML, 256 MiB compressed
archive, 1 GiB expanded archive, 3 GiB ontology file, 100 GiB matrix/H5AD,
200 GiB aggregate download, 250 GiB cache, four network workers, and one
ontology-build worker. Large is 5 redirects, 30/300-second timeouts, 512 MiB
XML, 1 GiB compressed archive, 4 GiB expanded archive, 5 GiB ontology file,
500 GiB matrix/H5AD, 1 TiB aggregate download, 500 GiB cache, eight network
workers, and two ontology-build workers. These are object/file/transfer
ceilings, not RAM reservations. Delegated disk consumers preflight at least
10% headroom; this package directly enforces HTTPS, allowed host suffixes,
manual redirect ceilings, response-body limits, and aggregate transfer limits.
When a response has a non-identity `Content-Encoding`, its declared
`Content-Length` is treated as the encoded transport size and is not compared
with the decoded bytes yielded by `requests`; both the declared ceiling and
the decoded response/aggregate ceilings still apply. This permits bounded
bioRxiv/medRxiv JATS retrieval through compressed HTTP responses.
MSC additionally validates public DNS for its ArrayExpress fetcher.

`RequestPolicy.get(url, *, params=None, retry_exceptions=False,
raise_for_status=True, max_retries=None)` normally uses the policy-wide retry
limit. Its optional nonnegative per-call limit lets an endpoint orchestrator
perform one bounded request without mutating shared policy state.
`RequestPolicy.wait(delay)` applies a nonnegative interval through the injected
sleeper, so endpoint pacing and tests share the same timing boundary.

<a id="architectural-decisions"></a>
## Architectural decisions

<a id="ad-001-stage-components"></a>
<a id="decision-delegated-model-work"></a>
### AD-001: One root orchestrator delegates stage implementation

- **Status:** Observed
- **Decision:** `Atlas` sequences collection, filtering/review, harmonization,
  output, and resume while specialist objects implement each stage.
- **Rationale:** Not documented.
- **Consequences:** CLI and runners share workflow policy and can inject test
  doubles, but signature changes at the orchestrator boundary affect many paths.
- **Affected components:** `Atlas`, `AtlasCollector`, `AtlasFilterer`,
  `PublicationTextReviewer`, and `AtlasHarmonizer`.
- **Evidence:** [`atlas.py`](../src/ThematicAtlases/atlas.py),
  [`cli_atlas.py`](../src/ThematicAtlases/cli_atlas.py), and
  [`test_atlas.py`](../tests/test_atlas.py).

<a id="ad-002-item-checkpoints"></a>
<a id="decision-checkpointed-traces"></a>
### AD-002: Traced work is checkpointed at stage and item boundaries

- **Status:** Observed
- **Decision:** traced runs combine readable JSON artifacts with a fingerprinted
  SQLite store and status/history rows. Cross-process item work is file-locked;
  event sequence allocation is one immediate SQLite
  transaction; cooperating provider calls can share a run-local pacing gate.
- **Rationale:** Not documented.
- **Consequences:** resume reuses completed and terminal work and can selectively
  requeue retryable/degraded work; concurrent workers do not allocate duplicate
  event sequences or duplicate a locked item; incompatible configurations fail
  validation.
- **Affected components:** `CheckpointStore`, `DevTraceWriter`, `Atlas`, remote
  wrappers, independent workers, and archive logic.
- **Evidence:** [`checkpoint.py`](../src/ThematicAtlases/checkpoint.py),
  [`trace.py`](../src/ThematicAtlases/trace.py), and
  [`test_checkpoint.py`](../tests/test_checkpoint.py).

<a id="ad-003-publication-text-map"></a>
<a id="decision-shared-publication-texts"></a>
### AD-003: Publication text is normalized into a shared map

- **Status:** Observed
- **Decision:** atlas accessions reference shared publication text through
  `publication_text_ref` instead of duplicating text under every accession.
- **Rationale:** Not documented.
- **Consequences:** repeated publications share review inputs and storage, while
  reference integrity becomes a required compatibility invariant.
- **Affected components:** `AtlasFilterer`, `EuropePMCWrapper`, reviewers,
  summaries, traces, and atlas consumers.
- **Evidence:** [`filterer.py`](../src/ThematicAtlases/filterer/filterer.py) and
  [`test_filterer.py`](../tests/test_filterer.py).

<a id="ad-004-review-strategies"></a>
### AD-004: Grounded direct review is the sole review contract

- **Status:** Observed
- **Decision:** `direct` is the only supported review contract; the retired
  evidence-then-judgement path is rejected before any model call.
- **Rationale:** Not documented.
- **Consequences:** review identity includes provider, model, generation
  configuration, prompt digest, and scientific inputs. A changed or legacy
  unfingerprinted review is recomputed instead of being silently reused.
- **Affected components:** CLI, `PublicationTextReviewer`, filterer traces, and
  independent review.
- **Evidence:** [`README.md`](../README.md),
  [`review.py`](../src/ThematicAtlases/filterer/review.py), and
  [`test_review.py`](../tests/test_review.py).

<a id="decision-safe-run-archival"></a>
### AD-005: Whole-run archival is verified before sources are removed

- **Status:** Observed
- **Decision:** A new fixed workflow relocates inactive traces and artifacts
  through an exclusive activity lock, non-busy SQLite checkpoint, stable
  durable-file snapshots, staging copy, checksum verification, recursive file
  and directory fsync, and atomic publication before deleting any source. SQLite's trace-root `-wal` and
  `-shm` sidecars are transient snapshot inputs and are not archived; a
  non-empty WAL after checkpointing fails closed.
- **Rationale:** Not documented.
- **Consequences:** Existing runs survive interrupted or conflicting archival,
  while active workflows, symlinks (including a symlinked trace root), unsafe
  names, and destination collisions stop a new run instead of being
  overwritten. `ArchiveDurabilityError` distinguishes a published destination
  whose durability or cleanup finalization failed from a pre-publication error.
- **Affected components:** `Atlas.archive_existing_runs`,
  `workflow_activity_lock`, trace manifests, SQLite stores, and fixed artifacts.
- **Evidence:** [`run_archive.py`](../src/ThematicAtlases/run_archive.py) and
  [`test_run_archive.py`](../tests/test_run_archive.py).

<a id="decision-central-atlas-document"></a>
### AD-006: Public workflows use one versioned document and one run authority

- **Status:** Observed
- **Decision:** Every public collection, creation, harmonization, and resume
  result crosses the boundary as a validated `AtlasDocument` v1 mapping. New
  traces use one `atlas_run.sqlite3` for lifecycle, artifacts, work results,
  attempts, retry metadata, and events; legacy stage maps remain internal.
- **Rationale:** Not documented.
- **Consequences:** Consumers receive one strict, extensible contract and can
  distinguish artifact roles, while incompatible v1 inputs/traces fail closed.
  Mature stage components can evolve behind `AtlasDocumentAdapter`.
- **Affected components:** `Atlas`, `AtlasDocumentAdapter`, `AtlasDocument`,
  `DevTraceWriter`, `AtlasRunStore`, `CheckpointStore`, CLI output, resume, and
  downstream contract fixtures.
- **Evidence:** [`atlas.py`](../src/ThematicAtlases/atlas.py),
  [`document_adapter.py`](../src/ThematicAtlases/document_adapter.py),
  [`trace.py`](../src/ThematicAtlases/trace.py), and
  [`test_atlas_v1_public_workflows.py`](../tests/test_atlas_v1_public_workflows.py).

<a id="design-invariants-and-expectations"></a>
## Design invariants and expectations

- Query order is explicit queries, file queries, then generated queries.
  Per-query limits align with that final order; positive-value validation occurs
  before network work.
- Public workflow mappings have `schema_version == "1.0"` and the exact
  top-level sections `atlas`, `run`, `datasets`, `publications`, and `summary`.
  Unknown fields, ambiguous boolean/integer or scalar/list values, duplicate
  identities, dangling publication references, and inconsistent derived counts
  fail validation during both mapping ingestion and producer serialization. Legacy `accessions` and
  `publication_texts` mappings exist only between mature internal stages.
- Metadata repository routing defaults to GEO and ArrayExpress. Unsupported, unresolved, or
  failed metadata is represented explicitly rather than silently fabricated.
- Repository classification, review identity, and harmonization eligibility
  must resolve through the same immutable capability registry.
- Persisted failures use safe error envelopes; raw exception text, payloads,
  prompts, credentials, and local absolute paths are not durable state.
- Review filtering requires a theme. `review_before_metadata` enriches only
  survivors; `stop_before_review` must not create reviewed/final markers.
- Checkpoint fingerprints protect immutable run inputs. Query amendment is the
  explicit exception and archives the previous fingerprint before replacement.
- Generated run IDs contain UTC microseconds plus 32 bits of random entropy;
  they remain lexically time-sortable without second-resolution collisions.
- Success/no-data and terminal consumed-call outcomes are reusable. Transient
  failures are retryable; one item failure must not discard unrelated successes.
- Output order and schemas remain stable under bounded parallel harmonization.
  Original metadata is retained when an item cannot be harmonized.
- Status 2.0 axes are authoritative. A degraded harmonization or partial
  metadata repair keeps usable metadata but makes the aggregate run `partial`.
- Related public Atlas/summary JSON is staged, parsed, copied to an immutable
  generation, fsynced, and selected by one atomically replaced pointer. A
  first-run failure leaves no final compatibility view or current pointer; an
  overwrite failure preserves the prior pointer and restores every view.
- `atlas_run.sqlite3` is the sole Atlas-run database for run, stage,
  artifact-role, event, item-result, and retry state. Resume does not infer or
  silently migrate missing v1 lifecycle state from a legacy
  `resume_state.sqlite`.
- The mature `CheckpointStore` API may operate inside a v1 run database only
  when exactly one run exists. Same-transaction triggers project current
  checkpoint items, replaced states, and metadata into normalized
  `work_items`, `attempts`, and `run_metadata`; deletes cascade consistently.
- Whole-run archival requires an exclusive activity lock, rejects symlinks and
  collisions, verifies and fsyncs copied content, and durably publishes before
  deleting sources. Post-publication finalization failure identifies the live
  archive through `ArchiveDurabilityError.destination`.
- Library modules do not configure global logging. No credential, prompt,
  response, authorization header, or full provider payload belongs in logs.

<a id="component-relationships-and-data-flow"></a>
## Component relationships and data flow

| Source | Destination | Interface and direction | Data/lifecycle ownership | Failure behavior |
| --- | --- | --- | --- | --- |
| CLI/runners | `Atlas` | synchronous Python calls | caller owns inputs; `Atlas` owns run ordering | parser/validation error ends invocation |
| `Atlas` | `AtlasCollector` | `collect_jsons` / `resume_metadata` | collector owns repository selection and metadata stage | item errors represented/checkpointed |
| collector | Europe PMC/NCBI/GEO/AE wrappers | adapter calls, outbound HTTP where implemented | wrappers own response normalization; shared `RequestPolicy` owns bounded GET retries; the NCBI provider owns exact PubMed→GDS→GSE graph projection | transient requests retry; unsupported handler statuses become terminal inventory without invocation |
| `Atlas` | `AtlasFilterer` | atlas-shaped mappings | filterer owns text map, review context, and filtering | review failures remain item-local in trace |
| filterer | `PublicationTextReviewer` | publication/context mappings | reviewer owns judgement contract; filterer applies outcome filter | strategy/fingerprint mismatches fail |
| `Atlas` | `AtlasHarmonizer` | dataset mappings and controls | harmonizer owns per-work-key cache and details | original metadata retained on failure |
| stage components | `AtlasDocumentAdapter` | legacy mappings into/out of typed v1 | adapter owns boundary projection; document owns validation | malformed v1 and broken references fail closed |
| `Atlas` | `JsonArtifactBundlePublisher` | mapping of path to JSON value | publisher owns stage/backup/replace cleanup | any replacement failure restores the complete prior bundle |
| traced orchestration | `AtlasRunStore` | normalized SQLite calls | store owns runs, stages, work, attempts, artifact roles, and events | incompatible schema/path-role conflict raises |
| item stages | `CheckpointStore` | internal SQLite calls | store owns fingerprints, item results/history, locks, and retry requests | transaction failure prevents false item completion |
| fibrosis benchmark runner | direct `benchmark_fibrosis_meta_pubs_recall.py` invocation | trace directory plus packaged/custom TSV | runner atomically owns one generated JSON report under caller-selected output | invalid TSV/trace fails without a partial report; ambiguous matches become conflicts |
| fibrosis query-recall benchmark | direct `benchmark_fibrosis_meta_pubs_query_recall.py` invocation | trace directory plus the same packaged/custom TSV | runner reads one consistent, query-only SQLite transaction and atomically owns its generated report | incomplete query checkpoints produce an explicit lower-bound report; malformed trace contracts fail without replacing a report |
| fibrosis review benchmark | direct `benchmark_fibrosis_meta_pubs_review.py` invocation | labeled DOI/PMID CSV plus packaged theme, raw SQLite, derived CSV, and audit | runner owns resumable public hydration, PubMed→GDS link/summary checkpoints, provider-stage/raw-package checkpoints, compressed pre-validation source evidence, terminal-negative reuse, compact projection, default complete-context eligibility, opt-in text-only eligibility, and atomic artifact replacement; production TA components own public retrieval/review | hydrate-only never initializes a model; targeted retry reuses captured source and isolates terminal metadata; retained base GEO packages become partial after exhausted enrichment; default review requires complete metadata, while `--include-text-only` admits only non-empty-text rows with zero supported accessions and never partial/error metadata; invalid global inputs fail without replacing a report |

Control flows downward from interfaces through `Atlas`; data returns upward as
plain mappings. Remote adapters never call the CLI. Benchmarking and independent
workers enter at saved-artifact boundaries and do not bypass checkpoint
validation when they modify a trace.

<a id="entrypoints-and-interfaces"></a>
## Entrypoints and interfaces

<a id="interface-thematic-atlas-cli"></a>
### Installed `thematic-atlas` CLI

- **Installed CLI:** `thematic-atlas` maps to
  `ThematicAtlases.cli_atlas:main` and dispatches `collect-datasets`,
  `create-atlas`, `harmonize-datasets`, `resume`, or `fork-run`. The parser is defined in
  [`cli_atlas.py`](../src/ThematicAtlases/cli_atlas.py).
- **Python workflow API:** import `Atlas` from `ThematicAtlases.atlas`.
  Component packages export collector, filterer/reviewer, harmonizer, wrapper,
  and benchmark types listed in the [public API reference](#public-api-reference).
- **Archived focused runners:** no repository-root `run_*.py` interface remains
  active. The canonical production fibrosis workflow is
  `gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py` in the parent
  adapter repository; reusable APIs and reference assets remain here.
- **Files:** queries/theme text and Atlas v1/reference JSON are inputs. Atlas v1
  JSON, summaries, details, benchmark reports, logs, readable trace JSON, and
  the single authoritative `atlas_run.sqlite3` are outputs.

The CLI is a thin adapter: it constructs `Atlas(metadata={})`, translates
hyphenated review filter values, resolves logging precedence, and forwards
validated arguments. `create-atlas` requires a nonblank inline/file theme and
defaults both query generation and thematic review on; their independent
BooleanOptional controls can disable either behavior. `collect-datasets`
retains its query-first, optional-theme, opt-in-generation contract. Accession
pruning is destructive and defaults off on both commands; only the explicit
`--prune-accessions` flag enables it. Complete
user options live in the [README CLI guide](../README.md#cli-guide).

`create-atlas --stop-after` and `resume --stop-after` accept the same ordered
boundaries: `query-results`, `datalinks`, `publication-text`,
`fulltext-accessions`, `accession-graph`, `metadata`, `review`, and
`harmonization`. A resume target supersedes the earlier invocation target;
requesting a boundary already passed returns the current snapshot without
rolling checkpoints or lifecycle state back.

<a id="interface-python-atlas"></a>
### Python `Atlas` interface

Import `Atlas` from `ThematicAtlases.atlas`; the package root intentionally
exports no names. Its supported workflow methods and specialist package exports
are inventoried in the [public API reference](#public-api-reference).
`Atlas.create_atlas(..., stop_after=...)` and
`Atlas.resume(..., stop_after=...)` expose the eight ordered boundaries.
Composing runners import `TraceStageWorker` from
`ThematicAtlases.stage_worker` for one-shot `text`, `graph`, `metadata`, or
`review` frontier advancement.

<a id="interface-focused-runners"></a>
### Archived focused runner interfaces

Archived non-canonical fibrosis runners are not supported interfaces. Ignored
local recovery copies are kept under
`.dev/archive/fibrosis-workflows-2026-08-03/`; because that directory is
untracked, it is not a distributable source of record. Use the installed CLI,
the Python API, or the canonical parent-adapter workflow documented in the
[archived-runner record](#workflow-fixed-runners).

<a id="orchestrators-and-core-types"></a>
## Orchestrators and core types

<a id="type-atlas"></a>
- [`Atlas`](../src/ThematicAtlases/atlas.py) owns component wiring, query
  resolution, credential/cache preflight, stage order, tracing, amendment, and
  v1 boundary conversion. It delegates run identity, resume selection,
  checkpoint-contract reconciliation, archival, and resumed bundle publication
  to an injected `AtlasRunLifecycle`.
<a id="type-atlas-run-lifecycle"></a>
- [`AtlasRunLifecycle`](../src/ThematicAtlases/run_lifecycle.py) owns run IDs,
  final status aggregation, resume-directory selection, stale-contract
  requeueing, archive delegation, and resumed output publication. The public
  `resolve_resume_run_directory(dev_out_dir, run_id)` function exposes the same
  explicit-or-latest-incomplete selection to composing runners, while the
  `Atlas` private facade remains a delegating compatibility seam.
<a id="type-atlas-document-service"></a>
- [`AtlasDocumentService`](../src/ThematicAtlases/application/atlas_documents.py)
  is the application use case for v1 assembly, internal projection, derived
  operational summaries, and single/bundle publication. It depends only on
  `AtlasDocumentAdapter` and `ArtifactPublisherPort`, keeping this policy out of
  the root facade.
<a id="type-atlas-ports"></a>
- [`ThematicAtlases.ports`](../src/ThematicAtlases/ports/__init__.py) declares
  runtime-checkable `CollectorPort`, `FiltererPort`, `HarmonizerPort`, and
  `ArtifactPublisherPort`. Protocols document the dependency direction without
  importing concrete wrappers into application services.
<a id="type-atlas-document-adapter"></a>
- [`AtlasDocumentAdapter`](../src/ThematicAtlases/document_adapter.py) is the
  internal anti-corruption layer between mature `accessions` /
  `publication_texts` stage mappings and strict `AtlasDocument` values. It
  centralizes identity/status/review/diagnostic projection instead of
  scattering final JSON assembly across stages. It unwraps Agentic Curator's
  structured evidence envelope while retaining flat-list compatibility, and
  projects provider `pre_hz_*`/`ontology_lookup` targets into canonical Atlas
  paths, raw values, and optional ontology matches. If the caller omits a
  theme, it derives one from Atlas metadata, the first nonblank query, or the
  title. `assemble()` and `to_legacy()` pass every MINiML-shaped value through
  the strict MSC boundary and preserve its canonical JSON mapping, including
  the independent `miniml_schema_version`; the adapter does not translate that
  marker into Atlas `schema_version`. A metadata collection represented as
  `{"packages": [...]}` is validated package by package.
<a id="type-atlas-document"></a>
- [`AtlasDocument`](../src/ThematicAtlases/domain/atlas.py) is the canonical v1
  exchange model. Frozen standard-library dataclasses and string enums own
  Atlas identity, run configuration/status, ordered datasets, publications,
  review/harmonization values, diagnostics, artifacts, and derived summary.
  `from_mapping`, `to_mapping`, `load`, `dump`, and `validate` reject unknown
  top-level/nested fields, unsupported versions, duplicate identities, broken
  publication references, blank identity/title/theme text, and inconsistent
  counts. JSON is deterministic,
  UTF-8, newline-terminated, parent-creating, and atomically replaced.
  Dataset `metadata` remains open for non-MINiML application mappings. A value
  declaring `miniml_schema_version` or the legacy `mage_tab` marker, or a
  `{"packages": [...]}` collection, is instead a strict MSC-owned boundary:
  Only MINiML 3.0/3.1 packages accepted by
  `MINiMLCodec.decode(..., strict=True)` are retained as canonical JSON-native
  3.0. MINiML 1.x, 2.0, and malformed nested
  packages are rejected rather than silently reinterpreted. ThematicAtlases
  owns the surrounding Atlas v1 model, not the nested MINiML package schema.
<a id="type-atlas-run-store"></a>
- [`AtlasRunStore`](../src/ThematicAtlases/run_store.py) owns the normalized v1
  operational database. It enables foreign keys/WAL/full synchronization and
  schema version 2 of `schema_migrations`, `run`, `stage_state`, `work_items`,
  `attempts`, `artifacts`, `run_events`, and `run_metadata`. Work order is
  explicit, attempts/events append monotonically, artifact roles cannot
  silently change paths, and foreign/newer/legacy databases raise
  `IncompatibleRunStoreError` rather than being reinterpreted.
<a id="type-json-artifact-bundle-publisher"></a>
- [`JsonArtifactBundlePublisher`](../src/ThematicAtlases/artifact_publisher.py)
  owns deterministic JSON serialization, sibling staging and validation,
  existing-output backups, atomic replacement, rollback, and cleanup for one
  related artifact bundle.
<a id="type-atlas-collector"></a>
- [`AtlasCollector`](../src/ThematicAtlases/collector/collector.py) owns Europe
  PMC discovery, default-on official PubMed→GDS→GSE discovery, accession
  filtering, metadata repository routing, and metadata collection.
  `TraceMetadataResumer` advances or audits a saved trace.
<a id="type-publication-text-reviewer"></a>
- [`AtlasFilterer`](../src/ThematicAtlases/filterer/filterer.py) owns text
  collection/reference attachment, review dispatch, review filtering, and final
  atlas assembly. `PublicationTextReviewer` owns the direct review contract;
  `TracePublicationReviewResumer` restores independent review state.
<a id="type-atlas-harmonizer"></a>
- [`AtlasHarmonizer`](../src/ThematicAtlases/harmonizer/harmonizer.py) owns
  eligible metadata selection, work-key memoization, bounded parallelism,
  upstream ontology-harmonizer construction, details, and fallback status.
<a id="type-checkpoint-store"></a>
- [`CheckpointStore`](../src/ThematicAtlases/checkpoint.py) owns SQLite schema,
  fingerprint validation/amendment, item state/history, retry selection, item
  locks, deterministic multi-item lock ordering, stage status summaries, and
  comparison archives. `DevTraceWriter` owns the readable run layout.
<a id="type-trace-stage-worker"></a>
- [`TraceStageWorker`](../src/ThematicAtlases/stage_worker.py) owns four
  one-shot sidecar frontiers. It takes shared workflow ownership, a nonblocking
  run/stage singleton, and the same bounded item locks used by the main path.
  Text retrieval and deterministic full-text accession extraction remain one
  worker; PubMed-GDS graph discovery is separate because PMID is sufficient.
  Metadata merges Datalinks, text, and cached graph evidence on every pass.
  Review requires terminal text/scrape and graph discovery plus reviewable
  supported metadata. Workers yield after an in-flight item if the main phase
  leaves Datalinks; harmonization and publication are never worker-owned.
  Large publication, checkpoint, and merged-accession frontier scans check the
  cancellation token between records, so a signal received before a claim
  cannot trigger provider or model work and does not wait for a full scan.
<a id="type-europe-pmc-wrapper"></a>
- [`EuropePMCWrapper`](../src/ThematicAtlases/wrappers/epmc.py) composes Europe
  PMC Datalinks, publication-text scanning, and the injectable
  [`PubMedGDSLinkGraphWrapper`](../src/ThematicAtlases/wrappers/pubmed_gds.py).
  The graph wrapper isolates exact NCBI ELink/ESummary projection and is
  independently injectable for tests or composing applications.
<a id="type-geo-wrapper"></a>
- [`GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py) and
  [`ArrayExpressWrapper`](../src/ThematicAtlases/wrappers/ae.py) isolate remote
  or repository-specific behavior. Europe PMC delegates publication identity,
  limits, merge/deduplication, and record projection to
  `PublicationRecordPolicy`; GEO delegates canonical package projection and GSE
  record deduplication to `GEORecordPolicy`. Both collaborators are injectable
  and perform no provider/network work. `GEOWrapper` accumulates delta metrics
  from its own request policy plus nested MSC GEO, PubMed, SRA, and ENA
  requesters, so the collector and one-shot worker summaries account for real
  enrichment calls without double-counting cumulative requester counters.
<a id="type-thematic-reviewer-benchmark"></a>
<a id="type-fibrosis-meta-pubs-recall-benchmark"></a>
- The direct [`benchmark_fibrosis_meta_pubs_recall.py`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_recall/benchmark_fibrosis_meta_pubs_recall.py)
  runner owns offline trace/TSV validation, exact DOI/PMID comparison, aggregate
  and per-reference-set scoring, and atomic report publication. The preceding
  anchor is retained only as a documentation alias for the removed class.
<a id="type-fibrosis-meta-pubs-query-recall-benchmark"></a>
- The direct [`benchmark_fibrosis_meta_pubs_query_recall.py`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_query_recall/benchmark_fibrosis_meta_pubs_query_recall.py)
  runner owns read-only query-checkpoint validation, exact DOI/PMID union,
  per-query and per-reference-set scoring, complete/lower-bound classification,
  and atomic report publication. It never reads accession or review artifacts.
<a id="type-fibrosis-meta-pubs-review-benchmark"></a>
- The direct [`benchmark_fibrosis_meta_pubs_review.py`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_review/benchmark_fibrosis_meta_pubs_review.py)
  runner owns labeled identifier validation, exact public hydration, row-level
  raw checkpoint and derived-cache reuse/refresh, fully enriched GEO MINiML collection including
  PubMed/SRA/ENA identifier enrichment, one outer retry for failed or incomplete
  hydration, terminal negative caching, interruption/resume, privacy-safe cache
  audit, model-free hydration-only execution, default complete-context gating,
  benchmark-only text-only inclusion, visible progress, production
  `PublicationTextReviewer` dispatch, context-stratified three-class metrics, and atomic report
  publication. Reviewer input requires non-empty full text, preprint text, or
  abstract text, at least one
  supported accession, non-empty metadata for every accession, only `available`
  metadata statuses, and no hydration errors. With explicit
  `--include-text-only`, a non-empty-text row with zero accessions is also
  reviewed with empty accession/metadata arrays; known partial/error accession
  contexts remain blocked, and production Atlas behavior is unchanged. MSC policy
  `miniml-3.0-source-compat-v1` preserves duplicate sample titles only when
  unique non-empty iids retain identity; accepted warnings are audited while
  all other strict diagnostics remain blocking. It has no trace input.
  Its packaged labeled CSV is the all-relevant, identity-deduplicated projection
  of the shared recall TSV rather than another direct consumer of that TSV.

<a id="public-api-reference"></a>
## Public API reference

### Support classification

- **Formal exports:** names in a package `__all__`. These are the declared
  reusable component surface.
- **Supported workflow API:** `ThematicAtlases.atlas.Atlas` and the installed
  CLI. The former repository-root runners are archived; `ThematicAtlases.__init__`
  exports nothing.
- **Supported importable production helpers:** public names used across live
  production modules or root runners, but not promised by a package `__all__`.
  They are documented so maintainers can reason about real coupling.
- **Evidence gap:** the repository has no versioning or compatibility policy
  stating whether any non-`__all__` helper is stable for third-party callers.
  Treat those helpers as internal integration surfaces unless a future policy
  promotes them.

### Supported workflow API

[`Atlas(metadata, epmc_wrapper_factory=None, metadata_handlers=None,
metadata_repositories=None, publication_text_reviewer=None, collector=None,
filterer=None, harmonizer=None, ontostore=None, cache_ontologies=False,
query_generator=None, credential_checker=None, document_adapter=None,
artifact_publisher=None, capability_registry=None, resource_profile="standard",
resource_overrides=None, runtime_provenance=None, run_lifecycle=None,
ncbi_api_key=None, ncbi_tool="ThematicAtlases", ncbi_email=None)`](../src/ThematicAtlases/atlas.py)
owns dependency injection. It raises `ValueError` when a supplied harmonizer is
combined with Atlas-managed ontology-store/cache options. The capability
registry and one resolved immutable resource profile are propagated to all
Atlas-owned collaborators. One optional NCBI identity is forwarded to the graph
and GEO callers; an omitted key may come from `NCBI_API_KEY`, is never logged,
and never raises the conservative request rate.

| Member | Exact signature | Return, failure, and side effects |
| --- | --- | --- |
| [`Atlas.create_atlas`](../src/ThematicAtlases/atlas.py) | `(query=None, file=None, out=None, theme=None, review_filter="none", review_strategy="direct", metadata_repositories=None, max_publications=None, max_publications_per_query=None, reviewer=None, collect_metadata=True, dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=True, max_generated_queries=3, harmonization_options=None, review_before_metadata=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, thematic_review=True, prune_accessions=False, stop_after=None) -> dict` | Requires a nonblank theme and normally returns a validated Atlas v1 mapping after collection and harmonization. `stop_after` accepts the eight ordered query-results-through-harmonization boundaries, requires a trace, publishes only a running collection snapshot, and leaves later work for resume. Generation and thematic review default on; destructive accession pruning is independently opt-in. Unsupported discoveries are terminal before review/harmonization. Complete output bundles remain rollback-safe. Invalid options/contracts, credentials, cache preparation, files, publication, or uncaught provider failures raise. |
| [`Atlas.collect_datasets`](../src/ThematicAtlases/atlas.py) | `(query=None, file=None, out=None, theme=None, review_filter="none", review_strategy="direct", metadata_repositories=None, max_publications=None, max_publications_per_query=None, reviewer=None, collect_metadata=True, generate_queries=False, max_generated_queries=3, dev_trace=False, dev_out_dir=".dev", run_id=None, review_before_metadata=False, stop_before_review=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, prune_accessions=False, _trace_writer=None) -> dict` | Returns a validated Atlas v1 mapping with run status `running`; `out` atomically receives the same mapping. Accession exclusions are retained unless the caller explicitly enables pruning; publication-level review filtering remains independent. An explicit unsupported path writes the separate inventory; a traced collection retains it and registers `collection_snapshot`, never `final_atlas`. Validates aligned positive limits, review/theme combinations, query generation, and trace fingerprints before eligible network/model work. `_trace_writer` is internal. |
| [`Atlas.harmonize_datasets`](../src/ThematicAtlases/atlas.py) | `(datasets, harmonization_details_out=None, harmonization_options=None) -> dict` | Requires Atlas v1 input, projects it to the internal stage contract, and returns validated v1 with status-2.0 harmonization details. Legacy/unknown wire fields fail validation. Unsupported/null/mismatched metadata receives a not-run envelope; caught item failures retain original metadata with failed/safe-error envelopes. |
| [`Atlas.resume`](../src/ThematicAtlases/atlas.py) | `(dev_out_dir=".dev", run_id=None, out=None, stop_before_review=False, retry_stages=None, retry_items=None, retry_degraded_stages=None, review_decisions=None, stop_after=None) -> dict` | Selects a v1 trace, requires authoritative `atlas_run.sqlite3`, optionally archives/requeues selected item-cache rows, reuses completed main/worker boundaries, and returns/publishes Atlas v1 or pauses at a newly supplied target. An already-passed target is a no-op without rollback. Missing/ambiguous/incompatible runs, fingerprint mismatches, stale review decisions, or invalid retry requests raise. |
| [`Atlas.fork_run`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, run_id, new_run_id, overrides=None) -> Path` | Atomically clones a metadata-paused create trace with a new ledger identity. It preserves discovery/text/metadata checkpoints, records source provenance, accepts downstream-only overrides, and rejects discovery changes, existing destinations, incomplete sources, and traces containing downstream work. |
| [`Atlas.migrate_discovery_run`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, run_id, new_run_id) -> Path` | Atomically clones a stopped, healthy pre-graph trace that remains in Datalinks, rewrites the ledger/output identity, retains prior checkpoints, audits stage counts and source hashes, and amends only the destination fingerprint to PubMed-GDS contract `1.0`. Active callers are excluded by the composing workflow lock; graph-aware, configuration-drifted, post-collection, corrupt, or existing destinations fail closed. |
| [`Atlas.amend_queries`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, run_id, queries, max_publications_per_query) -> Path` | Archives the prior fingerprint and installs aligned normalized queries atomically. Empty/misaligned limits, active work, or unsafe state raise. |
| [`Atlas.archive_existing_runs`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, archive_root, workflow, artifact_paths=()) -> list[Path]` | Returns durably published archive paths after verification and fsync; active runs, symlinks, unsafe names, nested roots, and collisions raise without deleting sources. A post-publication fsync or cleanup failure raises `ArchiveDurabilityError` with the published destination. |

[`ThematicAtlases.cli_atlas.main(argv=None) -> int`](../src/ThematicAtlases/cli_atlas.py)
parses `collect-datasets`, `create-atlas`, `harmonize-datasets`, `resume`,
`fork-run`, and `worker-snapshot`. Ordinary workflow success returns `0` and
parser errors terminate with argparse status `2`. A worker returns `0` for
complete/no work, `2` for busy/yielded/interrupted/deferred work, and `1` for a
safe outer failure. Complete flags are in the
[README CLI guide](../README.md#cli-guide). Each
[`run_*.py`](../README.md#workflow-scripts) `main(argv=None) -> int` is a
supported direct script interface with its own parser and fixed output policy.

[`TraceStageWorker(epmc_wrapper_factory=None, collector_factory=None,
publication_text_reviewer_factory=None)`](../src/ThematicAtlases/stage_worker.py)
is the supported composing API for one-shot sidecars.
`resume(trace_dir, *, stage, item_limit=None, cancelled=None) -> dict` accepts `text`, `graph`,
`metadata`, or `review`, writes `incremental_<stage>_progress.json`, and returns
legacy selected/completed/deferred/yielded counts plus scanned, actionable,
claimed, reused, prerequisite/cooldown deferred, remaining actionable,
provider-attempt, retry, rate-wait, and interruption fields. The limit follows
actionable-frontier construction. Invalid stages/limits raise
`ValueError`; unavailable workflow or singleton ownership raises
`StageWorkerBusy`; item/provider failures remain resumable in canonical SQLite.

### Formal exports

The following table is exhaustive across live package `__all__` declarations.
All mutable results are newly assembled lists/mappings unless the row says
otherwise.

| Qualified export | Constructor/value and public contract |
| --- | --- |
| [`ThematicAtlases.domain`](../src/ThematicAtlases/domain/atlas.py) | Formally exports the `AtlasDocument` v1 type family and enums through its `__all__`. The codec accepts a mapping or UTF-8 JSON path and returns frozen typed values; validation failures raise `ValueError`; `dump` creates parents and atomically replaces deterministic JSON. [`tests/fixtures/contracts/atlas-document-v1.json`](../tests/fixtures/contracts/atlas-document-v1.json) is the owner-produced downstream wire-contract fixture. |
| [`ThematicAtlases.application.AtlasDocumentService`](../src/ThematicAtlases/application/atlas_documents.py) | `(*, adapter=None, publisher=None)`; `assemble(...) -> AtlasDocument`, `to_legacy(document) -> dict`, `summary(document, atlas_path, *, unsupported_accessions_report=None, unsupported_accessions_path=None) -> dict`, `publish(document, out, *, include_summary, unsupported_accessions_report=None, unsupported_accessions_path=None) -> dict`, and `publish_unsupported_accessions(report, out) -> None`. Validation and publication errors propagate; bundle rollback belongs to its publisher port. |
| [`ThematicAtlases.unsupported_accessions`](../src/ThematicAtlases/unsupported_accessions.py) | Formally exports report schema version `1.0`, `is_unsupported_accession(record)`, `partition_unsupported_accessions(records)`, and `build_unsupported_accessions_report(records, *, atlas_id, run_id)`. The report keeps sanitized discovery/publication attribution and aggregate repository counts outside Atlas v1. |
| [`ThematicAtlases.ports`](../src/ThematicAtlases/ports/__init__.py) | Formally exports runtime-checkable `CollectorPort`, `FiltererPort`, `HarmonizerPort`, and `ArtifactPublisherPort`. They specify callable inputs/outputs for injected application collaborators; concrete exceptions and side effects remain owned by each implementation. |
| [`ThematicAtlases.run_store.AtlasRunStore`](../src/ThematicAtlases/run_store.py) and [`IncompatibleRunStoreError`](../src/ThematicAtlases/run_store.py) | Formally exported normalized Atlas v1 lifecycle/artifact store and fail-closed compatibility exception. Constructor accepts a path plus optional `event_emitter`, creates SQL schema version 2 for a new database, and rejects legacy/foreign/newer state. SQLite remains event authority; an emitter receives the same redacted event only after commit. Public methods are inventoried under supported helpers below. |
| [`ThematicAtlases.infrastructure.RequestPolicy`](../src/ThematicAtlases/infrastructure/http.py) | `(*, timeout=None, max_retries=3, retry_statuses={403,408,425,429,500,502,503,504}, request_get=None, sleep=time.sleep, logger=None, name="HTTP", resource_profile="standard", resource_overrides=None, allowed_hosts={}, allowed_host_suffixes=DEFAULT_ALLOWED_HOST_SUFFIXES, host_gate=None, host_start_intervals=None, max_inline_wait=30, random_value=random.random)`; `get(url, *, params=None, retry_exceptions=False, raise_for_status=True, max_retries=None) -> Response`; `wait(delay) -> None`; `defer_retry(url, *, response, attempt) -> float`. Every actual attempt/redirect uses the shared per-user MSC host gate. NCBI/Europe PMC default to 0.5-second starts and bioRxiv/medRxiv plus FTP default to one second. Numeric or HTTP-date `Retry-After` is persisted without an eight-second cap; a cooldown beyond the inline budget raises `HostRequestCooldownDeferred`. Transport errors and retry statuses use exponential full jitter. The policy exposes provider-attempt, retry, and rate-wait counters without logging URLs, parameters, or secrets. |
| [`ThematicAtlases.artifact_publisher.JsonArtifactBundlePublisher`](../src/ThematicAtlases/artifact_publisher.py), [`PublishedArtifactBundle`](../src/ThematicAtlases/artifact_publisher.py), [`resolve_current_bundle`](../src/ThematicAtlases/artifact_publisher.py), and [`ArtifactRollbackError`](../src/ThematicAtlases/artifact_publisher.py) | Formally exported immutable-generation publication boundary, verified resolver, and recovery-specific double-failure exception. `publish` makes one fsynced manifest pointer authoritative while maintaining direct compatibility views; failed restoration exposes the publication error, recovery errors, and preserved recovery paths. |
| [`ThematicAtlases.collector.AtlasCollector`](../src/ThematicAtlases/collector/collector.py) | `(epmc_wrapper_factory=None, metadata_handlers=None, metadata_repositories=None, metadata_resume_orchestrator_factory=None)`. `None` selects built-in GEO/ArrayExpress handlers; `{}` deliberately disables all handlers. `collect_jsons(query=None, file=None, out=None, metadata_repositories=None, max_publications=None, max_publications_per_query=None, collect_metadata=True, checkpoint_store=None, scrape_fulltext_accessions=True) -> list[dict]`; `filter_accessions`, `is_handled_accession`, `collect_accession_metadata`, `available_accession_metadata`, `metadata_repository`, and `metadata_handler(repository: str) -> Any` expose typed routing boundaries. Unsupported repositories and malformed files raise; remote item outcomes are represented/checkpointed where supported; `out` writes JSON. |
| [`ThematicAtlases.collector.TraceMetadataResumer`](../src/ThematicAtlases/collector/resume.py) | `(collector_factory=None, epmc_wrapper_factory=None)`; `resume(trace_dir, *, audit_enrichment_only=False, retry_tags=None) -> dict`. Reads manifest/SQLite, writes progress or audit/template artifacts, performs network metadata work unless audit-only, and rejects malformed manifests or conflicting retry tags. |
| [`ThematicAtlases.filterer.ACCESSIONS`](../src/ThematicAtlases/filterer/review.py) | `"accessions"` atlas key. |
| [`ThematicAtlases.filterer.AGENTIC_CURATOR`](../src/ThematicAtlases/filterer/review.py) | `"agentic_curator"` review-payload key. |
| [`ThematicAtlases.filterer.PUBLICATIONS`](../src/ThematicAtlases/filterer/review.py) | `"publications"` record key. |
| [`ThematicAtlases.filterer.PUBLICATION_TEXTS`](../src/ThematicAtlases/filterer/review.py) | `"publication_texts"` shared-map key. |
| [`ThematicAtlases.filterer.PUBLICATION_TEXT_REF`](../src/ThematicAtlases/filterer/review.py) | `"publication_text_ref"` foreign-key field. |
| [`ThematicAtlases.filterer.REVIEW_FILTERS`](../src/ThematicAtlases/filterer/review.py) | Mutable set `{"none", "not_relevant", "not_relevant_and_unsure"}`; callers should treat it as a supported-value registry, not mutate it. |
| [`ThematicAtlases.filterer.AtlasFilterer`](../src/ThematicAtlases/filterer/filterer.py) | `(epmc_wrapper_factory=None, publication_text_reviewer=None)`. `filter_jsons(jsons=None, file=None, theme=None, review_filter="none", review_strategy="direct", reviewer=None, prune_accessions=False, ...) -> dict`; public helpers map identities/text references, split/assemble atlas parts, collect text, and review/filter. Bad JSON, invalid review controls, and uncaught text-fetch errors raise; review failures are retained as failed judgement payloads. |
| [`ThematicAtlases.filterer.PublicationTextReviewer`](../src/ThematicAtlases/filterer/review.py) | `(reviewer_factory=None, resume_orchestrator_factory=None, cancelled=None)`. `resume(trace_dir, *, theme=None, reviewer=None, strategy="direct", allow_theme_override=False, require_resolved_metadata=False, collect_metadata=False, defer_metadata_errors=False, require_main_datalinks_phase=False, publication_limit=None, review_action_limit=None, cancelled=None, snapshot_accessions=None, publication_keys=None, item_lock_timeout_seconds=None, metadata_item_timeout_seconds=None, publication_text_item_timeout_seconds=None, review_item_timeout_seconds=None) -> dict`; `review_and_filter`, `review_publication_texts`, context/normalization/filter helpers. `publication_limit` retains snapshot semantics; `review_action_limit` counts actual actions after prerequisites, compatible checkpoint reuse, and future cooldowns. Cancellation is cooperative and distinct from a main-phase yield. Retryable model/shared-criteria cooldowns retain `next_retry_at`; cumulative model request metrics enter the progress summary. |
| [`ThematicAtlases.harmonizer.AtlasHarmonizer`](../src/ThematicAtlases/harmonizer/harmonizer.py) | `(ontology_harmonizer=None, ontology_harmonizer_factory=None, ontostore=None, credential_checker=None, max_workers=1, capability_registry=None, resource_profile="standard", resource_overrides=None)`. `harmonize_datasets(datasets, details_out=None, harmonization_options=None, checkpoint_store=None) -> tuple[dict, list[dict]]`; `publication_context` and `harmonize_jsons` are public. Unsupported/repository-mismatched items receive status-v2 not-run envelopes; caught item failures preserve input metadata with safe failed envelopes; usable upstream results must carry status contract 2.0. |
| [`ThematicAtlases.wrappers.ArrayExpressWrapper`](../src/ThematicAtlases/wrappers/ae.py) | `(converter_factory=None, resource_profile="standard", resource_overrides=None)` and `metadata_handler_status="supported"`; `collect_accession_metadata(jsons, checkpoint_store=None)` converts BioStudies MAGE-TAB through the resource-profiled MSC fetcher and emits strict canonical MINiML 3.1 metadata. Typed and mapping converter results share the same transport boundary, and only versioned compatible checkpoints are replayed. |
| [`ThematicAtlases.wrappers.EuropePMCWrapper`](../src/ThematicAtlases/wrappers/epmc.py) | `(page_limit=5, page_size=1000, timeout=None, request_delay=0.5, max_retries=3, request_policy=None, resource_profile="standard", resource_overrides=None, publication_policy=None, link_graph_provider=None, ncbi_api_key=None, ncbi_tool="ThematicAtlases", ncbi_email=None)`. Europe PMC, preprint, and graph calls use the common host gate. The NCBI identity reaches every default ELink/ESummary call, while request values remain absent from logs. Publication text/full-text extraction uses per-item locks and the five discovery stop boundaries remain durable. |
| [`ThematicAtlases.wrappers.GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py) | `(api_key=None, tool="ThematicAtlases", email=None, timeout=None, request_delay=0.5, max_retries=3, request_policy=None, resource_profile="standard", resource_overrides=None, record_policy=None, enrich_metadata=True)`. Calls NCBI E-utilities through the shared host gate with the configured identity; omitted `api_key` reads `NCBI_API_KEY` without changing 0.5-second pacing. Compatible canonical metadata checkpoints are read-only reuse. |

Complete public-member signatures for the exported classes:

- [`AtlasCollector`](../src/ThematicAtlases/collector/collector.py):
  `resume_metadata(trace_dir, *, audit_enrichment_only=False, retry_tags=None) -> dict`;
  `collect_jsons(query=None, file=None, out=None, metadata_repositories=None,
  max_publications=None, max_publications_per_query=None, collect_metadata=True,
  checkpoint_store=None) -> list[dict]`;
  `filter_accessions(accessions, metadata_repositories=None) -> list[dict]`;
  `is_handled_accession(record, metadata_repositories=None) -> bool`;
  `collect_accession_metadata(jsons, metadata_repositories=None,
  checkpoint_store=None, retry_tags=None) -> list[dict]`;
  `available_accession_metadata(jsons, metadata_repositories=None,
  checkpoint_store=None) -> list[dict]`;
  `metadata_repository(record, metadata_repositories=None) -> str | None`;
  `metadata_handler(repository) -> callable`.
- [`TraceMetadataResumer`](../src/ThematicAtlases/collector/resume.py):
  `resume(trace_dir, *, audit_enrichment_only=False, retry_tags=None) -> dict`.
- [`AtlasFilterer`](../src/ThematicAtlases/filterer/filterer.py):
  `filter_jsons(jsons=None, file=None, theme=None, review_filter="none",
  review_strategy="direct", reviewer=None, prune_accessions=False,
  _review_progress_callback=None,
  _checkpoint_store=None) -> dict`;
  `publication_key(publication) -> tuple`;
  `publication_text_ref(publication) -> str`;
  `atlas_parts(jsons=None) -> tuple[list[dict], dict]`;
  `filter_inputs(jsons, file) -> tuple[list[dict], dict]`;
  `collect_publication_texts(jsons, publication_texts=None,
  checkpoint_store=None) -> dict`;
  `accessions_with_publication_text_refs(jsons, publication_texts) -> list[dict]`;
  `publication_with_text_ref(publication, publication_texts) -> dict`;
  `review_and_filter_publications(accessions, publication_texts, theme,
  review_filter, review_strategy="direct", reviewer=None,
  progress_callback=None, checkpoint_store=None,
  prune_accessions=False) -> tuple[list[dict], dict]`;
  `atlas_object(accessions, publication_texts) -> dict`. Underscore-prefixed
  parameters are internal continuation hooks, not supported caller controls.
- [`PublicationTextReviewer`](../src/ThematicAtlases/filterer/review.py):
  `resume(trace_dir, *, theme=None, reviewer=None, strategy="direct",
  allow_theme_override=False, require_resolved_metadata=False,
  collect_metadata=False, defer_metadata_errors=False,
  require_main_datalinks_phase=False, publication_limit=None,
  snapshot_accessions=None, publication_keys=None,
  item_lock_timeout_seconds=None, metadata_item_timeout_seconds=None,
  publication_text_item_timeout_seconds=None,
  review_item_timeout_seconds=None) -> dict`;
  `validate_options(theme, review_filter, strategy="direct") -> None`;
  `review_and_filter(accessions, publication_texts, theme, review_filter,
  reviewer=None, strategy="direct", prune_accessions=False) -> tuple[list[dict], dict]`;
  `publication_review_contexts(accessions) -> dict`;
  `review_publication_texts(publication_texts, contexts, theme, reviewer=None,
  progress_callback=None, checkpoint_store=None, strategy="direct") -> dict`;
  `filtered_result(accessions, publication_texts, review_filter,
  prune_accessions=False) -> tuple[list[dict], dict]`;
  `agentic_curator_review(theme, review, strategy="direct",
  review_input_hash=None, metadata_context=None) -> dict`;
  `json_object(value) -> dict`; `removed_review_judgements(review_filter) -> set[str]`;
  `normalized_review_judgement(publication_text) -> str`.
- [`AtlasHarmonizer`](../src/ThematicAtlases/harmonizer/harmonizer.py):
  `harmonize_datasets(datasets, details_out=None, harmonization_options=None,
  checkpoint_store=None) -> tuple[dict, list[dict]]`;
  `publication_context(record) -> str | None`;
  `harmonize_jsons(datasets, details_out=None, harmonization_options=None) -> dict`.
- [`ArrayExpressWrapper.collect_accession_metadata`](../src/ThematicAtlases/wrappers/ae.py):
  `(jsons, checkpoint_store=None) -> list[dict]`.
- [`EuropePMCWrapper`](../src/ThematicAtlases/wrappers/epmc.py):
  `collect_accessions(queries, max_publications=None,
  max_publications_per_query=None, checkpoint_store=None,
  scrape_fulltext_accessions=True, stop_after=None) -> list[dict]`;
  `collect_publications(...) -> list[dict]`;
  `publication_text_sections(text) -> list[dict]`;
  `collect_publication_texts(publications, checkpoint_store=None) -> dict`;
  `collect_datalinks(publications, checkpoint_store=None) -> list[dict]`;
  `accessions_from_datalinks(datalinks) -> list[dict]`;
  `accessions_from_link_graph(publications, checkpoint_store=None,
  cached_only=False, continue_predicate=None) -> list[dict]`.
- [`PubMedGDSLinkGraphWrapper`](../src/ThematicAtlases/wrappers/pubmed_gds.py):
  `discover(publications, checkpoint_store=None, cached_only=False,
  continue_predicate=None) -> list[dict]`.
- [`GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py):
  `collect_accession_metadata(jsons, checkpoint_store=None,
  retry_tags=None) -> list[dict]`;
  `available_accession_metadata(jsons, checkpoint_store) -> list[dict]`;
  `get_gse(accession) -> str | None`.
### Supported importable production helpers

- [`ThematicAtlases.document_adapter.AtlasDocumentAdapter`](../src/ThematicAtlases/document_adapter.py):
  `assemble(stage_result, *, atlas_metadata, run_id, created_at, theme,
  config, run_status, harmonization_details=None) -> AtlasDocument` converts
  mature internal stage mappings into the v1 aggregate;
  `to_legacy(document) -> dict` projects the minimum internal harmonizer input.
  Invalid identifiers, references, enum values, metadata, or summary
  relationships raise during `AtlasDocument` validation.
- [`ThematicAtlases.artifact_publisher.JsonArtifactBundlePublisher`](../src/ThematicAtlases/artifact_publisher.py):
  `(*, replace=os.replace)`; `publish(artifacts: Mapping[str | Path, Any]) ->
  PublishedArtifactBundle` writes deterministic newline-terminated JSON into an
  immutable generation, fsyncs files/directories, then atomically replaces one
  `current.json` manifest pointer. Destinations must be unique and share one
  parent. Direct output files remain compatibility views. A failed publication
  preserves the prior pointer and restores every view; if restoration also
  fails, `ArtifactRollbackError(publication_error, rollback_errors,
  recovery_paths)` identifies preserved backups and the generation for recovery.
  `resolve_current_bundle(pointer_path)` verifies pointer, manifest, artifact
  paths, and SHA-256 digests before returning the selected generation.
- [`ThematicAtlases.run_store.AtlasRunStore`](../src/ThematicAtlases/run_store.py):
  normalized Atlas v1 run database (SQL schema version 2) with `create_run`, `get_run`,
  `set_run_status`, `set_stage_state`, `add_work_item`,
  `work_items`, `record_attempt`, `attempts`, `register_artifact`, `artifact`,
  `artifacts`, `record_event`, `events`, `metadata`, and `metadata_items`.
  Relative artifact paths cannot escape the run and a role cannot silently
  change path. Opening legacy, foreign, or newer schemas raises
  `IncompatibleRunStoreError`.
- [`CheckpointStore(path, *, default_item_lock_timeout_seconds=None)`](../src/ThematicAtlases/checkpoint.py): public
  `set_meta`, `get_meta_json`, `get_meta`, `validate_fingerprint`,
  `amend_fingerprint`, `put`, `get`, `items`, `has_retryable`,
  `has_retryable_boundary`, `history`, `request_retries`, `archive_stage`,
  `archive_items`, `item_lock`, and `wait_for_provider_slot` methods own SQLite
  state and can raise
  `ValueError`, `RuntimeError`, filesystem, or SQLite errors without partial
  source deletion. `is_retryable_error(error) -> bool` and
  `failure_category(error) -> str` classify failures.
  The selective retry entry is `CheckpointStore.request_retries`; all selected
  history rows and retry transitions commit in one transaction. Status/stage
  and stage/item/history indexes support resume, retry reporting, and history
  lookup without full checkpoint-table scans. `item_lock` supports a bounded
  wait, and provider
  slots persist one run-local next-request time under a kernel-released lock.
- [`TracePublicationReviewResumer.resume(trace_dir, *, theme=None,
  strategy="direct", reviewer=None, allow_theme_override=False,
  require_resolved_metadata=False, collect_metadata=False,
  defer_metadata_errors=False, require_main_datalinks_phase=False,
  publication_limit=None, item_lock_timeout_seconds=None,
  metadata_item_timeout_seconds=None,
  publication_text_item_timeout_seconds=None,
  review_item_timeout_seconds=None) -> dict`](../src/ThematicAtlases/filterer/resume.py)
  validates a trace, captures the current datalink snapshot once, optionally
  downloads/reuses metadata best-effort, reviews the eligible snapshot, and
  writes review progress. The default resolved gate accepts `available`,
  `partial`, `unavailable`, and `error`; `defer_metadata_errors=True` limits
  admission to the first three so pending, retryable, terminal-error, missing,
  and unknown contexts defer the complete publication. A collecting result
  adds deterministic snapshot/selection/attempt/reuse/defer/timeout/status
  counts under `metadata_summary`. With phase enforcement it only starts items
  during main `datalinks`; optional positive limits and hard deadlines bound
  work. It writes `incremental_review_progress.json`.
  [`DevTraceWriter`](../src/ThematicAtlases/trace.py) exposes
  `checkpoint_store`, `existing`, `write`, and `metadata` for readable artifacts;
  run IDs and artifact names must be single filesystem-safe path components.
  Each atomic write uses a unique temporary file so cooperating processes do
  not race on a shared temporary pathname.
- [`GoogleCredentialPreflight.check() -> str`](../src/ThematicAtlases/credentials.py)
  refreshes ADC and verifies a quota project, raising actionable runtime errors.
  [`load_query_catalog(path) -> dict`](../src/ThematicAtlases/query_catalog.py)
  validates the versioned static query JSON.
- [`RetryTags`](../src/ThematicAtlases/wrappers/enrichment.py) exposes
  `normalized_dict` and `digest`; `load_retry_tags(path)` validates tag JSON.
  `CheckpointedPubmedFetcher.pubmed_summary`, `CheckpointedINSDCFetcher.fetch_ena_fastq_files`,
  `CheckpointedINSDCFetcher.fetch_ena_file_report`, and
  `EnrichmentAuditor.audit` implement checkpointed enrichment and offline gap
  inspection.
- [`summary_path(atlas_path) -> Path` and
  `build_atlas_summary(atlas, atlas_path=None) -> dict`](../src/ThematicAtlases/summary.py)
  derive deterministic output paths/content.
  [`workflow_activity_lock(dev_out_dir, *, exclusive, blocking=False)` and
  `archive_existing_runs(...)`](../src/ThematicAtlases/run_archive.py) own
  cross-process locking and verified relocation.

Detailed record shapes, endpoint fallbacks, and checkpoint behavior continue
under [collector](#collector), [filterer](#filterer),
[harmonizer](#harmonizer), [Europe PMC](#epmc-wrapper),
[GEO](#geo-wrapper), and [benchmark package](#benchmark-package).

<a id="principal-workflows"></a>
## Principal workflows

<a id="workflow-collection"></a>
### Workflow 1: Collection

The CLI/Python collection path resolves queries, finds dataset links, routes
metadata, maps publication text, and optionally reviews/filter records.

```text
queries -> search -> datalinks + publication-text accession scan -> merge/dedupe
   |          |             | disabled                           |
 invalid    no hits         +----------> datalinks only           v
   v          v                                      capability route
 error     empty atlas                               | unsupported
                                                    +--> terminal inventory
                                      |
                     +----------------+----------------+
                     v                                 v
               metadata first                   review first
                     |                                 |
                     +------ text/review/filter -------+
                                      |
                           legacy stage result
                                      |
                           AtlasDocumentAdapter
                                      |
                           Atlas v1 snapshot
```

#### Numbered stages

1. `Atlas.collect_datasets` validates and orders query sources.
2. Optional generated queries follow explicit and file queries; credential or
   generation failure terminates before discovery. The resolved sequence is
   the authoritative `run.config.queries` value and is checkpointed so trace
   publication and resume preserve the queries actually sent to discovery.
3. `AtlasCollector.collect_jsons` calls Europe PMC Datalinks and, by default,
   scans Europe PMC `fullTextXML`, supported bioRxiv/medRxiv JATS, or abstract
   fallback with the deterministic accession registry. Visible text covers
   GEO and curated biomedical accession families; hidden JATS `href` targets
   cover stable curated portals and data repositories, not generic file shares.
   It merges case-insensitive IDs with precise provenance, routes supported
   metadata handlers, and marks other detected repositories terminal.
   `collect_datalinks()` itself remains API-only.
4. Before review, terminal records are partitioned into the separate
   unsupported inventory. They receive no metadata download, review, pruning,
   or harmonization. `AtlasFilterer.filter_jsons` maps the remaining full text with abstract/no-text outcomes,
   optionally calls review, applies the selected filter, and assembles output.
5. `AtlasDocumentAdapter` assembles and validates an Atlas v1 snapshot whose
   run status is `running`. An output path receives that mapping atomically.
   Tracing writes `collection_snapshot.json` and registers only the
   `collection_snapshot` role. Empty searches return a valid empty document.

#### Pseudocode

```text
Atlas.collect_datasets(args)                    # interface/orchestrator
  -> AtlasCollector.collect_jsons(...)          # internal call
     -> EuropePMCWrapper.collect_accessions     # search/datalinks/text scan
        -> extract_accessions_from_text/links   # deterministic curated scans
     -> metadata_handler.collect_accession...   # internal -> external/system
  -> AtlasFilterer.filter_jsons(...)            # internal legacy stage call
  -> AtlasDocumentAdapter.assemble(...)         # boundary conversion
  -> JsonArtifactBundlePublisher.publish(...)   # persistence, if requested
  <- AtlasDocument v1 mapping
```

#### Evidence

Definitions and decisive calls:
[`Atlas.collect_datasets`](../src/ThematicAtlases/atlas.py),
[`AtlasCollector.collect_jsons`](../src/ThematicAtlases/collector/collector.py),
[`AtlasFilterer.filter_jsons`](../src/ThematicAtlases/filterer/filterer.py), and
[`EuropePMCWrapper.collect_accessions`](../src/ThematicAtlases/wrappers/epmc.py).

<a id="workflow-atlas-creation"></a>
### Workflow 2: Atlas creation

Atlas creation composes collection and harmonization and writes the requested
atlas, summary, details, and optional trace. Eight explicit durable boundaries
permit staged advancement without changing checkpoint identity.

```text
create_atlas -> preflight/cache -> collect -> harmonize
     |              |                          |
     +-- error       +-- empty ----------------+--> empty atlas
                                                |
                                  item failure -> original + diagnostic
                                               |
                                   AtlasDocumentAdapter
                                               |
                             staged Atlas + summary bundle
```

#### Numbered stages

1. `Atlas.create_atlas` validates its required nonblank theme, ensures a query
   exists when default-on generation is disabled, and validates the independent
   default-on thematic-review switch before external work.
2. It performs eligible query-generation, review, and ontology credential/cache
   preflight. Invalid query/review/cache configuration or failed credential/cache
   preparation raises before collection.
3. It invokes the mature collection stage behind the public adapter; an empty
   collection remains a valid empty Atlas v1 document.
4. `stop_after` may pause after the completed search-result union, Datalinks,
   publication text, deterministic text accession extraction, accession graph,
   metadata, review, or harmonization. The pause retains run status `running`,
   writes an atomic `pause_<stage>_summary.json`, records `run_paused`, and
   stores stage/frontier counts, invocation identity, and hashes in SQLite.
   No later-stage or final marker is published. A normal resume consumes any
   compatible main/worker checkpoints and continues downstream.
5. It otherwise invokes the mature harmonization stage; caught item failures retain
   original metadata and become v1 diagnostics/status.
6. `AtlasDocumentAdapter` assembles and validates the final aggregate; the
   unsupported inventory is deliberately outside Atlas v1 datasets.
7. The summary includes aggregate unsupported counts. When `out` is set,
   `JsonArtifactBundlePublisher` stages and parses the Atlas plus derived summary
   and any explicitly requested detailed inventory, backs up prior files, then replaces them. A failed
   replacement restores the full prior pair or leaves no first-run artifacts.
8. A trace writes readable stage files, including
   `unsupported_accessions.json`, and registers `final_atlas`, `summary`,
   `unsupported_accessions`, and details roles in `atlas_run.sqlite3`; filesystem errors propagate.

#### Pseudocode

```text
Atlas.create_atlas(theme, explicit/file args)   # interface/orchestrator
  -> validate theme/generation/review controls  # no external work yet
  -> explicit + file + generated queries        # stable ordering
  -> _preflight_credentials/_prepare_cache      # internal/external policy
  -> _collect_datasets_legacy(...)              # internal stage workflow
  -> AtlasHarmonizer.harmonize_datasets(...)    # internal stage workflow
  -> AtlasDocumentAdapter.assemble(...)         # boundary conversion
  -> JsonArtifactBundlePublisher.publish(...)   # bundle persistence
  -> AtlasRunStore stage/artifact/event writes  # trace persistence
  <- AtlasDocument v1 mapping
```

#### Evidence

Definitions/calls:
[`Atlas.create_atlas`](../src/ThematicAtlases/atlas.py),
[`Atlas.collect_datasets`](../src/ThematicAtlases/atlas.py),
[`Atlas.harmonize_datasets`](../src/ThematicAtlases/atlas.py),
[`AtlasDocumentAdapter`](../src/ThematicAtlases/document_adapter.py), and
[`JsonArtifactBundlePublisher`](../src/ThematicAtlases/artifact_publisher.py).

<a id="workflow-harmonization"></a>
### Workflow 3: Harmonization

Harmonization transforms eligible accession metadata while preserving order and
original metadata for unsupported, null, or failed work.

```text
dataset -> eligible? -- no --> not_run/original
              |
             yes -> cached? -- yes --> reuse
                        |
                        no -> credentials/options valid?
                                  | no -> invocation error
                                  v
                         upstream harmonizer
                           | success/degraded
                           + caught item error -> original + error
```

#### Numbered stages

1. Public `Atlas.harmonize_datasets` parses and validates Atlas v1. Unknown or
   legacy unversioned accessions fields fail before delegated harmonization.
2. `AtlasDocumentAdapter.to_legacy` projects the minimum stage mapping, then
   `AtlasHarmonizer` validates controls and computes work keys from metadata,
   context, options, and the complete harmonization execution identity.
3. Non-mapping/list metadata and unsupported repository identities retain the
   original record with a status-v2 `not_run` envelope; duplicate work keys
   share one result without changing accession order.
4. Model-enabled controls preflight credentials; invalid options or credentials
   fail the invocation before provider work.
5. Unique eligible work is decoded through MSC 5's `MINiMLCodec`, calls the
   delegated patch-first `harmonize_miniml_annotations`, applies the
   source-bound `MINiMLHarmonizationPatch` 3.0 to a copy, and decodes the
   MINiML 3.1 result again. Legacy injected
   test/adaptor harmonizers may still expose the mutating wrapper.
6. Results and details, including execution identity provenance and target-local
   semantic `lookup_aliases`, are
   memoized/checkpointed; caught item failures remain local, retain original
   metadata, and persist only a safe error envelope.
   Successful and degraded provider results must contain a valid status 2.0
   envelope. The adapter retains every provider
   target that has a usable metadata path, including unmatched targets, and
   attaches an ontology match only when the provider supplied a complete
   label/accession/framework identity. It then validates the returned v1
   document. Requested details-file errors propagate.

#### Pseudocode

```text
Atlas.harmonize_datasets(datasets)              # interface
  -> HarmonizeDatasetsWorkflow.run               # operation-local orchestration
  -> AtlasDocument.from_mapping                 # strict v1 validation
  -> AtlasDocumentAdapter.to_legacy             # internal projection
  -> AtlasHarmonizer.harmonize_datasets         # internal call
     -> MINiMLCodec.decode_many                 # typed package boundary
     -> ontology_harmonizer.harmonize_miniml_annotations
     -> ontology_harmonizer.apply_miniml_harmonization_patch
     -> CheckpointStore.put                     # persistence call
  -> AtlasDocumentAdapter.assemble              # strict v1 result
  <- updated Atlas v1 + optional details sidecar
```

#### Evidence

Definitions/calls:
[`Atlas.harmonize_datasets`](../src/ThematicAtlases/atlas.py),
[`AtlasHarmonizer.harmonize_datasets`](../src/ThematicAtlases/harmonizer/harmonizer.py),
and [`CheckpointStore.put`](../src/ThematicAtlases/checkpoint.py).

<a id="workflow-resume-and-retry"></a>
### Workflow 4: Resume and selective retry

```text
trace admission -> explicit retries -> reconstructed discovery
                -> cached conversions/reviews -> harmonization -> publication
```

#### Numbered stages

1. Validate workflow contract 2.0 before writable open: `validate_trace(path)`.
2. Validate and archive explicit retry selections: `store.request_retries(...)`.
3. Rebuild completed discovery and re-enter shared stages: `CheckpointViews + collect`.
4. Reuse complete/partial conversions and valid review decisions: `input_hash == saved_hash`.
5. Run only remaining whole harmonizations: `harmonize(work_key)`.
6. Rebuild filtering, pruning, summaries and publish: `assemble(outcomes)`.

The same saved outcomes feed workers, independent continuations, metadata forks
and trace-reading benchmarks. The two text pause names are aliases. No intermediate
JSON is needed. See [contract 2.0](#workflow-checkpoints-v2) for branches, item status,
explicit partial retries, resource limits and legacy rejection.

#### Pseudocode

```text
validate_trace(run)
request_retries(selection)
datasets = collect(shared_stages, saved_outcomes)
result = harmonize(datasets, saved_outcomes)
publish(result)
```

#### Evidence

[`ResumeAtlasWorkflow`](../src/ThematicAtlases/workflows/resume.py),
[`CheckpointViews`](../src/ThematicAtlases/runtime/views.py), and
[`offline acceptance tests`](../tests/test_checkpoint_v2_e2e.py).

<a id="workflow-query-amendment-and-archive"></a>
### Workflow 5: Query amendment and whole-run archive

Amendment changes one trace's query contract without deleting item checkpoints;
whole-run archival safely relocates inactive traces and fixed artifacts.

```text
amend -> validate aligned query limits -> archive fingerprint -> install new
  \-> unchanged normalized configuration -----------------------> no-op/current
archive run -> exclusive lock -> checkpoint -> snapshot/copy/resnapshot
  -> matching checksums -> fsync tree -> publish -> fsync parents -> delete source
  \-> pre-publish error => keep source and publish nothing
  \-> post-publish finalization error => ArchiveDurabilityError(destination)
```

#### Numbered stages

1. `Atlas.amend_queries` normalizes queries and calls fingerprint amendment.
2. Empty/misaligned/non-positive inputs or unsafe/active trace state raise;
   equivalent normalized configuration does not duplicate work.
3. `Atlas.archive_existing_runs` delegates to lock-aware archive functions,
   assigning fixed artifacts to the newest trace or an orphan archive.
4. The archive implementation rejects active locks, symlinks, unsafe names,
   nested roots, and collisions before deletion.
5. SQLite checkpointing must report no busy readers and leave no non-empty WAL.
6. The staged tree and published directory entry are fsynced before cleanup.
   A failure after atomic publication reports the durable destination explicitly
   instead of presenting the operation as an unpublished failure.
   Durable files are hashed before and after a staged copy, while the exact
   trace-root WAL/SHM sidecars are excluded; both source snapshots and the copy
   must match before manifest relocation and atomic publication. Any failure
   keeps sources.

#### Pseudocode

```text
runner/Atlas amendment or archive               # interface
  -> CheckpointStore.amend_fingerprint          # persistence call
  -> run_archive.archive_existing_runs          # system call
     -> SQLite checkpoint + stable snapshots   # persistence/system calls
  <- amendment path or archive paths
```

#### Evidence

Definitions/calls:
[`Atlas.amend_queries`](../src/ThematicAtlases/atlas.py),
[`CheckpointStore.amend_fingerprint`](../src/ThematicAtlases/checkpoint.py),
and [`archive_existing_runs`](../src/ThematicAtlases/run_archive.py).

<a id="workflow-independent-review"></a>
### Workflow 6: Independent publication review

The independent worker reviews a stable or growing trace snapshot without
rerunning discovery and may safely coexist with a cooperating collector while
that collector remains in its advertised Datalinks phase.

```text
trace -> manifest/fingerprint validation -> fixed publication snapshot
   |                           |                         |
 invalid/error       main phase is downstream     main phase is datalinks
                                |                         |
                         yield without work       bounded metadata/text/review
                                                          |
                                              canonical checkpoints + isolated
                                                   incremental progress
```

#### Numbered stages

1. A Python caller supplies a trace and review options to
   `PublicationTextReviewer.resume`.
2. `PublicationTextReviewer.resume` uses `TracePublicationReviewResumer`, which
   validates the manifest/theme and rebuilds a stable current datalink snapshot.
3. A deterministic optional publication limit is applied before metadata work.
   When requested, metadata is downloaded or reused one accession at a time,
   and the publication is deferred unless every linked status is reviewable.
4. Before every metadata, publication-text, and review item, the worker checks
   the main phase. It starts only in `datalinks` and yields before the next item
   after the main collector switches to `downstream`.
5. The filterer fetches/reuses one publication text at a time and constructs
   accession/metadata context. Bounded item-lock waits and optional hard
   deadlines defer busy or stuck work while releasing all file locks.
6. `PublicationTextReviewer.review_publication_texts` derives one theme-level
   criterion catalogue when the reviewer supports that contract, persists it in
   run metadata, and passes the identical catalogue to every `review_relevancy`
   call. Canonical item checkpoints prevent duplicate completion and are reused
   by normal Atlas review.
7. Model exceptions remain item-local. `incremental_review_progress.json` is
   written independently of the main workflow's `resume_review_progress.json`;
   the SQLite checkpoints, not the sidecar progress file, are shared authority.

#### Pseudocode

```text
PublicationTextReviewer.resume                  # Python interface
  -> TracePublicationReviewResumer.resume       # internal orchestrator
  -> CheckpointStore.item_lock/provider slot    # cross-process coordination
  -> PublicationTextReviewer dispatch
     -> reviewer.derive_criteria                 # once per review identity/theme
     -> reviewer.review_relevancy                # external package/model API
  -> CheckpointStore.put                        # persistence call
<- reviewed datasets/progress
```

#### Evidence

Definitions/calls:
[`TracePublicationReviewResumer.resume`](../src/ThematicAtlases/filterer/resume.py),
and
[`PublicationTextReviewer.review_publication_texts`](../src/ThematicAtlases/filterer/review.py).

<a id="workflow-metadata-repair"></a>
### Workflow 7: Metadata collection, audit, and repair

The metadata worker resumes missing GEO metadata, audits enrichment gaps, or
applies an explicit retry-tag file to selected identifiers.

```text
trace -> mode?
          +-> no flag: resume missing metadata -> checkpoint results
          +-> audit only -> gap report, no repairs
          +-> retry tags -> repair selected cached identifiers -> merge
          \-> conflicting flags/parser error; bad tag history/error
```

#### Numbered stages

1. A Python caller supplies a trace and selects normal resume, offline audit,
   or explicit tagged repair.
2. `AtlasCollector.resume_metadata` delegates to `TraceMetadataResumer`.
3. Audit reads cached legacy packages, writes candidate/template artifacts, and
   makes no network calls.
4. Normal/repair mode rebuilds the current datalink snapshot, reuses GEO
   resolution/metadata rows, and calls remote enrichment only for missing or
   explicitly tagged identifiers.
5. Every selected identifier records a typed succeeded/failed repair outcome.
   Failed repairs persist safe error envelopes, retain the last usable package,
   set `metadata_status="partial"`, and make the final Atlas run `partial`.
   The public diagnostic exposes counts, not raw provider exception messages.
6. A repeated identical tag is idempotent; a reused tag ID with different
   content raises. Progress/log output is persisted; invalid trace/files raise.

#### Pseudocode

```text
AtlasCollector.resume_metadata                  # Python interface
     -> TraceMetadataResumer.resume             # internal orchestrator
     -> GEOWrapper.collect_accession_metadata   # external/system boundary
     -> EnrichmentAuditor.audit                 # internal/checkpoint reads
  <- progress/audit/repair artifacts
```

#### Evidence

Definitions/calls:
[`TraceMetadataResumer.resume`](../src/ThematicAtlases/collector/resume.py),
[`GEOWrapper.collect_accession_metadata`](../src/ThematicAtlases/wrappers/geo.py),
and [`EnrichmentAuditor.audit`](../src/ThematicAtlases/wrappers/enrichment.py).

<a id="workflow-fixed-runners"></a>
### Archived non-canonical fibrosis runners

The former repository-root fibrosis workflows were archived on 2026-08-03.
They are absent from version control and are not production entry points. Local
recovery copies live in the ignored
`.dev/archive/fibrosis-workflows-2026-08-03/` directory. The canonical workflow
is `gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py` in the parent
adapter repository.

```text
historical root runners -> ignored local archive
                              |
                              +-> recovery reference only
canonical execution -------> parent adapter fibrosis workflow
supported reuse -----------> CLI / Python APIs / retained data
```

#### Numbered stages

1. Six non-canonical runner files and their runner-specific tests moved to the
   ignored local archive.
2. `docs/theme_fibrosis.txt`, `config/fibrosis_discovery_queries.json`, the
   benchmark runners, and their shared four-set reference TSV remain tracked.
3. The installed CLI and reusable Python workflow APIs remain supported.
4. Production fibrosis atlas creation routes to the parent adapter script.

#### Pseudocode

```text
canonical adapter script                        # external repository interface
  -> ThematicAtlases Python API                  # supported internal boundary
  -> retained theme/reference inputs             # tracked files
  <- atlas artifacts
```

#### Evidence

Definitions/calls:
[`Atlas.create_atlas`](../src/ThematicAtlases/atlas.py),
[`load_query_catalog`](../src/ThematicAtlases/query_catalog.py), and the
[retained fibrosis theme](theme_fibrosis.txt).

<a id="workflow-benchmarking"></a>
### Workflow 8: Benchmarking

Three directly executed scripts own benchmarking. Query recall reads raw
Europe PMC search-page checkpoints before accession discovery or review.
Reviewed-output recall compares a later trace artifact with the same
packaged/custom TSV. Review classification takes a separately labeled identifier
CSV, hydrates stable public inputs without a trace, and calls the production TA
reviewer. There is no benchmark Python API or console entry point.

```text
trace SQLite search pages + shared TSV -> query union/per-query exact recall
       | incomplete query ----------------> lower-bound schema 1.0 report
       | malformed -----------------------> exit 1, preserve old report

review artifact + shared TSV ------------> reviewed-output recall report
labeled CSV -> hydrate/cache -> reviewer -> three-class metrics report
```

#### Numbered stages

1. Both recall runners require `TRACE_DIR`, share the same default/custom TSV,
   and default `--out` to the Git-ignored `benchmarks/` directory.
2. Shared TSV loading requires the exact ordered five-column header, no double
   quotes, an optional integer reference number, a title, and at least one valid
   DOI or PMID per row; missing, reordered, unexpected, or surplus fields fail.
3. Query recall opens `atlas_run.sqlite3` in a query-only transaction, validates
   `resolved_queries`, and reads raw `search_queries` plus `search_pages`
   checkpoints without constructing `CheckpointStore` or reading later stages.
4. Complete query statuses yield final scores. Missing, pending, retryable, or
   terminal query states retain available pages and yield an explicit lower
   bound; malformed structures or inconsistent completed counts fail.
5. Reviewed-output trace loading prefers `resume_review_progress.json`, then
   `02_reviewed_datasets.json`, then `06_final_atlas.json`.
6. Exact normalized DOI/PMID identities produce matched, missed, or conflict
   rows after connected-identity deduplication. Query recall scores the union,
   every reference set, and each query while retaining query provenance.
7. Each runner atomically replaces only its own schema `1.0` JSON report.

#### Pseudocode

```text
benchmark_fibrosis_meta_pubs_recall.py TRACE_DIR [--references TSV] [--out DIR]
  -> load/validate combined TSV and selected trace artifact
  -> normalize/group references and discovered publications
  -> score aggregate and each reference_set_id
  -> atomic temp-file replacement
  <- print report path and exit 0

benchmark_fibrosis_meta_pubs_query_recall.py TRACE_DIR
    [--references TSV] [--out DIR]
  -> load/validate shared TSV
  -> read one query-only SQLite snapshot of resolved queries and search pages
  -> normalize/group raw DOI/PMID hits and preserve query provenance
  -> score aggregate, each reference_set_id, and each query
  -> mark final or lower_bound; atomic temp-file replacement
  <- print report path and exit 0

benchmark_fibrosis_meta_pubs_review.py [DATASET_CSV] [--out DIR]
    [--cache CSV] [--raw-cache SQLITE] [--hydrate-only]
    [--retry-terminal-metadata] [--refresh-cache] [--include-text-only] [--verbose]
  -> validate publication_id/DOI/PMID/expected_decision rows
  -> exact Europe PMC text + fully enriched accession metadata hydration
     (GEO PubMed/SRA/ENA identifier enrichment enabled)
  -> checkpoint search/text/Datalinks, compressed source GEO XML or AE IDF/SDRF,
     pre-canonical mappings, strict diagnostics, canonical packages, and enrichment
  -> retry any failed/incomplete hydration once using successful stage checkpoints
  -> retain downloaded GEO base packages as partial if enrichment exhausts
  -> cache every publication as a terminal success, negative, or exhausted failure
  -> atomically derive compact CSV plus identifiers/status-only audit
  -> with --hydrate-only, stop without reviewer/model initialization or report writes
  -> with --retry-terminal-metadata, retry only terminal GEO/AE construction twice,
     reusing checksum-verified source evidence in an atomic staging database
  -> with --verbose, log each cache/hydration action and review-stage status
  -> default: skip still-incomplete rows before constructing reviewer inputs
  -> with --include-text-only, also admit non-empty-text rows with zero accessions
  -> PublicationTextReviewer.review_publication_texts(theme=packaged fibrosis theme)
  -> score relevant/not_relevant/unsure overall and by context tier
  -> retain row failures outside accuracy while preserving recall denominators
  -> atomic schema 1.1 report replacement
  <- print report path and exit 0
```

#### Evidence

Definitions/calls:
reviewed-output [`run_benchmark`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_recall/benchmark_fibrosis_meta_pubs_recall.py),
query-recall [`run_benchmark`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_query_recall/benchmark_fibrosis_meta_pubs_query_recall.py),
and direct [`main`](../src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_query_recall/benchmark_fibrosis_meta_pubs_query_recall.py).

<a id="extension-and-change-guidance"></a>
## Extension and change guidance

- Add a metadata repository through an adapter with the collector handler
  contract, register selection/validation, preserve provenance/status fields,
  and test routing, no-data, transient, terminal, and resume behavior.
- Add or replace a collector, filterer, harmonizer, or publisher through the
  corresponding `ThematicAtlases.ports` protocol. Keep application assembly in
  `AtlasDocumentService`; do not make a port depend on CLI parsing or a concrete
  sibling package.
- Add CLI options by updating parser validation and forwarding tests, the README
  option table, this handoff, and fingerprints when the option changes work.
- Add checkpointed stages with stable stage/item keys, explicit status/failure
  categories, immediate item-cache commits, normalized `AtlasRunStore` stage
  state, deterministic reconstruction, and selective retry tests. Never mark
  an external call complete before its durable result.
- Extend the public wire contract by changing the typed `AtlasDocument` model,
  strict codec, adapter, owner golden fixture, downstream copied fixtures, and
  docs together. Do not assemble public JSON in stage components or add
  unversioned top-level fragments.
- Change trace schemas through explicit schema versions/migrations. Keep one
  `atlas_run.sqlite3`, artifact paths run-relative, and role/path conflicts
  fail-closed. Do not infer v1 lifecycle state from legacy JSON filenames or a
  separate `resume_state.sqlite`.
- Publish related JSON through `JsonArtifactBundlePublisher`; add fault
  injection for every new bundle boundary so first-run cleanup and overwrite
  restoration remain proven.
- Add review/harmonization providers behind injected collaborators. Keep
  credentials and provider payloads out of logs, isolate per-item failures, and
  document which controls require network/model access.
- Add principal workflows to the architecture map, workflow section,
  `docs/index.md`, README Guide when user-facing, and focused/full tests.
- Avoid direct wrapper-to-CLI coupling, hidden mutation of caller mappings,
  bypassing the adapter/run-store/publisher boundaries, unverified archive
  deletion, or copying delegated sibling-package internals into this
  repository's documentation.

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`ThematicAtlases` provides implemented workflows for discovering biomedical
datasets from publications, collecting repository metadata, reviewing relevance,
harmonizing ontology-backed fields, resuming/retrying traced work, and
benchmarking saved outputs.

Live package files:

```text
src/ThematicAtlases/
├── __init__.py
├── atlas.py
├── checkpoint.py
├── cli_atlas.py
├── credentials.py
├── query_catalog.py
├── run_archive.py
├── run_lifecycle.py
├── summary.py
├── trace.py
├── collector/
│   ├── __init__.py
│   ├── collector.py
│   └── resume.py
├── filterer/
│   ├── __init__.py
│   ├── filterer.py
│   ├── resume.py
│   └── review.py
├── harmonizer/
│   ├── __init__.py
│   └── harmonizer.py
└── wrappers/
    ├── ae.py
    ├── __init__.py
    ├── enrichment.py
    ├── epmc.py
    ├── geo.py
    ├── geo_records.py
    └── publication_policy.py

src/benchmark_ThematicAtlases/
├── __init__.py
├── _fibrosis_references.py
├── benchmark_fibrosis_meta_pubs_recall/
│   ├── __init__.py
│   ├── benchmark_fibrosis_meta_pubs_recall.py
│   └── fibrosis_meta_publications.tsv
├── benchmark_fibrosis_meta_pubs_query_recall/
│   ├── __init__.py
│   └── benchmark_fibrosis_meta_pubs_query_recall.py
└── benchmark_fibrosis_meta_pubs_review/
    ├── __init__.py
    ├── benchmark_fibrosis_meta_pubs_review.py
    ├── fibrosis_meta_publications_review.csv
    └── theme_fibrosis.txt
```

Root interfaces and configuration:

```text
config/fibrosis_discovery_queries.json
pyproject.toml
requirements.txt
README.md
LICENSE
.gitignore
```

Canonical/supporting docs and tests:

```text
docs/codebase.md
docs/index.md
docs/dev.md
docs/memory.md
docs/burndown.md
docs/theme_fibrosis.txt
tests/test_*.py
```

Ignored runtime directories such as `.env/`, `.out/`, `benchmarks/`, caches,
and trace output are not part of the tracked source tree.

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Package version metadata is `6.0.0`; new output uses Atlas document schema 1.1 and canonical MSC MINiML 3.1 metadata with optional retained patch 3.2 provenance. Readers retain the previous contracts. Harmonization checkpoints bind AC source, prompts, policies and serialization identity.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies contain independently installable
  `agentic-curator>=4.3,<5`, `google-auth>=2,<3`,
  `meta-standards-converter>=5.2.1,<6`, and `requests>=2.31,<3`. MSC 5.2.1 supplies
  canonical H5AD metadata schema 1.0 while retaining the public GEO conversion
  interfaces used by this repository. No build or
  runtime dependency resolves through a sibling checkout or Git URL.
- `dependency-provenance/pylock.python312-linux-x86_64.toml` locks every
  external Python 3.12/Linux x86_64 runtime artifact by exact version, index
  URL, and SHA-256. Its deterministic CycloneDX 1.6 SBOM is derived from the
  lock. Agentic Curator and MSC remain separately hashed/signed internal
  distributions. `release-policy.json` requires a verified signed artifact
  manifest and an approved offline advisory snapshot no older than seven days,
  with critical/high/medium/low update SLAs of 2/7/30/90 days. Those trusted
  operator artifacts are not fabricated in the repository, so the composing
  release gate remains blocked until they are supplied.
- The `dev` optional dependency group contains `pytest>=8`.
- The public wire contract is Atlas document schema 1.0 and downstream H5AD projection uses H5AD metadata schema 1.0. The internal run-store SQL migration number is independently `2`; it is not an Atlas document version.
- `requirements.txt` delegates to the runtime project metadata with `-e .`; install it with `python3 -m pip install -r requirements.txt`. Development and test environments use `python3 -m pip install -e ".[dev]"`. The canonical test command is `.env/bin/python -m pytest -q`; the autouse test guard blocks sockets and HTTP transports. Only marked tests physically under `tests/live_api` may enable a fixed-host, bounded transport when `RUN_LIVE_API_TESTS=1`. Subprocess creation remains blocked unless a test declares `allow_subprocess`. On 2026-08-10 this deterministic gate reported `545 passed, 4 skipped`; the current full-suite result is recorded under [Test And Verification Status](#test-and-verification-status).

<a id="live-api-provider-contracts"></a>
### Live API provider contracts

`tests/live_api/test_public_provider_contracts.py` owns Europe PMC
search/datalinks/full text, bioRxiv details/JATS, GEO E-utilities, and
ArrayExpress BioStudies MAGE-TAB parsing contracts.
They use 10-second timeouts, no retries or delays, at most 12 sends per test,
and a fixed EBI/NCBI/preprint host allowlist. Run them with
`RUN_LIVE_API_TESTS=1 .env/bin/python -m pytest tests/live_api -m live_api -vv`.
- The distribution uses a `src/` layout with setuptools package discovery for both `ThematicAtlases` and `benchmark_ThematicAtlases`.
- The installed console command is `thematic-atlas`, pointing to `ThematicAtlases.cli_atlas:main`.

<a id="public-api"></a>
## Public API

`src/ThematicAtlases/__init__.py` intentionally exports only
`__version__ == "4.3.0"`. Application and domain imports remain explicit, for
example `ThematicAtlases.atlas.Atlas` and
`ThematicAtlases.domain.AtlasDocument`.

The live atlas class is `Atlas` in `src/ThematicAtlases/atlas.py`. Import callers must use:

```python
from ThematicAtlases.atlas import Atlas
```

`Atlas.archive_existing_runs(...)` is the public whole-run archival API. It
moves every inactive trace for one workflow into a verified archive while
preserving the trace layout for later `Atlas.resume()` calls.

The thematic reviewer/curator code has moved to the separate `agentic-curator` package. Import callers must use:

```python
from agentic_curator import ThematicReviewer
```

`ThematicAtlases` depends on `agentic-curator` but does not expose `ThematicAtlases.curator` or a curator CLI. The atlas workflow can call `ThematicReviewer` during `collect_datasets()` when a `theme` is supplied. Without a theme, thematic review is skipped and the publication text enrichment behavior is preserved.

<a id="benchmark-package"></a>
## Benchmark Package

`src/benchmark_ThematicAtlases/` contains separate direct reviewed-recall,
query-recall, and review-classification benchmark directories. The former `ThematicReviewerBenchmark`,
`thematic_reviewer/`, and empty `ontology_harmonizer/` namespaces are removed.
The package root and all three subpackages export no benchmark Python API.

Run the benchmark from the repository root:

```text
python src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_recall/benchmark_fibrosis_meta_pubs_recall.py TRACE_DIR [--references TSV] [--out DIRECTORY]
python src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_query_recall/benchmark_fibrosis_meta_pubs_query_recall.py TRACE_DIR [--references TSV] [--out DIRECTORY]
python src/benchmark_ThematicAtlases/benchmark_fibrosis_meta_pubs_review/benchmark_fibrosis_meta_pubs_review.py [DATASET_CSV] [--out DIRECTORY] [--cache CSV] [--raw-cache SQLITE] [--hydrate-only] [--retry-terminal-metadata] [--refresh-cache] [--include-text-only] [--verbose]
```

`fibrosis_meta_publications.tsv` combines four ordered reference sets: the
Küchenhoff 2026 source meta-study plus references 15-34 under
`leonie_2026_fibrosis`; the Taylor 2020 systematic review plus references
18-31 under `taylor_2020_nafld_fibrosis`; and the He 2025 interstitial-lung-
disease systematic review plus its 35 lung-transcriptomics studies, references
11-18 and 32-58, under `he_2025_ild_fibrosis`; plus the Jaimes Campos 2025
pan-fibrotic source and 19 associated heart, kidney, and liver dataset
publications under `jaimes_campos_2025_fibrosis`. The He set deliberately
excludes the review's eight peripheral-transcriptomics studies at references
24-31. The TSV has exactly five columns: `reference_set_id`,
`source_reference_number`, `doi`, `pmid`, and `title`. Each source-publication
row has a blank reference number. The Jaimes Campos dataset publications also
leave that field blank because they originate from source-study dataset tables,
not numbered bibliography entries. The file is quote-free; tabs delimit fields,
so commas in titles remain unmodified.

Both recall runners default `--references` to that one packaged TSV and accept
a custom quote-free TSV with the same exact columns and order. Each row requires
a title and a valid DOI, PMID, or both. The reviewed-output runner's `TRACE_DIR`
must contain a supported review artifact. Selection prefers the pre-filter
`resume_review_progress.json`, then `02_reviewed_datasets.json`, then
`06_final_atlas.json`; post-filter reports retain the discovery limitation.

DOI and PMID matching is normalized, offline, and exact. Duplicate reference
rows and repeated publications across accessions collapse through connected
identities. Zero candidates produce `missed`, one produces `matched`, and
multiple candidates produce `conflict` without arbitrary selection. Review
outcomes come from `publication_texts[*].agentic_curator` and normalize to
relevant, unsure, not relevant, other, failed, or unreviewed states.

Schema `1.0` contains TSV and trace provenance, a globally deduplicated
`aggregate` summary/details block, and ordered `reference_sets` blocks. Each
per-set block contains only its ID, summary, and publication details; the TSV
and report deliberately omit descriptive source metadata. Metrics include
duplicate, matched, missed, and conflict counts; discovery, relevant, and
relevant-or-unsure candidate recall; review completion/failure counts; and
judgement counts.

`--out` is a directory and defaults to Git-ignored `benchmarks/`. The runner
creates it, atomically replaces `fibrosis_meta_pubs_recall_report.json`, prints
the report path, and exits zero. Argument errors exit two. TSV, trace, JSON, or
filesystem failures emit a concise stderr message, exit one, and leave no
partial report. The runner makes no network, identifier-resolution, or model
calls and has no installed console entry point or supported `python -m` form.

The query-recall runner reads only `atlas_run.sqlite3` and requires non-empty
`resolved_queries` metadata plus the `search_queries` and `search_pages`
checkpoint contract. It opens a query-only SQLite transaction rather than the
initializing `CheckpointStore`, groups raw page publications by exact normalized
DOI/PMID identity, and scores their union, each reference set, and each resolved
query. Matched reference details retain ordered query provenance; the report
does not duplicate the complete raw search corpus.

Query statuses `available` and `no_data` are complete. Missing, pending,
retryable-error, and terminal-error query checkpoints retain any available page
hits but mark schema `1.0` source provenance `complete: false` and
`score_interpretation: lower_bound`, with an explicit limitation. Invalid
SQLite structure, malformed payloads, inconsistent completed counts, or invalid
reference input fail without replacing a report. Success atomically replaces
`fibrosis_meta_pubs_query_recall_report.json`; the runner makes no network,
identifier-resolution, accession, review, or model call.

The review benchmark's adjacent CSV has exact columns `publication_id`, `doi`,
`pmid`, and `expected_decision`. Its 90 rows are the first-seen connected
DOI/PMID identities projected from all 92 rows in the recall/query-recall TSV;
the two publications repeated across reference sets collapse once while their
PMIDs remain attached. `publication_id` is `doi:<normalized-doi>` for this
fixture and every `expected_decision` is `relevant`. This is intentionally a
positive-control test of reviewer recall, not a balanced three-class test.

Recall and query-recall therefore share one TSV directly, while reviewer
classification uses a separate CSV because it needs stable publication IDs and
expected class labels. A custom CSV may contain `relevant`, `not_relevant`, and
`unsure`, but every row still requires a unique ID and a DOI/PMID. The adjacent
theme is byte-identical to `docs/theme_fibrosis.txt`. An empty custom dataset
fails before cache/report writes.

The runner queries Europe PMC exactly by PMID (`EXT_ID` plus `SRC:MED`) or DOI,
requires one matching record, discovers supported accessions from Datalinks,
publication text, and exact official PubMed→GDS links, collects fully enriched
GEO and ArrayExpress context, and invokes
`PublicationTextReviewer.review_publication_texts` with an explicitly public
`ThematicReviewer` only for complete contexts. Complete means non-empty text from
full-text XML, preprint XML, or `abstractText`, at least one supported accession,
non-empty metadata for every accession, every metadata status exactly
`available`, and no hydration error. The runner retries the entire public
hydration once after any exception or incomplete result, then marks a still
incomplete row `metadata_incomplete` and excludes it from reviewer inputs. Its benchmark-owned collector uses the ordinary
`GEOWrapper` default `enrich_metadata=True`, so PubMed/SRA/ENA identifier
enrichment is part of the context shown to the reviewer. A benchmark-owned
`CheckpointStore` retains search pages, publication text, Datalinks, full-text
accession discovery, PubMed→GDS link results keyed by PMID, GDS summaries keyed
by UID, checksum-verified gzip-compressed GEO MINiML XML or
ArrayExpress IDF/SDRF resources, parser-produced pre-canonical mappings,
structured strict-validation diagnostics, canonical packages, PubMed/SRA/ENA
enrichment, sanitized failures, statuses, and attempt history. Source evidence
is captured immediately after download and reused after deterministic parse or
canonicalization failures. Source-compatible duplicate sample titles retain
their exact values and unique iids, while accepted `xsd_uniqueness` warnings
and the `miniml-3.0-source-compat-v1` policy identity remain in diagnostic and
runtime provenance. Exact graph-linked GSEs need no textual corroboration, but
remain reviewer-ineligible unless canonical metadata is non-empty and
`available`. Successful and
authoritative-negative stages are reused. After two hydration attempts,
transient provider errors become explicit terminal outcomes; a successfully
downloaded GEO base package is retained with `partial` derived status when only
supplementary enrichment exhausted. `--refresh-cache` requeues those exhausted
stages explicitly.

`--retry-terminal-metadata` is valid only with `--hydrate-only`. It snapshots
terminal GEO and ArrayExpress metadata checkpoints, makes two construction
attempts per unique accession through the unchanged production parsers, and
does not retry publication lookup/text, Datalinks, PubMed→GDS, PubMed, SRA,
ENA, or any review stage. Exhausted construction is terminalized before all 90 publication
rows are reprojected through checkpoint-only hydration under the new policy.
The run operates in a resumable staging copy and publishes the SQLite, derived
CSV, and audit together only after that terminal reprojection.

`--hydrate-only` never constructs the production reviewer or its credentials,
never makes a model call, and never replaces the reviewer report. It resumes a
hidden SQLite staging file, then publishes the raw database, existing-contract
compact CSV, and `fibrosis_meta_pubs_review_cache_audit.json` only after every
publication has a terminal hydration record and no pending stage remains. The
audit contains identifiers, download/parse/canonicalization statuses, attempt
counts, accepted/blocking diagnostic codes/paths/severities, compatibility
policy identity, coverage, graph query/UID/GSE/merge/rejection/failure counts,
and sanitized failure
categories, but excludes publication text, XML/MAGE-TAB resources,
pre-canonical/canonical package contents, and diagnostic messages.
The SQLite cache retains raw evidence and packages; the CSV retains publication text and only
the existing compact reviewer context. `--verbose`
emits an INFO event before and after each publication hydration/cache action and
for each outer hydration attempt, then reports review-stage
start/completion/failure. It never reads a trace. Complete/incomplete hydration is
frozen in a standard quoted CSV under the benchmark-specific Git-ignored output
directory. The identity hash binds the hydration/discovery-policy version, so
the pre-graph policy refreshes each row once while retaining successful text
and metadata checkpoints. Thereafter every terminal raw outcome is
reused; `--refresh-cache` forces compact reprojection and requeues exhausted raw
provider stages while retaining successful downloads. Source-label changes do
not refetch text.

`--include-text-only` is benchmark-only. It additionally admits a row when the
publication text and title are non-empty and the compact context has exactly
zero accessions, zero metadata entries, and zero metadata statuses. A row with
a discovered accession whose metadata is partial, unavailable, or erroneous
remains ineligible. Production Atlas collection/filtering is unchanged.

Review report schema `1.1` records dataset/theme/cache hashes and counts,
hydration/review coverage, expected/predicted counts, a three-by-three confusion
matrix, accuracy, per-class precision/recall/F1, macro F1, and ordered row
details without raw publication text. Retrieval/review failures remain visible;
they are excluded from scored accuracy and predicted counts but remain in the
expected-support denominator used by relevant recall. `review_eligible_count` and
`metadata_incomplete_count` distinguish complete reviewer inputs from rows
skipped after the retry. Each row records `full_context`, `text_only`, or
`ineligible`; the summary records eligible counts and complete classification
metrics separately for the full-context and text-only strata. Global input/cache failures
exit one without a partial report; row failures still produce an atomic report.
Because absent classes retain zero F1, perfect predictions on the packaged
all-relevant fixture yield relevant recall and accuracy of `1.0` but three-class
macro F1 of `1/3`; custom mixed-label datasets exercise balanced classification.

<a id="fibrosis-curation-theme"></a>
### Fibrosis Curation Theme

`docs/theme_fibrosis.txt` is a retained inclusion-policy reference. It targets human bulk, single-cell, single-nucleus, and spatial transcriptomic datasets containing at least one profiled sample with established or explicitly documented fibrosis. A qualifying dataset retains its non-fibrotic controls and comparator samples. The parent adapter owns the canonical production workflow and its effective configuration.

Confirmed sample-level fibrosis supports `relevant`. Induced fibrosis without confirmation, profibrotic stimulation, fibroblast activation, extracellular-matrix remodelling, wound healing, or a fibrosis-associated disease without sample-level confirmation supports `unsure`, not direct inclusion. Animal-only, non-transcriptomic, background-only, and otherwise unlinked studies are `not relevant`.

Use `--review-filter not-relevant` with this theme so unsure candidates remain available for manual review. The same theme may be passed to `--query-generator`; its domain-neutral prompt defaults to one comprehensive query with independent mandatory concepts joined by AND and extensive within-concept synonyms joined by OR. Additional queries require an explained unbridgeable logical, semantic, syntax, or length gap. The thematic reviewer then applies the sample- and assay-level inclusion policy.

<a id="fibrosis-run-script"></a>
### Archived Fibrosis Run Scripts

Archived non-canonical fibrosis runners were removed from the repository root
on 2026-08-03. Their ignored local recovery location is
`.dev/archive/fibrosis-workflows-2026-08-03/`; it is intentionally excluded from
Git and package distributions. The canonical production workflow is
`gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py` in the parent
adapter repository.

The archive contains the former full-atlas, discovery, publication-review,
metadata-repair, recall, and reference-review runner implementations together
with their runner-specific tests. It is historical recovery material, not a
supported interface. The supported surfaces in this repository are the
installed `thematic-atlas` CLI and the importable Python APIs.

Reusable assets were deliberately not archived:

- `docs/theme_fibrosis.txt` remains a tracked policy reference.
- `config/fibrosis_discovery_queries.json` remains a tracked, versioned query
  catalog; its four historical per-query caps permit 40,000 raw hits before cross-query deduplication.
- The direct fibrosis meta-publication recall runner remains tracked with one
  packaged TSV containing the Leonie and Taylor reference sets.
- `PublicationTextReviewer.resume`, `AtlasCollector.resume_metadata`, and
  the installed `thematic-atlas` CLI remain available to callers.

<a id="atlas-workflow"></a>
### Atlas Workflow

`class Atlas` is the workflow orchestrator currently used by the CLI. It keeps the public workflow surface in one root object while delegating implementation details to component packages: `ThematicAtlases.collector.AtlasCollector`, `ThematicAtlases.filterer.AtlasFilterer`, and `ThematicAtlases.harmonizer.AtlasHarmonizer`.

Public methods:

- `__init__(metadata: dict, ..., harmonizer=None, ontostore=None, cache_ontologies=False, query_generator=None, credential_checker=None, document_adapter=None, artifact_publisher=None, capability_registry=None, resource_profile="standard", resource_overrides=None, runtime_provenance=None)`: wires component instances, the shared immutable repository-capability registry, one resolved typed resource profile, optional JSON-compatible composing-application provenance, one optional shared ontology store, eager-cache policy, query-generation/credential-preflight dependencies, the v1 boundary adapter, and the rollback-safe publisher. Traced creation stores the resolved profile and provenance in the manifest/ledger; Atlas v1 run options retain the same values without changing the wire schema.
- `create_atlas(..., theme, review_strategy="direct", prune_accessions=False, dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=True, max_generated_queries=3, harmonization_options=None, review_before_metadata=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, thematic_review=True)`: requires a nonblank theme, defaults query generation and thematic review on while keeping accession pruning off, runs collection/filtering and harmonization, returns Atlas v1, publishes the v1 document and derived summary as one bundle beside `out`, optionally publishes a separate unsupported inventory, and can write an opt-in trace bundle.
- `_dev_run_id()` is internal run allocation policy. It returns
  `YYYYMMDDTHHMMSSffffffZ-xxxxxxxx`, combining UTC microseconds and 32 random
  bits so trace directories are sortable and collision-resistant.
- `resume(dev_out_dir=".dev", run_id=None, out=None, stop_before_review=False, retry_stages=None, retry_items=None, retry_degraded_stages=None, review_decisions=None)`: resumes an explicit trace or the newest incomplete valid trace from its latest atomic checkpoint. It reuses collected accessions, per-publication review progress, reviewed datasets, per-dataset harmonizations, or the final atlas without repeating completed work; transient checkpoint errors are retried. Incremental review progress contributes cached publication texts and review checkpoints but is merged with the complete `01_collected_accessions.json`, so an early subset never replaces the finished collection. `stop_before_review=True` overrides an older combined-workflow manifest and returns after accession and publication-text collection without reading or modifying thematic-review rows. Review decisions must name the same run and a current source fingerprint; only that source's work key is invalidated.
- `amend_queries(dev_out_dir, run_id, queries, max_publications_per_query)`: explicitly replaces an existing trace's query configuration while atomically archiving its prior fingerprint and writing a readable query archive. Existing item checkpoints remain live, and repeating the same amendment is idempotent.
- `archive_existing_runs(dev_out_dir, archive_root, workflow, artifact_paths=())`: archives every inactive trace under one workflow root, attaches fixed artifacts to the newest trace, verifies the copy, and returns the ordered archive paths. It is a no-op when neither traces nor artifacts exist, refuses unsafe workflow names, symlinks, active workflows, and destination collisions, and never overwrites an archive.
- `collect_datasets(..., max_publications=None, max_publications_per_query=None, review_strategy="direct", prune_accessions=False, generate_queries=False, max_generated_queries=3, dev_trace=False, dev_out_dir=".dev", run_id=None, review_before_metadata=False, stop_before_review=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None)`: owns explicit/file/generated query ordering and validation before collection, metadata enrichment, text mapping, and optional thematic review, then returns Atlas v1 with run status `running`. Publication-text, curated-link, and exact official PubMed→GDS→GSE discovery are on by default; accession pruning requires explicit opt-in. The PubMed-GDS discovery-contract version is part of trace manifests and fingerprints, so a pre-graph trace must fork rather than silently changing dataset membership. Unsupported capabilities are partitioned before review and can be written to the explicit sidecar. With review-before-metadata enabled, supported GEO and ArrayExpress accessions use registry-defined review identity, are filtered without metadata, and only survivors are enriched. `stop_before_review=True` defers review and metadata. A traced public collection writes `collection_snapshot.json`, never a final-atlas role.
- `harmonize_datasets(datasets, harmonization_details_out=None, harmonization_options=None, review_decisions=None)`: requires an Atlas v1 mapping, delegates its projected metadata to `AtlasHarmonizer`, returns validated Atlas v1, and optionally writes a details sidecar. A review-decision contract selectively changes the matching source work key. Legacy unversioned mappings fail closed.

`Atlas` no longer exposes `collect_jsons()`, `filter_jsons()`, or `harmonize_jsons()` as public methods. Helper-level behavior belongs to the component classes below.

Whole-run archives differ from checkpoint comparison archives.
`archive_existing_runs()` relocates complete resumable trace directories;
`CheckpointStore.archive_stage()` and `archive_items()` move selected checkpoint
rows to comparison databases while leaving the parent run active.

When `create_atlas(out="atlas.json")` succeeds, it also writes
`atlas.summary.json` with schema/run/atlas identity, dataset/publication/
completed/failed counts, and aggregate unsupported accession/repository counts.
An explicit `unsupported_accessions_out` adds the detailed external inventory
to the same rollback-safe publication bundle.
With `dev_trace=True`, `create_atlas()` or `collect_datasets()` writes a run
directory under `dev_out_dir` containing one authoritative
`atlas_run.sqlite3`, a manifest, and readable stage artifacts. The mature
`CheckpointStore` item/retry API is bound to that same database and projected
transactionally into normalized work/attempt/metadata rows. Full atlas traces
register final/details/summary/unsupported roles; collection traces register a
separate snapshot role plus unsupported inventory. SQLite uses WAL mode, full synchronous
commits, a configuration fingerprint, and one row per stage/item. Statuses
distinguish reusable success/no-data outcomes, non-retryable consumed-call
failures, and transient failures that should be attempted again.
`archive_stage(...)` transactionally moves a complete stage into comparison
tables in a separate SQLite database; `archive_items(stage, item_keys, ...)`
does the same for an explicit subset. Both preserve unrelated rows/stages,
reject missing selections or archive-ID reuse, and delete live rows only after
archive counts match.

Checkpoint schema version 2 migrates existing databases in place and records
attempt counts, failure timestamps, error type/category, and immutable history
before replacement. A central stage registry drives resume boundaries.
`Atlas.resume(...)` accepts selective terminal item/stage retries and degraded
harmonization-stage retries; the generic CLI and fibrosis scripts expose the
same controls.

Review-before-metadata traces use `01_collected_accessions.json` for supported
repository-filtered accessions, `unsupported_accessions.json` for detected
repositories without a supported handler, `02_reviewed_datasets.json` for pre-metadata
survivors, and `resume_metadata_enriched_datasets.json` for the enriched result.
Resume treats datalink, publication-text/review, and GEO metadata progress as
separate boundaries, so a GEO retry does not repeat successful reviews.
Retryable `pubmed_enrichment`, `sra_xml`, and `ena_fastq` rows are also treated
as incomplete metadata work, preventing a stale final or metadata-enriched
checkpoint from masking identifier-level repairs.
Collection-only traces additionally use `resume_publication_collection.json`
and its summary for the unreviewed accession/publication-text snapshot. Static
collection-only runs do not require Google credentials; generated-query runs do.

Eager ontology caching is opt-in. `Atlas(..., ontostore=store, cache_ontologies=True)` validates model credentials and then invokes `store.cache_all()` once at the beginning of the first `create_atlas()` call, before query generation or collection. The upstream cache API directly streams OWL into SQLite, imports an existing legacy JSON cache when available, and supports selective refresh through `store.cache_all(force_frameworks=[...])`; `force=True` still refreshes all active frameworks. It also builds semantic indexes for every selected lexical framework by default. `semantic_frameworks=[]` disables eager semantic construction, while a named subset limits it and is validated against the lexical selection. Lexical and semantic results are reported per framework, and a required semantic failure participates in the aggregate cache error. Framework replacement is transactional and temporary staging databases are deleted after success or failure. The result is retained as `atlas.ontology_cache_result`; aggregate cache exceptions propagate and prevent collection. The same store is passed to the default `AtlasHarmonizer` and its lazily created `OntologyHarmonizer`. Supplying a custom harmonizer together with Atlas-managed store/cache options raises `ValueError`.

<a id="collector"></a>
### Collector

`ThematicAtlases.collector.AtlasCollector` owns accession discovery and metadata collection.

`AtlasCollector.resume_metadata(trace_dir, *, audit_enrichment_only=False,
retry_tags=None)` delegates to `TraceMetadataResumer`
and processes one stable snapshot of the currently available datalink checkpoint
rows. It applies the trace manifest's repository selection, downloads metadata,
atomically writes the atlas-shaped `resume_metadata_progress.json`, and exits.
Python callers can invoke the same operation repeatedly to discover later
datalinks, rebuild the
deduplicated GSE list, and reuse completed `geo_resolution` and `geo_metadata`
items without repeating their network calls or requiring LLM credentials.
`audit_enrichment_only=True` reads legacy GSE packages without network calls,
writes `resume_enrichment_candidates.json`, and creates an empty
`resume_enrichment_retry_tags.json` template when needed. `retry_tags=PATH`
accepts explicit `pubmed`, `sra`, and `ena` identifier lists plus a unique
`tag_id`; completed tags are idempotent and a new tag forces another lookup.

Current responsibilities:

- Build query lists from repeated API/CLI query values and optional UTF-8 query files.
- Ignore blank query-file lines and lines beginning with `#`.
- Call `EuropePMCWrapper.collect_accessions(queries=..., max_publications=..., max_publications_per_query=...)`, which merges Datalinks, optional publication-text matches, and exact official PubMed→GDS→GSE links before repository filtering.
- Keep records handled by selected supported metadata repositories and retain
  scanner-identified unsupported repositories as terminal records.
  `metadata_repositories=None` selects GEO and ArrayExpress.
- Route only handlers declaring `metadata_handler_status="supported"` to
  metadata collection. The default registry supports GEO and ArrayExpress.
- Optionally write the intermediate collected accession list to `out`.
- Validate repository selections against `geo` and `arrayexpress`.

Query loading behavior:

- Repeated CLI `--query` values are preserved in order.
- `file` values are read as UTF-8 text.
- Query files ignore blank lines and lines starting with `#`.
- If neither `query` nor `file` is provided, the wrapper receives an empty query list.
- `max_publications` optionally caps searched Europe PMC publications globally across all queries before datalink fetching begins.

Repository filtering behavior:

- `filter_accessions(accessions, metadata_repositories=None)` keeps accessions handled by selected supported repositories and annotates scanner-identified unsupported records with terminal metadata status.
- `is_handled_accession(record, metadata_repositories=None)` returns true when `metadata_repository(...)` finds a selected repository.
- `collect_accession_metadata(jsons, metadata_repositories=None)` is the metadata repository routing step used after filtering.
- `collect_jsons(..., collect_metadata=False)` still loads queries, collects Europe PMC accessions, and filters to selected repositories, but skips metadata handler enrichment.
- `metadata_repository(record, metadata_repositories=None)` returns only a selected repository with a supported handler; `unsupported_metadata_repository(record)` identifies terminal scanner records.
- `metadata_handler(repository)` uses the instance metadata handler registry.
- GEO rules: `datalink_id_scheme` equals `GEO`, case-insensitive, or `datalink_id` starts with `GSE`, `GSM`, `GPL`, or `GDS`, case-insensitive.
- ArrayExpress rules: `datalink_id_scheme` equals `ArrayExpress`, case-insensitive, or `datalink_id` starts with `E-MTAB`, `E-GEOD`, or `E-MEXP`, case-insensitive.
- GSE normalization happens inside `GEOWrapper.collect_accession_metadata()`: GSE records remain GSE, GSM/GDS records resolve to their parent GSE, and GPL or unresolved records are removed.
- Metadata repository handlers append repository metadata under each returned accession/project record. GEO stores parsed MINiML JSON in `accession_metadata`.
- Multiple filtered records resolving to the same GSE collapse into one result. The merged result keeps first-seen GSE-level top-level values, deduplicates publications, records original datalink evidence in `original_datalinks`, and keeps the first available metadata package.
- Linked E-GEOD/GSE identities collapse after repository parsing. Discovery
  order selects the canonical record and later aliases contribute only unique
  publications and original-datalink provenance.
- GEO resolution and metadata downloads use per-item cross-process locks. New
  metadata checkpoints store provenance-independent, canonical MINiML 3.1
  packages with explicit transport and checkpoint versions; reuse rebuilds
  records from the latest accession snapshot so later publication links are not
  lost. Legacy record-shaped or unversioned package payloads are invalidated
  and recomputed, or shown as pending during offline availability checks.
- ArrayExpress metadata collection is enabled by default. Its MSC adapter
  applies the same strict MINiML 3.0/3.1 reader and 3.1 writer boundary before a package can enter a
  record, trace, or checkpoint.

<a id="filterer"></a>
### Filterer

`ThematicAtlases.filterer.AtlasFilterer` owns the publication text mapping and optional thematic review stage.

Current responsibilities:

- Accept collected accession records or an atlas-shaped object with `accessions` and optional `publication_texts`.
- Optionally append records from a JSON file.
- Reuse existing publication text entries and collect only missing texts.
- Add `publication_text_ref` to nested publication metadata when text is available.
- Strip `text`, `text_source`, `full_text_status`, and `full_text_links` from nested publication metadata so full text and raw link targets are not duplicated outside the shared text workflow.
- Optionally review each unique publication text against `theme`, then optionally filter by reviewer judgement.
- Return the top-level atlas object with `accessions` and `publication_texts`.

`collect_publication_texts(jsons, publication_texts=None)` extracts unique surviving nested publications that do not already have entries in the shared text map, calls `EuropePMCWrapper.collect_publication_texts(publications=...)` for missing text only, and returns a shared `publication_texts` map keyed by existing `publication_text_ref`, PMID, PMCID, DOI, or `source:epmc_id`.

Long Europe PMC datalink and publication-text loops log INFO progress for item
1, every tenth item, and the final item. DEBUG records source/accession,
category count, and request duration; completion summaries report collected,
skipped, failed, full-text, fallback, and missing counts.

`accessions_with_publication_text_refs(jsons, publication_texts)` adds `publication_text_ref` to nested publication metadata when text is available. Full text is not duplicated inside accession records.

`filter_jsons()` remains the internal filterer pipeline: parse/merge input, collect missing publication texts, attach publication text refs, optionally review/filter publications, then return the atlas object. Public callers use `Atlas.collect_datasets()`.

- `ThematicAtlases.filterer.review.PublicationTextReviewer` owns thematic review option validation, review reuse, `agentic_curator` JSON parsing, judgement normalization, and review-based accession/publication filtering.
- `PublicationTextReviewer.resume(trace_dir, theme=None, reviewer=None, strategy="direct", allow_theme_override=False, require_resolved_metadata=False, collect_metadata=False, defer_metadata_errors=False, require_main_datalinks_phase=False, publication_limit=None, review_action_limit=None, cancelled=None, snapshot_accessions=None, publication_keys=None, item_lock_timeout_seconds=None, metadata_item_timeout_seconds=None, publication_text_item_timeout_seconds=None, review_item_timeout_seconds=None)` delegates to the injectable `TracePublicationReviewResumer`. The public façade forwards an optional merged accession snapshot and terminal-frontier publication-key subset unchanged; omitting them preserves full-snapshot reconstruction from completed `datalinks`. `publication_limit` keeps the historical snapshot-prefix meaning; `review_action_limit` instead counts only real review actions after prerequisite deferral, compatible reuse, and future cooldown exclusion. It atomically writes `incremental_review_progress.json`, never the main workflow's progress artifact. Datalinks arriving after capture wait for the next call.
- `collect_metadata=True` reuses terminal metadata and attempts missing or due-retry GEO/ArrayExpress work. Compatible byte-identical metadata reuse is read-only. Provider exceptions remain checkpointed and are logged by safe type only; collection continues with unrelated accessions. Checkpoint item locks serialize the same accession across processes, while all requests additionally share cross-process host pacing. The result's `metadata_summary` includes provider attempts, retry count, accumulated rate wait, cooldown deferrals, and the existing fixed/selected/reused/status counts.
- With `require_resolved_metadata=True`, the default gate treats `available`, `partial`, `unavailable`, and `error` as resolved. `defer_metadata_errors=True` instead admits only `available`, `partial`, and authoritative `unavailable`; pending, retryable-error, terminal-error, missing, and unknown values defer the complete publication and all its accession edges before publication-text or model calls. Later calls automatically retry transient checkpoints. Terminal errors remain deferred until `CheckpointStore.request_retries` explicitly requeues the stage or item.
- The trace resumer uses the manifest theme and repository selection by default. An explicit non-empty theme is allowed when the manifest has none; a conflicting theme is rejected unless `allow_theme_override=True`. The reviewer-only override uses the explicit theme without modifying the historical collector manifest or fingerprint. Only `available` datalink items present when the call begins belong to that invocation, so the method does not poll or wait for collection completion.
- With `require_main_datalinks_phase=True`, missing or non-Datalinks phase metadata yields without starting work. `EuropePMCWrapper.collect_accessions` advertises `datalinks` before collection and atomically changes it to `downstream` after Datalinks returns. The sidecar checks this value before every metadata, text, and model item, finishes only its current item, then yields. It never changes the main run status, stage state, phase, manifest, fingerprint, or collected-accession artifact.
- When `theme` is provided, `PublicationTextReviewer.review_publication_texts(...)` reviews each `publication_texts` entry with `agentic_curator.ThematicReviewer.review_relevancy(...)`. The reviewer receives `publication_texts[ref]["text"]`, not `accessions[].publications[].abstractText` directly, plus the title and every distinct associated GSE accession. When metadata exists, context contains one compact `build_miniml_metadata_context(...)` entry per associated accession; full MINiML, protocol, platform, and author sections are not sent. Original `accession_metadata` remains unchanged in atlas and trace artifacts.
- Collected accession JSONs keep Europe PMC abstracts at `accessions[].publications[].abstractText`. During filtering, publication text enrichment promotes either full text or abstract fallback into `publication_texts[ref]["text"]`.
- Publication text source values distinguish the fallback path: fullTextXML success stores `text_source="fullTextXML"`; full text unavailable or failed with a non-empty abstract stores `text_source="abstractText"`; full text and abstract both missing or empty stores `text=""` and `text_source="none"`.
- `review_strategy="direct"` is the sole supported strategy. Agentic Curator revision 4 with evidence contract 2 first derives one shared catalogue of 1–`max_review_criteria` generic criteria (default maximum 12) from the non-empty theme, then each publication call receives that fixed catalogue and returns evidence/decisions without regenerating it. The catalogue is cached under a theme/strategy/reviewer-identity key and reused across resume invocations. Every publication still requires exactly one complete assessment per supplied accession; a destructive exclusion is accepted only when a failed criterion cites a caller-verified exact quote by source kind and source ID tied to that accession. The model neither receives nor returns source digests, offsets, JSON pointers, or evidence contract fields. The retired evidence-then-judgement value fails before a model call.
- Direct output is stored under `publication_texts[ref]["agentic_curator"]` with `theme`, `strategy`, `review_revision`, `evidence_contract_version`, `criteria`, `judgement`, `reasoning`, `confidence`, `accession_assessments`, derived `accessions_to_remove`, `raw_review`, `review_input_hash`, `review_contract_version`, and `reviewer_identity`. The reviewer identity binds provider, model, generation configuration, and prompt SHA-256. The model owns `qualifies`/`exclude`/`uncertain` and publication relevance decisions; agentic-curator derives removals only from grounded exclusions. With explicit `prune_accessions=True`, each removal drops that publication–accession association; the accession remains when another publication retains it and is dropped only when no associations remain. The default is `False`. `review_filter` independently applies publication-level judgements. The canonical Atlas v1 projection remains unchanged and exposes its existing publication-level `thematic_relevance` criterion rather than the per-accession catalog.
- The complete available publication remains the primary context. When accession metadata was collected first, each GSE additionally receives its own compact, at-most-500-character MINiML context. Full MINiML, author, protocol, and platform content is not sent, and absent metadata is represented by no compact context rather than inferred accession knowledge.
- Existing `agentic_curator` reviews are reused only when their effective input matches. Review identity includes contract version, strategy, theme, the fixed criteria catalogue, publication text, title, associated accessions, compact metadata context, metadata coverage, reviewer class/provider/model, generation configuration, and prompt digest. Contract version 9 rejects pre-stable-catalogue or unfingerprinted review checkpoints; a change to any review or execution input triggers a new review.
- Incremental reviewer snapshots overlay completed metadata checkpoints without
  waiting for missing metadata. Reviews store `metadata_context` with used and
  non-used accessions plus per-accession status. Contract version 5 includes the
  compact metadata context and its coverage in the effective input hash, so
  metadata arriving after an early review triggers a replacement review on the
  next reviewer or full-resume invocation. The raw MINiML object is not sent.
- Each thematic review is checkpointed atomically under `thematic_review/direct:<publication_ref>`. Per-item locks prevent duplicate calls. The main workflow recomputes the same input identity and reuses a completed sidecar checkpoint even when `incremental_review_progress.json` is absent. Invalid structured output gets one immediate correction attempt and then becomes terminal; transient provider/network/429 failures use bounded jittered retries, share a provider/project/location/model concurrency/cooldown gate, and persist retryable `next_retry_at` state. Cooperative cancellation waits for an in-flight model request and stops before the next item.
- `PublicationTextReviewer.resume` reviews one stable datalink snapshot and can
  be invoked again as collection advances. A caller must explicitly allow a
  theme override when reviewing a historical collector snapshot with a newer
  theme. Full Atlas resume treats completed canonical item checkpoints as a
  reusable cache over the eventual full collected-accession set; the isolated
  incremental progress artifact is never authoritative collection scope.
- `review_filter` accepts `none`, `not_relevant`, and `not_relevant_and_unsure`. Filtering uses the judge-level `agentic_curator.judgement`, treating underscores and case differences as equivalent. `not_relevant` removes judgement `not relevant`; `not_relevant_and_unsure` removes `not relevant` and `unsure`.
- `prune_accessions` defaults to false and consumes normalized exact accession identifiers from grounded `accessions_to_remove` only when explicitly enabled, independently of `review_filter`. Missing, malformed, unknown, or failed-review removals fail open. New traces persist and fingerprint the option; legacy traces without it resume with pruning disabled.
- When thematic review is active, accessions with no retained publications are dropped and `publication_texts` is pruned to refs used by returned accessions. When no theme is supplied, existing unreferenced `publication_texts` are preserved for backward compatibility.
- `review_filter != "none"` without a `theme` raises `ValueError`.
- Raw unselected datalinks are not preserved by the collection stage.

<a id="harmonizer"></a>
### Harmonizer

`ThematicAtlases.harmonizer.AtlasHarmonizer` accepts an optional shared
`ontostore`, iterates atlas accessions, builds ordered publication context from
non-empty publication titles and abstracts, canonicalizes dictionary or list
`accession_metadata` with MSC 8, requests an Agentic-built MSC patch 3.2,
applies it copy-on-write, and revalidates the resulting typed packages. MSC
partitions document operations and attaches immutable package-local fragments
under `extensions.msc_harmonization`; the extension survives Atlas documents,
item checkpoints, resume, trace artifacts, and publication. The separate
bounded target/resolution details remain in the harmonization sidecar and
checkpoint. Retained patches are evidence, not implicit override instructions.
Its lazily
created default harmonizer receives that same store.

An injected `OntoStore` may configure ordered runtime-only
`preferred_ontology_ids`. These preferences do not restrict local, semantic, or
OLS retrieval. Instead, the local/RAG shared judge and the OLS judge receive
the ordered IDs plus up to two reserved candidates per preferred ontology
within their existing pool sizes. The preference is advisory and is not passed
to target checking or field assignment. OLS still makes exactly one
unrestricted request, regardless of a target's existing ontology ID.

The dataset-level target checker receives the complete deduplicated target and
field catalogues. Its semantic `splits` are additive: a compound source target
continues independently while every accepted two- or three-part split target
is copied to all source occurrences. `prunes` are mutually exclusive with a
split and require high confidence. Identifier-like, numeric, and values longer
than 200 characters are exposed as prune-only targets (or a bounded synthetic
summary at 20 distinct values); unresolved prune-only inputs remain excluded,
are checkpointed as pending review, and make publication review-required.

A usable call replaces `accession_metadata` with the returned `miniml_json`,
sets the compatibility `ontology_harmonization_run_status="completed"`, and
copies the validated status 2.0 envelope to
`ontology_harmonization_status`. That envelope independently states execution
(`succeeded` or `degraded`), completeness, evidence confidence, validation,
and publication disposition; completion alone does not claim that every
target matched or that publication is safe. Null, unsupported, or
repository-mismatched metadata is retained with an explicit status-v2
`not_run`. Exceptions are isolated per accession: original metadata is
retained with compatibility run status `error`, status-v2 execution `failed`,
and a safe `ontology_harmonization_error` envelope, then later accessions
continue.

The former `ontology_harmonization_quality_status` scalar is removed. The
summary aggregates the compatibility values plus all five authoritative
status axes under `harmonization_execution_statuses`,
`harmonization_completeness_statuses`,
`harmonization_evidence_confidence_statuses`,
`harmonization_validation_statuses`, and
`harmonization_publication_dispositions`. A degraded or failed item makes the
final run partial. Target-checker and field-assignment invalid-output fallbacks
may still be usable degraded outcomes; provider failures remain classified for
selective retry.

The upstream ontology path is fixed and hierarchy enrichment defaults on:

1. local exact lookup, then FTS5;
2. semantic lookup across locally cached ontology frameworks;
3. unrestricted OLS when semantic lookup misses;
4. selected-term title promotion to `hz_label`;
5. field registry lookup or semantic LLM field assignment using the harmonized
   label, with accepted novel fields registered as run-local extensions;
6. traverse and emit all distinct parents through depth two for every matched
   ontology, retaining ordered source/depth provenance.

Semantic lookup embeds one ontology term per chunk with Gemini and retrieves
cosine-nearest neighbours from persistent USearch partitions. It never downloads
a missing local framework. OLS is the only external ontology search; no grounded
web search or prior LLM framework-selection call occurs.

Every available local, semantic, or OLS candidate set is judged when its
stage-specific judge is enabled. Candidate labels are the model's primary
decision surface because natural-language tokens are more distinguishable
than compact identifiers. Host resolution matches normalized label first,
requires ontology only for cross-ontology collisions, and requires accession,
ID, or IRI only when duplicates remain inside an ontology. Unneeded supplied
disambiguators are ignored. No `C###`, `T###`, or `F###` choice-token contract
crosses this boundary. With `direct_lookup_judge=False`, only one
unique exact identity is accepted; ambiguous exact and FTS candidates remain
unjudged evidence. `rag_lookup` and `ols_lookup` independently control
retrieval, while their judge switches independently control selection. An
unjudged RAG or OLS candidate list is trace-only and the first result is never
automatically applied. `no_match` rejects that stage's candidates and continues
to the next stage. `false` terminally skips a non-harmonizable target, records
`harmonization_status="skipped"` plus `harmonization_skip`, and bypasses later
search, label, field, and MINiML application. The OLS judge receives a neutral
candidate section and no restricted/unrestricted stage literal.

Field harmonization runs after label resolution. A selected canonical term
title replaces `hz_label` and is supplied to field lookup/assignment together
with the original `pre_hz_label`. Assignment may select an existing semantic
field or propose `new_extension`; normalized extension keys and their label,
stage, reason, confidence, occurrences, and review state remain run-local.
Low-confidence/exhausted assignment retains the normalized source field as an
unreviewed extension. Applied patches preserve raw values and add aligned
occurrence-local `hz_<field>`, `_id`, `_onto`, and `_hierarchy_depth` groups;
collisions use `(1)`, `(2)`, and no `annotations` arrays are emitted.

The details sidecar records targets, `workflow`, effective `controls`, paths,
`run_status`, errors, configured `preferred_ontology_ids`, and the complete
`harmonization_execution_identity` by `datalink_id`. It also checkpoints the
`harmonization_patch`, run-local `extension_registry`, `pending_review`, and
`review_required` state. A validated review-decision file contains run ID,
source fingerprint, dataset/field identity, `harmonize|prune`, reviewer, and
reason. Partial decisions leave unresolved fields pending.
The current upstream wrapper reports `workflow="local_rag_ols"`. Per-run
`harmonization_options` such as `target_paths`, `target_checker`,
`direct_lookup_judge`, `rag_lookup`, `rag_lookup_judge`, `ols_lookup`,
`ols_lookup_judge`, and `field_assignment_judge` are forwarded unchanged.
The removed `llm`, `lookup_llm_judge`, and `search_llm_judge` keys fail fast
before metadata iteration or upstream harmonizer construction.

Identical metadata/context/options and executor identity are memoized within a
run. Before computing a work key, the adapter requests the upstream
`harmonization_execution_identity`; the required contract binds model and
generation settings, prompt digests, embedding model, ontology sources/indexes,
strategy settings, and preprocessing revision. Incomplete declared identities
fail closed. Legacy injected adapters without that method receive a best-effort
identity derived from their implementation, model attribute, store type, and
ordered preferred ontologies. Changing any identity input invalidates prior
harmonization checkpoints. `max_workers=1` is the safe default; higher values
opt into bounded parallel work with stable output order. Unsupported/empty
metadata never constructs the upstream harmonizer or performs LLM calls.

With a checkpoint store, each unique metadata/context/options work key is
committed immediately after harmonization. Successful outcomes and terminal
consumed-call failures are reused; transient provider/network errors are retried
on resume. One dataset failure remains isolated from other work items.

`GoogleCredentialPreflight` is an optional injected policy. It resolves Google
ADC/project configuration and refreshes the token once without generating model
content. Preflight runs only for eligible metadata when target checking, the
direct judge, RAG retrieval (which needs embeddings), an enabled OLS retrieval
plus judge, or field assignment is enabled. A fully deterministic/offline set
of stage controls does not require credentials.
<a id="epmc-wrapper"></a>
### EuropePMC Wrapper

`ThematicAtlases.wrappers.epmc.EuropePMCWrapper` handles Europe PMC publication search.

Generated queries are checkpointed under `query_generation` using a stable
input hash. Query-level search state is checkpointed under `search_queries`
with page/cursor progress alongside `search_pages`; transient search failures
resume without refetching completed pages.

Current public methods:

- `collect_accessions(queries, max_publications=None, max_publications_per_query=None, checkpoint_store=None, scrape_fulltext_accessions=True) -> list[dict]`: searches and deduplicates publications, advertises main phase `datalinks`, fetches Datalinks, changes the phase to `downstream`, optionally scans Europe PMC XML, supported preprint JATS, or abstract fallback, resolves exact official PubMed→GDS links, merges normalized accession records with provenance, and returns candidates before repository filtering.
- `collect_publications(queries, max_publications=None, max_publications_per_query=None) -> list[dict]`: searches Europe PMC for each query and returns normalized, cross-query-deduplicated publication rows. The per-query limit list aligns with query order; configured limits can expand pagination beyond the default five pages.
- `collect_publication_texts(publications: list[dict], checkpoint_store=None) -> list[dict]`: fetches Europe PMC `fullTextXML`, then official bioRxiv/medRxiv JATS for supported preprints, and otherwise falls back to abstracts. With a checkpoint store, each publication is locked and a busy bounded lock defers that item.
- `collect_datalinks(publications: list[dict], checkpoint_store=None) -> list[dict]`: calls only the Europe PMC datalinks API for publication rows, flattens datalink rows internally, deduplicates by accession, and returns accession records; publication-text fetching belongs to `collect_accessions`. Datalinks and Europe PMC full-text request starts share the run-local cross-process provider interval.
- `accessions_from_fulltexts(publications, checkpoint_store=None) -> list[dict]`: extracts registry matches from available Europe PMC XML or preprint JATS with `fulltext_regex` provenance and from abstract fallback with `abstract_regex` provenance, then checkpoints each publication.
- `accessions_from_link_graph(publications, checkpoint_store=None, cached_only=False) -> list[dict]`: delegates numeric-PMID discovery to the injected NCBI graph provider and can replay only existing graph checkpoints without network calls.
- `merge_accessions(datalink_accessions, scraped_accessions, link_graph_accessions=None) -> list[dict]`: performs deterministic Datalinks → text → graph, case-insensitive accession/publication merging while retaining every discovery source and graph provenance.
- `publication_text_sections(text: str) -> list[dict]`: parses section-delimited publication text into ordered section dictionaries.

The wrapper uses `requests.get()` against:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/search
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML
https://api.biorxiv.org/details/{biorxiv|medrxiv}/{doi}/na/json
https://www.biorxiv.org/...source.xml
https://www.medrxiv.org/...source.xml
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi
```

Preprint JATS fetching is limited to Europe PMC `PPR` rows with bioRxiv or
medRxiv DOI prefixes. The wrapper selects the latest numeric API version and
accepts only HTTPS JATS URLs on the exact `www.biorxiv.org` or
`www.medrxiv.org` hosts.

Search parameters:

- `query`: the keyword query string.
- `format=json`
- `resultType=core`
- `pageSize=1000`
- `cursorMark=*` initially, then the returned `nextCursorMark`.
- `synonym=TRUE`

`max_publications` remains an optional positive global raw-hit cap for backward compatibility. `max_publications_per_query` accepts one positive integer or `None` per ordered query, so reaching one query's limit does not suppress later queries. Raw hits count toward limits before deduplication. Publications match by Europe PMC source/id, PMID, PMCID, or normalized DOI; merged multi-query records preserve the first `query` and add ordered `queries` provenance.

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

`abstractText` comes directly from the Europe PMC `/search` response for each hit. Europe PMC may omit the field or return it empty; the wrapper normalizes missing values to `abstractText=""` in collected publication provenance. This is independent of datalink collection, so either the primary XML representation or the JSON fallback can produce accession records whose publication has an empty `abstractText`.

`collect_publications()` and `collect_datalinks()` are intermediate stages inside
`collect_accessions()`. With scraping enabled, `collect_publication_texts()` is
also called there so publications with no Datalinks can still contribute
accessions. PubMed→GDS discovery remains active whether scraping is enabled or
disabled. The enriched publication rows are carried forward and reused by
`AtlasFilterer`, avoiding a second full-text request.

<a id="pubmed-gds-link-graph"></a>
#### PubMed→GDS link-graph discovery

`PubMedGDSLinkGraphWrapper` batches numeric PMIDs through NCBI ELink using
repeated `id` parameters, `dbfrom=pubmed`, `db=gds`, and
`linkname=pubmed_gds`. It validates an exact one-to-one LinkSet mapping back to
the requested PMIDs, then batches the linked UIDs through GDS ESummary. Only a
summary with `entrytype=GSE`, an accession matching `GSE\d+`, and an identity
accepted by `RepositoryCapabilityRegistry.review_identity()` is projected.
Titles, related articles, computational neighbours, GDS/GSM/GPL entries, and
DOI-only fuzzy searches are not inference sources.

Link results are checkpointed under `pubmed_gds_links` by PMID and summaries
under `gds_summaries` by GDS UID. Successful and authoritative `no_data`
outcomes replay within the trace; retryable request failures use the existing
request policy and shared `ncbi_eutils` provider pacing. Public records retain
only the PMID, `pubmed_gds` link name, target UID, normalized GSE, provider, and
discovery-contract version rather than raw API responses. Exact official graph
evidence is sufficient for discovery without a text match. Suitability remains
strictly downstream: unavailable, empty, or invalid metadata packages never
become reviewer inputs. The contract version is part of new trace fingerprints,
so pre-graph production traces cannot resume silently with changed dataset
membership. A stopped mid-Datalinks trace may be cloned explicitly through
`Atlas.migrate_discovery_run`; the source remains immutable and only the new
trace adopts the graph contract.

<a id="fulltext-accession-discovery"></a>
#### Publication-text accession discovery

The option is enabled by default across Python, the installed CLI, and fixed
fibrosis runners. `--no-scrape-fulltext-accessions` disables only publication-
text scanning; Europe PMC Datalinks and PubMed→GDS graph discovery remain
active. Resume treats a missing manifest field as the legacy disabled text-scan
behavior; new enabled traces include the field in the fingerprint.

The registry accepts canonical contiguous tokens, case-insensitively, and
normalizes them to uppercase:

- GEO: `GSE`, `GSM`, `GPL`, and `GDS`;
- ArrayExpress: experiment/study `E-*` and array-design `A-*`;
- BioStudies `S-*`;
- BioProject `PRJNA`, `PRJEB`, and `PRJDB`;
- INSDC study/sample/experiment/run/analysis/submission families
  `?RP`, `?RS`, `?RX`, `?RR`, `?RZ`, and `?RA` for `S`, `E`, or `D`;
- BioSample `SAMN`, `SAMEA`, and `SAMD`.

Europe PMC XML and supported preprint JATS use `fulltext_regex`; abstract
fallback uses `abstract_regex`. JATS parsing includes body and back-matter
sections such as Data Availability but excludes the reference list. Datalink
fields win conflicts, while
`discovery_sources` and nested `accession_discovery_sources` retain
`europe_pmc_datalink`, `fulltext_regex`, `abstract_regex`,
`ncbi_pubmed_gds`, or their applicable combination. Each publication's normalized
candidates are stored under `fulltext_accession_discovery`, a retryable
discovery boundary. The existing `AtlasCollector.filter_accessions()` remains
authoritative: currently supported GEO and selected ArrayExpress experiment
IDs continue, while every other family is visible only in checkpoints/logs.

During traced workflows, every completed search page, publication datalink
lookup, publication full-text/fallback result, and full-text accession extraction
is committed independently to SQLite. A resumed call reconstructs ordered results from these rows and only
reissues missing or transiently failed requests.

`collect_accessions()` returns deduplicated accession records with:

```text
datalink_id
datalink_id_scheme
datalink_url
datalink_category
publications
```

When metadata collection is enabled, `AtlasCollector.collect_jsons()` then routes selected records to metadata handlers. GEO records are normalized to GSE accessions. Final atlas records add:

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

`create_atlas()` returns and writes the current final atlas object. Internally it calls `collect_datasets()` and then `harmonize_datasets()`. The dataset object uses a top-level object with collected accession records and a shared publication text map:

```text
accessions
publication_texts
```

Each `publication_texts` entry contains `text`, `text_source`, and `full_text_status`. Publications attached only to unselected, GPL, or unresolved records are not sent through the fullTextXML enrichment stage.

Publication text enrichment uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{id}/fullTextXML
```

The full-text ID is the publication `pmcid` when present, or `epmc_id` when it is PMC-style. Successful fullTextXML responses are parsed into section-delimited plain text and stored as `text` with `text_source="fullTextXML"` and `full_text_status="available"`. Section delimiters use this exact sentinel, which downstream parsers may split on:

```text
<<<THEMATIC_ATLASES_SECTION:title=Methods>>>
```

`publication_text_sections(text)` converts delimited text back into ordered dictionaries such as `{"title": "Methods", "text": "..."}`. For plain fallback text without sentinels, it returns one `Text` section when text is non-empty.

If full text is unavailable, non-open-access, missing a PMC identifier, empty, or fails with an unrecoverable error, the publication remains in provenance and the shared publication text map falls back to `abstractText` when present. In that fallback path, `text_source` is `abstractText` when the abstract is non-empty, otherwise `none`; `full_text_status` is `unavailable`, `missing_pmcid`, or `error`; and fallback text is not delimiter-wrapped. Publisher pages and `fullTextUrls` are not fetched.
An ordinary fullTextXML 404 is an authoritative terminal unavailability
checkpoint rather than retryable work; throttling responses, 5xx responses,
and concrete transport failures remain retryable.

The datalink request uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
```

without a format parameter, using Europe PMC's default XML representation.
Each retry round performs one XML request, waits at least `request_delay`, and
then performs one `format=json` request when XML has a transport/HTTP or
ordinary syntax failure. When either failure is retryable and neither format
succeeds, the shared bounded backoff starts another round at XML. With the
default `max_retries=3`, this permits four attempts per representation and at
most eight requests, matching the prior worst-case request ceiling while
allowing JSON to recover after the first XML failure. A pair of permanent
failures stops immediately; an exhausted mixed pair propagates a retryable
failure so its checkpoint remains resumable. Throttle statuses and
`Retry-After` use the greater of provider backoff and `request_delay`, and all
failed or consumed responses are closed before the next request. Valid XML,
including valid empty XML, remains authoritative. XML security and size-limit
failures remain fail closed and never fall back. If both representations fail
for one publication, that publication is skipped, logged, paced, and counted
while collection continues. The public output, checkpoint schema, and current
dataset category filter are unchanged; the filter keeps `GEO`, `BioProject`,
`BioStudies`, `Nucleotide Sequences`, `BioStudies: supplemental material and
supporting data`, and `Functional Genomics Experiments`.

Atlas, collector, filterer, EuropePMC, and GEO library modules define loggers but do not configure global logging. The CLI is responsible for logging configuration.

Atlas emits INFO-level progress logs for the `create_atlas()` orchestration stages. `AtlasCollector` emits INFO-level collection progress and stats, including query loading, Europe PMC accession collection, accession filtering, metadata collection, output writing, query count, raw accession count, filtered accession count, and metadata output count. `AtlasFilterer` emits INFO-level filtering progress and stats, including publication text collection, publication text-reference attachment, publication text map count, and accessions with publication text references.

Each EuropePMC query logs one INFO-level search stats message with the query, total hits from `hitCount` when present, collected hits, fetched pages, page limit, whether the page limit stopped pagination, and final cursor.

Each publication text enrichment pass logs one INFO-level stats message with publications checked, full text available, abstract fallbacks, and missing text.

Each datalink collection pass logs one INFO-level stats message with publications checked, datalinks collected, skipped categories, and failed publications.

Each accession deduplication pass logs one INFO-level stats message with input datalink rows, output accessions, duplicate rows collapsed, and skipped rows.

<a id="rate-handling"></a>
### Rate Handling

`EuropePMCWrapper` has conservative defaults:

- `page_limit=5`
- `page_size=1000`
- `timeout=None`, selecting the profile's 10/60-second connect/read pair
- `request_delay=0.5`
- `max_retries=3`

`EuropePMCWrapper`, `GEOWrapper`, the graph wrapper, and MSC clients delegate
every actual attempt and redirect to the same per-user `HostRequestGate`. The
gate normalizes host keys, serializes updates with `flock`, spaces NCBI and
Europe PMC starts by 0.5 seconds and bioRxiv/medRxiv, GEO FTP, ENA, and
BioStudies starts by one second, and persists provider cooldowns across local
processes and traces. Different hosts proceed independently.

`RequestPolicy` retains HTTPS, host, redirect, decoded-body, aggregate-byte,
and response-close boundaries. Concrete timeout, connection, chunked-transfer,
incomplete-read, and content-decoding errors plus 403/408/425/429/5xx responses
use bounded exponential full jitter. Numeric and HTTP-date `Retry-After` values
are persisted without an artificial cap. When a cooldown exceeds the remaining
inline worker budget, the caller writes a retryable checkpoint with
`next_retry_at` and defers rather than sleeping indefinitely. Counters expose
provider attempts, retries, and accumulated gate wait without logging URLs,
parameters, query values, or credentials. A configured NCBI API key never
automatically raises the conservative default rate.

<a id="arrayexpress-wrapper"></a>
### ArrayExpress Wrapper

`ArrayExpressWrapper.collect_accession_metadata` and its offline availability
projection share `MetadataConversionAdapter` with GEO. The adapter calls MSC
`Converter.convert()` once per study, preserves all returned canonical packages,
and checkpoints `metadata_conversion[arrayexpress:ACCESSION]`. Default enrichment
is `standard`, related-study expansion is enabled, and the configured resource
limits are passed to MSC. Inject `converter=` to replace the conversion boundary.
See [contract 2.0](#workflow-checkpoints-v2) for statuses, retries and compatibility.

<a id="geo-wrapper"></a>
### GEO Wrapper

`GEOWrapper` retains NCBI ESearch/ESummary resolution of GSM/GDS to GSE and normalizes
GSE identifiers locally. It delegates metadata to the same MSC unified adapter as
ArrayExpress, preserving publications and original Datalinks across all returned
packages. `metadata_source` is `msc.convert`. `converter=` is the conversion
injection point. `enrich_metadata=False` explicitly selects enrichment `off`;
the default uses MSC standard enrichment and related-study expansion.

The only GEO metadata recovery boundaries are remote `geo_resolution` and whole
`metadata_conversion[geo:GSE...]`. No raw-source, parsing, validation or identifier
repair checkpoint is resumed. See [contract 2.0](#workflow-checkpoints-v2).

<a id="cli-atlas"></a>
## CLI Atlas

`ThematicAtlases.cli_atlas` provides a standard-library `argparse` CLI with `main(argv: list[str] | None = None) -> int`.

Commands:

- `[-v | --verbose] [--log-file LOG_FILE]`
- `create-atlas [--verbose] [--log-file LOG_FILE] [--resource-profile standard|large] [--resource-override FIELD=VALUE] [--query QUERY] [--file FILE] [--query-generator|--no-query-generator] [--max-generated-queries N] [--thematic-review|--no-thematic-review] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--scrape-fulltext-accessions|--no-scrape-fulltext-accessions] [--dev-trace] [--dev-out-dir DIR] [--stop-after query-results|datalinks|publication-text|fulltext-accessions|accession-graph|metadata|review|harmonization] (--theme THEME|--theme-file FILE) [--review-filter MODE] [--review-strategy direct] [--harmonization-details-out PATH]`
- `fork-run [--resource-profile standard|large] [--resource-override FIELD=VALUE] --dev-out-dir DIR --run-id SOURCE --new-run-id DEST --config JSON`
- `collect-datasets [--verbose] [--log-file LOG_FILE] [--resource-profile standard|large] [--resource-override FIELD=VALUE] [--query QUERY] [--file FILE] [--query-generator] [--max-generated-queries N] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--scrape-fulltext-accessions|--no-scrape-fulltext-accessions] [--theme THEME] [--theme-file FILE] [--review-filter MODE] [--review-strategy direct]`
- `harmonize-datasets [--verbose] [--log-file LOG_FILE] [--resource-profile standard|large] [--resource-override FIELD=VALUE] --file INPUT --out OUTPUT [--harmonization-details-out PATH]`
- `resume [--verbose] [--log-file LOG_FILE] [--resource-profile standard|large] [--resource-override FIELD=VALUE] [--dev-out-dir DIR] [--run-id ID] [--out OUT] [--stop-after query-results|datalinks|publication-text|fulltext-accessions|accession-graph|metadata|review|harmonization] [--retry-stage STAGE] [--retry-item STAGE:KEY] [--retry-degraded-stage STAGE]`
- `worker-snapshot [--verbose] [--log-file LOG_FILE] --dev-out-dir DIR --run-id ID --stage text|graph|metadata|review [--item-limit N]`

Logging options may appear before or after the subcommand. Default logging level is `WARNING`; `-v` or `--verbose` enables INFO progress and stats logs, and `-vv` enables DEBUG request, retry, and routing logs. Without `--log-file`, logs go to stdout. With `--log-file`, logs are written to that UTF-8 file only. If logging options are supplied both before and after the subcommand, the subcommand-local value is used.

The CLI forwards explicit queries, the query-file path, `--query-generator`,
`--max-generated-queries`, `--review-before-metadata`,
`--scrape-fulltext-accessions`/`--no-scrape-fulltext-accessions`, and
`--review-strategy`; `Atlas.collect_datasets()` owns loading, ordering,
generation, validation, accession discovery, and review dispatch. Full-text
accession discovery defaults on. Explicit query values precede file queries,
followed by generated queries. Without the query-generator flag no
query-generation LLM call occurs. Review-before-metadata requires a theme.
`--dev-trace` is supported by `create-atlas` only; `--dev-out-dir` chooses its
root directory.

Each command instantiates `Atlas(metadata={}, resource_profile=...,
resource_overrides=...)`, calls the matching method, and configures logging
from CLI options. Unknown override fields and invalid numeric values fail
before workflow work. Ordinary successful commands do not print result data to
stdout. A worker prints its JSON summary and returns `0` for complete/no work,
`2` for busy/yielded/interrupted/deferred work, or `1` for a safe outer failure.
SIGINT/SIGTERM sets cooperative cancellation and allows the in-flight atomic
item or model request to finish before the summary and locks are finalized. If
no item has been claimed, frontier construction stops between records.

`collect-datasets` and `create-atlas` share the mature collection and
publication-text stage components. Supplying `--theme` or `--theme-file` opts
into `agentic_curator` thematic review for each unique publication text before
review filtering. Both public commands return/write Atlas v1 through
`AtlasDocumentAdapter`. `create-atlas` then harmonizes and transactionally
publishes the requested final JSON plus automatic summary. The standalone
`harmonize-datasets` command requires Atlas v1 at `--file`, writes Atlas v1 at
`--out`, and fails closed on legacy unversioned accessions envelopes. Both
harmonizing commands can write the optional details sidecar and accept
`--review-decisions-file`.

`resume` selects `--run-id` or the newest incomplete v1 trace under
`--dev-out-dir` (default `.dev`), optionally writes `--out`, and
`--stop-before-review` returns the collection snapshot. Repeatable
`--retry-stage`, `--retry-item STAGE:KEY`, and `--retry-degraded-stage`
requests are validated and forwarded to `Atlas.resume`; missing
`atlas_run.sqlite3`, malformed item syntax, or unsupported selections raise
rather than migrating state or silently requeueing other work. A supplied
`--review-decisions-file` must identify the selected run and a current MINiML
source fingerprint before its matching item is selectively rerun.

<a id="archive-reference"></a>
## Archive Reference

No `oldd/` archive is tracked in the current repository. Historical
implementations must be recovered from version control rather than from a live
source directory. Runtime whole-run archives are ignored data under
`.out/previous_runs/`; they are resumable artifacts produced by
[`archive_existing_runs`](../src/ThematicAtlases/run_archive.py), not source
material and never an import boundary.

<a id="test-and-verification-status"></a>
## Test And Verification Status

The deterministic gate reported `723 passed, 4 skipped` on 2026-08-25. Tests cover an offline real-component Atlas system workflow, empty and nested outputs, summaries, strict Atlas v1 scalar/list/boolean/integer types, opt-in trace checkpoints and path safety, persisted runtime provenance/resource profiles, canonical exact resume selection, SQLite durability/fingerprints, atomic concurrent event allocation, selective retry atomicity, review-decision run/source validation and selective checkpoint invalidation, terminal/retryable harmonization reuse, cache invalidation across complete harmonization execution identities, v3-only MINiML validation and canonical 3.0 transport, harmonized summary projection from `hz_*` groups, archive copy/publication/fsync/cleanup failures, transient SQLite-sidecar races, durable archive mutation rejection, actionable-frontier limits for all four workers, legacy transport-checkpoint recovery, deterministic graph batch splitting and singleton isolation, cooperative cancellation during pre-claim scans and in-flight work, shared cross-process HTTP/model pacing and cooldowns, Retry-After persistence, metadata/review read-only reuse, canonical sidecar-to-main checkpoint reuse, metadata audit/typed repair artifacts, grounded direct review, interruption and item-level resume across providers, method-owned query generation, credential preflight, immutable repository capability routing, status 2.0 propagation, resource profile/CLI overrides, safe error persistence, bounded external-DTD XML parsing, compressed-response/redirect/aggregate limits, GEO filtering, publication review, configurable/cached/parallel ontology harmonization, CLI forwarding, repository resolution, packaged recall references, resumable reviewer hydration, source-faithful metadata retention, privacy-safe diagnostics, and trace-free thematic-review benchmarking. Network, HTTP/socket, subprocess, model, Docker, and nf-core effects are blocked or replaced by default.

Useful checks:

```bash
.env/bin/python -m py_compile src/ThematicAtlases/__init__.py src/ThematicAtlases/atlas.py src/ThematicAtlases/checkpoint.py src/ThematicAtlases/cli_atlas.py src/ThematicAtlases/summary.py src/ThematicAtlases/trace.py src/ThematicAtlases/collector/__init__.py src/ThematicAtlases/collector/collector.py src/ThematicAtlases/filterer/__init__.py src/ThematicAtlases/filterer/filterer.py src/ThematicAtlases/filterer/review.py src/ThematicAtlases/harmonizer/__init__.py src/ThematicAtlases/harmonizer/harmonizer.py src/ThematicAtlases/wrappers/__init__.py src/ThematicAtlases/wrappers/ae.py src/ThematicAtlases/wrappers/epmc.py src/ThematicAtlases/wrappers/geo.py
.env/bin/python -m pytest -q
```

If `pytest` is unavailable in the active environment, use a direct smoke check:

```bash
PYTHONPATH=src python3 -m ThematicAtlases.cli_atlas collect-datasets --query fibrosis
```

The smoke check performs a live Europe PMC request when `requests` is installed and network access is available.

<a id="operational-events-v1"></a>
## Operational Events V1

`ThematicAtlases.operational_events.OperationalEventEmitter` emits a shared
schema-1.0 envelope to ordinary structured logging and an optional append-only
JSONL file. Fields are `timestamp`, `repository`, `component`, `event_type`,
`level`, `run_id`, `stage`, `status`, `duration_seconds`, and redacted
`attributes`. Recursive redaction removes credential-like keys and URL query
strings before persistence or logging. In-memory aggregates export atomically
as JSON or Prometheus text.

`AtlasRunStore.record_event` remains the authoritative Atlas lifecycle record.
It stores redacted detail transactionally and, when an emitter was injected,
emits the matching operational envelope after the SQLite commit. Qualified
symbols are `ThematicAtlases.operational_events.EVENT_SCHEMA_VERSION`,
`ThematicAtlases.operational_events.OperationalEventEmitter`, and
`ThematicAtlases.operational_events.redact`.

<a id="resume-dependency-wiring"></a>
## Resume Dependency Wiring

Collector and review resume modules now depend only on checkpoints, trace
storage, provider wrappers, and injected collaborator factories. They do not
import their owning collector/filterer implementations, and the owning modules
contain no method-local component imports. Package composition registers the v1
default factories after concrete classes are defined; explicit factories remain
authoritative in tests and custom integrations. This preserves the public
`TraceMetadataResumer()` and `PublicationTextReviewer.resume()` behavior while
making the dependency direction one-way and inspectable.

<a id="msc6-source-migration"></a>
## MSC 6 source-service migration

GEO and ArrayExpress converter classes now use explicit uppercase names. Provider
imports use `meta_standards_converter.sources`; enrichment uses
`meta_standards_converter.metadata.enrichment`. Source serialization is unchanged.

Checkpointed GEO ingestion composes `GEOSource` and `MINiMLEnricher` directly.
Source XML, pre-canonical packages, diagnostics and incremental enrichment retain
the existing checkpoint stages. Checkpointed INSDC retrieval implements a public
client interface instead of inheriting private XML retrieval; metrics use explicit
snapshots. The focused GEO/enrichment regression suite passes 60 tests.

<a id="msc6-direct-integration"></a>
## MSC 6 direct integration

Historical cutover record: serialization versions below describe that release.
See [current curation contracts](#curation-policy-v11) for new output and compatibility.

GEO ingestion injects `GEOSource`, a network-free `GEOParser`, and checkpoint-aware enrichment clients. `CheckpointedINSDCFetcher` implements public SRA XML and ENA file-report retrieval; no private `_ncbi_nrx` override remains. `ArrayExpressWrapper(source_resolver=None, parser=None, ...)` resolves MAGE-TAB directly through `AEWebFetcher` and `AEParser`. Both paths checkpoint source evidence before parsing and preserve validation diagnostics. Metrics accumulate deltas from cumulative public snapshots. The checkpoint ingestion path retains its original publication inheritance rules.

The coordinated release preserves MINiML 3.0, retained patches 3.1, Atlas documents 1.0 and serialized checkpoint/status contracts. Historical runs retain their original revision provenance. A new implementation does not authorize automatic production resume: validate a disposable transition using the supported workflow mechanism, or start a new run. Never mix old and new workers against shared state. Processed H5AD checkpoints use version-specific destinations without changing the fingerprint algorithm.

<a id="msc7-export-policy"></a>
## MSC 7 export policy boundary

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

Publication applies no export profile. The Atlas v1 metadata field remains canonical MINiML; converters apply caller policy later. Dependency tests assert Curator 5 and MSC 7 compatibility.


<a id="miniml-v3-only-cutover"></a>
## MINiML v3-only cutover

Historical cutover record; the [current curation contracts](#curation-policy-v11)
add MINiML 3.1 output while retaining 3.0 readers.

MSC 8.0.0, Agentic Curator 6.0.0, ThematicAtlases 6.0.0, and the GSK adapter
6.0.0 require canonical MSC MINiML `3.0` at application boundaries. MSC no
longer exports `MINiMLV2Migrator` or `MINiMLCodec.migrate_v2`; v2 packages are
rejected, including packages embedded in Atlas metadata and profile-free
Curator envelopes. GEO and MAGE-TAB source ingestion remains supported and
constructs v3 directly, including harmonized values, units, ontology companions,
hierarchy depth, and indexed occurrences. Explicit unversioned/1.0 source
import remains available through `miniml-migrate legacy.json canonical.json`.

Saved v2 documents must be regenerated from source or converted with the
preceding MSC 7 release in a separate environment before loading. Changing only
the version marker is insufficient when annotation arrays are present. This
release does not rewrite historical runs, caches, checkpoints, or archives.
The converter version separates new processed checkpoints from earlier releases;
replacement profiles remain part of checkpoint identity.

The canonical v3 wire schema is unchanged: raw values and `hz_*` evidence remain
additive; source-bound patch evidence stays in `extensions.msc_harmonization`.
Curator's evidence remains optional. Patch 3.1, Atlas 1.0, H5AD metadata 2.0,
assay export 3.0, and unrelated status-v2 contracts keep their versions. GSK
scientific selection policy is unchanged. Boundary rejection, fresh ingestion,
semantic export/reparse, source preservation, profiles, and consumer integration
are covered by the maintained v3 fixtures and `test_miniml_v3_only.py` tests.

<a id="magetab-source-evidence-v2"></a>
## MAGE-TAB source evidence v2

`integrations.magetab` owns the lossless MSC `MAGETabInput` checkpoint codec.
Catalogue-capable MSC writes ArrayExpress source payload v2 with the complete,
ordered `file_catalogue`; parsing restored evidence must equal fresh parsing.
The existing wrapper codec methods delegate to this adapter. This changes only
the source-evidence payload, not SQLite, Atlas v1, or MINiML schemas.

Older MSC without the optional catalogue field continues to read/write v1.
A v2 snapshot requires catalogue-capable MSC. Under the newer runtime, v1
accession evidence lacks a known catalogue: source-only reparsing raises
`SourceEvidenceCompatibilityError` and requests complete recollection in a fresh
run, without fetching or rewriting historical evidence. Available metadata reuse
retains its existing rules; v1 local/URL snapshots retain their empty-catalogue
resolver contract. Invalid/future payloads fail explicitly. Compatibility errors
escape the wrapper's provider-failure handler rather than being cached as a
terminal provider error. Run provenance checks still apply.

Tests: `tests/test_magetab_source_contract.py` exercises actual MSC parsing of a
nonempty catalogue, source-only restoration, nested/ambiguous filenames, complete
row preservation, old-MSC construction, legacy snapshots and available-result
reuse. Offline tests isolate default ontology storage as well as provider gates.

<a id="workflow-ownership"></a>
## Workflow ownership

`Atlas` preserves its public signatures and injected-service/subclass hooks while
operation-local workflow objects implement `create`, `collect`, `resume`,
`harmonize`, and query `amend` in `ThematicAtlases.workflows`. Each workflow receives
the facade as its compatibility context and owns its execution order; it does not
construct shared provider clients. `runtime.pauses.AtlasPauseController` owns
pause snapshots and frontier counts. Existing public methods delegate explicitly.

Creation and resume still reach overridden `collect_datasets` and
`harmonize_datasets` methods through the existing compatibility adapters. Storage,
publication, stage names and fingerprint policies are unchanged by extraction.
Tests in `test_workflow_boundaries.py` freeze the public Python signatures and
exercise independently invoked workflows, subclass overrides and validation
before external work. Existing creation/resume/pause suites cover lifecycle and
artifact parity.

<a id="typed-stage-operations"></a>
## Typed stage operations

`ThematicAtlases.stages` holds discovery, metadata collection, publication text,
per-publication review and harmonization operations. Each receives a frozen
request dataclass and returns an explicit result (`RecordsResult`,
`PublicationTextsResult`, `ReviewResult`, or `HarmonizationResult`). `StagePort`
describes this internal boundary. Requests retain source values and references;
they do not duplicate MSC's structural metadata model or deep-copy service state.

Existing collector/filterer/reviewer/harmonizer/provider methods construct these
requests and adapt results to their original public shapes. Main, resume and
worker callers therefore share the operations while retaining their scheduling,
locking and eligibility rules. Operation-local stage instances receive the owning
service's dependencies and extension hooks; they do not confer thread safety on
injected mutable clients. Review input identities, retry outcomes, harmonization
deduplication and output ordering remain unchanged.

Focused tests cover cross-repository batching/order, embedded text reuse, review
checkpoints, failed/reused harmonization, discovery pauses and worker behaviour.

<a id="runtime-construction-and-management"></a>
## Runtime construction and management

`bootstrap.AtlasRuntimeFactory` is the supported reusable construction boundary.
It accepts provider/metadata/reviewer factories, repository selection, resource
profiles, NCBI identity and capabilities; builds Atlas through `build_atlas`; and
creates fresh collectors, filterers, reviewer continuations and workers. Injected
services pass through unchanged. Construction makes no provider/model call.
Explicit classification remains a caller policy; the default remains unknown.
`Atlas.__init__` delegates initialization to this same construction module while
retaining its public signature and lazy query/cache behaviour.

`DevTraceWriter.manager` exposes `runtime.manager.AtlasRunManager`, bound to one
run identity. It supports retry selection, status counts, redacted events and
failure recording without exposing store layout to callers. Failure recording
preserves item checkpoints and publishes the existing retry-report artifact.
`runtime.snapshots.read_checkpoint_snapshot` opens a query-only SQLite transaction
and returns coherent metadata/rows without constructing or migrating stores. The
query recall benchmark uses this boundary. Store schemas and projection triggers
remain unchanged.

Tests: `test_bootstrap.py`, `test_run_management.py`, existing CLI, trace and query
benchmark suites cover lazy construction, resource/cancellation propagation,
operation lifetimes, selected retries, preservation of available evidence and
read-only snapshots.

<a id="package-boundaries-and-compatibility"></a>
## Package boundaries and compatibility

The implementation is organized by responsibility:

- `domain/atlas.py`: Atlas document models and validation, exported by `domain`.
- `workflows/`: create, collect, resume, harmonize, amend and cooperative workers.
- `stages/`: typed operations shared by the workflows and legacy service facades.
- `integrations/`: Europe PMC, GEO, ArrayExpress and MSC source-evidence adapters.
- `runtime/`: checkpoint/run stores, traces, archive/lifecycle, pauses, management
  and read-only snapshots. Storage SQL and authority remain unchanged.
- `publication/`: document adaptation/assembly, summaries and durable publication.
- `cli/atlas.py`: argument parsing and dispatch, including explicit factory
  injection for offline callers/tests. The installed `cli_atlas.main` entrypoint
  retains its original signature and delegates here.
- `bootstrap.py`: construction of shared services and fresh continuation objects.

Former modules remain compatibility exports of the same classes/functions. Private
module-level monkeypatches must target the owning implementation; supported
constructor injection and public subclass methods remain valid. Provider log
names remain stable across relocation. Wrapper package exports load lazily so a
provider can import shared helpers without an eager provider-import cycle.
Tests in `test_package_boundaries.py` check old/new import identity and injected
CLI dispatch; the workflow signature fixture checks public arguments/defaults
and exported annotation types independently of their implementation module names.

<a id="curation-policy-v11"></a>
## Curation policy and Atlas 1.1

Consolidation decision, 2026-11-16: retain existing publication filtering while
adding schema transport and configurable criterion limits. TA configures a fresh
AC reviewer through its existing `MAX_CRITERIA` override; the AC constructor and
prompts remain unchanged. Injected reviewers must declare the same effective cap.
The cap, reviewer identity and review contract 12 invalidate incompatible cached
criteria and reviews. `Atlas.collect_datasets`, `Atlas.create_atlas` and their CLI
commands expose `max_review_criteria` / `--max-review-criteria` (default 12).
Positive integer limits are maxima, not requested counts. Manifests, resumes,
workers and downstream forks retain the cap.

`review_filter="not_relevant"` removes negative judgements regardless of confidence.
`not_relevant_and_unsure` also removes unsure judgements; it is not deprecated.
`none` disables publication filtering. Existing accession-removal behavior remains
unchanged. New reviews retain raw confidence without generating publication policy,
model-assessment or accession-action records from the excluded AC policy proposal.

New Atlas JSON uses schema 1.1; readers accept 1.0 and 1.1. PublicationReview stores
confidence and optionally a historical typed PublicationPolicy. Historical policy
records round-trip without controlling current filtering, and absent policies stay
absent/null. Negative thematic-relevance criteria retain `passed=false` at every
confidence. Dataset MINiML writes use MSC 3.1 and depth-qualified ancestor names;
checkpoint payload version 2 rejects incompatible previous wire contracts. MSC owns
legacy patch hashes and typed rendering/parsing. AC's existing egress APIs remain
required by configured callers.
