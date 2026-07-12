import json
import logging
from datetime import datetime
from pathlib import Path

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
        query_generator=None,
        credential_checker=None,
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
        self._harmonizer = harmonizer or AtlasHarmonizer(
            credential_checker=credential_checker
        )
        self._query_generator_instance = query_generator
        self._credential_checker = credential_checker
        self._credentials_checked = False

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
        dev_out_dir: str | None = ".dev",
        harmonization_details_out: str | None = None,
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        harmonization_options: dict | None = None,
    ) -> dict:
        run_id = self._dev_run_id()
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
            dev_out_dir=dev_out_dir,
            dev_run_id=run_id,
            generate_queries=generate_queries,
            max_generated_queries=max_generated_queries,
        )
        logger.info(
            "Atlas create_atlas progress stage=collect-datasets-complete accessions=%s publication_texts=%s",
            len(datasets.get("accessions", [])),
            len(datasets.get("publication_texts", {})),
        )
        logger.info("Atlas create_atlas progress stage=harmonize-datasets")
        result = self.harmonize_datasets(
            datasets=datasets,
            harmonization_details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
        )
        self._write_dev_json(
            stage_name="03_harmonized_datasets",
            result=result,
            dev_out_dir=dev_out_dir,
            run_id=run_id,
        )
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
        dev_out_dir: str | None = ".dev",
        dev_run_id: str | None = None,
        generate_queries: bool = False,
        max_generated_queries: int = 3,
    ) -> dict:
        run_id = dev_run_id or self._dev_run_id()
        if generate_queries or theme is not None:
            self._preflight_credentials()
        if generate_queries:
            query = self._queries_with_generated(
                query=query,
                file=file,
                theme=theme,
                max_generated_queries=max_generated_queries,
            )
            file = None
        logger.info("Atlas collect_datasets progress stage=collect-accessions")
        accessions = self._collect_jsons(
            query=query,
            file=file,
            out=None,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            collect_metadata=collect_metadata,
        )
        self._write_dev_json(
            stage_name="01_collected_accessions",
            result=accessions,
            dev_out_dir=dev_out_dir,
            run_id=run_id,
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
        self._write_dev_json(
            stage_name="02_collected_datasets",
            result=result,
            dev_out_dir=dev_out_dir,
            run_id=run_id,
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

    def harmonize_datasets(
        self,
        datasets: dict,
        harmonization_details_out: str | None = None,
        harmonization_options: dict | None = None,
    ) -> dict:
        result, _ = self._harmonizer.harmonize_datasets(
            datasets=datasets,
            details_out=harmonization_details_out,
            harmonization_options=harmonization_options,
        )
        return result

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

    def _harmonize_jsons(self, datasets: dict) -> dict:
        return self._harmonizer.harmonize_jsons(datasets=datasets)

    def _queries_with_generated(
        self,
        query: list[str] | None,
        file: str | None,
        theme: str | None,
        max_generated_queries: int,
    ) -> list[str]:
        if theme is None or not theme.strip():
            raise ValueError("generate_queries requires a non-empty theme")

        queries = list(query or [])
        if file is not None:
            queries.extend(self._load_queries(file=file))

        generated = self._query_generator().generate_queries(
            theme,
            max_queries=max_generated_queries,
        )
        generated_queries = generated.get("queries")
        if not isinstance(generated_queries, list) or not all(
            isinstance(value, str) and value.strip() for value in generated_queries
        ):
            raise ValueError("query generator returned an invalid queries list")

        queries.extend(generated_queries)
        return queries

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _query_generator(self):
        if self._query_generator_instance is None:
            from agentic_curator import QueryGenerator

            self._query_generator_instance = QueryGenerator()
        return self._query_generator_instance

    def _preflight_credentials(self) -> None:
        if self._credential_checker is None or self._credentials_checked:
            return
        self._credential_checker.check()
        self._credentials_checked = True

    def _write_json(self, result: dict | list[dict], out: str) -> None:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)

    def _write_dev_json(
        self,
        stage_name: str,
        result: dict | list[dict],
        dev_out_dir: str | None,
        run_id: str,
    ) -> None:
        if dev_out_dir is None:
            return

        path = self._dev_output_path(
            stage_name=stage_name,
            dev_out_dir=dev_out_dir,
            run_id=run_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Atlas dev snapshot progress stage=%s output_path=%s",
            stage_name,
            path,
        )
        self._write_json(result=result, out=str(path))

    def _dev_output_path(self, stage_name: str, dev_out_dir: str, run_id: str) -> Path:
        return Path(dev_out_dir) / f"{run_id}_{stage_name}.json"

    def _dev_run_id(self) -> str:
        return datetime.now().strftime("%Y%m%dT%H%M%S")
