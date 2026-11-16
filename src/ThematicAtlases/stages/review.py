"""PublicationReviewStage: a typed operation shared by caller-specific scheduling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .results import ReviewResult
if TYPE_CHECKING:
    from ThematicAtlases.filterer.review import PublicationTextReviewer
import inspect
from ThematicAtlases.checkpoint import failure_category, is_retryable_error
from ThematicAtlases.runtime_contracts import safe_error_json, safe_error_mapping
import logging
logger = logging.getLogger("ThematicAtlases.filterer.review")


@dataclass(frozen=True, kw_only=True)
class PublicationReviewRequest:
    publication_ref: str
    publication_text: dict
    context: dict
    theme: str
    reviewer: Any
    checkpoint_store: Any
    index: int
    input_hash: str
    identity_hash: str
    strategy: str
    reviewer_identity: dict
    criteria: list[dict[str, str]] | None
    review_filter: str = "none"


class PublicationReviewStage:
    def __init__(self, owner: PublicationTextReviewer):
        self.owner = owner

    def run(self, request: PublicationReviewRequest) -> ReviewResult:
        return ReviewResult(**self._execute(
            publication_ref=request.publication_ref,
            publication_text=request.publication_text,
            context=request.context,
            theme=request.theme,
            reviewer=request.reviewer,
            checkpoint_store=request.checkpoint_store,
            index=request.index,
            input_hash=request.input_hash,
            identity_hash=request.identity_hash,
            strategy=request.strategy,
            reviewer_identity=request.reviewer_identity,
            criteria=request.criteria,
        ))

    def _execute(
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
        reviewer_identity: dict,
        criteria: list[dict[str, str]] | None,
    ) -> dict:
        stage_owner = self.owner
        from ThematicAtlases.filterer.review import AGENTIC_CURATOR, REVIEW_CONTRACT_VERSION
        from ThematicAtlases.runtime.evidence import reference_text
        text_ref = reference_text(checkpoint_store, publication_ref, publication_text) if checkpoint_store is not None else None
        checkpoint_key = stage_owner._review_checkpoint_key(strategy, publication_ref)
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
            if payload.get("text_ref") == text_ref and payload.get("review") is not None:
                publication_text = {**publication_text, AGENTIC_CURATOR: payload["review"]}

        existing_review = publication_text.get(AGENTIC_CURATOR)
        coverage_context = stage_owner._metadata_context(context)
        if (
            isinstance(existing_review, dict)
            and existing_review.get("theme") == theme
            and existing_review.get("strategy") == strategy
            and existing_review.get("review_input_hash") == input_hash
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
            if criteria is not None:
                review_options["criteria"] = criteria
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
            logger.error(
                "Atlas thematic review failed publication_ref=%s error_type=%s; retaining publication as unreviewed",
                publication_ref,
                type(error).__name__,
            )
            safe_error = safe_error_mapping(
                error,
                provider="agentic_curator",
                stage="thematic_review",
                item_id=publication_ref,
                retryable=is_retryable_error(error),
            )
            failed_review = {
                "theme": theme,
                "strategy": strategy,
                "review_status": "failed",
                "error_type": type(error).__name__,
                "error": safe_error,
                "review_input_hash": input_hash,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
                "reviewer_identity": reviewer_identity,
            }
            if coverage_context is not None:
                failed_review["metadata_context"] = coverage_context
            publication_text[AGENTIC_CURATOR] = failed_review
            if checkpoint_store is not None:
                checkpoint_store.put(
                    "thematic_review",
                    checkpoint_key,
                    index,
                    "retryable_error"
                    if is_retryable_error(error)
                    else "terminal_error",
                    payload={
                        "text_ref": text_ref,
                        "review": publication_text[AGENTIC_CURATOR],
                        "input_hash": input_hash,
                        "identity_hash": identity_hash,
                        "review_contract_version": REVIEW_CONTRACT_VERSION,
                        "strategy": strategy,
                        "publication_ref": publication_ref,
                        "reviewer_identity": reviewer_identity,
                        **(
                            {"next_retry_at": float(error.retry_at)}
                            if getattr(error, "retry_at", None) is not None
                            else {}
                        ),
                    },
                    error=safe_error_json(
                        error,
                        provider="agentic_curator",
                        stage="thematic_review",
                        item_id=publication_ref,
                        retryable=is_retryable_error(error),
                    ),
                    error_type=type(error).__name__,
                    failure_category=failure_category(error),
                )
            return {
                "publication_text": publication_text,
                "reviewed": 0,
                "reused": 0,
                "failed": 1,
            }

        publication_text[AGENTIC_CURATOR] = stage_owner.agentic_curator_review(
            theme=theme,
            review=review,
            strategy=strategy,
            review_input_hash=input_hash,
            metadata_context=coverage_context,
            reviewer_identity=reviewer_identity,
        )
        if checkpoint_store is not None:
            checkpoint_store.put(
                "thematic_review",
                checkpoint_key,
                index,
                "available",
                payload={
                    "text_ref": text_ref,
                    "review": publication_text[AGENTIC_CURATOR],
                    "input_hash": input_hash,
                    "identity_hash": identity_hash,
                    "review_contract_version": REVIEW_CONTRACT_VERSION,
                    "strategy": strategy,
                    "publication_ref": publication_ref,
                    "reviewer_identity": reviewer_identity,
                },
            )
        return {
            "publication_text": publication_text,
            "reviewed": 1,
            "reused": 0,
            "failed": 0,
        }

