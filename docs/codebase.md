# ThematicAtlases Codebase Handoff

This document describes the current live package at the repository root. The previous implementation is archived under `oldd/` and is reference-only until behavior is deliberately ported into the live package.

The current implemented path collects Europe PMC dataset datalinks from keyword-driven publication searches:

```text
python3 -m ThematicAtlases.cli_atlas create-atlas
python3 -m ThematicAtlases.cli_atlas create-atlas --query fibrosis --out atlas.json
python3 -m ThematicAtlases.cli_atlas create-atlas --theme-file docs/theme_fibrosis.txt --query-generator --review-filter not-relevant --out atlas.json
python3 -m ThematicAtlases.cli_atlas create-atlas --query fibrosis --out atlas.json --dev-trace
.env/bin/python run_fibrosis_atlas.py
```

Use `--resume` to select the newest incomplete valid trace, or
`--resume RUN_ID` to select one explicitly. Readable JSON stage exports are
paired with a transactional `resume_state.sqlite` item store. Resume validates
the run fingerprint, reuses completed items, retries transient failures, and
skips completed collection, review, harmonization, or final output stages.

`create-atlas` is the preferred end-to-end workflow entrypoint. It collects GEO-filtered, deduplicated accession records with publication provenance and accession metadata, then runs the publication text mapping stage and writes the final atlas object when `--out` is provided.

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`ThematicAtlases` will provide tools for building thematic atlases of biomedical datasets. The live package is a fresh foundation, with only the Europe PMC publication-search path restored so far.

Live package files:

```text
src/ThematicAtlases/
├── __init__.py
├── atlas.py
├── checkpoint.py
├── cli_atlas.py
├── summary.py
├── trace.py
├── collector/
│   ├── __init__.py
│   └── collector.py
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
    ├── epmc.py
    └── geo.py

src/benchmark_ThematicAtlases/
├── __init__.py
└── thematic_reviewer.py

```

Root project files:

```text
pyproject.toml
requirements.txt
run_fibrosis_atlas.py
run_publication_reviewer.py
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
tests/test_ae_wrapper.py
tests/test_benchmark_package.py
tests/test_checkpoint.py
tests/test_cli_atlas.py
tests/test_collector.py
tests/test_epmc_wrapper.py
tests/test_filterer.py
tests/test_geo_wrapper.py
tests/test_harmonizer.py
tests/test_review.py
tests/test_run_fibrosis_atlas.py
tests/test_run_publication_reviewer.py
tests/test_summary.py
tests/test_theme_fibrosis.py
tests/test_thematic_reviewer_benchmark.py
```

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Version metadata is `0.1.0`.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies contain `agentic-curator` from `jaychowcl/agentic_curator`, `google-auth>=2,<3`, `meta-standards-converter` from `jaychowcl/meta_standards_converter`, and `requests>=2.31,<3`. The Git dependencies intentionally track their default branches.
- The `dev` optional dependency group contains `pytest>=8`.
- `requirements.txt` delegates to the runtime project metadata with `-e .`; install it with `python3 -m pip install -r requirements.txt`. Development and test environments use `python3 -m pip install -e ".[dev]"`.
- The distribution uses a `src/` layout with setuptools package discovery for both `ThematicAtlases` and `benchmark_ThematicAtlases`.
- The installed console command is `thematic-atlas`, pointing to `ThematicAtlases.cli_atlas:main`.

<a id="public-api"></a>
## Public API

`src/ThematicAtlases/__init__.py` is currently empty. It does not export `Atlas`, `ThematicAtlas`, `__version__`, or any other symbol.

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

Schema `1.1` reports contain the benchmark method and reference-set provenance, thematic-output provenance, unique-reference and duplicate counts, matched/missed/conflict counts, discovery recall, review completion/failure counts, normalized judgement counts, relevant recall, relevant-or-unsure candidate recall, and one detailed row per unique reference. The benchmark makes no network calls and has no DOI/PMID resolution service or additional dependency.

The root runner scores an existing atlas JSON or development trace against every packaged set, optionally adds repeated custom files, and writes one aggregate report without running discovery or review:

```bash
.env/bin/python run_reference_publication_recall.py \
  .out/dev_trace_discovery/<run-id> \
  --reference-set-file custom_fibrosis.json \
  --out .out/reference_publication_recall.json
```

