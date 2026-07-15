import json
import logging
import hashlib
import inspect
import re
from contextlib import nullcontext
from pathlib import Path

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
REVIEW_STRATEGIES = {"direct", "evidence_then_judgement"}
REVIEW_CONTRACT_VERSION = 4

logger = logging.getLogger(__name__)


class PublicationTextReviewer:
    def __init__(self, reviewer_factory=None, resume_orchestrator_factory=None):
        self._reviewer_factory = reviewer_factory
        self._resume_orchestrator_factory = resume_orchestrator_factory
        self._resume_orchestrator_instance = None

    def resume(
        self,
        trace_dir: str | Path,
        *,
        theme: str | None = None,
        reviewer=None,
        strategy: str = "direct",
        allow_theme_override: bool = False,
    ) -> dict:
        """Review the current publication snapshot in an evolving trace."""
        return self._resume_orchestrator().resume(
            trace_dir=trace_dir,
            theme=theme,
            reviewer=reviewer,
            strategy=strategy,
            allow_theme_override=allow_theme_override,
        )

    def validate_options(
        self,
        theme: str | None,
        review_filter: str,
        strategy: str = "direct",
    ) -> None:
        if review_filter not in REVIEW_FILTERS:
            raise ValueError(
                f"Unsupported review_filter: {review_filter!r}. "
                f"Expected one of: {', '.join(sorted(REVIEW_FILTERS))}."
            )

        if theme is None and review_filter != "none":
            raise ValueError("review_filter requires a theme.")
        if strategy not in REVIEW_STRATEGIES:
            raise ValueError(
                f"Unsupported review_strategy: {strategy!r}. Expected one of: "
                f"{', '.join(sorted(REVIEW_STRATEGIES))}."
            )

    def review_and_filter(
        self,
        accessions: list[dict],
        publication_texts: dict,
        theme: str | None,
        review_filter: str,
        reviewer=None,
        strategy: str = "direct",
    ) -> tuple[list[dict], dict]:
        if theme is None:
            return accessions, publication_texts

        publication_texts = self.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self.publication_review_contexts(accessions=accessions),
            theme=theme,
            reviewer=reviewer,
            strategy=strategy,
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

                if not publication_ref:
                    continue

                context = contexts.setdefault(
                    publication_ref,
                    {
                        "title": "",
                        "metadata": [],
                        "accessions": [],
                        "metadata_statuses": {},
                    },
                )
                if not context["title"] and publication.get("title"):
                    context["title"] = publication.get("title", "")
                accession = str(record.get("datalink_id", "")).strip()
                if re.fullmatch(r"GSE\d+", accession, flags=re.IGNORECASE):
                    accession = accession.upper()
                    if accession not in context["accessions"]:
                        context["accessions"].append(accession)
                metadata = build_miniml_metadata_context(
                    record.get("accession_metadata")
                )
                if metadata:
                    metadata_entry = {"accession": accession, "context": metadata}
                    if metadata_entry not in context["metadata"]:
                        context["metadata"].append(metadata_entry)
                    context["metadata_statuses"][accession] = "available"
                elif accession:
                    status = str(record.get("metadata_status") or "pending")
                    if status == "available":
                        status = "available_but_empty"
                    context["metadata_statuses"][accession] = status

        return contexts

    def review_publication_texts(
        self,
        publication_texts: dict,
        contexts: dict,
        theme: str,
        reviewer=None,
        progress_callback=None,
        checkpoint_store=None,
        strategy: str = "direct",
    ) -> dict:
        self.validate_options(theme=theme, review_filter="none", strategy=strategy)
        reviewer = reviewer or self._reviewer()
        reviewed_publication_texts = {}
        reviewed_count = 0
        reused_count = 0
        failed_count = 0

        total = len(publication_texts)
        for index, (publication_ref, publication_text) in enumerate(
            publication_texts.items(), start=1
        ):
            if index == 1 or index == total or index % 10 == 0:
                logger.info(
                    "Atlas thematic review progress publication_index=%s publication_total=%s publication_ref=%s",
                    index,
                    total,
                    publication_ref,
                )
            publication_text = dict(publication_text)
            context = contexts.get(publication_ref, {})
            input_hash = self._review_input_hash(
                publication_text=publication_text,
                context=context,
                theme=theme,
                strategy=strategy,
            )
            identity_hash = self._review_identity_hash(
                publication_text=publication_text,
                context=context,
                theme=theme,
                strategy=strategy,
            )
            item_lock = (
                checkpoint_store.item_lock(
                    "thematic_review",
                    self._review_checkpoint_key(strategy, publication_ref),
                )
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                outcome = self._review_checkpoint_item(
                    publication_ref=publication_ref,
                    publication_text=publication_text,
                    context=context,
                    theme=theme,
                    reviewer=reviewer,
                    checkpoint_store=checkpoint_store,
                    index=index,
                    input_hash=input_hash,
                    identity_hash=identity_hash,
                    strategy=strategy,
                )
            reviewed_publication_texts[publication_ref] = outcome["publication_text"]
            reviewed_count += outcome["reviewed"]
            reused_count += outcome["reused"]
            failed_count += outcome["failed"]
            if progress_callback is not None:
                progress_callback(reviewed_publication_texts)

        logger.info(
            "Atlas thematic review stats publication_texts=%s reviewed=%s reused=%s failed=%s",
            len(publication_texts),
            reviewed_count,
            reused_count,
            failed_count,
        )
        return reviewed_publication_texts

    def _review_checkpoint_item(
        self,
        *,
        publication_ref: str,
        publication_text: dict,
        context: dict,
        theme: str,
        reviewer,
        checkpoint_store,
        index: int,
        input_hash: str,
        identity_hash: str,
        strategy: str,
    ) -> dict:
        checkpoint_key = self._review_checkpoint_key(strategy, publication_ref)
        checkpoint = (
            checkpoint_store.get("thematic_review", checkpoint_key)
            if checkpoint_store is not None
            else None
        )
        payload = (checkpoint or {}).get("payload") or {}
        if checkpoint and checkpoint["status"] in {
            "available",
            "terminal_error",
        } and (
            payload.get("input_hash") == input_hash
        ):
            publication_text = dict(
                payload.get("publication_text", publication_text)
            )

        existing_review = publication_text.get(AGENTIC_CURATOR)
        coverage_context = self._metadata_context(context)
        metadata_changes_review = any(
            status != "pending"
            for status in (context.get("metadata_statuses") or {}).values()
        )
        if (
            isinstance(existing_review, dict)
            and existing_review.get("theme") == theme
            and existing_review.get("strategy") == strategy
            and (
                "metadata_statuses" not in context
                or (
                    not metadata_changes_review
                    and existing_review.get("review_input_hash") is None
                )
                or existing_review.get("review_input_hash") == input_hash
            )
        ):
            return {
                "publication_text": publication_text,
                "reviewed": 0,
                "reused": 1,
                "failed": 0,
            }

        try:
            review_options = {
                "publication_text": publication_text.get("text", ""),
                "theme": theme,
                "metadata": context.get("metadata"),
                "title": context.get("title"),
                "accessions": context.get("accessions", []),
                "strategy": strategy,
            }
            signature = inspect.signature(reviewer.review_relevancy)
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            if not accepts_kwargs:
                review_options = {
                    key: value
                    for key, value in review_options.items()
                    if key in signature.parameters
                }
            review = reviewer.review_relevancy(
                **review_options
            )
        except Exception as error:
            logger.exception(
                "Atlas thematic review failed publication_ref=%s; retaining publication as unreviewed",
                publication_ref,
            )
            failed_review = {
                "theme": theme,
                "strategy": strategy,
                "review_status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
            }
            if coverage_context is not None:
                failed_review.update(
                    {
                        "review_input_hash": input_hash,
                        "review_contract_version": REVIEW_CONTRACT_VERSION,
                        "metadata_context": coverage_context,
                    }
                )
            publication_text[AGENTIC_CURATOR] = failed_review
            if checkpoint_store is not None:
                checkpoint_store.put(
                    "thematic_review",
                    checkpoint_key,
                    index,
                    "terminal_error",
                    payload={
                        "publication_text": publication_text,
                        "input_hash": input_hash,
                        "identity_hash": identity_hash,
                        "review_contract_version": REVIEW_CONTRACT_VERSION,
                        "strategy": strategy,
                        "publication_ref": publication_ref,
                    },
                    error=str(error),
                )
            return {
                "publication_text": publication_text,
                "reviewed": 0,
                "reused": 0,
                "failed": 1,
            }

        publication_text[AGENTIC_CURATOR] = self.agentic_curator_review(
            theme=theme,
            review=review,
            strategy=strategy,
            review_input_hash=input_hash,
            metadata_context=coverage_context,
        )
        if checkpoint_store is not None:
            checkpoint_store.put(
                "thematic_review",
                checkpoint_key,
                index,
                "available",
                payload={
                    "publication_text": publication_text,
                    "input_hash": input_hash,
                    "identity_hash": identity_hash,
                    "review_contract_version": REVIEW_CONTRACT_VERSION,
                    "strategy": strategy,
                    "publication_ref": publication_ref,
                },
            )
        return {
            "publication_text": publication_text,
            "reviewed": 1,
            "reused": 0,
            "failed": 0,
        }

    @staticmethod
    def _review_input_hash(
        publication_text: dict,
        context: dict,
        theme: str,
        strategy: str = "direct",
    ) -> str:
        value = json.dumps(
            {
                "text": publication_text.get("text", ""),
                "theme": theme,
                "context": context,
                "strategy": strategy,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _review_identity_hash(
        publication_text: dict,
        context: dict,
        theme: str,
        strategy: str = "direct",
    ) -> str:
        value = json.dumps(
            {
                "text": publication_text.get("text", ""),
                "theme": theme,
                "title": context.get("title", ""),
                "accessions": context.get("accessions", []),
                "strategy": strategy,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

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

    @staticmethod
    def _review_checkpoint_key(strategy: str, publication_ref: str) -> str:
        return f"{strategy}:{publication_ref}"

    def agentic_curator_review(
        self,
        theme: str,
        review: dict,
        strategy: str = "direct",
        review_input_hash: str | None = None,
        metadata_context: dict | None = None,
    ) -> dict:
        direct_judgement = " ".join(
            str(review.get("judgement", "")).lower().replace("_", " ").split()
        )
        if direct_judgement in {"relevant", "not relevant", "unsure"}:
            removals = review.get("accessions_to_remove", [])
            if not isinstance(removals, list):
                removals = []
            result = {
                "theme": theme,
                "strategy": str(review.get("strategy", strategy)),
                "evidences": review.get("evidences", []),
                "judgement": str(review.get("judgement", "")),
                "reasoning": str(review.get("reasoning", "")),
                "confidence": str(review.get("confidence", "")),
                "accessions_to_remove": removals,
                "accession_assessments": review.get(
                    "accession_assessments", []
                ),
                "review_revision": review.get("review_revision"),
                "raw_review": review,
            }
            if metadata_context is not None:
                result["metadata_context"] = metadata_context
                result["review_input_hash"] = review_input_hash
                result["review_contract_version"] = REVIEW_CONTRACT_VERSION
            return result
        raw_evidences = review.get("evidences", "")
        raw_judgement = review.get("judgement", "")
        evidence_object = self.json_object(raw_evidences)
        judgement_object = self.json_object(raw_judgement)

        evidences = evidence_object.get("evidences", [])
        if not isinstance(evidences, list):
            evidences = []

        result = {
            "theme": theme,
            "strategy": strategy,
            "evidences": evidences,
            "judgement": str(judgement_object.get("judgement", "")),
            "reasoning": str(judgement_object.get("reasoning", "")),
            "confidence": str(judgement_object.get("confidence", "")),
            "raw_evidences": raw_evidences,
            "raw_judgement": raw_judgement,
            "accessions_to_remove": judgement_object.get(
                "accessions_to_remove", []
            ),
        }
        if metadata_context is not None:
            result["metadata_context"] = metadata_context
            result["review_input_hash"] = review_input_hash
            result["review_contract_version"] = REVIEW_CONTRACT_VERSION
        return result

    @staticmethod
    def _metadata_context(context: dict) -> dict | None:
        if "metadata_statuses" not in context:
            return None
        statuses = dict(context.get("metadata_statuses") or {})
        used = [
            item.get("accession")
            for item in context.get("metadata", [])
            if item.get("accession")
        ]
        accessions = list(context.get("accessions") or [])
        return {
            "used_accessions": [accession for accession in accessions if accession in used],
            "not_used_accessions": [accession for accession in accessions if accession not in used],
            "statuses": {accession: statuses.get(accession, "pending") for accession in accessions},
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

        if agentic_curator.get("review_status") == "failed":
            return ""

        return " ".join(
            str(agentic_curator.get("judgement", "")).lower().replace("_", " ").split()
        )

    def _reviewer(self):
        if self._reviewer_factory is not None:
            return self._reviewer_factory()

        from agentic_curator import ThematicReviewer

        return ThematicReviewer()

    def _resume_orchestrator(self):
        if self._resume_orchestrator_instance is not None:
            return self._resume_orchestrator_instance

        if self._resume_orchestrator_factory is not None:
            self._resume_orchestrator_instance = self._resume_orchestrator_factory(
                self
            )
            return self._resume_orchestrator_instance

        from ThematicAtlases.filterer.resume import TracePublicationReviewResumer

        self._resume_orchestrator_instance = TracePublicationReviewResumer(self)
        return self._resume_orchestrator_instance
