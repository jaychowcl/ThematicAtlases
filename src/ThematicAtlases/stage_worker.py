from __future__ import annotations

from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointItemLockTimeout, CheckpointStore
from ThematicAtlases.run_archive import workflow_activity_lock
from ThematicAtlases.trace import DevTraceWriter


WORKER_STAGES = ("text", "graph", "metadata", "review")
TERMINAL_CHECKPOINT_STATUSES = frozenset(
    {"available", "no_data", "terminal_error"}
)
REVIEWABLE_METADATA_STATUSES = frozenset(
    {"available", "partial", "unavailable", "unsupported"}
)


class StageWorkerBusy(RuntimeError):
    """Report that a non-blocking worker ownership lock is unavailable."""


class TraceStageWorker:
    """Select and advance one stable stage frontier in an existing trace."""

    TERMINAL_DATALINK_STATUSES = frozenset({"available", "no_data"})

    def __init__(
        self,
        *,
        epmc_wrapper_factory=None,
        collector_factory=None,
        publication_text_reviewer_factory=None,
    ) -> None:
        if epmc_wrapper_factory is None:
            from ThematicAtlases.wrappers.epmc import EuropePMCWrapper

            epmc_wrapper_factory = EuropePMCWrapper
        self._epmc_wrapper_factory = epmc_wrapper_factory
        self._collector_factory = collector_factory
        self._publication_text_reviewer_factory = publication_text_reviewer_factory

    def resume(
        self,
        trace_dir: str | Path,
        *,
        stage: str,
        item_limit: int | None = None,
    ) -> dict:
        if stage not in WORKER_STAGES:
            raise ValueError("worker stage must be one of: " + ", ".join(WORKER_STAGES))
        if item_limit is not None and (
            isinstance(item_limit, bool)
            or not isinstance(item_limit, int)
            or item_limit <= 0
        ):
            raise ValueError("item_limit must be a positive integer")
        directory = Path(trace_dir)
        trace = DevTraceWriter.existing(directory)
        store = CheckpointStore(
            directory / "atlas_run.sqlite3",
            default_item_lock_timeout_seconds=2.0,
        )
        with stage_worker_locks(directory, stage):
            trace.run_store.record_event(
                directory.name,
                "stage_worker_started",
                stage=stage,
                detail={"contract_version": "1.0", "item_limit": item_limit},
            )
            if not self._worker_allowed(store):
                result = self._summary(
                    stage=stage,
                    selected_count=0,
                    completed_count=0,
                    deferred_count=0,
                    yielded_to_main=True,
                    store=store,
                )
            else:
                publications = self.eligible_publications(directory)
                result = self._run_stage(
                    stage=stage,
                    publications=publications,
                    directory=directory,
                    store=store,
                    item_limit=item_limit,
                )
            trace.write(f"incremental_{stage}_progress.json", result)
            trace.run_store.record_event(
                directory.name,
                "stage_worker_completed",
                stage=stage,
                detail=result,
            )
            return result

    def _run_stage(
        self, *, stage, publications, directory, store, item_limit=None
    ) -> dict:
        if stage == "text":
            return self._run_text(publications[:item_limit], store)
        if stage == "graph":
            return self._run_graph(publications[:item_limit], store)
        if stage == "metadata":
            return self._run_metadata(publications, store, item_limit=item_limit)
        return self._run_review(
            directory,
            publications,
            store,
            item_limit=item_limit,
        )

    def _run_text(self, publications, store) -> dict:
        wrapper = self._epmc_wrapper_factory()
        completed = 0
        deferred = 0
        yielded = False
        for publication in publications:
            if not self._worker_allowed(store):
                yielded = True
                break
            try:
                enriched = wrapper.collect_publication_texts(
                    [publication], checkpoint_store=store
                )
                wrapper.accessions_from_fulltexts(
                    enriched, checkpoint_store=store
                )
                if self._text_publication_complete(store, publication):
                    completed += 1
                else:
                    deferred += 1
            except (CheckpointItemLockTimeout, TimeoutError):
                deferred += 1
            except Exception:
                deferred += 1
        if yielded:
            deferred += max(0, len(publications) - completed - deferred)
        return self._summary(
            stage="text",
            selected_count=len(publications),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=yielded,
            store=store,
        )

    def _run_graph(self, publications, store) -> dict:
        if not publications:
            completed = 0
            deferred = 0
        else:
            wrapper = self._epmc_wrapper_factory()
            try:
                wrapper.accessions_from_link_graph(
                    publications,
                    checkpoint_store=store,
                    continue_predicate=lambda: self._worker_allowed(store),
                )
                completed = sum(
                    1
                    for publication in publications
                    if self._graph_publication_complete(store, publication)
                )
                deferred = len(publications) - completed
            except (CheckpointItemLockTimeout, TimeoutError):
                completed = 0
                deferred = len(publications)
        return self._summary(
            stage="graph",
            selected_count=len(publications),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=not self._worker_allowed(store),
            store=store,
        )

    def _run_metadata(self, publications, store, *, item_limit=None) -> dict:
        collector = self._collector()
        accessions = self._merged_accessions(publications, store)
        if item_limit is not None:
            accessions = accessions[:item_limit]
        completed = 0
        deferred = 0
        yielded = False
        for accession in accessions:
            if not self._worker_allowed(store):
                yielded = True
                break
            try:
                records = collector.collect_accession_metadata(
                    jsons=[accession],
                    metadata_repositories=self._manifest_repositories(store.path.parent),
                    checkpoint_store=store,
                )
                statuses = {
                    str(record.get("metadata_status") or "").lower()
                    for record in records
                }
                if statuses and statuses <= REVIEWABLE_METADATA_STATUSES:
                    completed += 1
                else:
                    deferred += 1
            except (CheckpointItemLockTimeout, TimeoutError):
                deferred += 1
            except Exception:
                deferred += 1
        if yielded:
            deferred += max(0, len(accessions) - completed - deferred)
        return self._summary(
            stage="metadata",
            selected_count=len(accessions),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=yielded,
            store=store,
        )

    def _run_review(
        self, directory, publications, store, *, item_limit=None
    ) -> dict:
        reviewer = self._publication_text_reviewer()
        publications = [
            publication
            for publication in publications
            if self._review_discovery_terminal(store, publication)
        ]
        if item_limit is not None:
            publications = publications[:item_limit]
        publication_keys = [self.review_publication_key(item) for item in publications]
        accessions = self._merged_accessions(publications, store)
        paused = self._explicitly_paused(store)
        result = reviewer.resume(
            directory,
            require_resolved_metadata=True,
            collect_metadata=False,
            defer_metadata_errors=True,
            require_main_datalinks_phase=not paused,
            publication_limit=None,
            snapshot_accessions=accessions,
            publication_keys=publication_keys,
            item_lock_timeout_seconds=2.0,
        )
        metadata = result.get("metadata_summary", {})
        selected = int(metadata.get("selected_publication_count", len(publications)))
        reviewed = len(result.get("publication_texts") or {})
        deferred = max(
            selected - reviewed,
            int(metadata.get("review_deferred_count", 0)) + int(
                metadata.get("deferred_publication_count", 0)
            ),
        )
        return self._summary(
            stage="review",
            selected_count=selected,
            completed_count=max(0, selected - deferred),
            deferred_count=deferred,
            yielded_to_main=bool(metadata.get("yielded_to_main")),
            store=store,
        )

    def _merged_accessions(self, publications, store) -> list[dict]:
        wrapper = self._epmc_wrapper_factory()
        datalink_rows = [
            row
            for item in store.items("datalinks")
            if item["status"] == "available"
            for row in (item.get("payload") or {}).get("rows", [])
        ]
        datalink_accessions = wrapper.accessions_from_datalinks(datalink_rows)
        fulltext_accessions = [
            record
            for item in store.items("fulltext_accession_discovery")
            if item["status"] in {"available", "no_data", "terminal_error"}
            for record in (item.get("payload") or {}).get("records", [])
        ]
        graph_accessions = wrapper.accessions_from_link_graph(
            publications,
            checkpoint_store=store,
            cached_only=True,
        )
        merged = wrapper.merge_accessions(
            datalink_accessions,
            fulltext_accessions,
            graph_accessions,
        )
        manifest = self._read_manifest(store.path.parent)
        return self._collector().filter_accessions(
            merged,
            metadata_repositories=manifest.get("metadata_repositories"),
        )

    def _collector(self):
        if self._collector_factory is not None:
            return self._collector_factory()
        from ThematicAtlases.collector.collector import AtlasCollector

        return AtlasCollector()

    def _publication_text_reviewer(self):
        if self._publication_text_reviewer_factory is not None:
            return self._publication_text_reviewer_factory()
        from ThematicAtlases.filterer.review import PublicationTextReviewer

        return PublicationTextReviewer()

    @staticmethod
    def _read_manifest(directory: Path) -> dict:
        import json

        with open(directory / "00_run_manifest.json", encoding="utf-8") as handle:
            return json.load(handle)

    def _manifest_repositories(self, directory: Path):
        return self._read_manifest(directory).get("metadata_repositories")

    @staticmethod
    def _graph_publication_complete(store, publication) -> bool:
        pmid = str(publication.get("pmid") or "")
        if not pmid:
            return True
        checkpoint = store.get("pubmed_gds_links", pmid)
        if not checkpoint or checkpoint["status"] not in TERMINAL_CHECKPOINT_STATUSES:
            return False
        target_uids = (checkpoint.get("payload") or {}).get("target_uids", [])
        return all(
            bool(
                (summary := store.get("gds_summaries", str(uid)))
                and summary["status"] in TERMINAL_CHECKPOINT_STATUSES
            )
            for uid in target_uids
        )

    @staticmethod
    def _text_publication_complete(store, publication) -> bool:
        key = TraceStageWorker.publication_checkpoint_key(publication)
        return all(
            bool(
                (checkpoint := store.get(stage, key))
                and checkpoint["status"] in TERMINAL_CHECKPOINT_STATUSES
            )
            for stage in ("publication_text", "fulltext_accession_discovery")
        )

    @classmethod
    def _review_discovery_terminal(cls, store, publication) -> bool:
        return cls._text_publication_complete(
            store, publication
        ) and cls._graph_publication_complete(store, publication)

    @staticmethod
    def review_publication_key(publication: dict) -> tuple:
        return tuple(
            publication.get(key, "")
            for key in ("source", "epmc_id", "pmid", "pmcid", "doi")
        )

    @staticmethod
    def _explicitly_paused(store) -> bool:
        return store.get_meta("main_pipeline_stage", {}).get("state") == "paused"

    def _worker_allowed(self, store) -> bool:
        if self._explicitly_paused(store):
            return True
        return store.get_meta("main_pipeline_phase", {}).get("phase") == "datalinks"

    @staticmethod
    def _summary(
        *, stage, selected_count, completed_count, deferred_count,
        yielded_to_main, store,
    ) -> dict:
        return {
            "contract_version": "1.0",
            "stage": stage,
            "selected_count": selected_count,
            "completed_count": completed_count,
            "deferred_count": deferred_count,
            "yielded_to_main": yielded_to_main,
            "checkpoint_status_counts": store.stage_status_counts(),
        }

    def eligible_publications(self, trace_dir: str | Path) -> list[dict]:
        directory = Path(trace_dir)
        store = CheckpointStore(directory / "atlas_run.sqlite3")
        terminal = {
            item["key"]
            for item in store.items("datalinks")
            if item["status"] in self.TERMINAL_DATALINK_STATUSES
        }
        publications = []
        identities = set()
        for page in store.items("search_pages"):
            if page["status"] != "available":
                continue
            for publication in (page.get("payload") or {}).get("publications", []):
                key = self.publication_checkpoint_key(publication)
                identity = self.publication_identity(publication)
                if key not in terminal or identity in identities:
                    continue
                identities.add(identity)
                publications.append(publication)
        return publications

    @staticmethod
    def publication_checkpoint_key(publication: dict) -> str:
        return (
            f"{str(publication.get('source') or '')}:"
            f"{str(publication.get('epmc_id') or '')}"
        )

    @staticmethod
    def publication_identity(publication: dict) -> tuple[str, str, str]:
        return (
            str(publication.get("source") or ""),
            str(publication.get("epmc_id") or ""),
            str(publication.get("pmid") or ""),
        )


@contextmanager
def stage_worker_activity_lock(trace_dir: str | Path, stage: str):
    """Permit at most one worker for a run/stage pair."""

    directory = Path(trace_dir)
    lock_directory = directory.parent / ".stage-worker-locks"
    lock_directory.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(f"{directory.name}\0{stage}".encode()).hexdigest()
    lock_path = lock_directory / f"{lock_name}.lock"
    with open(lock_path, "a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise StageWorkerBusy(
                f"{stage} worker is already active for run {directory.name}"
            ) from error
        try:
            yield lock_path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def stage_worker_locks(trace_dir: str | Path, stage: str):
    """Acquire shared workflow and per-run/stage ownership without blocking."""

    directory = Path(trace_dir)
    with ExitStack() as stack:
        try:
            stack.enter_context(
                workflow_activity_lock(
                    directory.parent,
                    exclusive=False,
                    blocking=False,
                )
            )
            stack.enter_context(stage_worker_activity_lock(directory, stage))
        except StageWorkerBusy:
            raise
        except RuntimeError as error:
            raise StageWorkerBusy(str(error)) from error
        yield
