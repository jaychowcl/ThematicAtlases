# ThematicAtlases Codebase Handoff

This is the canonical architecture, interface, and workflow handoff for the
implemented package. It is evidence-backed by the production modules, package
metadata, supported interfaces, and tests in this repository.

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
  `benchmark_ThematicAtlases` consumes outputs but never mutates production
  traces. Repository metadata-handler status is explicit: GEO is supported;
  ArrayExpress and scanner-only curated repositories are retained as terminal
  inventory until a real supported handler is injected.
- **Privacy/trust boundary:** credentials, authorization headers, provider
  payloads, prompts, and responses must not be written to operational logs.
  Safe logs contain identifiers, status, duration, counts, and stage summaries.

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
  SQLite store and status/history rows.
- **Rationale:** Not documented.
- **Consequences:** resume reuses completed and terminal work and can selectively
  requeue retryable/degraded work; incompatible configurations fail validation.
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
### AD-004: Direct review is the default and legacy review remains isolated

- **Status:** Observed
- **Decision:** `direct` is the default review contract;
  `evidence_then_judgement` remains an explicit compatibility choice.
- **Rationale:** Not documented.
- **Consequences:** review strategy is fingerprinted and cannot change on
  resume without an explicit supported override.
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
  durable-file snapshots, staging copy, checksum verification, and atomic
  publication before deleting any source. SQLite's trace-root `-wal` and
  `-shm` sidecars are transient snapshot inputs and are not archived; a
  non-empty WAL after checkpointing fails closed.
- **Rationale:** Not documented.
- **Consequences:** Existing runs survive interrupted or conflicting archival,
  while active workflows, symlinks, unsafe names, and destination collisions
  stop a new run instead of being overwritten.
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
  Unknown fields, duplicate identities, dangling publication references, and
  inconsistent derived counts fail validation. Legacy `accessions` and
  `publication_texts` mappings exist only between mature internal stages.
- Metadata repository routing defaults to GEO. Unsupported, unresolved, or
  failed metadata is represented explicitly rather than silently fabricated.
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
  collisions, verifies copied content, and publishes before deleting sources.
- Library modules do not configure global logging. No credential, prompt,
  response, authorization header, or full provider payload belongs in logs.

<a id="component-relationships-and-data-flow"></a>
## Component relationships and data flow

