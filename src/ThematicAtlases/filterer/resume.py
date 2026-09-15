from __future__ import annotations

from ThematicAtlases.integrations.magetab import SourceEvidenceCompatibilityError

import json
import logging
import signal
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from ThematicAtlases.checkpoint import (
    CheckpointItemLockTimeout,
    CheckpointStore,
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.runtime_contracts import safe_error_json
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


_default_collector_factory = None
_default_filterer_factory = None
_RESOLVED_METADATA_STATUSES = frozenset(
    {"available", "partial", "unavailable", "error"}
)
_REVIEWABLE_METADATA_STATUSES = frozenset(
    {"available", "partial", "unavailable"}
)

logger = logging.getLogger(__name__)


class SnapshotItemTimeout(TimeoutError):
    """Report that one incremental snapshot item exceeded its hard deadline."""


class _SnapshotDeadlineInterrupt(BaseException):
    """Escape broad provider exception handlers when a hard deadline expires."""


def _validated_positive_timeout(value, *, name: str):
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive number")
    return float(value)


@contextmanager
def _item_deadline(timeout_seconds, *, item: str):
    timeout_seconds = _validated_positive_timeout(
        timeout_seconds,
        name="snapshot item timeout",
    )
    if timeout_seconds is None:
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("snapshot item hard deadlines require the main thread")

    def interrupt(_signum, _frame):
        raise _SnapshotDeadlineInterrupt()

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    except _SnapshotDeadlineInterrupt as error:
        raise SnapshotItemTimeout(
            f"incremental snapshot item timed out: {item}"
        ) from error
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.000001, previous_delay - elapsed),
                previous_interval,
            )


def configure_default_resume_factories(*, collector_factory, filterer_factory) -> None:
    """Wire concrete resume collaborators without reverse component imports."""

    global _default_collector_factory, _default_filterer_factory
    _default_collector_factory = collector_factory
    _default_filterer_factory = filterer_factory