Without `--out`, the path defaults to `.out/reference_publication_recall.json`. Aggregate schema `1.0` records the thematic input and an ordered `reports` object keyed by collection ID; each value is an unchanged schema `1.1` benchmark report. Packaged sets run first, followed by custom files in argument order. Duplicate IDs fail without writing a partial output. The runner prints its resolved configuration and per-set summaries.

`run_reference_set_review.py` is the isolated production-path diagnostic for a
named packaged set. It resolves each reference with an exact Europe PMC `DOI:`
query, rejects non-exact responses, collects datalinks only for resolved
references, retains GEO/GSE accessions, and directly reviews the linked
publication text without downloading MINiML metadata. It uses an independent
SQLite checkpoint and writes a resolution/datalink audit, accession list,
reviewer input and progress, reviewed output, benchmark, and run summary under
`.out/reference_reviews/<reference-set>/`. Rerunning the same command resumes
that isolated workflow:

```bash
.env/bin/python run_reference_set_review.py \
  --reference-set leonie_2026_fibrosis
```

`tests/fixtures/benchmark/` contains complete mixed input/output examples for both sets. The Leonie fixture records a complete 21-row report with 6 matches and 15 misses; the Taylor fixture records a complete 15-row report with 6 matches and 9 misses. Both cover relevant, unsure, not-relevant, failed, unreviewed, and repeated-accession behavior. End-to-end method tests substitute only the machine-specific artifact path, independently verify summaries, then compare entire reports exactly. A real runner integration test also verifies both packaged reports are produced together.

<a id="fibrosis-curation-theme"></a>
### Fibrosis Curation Theme

`docs/theme_fibrosis.txt` is the canonical inclusion policy for the current fibrosis atlas. It targets human bulk, single-cell, single-nucleus, and spatial transcriptomic datasets containing at least one profiled sample with established or explicitly documented fibrosis. A qualifying dataset retains its non-fibrotic controls and comparator samples.

Confirmed sample-level fibrosis supports `relevant`. Induced fibrosis without confirmation, profibrotic stimulation, fibroblast activation, extracellular-matrix remodelling, wound healing, or a fibrosis-associated disease without sample-level confirmation supports `unsure`, not direct inclusion. Animal-only, non-transcriptomic, background-only, and otherwise unlinked studies are `not relevant`.

Use `--review-filter not-relevant` with this theme so unsure candidates remain available for manual review. The same theme may be passed to `--query-generator`; its domain-neutral prompt defaults to one comprehensive query with independent mandatory concepts joined by AND and extensive within-concept synonyms joined by OR. Additional queries require an explained unbridgeable logical, semantic, syntax, or length gap. The thematic reviewer then applies the sample- and assay-level inclusion policy.

<a id="fibrosis-run-script"></a>
### Fibrosis Run Script

`run_fibrosis_atlas.py` is the fixed, repository-root entry point for the complete fibrosis workflow. Run it only with `.env/bin/python`; it prints all resolved settings before network or model work and writes every generated artifact under the ignored `.out/` directory.

The script configures the root logger at DEBUG with simultaneous stdout and
file handlers. Safe diagnostics include per-request identifiers/status/duration,
first/every-tenth/final progress for long loops, and stage summaries from all
three packages. Prompt and response bodies, publication/metadata payloads,
credentials, authorization headers, and request parameters are not logged.

The fixed configuration loads `docs/theme_fibrosis.txt`, generates up to three Europe PMC queries, searches at most 50 publications, collects GEO metadata only, retains `unsure` while filtering `not_relevant`, enables full LLM-backed web-search harmonization with one worker, writes the atlas/summary/details/log outputs, and enables the complete development trace. It creates `OntoStore(storage_dir=".out/ontology_store")`, calls `configure_framework("snomed", remove=True)`, and passes that store to `Atlas(cache_ontologies=True)`. `Atlas.create_atlas()` calls `cache_all()` before collection, aborts on any aggregate cache failure, and passes the same fully indexed store to its default ontology harmonizer. Current `agentic_curator` caching streams RDF/XML through a bounded temporary SQLite triple store into the shared index, so this run creates no new intermediate ontology JSON files; pre-existing JSON caches remain compatible.

Prepare and run it with:

```bash
python3 -m venv .env
.env/bin/python -m pip install -e ".[dev]"
gcloud auth application-default login
.env/bin/python run_fibrosis_atlas.py
```

