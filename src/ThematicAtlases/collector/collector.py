import json
import logging

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

ARRAYEXPRESS_ACCESSION_PREFIXES = ("E-MTAB", "E-GEOD", "E-MEXP")
DEFAULT_METADATA_REPOSITORIES = ("geo",)
GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")
SUPPORTED_METADATA_REPOSITORIES = {"arrayexpress", "geo"}
logger = logging.getLogger(__name__)


class AtlasCollector:
    def __init__(
        self,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
        metadata_resume_orchestrator_factory=None,
    ):
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        self._metadata_handlers = metadata_handlers or {
            "arrayexpress": ArrayExpressWrapper,
            "geo": GEOWrapper,
        }
        self._metadata_repositories = self._normalized_metadata_repositories(
            metadata_repositories
        )
        self._metadata_resume_orchestrator_factory = metadata_resume_orchestrator_factory
        self._metadata_resume_orchestrator_instance = None

    def resume_metadata(
        self,
        trace_dir: str,
        *,
        audit_enrichment_only: bool = False,
        retry_tags=None,
    ) -> dict:
        """Collect metadata for the current datalink snapshot in a trace."""
        return self._metadata_resume_orchestrator().resume(
            trace_dir,
            audit_enrichment_only=audit_enrichment_only,
            retry_tags=retry_tags,
        )

    def _metadata_resume_orchestrator(self):
        if self._metadata_resume_orchestrator_instance is not None:
            return self._metadata_resume_orchestrator_instance
        if self._metadata_resume_orchestrator_factory is not None:
            instance = self._metadata_resume_orchestrator_factory()
        else:
            from ThematicAtlases.collector.resume import TraceMetadataResumer

            instance = TraceMetadataResumer(collector_factory=lambda: self)
        self._metadata_resume_orchestrator_instance = instance
        return instance

    def collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        collect_metadata: bool = True,
        checkpoint_store=None,
    ) -> list[dict]:
        selected_repositories = self._selected_metadata_repositories(
            metadata_repositories=metadata_repositories
        )
        logger.info("Atlas collect_jsons progress stage=query-loading")
        queries = list(query or [])

        if file is not None:
            queries.extend(self._load_queries(file))

        logger.info("Atlas collect_jsons stats query_count=%s", len(queries))
        logger.info("Atlas collect_jsons progress stage=collect-accessions")
        accession_options = {
            "queries": queries,
            "max_publications": max_publications,
        }
        if max_publications_per_query is not None:
            accession_options["max_publications_per_query"] = (
                max_publications_per_query
            )
        if checkpoint_store is not None:
            accession_options["checkpoint_store"] = checkpoint_store
        accessions = self._epmc_wrapper().collect_accessions(**accession_options)
        logger.info(
            "Atlas collect_jsons progress stage=collect-accessions-complete raw_accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_jsons progress stage=filter-accessions")
        result = self.filter_accessions(
            accessions,
            metadata_repositories=selected_repositories,
        )
        if collect_metadata:
            logger.info("Atlas collect_jsons progress stage=collect-accession-metadata")
            result = self.collect_accession_metadata(
                jsons=result,
                metadata_repositories=selected_repositories,
                checkpoint_store=checkpoint_store,
            )
            logger.info(
                "Atlas collect_jsons progress stage=collect-accession-metadata-complete metadata_records=%s",
                len(result),
            )
        else:
            logger.info("Atlas collect_jsons progress stage=skip-accession-metadata")

        if out is not None:
            logger.info("Atlas collect_jsons progress stage=write-output output_path=%s", out)
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        logger.info(
            "Atlas collect_jsons stats query_count=%s raw_accessions=%s metadata_records=%s collect_metadata=%s output_path=%s",
            len(queries),
            len(accessions),
            len(result),
            collect_metadata,
            out,
        )
        return result

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def filter_accessions(
        self,
        accessions: list[dict],
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        selected_repositories = self._selected_metadata_repositories(
            metadata_repositories=metadata_repositories
        )
        filtered_accessions = [
            record
            for record in accessions
            if self.is_handled_accession(
                record=record,
                metadata_repositories=selected_repositories,
            )
        ]
        logger.info(
            "Atlas accession filter stats input_accessions=%s output_accessions=%s dropped_accessions=%s",
            len(accessions),
            len(filtered_accessions),
            len(accessions) - len(filtered_accessions),
        )
        return filtered_accessions

    def is_handled_accession(
        self,
        record: dict,
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> bool:
        return (
            self.metadata_repository(
                record=record,
                metadata_repositories=metadata_repositories,
            )
            is not None
        )

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
        checkpoint_store=None,
        retry_tags=None,
    ) -> list[dict]:
        selected_repositories = self._selected_metadata_repositories(
            metadata_repositories=metadata_repositories
        )
        records = []
        repository_records = {}
        skipped_records = 0

        for record in jsons:
            repository = self.metadata_repository(
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
            records.extend(
                self.metadata_handler(repository=repository).collect_accession_metadata(
                    **handler_options
                )
            )

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
        return records

    def available_accession_metadata(
        self,
        jsons: list[dict],
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
        checkpoint_store=None,
    ) -> list[dict]:
        """Overlay completed repository metadata without performing downloads."""
        selected = self._selected_metadata_repositories(metadata_repositories)
        records = []
        grouped = {}
        for record in jsons:
            repository = self.metadata_repository(record, selected)
            if repository is not None:
                grouped.setdefault(repository, []).append(record)
        for repository, repository_records in grouped.items():
            handler = self.metadata_handler(repository)
            if checkpoint_store is not None and hasattr(handler, "available_accession_metadata"):
                records.extend(
                    handler.available_accession_metadata(repository_records, checkpoint_store)
                )
            elif repository == "arrayexpress":
                records.extend(handler.collect_accession_metadata(repository_records))
            else:
                records.extend(repository_records)
        return records

    def metadata_repository(
        self,
        record: dict,
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> str | None:
        selected_repositories = self._selected_metadata_repositories(
            metadata_repositories=metadata_repositories
        )

        if "geo" in selected_repositories and self._is_geo_accession(record=record):
            return "geo"

        if "arrayexpress" in selected_repositories and self._is_arrayexpress_accession(
            record=record
        ):
            return "arrayexpress"

        return None

    def _is_geo_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def _is_arrayexpress_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).lower()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "arrayexpress" or datalink_id.startswith(
            ARRAYEXPRESS_ACCESSION_PREFIXES
        )

    def metadata_handler(self, repository: str):
        handler_factory = self._metadata_handlers.get(repository)

        if handler_factory is not None:
            return handler_factory()

        raise ValueError(f"Unsupported metadata repository: {repository}")

    def _epmc_wrapper(self):
        return self._epmc_wrapper_factory()

    def _selected_metadata_repositories(
        self,
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None,
    ) -> tuple[str, ...]:
        if metadata_repositories is None:
            return self._metadata_repositories

        return self._normalized_metadata_repositories(metadata_repositories)

    def _normalized_metadata_repositories(
        self,
        metadata_repositories: list[str] | tuple[str, ...] | set[str] | None,
    ) -> tuple[str, ...]:
        if metadata_repositories is None:
            metadata_repositories = DEFAULT_METADATA_REPOSITORIES

        normalized = tuple(
            dict.fromkeys(str(repository).strip().lower() for repository in metadata_repositories)
        )
        unsupported = sorted(
            repository
            for repository in normalized
            if repository not in SUPPORTED_METADATA_REPOSITORIES
        )

        if unsupported:
            raise ValueError(
                "Unsupported metadata repositories: "
                f"{', '.join(unsupported)}. "
                "Expected one or more of: "
                f"{', '.join(sorted(SUPPORTED_METADATA_REPOSITORIES))}."
            )

        return normalized