| Source | Destination | Interface and direction | Data/lifecycle ownership | Failure behavior |
| --- | --- | --- | --- | --- |
| CLI/runners | `Atlas` | synchronous Python calls | caller owns inputs; `Atlas` owns run ordering | parser/validation error ends invocation |
| `Atlas` | `AtlasCollector` | `collect_jsons` / `resume_metadata` | collector owns repository selection and metadata stage | item errors represented/checkpointed |
| collector | Europe PMC/GEO/AE wrappers | adapter calls, outbound HTTP where implemented | wrappers own response normalization; shared `RequestPolicy` owns bounded GET retries | transient requests retry; unsupported handler statuses become terminal inventory without invocation |
| `Atlas` | `AtlasFilterer` | atlas-shaped mappings | filterer owns text map, review context, and filtering | review failures remain item-local in trace |
| filterer | `PublicationTextReviewer` | publication/context mappings | reviewer owns judgement contract; filterer applies outcome filter | strategy/fingerprint mismatches fail |
| `Atlas` | `AtlasHarmonizer` | dataset mappings and controls | harmonizer owns per-work-key cache and details | original metadata retained on failure |
| stage components | `AtlasDocumentAdapter` | legacy mappings into/out of typed v1 | adapter owns boundary projection; document owns validation | malformed v1 and broken references fail closed |
| `Atlas` | `JsonArtifactBundlePublisher` | mapping of path to JSON value | publisher owns stage/backup/replace cleanup | any replacement failure restores the complete prior bundle |
| traced orchestration | `AtlasRunStore` | normalized SQLite calls | store owns runs, stages, work, attempts, artifact roles, and events | incompatible schema/path-role conflict raises |
| item stages | `CheckpointStore` | internal SQLite calls | store owns fingerprints, item results/history, locks, and retry requests | transaction failure prevents false item completion |
| benchmark runner | `ThematicReviewerBenchmark` | saved JSON/trace input | benchmark owns an offline report only | invalid/ambiguous reference identities fail/report conflict |

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
  `create-atlas`, `harmonize-datasets`, or `resume`. The parser is defined in
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
retains its query-first, optional-theme, opt-in-generation contract. Complete
user options live in the [README CLI guide](../README.md#cli-guide).

<a id="interface-python-atlas"></a>
### Python `Atlas` interface

Import `Atlas` from `ThematicAtlases.atlas`; the package root intentionally
exports no names. Its supported workflow methods and specialist package exports
are inventoried in the [public API reference](#public-api-reference).

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
  resolution, credential/cache preflight, stage order, tracing, resume,
  amendment, archival delegation, v1 boundary conversion, and bundle
  publication.
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
  title.
<a id="type-atlas-document"></a>
- [`AtlasDocument`](../src/ThematicAtlases/domain.py) is the canonical v1
  exchange model. Frozen standard-library dataclasses and string enums own
  Atlas identity, run configuration/status, ordered datasets, publications,
  review/harmonization values, diagnostics, artifacts, and derived summary.
  `from_mapping`, `to_mapping`, `load`, `dump`, and `validate` reject unknown
  top-level/nested fields, unsupported versions, duplicate identities, broken
  publication references, blank identity/title/theme text, and inconsistent
  counts. JSON is deterministic,
  UTF-8, newline-terminated, parent-creating, and atomically replaced.
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
  PMC discovery, accession filtering, metadata repository routing, and
  metadata collection. `TraceMetadataResumer` advances or audits a saved trace.
<a id="type-publication-text-reviewer"></a>
- [`AtlasFilterer`](../src/ThematicAtlases/filterer/filterer.py) owns text
  collection/reference attachment, review dispatch, review filtering, and final
  atlas assembly. `PublicationTextReviewer` owns direct/legacy review contracts;
  `TracePublicationReviewResumer` restores independent review state.
<a id="type-atlas-harmonizer"></a>
- [`AtlasHarmonizer`](../src/ThematicAtlases/harmonizer/harmonizer.py) owns
  eligible metadata selection, work-key memoization, bounded parallelism,
  upstream ontology-harmonizer construction, details, and fallback status.
<a id="type-checkpoint-store"></a>
- [`CheckpointStore`](../src/ThematicAtlases/checkpoint.py) owns SQLite schema,
  fingerprint validation/amendment, item state/history, retry selection, item
  locks, and comparison archives. `DevTraceWriter` owns the readable run layout.
<a id="type-europe-pmc-wrapper"></a>
- [`EuropePMCWrapper`](../src/ThematicAtlases/wrappers/epmc.py),
<a id="type-geo-wrapper"></a>
  [`GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py), and
  [`ArrayExpressWrapper`](../src/ThematicAtlases/wrappers/ae.py) isolate remote
  or repository-specific behavior.
<a id="type-thematic-reviewer-benchmark"></a>
- [`ThematicReviewerBenchmark`](../src/benchmark_ThematicAtlases/thematic_reviewer/benchmark.py)
  owns offline exact DOI/PMID comparison and reference-set validation.

<a id="public-api-reference"></a>
## Public API reference

### Support classification

- **Formal exports:** names in a package `__all__`. These are the declared
  reusable component surface.
- **Supported workflow API:** `ThematicAtlases.atlas.Atlas`, the installed CLI,
  and the six root runners. `ThematicAtlases.__init__` exports nothing.
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
artifact_publisher=None)`](../src/ThematicAtlases/atlas.py)
owns dependency injection. It raises `ValueError` when a supplied harmonizer is
combined with Atlas-managed ontology-store/cache options.

| Member | Exact signature | Return, failure, and side effects |
| --- | --- | --- |
| [`Atlas.create_atlas`](../src/ThematicAtlases/atlas.py) | `(query=None, file=None, out=None, theme=None, review_filter="none", review_strategy="direct", metadata_repositories=None, max_publications=None, max_publications_per_query=None, reviewer=None, collect_metadata=True, dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=True, max_generated_queries=3, harmonization_options=None, review_before_metadata=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, thematic_review=True) -> dict` | Requires a nonblank theme and returns a validated Atlas v1 mapping after collection and harmonization. Generation defaults on and appends generated queries after explicit/file queries; disabling it requires an input query. Thematic review defaults on independently and can be disabled only with no review filter or review-before-metadata. Unsupported discoveries are terminal before review/harmonization; summaries include their aggregate counts and the detailed inventory is written only to an explicit path or trace. When `out` is set, related JSON publishes as one rollback-safe bundle. Invalid options/contracts, credentials, cache preparation, files, publication, or uncaught provider failures raise. |
| [`Atlas.collect_datasets`](../src/ThematicAtlases/atlas.py) | `(query=None, file=None, out=None, theme=None, review_filter="none", review_strategy="direct", metadata_repositories=None, max_publications=None, max_publications_per_query=None, reviewer=None, collect_metadata=True, generate_queries=False, max_generated_queries=3, dev_trace=False, dev_out_dir=".dev", run_id=None, review_before_metadata=False, stop_before_review=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, _trace_writer=None) -> dict` | Returns a validated Atlas v1 mapping with run status `running`; `out` atomically receives the same mapping. An explicit unsupported path writes the separate inventory; a traced collection retains it and registers `collection_snapshot`, never `final_atlas`. Validates aligned positive limits, review/theme combinations, query generation, and trace fingerprints before eligible network/model work. `_trace_writer` is internal. |
| [`Atlas.harmonize_datasets`](../src/ThematicAtlases/atlas.py) | `(datasets, harmonization_details_out=None, harmonization_options=None) -> dict` | Requires Atlas v1 input, projects it to the internal stage contract, and returns validated v1 with harmonized status/details. Legacy/unknown wire fields fail validation. Unsupported/null metadata is `not_run`; caught item failures retain original metadata as `error`. |
| [`Atlas.resume`](../src/ThematicAtlases/atlas.py) | `(dev_out_dir=".dev", run_id=None, out=None, stop_before_review=False, retry_stages=None, retry_items=None, retry_degraded_stages=None) -> dict` | Selects a v1 trace, requires authoritative `atlas_run.sqlite3`, optionally archives/requeues selected item-cache rows, reuses completed boundaries, and returns/publishes Atlas v1. Missing/ambiguous/incompatible runs, fingerprint mismatches, or invalid retry requests raise. |
| [`Atlas.amend_queries`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, run_id, queries, max_publications_per_query) -> Path` | Archives the prior fingerprint and installs aligned normalized queries atomically. Empty/misaligned limits, active work, or unsafe state raise. |
| [`Atlas.archive_existing_runs`](../src/ThematicAtlases/atlas.py) | `(*, dev_out_dir, archive_root, workflow, artifact_paths=()) -> list[Path]` | Returns published archive paths after verification; active runs, symlinks, unsafe names, nested roots, and collisions raise without deleting sources. |

[`ThematicAtlases.cli_atlas.main(argv=None) -> int`](../src/ThematicAtlases/cli_atlas.py)
parses `collect-datasets`, `create-atlas`, `harmonize-datasets`, and `resume`;
success returns `0`, parser errors terminate with argparse status `2`, and
workflow exceptions propagate. Complete flags are in the
[README CLI guide](../README.md#cli-guide). Each
[`run_*.py`](../README.md#workflow-scripts) `main(argv=None) -> int` is a
supported direct script interface with its own parser and fixed output policy.

### Formal exports

The following table is exhaustive across live package `__all__` declarations.
All mutable results are newly assembled lists/mappings unless the row says
otherwise.

| Qualified export | Constructor/value and public contract |
| --- | --- |
| [`ThematicAtlases.domain`](../src/ThematicAtlases/domain.py) | Formally exports the `AtlasDocument` v1 type family and enums through its `__all__`. The codec accepts a mapping or UTF-8 JSON path and returns frozen typed values; validation failures raise `ValueError`; `dump` creates parents and atomically replaces deterministic JSON. [`tests/fixtures/contracts/atlas-document-v1.json`](../tests/fixtures/contracts/atlas-document-v1.json) is the owner-produced downstream wire-contract fixture. |
| [`ThematicAtlases.application.AtlasDocumentService`](../src/ThematicAtlases/application/atlas_documents.py) | `(*, adapter=None, publisher=None)`; `assemble(...) -> AtlasDocument`, `to_legacy(document) -> dict`, `summary(document, atlas_path, *, unsupported_accessions_report=None, unsupported_accessions_path=None) -> dict`, `publish(document, out, *, include_summary, unsupported_accessions_report=None, unsupported_accessions_path=None) -> dict`, and `publish_unsupported_accessions(report, out) -> None`. Validation and publication errors propagate; bundle rollback belongs to its publisher port. |
| [`ThematicAtlases.unsupported_accessions`](../src/ThematicAtlases/unsupported_accessions.py) | Formally exports report schema version `1.0`, `is_unsupported_accession(record)`, `partition_unsupported_accessions(records)`, and `build_unsupported_accessions_report(records, *, atlas_id, run_id)`. The report keeps sanitized discovery/publication attribution and aggregate repository counts outside Atlas v1. |
| [`ThematicAtlases.ports`](../src/ThematicAtlases/ports/__init__.py) | Formally exports runtime-checkable `CollectorPort`, `FiltererPort`, `HarmonizerPort`, and `ArtifactPublisherPort`. They specify callable inputs/outputs for injected application collaborators; concrete exceptions and side effects remain owned by each implementation. |
| [`ThematicAtlases.run_store.AtlasRunStore`](../src/ThematicAtlases/run_store.py) and [`IncompatibleRunStoreError`](../src/ThematicAtlases/run_store.py) | Formally exported normalized Atlas v1 lifecycle/artifact store and fail-closed compatibility exception. Constructor accepts a path plus optional `event_emitter`, creates SQL schema version 2 for a new database, and rejects legacy/foreign/newer state. SQLite remains event authority; an emitter receives the same redacted event only after commit. Public methods are inventoried under supported helpers below. |
| [`ThematicAtlases.infrastructure.RequestPolicy`](../src/ThematicAtlases/infrastructure/http.py) | `(*, timeout=30, max_retries=3, retry_statuses={429,500,502,503,504}, request_get=None, sleep=time.sleep, logger=None, name="HTTP")`; `get(url, *, params=None, retry_exceptions=False, raise_for_status=True) -> Response`. Retries are bounded, honor numeric `Retry-After`, otherwise use capped exponential delay, and propagate terminal request/status failures according to caller policy. |
| [`ThematicAtlases.artifact_publisher.JsonArtifactBundlePublisher`](../src/ThematicAtlases/artifact_publisher.py), [`PublishedArtifactBundle`](../src/ThematicAtlases/artifact_publisher.py), [`resolve_current_bundle`](../src/ThematicAtlases/artifact_publisher.py), and [`ArtifactRollbackError`](../src/ThematicAtlases/artifact_publisher.py) | Formally exported immutable-generation publication boundary, verified resolver, and recovery-specific double-failure exception. `publish` makes one fsynced manifest pointer authoritative while maintaining direct compatibility views; failed restoration exposes the publication error, recovery errors, and preserved recovery paths. |
| [`ThematicAtlases.collector.AtlasCollector`](../src/ThematicAtlases/collector/collector.py) | `(epmc_wrapper_factory=None, metadata_handlers=None, metadata_repositories=None, metadata_resume_orchestrator_factory=None)`. `collect_jsons(query=None, file=None, out=None, metadata_repositories=None, max_publications=None, max_publications_per_query=None, collect_metadata=True, checkpoint_store=None, scrape_fulltext_accessions=True) -> list[dict]`; `filter_accessions`, `is_handled_accession`, `collect_accession_metadata`, `available_accession_metadata`, `metadata_repository`, and `metadata_handler(repository: str) -> Any` expose typed routing boundaries. Unsupported repositories and malformed files raise; remote item outcomes are represented/checkpointed where supported; `out` writes JSON. |
| [`ThematicAtlases.collector.TraceMetadataResumer`](../src/ThematicAtlases/collector/resume.py) | `(collector_factory=None, epmc_wrapper_factory=None)`; `resume(trace_dir, *, audit_enrichment_only=False, retry_tags=None) -> dict`. Reads manifest/SQLite, writes progress or audit/template artifacts, performs network metadata work unless audit-only, and rejects malformed manifests or conflicting retry tags. |
| [`ThematicAtlases.filterer.ACCESSIONS`](../src/ThematicAtlases/filterer/review.py) | `"accessions"` atlas key. |
| [`ThematicAtlases.filterer.AGENTIC_CURATOR`](../src/ThematicAtlases/filterer/review.py) | `"agentic_curator"` review-payload key. |
| [`ThematicAtlases.filterer.PUBLICATIONS`](../src/ThematicAtlases/filterer/review.py) | `"publications"` record key. |
| [`ThematicAtlases.filterer.PUBLICATION_TEXTS`](../src/ThematicAtlases/filterer/review.py) | `"publication_texts"` shared-map key. |
| [`ThematicAtlases.filterer.PUBLICATION_TEXT_REF`](../src/ThematicAtlases/filterer/review.py) | `"publication_text_ref"` foreign-key field. |
| [`ThematicAtlases.filterer.REVIEW_FILTERS`](../src/ThematicAtlases/filterer/review.py) | Mutable set `{"none", "not_relevant", "not_relevant_and_unsure"}`; callers should treat it as a supported-value registry, not mutate it. |
| [`ThematicAtlases.filterer.AtlasFilterer`](../src/ThematicAtlases/filterer/filterer.py) | `(epmc_wrapper_factory=None, publication_text_reviewer=None)`. `filter_jsons(jsons=None, file=None, theme=None, review_filter="none", review_strategy="direct", reviewer=None, ...) -> dict`; public helpers map identities/text references, split/assemble atlas parts, collect text, and review/filter. Bad JSON, invalid review controls, and uncaught text-fetch errors raise; review failures are retained as failed judgement payloads. |
| [`ThematicAtlases.filterer.PublicationTextReviewer`](../src/ThematicAtlases/filterer/review.py) | `(reviewer_factory=None, resume_orchestrator_factory=None)`. `resume(trace_dir, *, theme=None, reviewer=None, strategy="direct", allow_theme_override=False) -> dict`; `review_and_filter`, `review_publication_texts`, context/normalization/filter helpers. Calls upstream `ThematicReviewer.review_relevancy`; per-item exceptions become failed review payloads/checkpoints, while invalid theme/filter/strategy raises. |
| [`ThematicAtlases.harmonizer.AtlasHarmonizer`](../src/ThematicAtlases/harmonizer/harmonizer.py) | `(ontology_harmonizer=None, ontology_harmonizer_factory=None, ontostore=None, credential_checker=None, max_workers=1)`. `harmonize_datasets(datasets, details_out=None, harmonization_options=None, checkpoint_store=None) -> tuple[dict, list[dict]]`; `publication_context` and `harmonize_jsons` are public. Invalid worker/options or required credentials raise; caught item failures preserve input metadata; details may be written. |
| [`ThematicAtlases.wrappers.ArrayExpressWrapper`](../src/ThematicAtlases/wrappers/ae.py) | Declares `metadata_handler_status="unsupported"`; its unimplemented `collect_accession_metadata(jsons, checkpoint_store=None)` remains a fail-fast guard but normal collector routing never calls it. Callers may inject a supported handler through `AtlasCollector(metadata_handlers=...)`. |
| [`ThematicAtlases.wrappers.EuropePMCWrapper`](../src/ThematicAtlases/wrappers/epmc.py) | `(page_limit=5, page_size=1000, timeout=30, request_delay=0.5, max_retries=3, request_policy=None)`. `collect_accessions`, `collect_publications`, `collect_publication_texts`, `collect_datalinks`, `accessions_from_datalinks`, and `publication_text_sections` return normalized lists/maps. Calls Europe PMC search/datalinks/full-text endpoints and official bioRxiv/medRxiv details/JATS endpoints; scans visible text plus hidden curated JATS links, uses abstract fallback, versions text/discovery checkpoints, and checkpoints item outcomes. |
| [`ThematicAtlases.wrappers.GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py) | `(api_key=None, tool="ThematicAtlases", email=None, timeout=30, request_delay=0.34, max_retries=3, request_policy=None)`. `collect_accession_metadata(jsons, checkpoint_store=None, retry_tags=None) -> list[dict]`, `available_accession_metadata`, and `get_gse`. Calls NCBI E-utilities through the injected/shared policy and delegates MINiML/PubMed/SRA/ENA handlers; normalizes to GSE, drops unresolved/GPL-only records, deduplicates, and represents metadata errors/status. |
| [`benchmark_ThematicAtlases.ThematicReviewerBenchmark`](../src/benchmark_ThematicAtlases/thematic_reviewer/benchmark.py) | `benchmark_reference_publication_recall(*, reference_set=None, reference_set_file=None, thematic_output) -> dict`; `available_reference_sets() -> tuple[str, ...]`; `load_reference_set(name) -> dict`. Reads package/file/trace JSON only, writes nothing, requires exactly one reference source, and raises on malformed or ambiguous reference identities. The identical class is formally re-exported as `benchmark_ThematicAtlases.thematic_reviewer.ThematicReviewerBenchmark`. |

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
  review_strategy="direct", reviewer=None, _review_progress_callback=None,
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
  progress_callback=None, checkpoint_store=None) -> tuple[list[dict], dict]`;
  `atlas_object(accessions, publication_texts) -> dict`. Underscore-prefixed
  parameters are internal continuation hooks, not supported caller controls.
- [`PublicationTextReviewer`](../src/ThematicAtlases/filterer/review.py):
  `resume(trace_dir, *, theme=None, reviewer=None, strategy="direct",
  allow_theme_override=False) -> dict`;
  `validate_options(theme, review_filter, strategy="direct") -> None`;
  `review_and_filter(accessions, publication_texts, theme, review_filter,
  reviewer=None, strategy="direct") -> tuple[list[dict], dict]`;
  `publication_review_contexts(accessions) -> dict`;
  `review_publication_texts(publication_texts, contexts, theme, reviewer=None,
  progress_callback=None, checkpoint_store=None, strategy="direct") -> dict`;
  `filtered_result(accessions, publication_texts, review_filter) -> tuple[list[dict], dict]`;
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
  scrape_fulltext_accessions=True) -> list[dict]`;
  `collect_publications(...) -> list[dict]`;
  `publication_text_sections(text) -> list[dict]`;
  `collect_publication_texts(publications, checkpoint_store=None) -> dict`;
  `collect_datalinks(publications, checkpoint_store=None) -> list[dict]`;
  `accessions_from_datalinks(datalinks) -> list[dict]`.