The script requires working Google Application Default Credentials and quota. Tests replace every workflow collaborator and never launch the live Europe PMC, GEO, OLS, or LLM calls.

`run_fibrosis_discovery.py` is the collection-only companion entry point. Its
ordered, versioned defaults live in
`config/fibrosis_discovery_queries.json`; the runner validates and loads the
catalog while preserving its existing exported query constants. The four
queries are: the original
human/fibrosis/transcriptomics query, an expanded core query, a high-specificity
fibrotic-disease query, and a complementary human organ/disease query. The
original query is capped at 5,000 raw results and each new query at 15,000.
Publications are deduplicated across query sets before datalink calls while
ordered query provenance is retained. The runner
stops after incrementally collecting full text or abstracts for GEO-linked
publications. It does not invoke thematic review, download GEO MINiML metadata,
filter accessions, or harmonize. The separate `run_publication_reviewer.py`
command reviews a stable snapshot from the same trace and may run concurrently
with discovery. The query removes
generic sclerosis and remodelling-only terms, excludes reviews, and deliberately
does not exclude mouse/rat mentions because mixed-species publications can still
contain qualifying human datasets. `--generate-query` replaces the static query
with the existing LLM theme-to-query workflow. Europe PMC synonym expansion
remains enabled in both modes. The script searches up to 5,000 publications and
calls `Atlas.collect_datasets(stop_before_review=True)`. It never constructs `OntoStore`,
caches ontologies, calls `create_atlas()`, or invokes harmonization. It prints
the resolved query mode and configuration and writes
`.out/fibrosis_discovery.json`, `.out/fibrosis_discovery.summary.json`, and
`.out/fibrosis_discovery.log`.

Query amendment compares normalized whitespace as well as ordered limits. This
lets formatting-only changes in the stored catalog reuse an existing trace
without changing its fingerprint or archiving a duplicate query generation.

The discovery runner retains the fibrosis theme and direct-review configuration
in its trace for the standalone reviewer, but collection-only execution does
not preflight LLM credentials or make a judgement call. `--generate-query`
still requires credentials because query construction itself uses the LLM.
`--resume RUN_ID --amend-queries` transactionally archives the trace's previous
query fingerprint and readable manifest, installs the four-query configuration,
and resumes without deleting search, datalink, text, or review checkpoints.

Run it with:

```bash
.env/bin/python run_fibrosis_discovery.py
.env/bin/python run_fibrosis_discovery.py --generate-query
.env/bin/python run_fibrosis_discovery.py --resume
.env/bin/python run_fibrosis_discovery.py --resume RUN_ID
.env/bin/python run_fibrosis_discovery.py --resume RUN_ID --amend-queries
```

Both fibrosis scripts enable incremental SQLite checkpoints automatically.
Library callers opt in by enabling `dev_trace`; untraced calls retain the
existing in-memory behavior.

Before either fibrosis script starts a new non-resume run, it calls
`Atlas.archive_existing_runs()` before opening the new log. All valid trace
directories for that workflow and any existing fixed output, summary, details,
and log artifacts move under
`.out/previous_runs/<workflow>/<run-id>/`; fixed artifacts belong to the newest
trace and live in its `artifacts/` subdirectory. A run with artifacts but no
trace is retained as `orphan-<timestamp>`. Resume invocations never archive.
The shared `.out/ontology_store/` cache is deliberately excluded.

Collectors, resumes, and standalone reviewers hold a shared workflow activity
lock. Archiving requires the exclusive form, checkpoints and validates SQLite,
copies to hidden staging, verifies SHA-256 checksums, atomically publishes the
archive, and only then deletes the sources. Consequently a new run refuses to
archive while a cooperating collector or reviewer is active. The archived
`00_run_manifest.json` points at relocated artifacts, and the trace remains
directly resumable by using its workflow archive directory as `dev_out_dir`.

<a id="atlas-workflow"></a>
### Atlas Workflow

`class Atlas` is the workflow orchestrator currently used by the CLI. It keeps the public workflow surface in one root object while delegating implementation details to component packages: `ThematicAtlases.collector.AtlasCollector`, `ThematicAtlases.filterer.AtlasFilterer`, and `ThematicAtlases.harmonizer.AtlasHarmonizer`.

Public methods:

