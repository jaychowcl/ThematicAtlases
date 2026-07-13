import json
import logging

from ThematicAtlases.filterer.review import (
    ACCESSIONS,
    PUBLICATIONS,
    PUBLICATION_TEXTS,
    PUBLICATION_TEXT_REF,
    PublicationTextReviewer,
)
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper

logger = logging.getLogger(__name__)


class AtlasFilterer:
    def __init__(
        self,
        epmc_wrapper_factory=None,
        publication_text_reviewer: PublicationTextReviewer | None = None,
    ):
        self._epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        self._publication_text_reviewer = (
            publication_text_reviewer or PublicationTextReviewer()
        )

    def filter_jsons(
        self,
        jsons: dict | list[dict] | None = None,
        file: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        reviewer=None,
        _review_progress_callback=None,
        _checkpoint_store=None,
    ) -> dict:
        self._publication_text_reviewer.validate_options(
            theme=theme,
            review_filter=review_filter,
        )
        accession_records, publication_texts = self.filter_inputs(
            jsons=jsons,
            file=file,
        )

        logger.info("Atlas filter_jsons progress stage=collect-publication-texts")
        publication_texts = self.collect_publication_texts(
            jsons=accession_records,
            publication_texts=publication_texts,
            checkpoint_store=_checkpoint_store,
        )
        logger.info("Atlas filter_jsons progress stage=attach-publication-text-refs")
        accessions = self.accessions_with_publication_text_refs(
            jsons=accession_records,
            publication_texts=publication_texts,
        )
        if theme is not None:
            accessions, publication_texts = self.review_and_filter_publications(
                accessions=accessions,
                publication_texts=publication_texts,
                theme=theme,
                review_filter=review_filter,
                reviewer=reviewer,
                progress_callback=_review_progress_callback,
                checkpoint_store=_checkpoint_store,
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

        return self.atlas_object(
            accessions=accessions,
            publication_texts=publication_texts,
        )

    def _load_json(self, file: str) -> dict | list:
        with open(file, encoding="utf-8") as handle:
            return json.load(handle)

    def publication_key(self, publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

    def publication_text_ref(self, publication: dict) -> str:
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

    def atlas_parts(
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

    def filter_inputs(
        self,
        jsons: dict | list[dict] | None,
        file: str | None,
    ) -> tuple[list[dict], dict]:
        accession_records, publication_texts = self.atlas_parts(jsons=jsons)

        if file is not None:
            file_accessions, file_publication_texts = self.atlas_parts(
                jsons=self._load_json(file=file)
            )
            accession_records.extend(file_accessions)
            publication_texts.update(file_publication_texts)

        return accession_records, publication_texts

    def collect_publication_texts(
        self,
        jsons: list[dict],
        publication_texts: dict | None = None,
        checkpoint_store=None,
    ) -> dict:
        publication_texts = dict(publication_texts or {})
        publications = []
        publication_index = {}

        for record in jsons:
            for publication in record.get(PUBLICATIONS, []):
                publication_ref = self.publication_text_ref(publication=publication)

                if publication_ref in publication_texts:
                    continue

                publication_key = self.publication_key(publication=publication)

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
        text_options = {"publications": publications}
        if checkpoint_store is not None:
            text_options["checkpoint_store"] = checkpoint_store
        enriched_publications = self._epmc_wrapper().collect_publication_texts(
            **text_options
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
                    publication_ref := self.publication_text_ref(
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

    def accessions_with_publication_text_refs(
        self,
        jsons: list[dict],
        publication_texts: dict,
    ) -> list[dict]:
        accessions = [
            {
                **record,
                PUBLICATIONS: [
                    self.publication_with_text_ref(
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

    def publication_with_text_ref(
        self,
        publication: dict,
        publication_texts: dict,
    ) -> dict:
        publication_ref = self.publication_text_ref(publication=publication)
        publication = {
            key: value
            for key, value in publication.items()
            if key not in {"text", "text_source", "full_text_status"}
        }

        if publication_ref in publication_texts:
            publication[PUBLICATION_TEXT_REF] = publication_ref

        return publication

    def review_and_filter_publications(
        self,
        accessions: list[dict],
        publication_texts: dict,
        theme: str,
        review_filter: str,
        reviewer=None,
        progress_callback=None,
        checkpoint_store=None,
    ) -> tuple[list[dict], dict]:
        logger.info("Atlas filter_jsons progress stage=review-publication-texts")
        review_options = dict(
            publication_texts=publication_texts,
            contexts=self._publication_text_reviewer.publication_review_contexts(
                accessions=accessions
            ),
            theme=theme,
            reviewer=reviewer,
            progress_callback=progress_callback,
        )
        if checkpoint_store is not None:
            review_options["checkpoint_store"] = checkpoint_store
        publication_texts = self._publication_text_reviewer.review_publication_texts(
            **review_options
        )
        logger.info("Atlas filter_jsons progress stage=filter-reviewed-publications")
        return self._publication_text_reviewer.filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter=review_filter,
        )

    def atlas_object(self, accessions: list[dict], publication_texts: dict) -> dict:
        return {
            ACCESSIONS: accessions,
            PUBLICATION_TEXTS: publication_texts,
        }

    def _epmc_wrapper(self):
        return self._epmc_wrapper_factory()
