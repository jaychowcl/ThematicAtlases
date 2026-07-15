from __future__ import annotations

import json
import logging
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


logger = logging.getLogger(__name__)


class TraceMetadataResumer:
    """Collect metadata for one stable snapshot of an evolving trace."""

    def __init__(self, *, collector_factory=None, epmc_wrapper_factory=None):
        if collector_factory is None:
            from ThematicAtlases.collector.collector import AtlasCollector

            collector_factory = AtlasCollector
        self._collector_factory = collector_factory
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper

    def resume(self, trace_dir: str | Path) -> dict:
        directory = Path(trace_dir)
        manifest = self._read_manifest(directory)
        store = CheckpointStore(directory / "resume_state.sqlite")
        datalink_items = [
            item for item in store.items("datalinks") if item["status"] == "available"
        ]
        datalink_rows = [
            row
            for item in datalink_items
            for row in (item.get("payload") or {}).get("rows", [])
        ]
        logger.info(
            "Metadata snapshot stats datalink_checkpoints=%s datalink_rows=%s",
            len(datalink_items),
            len(datalink_rows),
        )
        raw_accessions = self._epmc_wrapper_factory().accessions_from_datalinks(
            datalinks=datalink_rows
        )
        collector = self._collector_factory()
        repositories = manifest.get("metadata_repositories")
        accessions = collector.filter_accessions(
            accessions=raw_accessions,
            metadata_repositories=repositories,
        )
        logger.info(
            "Metadata snapshot repository stats raw_accessions=%s selected_accessions=%s repositories=%s",
            len(raw_accessions),
            len(accessions),
            repositories,
        )
        logger.info(
            "Metadata checkpoint stats before resolution=%s metadata=%s",
            self._stage_counts(store, "geo_resolution"),
            self._stage_counts(store, "geo_metadata"),
        )
        accessions = collector.collect_accession_metadata(
            jsons=accessions,
            metadata_repositories=repositories,
            checkpoint_store=store,
        )
        result = {"accessions": accessions, "publication_texts": {}}
        DevTraceWriter.existing(directory).write("resume_metadata_progress.json", result)
        logger.info(
            "Metadata checkpoint stats after resolution=%s metadata=%s",
            self._stage_counts(store, "geo_resolution"),
            self._stage_counts(store, "geo_metadata"),
        )
        logger.info(
            "Metadata snapshot complete accessions=%s progress_artifact=%s",
            len(accessions),
            directory / "resume_metadata_progress.json",
        )
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
