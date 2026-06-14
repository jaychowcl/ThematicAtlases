import json
import logging

from ThematicAtlases.review import (
    ACCESSIONS,
    PUBLICATIONS,
    PUBLICATION_TEXTS,
    PUBLICATION_TEXT_REF,
    PublicationTextReviewer,
)
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")
logger = logging.getLogger(__name__)


class Atlas():
    def __init__(
        self,
        metadata: dict,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
        publication_text_reviewer: PublicationTextReviewer | None = None,
    ):
        self.metadata = metadata
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        self._metadata_handlers = metadata_handlers or {"geo": GEOWrapper}
        self._publication_text_reviewer = (
            publication_text_reviewer or PublicationTextReviewer()
        )

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _load_json(self, file: str) -> dict | list:
        with open(file, encoding="utf-8") as handle:
            return json.load(handle)

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
        handler_factory = self._metadata_handlers.get(repository)

        if handler_factory is not None:
            return handler_factory()

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
        publication_text_ref = str(publication.get("publication_text_ref", "")).strip()

        if publication_text_ref:
            return publication_text_ref

        for key in ("pmid", "pmcid", "doi"):
            value = str(publication.get(key, "")).strip()

            if value:
                return value

        source = str(publication.get("source", "")).strip()
        epmc_id = str(publication.get("epmc_id", "")).strip()

        if source or epmc_id:
            return f"{source}:{epmc_id}"

        return ""

    def _atlas_parts(
        self,
        jsons: dict | list[dict] | None = None,
    ) -> tuple[list[dict], dict]:
        if jsons is None:
            return [], {}

        if isinstance(jsons, list):
            return list(jsons), {}

        if isinstance(jsons, dict):
            return (
                list(jsons.get(ACCESSIONS, [])),
                dict(jsons.get(PUBLICATION_TEXTS, {})),
            )

        return [], {}

    def _collect_publication_texts(
        self,
        jsons: list[dict],
        publication_texts: dict | None = None,
    ) -> dict:
        publication_texts = dict(publication_texts or {})
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get(PUBLICATIONS, []):
                publication_ref = self._publication_text_ref(publication=publication)

                if publication_ref in publication_texts:
                    continue

                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_index:
                    publication_index[publication_key] = len(publications)
                    publications.append(publication)

        if not publications:
            logger.info(
                "Atlas publication text stats input_accessions=%s unique_publications=0 publication_texts=%s",
                len(jsons),
                len(publication_texts),
            )
            return publication_texts

        logger.info(
            "Atlas publication text progress unique_publications=%s",
            len(publications),
        )
        enriched_publications = self._epmc_wrapper().collect_publication_texts(
            publications=publications
        )

        publication_texts.update(
            {
                publication_ref: {
                    "text": publication.get("text", ""),
                    "text_source": publication.get("text_source", "none"),
                    "full_text_status": publication.get(
                        "full_text_status",
                        "unavailable",
                    ),
                }
                for publication in enriched_publications
                if (
                    publication_ref := self._publication_text_ref(
                        publication=publication
                    )
                )
            }
        )
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
                PUBLICATIONS: [
                    self._publication_with_text_ref(
                        publication=publication,
                        publication_texts=publication_texts,
                    )
                    for publication in record.get(PUBLICATIONS, [])
                ],
            }
            for record in jsons
        ]
        accessions_with_refs = sum(
            1
            for record in accessions
            if any(
                PUBLICATION_TEXT_REF in publication
                for publication in record.get(PUBLICATIONS, [])
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
            publication[PUBLICATION_TEXT_REF] = publication_ref

        return publication

    def _epmc_wrapper(self):
        return self._epmc_wrapper_factory()

    def _atlas_object(self, accessions: list[dict], publication_texts: dict) -> dict:
        return {
            ACCESSIONS: accessions,
            PUBLICATION_TEXTS: publication_texts,
        }

    def create_atlas(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        reviewer=None,
    ) -> dict:
        logger.info("Atlas create_atlas progress stage=collect-jsons")
        accessions = self.collect_jsons(query=query, file=file, out=None)
        logger.info(
            "Atlas create_atlas progress stage=collect-jsons-complete accessions=%s",
            len(accessions),
        )
        logger.info("Atlas create_atlas progress stage=filter-jsons")
        result = self.filter_jsons(
            jsons=accessions,
            theme=theme,
            review_filter=review_filter,
            reviewer=reviewer,
        )
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
        accessions = self._epmc_wrapper().collect_accessions(queries=queries)
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

    def filter_jsons(
        self,
        jsons: dict | list[dict] | None = None,
        file: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        reviewer=None,
    ) -> dict:
        self._publication_text_reviewer.validate_options(
            theme=theme,
            review_filter=review_filter,
        )
        accession_records, publication_texts = self._filter_inputs(
            jsons=jsons,
            file=file,
        )

        logger.info("Atlas filter_jsons progress stage=collect-publication-texts")
        publication_texts = self._collect_publication_texts(
            jsons=accession_records,
            publication_texts=publication_texts,
        )
        logger.info("Atlas filter_jsons progress stage=attach-publication-text-refs")
        accessions = self._accessions_with_publication_text_refs(
            jsons=accession_records,
            publication_texts=publication_texts,
        )
        if theme is not None:
            accessions, publication_texts = self._review_and_filter_publications(
                accessions=accessions,
                publication_texts=publication_texts,
                theme=theme,
                review_filter=review_filter,
                reviewer=reviewer,
            )
        accessions_with_refs = sum(
            1
            for record in accessions
            if any(
                PUBLICATION_TEXT_REF in publication
                for publication in record.get(PUBLICATIONS, [])
            )
        )
        logger.info(
            "Atlas filter_jsons stats input_accessions=%s publication_texts=%s accessions_with_text_refs=%s",
            len(accession_records),
            len(publication_texts),
            accessions_with_refs,
        )

        return self._atlas_object(
            accessions=accessions,
            publication_texts=publication_texts,
        )

    def _filter_inputs(
        self,
        jsons: dict | list[dict] | None,
        file: str | None,
    ) -> tuple[list[dict], dict]:
        accession_records, publication_texts = self._atlas_parts(jsons=jsons)

        if file is not None:
            file_accessions, file_publication_texts = self._atlas_parts(
                jsons=self._load_json(file=file)
            )
            accession_records.extend(file_accessions)
            publication_texts.update(file_publication_texts)

        return accession_records, publication_texts

    def _review_and_filter_publications(
        self,
        accessions: list[dict],
        publication_texts: dict,
        theme: str,
        review_filter: str,
        reviewer=None,
    ) -> tuple[list[dict], dict]:
        logger.info("Atlas filter_jsons progress stage=review-publication-texts")
        publication_texts = self._publication_text_reviewer.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self._publication_text_reviewer.publication_review_contexts(
                accessions=accessions
            ),
            theme=theme,
            reviewer=reviewer,
        )
        logger.info("Atlas filter_jsons progress stage=filter-reviewed-publications")
        return self._publication_text_reviewer.filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter=review_filter,
        )

    def harmonize_jsons(self, ) -> list[dict]:
        pass