class TracePublicationReviewResumer:
    """Review a stable snapshot of publications in an evolving trace."""

    def __init__(
        self,
        publication_text_reviewer,
        *,
        collector_factory=None,
        filterer_factory=None,
        epmc_wrapper_factory=None,
    ):
        self._publication_text_reviewer = publication_text_reviewer
        self._collector_factory = collector_factory or _default_collector_factory
        self._filterer_factory = filterer_factory or _default_filterer_factory
        if self._collector_factory is None or self._filterer_factory is None:
            raise RuntimeError("default publication-review resume wiring is not configured")
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper

    def resume(
        self,
        trace_dir: str | Path,
        *,
        theme: str | None = None,
        strategy: str = "direct",
        reviewer=None,
        allow_theme_override: bool = False,
        require_resolved_metadata: bool = False,
        collect_metadata: bool = False,
        defer_metadata_errors: bool = False,
        require_main_datalinks_phase: bool = False,
        publication_limit: int | None = None,
        review_action_limit: int | None = None,
        cancelled=None,
        snapshot_accessions: list[dict] | None = None,
        publication_keys: list[tuple] | None = None,
        item_lock_timeout_seconds: int | float | None = None,
        metadata_item_timeout_seconds: int | float | None = None,
        publication_text_item_timeout_seconds: int | float | None = None,
        review_item_timeout_seconds: int | float | None = None,
    ) -> dict:
        directory = Path(trace_dir)
        publication_limit = self._validated_publication_limit(publication_limit)
        review_action_limit = self._validated_publication_limit(
            review_action_limit
        )
        metadata_item_timeout_seconds = _validated_positive_timeout(
            metadata_item_timeout_seconds,
            name="metadata item timeout",
        )
        publication_text_item_timeout_seconds = _validated_positive_timeout(
            publication_text_item_timeout_seconds,
            name="publication text item timeout",
        )
        review_item_timeout_seconds = _validated_positive_timeout(
            review_item_timeout_seconds,
            name="review item timeout",
        )
        manifest = self._read_manifest(directory)
        resolved_theme = self._resolved_theme(
            theme=theme,
            manifest=manifest,
            allow_theme_override=allow_theme_override,
        )
        store = CheckpointStore(
            directory / "atlas_run.sqlite3",
            default_item_lock_timeout_seconds=item_lock_timeout_seconds,
        )
        trace = DevTraceWriter.existing(directory)

        def main_phase_name() -> str:
            phase = store.get_meta("main_pipeline_phase", {})
            return str(phase.get("phase") or "missing")

        def cancellation_requested() -> bool:
            return bool(cancelled is not None and cancelled())

        def main_allows_snapshot_work() -> bool:
            return (
                not require_main_datalinks_phase
                or main_phase_name() == "datalinks"
            )

        def continue_snapshot_work() -> bool:
            return not cancellation_requested() and main_allows_snapshot_work()

        datalink_items = [
            item for item in store.items("datalinks") if item["status"] == "available"
        ]
        datalink_rows = [
            row
            for item in datalink_items
            for row in (item.get("payload") or {}).get("rows", [])
        ]
        phase_name = main_phase_name()
        if require_main_datalinks_phase and phase_name != "datalinks":
            result = {
                "accessions": [],
                "publication_texts": {},
                "metadata_summary": {
                    "snapshot_datalink_checkpoint_count": len(datalink_items),
                    "snapshot_datalink_row_count": len(datalink_rows),
                    "snapshot_accession_count": 0,
                    "snapshot_publication_count": 0,
                    "selected_publication_count": 0,
                    "publication_limit": publication_limit,
                    "review_action_limit": review_action_limit,
                    "review_action_count": 0,
                    "review_completed_action_count": 0,
                    "review_reused_count": 0,
                    "review_actionable_count": 0,
                    "review_remaining_actionable_count": 0,
                    "eligible_publication_count": 0,
                    "deferred_publication_count": 0,
                    "metadata_attempted_count": 0,
                    "metadata_reused_count": 0,
                    "metadata_deferred_accession_count": 0,
                    "metadata_busy_count": 0,
                    "metadata_timeout_count": 0,
                    "publication_text_deferred_count": 0,
                    "publication_text_timeout_count": 0,
                    "review_deferred_count": 0,
                    "review_timeout_count": 0,
                    "review_cooldown_deferred_count": 0,
                    "provider_attempts": 0,
                    "retry_count": 0,
                    "rate_wait_seconds": 0.0,
                    "metadata_status_counts": {},
                    "yielded_to_main": True,
                    "main_phase": phase_name,
                },
            }
            trace.write(
                "incremental_review_progress.json",
                result,
            )
            return result
        accessions = (
            list(snapshot_accessions)
            if snapshot_accessions is not None
            else self._epmc_wrapper_factory().accessions_from_datalinks(
                datalinks=datalink_rows
            )
        )
        accessions = self._collector_factory().filter_accessions(
            accessions=accessions,
            metadata_repositories=manifest.get("metadata_repositories"),
        )
        snapshot_accessions = [
            record
            for record in accessions
            if str(record.get("metadata_status") or "").lower() != "unsupported"
        ]
        filterer = self._filterer_factory(
            publication_text_reviewer=self._publication_text_reviewer,
        )
        if publication_keys is not None:
            snapshot_accessions = self._only_publications(
                accessions=snapshot_accessions,
                publication_keys={tuple(key) for key in publication_keys},
                filterer=filterer,
            )
        snapshot_publications = self._publication_keys(snapshot_accessions, filterer)
        selected_publications = set(
            self._sorted_publication_keys(snapshot_publications)[:publication_limit]
            if publication_limit is not None
            else snapshot_publications
        )
        accessions = self._only_publications(
            accessions=snapshot_accessions,
            publication_keys=selected_publications,
            filterer=filterer,
        )
        collector = self._collector_factory()
        metadata_summary = None
        if collect_metadata:
            accessions, metadata_summary = self._collect_snapshot_metadata(
                collector=collector,
                accessions=accessions,
                repositories=manifest.get("metadata_repositories"),
                store=store,
                datalink_checkpoint_count=len(datalink_items),
                datalink_row_count=len(datalink_rows),
                continue_predicate=continue_snapshot_work,
                item_timeout_seconds=metadata_item_timeout_seconds,
            )
        elif hasattr(collector, "available_accession_metadata"):
            accessions = collector.available_accession_metadata(
                jsons=accessions,
                metadata_repositories=manifest.get("metadata_repositories"),
                checkpoint_store=store,
            )
        if require_resolved_metadata:
            accessions = self._resolved_metadata_publications(
                accessions=accessions,
                filterer=filterer,
                defer_metadata_errors=defer_metadata_errors,
            )
        eligible_publications = self._publication_keys(accessions, filterer)
        if metadata_summary is None and review_action_limit is not None:
            metadata_summary = {
                "snapshot_datalink_checkpoint_count": len(datalink_items),
                "snapshot_datalink_row_count": len(datalink_rows),
                "snapshot_accession_count": len(snapshot_accessions),
                "metadata_attempted_count": 0,
                "metadata_reused_count": 0,
                "metadata_deferred_accession_count": 0,
                "metadata_busy_count": 0,
                "metadata_timeout_count": 0,
                "metadata_status_counts": {},
                "yielded_to_main": False,
            }
        if metadata_summary is not None:
            metadata_summary.update(
                {
                    "snapshot_publication_count": len(snapshot_publications),
                    "snapshot_accession_count": len(snapshot_accessions),
                    "selected_publication_count": len(selected_publications),
                    "publication_limit": publication_limit,
                    "review_action_limit": review_action_limit,
                    "review_action_count": 0,
                    "review_completed_action_count": 0,
                    "review_reused_count": 0,
                    "review_actionable_count": 0,
                    "review_remaining_actionable_count": 0,
                    "eligible_publication_count": len(eligible_publications),
                    "deferred_publication_count": len(
                        selected_publications - eligible_publications
                    ),
                    "publication_text_deferred_count": 0,
                    "publication_text_timeout_count": 0,
                    "review_deferred_count": 0,
                    "review_timeout_count": 0,
                    "review_cooldown_deferred_count": 0,
                    "provider_attempts": 0,
                    "retry_count": 0,
                    "rate_wait_seconds": 0.0,
                }
            )
            metadata_summary.setdefault("yielded_to_main", False)
            metadata_summary["main_phase"] = main_phase_name()
        if require_main_datalinks_phase and not continue_snapshot_work():
            if metadata_summary is not None:
                metadata_summary["yielded_to_main"] = (
                    not main_allows_snapshot_work()
                )
            result = {
                "accessions": [],
                "publication_texts": {},
            }
            if metadata_summary is not None:
                result["metadata_summary"] = metadata_summary
            trace.write(
                "incremental_review_progress.json",
                result,
            )
            return result
        publication_texts = {}
        publication_text_deferred_count = 0
        publication_text_timeout_count = 0
        for publication_key in self._sorted_publication_keys(eligible_publications):
            if not continue_snapshot_work():
                if metadata_summary is not None:
                    metadata_summary["yielded_to_main"] = (
                        not main_allows_snapshot_work()
                    )
                break
            item_accessions = self._only_publications(
                accessions=accessions,
                publication_keys={publication_key},
                filterer=filterer,
            )
            try:
                with _item_deadline(
                    publication_text_item_timeout_seconds,
                    item=f"publication_text:{publication_key!r}",
                ):
                    collected_texts = filterer.collect_publication_texts(
                        jsons=item_accessions,
                        checkpoint_store=store,
                    )
            except SnapshotItemTimeout:
                publication_text_timeout_count += 1
                logger.warning(
                    "Incremental publication text timed out publication_key=%r",
                    publication_key,
                )
                continue
            except CheckpointItemLockTimeout:
                publication_text_deferred_count += 1
                logger.info(
                    "Incremental publication text deferred for busy item publication_key=%r",
                    publication_key,
                )
                continue
            except Exception as error:
                publication_text_deferred_count += 1
                logger.warning(
                    "Incremental publication text deferred publication_key=%r error_type=%s",
                    publication_key,
                    type(error).__name__,
                )
                continue
            if not collected_texts:
                publication_text_deferred_count += 1
                continue
            publication_texts.update(collected_texts)

        accessions_with_refs = filterer.accessions_with_publication_text_refs(
            jsons=accessions,
            publication_texts=publication_texts,
        )

        def write_progress(reviewed_texts: dict) -> None:
            review_actionable_count = max(
                len(publication_texts)
                - review_reused_count
                - review_cooldown_deferred_count,
                0,
            )
            if metadata_summary is not None:
                metadata_summary.update(
                    {
                        "main_phase": main_phase_name(),
                        "publication_text_deferred_count": (
                            publication_text_deferred_count
                        ),
                        "publication_text_timeout_count": (
                            publication_text_timeout_count
                        ),
                        "review_deferred_count": review_deferred_count,
                        "review_timeout_count": review_timeout_count,
                        "review_cooldown_deferred_count": (
                            review_cooldown_deferred_count
                        ),
                        "review_action_count": review_action_count,
                        "review_completed_action_count": (
                            review_completed_action_count
                        ),
                        "review_reused_count": review_reused_count,
                        "review_actionable_count": review_actionable_count,
                        "review_remaining_actionable_count": max(
                            review_actionable_count - review_action_count,
                            0,
                        ),
                    }
                )
            progress = {
                "accessions": filterer.accessions_with_publication_text_refs(
                    jsons=accessions,
                    publication_texts=reviewed_texts,
                ),
                "publication_texts": reviewed_texts,
            }
            if metadata_summary is not None:
                progress["metadata_summary"] = metadata_summary
            trace.write("incremental_review_progress.json", progress)

        reviewed_texts = {}
        review_deferred_count = 0
        review_timeout_count = 0
        review_cooldown_deferred_count = 0
        review_action_count = 0
        review_completed_action_count = 0
        review_reused_count = 0
        contexts = self._publication_text_reviewer.publication_review_contexts(
            accessions=accessions_with_refs
        )
        resolved_reviewer = reviewer
        if publication_texts and resolved_reviewer is None:
            resolved_reviewer = self._publication_text_reviewer._reviewer()
        model_metrics_before = self._reviewer_provider_metrics(resolved_reviewer)
        for publication_ref in sorted(publication_texts):
            if (
                review_action_limit is not None
                and review_action_count >= review_action_limit
            ):
                break
            if not continue_snapshot_work():
                if metadata_summary is not None:
                    metadata_summary["yielded_to_main"] = (
                        not main_allows_snapshot_work()
                    )
                break
            checkpoint_key = f"{strategy}:{publication_ref}"
            checkpoint_before = store.get("thematic_review", checkpoint_key)
            retry_at = (checkpoint_before or {}).get("payload", {}).get(
                "next_retry_at"
            )
            try:
                cooldown_pending = (
                    retry_at is not None and float(retry_at) > time.time()
                )
            except (TypeError, ValueError):
                cooldown_pending = False
            if (
                checkpoint_before
                and checkpoint_before.get("status") == "retryable_error"
                and cooldown_pending
            ):
                review_cooldown_deferred_count += 1
                write_progress(reviewed_texts)
                continue
            try:
                with _item_deadline(
                    review_item_timeout_seconds,
                    item=f"thematic_review:{strategy}:{publication_ref}",
                ):
                    reviewed = (
                        self._publication_text_reviewer.review_publication_texts(
                            publication_texts={
                                publication_ref: publication_texts[publication_ref]
                            },
                            contexts={
                                publication_ref: contexts.get(publication_ref, {})
                            },
                            theme=resolved_theme,
                            strategy=strategy,
                            reviewer=resolved_reviewer,
                            checkpoint_store=store,
                        )
                    )
            except SnapshotItemTimeout:
                review_action_count += 1
                review_timeout_count += 1
                logger.warning(
                    "Incremental thematic review timed out publication_ref=%s",
                    publication_ref,
                )
                write_progress(reviewed_texts)
                continue
            except CheckpointItemLockTimeout:
                review_deferred_count += 1
                logger.info(
                    "Incremental thematic review deferred for busy item publication_ref=%s",
                    publication_ref,
                )
                write_progress(reviewed_texts)
                continue
            except Exception as error:
                review_action_count += 1
                review_deferred_count += 1
                retryable = is_retryable_error(error)
                if checkpoint_before is None or checkpoint_before.get(
                    "status"
                ) == "retryable_error":
                    retry_at = getattr(error, "retry_at", None)
                    store.put(
                        "thematic_review",
                        checkpoint_key,
                        review_action_count,
                        "retryable_error" if retryable else "terminal_error",
                        payload={
                            "contract_version": 1,
                            "strategy": strategy,
                            "publication_ref": publication_ref,
                            "failure_stage": "shared_review_context",
                            **(
                                {"next_retry_at": float(retry_at)}
                                if retry_at is not None
                                else {}
                            ),
                        },
                        error=safe_error_json(
                            error,
                            provider="agentic_curator",
                            stage="thematic_review",
                            item_id=publication_ref,
                            retryable=retryable,
                        ),
                        error_type=type(error).__name__,
                        failure_category=failure_category(error),
                    )
                logger.warning(
                    "Incremental thematic review deferred publication_ref=%s error_type=%s",
                    publication_ref,
                    type(error).__name__,
                )
                write_progress(reviewed_texts)
                continue
            checkpoint_after = store.get("thematic_review", checkpoint_key)
            if checkpoint_after != checkpoint_before:
                review_action_count += 1
            reviewed_publication = reviewed.get(publication_ref, {})
            review_trace = reviewed_publication.get("agentic_curator", {})
            if review_trace.get("review_status") == "failed":
                review_deferred_count += 1
            else:
                if checkpoint_after != checkpoint_before:
                    review_completed_action_count += 1
                elif checkpoint_before is not None:
                    review_reused_count += 1
                reviewed_texts.update(reviewed)
            write_progress(reviewed_texts)

        if metadata_summary is not None:
            model_metrics_after = self._reviewer_provider_metrics(
                resolved_reviewer
            )
            review_actionable_count = max(
                len(publication_texts)
                - review_reused_count
                - review_cooldown_deferred_count,
                0,
            )
            metadata_summary.update(
                {
                    "main_phase": main_phase_name(),
                    "yielded_to_main": not main_allows_snapshot_work(),
                    "publication_text_deferred_count": (
                        publication_text_deferred_count
                    ),
                    "publication_text_timeout_count": (
                        publication_text_timeout_count
                    ),
                    "review_deferred_count": review_deferred_count,
                    "review_timeout_count": review_timeout_count,
                    "review_cooldown_deferred_count": (
                        review_cooldown_deferred_count
                    ),
                    "review_action_count": review_action_count,
                    "review_completed_action_count": review_completed_action_count,
                    "review_reused_count": review_reused_count,
                    "review_actionable_count": review_actionable_count,
                    "review_remaining_actionable_count": max(
                        review_actionable_count - review_action_count,
                        0,
                    ),
                    "provider_attempts": max(
                        model_metrics_after["provider_attempts"]
                        - model_metrics_before["provider_attempts"],
                        0,
                    ),
                    "retry_count": max(
                        model_metrics_after["retry_count"]
                        - model_metrics_before["retry_count"],
                        0,
                    ),
                    "rate_wait_seconds": max(
                        model_metrics_after["rate_wait_seconds"]
                        - model_metrics_before["rate_wait_seconds"],
                        0.0,
                    ),
                }
            )
        result = {
            "accessions": filterer.accessions_with_publication_text_refs(
                jsons=accessions,
                publication_texts=reviewed_texts,
            ),
            "publication_texts": reviewed_texts,
        }
        if metadata_summary is not None:
            result["metadata_summary"] = metadata_summary
        trace.write("incremental_review_progress.json", result)
        return result

    @staticmethod
    def _reviewer_provider_metrics(reviewer) -> dict:
        metrics = getattr(reviewer, "llm", None)
        if not all(
            hasattr(metrics, name)
            for name in ("provider_attempts", "retry_count", "rate_wait_seconds")
        ):
            metrics = reviewer
        if not all(
            hasattr(metrics, name)
            for name in ("provider_attempts", "retry_count", "rate_wait_seconds")
        ):
            return {
                "provider_attempts": 0,
                "retry_count": 0,
                "rate_wait_seconds": 0.0,
            }
        return {
            "provider_attempts": int(metrics.provider_attempts),
            "retry_count": int(metrics.retry_count),
            "rate_wait_seconds": float(metrics.rate_wait_seconds),
        }

    @staticmethod
    def _collect_snapshot_metadata(
        *,
        collector,
        accessions: list[dict],
        repositories,
        store,
        datalink_checkpoint_count: int,
        datalink_row_count: int,
        continue_predicate=None,
        item_timeout_seconds=None,
    ) -> tuple[list[dict], dict]:
        attempted = 0
        reused = 0
        busy = 0
        timeout_count = 0
        yielded_to_main = False
        for record in accessions:
            if continue_predicate is not None and not continue_predicate():
                yielded_to_main = True
                break
            existing = collector.available_accession_metadata(
                jsons=[record],
                metadata_repositories=repositories,
                checkpoint_store=store,
            )
            existing_statuses = {
                str(item.get("metadata_status") or "missing").lower()
                for item in existing
            }
            if existing_statuses and existing_statuses <= _RESOLVED_METADATA_STATUSES:
                reused += 1
                continue
            attempted += 1
            try:
                with _item_deadline(
                    item_timeout_seconds,
                    item=f"metadata:{record.get('datalink_id', '')}",
                ):
                    collector.collect_accession_metadata(
                        jsons=[record],
                        metadata_repositories=repositories,
                        checkpoint_store=store,
                    )
            except SnapshotItemTimeout:
                timeout_count += 1
                logger.warning(
                    "Incremental metadata collection timed out accession=%s",
                    record.get("datalink_id", ""),
                )
            except CheckpointItemLockTimeout:
                busy += 1
                logger.info(
                    "Incremental metadata collection deferred for busy item accession=%s",
                    record.get("datalink_id", ""),
                )
            except SourceEvidenceCompatibilityError:
                raise
            except Exception as error:
                logger.warning(
                    "Incremental metadata collection deferred accession=%s "
                    "error_type=%s",
                    record.get("datalink_id", ""),
                    type(error).__name__,
                )

        overlaid = collector.available_accession_metadata(
            jsons=accessions,
            metadata_repositories=repositories,
            checkpoint_store=store,
        )
        status_counts = Counter(
            str(record.get("metadata_status") or "missing").lower()
            for record in overlaid
        )
        deferred = sum(
            count
            for status, count in status_counts.items()
            if status not in _REVIEWABLE_METADATA_STATUSES
        )
        summary = {
            "snapshot_datalink_checkpoint_count": datalink_checkpoint_count,
            "snapshot_datalink_row_count": datalink_row_count,
            "snapshot_accession_count": len(accessions),
            "metadata_attempted_count": attempted,
            "metadata_reused_count": reused,
            "metadata_deferred_accession_count": deferred,
            "metadata_busy_count": busy,
            "metadata_timeout_count": timeout_count,
            "metadata_status_counts": dict(sorted(status_counts.items())),
            "yielded_to_main": yielded_to_main,
        }
        logger.info(
            "Incremental metadata snapshot checkpoints=%s rows=%s accessions=%s "
            "attempted=%s reused=%s deferred=%s statuses=%s",
            datalink_checkpoint_count,
            datalink_row_count,
            len(accessions),
            attempted,
            reused,
            deferred,
            summary["metadata_status_counts"],
        )
        return overlaid, summary

    @staticmethod
    def _validated_publication_limit(value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("publication_limit must be a positive integer")
        return value

    @staticmethod
    def _only_publications(*, accessions, publication_keys, filterer):
        selected = []
        for record in accessions:
            publications = [
                publication
                for publication in record.get("publications", [])
                if filterer.publication_key(publication) in publication_keys
            ]
            if publications:
                selected.append({**record, "publications": publications})
        return selected

    @staticmethod
    def _sorted_publication_keys(publication_keys):
        return sorted(
            publication_keys,
            key=lambda key: tuple(str(value or "") for value in key),
        )

    @staticmethod
    def _publication_keys(accessions: list[dict], filterer) -> set[tuple]:
        return {
            filterer.publication_key(publication)
            for record in accessions
            for publication in record.get("publications", [])
        }

    @staticmethod
    def _resolved_metadata_publications(
        *,
        accessions: list[dict],
        filterer,
        defer_metadata_errors: bool = False,
    ):
        statuses: dict[tuple, list[str]] = {}
        for record in accessions:
            metadata_status = str(record.get("metadata_status") or "").lower()
            for publication in record.get("publications", []):
                key = filterer.publication_key(publication)
                statuses.setdefault(key, []).append(metadata_status)

        accepted_statuses = (
            _REVIEWABLE_METADATA_STATUSES
            if defer_metadata_errors
            else _RESOLVED_METADATA_STATUSES
        )
        eligible = {
            key
            for key, values in statuses.items()
            if values and all(value in accepted_statuses for value in values)
        }
        filtered = []
        for record in accessions:
            publications = [
                publication
                for publication in record.get("publications", [])
                if filterer.publication_key(publication) in eligible
            ]
            if publications:
                filtered.append({**record, "publications": publications})

        logger.info(
            "Incremental review metadata gate publications_total=%s "
            "publications_eligible=%s publications_deferred=%s "
            "accessions_total=%s accessions_eligible=%s",
            len(statuses),
            len(eligible),
            len(statuses) - len(eligible),
            len(accessions),
            len(filtered),
        )
        return filtered

    @staticmethod
    def _read_manifest(directory: Path) -> dict:
        path = directory / "00_run_manifest.json"
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("trace manifest must contain a JSON object")
        return manifest

    @staticmethod
    def _resolved_theme(
        theme: str | None,
        manifest: dict,
        allow_theme_override: bool = False,
    ) -> str:
        manifest_theme = str(manifest.get("theme") or "")
        explicit_theme = None if theme is None else str(theme)
        if (
            explicit_theme is not None
            and explicit_theme.strip()
            and manifest_theme.strip()
            and explicit_theme.strip() != manifest_theme.strip()
            and not allow_theme_override
        ):
            raise ValueError("requested theme does not match the trace manifest theme")
        resolved = (
            explicit_theme
            if allow_theme_override and explicit_theme and explicit_theme.strip()
            else manifest_theme if manifest_theme.strip() else explicit_theme
        )
        if resolved is None or not resolved.strip():
            raise ValueError("incremental publication review requires a non-empty theme")
        return resolved