- `__init__(metadata: dict, ..., harmonizer=None, ontostore=None, cache_ontologies=False, query_generator=None, credential_checker=None)`: wires component instances, one optional shared ontology store, eager-cache policy, and query-generation/credential-preflight dependencies.
- `create_atlas(..., review_strategy="direct", dev_trace=False, dev_out_dir=".dev", harmonization_details_out=None, generate_queries=False, max_generated_queries=3, harmonization_options=None, review_before_metadata=False)`: optionally generates queries, runs collection/filtering and harmonization, writes/returns the final atlas, automatically writes a summary beside `out`, and can write an opt-in trace bundle.
- `resume(dev_out_dir=".dev", run_id=None, out=None, stop_before_review=False)`: resumes an explicit trace or the newest incomplete valid trace from its latest atomic checkpoint. It reuses collected accessions, per-publication review progress, reviewed datasets, per-dataset harmonizations, or the final atlas without repeating completed work; transient checkpoint errors are retried. `stop_before_review=True` overrides an older combined-workflow manifest and returns after accession and publication-text collection without reading or modifying thematic-review rows.
- `amend_queries(dev_out_dir, run_id, queries, max_publications_per_query)`: explicitly replaces an existing trace's query configuration while atomically archiving its prior fingerprint and writing a readable query archive. Existing item checkpoints remain live, and repeating the same amendment is idempotent.
- `archive_existing_runs(dev_out_dir, archive_root, workflow, artifact_paths=())`: archives every inactive trace under one workflow root, attaches fixed artifacts to the newest trace, verifies the copy, and returns the ordered archive paths. It is a no-op when neither traces nor artifacts exist, refuses unsafe workflow names, symlinks, active workflows, and destination collisions, and never overwrites an archive.
- `collect_datasets(..., max_publications=None, max_publications_per_query=None, review_strategy="direct", generate_queries=False, max_generated_queries=3, dev_trace=False, dev_out_dir=".dev", run_id=None, review_before_metadata=False, stop_before_review=False)`: owns explicit/file/generated query ordering and validation before collection, metadata enrichment, text mapping, and optional thematic review. The legacy maximum is global; an ordered per-query list permits independent result sets. With review-before-metadata enabled, repository-filtered accessions are reviewed without metadata, filtered, and only survivors are enriched. `stop_before_review=True` defers review and metadata, writes `resume_publication_collection.json`, and omits reviewed/final-atlas trace markers.
- `harmonize_datasets(datasets, harmonization_details_out=None, harmonization_options=None)`: delegates to `AtlasHarmonizer`, replaces supported metadata, and optionally writes a details sidecar.

`Atlas` no longer exposes `collect_jsons()`, `filter_jsons()`, or `harmonize_jsons()` as public methods. Helper-level behavior belongs to the component classes below.

Whole-run archives differ from checkpoint comparison archives.
`archive_existing_runs()` relocates complete resumable trace directories;
`CheckpointStore.archive_stage()` and `archive_items()` move selected checkpoint
rows to comparison databases while leaving the parent run active.

When `create_atlas(out="atlas.json")` succeeds, it also writes `atlas.summary.json` with operational counts and a deterministic scientific profile derived from MINiML samples, platforms, and characteristics. With `dev_trace=True`, `create_atlas()` or `collect_datasets()` writes a run directory under `dev_out_dir` containing `resume_state.sqlite`, a manifest, readable collection/review checkpoints, and final output/summary; full atlas traces also include pre/post harmonization metadata and target details. `CheckpointStore` uses WAL mode, full synchronous commits, a configuration fingerprint, and one row per stage/item. Statuses distinguish reusable success/no-data outcomes, non-retryable consumed-call failures, and transient failures that should be attempted again. `archive_stage(...)` transactionally moves a complete stage into comparison tables in a separate SQLite database; `archive_items(stage, item_keys, ...)` performs the same verified operation for an explicit subset. Both preserve unrelated rows/stages, reject missing selections or archive-ID reuse, and delete live rows only after archive counts match.

Review-before-metadata traces use `01_collected_accessions.json` for the raw
repository-filtered accessions, `02_reviewed_datasets.json` for pre-metadata
survivors, and `resume_metadata_enriched_datasets.json` for the enriched result.
Resume treats datalink, publication-text/review, and GEO metadata progress as
separate boundaries, so a GEO retry does not repeat successful reviews.
Collection-only traces additionally use `resume_publication_collection.json`
and its summary for the unreviewed accession/publication-text snapshot. Static
collection-only runs do not require Google credentials; generated-query runs do.

