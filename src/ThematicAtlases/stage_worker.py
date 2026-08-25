from __future__ import annotations

from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
from pathlib import Path
import time

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
        self._cancellation_check = None

    def resume(
        self,
        trace_dir: str | Path,
        *,
        stage: str,
        item_limit: int | None = None,
        cancelled=None,
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
        self._cancellation_check = cancelled
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
                (
                    "stage_worker_interrupted"
                    if result.get("interrupted")
                    else "stage_worker_completed"
                ),
                stage=stage,
                detail=result,
            )
            return result

    def _run_stage(
        self, *, stage, publications, directory, store, item_limit=None
    ) -> dict:
        if stage == "text":
            frontier = self._text_frontier(publications, store)
            incomplete = sum(
                not self._text_publication_complete(store, publication)
                for publication in publications
            )
            selected = frontier[:item_limit]
            return self._run_text(
                selected,
                store,
                scanned=len(publications),
                actionable=len(frontier),
                cooldown_deferred=max(incomplete - len(frontier), 0),
            )
        if stage == "graph":
            frontier = self._graph_frontier(publications, store)
            incomplete = sum(
                not self._graph_publication_complete(store, publication)
                for publication in publications
            )
            selected = frontier[:item_limit]
            return self._run_graph(
                selected,
                store,
                scanned=len(publications),
                actionable=len(frontier),
                cooldown_deferred=max(incomplete - len(frontier), 0),
            )
        if stage == "metadata":
            return self._run_metadata(publications, store, item_limit=item_limit)
        return self._run_review(
            directory,
            publications,
            store,
            item_limit=item_limit,
        )

    def _run_text(
        self, publications, store, *, scanned=None, actionable=None,
        cooldown_deferred=0,
    ) -> dict:
        wrapper = self._epmc_wrapper_factory()
        completed = 0
        deferred = 0
        yielded = False
        for publication in publications:
            if not self._continue_work(store):
                yielded = not self._worker_allowed(store)
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
        interrupted = self._cancelled()
        if yielded or interrupted:
            deferred += max(0, len(publications) - completed - deferred)
        metrics = self._provider_metrics(wrapper)
        return self._summary(
            stage="text",
            selected_count=len(publications),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=yielded,
            store=store,
            scanned=scanned,
            actionable=actionable,
            interrupted=interrupted,
            cooldown_deferred=cooldown_deferred,
            **metrics,
        )

    def _run_graph(
        self, publications, store, *, scanned=None, actionable=None,
        cooldown_deferred=0,
    ) -> dict:
        wrapper = None
        if not publications:
            completed = 0
            deferred = 0
        else:
            wrapper = self._epmc_wrapper_factory()
            try:
                wrapper.accessions_from_link_graph(
                    publications,
                    checkpoint_store=store,
                    continue_predicate=lambda: self._continue_work(store),
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
        metrics = self._provider_metrics(wrapper)
        return self._summary(
            stage="graph",
            selected_count=len(publications),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=not self._worker_allowed(store),
            store=store,
            scanned=scanned,
            actionable=actionable,
            interrupted=self._cancelled(),
            cooldown_deferred=cooldown_deferred,
            **metrics,
        )

    def _run_metadata(self, publications, store, *, item_limit=None) -> dict:
        collector = self._collector()
        scanned_accessions = self._merged_accessions(publications, store)
        accessions = []
        reused = 0
        cooldown_deferred = 0
        for accession in scanned_accessions:
            checkpoint = store.get(
                self._metadata_stage(accession),
                str(accession.get("datalink_id") or ""),
            )
            if (
                checkpoint
                and checkpoint["status"] == "retryable_error"
                and not self._checkpoint_actionable(checkpoint)
            ):
                cooldown_deferred += 1
                continue
            if self._metadata_accession_actionable(collector, accession, store):
                accessions.append(accession)
            else:
                reused += 1
        accessions = self._prioritized_metadata_frontier(accessions, store)
        actionable = len(accessions)
        if item_limit is not None:
            accessions = accessions[:item_limit]
        completed = 0
        deferred = 0
        yielded = False
        for accession in accessions:
            if not self._continue_work(store):
                yielded = not self._worker_allowed(store)
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
        interrupted = self._cancelled()
        if yielded or interrupted:
            deferred += max(0, len(accessions) - completed - deferred)
        metrics = self._provider_metrics(collector)
        return self._summary(
            stage="metadata",
            selected_count=len(accessions),
            completed_count=completed,
            deferred_count=deferred,
            yielded_to_main=yielded,
            store=store,
            scanned=len(scanned_accessions),
            actionable=actionable,
            interrupted=interrupted,
            cooldown_deferred=cooldown_deferred,
            **metrics,
        )

    def _metadata_accession_actionable(self, collector, accession, store) -> bool:
        available = getattr(collector, "available_accession_metadata", None)
        if callable(available):
            try:
                records = available(
                    jsons=[accession],
                    metadata_repositories=self._manifest_repositories(
                        store.path.parent
                    ),
                    checkpoint_store=store,
                )
            except Exception:
                return True
            statuses = {
                str(record.get("metadata_status") or "missing").casefold()
                for record in records
            }
            return not bool(statuses and statuses <= REVIEWABLE_METADATA_STATUSES)
        checkpoint = store.get(
            self._metadata_stage(accession),
            str(accession.get("datalink_id") or ""),
        )
        return not bool(
            checkpoint
            and checkpoint["status"] in TERMINAL_CHECKPOINT_STATUSES
        )

    @classmethod
    def _prioritized_metadata_frontier(cls, accessions, store):
        indexed = list(enumerate(accessions))

        def priority(item):
            ordinal, accession = item
            checkpoint = store.get(
                cls._metadata_stage(accession),
                str(accession.get("datalink_id") or ""),
            )
            return (
                0
                if checkpoint and checkpoint["status"] == "retryable_error"
                else 1,
                ordinal,
            )

        return [accession for _ordinal, accession in sorted(indexed, key=priority)]

    @staticmethod
    def _metadata_stage(accession) -> str:
        repository = str(accession.get("accession_repository") or "").casefold()
        identity = str(accession.get("datalink_id") or "").upper()
        return (
            "arrayexpress_metadata"
            if repository == "arrayexpress" or identity.startswith("E-")
            else "geo_metadata"
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
            review_action_limit=item_limit,
            cancelled=self._cancellation_check,
            snapshot_accessions=accessions,
            publication_keys=publication_keys,
            item_lock_timeout_seconds=2.0,
        )
        metadata = result.get("metadata_summary", {})
        snapshot_selected = int(
            metadata.get("selected_publication_count", len(publications))
        )
        reviewed = len(result.get("publication_texts") or {})
        action_count = int(
            metadata.get("review_action_count", snapshot_selected)
        )
        completed_actions = int(
            metadata.get("review_completed_action_count", reviewed)
        )
        selected = action_count
        prerequisite_deferred = int(
            metadata.get("deferred_publication_count", 0)
        ) + int(metadata.get("publication_text_deferred_count", 0)) + int(
            metadata.get("publication_text_timeout_count", 0)
        )
        deferred = prerequisite_deferred + int(
            metadata.get("review_deferred_count", 0)
        ) + int(metadata.get("review_timeout_count", 0))
        metrics = {
            "provider_attempts": int(metadata.get("provider_attempts", 0)),
            "retry_count": int(metadata.get("retry_count", 0)),
            "rate_wait_seconds": float(metadata.get("rate_wait_seconds", 0.0)),
        }
        return self._summary(
            stage="review",
            selected_count=selected,
            completed_count=completed_actions,
            deferred_count=deferred,
            yielded_to_main=bool(metadata.get("yielded_to_main")),
            store=store,
            scanned=len(publications),
            actionable=int(metadata.get("review_actionable_count", action_count)),
            prerequisite_deferred=prerequisite_deferred,
            cooldown_deferred=int(
                metadata.get("review_cooldown_deferred_count", 0)
            ),
            interrupted=self._cancelled(),
            claimed=action_count,
            reused=int(metadata.get("review_reused_count", 0)),
            remaining_actionable=int(
                metadata.get("review_remaining_actionable_count", 0)
            ),
            **metrics,
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

        return PublicationTextReviewer(cancelled=self._cancellation_check)

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
        if (
            not checkpoint
            or checkpoint["status"] not in TERMINAL_CHECKPOINT_STATUSES
            or TraceStageWorker._legacy_transport_terminal(checkpoint)
        ):
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

    @classmethod
    def _text_frontier(cls, publications, store):
        return cls._prioritized_frontier(
            [
                publication
                for publication in publications
                if cls._text_publication_actionable(store, publication)
            ],
            store=store,
            stages=("publication_text", "fulltext_accession_discovery"),
            key=lambda publication: cls.publication_checkpoint_key(publication),
        )

    @classmethod
    def _graph_frontier(cls, publications, store):
        return cls._prioritized_frontier(
            [
                publication
                for publication in publications
                if cls._graph_publication_actionable(store, publication)
            ],
            store=store,
            stages=("pubmed_gds_links",),
            key=lambda publication: str(publication.get("pmid") or ""),
        )

    @staticmethod
    def _prioritized_frontier(publications, *, store, stages, key):
        indexed = list(enumerate(publications))

        def priority(item):
            ordinal, publication = item
            item_key = key(publication)
            due_retry = any(
                bool(
                    (checkpoint := store.get(stage, item_key))
                    and checkpoint["status"] == "retryable_error"
                )
                for stage in stages
            )
            return (0 if due_retry else 1, ordinal)

        return [publication for _ordinal, publication in sorted(indexed, key=priority)]

    @classmethod
    def _text_publication_actionable(cls, store, publication) -> bool:
        key = cls.publication_checkpoint_key(publication)
        return any(
            cls._checkpoint_actionable(store.get(stage, key))
            for stage in ("publication_text", "fulltext_accession_discovery")
        )

    @classmethod
    def _graph_publication_actionable(cls, store, publication) -> bool:
        pmid = str(publication.get("pmid") or "")
        if not pmid:
            return False
        link = store.get("pubmed_gds_links", pmid)
        if cls._legacy_transport_terminal(link or {}):
            return True
        if cls._checkpoint_actionable(link):
            return True
        return any(
            cls._checkpoint_actionable(store.get("gds_summaries", str(uid)))
            for uid in (link.get("payload") or {}).get("target_uids", [])
        ) if link else False

    @staticmethod
    def _checkpoint_actionable(checkpoint) -> bool:
        if checkpoint is None or checkpoint["status"] == "pending":
            return True
        if checkpoint["status"] != "retryable_error":
            return False
        retry_at = (checkpoint.get("payload") or {}).get("next_retry_at")
        try:
            return retry_at is None or float(retry_at) <= time.time()
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _legacy_transport_terminal(checkpoint: dict) -> bool:
        return bool(
            checkpoint.get("status") == "terminal_error"
            and str(checkpoint.get("error_type") or "").casefold()
            in {
                "chunkedencodingerror",
                "contentdecodingerror",
                "incompleteread",
                "protocolerror",
                "connectionerror",
                "connecttimeout",
                "readtimeout",
                "timeout",
            }
        )

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

    def _cancelled(self) -> bool:
        return bool(
            self._cancellation_check is not None
            and self._cancellation_check()
        )

    def _continue_work(self, store) -> bool:
        return self._worker_allowed(store) and not self._cancelled()

    @staticmethod
    def _provider_metrics(*roots) -> dict:
        """Sum distinct request counters exposed by worker-owned providers."""
        totals = {
            "provider_attempts": 0,
            "retry_count": 0,
            "rate_wait_seconds": 0.0,
        }
        seen = set()

        def visit(candidate) -> None:
            if candidate is None or id(candidate) in seen:
                return
            seen.add(id(candidate))
            metric_names = tuple(totals)
            if all(hasattr(candidate, name) for name in metric_names):
                totals["provider_attempts"] += int(candidate.provider_attempts)
                totals["retry_count"] += int(candidate.retry_count)
                totals["rate_wait_seconds"] += float(
                    candidate.rate_wait_seconds
                )
                return
            for attribute in ("_request_policy", "_link_graph_provider"):
                visit(getattr(candidate, attribute, None))

        for root in roots:
            visit(root)
        return totals

    @staticmethod
    def _summary(
        *, stage, selected_count, completed_count, deferred_count,
        yielded_to_main, store, scanned=None, actionable=None,
        prerequisite_deferred=0, cooldown_deferred=0,
        provider_attempts=0, retry_count=0, rate_wait_seconds=0.0,
        interrupted=False, claimed=None, reused=None,
        remaining_actionable=None,
    ) -> dict:
        scanned = selected_count if scanned is None else int(scanned)
        actionable = selected_count if actionable is None else int(actionable)
        return {
            "contract_version": "1.0",
            "stage": stage,
            "selected_count": selected_count,
            "completed_count": completed_count,
            "deferred_count": deferred_count,
            "yielded_to_main": yielded_to_main,
            "interrupted": bool(interrupted),
            "scanned": scanned,
            "actionable": actionable,
            "claimed": selected_count if claimed is None else int(claimed),
            "reused": (
                max(
                    scanned
                    - actionable
                    - int(prerequisite_deferred)
                    - int(cooldown_deferred),
                    0,
                )
                if reused is None
                else int(reused)
            ),
            "prerequisite_deferred": int(prerequisite_deferred),
            "cooldown_deferred": int(cooldown_deferred),
            "remaining_actionable": (
                max(actionable - completed_count, 0)
                if remaining_actionable is None
                else int(remaining_actionable)
            ),
            "provider_attempts": int(provider_attempts),
            "retry_count": int(retry_count),
            "rate_wait_seconds": float(rate_wait_seconds),
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