- [`GEOWrapper`](../src/ThematicAtlases/wrappers/geo.py):
  `collect_accession_metadata(jsons, checkpoint_store=None,
  retry_tags=None) -> list[dict]`;
  `available_accession_metadata(jsons, checkpoint_store) -> list[dict]`;
  `get_gse(accession) -> str | None`.
- [`ThematicReviewerBenchmark`](../src/benchmark_ThematicAtlases/thematic_reviewer/benchmark.py):
  `benchmark_reference_publication_recall(*, reference_set=None,
  reference_set_file=None, thematic_output) -> dict`;
  `available_reference_sets() -> tuple[str, ...]`;
  `load_reference_set(reference_set) -> dict`.

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
- [`CheckpointStore(path)`](../src/ThematicAtlases/checkpoint.py): public
  `set_meta`, `get_meta_json`, `get_meta`, `validate_fingerprint`,
  `amend_fingerprint`, `put`, `get`, `items`, `has_retryable`,
  `has_retryable_boundary`, `history`, `request_retries`, `archive_stage`,
  `archive_items`, and `item_lock` methods own SQLite state and can raise
  `ValueError`, `RuntimeError`, filesystem, or SQLite errors without partial
  source deletion. `is_retryable_error(error) -> bool` and
  `failure_category(error) -> str` classify failures.
  The selective retry entry is `CheckpointStore.request_retries`.