Eager ontology caching is opt-in. `Atlas(..., ontostore=store, cache_ontologies=True)` invokes `store.cache_all()` once at the beginning of the first `create_atlas()` call, before credentials, query generation, or collection. The upstream cache API directly streams OWL into SQLite, imports an existing legacy JSON cache when available, and supports selective refresh through `store.cache_all(force_frameworks=[...])`; `force=True` still refreshes all active frameworks. Its framework replacement is transactional and temporary staging databases are deleted after success or failure. The result is retained as `atlas.ontology_cache_result`; aggregate cache exceptions propagate and prevent collection. The same store is passed to the default `AtlasHarmonizer` and its lazily created `OntologyHarmonizer`. Supplying a custom harmonizer together with Atlas-managed store/cache options raises `ValueError`.

<a id="collector"></a>
### Collector

`ThematicAtlases.collector.AtlasCollector` owns accession discovery and metadata collection.

`AtlasCollector.resume_metadata(trace_dir)` delegates to `TraceMetadataResumer`
and processes one stable snapshot of the currently available datalink checkpoint
rows. It applies the trace manifest's repository selection, downloads metadata,
atomically writes the atlas-shaped `resume_metadata_progress.json`, and exits.
The root `run_accession_metadata_collector.py TRACE_DIR [-v|-vv]` command exposes
the same operation. Repeated calls discover later datalinks and reuse completed
`geo_resolution` and `geo_metadata` items without requiring LLM credentials.

Current responsibilities:

- Build query lists from repeated API/CLI query values and optional UTF-8 query files.
- Ignore blank query-file lines and lines beginning with `#`.
- Call `EuropePMCWrapper.collect_accessions(queries=..., max_publications=..., max_publications_per_query=...)`.
- Keep records handled by the selected metadata repositories. `metadata_repositories=None` means GEO-only.
- Route handled records to metadata repository handlers when metadata collection is enabled. The default registry routes `geo` to `GEOWrapper` and `arrayexpress` to `ArrayExpressWrapper`.
- Optionally write the intermediate collected accession list to `out`.
- Validate repository selections against `geo` and `arrayexpress`.

Query loading behavior:

- Repeated CLI `--query` values are preserved in order.
- `file` values are read as UTF-8 text.
- Query files ignore blank lines and lines starting with `#`.
- If neither `query` nor `file` is provided, the wrapper receives an empty query list.
- `max_publications` optionally caps searched Europe PMC publications globally across all queries before datalink fetching begins.

Repository filtering behavior:

- `filter_accessions(accessions, metadata_repositories=None)` keeps accessions handled by the selected repositories.
- `is_handled_accession(record, metadata_repositories=None)` returns true when `metadata_repository(...)` finds a selected repository.
- `collect_accession_metadata(jsons, metadata_repositories=None)` is the metadata repository routing step used after filtering.
- `collect_jsons(..., collect_metadata=False)` still loads queries, collects Europe PMC accessions, and filters to selected repositories, but skips metadata handler enrichment.
- `metadata_repository(record, metadata_repositories=None)` currently returns `geo`, `arrayexpress`, or `None`.
- `metadata_handler(repository)` uses the instance metadata handler registry.
- GEO rules: `datalink_id_scheme` equals `GEO`, case-insensitive, or `datalink_id` starts with `GSE`, `GSM`, `GPL`, or `GDS`, case-insensitive.
- ArrayExpress rules: `datalink_id_scheme` equals `ArrayExpress`, case-insensitive, or `datalink_id` starts with `E-MTAB`, `E-GEOD`, or `E-MEXP`, case-insensitive.
- GSE normalization happens inside `GEOWrapper.collect_accession_metadata()`: GSE records remain GSE, GSM/GDS records resolve to their parent GSE, and GPL or unresolved records are removed.
- Metadata repository handlers append repository metadata under each returned accession/project record. GEO stores parsed MINiML JSON in `accession_metadata`.
- Multiple filtered records resolving to the same GSE collapse into one result. The merged result keeps first-seen GSE-level top-level values, deduplicates publications, records original datalink evidence in `original_datalinks`, and keeps the first available metadata package.
- GEO resolution and metadata downloads use per-item cross-process locks. New
  metadata checkpoints store provenance-independent packages; reuse rebuilds
  records from the latest accession snapshot so later publication links are not
  lost. Legacy record-shaped checkpoint payloads remain readable.
