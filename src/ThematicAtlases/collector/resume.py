from __future__ import annotations

import json
import logging
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


logger = logging.getLogger(__name__)
_default_collector_factory = None


def configure_default_collector_factory(factory) -> None:
    """Wire the concrete collector without importing it back into this module."""

    global _default_collector_factory
    _default_collector_factory = factory


class TraceMetadataResumer:
    """Collect metadata for one stable snapshot of an evolving trace."""

    def __init__(self, *, collector_factory=None, epmc_wrapper_factory=None):
        resolved_factory = collector_factory or _default_collector_factory
        if resolved_factory is None:
            raise RuntimeError("default AtlasCollector wiring is not configured")
        self._collector_factory = resolved_factory
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper

    def resume(
        self,
        trace_dir: str | Path,
        *,
        audit_enrichment_only: bool = False,
        retry_tags=None,
    ) -> dict:
        if audit_enrichment_only or retry_tags is not None:
            raise ValueError("Identifier enrichment audit/retry tags are retired. Retry the whole study with retry_items={'metadata_conversion': ['geo:GSE123']} (or arrayexpress:E-MTAB-123).")
        from ThematicAtlases.runtime.views import CheckpointViews
        directory = Path(trace_dir)
        manifest = self._read_manifest(directory)
        trace = DevTraceWriter.existing(directory)
        store = trace.checkpoint_store
        collector = self._collector_factory()
        accessions = CheckpointViews(store, manifest).discovery(wrapper=self._epmc_wrapper_factory())
        accessions = collector.filter_accessions(accessions, manifest.get("metadata_repositories"))
        logger.info("Metadata snapshot stats accessions=%s", len(accessions))
        accessions = collector.collect_accession_metadata(
            jsons=accessions, metadata_repositories=manifest.get("metadata_repositories"), checkpoint_store=store)
        result = {"accessions": accessions, "publication_texts": CheckpointViews(store, manifest).publication_texts()}
        trace.write("resume_metadata_progress.json", result)
        logger.info("Metadata snapshot complete accessions=%s checkpoints=%s", len(accessions), store.stage_status_counts())
        return result

    @staticmethod
    def _stage_counts(store: CheckpointStore, stage: str) -> dict:
        counts = {}
        for item in store.items(stage):
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {"total": sum(counts.values()), **counts}

    @staticmethod
    def _read_manifest(directory: Path) -> dict:
        with open(directory / "00_run_manifest.json", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if not isinstance(manifest, dict):
            raise ValueError("trace manifest must contain a JSON object")
        return manifest