- [`TracePublicationReviewResumer.resume(trace_dir, *, theme=None,
  strategy="direct", reviewer=None, allow_theme_override=False) -> dict`](../src/ThematicAtlases/filterer/resume.py)
  validates a trace, reviews the current datalink snapshot, and writes review
  progress. [`DevTraceWriter`](../src/ThematicAtlases/trace.py) exposes
  `checkpoint_store`, `existing`, `write`, and `metadata` for readable artifacts.
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
   v          v                                      handler-status route
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
atlas, summary, details, and optional trace.

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
4. It invokes the mature harmonization stage; caught item failures retain
   original metadata and become v1 diagnostics/status.
5. `AtlasDocumentAdapter` assembles and validates the final aggregate; the
   unsupported inventory is deliberately outside Atlas v1 datasets.
6. The summary includes aggregate unsupported counts. When `out` is set,
   `JsonArtifactBundlePublisher` stages and parses the Atlas plus derived summary
   and any explicitly requested detailed inventory, backs up prior files, then replaces them. A failed
   replacement restores the full prior pair or leaves no first-run artifacts.
7. A trace writes readable stage files, including
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
   `AtlasHarmonizer` validates controls and computes work keys.
3. Non-mapping/list metadata is retained with `not_run`; duplicate work keys
   share one result without changing accession order.
4. Model-enabled controls preflight credentials; invalid options or credentials
   fail the invocation before provider work.
5. Unique eligible work calls the delegated ontology harmonizer, serially or
   with bounded workers.
6. Results and details are memoized/checkpointed; caught item failures remain
   local and retain original metadata. The adapter retains every provider
   target that has a usable metadata path, including unmatched targets, and
   attaches an ontology match only when the provider supplied a complete
   label/accession/framework identity. It then validates the returned v1
   document. Requested details-file errors propagate.

#### Pseudocode

```text
Atlas.harmonize_datasets(datasets)              # interface
  -> AtlasDocument.from_mapping                 # strict v1 validation
  -> AtlasDocumentAdapter.to_legacy             # internal projection
  -> AtlasHarmonizer.harmonize_datasets         # internal call
     -> ontology_harmonizer.harmonize           # external package/API calls
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

Resume validates a traced run, optionally requeues selected failure boundaries,
then continues at the newest reusable checkpoint.

```text
select trace -> validate fingerprint -> retry request?
       |                 |                    |
   none/error      mismatch/error      invalid selection/error
                                             |
                                      archive selected rows
                                             |
                              final? reuse : continue missing stages
                                             |
                                  retryable failure remains resumable
```

#### Numbered stages

1. CLI retry flags become stage/item/degraded-stage selections.
2. `Atlas.resume` selects an explicit or newest incomplete trace and requires a
   compatible authoritative `atlas_run.sqlite3` before it validates the
   manifest/item-cache fingerprint; missing, ambiguous, legacy, or incompatible
   state raises without silent migration.
3. `CheckpointStore.request_retries` validates requested boundaries and
   archives selected rows; invalid stages/items leave live rows unchanged.
4. Resume reconstructs completed search, datalink, text, metadata, review, and
   harmonization boundaries and invokes only missing/requeued work. The traced
   unsupported inventory is reused for summaries and optional publication but
   never re-enters review, metadata, or harmonization.
5. A reusable internal result is converted to Atlas v1 and returned/published
   immediately. Collection-only publication registers `collection_snapshot`;
   complete publication registers `final_atlas`. Retryable item failures remain
   resumable; terminal outcomes are reused unless explicitly selected.

#### Pseudocode

```text
thematic-atlas resume(args)                     # interface
  -> Atlas.resume(...)                          # orchestrator
     -> AtlasRunStore lifecycle/artifact calls  # authoritative persistence
     -> CheckpointStore.request_retries         # persistence call, optional
     -> CheckpointStore.get/items               # persistence calls
     -> collection/review/harmonization         # internal calls as needed
     -> AtlasDocumentAdapter + bundle publisher # output boundary
  <- resumed Atlas v1 or validation error
```

#### Evidence

Definitions/calls:
[`cli_atlas.main`](../src/ThematicAtlases/cli_atlas.py),
[`Atlas.resume`](../src/ThematicAtlases/atlas.py), and
[`CheckpointStore.request_retries`](../src/ThematicAtlases/checkpoint.py).

<a id="workflow-query-amendment-and-archive"></a>
### Workflow 5: Query amendment and whole-run archive

Amendment changes one trace's query contract without deleting item checkpoints;
whole-run archival safely relocates inactive traces and fixed artifacts.

```text
amend -> validate aligned query limits -> archive fingerprint -> install new
  \-> unchanged normalized configuration -----------------------> no-op/current
archive run -> exclusive lock -> checkpoint -> snapshot/copy/resnapshot
  -> matching durable checksums -> publish -> delete source
  \-> busy/WAL/mutation/symlink/collision => error, keep source
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
rerunning discovery and may safely coexist with a cooperating collector.

```text
trace -> manifest/fingerprint validation -> publication snapshot
   |                                               |
 invalid/error                              review missing items
                                              | model error
                                              v
                                      failed payload/checkpoint
                                                   |
                                      progress + reviewed datasets
```

#### Numbered stages

1. A Python caller supplies a trace and review options to
   `PublicationTextReviewer.resume`.
2. `PublicationTextReviewer.resume` uses `TracePublicationReviewResumer`, which
   validates the manifest/theme and rebuilds a stable current datalink snapshot.
3. The filterer fetches/reuses text and constructs accession/metadata context.
4. `PublicationTextReviewer.review_publication_texts` calls the injected
   reviewer's `review_relevancy`; item locks prevent duplicate completion.
5. Model exceptions become retryable/terminal failed review payloads rather
   than aborting unrelated publications. Progress is written after each item;
   missing theme or forbidden override raises before review.

#### Pseudocode

