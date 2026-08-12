from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

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
    ) -> dict:
        directory = Path(trace_dir)
        manifest = self._read_manifest(directory)
        resolved_theme = self._resolved_theme(
            theme=theme,
            manifest=manifest,
            allow_theme_override=allow_theme_override,
        )
        store = DevTraceWriter.existing(directory).checkpoint_store

        datalink_items = [
            item for item in store.items("datalinks") if item["status"] == "available"
        ]
        datalink_rows = [
            row
            for item in datalink_items
            for row in (item.get("payload") or {}).get("rows", [])
        ]
        accessions = self._epmc_wrapper_factory().accessions_from_datalinks(
            datalinks=datalink_rows
        )
        accessions = self._collector_factory().filter_accessions(
            accessions=accessions,
            metadata_repositories=manifest.get("metadata_repositories"),
        )
        accessions = [
            record
            for record in accessions
            if str(record.get("metadata_status") or "").lower() != "unsupported"
        ]
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
            )
        elif hasattr(collector, "available_accession_metadata"):
            accessions = collector.available_accession_metadata(
                jsons=accessions,
                metadata_repositories=manifest.get("metadata_repositories"),
                checkpoint_store=store,
            )
        filterer = self._filterer_factory(
            publication_text_reviewer=self._publication_text_reviewer,
        )
        if require_resolved_metadata:
            accessions = self._resolved_metadata_publications(
                accessions=accessions,
                filterer=filterer,
                defer_metadata_errors=defer_metadata_errors,
            )
        publication_texts = filterer.collect_publication_texts(
            jsons=accessions,
            checkpoint_store=store,
        )
        accessions_with_refs = filterer.accessions_with_publication_text_refs(
            jsons=accessions,
            publication_texts=publication_texts,
        )
        trace = DevTraceWriter.existing(directory)

        def write_progress(reviewed_texts: dict) -> None:
            progress = {
                "accessions": filterer.accessions_with_publication_text_refs(
                    jsons=accessions,
                    publication_texts=reviewed_texts,
                ),
                "publication_texts": reviewed_texts,
            }
            if metadata_summary is not None:
                progress["metadata_summary"] = metadata_summary
            trace.write("resume_review_progress.json", progress)

        reviewed_texts = self._publication_text_reviewer.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self._publication_text_reviewer.publication_review_contexts(
                accessions=accessions_with_refs
            ),
            theme=resolved_theme,
            strategy=strategy,
            reviewer=reviewer,
            progress_callback=write_progress,
            checkpoint_store=store,
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
        trace.write("resume_review_progress.json", result)
        return result

    @staticmethod
    def _collect_snapshot_metadata(
        *,
        collector,
        accessions: list[dict],
        repositories,
        store,
        datalink_checkpoint_count: int,
        datalink_row_count: int,
    ) -> tuple[list[dict], dict]:
        attempted = 0
        reused = 0
        for record in accessions:
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
                collector.collect_accession_metadata(
                    jsons=[record],
                    metadata_repositories=repositories,
                    checkpoint_store=store,
                )
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
            "metadata_status_counts": dict(sorted(status_counts.items())),
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