- ArrayExpress metadata is placeholder-only for now. `ArrayExpressWrapper` preserves the input record and adds `metadata_repository="arrayexpress"`, `metadata_source="placeholder"`, `metadata_status="placeholder"`, and `accession_metadata=null`.

<a id="filterer"></a>
### Filterer

`ThematicAtlases.filterer.AtlasFilterer` owns the publication text mapping and optional thematic review stage.

Current responsibilities:

- Accept collected accession records or an atlas-shaped object with `accessions` and optional `publication_texts`.
- Optionally append records from a JSON file.
- Reuse existing publication text entries and collect only missing texts.
- Add `publication_text_ref` to nested publication metadata when text is available.
- Strip `text`, `text_source`, and `full_text_status` from nested publication metadata so full text is stored only in the shared text map.
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
- `review_strategy="direct"` is the default and makes one structured call over the whole publication. The model returns one assessment per supplied GSE covering human samples, eligible transcriptomics, established fibrosis, and explicit evidence-to-accession linkage. Each criterion is `meets`, `fails`, or `uncertain`; application code derives accession and publication decisions instead of accepting a model-authored verdict. `evidence_then_judgement` preserves the prior two-call evidence extraction followed by judgement as an explicit legacy strategy.
- Direct output is stored under `publication_texts[ref]["agentic_curator"]` with `theme`, `strategy`, `review_revision`, derived `judgement`, `reasoning`, `confidence`, `accession_assessments`, and derived `accessions_to_remove`. Missing supplied accessions become uncertain; unknown and duplicate assessments are discarded. Revision 2 treats low-confidence failures as uncertain, requires absent accession linkage to remain uncertain, and evaluates human origin and fibrosis independently. A publication is relevant when at least one supplied accession meets all criteria, not relevant when every accession has a medium/high-confidence explicit failure, and unsure otherwise. Removal suggestions remain trace-only: publication-level `review_filter` does not apply them.
- The complete available publication remains the primary context. When accession metadata was collected first, each GSE additionally receives its own compact, at-most-500-character MINiML context. Full MINiML, author, protocol, and platform content is not sent, and absent metadata is represented by no compact context rather than inferred accession knowledge.
- Existing `agentic_curator` reviews are reused only when their effective input matches. Review identity includes contract version, strategy, theme, publication text, title, associated accessions, compact metadata context, and metadata coverage. Contract version 4 invalidates earlier direct checkpoints; a change to any review input triggers a new review.
- Incremental reviewer snapshots overlay completed metadata checkpoints without
  waiting for missing metadata. Reviews store `metadata_context` with used and
  non-used accessions plus per-accession status. Contract version 4 includes the
  compact metadata context and its coverage in the effective input hash, so
  metadata arriving after an early review triggers a replacement review on the
  next reviewer or full-resume invocation. The raw MINiML object is not sent.
- Each thematic review is checkpointed atomically under `thematic_review/<strategy>:<publication_ref>`. Direct and legacy strategies resume independently. Unversioned legacy checkpoint keys remain in SQLite but are ignored, so their publications are reviewed under the new contract. Per-item locks prevent duplicate calls across processes. A publication-level exception is stored with `review_status="failed"`, retained regardless of `review_filter`, and does not stop later reviews. Invalid or truncated consumed LLM responses are not retried; Europe PMC/network fetching retains its bounded transient retry behavior.
- Root `run_publication_reviewer.py TRACE_DIR [--theme-file PATH] [--allow-theme-override] [--strategy direct|evidence_then_judgement] [-v|-vv]` checks project ADC, reviews one stable datalink snapshot, prints counts, and exits so it can be invoked again as collection advances. The override flag is required when intentionally reviewing a historical collector snapshot with a newer explicit theme.
- `review_filter` accepts `none`, `not_relevant`, and `not_relevant_and_unsure`. Filtering uses the judge-level `agentic_curator.judgement`, treating underscores and case differences as equivalent. `not_relevant` removes judgement `not relevant`; `not_relevant_and_unsure` removes `not relevant` and `unsure`.
- When thematic review is active, accessions with no retained publications are dropped and `publication_texts` is pruned to refs used by returned accessions. When no theme is supplied, existing unreferenced `publication_texts` are preserved for backward compatibility.
- `review_filter != "none"` without a `theme` raises `ValueError`.
- Raw unselected datalinks are not preserved by the collection stage.

<a id="harmonizer"></a>
### Harmonizer