```text
PublicationTextReviewer.resume                  # Python interface
  -> TracePublicationReviewResumer.resume       # internal orchestrator
  -> PublicationTextReviewer dispatch
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
5. A repeated identical tag is idempotent; a reused tag ID with different
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
   benchmark package, and both packaged reference sets remain tracked.
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

Offline recall compares saved outputs with packaged or custom references
through the importable benchmark API.

```text
saved atlas/trace -> normalize identities -> exact DOI/PMID match -> report
      | malformed/ambiguous -------------------------------> error
```

#### Numbered stages

1. `ThematicReviewerBenchmark` validates one reference source and saved output.
2. Exact normalized DOI/PMID identities produce matched, missed, or conflict
   rows; malformed or ambiguous reference data raises.
3. `benchmark_reference_publication_recall` performs the pure offline
   comparison and returns a schema `1.0` report.
4. Callers may iterate `available_reference_sets()` or provide one validated
   custom reference-set file.

#### Pseudocode

```text
ThematicReviewerBenchmark                       # Python interface
  -> load_reference_set/output                  # package/file reads
  -> benchmark_reference_publication_recall     # internal pure comparison
  <- schema 1.0 report
```

#### Evidence

Definitions/calls:
[`ThematicReviewerBenchmark`](../src/benchmark_ThematicAtlases/thematic_reviewer/benchmark.py)
and
[`load_reference_set`](../src/benchmark_ThematicAtlases/thematic_reviewer/benchmark.py).

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
    └── geo.py

src/benchmark_ThematicAtlases/
├── __init__.py
├── ontology_harmonizer/
│   └── __init__.py
└── thematic_reviewer/
    ├── __init__.py
    ├── benchmark.py
    └── data/*.json
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
tests/fixtures/benchmark/*.json
```

Ignored runtime directories such as `.env/`, `.out/`, caches, and trace output
are not part of the tracked source tree.

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Version metadata is `1.0.0`, matching the initial Atlas document release.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies contain independently installable
  `agentic-curator>=1,<2`, `google-auth>=2,<3`,
  `meta-standards-converter>=1,<2`, and `requests>=2.31,<3`. MSC 1 supplies
  canonical H5AD metadata schema 1.0 while retaining the public GEO conversion
  interfaces used by this repository. No build or
  runtime dependency resolves through a sibling checkout or Git URL.
- The `dev` optional dependency group contains `pytest>=8`.
- The public wire contract is Atlas document schema 1.0 and downstream H5AD projection uses H5AD metadata schema 1.0. The internal run-store SQL migration number is independently `2`; it is not an Atlas document version.
- `requirements.txt` delegates to the runtime project metadata with `-e .`; install it with `python3 -m pip install -r requirements.txt`. Development and test environments use `python3 -m pip install -e ".[dev]"`. The canonical test command is `.env/bin/python -m pytest -q`; the autouse test guard blocks sockets and HTTP transports. Only marked tests physically under `tests/live_api` may enable a fixed-host, bounded transport when `RUN_LIVE_API_TESTS=1`. Subprocess creation remains blocked unless a test declares `allow_subprocess`. On 2026-08-03 this deterministic gate reported `441 passed, 4 skipped`.

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
`__version__ == "1.0.0"`. Application and domain imports remain explicit, for
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

`src/benchmark_ThematicAtlases/` is a sibling import package in the existing `ThematicAtlases` distribution. Benchmark implementations are separated by concern: `thematic_reviewer/` contains publication-discovery and curation benchmarks, while `ontology_harmonizer/` is the reserved namespace for future ontology-harmonization benchmarks. `ThematicReviewerBenchmark` remains exported from the package root and its subpackage.

`load_reference_set(name)` is the public loader for validated packaged reference
data. It returns a defensive copy so callers can build network-resolution or
review workflows without mutating package state.

The named reference-publication recall workflow loads a version-controlled reference set from the thematic-reviewer package data and compares it with thematic-review output:

```python
from benchmark_ThematicAtlases import ThematicReviewerBenchmark

report = ThematicReviewerBenchmark().benchmark_reference_publication_recall(
    reference_set="leonie_2026_fibrosis",
    thematic_output=atlas_dict_or_json_path_or_trace_directory,
)
```

Two named sets are packaged: `leonie_2026_fibrosis` contains the Küchenhoff et al. 2026 source meta-study plus references 15-34 (21 targets), and `taylor_2020_nafld_fibrosis` contains the Taylor et al. 2020 NAFLD systematic review plus references 18-31 (15 targets). Each ordered publication records its source relationship, DOI, title, authors as cited, journal, year, and citation. `ThematicReviewerBenchmark.available_reference_sets()` returns packaged names in execution order. New collections are added as packaged JSON files and registered by stable name; setuptools includes `data/*.json` in distributions.

Each reference requires a DOI, PMID, or both; other fields are preserved in the per-publication report. DOI and PMID matching is normalized, offline, and exact. Duplicate reference rows and repeated publications across accessions collapse into single publication identities. If a reference DOI and PMID resolve to different thematic publications, the row is reported as a conflict rather than matched arbitrarily. Unknown names fail with available names. Callers select exactly one packaged `reference_set` or `reference_set_file`; custom files use the same single-set schema and are validated before benchmarking.

The method accepts an atlas-shaped mapping, an explicit JSON path, or a development-trace directory. Trace loading prefers `resume_review_progress.json`, then `02_reviewed_datasets.json`, then `06_final_atlas.json`. The pre-filter progress artifact gives the strongest discovery-recall evidence. Reports from post-filter or unknown-stage data carry an explicit limitation because removed publications cannot be distinguished from publications that were never discovered.

Schema `1.0` reports contain the benchmark method and reference-set provenance, thematic-output provenance, unique-reference and duplicate counts, matched/missed/conflict counts, discovery recall, review completion/failure counts, normalized judgement counts, relevant recall, relevant-or-unsure candidate recall, and one detailed row per unique reference. The benchmark makes no network calls and has no DOI/PMID resolution service or additional dependency.

Callers that need an aggregate report can iterate
`ThematicReviewerBenchmark.available_reference_sets()`, call the benchmark
method for each set, and persist the returned mappings in their own application
boundary. The benchmark package itself remains deliberately offline and does
not own a live reference-resolution workflow.

`tests/fixtures/benchmark/` contains complete mixed input/output examples for both sets. The Leonie fixture records a complete 21-row report with 6 matches and 15 misses; the Taylor fixture records a complete 15-row report with 6 matches and 9 misses. Both cover relevant, unsure, not-relevant, failed, unreviewed, and repeated-accession behavior. End-to-end method tests substitute only the machine-specific artifact path, independently verify summaries, then compare entire reports exactly.

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
- `benchmark_ThematicAtlases` remains importable, with the Leonie and Taylor
  packaged reference sets and their fixtures/tests.
- `PublicationTextReviewer.resume`, `AtlasCollector.resume_metadata`, and
  `ThematicReviewerBenchmark` remain available to Python callers.

<a id="atlas-workflow"></a>
### Atlas Workflow

`class Atlas` is the workflow orchestrator currently used by the CLI. It keeps the public workflow surface in one root object while delegating implementation details to component packages: `ThematicAtlases.collector.AtlasCollector`, `ThematicAtlases.filterer.AtlasFilterer`, and `ThematicAtlases.harmonizer.AtlasHarmonizer`.

Public methods:

- `__init__(metadata: dict, ..., harmonizer=None, ontostore=None, cache_ontologies=False, query_generator=None, credential_checker=None, document_adapter=None, artifact_publisher=None)`: wires component instances, one optional shared ontology store, eager-cache policy, query-generation/credential-preflight dependencies, the v1 boundary adapter, and the rollback-safe publisher.
- `create_atlas(..., theme, review_strategy="direct", dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=True, max_generated_queries=3, harmonization_options=None, review_before_metadata=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None, thematic_review=True)`: requires a nonblank theme, defaults query generation and thematic review on independently, runs collection/filtering and harmonization, returns Atlas v1, publishes the v1 document and derived summary as one bundle beside `out`, optionally publishes a separate unsupported inventory, and can write an opt-in trace bundle.
- `_dev_run_id()` is internal run allocation policy. It returns
  `YYYYMMDDTHHMMSSffffffZ-xxxxxxxx`, combining UTC microseconds and 32 random
  bits so trace directories are sortable and collision-resistant.
- `resume(dev_out_dir=".dev", run_id=None, out=None, stop_before_review=False)`: resumes an explicit trace or the newest incomplete valid trace from its latest atomic checkpoint. It reuses collected accessions, per-publication review progress, reviewed datasets, per-dataset harmonizations, or the final atlas without repeating completed work; transient checkpoint errors are retried. `stop_before_review=True` overrides an older combined-workflow manifest and returns after accession and publication-text collection without reading or modifying thematic-review rows.
- `amend_queries(dev_out_dir, run_id, queries, max_publications_per_query)`: explicitly replaces an existing trace's query configuration while atomically archiving its prior fingerprint and writing a readable query archive. Existing item checkpoints remain live, and repeating the same amendment is idempotent.
- `archive_existing_runs(dev_out_dir, archive_root, workflow, artifact_paths=())`: archives every inactive trace under one workflow root, attaches fixed artifacts to the newest trace, verifies the copy, and returns the ordered archive paths. It is a no-op when neither traces nor artifacts exist, refuses unsafe workflow names, symlinks, active workflows, and destination collisions, and never overwrites an archive.
- `collect_datasets(..., max_publications=None, max_publications_per_query=None, review_strategy="direct", generate_queries=False, max_generated_queries=3, dev_trace=False, dev_out_dir=".dev", run_id=None, review_before_metadata=False, stop_before_review=False, scrape_fulltext_accessions=True, unsupported_accessions_out=None)`: owns explicit/file/generated query ordering and validation before collection, metadata enrichment, text mapping, and optional thematic review, then returns Atlas v1 with run status `running`. Full-text and curated-link discovery are on by default. Unsupported handler statuses are partitioned before review and can be written to the explicit sidecar. With review-before-metadata enabled, supported repository accessions are reviewed without metadata, filtered, and only survivors are enriched. `stop_before_review=True` defers review and metadata. A traced public collection writes `collection_snapshot.json`, never a final-atlas role.
- `harmonize_datasets(datasets, harmonization_details_out=None, harmonization_options=None)`: requires an Atlas v1 mapping, delegates its projected metadata to `AtlasHarmonizer`, returns validated Atlas v1, and optionally writes a details sidecar. Legacy unversioned mappings fail closed.

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
- Call `EuropePMCWrapper.collect_accessions(queries=..., max_publications=..., max_publications_per_query=...)`.
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
  metadata checkpoints store provenance-independent packages; reuse rebuilds
  records from the latest accession snapshot so later publication links are not
  lost. Legacy record-shaped checkpoint payloads remain readable.
- Default ArrayExpress metadata collection remains unimplemented, but its
  handler status prevents invocation. Discovered records are preserved in the
  unsupported inventory with `accession_metadata: null`; applications can
  inject a handler whose status is `supported` to enable normal processing.

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
- `PublicationTextReviewer.resume(trace_dir, theme=None, reviewer=None, strategy="direct", allow_theme_override=False)` delegates to the injectable `TracePublicationReviewResumer`. It snapshots completed `datalinks` checkpoint rows from an active trace, reconstructs and repository-filters accessions, collects missing publication text, reviews unique texts, atomically writes `resume_review_progress.json`, and returns that unfiltered atlas-shaped snapshot. Repeated calls discover newly checkpointed datalinks and reuse completed text/review items for the selected strategy.
- The trace resumer uses the manifest theme and repository selection by default. An explicit non-empty theme is allowed when the manifest has none; a conflicting theme is rejected unless `allow_theme_override=True`. The reviewer-only override uses the explicit theme without modifying the historical collector manifest or fingerprint. Only `available` datalink items present when the call begins belong to that invocation, so the method does not poll or wait for collection completion.
- When `theme` is provided, `PublicationTextReviewer.review_publication_texts(...)` reviews each `publication_texts` entry with `agentic_curator.ThematicReviewer.review_relevancy(...)`. The reviewer receives `publication_texts[ref]["text"]`, not `accessions[].publications[].abstractText` directly, plus the title and every distinct associated GSE accession. When metadata exists, context contains one compact `build_miniml_metadata_context(...)` entry per associated accession; full MINiML, protocol, platform, and author sections are not sent. Original `accession_metadata` remains unchanged in atlas and trace artifacts.
- Collected accession JSONs keep Europe PMC abstracts at `accessions[].publications[].abstractText`. During filtering, publication text enrichment promotes either full text or abstract fallback into `publication_texts[ref]["text"]`.
- Publication text source values distinguish the fallback path: fullTextXML success stores `text_source="fullTextXML"`; full text unavailable or failed with a non-empty abstract stores `text_source="abstractText"`; full text and abstract both missing or empty stores `text=""` and `text_source="none"`.
- `review_strategy="direct"` is the default and makes one structured call over the whole publication. Agentic Curator revision 1 derives a shared catalog of 1–12 generic criteria from the non-empty theme, requires exactly one complete assessment per supplied GSE, and returns model-authored accession and publication decisions. `evidence_then_judgement` preserves the prior two-call evidence extraction followed by judgement as an explicit legacy strategy.
- Direct output is stored under `publication_texts[ref]["agentic_curator"]` with `theme`, `strategy`, `review_revision`, `criteria`, `judgement`, `reasoning`, `confidence`, `accession_assessments`, derived `accessions_to_remove`, and `raw_review`. The model owns `qualifies`/`exclude`/`uncertain` and publication relevance decisions; agentic-curator derives removals only from `exclude`. Removal suggestions remain trace-only: publication-level `review_filter` does not apply them. The canonical Atlas v1 projection remains unchanged and exposes its existing publication-level `thematic_relevance` criterion rather than the per-accession catalog.
- The complete available publication remains the primary context. When accession metadata was collected first, each GSE additionally receives its own compact, at-most-500-character MINiML context. Full MINiML, author, protocol, and platform content is not sent, and absent metadata is represented by no compact context rather than inferred accession knowledge.
- Existing `agentic_curator` reviews are reused only when their effective input matches. Review identity includes contract version, strategy, theme, publication text, title, associated accessions, compact metadata context, and metadata coverage. Contract version 5 invalidates revision-2 fibrosis-shaped direct checkpoints; a change to any review input triggers a new review.
- Incremental reviewer snapshots overlay completed metadata checkpoints without
  waiting for missing metadata. Reviews store `metadata_context` with used and
  non-used accessions plus per-accession status. Contract version 5 includes the
  compact metadata context and its coverage in the effective input hash, so
  metadata arriving after an early review triggers a replacement review on the
  next reviewer or full-resume invocation. The raw MINiML object is not sent.
- Each thematic review is checkpointed atomically under `thematic_review/<strategy>:<publication_ref>`. Direct and legacy strategies resume independently. Per-item locks prevent duplicate calls. Invalid structured output gets one immediate correction attempt and then becomes terminal; transient provider/network failures become `retryable_error` and participate in full Atlas resume gates.
- `PublicationTextReviewer.resume` reviews one stable datalink snapshot and can
  be invoked again as collection advances. A caller must explicitly allow a
  theme override when reviewing a historical collector snapshot with a newer
  theme.
