from __future__ import annotations

import json
import logging
from pathlib import Path

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.trace import DevTraceWriter
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.enrichment import EnrichmentAuditor, load_retry_tags


logger = logging.getLogger(__name__)


class TraceMetadataResumer:
    """Collect metadata for one stable snapshot of an evolving trace."""

    def __init__(self, *, collector_factory=None, epmc_wrapper_factory=None):
        if collector_factory is None:
            from ThematicAtlases.collector.collector import AtlasCollector

            collector_factory = AtlasCollector
        self._collector_factory = collector_factory
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper

    def resume(
        self,
        trace_dir: str | Path,
        *,
        audit_enrichment_only: bool = False,
        retry_tags=None,
    ) -> dict:
        directory = Path(trace_dir)
        manifest = self._read_manifest(directory)
        store = CheckpointStore(directory / "resume_state.sqlite")
        if audit_enrichment_only:
            return self._audit_enrichment(directory, store)
        tags = load_retry_tags(retry_tags) if retry_tags is not None else None
        if tags is not None:
            self._validate_tag_history(store, tags)
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
        collection_options = dict(
            jsons=accessions,
            metadata_repositories=repositories,
            checkpoint_store=store,
        )
        if tags is not None:
            collection_options["retry_tags"] = tags
        accessions = collector.collect_accession_metadata(**collection_options)
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
        if tags is not None:
            history = dict(store.get_meta("applied_enrichment_retry_tags", {}))
            history[tags.tag_id] = {"sha256": tags.digest(), "status": "complete"}
            store.set_meta("applied_enrichment_retry_tags", history)
            logger.info(
                "Metadata retry tag complete tag_id=%s pubmed=%s sra=%s ena=%s",
                tags.tag_id,
                len(tags.pubmed),
                len(tags.sra),
                len(tags.ena),
            )
        return result

    def _audit_enrichment(self, directory: Path, store: CheckpointStore) -> dict:
        report = EnrichmentAuditor().audit(store)
        writer = DevTraceWriter.existing(directory)
        writer.write("resume_enrichment_candidates.json", report)
        template = directory / "resume_enrichment_retry_tags.json"
        if not template.exists():
            writer.write(
                template.name,
                {"tag_id": "", "pubmed": [], "sra": [], "ena": []},
            )
        logger.info(
            "Metadata enrichment audit stats legacy_geo_rows=%s packages=%s pubmed=%s sra=%s ena=%s total=%s",
            report["source"]["legacy_geo_rows"],
            report["source"]["packages"],
            report["counts"]["pubmed"],
            report["counts"]["sra"],
            report["counts"]["ena"],
            report["counts"]["total"],
        )
        return report

    @staticmethod
    def _validate_tag_history(store: CheckpointStore, tags) -> None:
        existing = store.get_meta("applied_enrichment_retry_tags", {}).get(tags.tag_id)
        if existing and existing.get("sha256") != tags.digest():
            raise ValueError(
                f"tag_id {tags.tag_id!r} was already applied with different contents"
            )

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
