import json
import logging
from datetime import datetime
from pathlib import Path

from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.filterer import AtlasFilterer
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.harmonizer import AtlasHarmonizer
from ThematicAtlases.summary import build_atlas_summary, summary_path
from ThematicAtlases.trace import DevTraceWriter
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
        ontostore=None,
        cache_ontologies: bool = False,
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
        if harmonizer is not None and (ontostore is not None or cache_ontologies):
            raise ValueError(
                "ontostore/cache_ontologies cannot be combined with a custom harmonizer"
            )
        if cache_ontologies and ontostore is None:
            from agentic_curator.curators.ontology_harmonizer import OntoStore

            ontostore = OntoStore()
        self._ontostore = ontostore
        self._cache_ontologies = cache_ontologies
        self._ontologies_cached = False
        self.ontology_cache_result = None
        self._harmonizer = harmonizer or AtlasHarmonizer(
            ontostore=ontostore,
            credential_checker=credential_checker,
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
        dev_trace: bool = False,
        dev_out_dir: str = ".dev",
        harmonization_details_out: str | None = None,
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        harmonization_options: dict | None = None,
    ) -> dict:
        self._prepare_ontology_cache()
        run_id = self._dev_run_id()
        trace = None
        if dev_trace:
            trace = DevTraceWriter(
                root=dev_out_dir,
                run_id=run_id,
                manifest={
                    "command": "create-atlas",
                    "created_at": run_id,
                    "atlas_out": out,
                    "artifacts": [
                        "00_run_manifest.json",
                        "01_collected_accessions.json",
                        "02_reviewed_datasets.json",
                        "03_pre_harmonization_accession_metadata.json",
                        "04_harmonization_details.json",
                        "05_post_harmonization_accession_metadata.json",
                        "06_final_atlas.json",
                        "07_summary.json",
                    ],
                    "query": query,
                    "query_file": file,
                    "theme": theme,
                    "review_filter": review_filter,
                    "metadata_repositories": metadata_repositories,
                    "max_publications": max_publications,
                    "collect_metadata": collect_metadata,
                    "generate_queries": generate_queries,
                    "max_generated_queries": max_generated_queries,
                    "harmonization_options": harmonization_options,
                    "harmonization_details_out": harmonization_details_out,
                },
            )
        logger.info("Atlas create_atlas progress stage=collect-datasets")
        collect_kwargs = dict(
            query=query,
            file=file,
            out=None,
            theme=theme,
            review_filter=review_filter,
            metadata_repositories=metadata_repositories,
            max_publications=max_publications,
            reviewer=reviewer,
            collect_metadata=collect_metadata,
            generate_queries=generate_queries,
            max_generated_queries=max_generated_queries,
        )
        if trace is not None:
            collect_kwargs["_trace_writer"] = trace
        datasets = self.collect_datasets(**collect_kwargs)
        logger.info(
            "Atlas create_atlas progress stage=collect-datasets-complete accessions=%s publication_texts=%s",
            len(datasets.get("accessions", [])),
            len(datasets.get("publication_texts", {})),
        )
        logger.info("Atlas create_atlas progress stage=harmonize-datasets")
        if trace is not None:
            trace.write(
                "03_pre_harmonization_accession_metadata.json",
                trace.metadata(datasets.get("accessions", [])),
            )
            result, details = self._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
            )
            trace.write("04_harmonization_details.json", details)
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
        else:
            result = self.harmonize_datasets(
                datasets=datasets,
                harmonization_details_out=harmonization_details_out,
                harmonization_options=harmonization_options,
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
            summary = build_atlas_summary(atlas=result, atlas_path=out)
            self._write_json(result=summary, out=str(summary_path(out)))
        else:
            summary = build_atlas_summary(atlas=result)

        if trace is not None:
            trace.write("06_final_atlas.json", result)
            trace.write("07_summary.json", summary)

        logger.info(
            "Atlas create_atlas stats final_accessions=%s publication_texts=%s output_path=%s",
            len(final_accessions),
            len(publication_texts),
            out,
        )
        return result

    def resume(
        self,
        dev_out_dir: str = ".dev",
        run_id: str | None = None,
        out: str | None = None,
    ) -> dict:
        """Resume an incomplete development trace from its latest valid stage."""
        run_dir = self._resume_run_directory(dev_out_dir=dev_out_dir, run_id=run_id)
        manifest = self._read_checkpoint(run_dir / "00_run_manifest.json")
        trace = DevTraceWriter.existing(run_dir)
        output_path = out if out is not None else manifest.get("atlas_out")
        self._prepare_ontology_cache()
        if manifest.get("theme") is not None:
            self._preflight_credentials()
        logger.info("Atlas resume selected run_id=%s run_dir=%s", run_dir.name, run_dir)

        final_path = run_dir / "06_final_atlas.json"
        if final_path.exists():
            result = self._read_checkpoint(final_path)
            logger.info("Atlas resume progress stage=final-atlas-complete")
            self._write_resumed_outputs(result=result, out=output_path, trace=trace)
            return result

        harmonized_path = run_dir / "resume_harmonized_datasets.json"
        if harmonized_path.exists():
            result = self._read_checkpoint(harmonized_path)
            logger.info("Atlas resume progress stage=harmonization-complete")
        else:
            reviewed_path = run_dir / "02_reviewed_datasets.json"
            if reviewed_path.exists():
                datasets = self._read_checkpoint(reviewed_path)
                logger.info("Atlas resume progress stage=review-complete")
            else:
                collected_path = run_dir / "01_collected_accessions.json"
                if collected_path.exists():
                    accessions = self._read_checkpoint(collected_path)
                    logger.info("Atlas resume progress stage=collection-complete")
                    progress_path = run_dir / "resume_review_progress.json"
                    review_input = (
                        self._read_checkpoint(progress_path)
                        if progress_path.exists()
                        else accessions
                    )
                    datasets = self._filter_jsons(
                        jsons=review_input,
                        theme=manifest.get("theme"),
                        review_filter=manifest.get("review_filter", "none"),
                        _review_progress_callback=lambda texts: trace.write(
                            "resume_review_progress.json",
                            {"accessions": self._filterer.accessions_with_publication_text_refs(accessions, texts), "publication_texts": texts},
                        ),
                    )
                    trace.write("02_reviewed_datasets.json", datasets)
                else:
                    logger.info("Atlas resume progress stage=collection-required")
                    datasets = self.collect_datasets(
                        query=manifest.get("query"),
                        file=manifest.get("query_file"),
                        theme=manifest.get("theme"),
                        review_filter=manifest.get("review_filter", "none"),
                        metadata_repositories=manifest.get("metadata_repositories"),
                        max_publications=manifest.get("max_publications"),
                        collect_metadata=manifest.get("collect_metadata", True),
                        generate_queries=manifest.get("generate_queries", False),
                        max_generated_queries=manifest.get("max_generated_queries", 3),
                        _trace_writer=trace,
                    )

            trace.write(
                "03_pre_harmonization_accession_metadata.json",
                trace.metadata(datasets.get("accessions", [])),
            )
            result, details = self._harmonizer.harmonize_datasets(
                datasets=datasets,
                details_out=manifest.get("harmonization_details_out"),
                harmonization_options=manifest.get("harmonization_options"),
            )
            trace.write("04_harmonization_details.json", details)
            trace.write(
                "05_post_harmonization_accession_metadata.json",
                trace.metadata(result.get("accessions", [])),
            )
            trace.write("resume_harmonized_datasets.json", result)

        self._write_resumed_outputs(result=result, out=output_path, trace=trace)
        logger.info("Atlas resume stats run_id=%s accessions=%s", run_dir.name, len(result.get("accessions", [])))
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
        generate_queries: bool = False,
        max_generated_queries: int = 3,
        _trace_writer: DevTraceWriter | None = None,
    ) -> dict:
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
        if _trace_writer is not None:
            _trace_writer.write("01_collected_accessions.json", accessions)
        logger.info(
            "Atlas collect_datasets progress stage=collect-accessions-complete accessions=%s",
            len(accessions),
        )
        logger.info("Atlas collect_datasets progress stage=map-publication-texts")
        review_progress_callback = None
        if _trace_writer is not None:
            review_progress_callback = lambda texts: _trace_writer.write(
                "resume_review_progress.json",
                {
                    "accessions": self._filterer.accessions_with_publication_text_refs(
                        accessions, texts
                    ),
                    "publication_texts": texts,
                },
            )
        result = self._filter_jsons(
            jsons=accessions,
            theme=theme,
            review_filter=review_filter,
            reviewer=reviewer,
            _review_progress_callback=review_progress_callback,
        )
        if _trace_writer is not None:
            _trace_writer.write("02_reviewed_datasets.json", result)
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
        _review_progress_callback=None,
    ) -> dict:
        options = dict(
            jsons=jsons,
            file=file,
            theme=theme,
            review_filter=review_filter,
            reviewer=reviewer,
        )
        if _review_progress_callback is not None:
            options["_review_progress_callback"] = _review_progress_callback
        return self._filterer.filter_jsons(**options)

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

    def _prepare_ontology_cache(self) -> None:
        if not self._cache_ontologies or self._ontologies_cached:
            return
        self.ontology_cache_result = self._ontostore.cache_all()
        self._ontologies_cached = True

    def _write_json(self, result: dict | list[dict], out: str) -> None:
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)

    def _write_resumed_outputs(self, result: dict, out: str | None, trace: DevTraceWriter) -> None:
        if out is not None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            self._write_json(result=result, out=out)
            summary = build_atlas_summary(atlas=result, atlas_path=out)
            self._write_json(result=summary, out=str(summary_path(out)))
        else:
            summary = build_atlas_summary(atlas=result)
        trace.write("06_final_atlas.json", result)
        trace.write("07_summary.json", summary)

    def _resume_run_directory(self, dev_out_dir: str, run_id: str | None) -> Path:
        root = Path(dev_out_dir)
        if run_id is not None:
            candidate = Path(run_id)
            run_dir = candidate if candidate.is_dir() else root / run_id
            self._read_checkpoint(run_dir / "00_run_manifest.json")
            return run_dir

        candidates = []
        for run_dir in root.iterdir() if root.is_dir() else []:
            manifest_path = run_dir / "00_run_manifest.json"
            final_path = run_dir / "06_final_atlas.json"
            if not run_dir.is_dir() or not manifest_path.exists() or final_path.exists():
                continue
            try:
                self._read_checkpoint(manifest_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            candidates.append(run_dir)
        if not candidates:
            raise FileNotFoundError(f"No incomplete valid trace found under {root}")
        return max(candidates, key=lambda path: path.name)

    def _read_checkpoint(self, path: Path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _dev_run_id(self) -> str:
        return datetime.now().strftime("%Y%m%dT%H%M%S")
