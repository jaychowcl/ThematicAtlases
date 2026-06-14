import json
import logging

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")
REVIEW_FILTERS = {
    "none",
    "not_relevant",
    "not_relevant_and_unsure",
}
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
                list(jsons.get("accessions", [])),
                dict(jsons.get("publication_texts", {})),
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
            for publication in record.get("publications", []):
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
        enriched_publications = EuropePMCWrapper().collect_publication_texts(
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

    def _validate_review_options(self, theme: str | None, review_filter: str) -> None:
        if review_filter not in REVIEW_FILTERS:
            raise ValueError(
                f"Unsupported review_filter: {review_filter!r}. "
                f"Expected one of: {', '.join(sorted(REVIEW_FILTERS))}."
            )

        if theme is None and review_filter != "none":
            raise ValueError("review_filter requires a theme.")

    def _publication_review_contexts(self, accessions: list[dict]) -> dict:
        contexts = {}

        for record in accessions:
            for publication in record.get("publications", []):
                publication_ref = publication.get("publication_text_ref", "")

                if not publication_ref or publication_ref in contexts:
                    continue

                contexts[publication_ref] = {
                    "title": publication.get("title", ""),
                    "metadata": record.get("accession_metadata"),
                }

        return contexts

    def _review_publication_texts(
        self,
        publication_texts: dict,
        contexts: dict,
        theme: str | None,
        reviewer=None,
    ) -> dict:
        if theme is None:
            return publication_texts

        reviewer = reviewer or self._thematic_reviewer()
        reviewed_publication_texts = {}
        reviewed_count = 0
        reused_count = 0

        for publication_ref, publication_text in publication_texts.items():
            publication_text = dict(publication_text)
            existing_review = publication_text.get("agentic_curator")

            if (
                isinstance(existing_review, dict)
                and existing_review.get("theme") == theme
            ):
                reviewed_publication_texts[publication_ref] = publication_text
                reused_count += 1
                continue

            context = contexts.get(publication_ref, {})
            review = reviewer.review_relevancy(
                publication_text=publication_text.get("text", ""),
                theme=theme,
                metadata=context.get("metadata"),
                title=context.get("title"),
            )
            publication_text["agentic_curator"] = self._agentic_curator_review(
                theme=theme,
                review=review,
            )
            reviewed_publication_texts[publication_ref] = publication_text
            reviewed_count += 1

        logger.info(
            "Atlas thematic review stats publication_texts=%s reviewed=%s reused=%s",
            len(publication_texts),
            reviewed_count,
            reused_count,
        )
        return reviewed_publication_texts

    def _thematic_reviewer(self):
        from agentic_curator import ThematicReviewer

        return ThematicReviewer()

    def _agentic_curator_review(self, theme: str, review: dict) -> dict:
        raw_evidences = review.get("evidences", "")
        raw_judgement = review.get("judgement", "")
        evidence_object = self._json_object(raw_evidences)
        judgement_object = self._json_object(raw_judgement)

        evidences = evidence_object.get("evidences", [])
        if not isinstance(evidences, list):
            evidences = []

        return {
            "theme": theme,
            "evidences": evidences,
            "judgement": str(judgement_object.get("judgement", "")),
            "reasoning": str(judgement_object.get("reasoning", "")),
            "confidence": str(judgement_object.get("confidence", "")),
            "raw_evidences": raw_evidences,
            "raw_judgement": raw_judgement,
        }

    def _json_object(self, value) -> dict:
        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}

            if isinstance(parsed, dict):
                return parsed

        return {}

    def _review_filtered_result(
        self,
        accessions: list[dict],
        publication_texts: dict,
        review_filter: str,
    ) -> tuple[list[dict], dict]:
        removed_judgements = self._removed_review_judgements(review_filter=review_filter)
        filtered_accessions = []
        used_refs = set()

        for record in accessions:
            publications = []

            for publication in record.get("publications", []):
                publication_ref = publication.get("publication_text_ref", "")

                if not publication_ref:
                    continue

                publication_text = publication_texts.get(publication_ref)

                if publication_text is None:
                    continue

                judgement = self._normalized_review_judgement(
                    publication_text=publication_text
                )

                if judgement in removed_judgements:
                    continue

                publications.append(publication)
                used_refs.add(publication_ref)

            if publications:
                filtered_accessions.append({**record, "publications": publications})

        filtered_publication_texts = {
            publication_ref: publication_texts[publication_ref]
            for publication_ref in publication_texts
            if publication_ref in used_refs
        }
        logger.info(
            "Atlas thematic filter stats review_filter=%s input_accessions=%s output_accessions=%s input_publication_texts=%s output_publication_texts=%s",
            review_filter,
            len(accessions),
            len(filtered_accessions),
            len(publication_texts),
            len(filtered_publication_texts),
        )
        return filtered_accessions, filtered_publication_texts

    def _removed_review_judgements(self, review_filter: str) -> set[str]:
        if review_filter == "not_relevant":
            return {"not relevant"}

        if review_filter == "not_relevant_and_unsure":
            return {"not relevant", "unsure"}

        return set()

    def _normalized_review_judgement(self, publication_text: dict) -> str:
        agentic_curator = publication_text.get("agentic_curator", {})

        if not isinstance(agentic_curator, dict):
            return ""

        return " ".join(
            str(agentic_curator.get("judgement", "")).lower().replace("_", " ").split()
        )

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

    def filter_jsons(
        self,
        jsons: dict | list[dict] | None = None,
        file: str | None = None,
        theme: str | None = None,
        review_filter: str = "none",
        reviewer=None,
    ) -> dict:
        self._validate_review_options(theme=theme, review_filter=review_filter)
        jsons, publication_texts = self._atlas_parts(jsons=jsons)

        if file is not None:
            file_jsons, file_publication_texts = self._atlas_parts(
                jsons=self._load_json(file=file)
            )
            jsons.extend(file_jsons)
            publication_texts.update(file_publication_texts)

        logger.info("Atlas filter_jsons progress stage=collect-publication-texts")
        publication_texts = self._collect_publication_texts(
            jsons=jsons,
            publication_texts=publication_texts,
        )
        logger.info("Atlas filter_jsons progress stage=attach-publication-text-refs")
        accessions = self._accessions_with_publication_text_refs(
            jsons=jsons,
            publication_texts=publication_texts,
        )
        if theme is not None:
            logger.info("Atlas filter_jsons progress stage=review-publication-texts")
            publication_texts = self._review_publication_texts(
                publication_texts=publication_texts,
                contexts=self._publication_review_contexts(accessions=accessions),
                theme=theme,
                reviewer=reviewer,
            )
            logger.info("Atlas filter_jsons progress stage=filter-reviewed-publications")
            accessions, publication_texts = self._review_filtered_result(
                accessions=accessions,
                publication_texts=publication_texts,
                review_filter=review_filter,
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