- `review_filter` accepts `none`, `not_relevant`, and `not_relevant_and_unsure`. Filtering uses the judge-level `agentic_curator.judgement`, treating underscores and case differences as equivalent. `not_relevant` removes judgement `not relevant`; `not_relevant_and_unsure` removes `not relevant` and `unsure`.
- When thematic review is active, accessions with no retained publications are dropped and `publication_texts` is pruned to refs used by returned accessions. When no theme is supplied, existing unreferenced `publication_texts` are preserved for backward compatibility.
- `review_filter != "none"` without a `theme` raises `ValueError`.
- Raw unselected datalinks are not preserved by the collection stage.

<a id="harmonizer"></a>
### Harmonizer

`ThematicAtlases.harmonizer.AtlasHarmonizer` accepts an optional shared
`ontostore`, iterates atlas accessions, builds ordered publication context from
non-empty publication titles and abstracts, and calls
`agentic_curator.OntologyHarmonizer.harmonize_miniml_json(...)` for dictionary
or list `accession_metadata`. Its lazily created default harmonizer receives
that same store.

An injected `OntoStore` may configure ordered runtime-only
`preferred_ontology_ids`. These preferences do not restrict local, semantic, or
OLS retrieval. Instead, the local/RAG shared judge and the OLS judge receive
the ordered IDs plus up to two reserved candidates per preferred ontology
within their existing pool sizes. The preference is advisory and is not passed
to target checking or field assignment. OLS still makes exactly one
unrestricted request, regardless of a target's existing ontology ID.

The optional target checker can return `prunes` alongside `additions`. Only
high-confidence prunes of known, unique targets are applied. Pruned targets are
omitted from lookup and field assignment but remain unchanged in the raw
MINiML input and are recorded with their evidence in the target-check trace.
Rejected medium-confidence, unknown, or ambiguous prune requests are also
retained in that trace for auditability.

A successful call replaces `accession_metadata` with the returned
`miniml_json` and sets `ontology_harmonization_run_status="completed"`. This
means the workflow completed; it does not claim that every target matched.
Null or unsupported metadata is retained with `not_run`. Exceptions are
isolated per accession: original metadata is retained with run status `error`
and `ontology_harmonization_error`, then later accessions continue. The summary
aggregates these values under `harmonization_run_statuses`.

Completed accessions additionally expose
`ontology_harmonization_quality_status="healthy"|"degraded"`. Target-checker
and field-assignment invalid-output fallbacks are degraded available outcomes;
provider failures propagate for retry classification. Details and summaries
include the same quality signal.

The upstream ontology path is fixed:

1. local exact lookup, then FTS5;
2. semantic lookup across locally cached ontology frameworks;
3. unrestricted OLS when semantic lookup misses;
4. selected-term title promotion to `hz_label`;
5. field registry lookup or LLM field assignment using the harmonized label.

Semantic lookup embeds one ontology term per chunk with Gemini and retrieves
cosine-nearest neighbours from persistent USearch partitions. It never downloads
a missing local framework. OLS is the only external ontology search; no grounded
web search or prior LLM framework-selection call occurs.

Every available local, semantic, or OLS candidate set is judged when its
stage-specific judge is enabled. With `direct_lookup_judge=False`, only one
unique exact identity is accepted; ambiguous exact and FTS candidates remain
unjudged evidence. `rag_lookup` and `ols_lookup` independently control
retrieval, while their judge switches independently control selection. An
unjudged RAG or OLS candidate list is trace-only and the first result is never
automatically applied. `no_match` rejects that stage's candidates and continues
to the next stage. `false` terminally skips a non-harmonizable target, records
`harmonization_status="skipped"` plus `harmonization_skip`, and bypasses later
search, label, field, and MINiML application. The OLS judge receives a neutral
candidate section and no restricted/unrestricted stage literal.

Field harmonization runs after label resolution. A selected canonical term title
replaces `hz_label` and is supplied to field lookup/assignment together with
the original `pre_hz_label`. If no term matches, field harmonization uses the
normalized input label; terminal skips are the exception.

The details sidecar records targets, `workflow`, effective `controls`, paths,
`run_status`, errors, and configured `preferred_ontology_ids` by `datalink_id`.
The current upstream wrapper reports `workflow="local_rag_ols"`. Per-run
`harmonization_options` such as `target_paths`, `target_checker`,
`direct_lookup_judge`, `rag_lookup`, `rag_lookup_judge`, `ols_lookup`,
`ols_lookup_judge`, and `field_assignment_judge` are forwarded unchanged.
The removed `llm`, `lookup_llm_judge`, and `search_llm_judge` keys fail fast
before metadata iteration or upstream harmonizer construction.

Identical metadata/context/options/preferences are memoized within a run.
Configured preferred ontology IDs, including their order, participate in the
work key so changing preferences invalidates prior harmonization checkpoints;
an empty preference list retains the legacy key shape. `max_workers=1` is the
safe default; higher values opt into bounded parallel work with stable output
order. Unsupported/empty metadata never constructs the upstream harmonizer or
performs LLM calls.

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

- `collect_accessions(queries, max_publications=None, max_publications_per_query=None, checkpoint_store=None, scrape_fulltext_accessions=True) -> list[dict]`: searches and deduplicates publications, fetches Datalinks, scans Europe PMC XML, supported preprint JATS, or abstract fallback by default, merges normalized accession records with provenance, and returns candidates before repository filtering.
- `collect_publications(queries, max_publications=None, max_publications_per_query=None) -> list[dict]`: searches Europe PMC for each query and returns normalized, cross-query-deduplicated publication rows. The per-query limit list aligns with query order; configured limits can expand pagination beyond the default five pages.
- `collect_publication_texts(publications: list[dict]) -> list[dict]`: fetches Europe PMC `fullTextXML`, then official bioRxiv/medRxiv JATS for supported preprints, and otherwise falls back to abstracts.
- `collect_datalinks(publications: list[dict]) -> list[dict]`: calls only the Europe PMC datalinks API for publication rows, flattens datalink rows internally, deduplicates by accession, and returns accession records; publication-text fetching belongs to `collect_accessions`.
- `accessions_from_fulltexts(publications, checkpoint_store=None) -> list[dict]`: extracts registry matches from available Europe PMC XML or preprint JATS with `fulltext_regex` provenance and from abstract fallback with `abstract_regex` provenance, then checkpoints each publication.
- `merge_accessions(datalink_accessions, scraped_accessions) -> list[dict]`: performs case-insensitive accession and publication merging while retaining discovery provenance.
- `publication_text_sections(text: str) -> list[dict]`: parses section-delimited publication text into ordered section dictionaries.

The wrapper uses `requests.get()` against:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/search
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML
https://api.biorxiv.org/details/{biorxiv|medrxiv}/{doi}/na/json
https://www.biorxiv.org/...source.xml
https://www.medrxiv.org/...source.xml
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

`abstractText` comes directly from the Europe PMC `/search` response for each hit. Europe PMC may omit the field or return it empty; the wrapper normalizes missing values to `abstractText=""` in collected publication provenance. This is independent of datalink collection, so a datalink JSON timeout followed by successful XML fallback can still produce accession records whose publication has an empty `abstractText`.

`collect_publications()` and `collect_datalinks()` are intermediate stages inside
`collect_accessions()`. With scraping enabled, `collect_publication_texts()` is
also called there so publications with no Datalinks can still contribute
accessions. The enriched publication rows are carried forward and reused by
`AtlasFilterer`, avoiding a second full-text request.

<a id="fulltext-accession-discovery"></a>
#### Publication-text accession discovery

