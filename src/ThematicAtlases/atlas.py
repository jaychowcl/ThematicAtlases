import json
import logging

from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.review import PublicationTextReviewer
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

logger = logging.getLogger(__name__)


class Atlas:
    def __init__(
        self,
        metadata: dict,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
        publication_text_reviewer: PublicationTextReviewer | None = None,
        collector: AtlasCollector | None = None,
        filterer: AtlasFilterer | None = None,
        harmonizer: AtlasHarmonizer | None = None,
    ):
        self.metadata = metadata
        epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        metadata_handlers = metadata_handlers or {"geo": GEOWrapper}
        publication_text_reviewer = (
            publication_text_reviewer or PublicationTextReviewer()
        )
        self._collector = collector or AtlasCollector(
            epmc_wrapper_factory=epmc_wrapper_factory,
            metadata_handlers=metadata_handlers,
        )
        self._filterer = filterer or AtlasFilterer(
            epmc_wrapper_factory=epmc_wrapper_factory,
            publication_text_reviewer=publication_text_reviewer,
        )
        self._harmonizer = harmonizer or AtlasHarmonizer()

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
        return self._collector.collect_jsons(query=query, file=file, out=out)

    def filter_jsons(
        self,
        jsons: dict | list[dict] | None = None,
        file: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        reviewer=None,
    ) -> dict:
        return self._filterer.filter_jsons(
            jsons=jsons,
            file=file,
            theme=theme,
            review_filter=review_filter,
            reviewer=reviewer,
        )

    def harmonize_jsons(self) -> list[dict] | None:
        return self._harmonizer.harmonize_jsons()