`ThematicAtlases.harmonizer.AtlasHarmonizer` accepts an optional shared `ontostore`, iterates the atlas `accessions`, builds ordered publication context from each record's non-empty nested `title` and `abstractText`, and calls `agentic_curator.OntologyHarmonizer.harmonize_miniml_json(publication_context=..., miniml_json=...)` for dictionary/list `accession_metadata`. Its lazily created default `OntologyHarmonizer` receives that same store. A successful call replaces `accession_metadata` with the returned `miniml_json` and adds `ontology_harmonization_status="available"`. Null or unsupported metadata is retained with status `unavailable`. Exceptions are isolated per accession: original metadata is retained with status `error` and `ontology_harmonization_error`, and later accessions continue.

The optional details file records targets, strategy, paths, statuses, and errors by `datalink_id`. `AtlasHarmonizer(ontology_harmonizer=...)` accepts a configured upstream instance, including `OntoStore`, LLM, and request policy; per-run `harmonization_options` are forwarded unchanged. Identical metadata/context/options are memoized within a run. `max_workers=1` is the safe default and higher values opt into bounded parallel work with stable output order. Null ArrayExpress metadata never constructs the upstream harmonizer or performs LLM calls.

With a checkpoint store, each unique metadata/context/options work key is
committed immediately after harmonization. Successful outcomes and terminal
consumed-call failures are reused; transient provider/network errors are retried
on resume. One dataset failure remains isolated from all other work items.

`ThematicAtlases.credentials.GoogleCredentialPreflight` is an optional injected policy. It resolves Google ADC/project configuration and refreshes the token once without generating model content. An injected checker runs before method-owned query generation/thematic review and before eligible LLM-enabled harmonization.

<a id="epmc-wrapper"></a>
### EuropePMC Wrapper

`ThematicAtlases.wrappers.epmc.EuropePMCWrapper` handles Europe PMC publication search.

Current public methods:

- `collect_accessions(queries, max_publications=None, max_publications_per_query=None) -> list[dict]`: searches publications, deduplicates publications across queries, fetches datalinks once per unique publication, deduplicates by normalized `datalink_id`, and returns accession records before publication text enrichment.
- `collect_publications(queries, max_publications=None, max_publications_per_query=None) -> list[dict]`: searches Europe PMC for each query and returns normalized, cross-query-deduplicated publication rows. The per-query limit list aligns with query order; configured limits can expand pagination beyond the default five pages.
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

`collect_publications()` and `collect_datalinks()` are intermediate stages inside `collect_accessions()`. `collect_datalinks()` owns the flattened datalink row collection and internal `_deduplicate_accessions()` pass. `collect_publication_texts()` remains a reusable enrichment stage and is called by the dataset collection workflow after accession collection and optional metadata routing.

During traced workflows, every completed search page, publication datalink
lookup, and publication full-text/fallback result is committed independently to
SQLite. A resumed call reconstructs ordered results from these rows and only
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

These request tuning values are stored together in an internal settings dictionary. The base delay can be overridden explicitly by a caller, including with zero for controlled tests. Transient response statuses `429`, `500`, `502`, `503`, and `504` are retried. `Retry-After` is honored when present; otherwise retry delay uses short exponential backoff. Pagination is sequential, with no parallel requests.

<a id="arrayexpress-wrapper"></a>
### ArrayExpress Wrapper

`ThematicAtlases.wrappers.ae.ArrayExpressWrapper` is a placeholder metadata handler for selected ArrayExpress records. It does not call a live ArrayExpress API yet.

`collect_accession_metadata(jsons: list[dict]) -> list[dict]` preserves each input record and appends:

```text
metadata_repository=arrayexpress
metadata_source=placeholder
metadata_status=placeholder
accession_metadata=null
```

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

<a id="cli-atlas"></a>
## CLI Atlas

`ThematicAtlases.cli_atlas` provides a standard-library `argparse` CLI with `main(argv: list[str] | None = None) -> int`.

Commands:

- `[-v | --verbose] [--log-file LOG_FILE]`
- `create-atlas [--verbose] [--log-file LOG_FILE] [--query QUERY] [--file FILE] [--query-generator] [--max-generated-queries N] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--dev-trace] [--dev-out-dir DIR] [--theme THEME] [--theme-file FILE] [--review-filter MODE] [--review-strategy direct|evidence_then_judgement] [--harmonization-details-out PATH]`
- `collect-datasets [--verbose] [--log-file LOG_FILE] [--query QUERY] [--file FILE] [--query-generator] [--max-generated-queries N] [--out OUT] [--metadata-repository REPO] [--max-publications N] [--skip-metadata] [--review-before-metadata] [--theme THEME] [--theme-file FILE] [--review-filter MODE] [--review-strategy direct|evidence_then_judgement]`
- `harmonize-datasets [--verbose] [--log-file LOG_FILE] --file INPUT --out OUTPUT [--harmonization-details-out PATH]`

Logging options may appear before or after the subcommand. Default logging level is `WARNING`; `-v` or `--verbose` enables INFO progress and stats logs, and `-vv` enables DEBUG request, retry, and routing logs. Without `--log-file`, logs go to stdout. With `--log-file`, logs are written to that UTF-8 file only. If logging options are supplied both before and after the subcommand, the subcommand-local value is used.

The CLI forwards explicit queries, the query-file path, `--query-generator`, `--max-generated-queries`, `--review-before-metadata`, and `--review-strategy`; `Atlas.collect_datasets()` owns loading, ordering, generation, validation, and review dispatch. Explicit values precede file queries, followed by generated queries. Without the query-generator flag no query-generation LLM call occurs. Review-before-metadata requires a theme. `--dev-trace` is supported by `create-atlas` only; `--dev-out-dir` chooses its root directory.

Each command instantiates `Atlas(metadata={})`, calls the matching method, and configures logging from CLI options. Successful commands do not print result data to stdout, though stdout may contain logs when verbose console logging is enabled. Use `--out` as the JSON result channel and logging as the stats channel.

`collect-datasets` and `create-atlas` both call `Atlas.collect_datasets()` for the collection and publication text mapping stage. Supplying `--theme` or `--theme-file` opts into `agentic_curator` thematic review for each unique publication text before review filtering is applied. `create-atlas` then harmonizes the atlas, writes the requested final JSON and automatic summary, and optionally writes the trace bundle. The standalone `harmonize-datasets` command reads `--file`, transforms the atlas, and writes required `--out`; both harmonizing commands can write the optional details sidecar.

<a id="archive-reference"></a>
## Archive Reference

`oldd/` contains the archived previous implementation, generated outputs, old docs, and old environment artifacts. Treat it as source material to inspect and cannibalize deliberately, not as live package code.

Live code should not import from `oldd/`. If behavior is restored from the archive, port it into `src/ThematicAtlases/` with tests and updated docs.

<a id="test-and-verification-status"></a>
## Test And Verification Status

Live tests cover atlas orchestration, summaries, opt-in trace checkpoints, SQLite durability/fingerprints, review-before-metadata ordering/resume, direct and legacy strategy isolation, shared-publication GSE aggregation, trace-only accession exclusions, interruption and item-level resume across Europe PMC/GEO/review/harmonization, method-owned query generation, credential preflight, repository selection, GEO filtering, ArrayExpress no-call behavior, publication review, configurable/cached/parallel ontology harmonization, CLI forwarding, Europe PMC requests/retries/text/datalinks, GEO-to-GSE resolution, and exact complete input/output comparison for the Leonie reference-publication recall benchmark. Network/provider access is mocked.

Useful checks:

```bash
.env/bin/python -m py_compile src/ThematicAtlases/__init__.py src/ThematicAtlases/atlas.py src/ThematicAtlases/checkpoint.py src/ThematicAtlases/cli_atlas.py src/ThematicAtlases/summary.py src/ThematicAtlases/trace.py src/ThematicAtlases/collector/__init__.py src/ThematicAtlases/collector/collector.py src/ThematicAtlases/filterer/__init__.py src/ThematicAtlases/filterer/filterer.py src/ThematicAtlases/filterer/review.py src/ThematicAtlases/harmonizer/__init__.py src/ThematicAtlases/harmonizer/harmonizer.py src/ThematicAtlases/wrappers/__init__.py src/ThematicAtlases/wrappers/ae.py src/ThematicAtlases/wrappers/epmc.py src/ThematicAtlases/wrappers/geo.py
.env/bin/python -m pytest
```

If `pytest` is unavailable in the active environment, use a direct smoke check:

```bash
PYTHONPATH=src python3 -m ThematicAtlases.cli_atlas collect-datasets --query fibrosis
```

The smoke check performs a live Europe PMC request when `requests` is installed and network access is available.
