import json
import logging

from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

logger = logging.getLogger(__name__)


class Atlas:
    def __init__(
        self,
        metadata: dict,
        epmc_wrapper_factory=None,
        metadata_handlers: dict | None = None,
        metadata_repositories: list[str] | None = None,
        publication_text_reviewer: PublicationTextReviewer | None = None,
        collector: AtlasCollector | None = None,
        filterer: AtlasFilterer | None = None,
        harmonizer: AtlasHarmonizer | None = None,
    ):
        self.metadata = metadata
        epmc_wrapper_factory = epmc_wrapper_factory or EuropePMCWrapper
        metadata_handlers = metadata_handlers or {
            "arrayexpress": ArrayExpressWrapper,
            "geo": GEOWrapper,
        }
        publication_text_reviewer = (
            publication_text_reviewer or PublicationTextReviewer()
        )
        self._collector = collector or AtlasCollector(
            epmc_wrapper_factory=epmc_wrapper_factory,
            metadata_handlers=metadata_handlers,
            metadata_repositories=metadata_repositories,
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
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        reviewer=None,
        collect_metadata: bool = True,
    ) -> dict:
        logger.info("Atlas create_atlas progress stage=collect-datasets")
        datasets = self.collect_datasets(
            query=query,
            file=file,
            out=None,
            theme=theme,
            review_filter=review_filter,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            reviewer=reviewer,
            collect_metadata=collect_metadata,
        )
        logger.info(
            "Atlas create_atlas progress stage=collect-datasets-complete accessions=%s publication_texts=%s",
            len(datasets.get("accessions", [])),
            len(datasets.get("publication_texts", {})),
        )
        logger.info("Atlas create_atlas progress stage=harmonize-datasets")
        result = self.harmonize_datasets(datasets=datasets)
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas create_atlas progress stage=harmonize-datasets-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        if out is not None:
            logger.info("Atlas create_atlas progress stage=write-output output_path=%s", out)
            self._write_json(result=result, out=out)

        logger.info(
            "Atlas create_atlas stats final_accessions=%s publication_texts=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            out,
        )
        return result

    def collect_datasets(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        reviewer=None,
        collect_metadata: bool = True,
    ) -> dict:
        logger.info("Atlas collect_datasets progress stage=collect-accessions")
        accessions = self._collect_jsons(
            query=query,
            file=file,
            out=None,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            collect_metadata=collect_metadata,
        )
        logger.info(
            "Atlas collect_datasets progress stage=collect-accessions-complete accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_datasets progress stage=map-publication-texts")
        result = self._filter_jsons(
            jsons=accessions,
            theme=theme,
            review_filter=review_filter,
            reviewer=reviewer,
        )
        final_accessions = result.get("accessions", [])
        publication_texts = result.get("publication_texts", {})
        logger.info(
            "Atlas collect_datasets progress stage=map-publication-texts-complete accessions=%s publication_texts=%s",
            len(final_accessions),
            len(publication_texts),
        )

        if out is not None:
            logger.info("Atlas collect_datasets progress stage=write-output output_path=%s", out)
            self._write_json(result=result, out=out)

        logger.info(
            "Atlas collect_datasets stats final_accessions=%s publication_texts=%s collect_metadata=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            collect_metadata,
            out,
        )
        return result

    def harmonize_datasets(self, datasets: dict) -> dict:
        return datasets

    def _collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
        metadata_repositories: list[str] | None = None,
        max_publications: int | None = None,
        collect_metadata: bool = True,
    ) -> list[dict]:
        return self._collector.collect_jsons(
            query=query,
            file=file,
            out=out,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            collect_metadata=collect_metadata,
        )

    def _filter_jsons(
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

    def _harmonize_jsons(self) -> list[dict] | None:
        return self._harmonizer.harmonize_jsons()

    def _write_json(self, result: dict | list[dict], out: str) -> None:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
