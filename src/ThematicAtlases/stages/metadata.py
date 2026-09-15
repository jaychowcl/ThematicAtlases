"""MetadataStage: a typed operation shared by caller-specific scheduling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .results import RecordsResult
if TYPE_CHECKING:
    from ThematicAtlases.collector.collector import AtlasCollector
import logging
logger = logging.getLogger("ThematicAtlases.collector.collector")


@dataclass(frozen=True, kw_only=True)
class MetadataRequest:
    jsons: list[dict]
    metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None
    checkpoint_store: Any = None
    retry_tags: Any = None


class MetadataStage:
    def __init__(self, owner: AtlasCollector):
        self.owner = owner

    def run(self, request: MetadataRequest) -> RecordsResult:
        return RecordsResult(self._execute(
            jsons=request.jsons,
            metadata_repositories=request.metadata_repositories,
            checkpoint_store=request.checkpoint_store,
            retry_tags=request.retry_tags,
        ))

    def _execute(
        self,
        jsons: list[dict],
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
        checkpoint_store=None,
        retry_tags=None,
    ) -> list[dict]:
        stage_owner = self.owner
        selected_repositories = stage_owner._selected_metadata_repositories(
            metadata_repositories=metadata_repositories
        )
        records = []
        repository_records = {}
        skipped_records = 0

        for ordinal, original_record in enumerate(jsons):
            record = {**original_record, "_atlas_discovery_ordinal": ordinal}
            if str(record.get("metadata_status") or "").lower() == "unsupported":
                records.append(record)
                continue
            repository = stage_owner.metadata_repository(
                record=record,
                metadata_repositories=selected_repositories,
            )
            if repository is None:
                skipped_records += 1
                continue
            repository_records.setdefault(repository, []).append(record)

        for repository, repository_jsons in repository_records.items():
            logger.info(
                "Atlas metadata collection progress repository=%s records=%s",
                repository,
                len(repository_jsons),
            )
            handler_options = {"jsons": repository_jsons}
            if checkpoint_store is not None:
                handler_options["checkpoint_store"] = checkpoint_store
            if retry_tags is not None and repository == "geo":
                handler_options["retry_tags"] = retry_tags
            handler = stage_owner.metadata_handler(repository=repository)
            try:
                records.extend(
                    handler.collect_accession_metadata(**handler_options)
                )
            finally:
                stage_owner._accumulate_request_metrics(handler)

        logger.info(
            "Atlas metadata collection stats input_records=%s repositories=%s output_records=%s skipped_records=%s",
            len(jsons),
            ",".join(
                f"{repository}:{len(repository_jsons)}"
                for repository, repository_jsons in repository_records.items()
            ),
            len(records),
            skipped_records,
        )
        return stage_owner._deduplicate_repository_aliases(records)

