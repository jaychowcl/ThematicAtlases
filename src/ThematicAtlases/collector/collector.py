import json
import logging

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")
logger = logging.getLogger(__name__)


class AtlasCollector:
    def __init__(
        self,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
    ):
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        self._metadata_handlers = metadata_handlers or {"geo": GEOWrapper}

    def collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
    ) -> list[dict]:
        logger.info("Atlas collect_jsons progress stage=query-loading")
        queries = list(query or [])

        if file is not None:
            queries.extend(self._load_queries(file))

        logger.info("Atlas collect_jsons stats query_count=%s", len(queries))
        logger.info("Atlas collect_jsons progress stage=collect-accessions")
        accessions = self._epmc_wrapper().collect_accessions(queries=queries)
        logger.info(
            "Atlas collect_jsons progress stage=collect-accessions-complete raw_accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_jsons progress stage=filter-accessions")
        result = self.filter_accessions(accessions)
        logger.info("Atlas collect_jsons progress stage=collect-accession-metadata")
        result = self.collect_accession_metadata(jsons=result)
        logger.info(
            "Atlas collect_jsons progress stage=collect-accession-metadata-complete metadata_records=%s",
            len(result),
        )

        if out is not None:
            logger.info("Atlas collect_jsons progress stage=write-output output_path=%s", out)
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        logger.info(
            "Atlas collect_jsons stats query_count=%s raw_accessions=%s metadata_records=%s output_path=%s",
            len(queries),
            len(accessions),
            len(result),
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

    def filter_accessions(self, accessions: list[dict]) -> list[dict]:
        filtered_accessions = [
            record
            for record in accessions
            if self.is_handled_accession(record=record)
        ]
        logger.info(
            "Atlas accession filter stats input_accessions=%s output_accessions=%s dropped_accessions=%s",
            len(accessions),
            len(filtered_accessions),
            len(accessions) - len(filtered_accessions),
        )
        return filtered_accessions

    def is_handled_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        records = []
        repository_records = {}
        skipped_records = 0

        for record in jsons:
            repository = self.metadata_repository(record=record)
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
            records.extend(
                self.metadata_handler(repository=repository).collect_accession_metadata(
                    jsons=repository_jsons
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

    def metadata_repository(self, record: dict) -> str | None:
        if self.is_handled_accession(record=record):
            return "geo"

        return None

    def metadata_handler(self, repository: str):
        handler_factory = self._metadata_handlers.get(repository)

        if handler_factory is not None:
            return handler_factory()

        raise ValueError(f"Unsupported metadata repository: {repository}")

    def _epmc_wrapper(self):
        return self._epmc_wrapper_factory()
