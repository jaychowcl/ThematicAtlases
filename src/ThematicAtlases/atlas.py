import json
import logging

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")
logger = logging.getLogger(__name__)


class Atlas():
    def __init__(self, metadata: dict):
        pass

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _filter_accessions(self, accessions: list[dict]) -> list[dict]:
        filtered_accessions = [
            record
            for record in accessions
            if self._is_handled_accession(record=record)
        ]
        logger.info(
            "Atlas accession filter stats input_accessions=%s output_accessions=%s dropped_accessions=%s",
            len(accessions),
            len(filtered_accessions),
            len(accessions) - len(filtered_accessions),
        )
        return filtered_accessions

    def _is_handled_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def _collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        records = []
        repository_records = {}
        skipped_records = 0

        for record in jsons:
            repository = self._metadata_repository(record=record)
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
                self._metadata_handler(repository=repository).collect_accession_metadata(
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

    def _metadata_repository(self, record: dict) -> str | None:
        if self._is_handled_accession(record=record):
            return "geo"

        return None

    def _metadata_handler(self, repository: str):
        if repository == "geo":
            return GEOWrapper()

        raise ValueError(f"Unsupported metadata repository: {repository}")

    def _publication_key(self, publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

    def _publication_text_ref(self, publication: dict) -> str:
        for key in ("pmid", "pmcid", "doi"):
            value = str(publication.get(key, "")).strip()

            if value:
                return value

        source = str(publication.get("source", "")).strip()
        epmc_id = str(publication.get("epmc_id", "")).strip()

        if source or epmc_id:
            return f"{source}:{epmc_id}"

        return ""

    def _collect_publication_texts(self, jsons: list[dict]) -> dict:
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_index:
                    publication_index[publication_key] = len(publications)
                    publications.append(publication)

        if not publications:
            logger.info(
                "Atlas publication text stats input_accessions=%s unique_publications=0 publication_texts=0",
                len(jsons),
            )
            return {}

        logger.info(
            "Atlas publication text progress unique_publications=%s",
            len(publications),
        )
        enriched_publications = EuropePMCWrapper().collect_publication_texts(
            publications=publications
        )

        publication_texts = {
            publication_ref: {
                "text": publication.get("text", ""),
                "text_source": publication.get("text_source", "none"),
                "full_text_status": publication.get("full_text_status", "unavailable"),
            }
            for publication in enriched_publications
            if (publication_ref := self._publication_text_ref(publication=publication))
        }
        logger.info(
            "Atlas publication text stats input_accessions=%s unique_publications=%s publication_texts=%s",
            len(jsons),
            len(publications),
            len(publication_texts),
        )
        return publication_texts

    def _accessions_with_publication_text_refs(
        self,
        jsons: list[dict],
        publication_texts: dict,
    ) -> list[dict]:
        accessions = [
            {
                **record,
                "publications": [
                    self._publication_with_text_ref(
                        publication=publication,
                        publication_texts=publication_texts,
                    )
                    for publication in record.get("publications", [])
                ],
            }
            for record in jsons
        ]
        accessions_with_refs = sum(
            1
            for record in accessions
            if any(
                "publication_text_ref" in publication
                for publication in record.get("publications", [])
            )
        )
        logger.info(
            "Atlas publication text reference stats input_accessions=%s accessions_with_text_refs=%s publication_texts=%s",
            len(jsons),
            accessions_with_refs,
            len(publication_texts),
        )
        return accessions

    def _publication_with_text_ref(
        self,
        publication: dict,
        publication_texts: dict,
    ) -> dict:
        publication_ref = self._publication_text_ref(publication=publication)
        publication = {
            key: value
            for key, value in publication.items()
            if key not in {"text", "text_source", "full_text_status"}
        }

        if publication_ref in publication_texts:
            publication["publication_text_ref"] = publication_ref

        return publication

    def create_atlas(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
    ) -> dict:
        logger.info("Atlas create_atlas progress stage=collect-jsons")
        accessions = self.collect_jsons(query=query, file=file, out=None)
        logger.info(
            "Atlas create_atlas progress stage=collect-jsons-complete accessions=%s",
            len(accessions),
        )
        logger.info("Atlas create_atlas progress stage=filter-jsons")
        result = self.filter_jsons(jsons=accessions)
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas create_atlas progress stage=filter-jsons-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        if out is not None:
            logger.info("Atlas create_atlas progress stage=write-output output_path=%s", out)
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        logger.info(
            "Atlas create_atlas stats collected_accessions=%s final_accessions=%s publication_texts=%s output_path=%s",
            len(accessions),
            len(final_accessions),
            len(publication_texts),
            out,
        )
        return result

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
        accessions = EuropePMCWrapper().collect_accessions(queries=queries)
        logger.info(
            "Atlas collect_jsons progress stage=collect-accessions-complete raw_accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_jsons progress stage=filter-accessions")
        result = self._filter_accessions(accessions)
        logger.info("Atlas collect_jsons progress stage=collect-accession-metadata")
        result = self._collect_accession_metadata(jsons=result)
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

    def filter_jsons(self, jsons: list[dict] | None = None) -> dict:
        jsons = list(jsons or [])
        logger.info("Atlas filter_jsons progress stage=collect-publication-texts")
        publication_texts = self._collect_publication_texts(jsons=jsons)
        logger.info("Atlas filter_jsons progress stage=attach-publication-text-refs")
        accessions = self._accessions_with_publication_text_refs(
            jsons=jsons,
            publication_texts=publication_texts,
        )
        accessions_with_refs = sum(
            1
            for record in accessions
            if any(
                "publication_text_ref" in publication
                for publication in record.get("publications", [])
            )
        )
        logger.info(
            "Atlas filter_jsons stats input_accessions=%s publication_texts=%s accessions_with_text_refs=%s",
            len(jsons),
            len(publication_texts),
            accessions_with_refs,
        )

        return {
            "accessions": accessions,
            "publication_texts": publication_texts,
        }

    def harmonize_jsons(self, ) -> list[dict]:
        pass
