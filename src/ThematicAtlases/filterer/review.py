import json
import logging

from agentic_curator.curators.ontology_harmonizer import (
    build_miniml_metadata_context,
)

ACCESSIONS = "accessions"
AGENTIC_CURATOR = "agentic_curator"
PUBLICATIONS = "publications"
PUBLICATION_TEXTS = "publication_texts"
PUBLICATION_TEXT_REF = "publication_text_ref"

REVIEW_FILTERS = {
    "none",
    "not_relevant",
    "not_relevant_and_unsure",
}

logger = logging.getLogger(__name__)


class PublicationTextReviewer:
    def __init__(self, reviewer_factory=None):
        self._reviewer_factory = reviewer_factory

    def validate_options(self, theme: str | None, review_filter: str) -> None:
        if review_filter not in REVIEW_FILTERS:
            raise ValueError(
                f"Unsupported review_filter: {review_filter!r}. "
                f"Expected one of: {', '.join(sorted(REVIEW_FILTERS))}."
            )

        if theme is None and review_filter != "none":
            raise ValueError("review_filter requires a theme.")

    def review_and_filter(
        self,
        accessions: list[dict],
        publication_texts: dict,
        theme: str | None,
        review_filter: str,
        reviewer=None,
    ) -> tuple[list[dict], dict]:
        if theme is None:
            return accessions, publication_texts

        publication_texts = self.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self.publication_review_contexts(accessions=accessions),
            theme=theme,
            reviewer=reviewer,
        )
        return self.filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter=review_filter,
        )

    def publication_review_contexts(self, accessions: list[dict]) -> dict:
        contexts = {}

        for record in accessions:
            for publication in record.get(PUBLICATIONS, []):
                publication_ref = publication.get(PUBLICATION_TEXT_REF, "")

                if not publication_ref or publication_ref in contexts:
                    continue

                contexts[publication_ref] = {
                    "title": publication.get("title", ""),
                    "metadata": build_miniml_metadata_context(
                        record.get("accession_metadata")
                    ),
                }

        return contexts

    def review_publication_texts(
        self,
        publication_texts: dict,
        contexts: dict,
        theme: str,
        reviewer=None,
    ) -> dict:
        reviewer = reviewer or self._reviewer()
        reviewed_publication_texts = {}
        reviewed_count = 0
        reused_count = 0

        for publication_ref, publication_text in publication_texts.items():
            publication_text = dict(publication_text)
            existing_review = publication_text.get(AGENTIC_CURATOR)

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
            publication_text[AGENTIC_CURATOR] = self.agentic_curator_review(
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

    def filtered_result(
        self,
        accessions: list[dict],
        publication_texts: dict,
        review_filter: str,
    ) -> tuple[list[dict], dict]:
        removed_judgements = self.removed_review_judgements(review_filter=review_filter)
        filtered_accessions = []
        used_refs = set()

        for record in accessions:
            publications = []

            for publication in record.get(PUBLICATIONS, []):
                publication_ref = publication.get(PUBLICATION_TEXT_REF, "")

                if not publication_ref:
                    continue

                publication_text = publication_texts.get(publication_ref)

                if publication_text is None:
                    continue

                judgement = self.normalized_review_judgement(
                    publication_text=publication_text
                )

                if judgement in removed_judgements:
                    continue

                publications.append(publication)
                used_refs.add(publication_ref)

            if publications:
                filtered_accessions.append({**record, PUBLICATIONS: publications})

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

    def agentic_curator_review(self, theme: str, review: dict) -> dict:
        raw_evidences = review.get("evidences", "")
        raw_judgement = review.get("judgement", "")
        evidence_object = self.json_object(raw_evidences)
        judgement_object = self.json_object(raw_judgement)

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

    def json_object(self, value) -> dict:
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

    def removed_review_judgements(self, review_filter: str) -> set[str]:
        if review_filter == "not_relevant":
            return {"not relevant"}

        if review_filter == "not_relevant_and_unsure":
            return {"not relevant", "unsure"}

        return set()

    def normalized_review_judgement(self, publication_text: dict) -> str:
        agentic_curator = publication_text.get(AGENTIC_CURATOR, {})

        if not isinstance(agentic_curator, dict):
            return ""

        return " ".join(
            str(agentic_curator.get("judgement", "")).lower().replace("_", " ").split()
        )

    def _reviewer(self):
        if self._reviewer_factory is not None:
            return self._reviewer_factory()

        from agentic_curator import ThematicReviewer

        return ThematicReviewer()