The option is enabled by default across Python, the installed CLI, and fixed
fibrosis runners. `--no-scrape-fulltext-accessions` restores Datalinks-only
discovery. Resume treats a missing manifest field as the legacy disabled
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
`europe_pmc_datalink`, `fulltext_regex`, `abstract_regex`, or their applicable
combination. Each publication's normalized
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

The datalink request uses:

```text
https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks
```

with `format=json` first. If Europe PMC returns a server error or the JSON datalinks request times out, the wrapper retries the same URL without `format=json`, parses the XML Scholix response, and normalizes it to the same internal datalink shape. If JSON and XML datalink retrieval both fail for one publication, that publication is skipped, logged, and counted while collection continues for the remaining publications. The current dataset category filter keeps `GEO`, `BioProject`, `BioStudies`, `Nucleotide Sequences`, `BioStudies: supplemental material and supporting data`, and `Functional Genomics Experiments`.

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
- `timeout=30`
- `request_delay=0.5`
- `max_retries=3`

These request tuning values are stored together in an internal settings
dictionary. `EuropePMCWrapper` and `GEOWrapper` delegate GET retry mechanics to
the same injectable `RequestPolicy`; endpoint adapters retain parsing and
fallback decisions. The base delay can be overridden explicitly by a caller,
including with zero for controlled tests. Transient response statuses `429`,
`500`, `502`, `503`, and `504` are retried. Numeric `Retry-After` is honored;
otherwise retry delay uses capped exponential backoff. Pagination is
sequential, with no parallel requests.

<a id="arrayexpress-wrapper"></a>
### ArrayExpress Wrapper

`ThematicAtlases.wrappers.ae.ArrayExpressWrapper` is a supported MSC adapter.
For each normalized E-MTAB, E-GEOD, or E-MEXP accession it calls
`ae2json().convert(source=accession, out=None, sdrf_sources=None)`, so BioStudies
IDF/SDRF content remains in memory. It returns the common MINiML-compatible
package plus validated `mage_tab.model` and round-trip evidence with
`metadata_source="ae2json"`.

`arrayexpress_metadata` checkpoints store provenance-independent packages and
use item locks plus available/no-data/retryable/terminal states. Offline
availability overlays completed checkpoints without constructing a converter
or issuing network calls; current publications are rebuilt from the latest
record snapshot.

<a id="geo-wrapper"></a>
### GEO Wrapper

`ThematicAtlases.wrappers.geo.GEOWrapper` resolves GEO accessions to GEO Series accessions through NCBI E-utilities and appends parsed GEO MINiML JSON through `meta_standards_converter`. When metadata collection is enabled, `AtlasCollector.collect_jsons()` routes GEO records to it through `collect_accession_metadata()`.

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

Traced runs checkpoint source-accession-to-GSE resolution and each GSE metadata
conversion separately. Available, unavailable, and terminal parse outcomes are
reused; transient fetch/conversion failures are retried on resume.

For newly parsed GSE packages, PubMed summaries, NCBI SRA XML, and ENA FASTQ
reports are separately stored as `pubmed_enrichment/<PMID>`,
`sra_xml/<SRA accession>`, and `ena_fastq/<SRA accession>`. Each stage uses the
standard four checkpoint outcomes and a cross-process item lock. Parsed MINiML
packages are persisted in a pending version-3 `geo_metadata` payload before
enrichment begins, so interruption resumes enrichment without another MINiML
download or parse. Identifier failures leave partial GSE metadata available;
later successful retries are merged into every affected cached package.

Version-2 GSE rows remain readable and are not automatically enriched. The
audit reports all-null PubMed summaries, SRA accessions without runs, and any
SRA-linked sample with at least one run lacking FASTQ data. Only identifiers in
an explicit retry-tag file modify those legacy packages; other inferred gaps
remain untouched. Atlas records and `accession_metadata` package shapes do not
change.

<a id="cli-atlas"></a>
## CLI Atlas

`ThematicAtlases.cli_atlas` provides a standard-library `argparse` CLI with `main(argv: list[str] | None = None) -> int`.

Commands:

- `[-v | --verbose] [--log-file LOG_FILE]`
- `create-atlas [--verbose] [--log-file LOG_FILE] [--query QUERY] [--file FILE] [--query-generator|--no-query-generator] [--max-generated-queries N] [--thematic-review|--no-thematic-review] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--scrape-fulltext-accessions|--no-scrape-fulltext-accessions] [--dev-trace] [--dev-out-dir DIR] (--theme THEME|--theme-file FILE) [--review-filter MODE] [--review-strategy direct|evidence_then_judgement] [--harmonization-details-out PATH]`
- `collect-datasets [--verbose] [--log-file LOG_FILE] [--query QUERY] [--file FILE] [--query-generator] [--max-generated-queries N] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--scrape-fulltext-accessions|--no-scrape-fulltext-accessions] [--theme THEME] [--theme-file FILE] [--review-filter MODE] [--review-strategy direct|evidence_then_judgement]`
- `harmonize-datasets [--verbose] [--log-file LOG_FILE] --file INPUT --out OUTPUT [--harmonization-details-out PATH]`
- `resume [--verbose] [--log-file LOG_FILE] [--dev-out-dir DIR] [--run-id ID] [--out OUT] [--stop-before-review] [--retry-stage STAGE] [--retry-item STAGE:KEY] [--retry-degraded-stage STAGE]`

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

Each command instantiates `Atlas(metadata={})`, calls the matching method, and configures logging from CLI options. Successful commands do not print result data to stdout, though stdout may contain logs when verbose console logging is enabled. Use `--out` as the JSON result channel and logging as the stats channel.

`collect-datasets` and `create-atlas` share the mature collection and
publication-text stage components. Supplying `--theme` or `--theme-file` opts
into `agentic_curator` thematic review for each unique publication text before
review filtering. Both public commands return/write Atlas v1 through
`AtlasDocumentAdapter`. `create-atlas` then harmonizes and transactionally
publishes the requested final JSON plus automatic summary. The standalone
`harmonize-datasets` command requires Atlas v1 at `--file`, writes Atlas v1 at
`--out`, and fails closed on legacy unversioned accessions envelopes. Both harmonizing commands can write the
optional details sidecar.

`resume` selects `--run-id` or the newest incomplete v1 trace under
`--dev-out-dir` (default `.dev`), optionally writes `--out`, and
`--stop-before-review` returns the collection snapshot. Repeatable
`--retry-stage`, `--retry-item STAGE:KEY`, and `--retry-degraded-stage`
requests are validated and forwarded to `Atlas.resume`; missing
`atlas_run.sqlite3`, malformed item syntax, or unsupported selections raise
rather than migrating state or silently requeueing other work.

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

Live tests cover an offline real-component Atlas system workflow, empty and nested outputs, summaries, opt-in trace checkpoints, SQLite durability/fingerprints, selective retry atomicity, terminal/retryable harmonization reuse, archive copy/publication failures, transient SQLite-sidecar races, durable archive mutation rejection, review-before-metadata ordering/resume, evolving independent review, metadata audit artifacts, direct and legacy strategy isolation, shared-publication GSE aggregation, trace-only accession exclusions, interruption and item-level resume across Europe PMC/GEO/review/harmonization, method-owned query generation, credential preflight, repository selection, GEO filtering, ArrayExpress no-call behavior, publication review, configurable/cached/parallel ontology harmonization, CLI forwarding, Europe PMC requests/retries/text/datalinks, GEO-to-GSE resolution, and exact complete input/output comparison for the Leonie reference-publication recall benchmark. Network, HTTP/socket, subprocess, model, Docker, and nf-core effects are blocked or replaced by default.

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
