from ThematicAtlases.stages.review import PublicationReviewStage, PublicationReviewRequest
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
from ThematicAtlases.filterer.resume import TracePublicationReviewResumer
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry

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
REVIEW_STRATEGIES = {"direct"}
REVIEW_CONTRACT_VERSION = 12
_CRITERION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

logger = logging.getLogger(__name__)


def validate_max_review_criteria(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_review_criteria must be a positive integer")
    return value


class PublicationTextReviewer:
    def __init__(
        self,
        reviewer_factory=None,
        resume_orchestrator_factory=None,
        capability_registry: RepositoryCapabilityRegistry | None = None,
        cancelled=None,
    ):
        self._reviewer_factory = reviewer_factory
        self._resume_orchestrator_factory = resume_orchestrator_factory
        self._resume_orchestrator_instance = None
        self._capability_registry = (
            capability_registry or RepositoryCapabilityRegistry()
        )
        self._cancelled = cancelled

    def resume(
        self,
        trace_dir: str | Path,
        *,
        theme: str | None = None,
        reviewer=None,
        strategy: str = "direct",
        allow_theme_override: bool = False,
        require_resolved_metadata: bool = False,
        collect_metadata: bool = False,
        defer_metadata_errors: bool = False,
        require_main_datalinks_phase: bool = False,
        publication_limit: int | None = None,
        review_action_limit: int | None = None,
        cancelled=None,
        snapshot_accessions: list[dict] | None = None,
        publication_keys: list[tuple] | None = None,
        item_lock_timeout_seconds: int | float | None = None,
        metadata_item_timeout_seconds: int | float | None = None,
        publication_text_item_timeout_seconds: int | float | None = None,
        review_item_timeout_seconds: int | float | None = None,
    ) -> dict:
        """Review the current publication snapshot in an evolving trace."""
        return self._resume_orchestrator().resume(
            trace_dir=trace_dir,
            theme=theme,
            reviewer=reviewer,
            strategy=strategy,
            allow_theme_override=allow_theme_override,
            require_resolved_metadata=require_resolved_metadata,
            collect_metadata=collect_metadata,
            defer_metadata_errors=defer_metadata_errors,
            require_main_datalinks_phase=require_main_datalinks_phase,
            publication_limit=publication_limit,
            review_action_limit=review_action_limit,
            cancelled=cancelled,
            snapshot_accessions=snapshot_accessions,
            publication_keys=publication_keys,
            item_lock_timeout_seconds=item_lock_timeout_seconds,
            metadata_item_timeout_seconds=metadata_item_timeout_seconds,
            publication_text_item_timeout_seconds=(
                publication_text_item_timeout_seconds
            ),
            review_item_timeout_seconds=review_item_timeout_seconds,
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
        prune_accessions: bool = False,
        max_review_criteria: int = 12,
    ) -> tuple[list[dict], dict]:
        if theme is None:
            return accessions, publication_texts

        publication_texts = self.review_publication_texts(
            publication_texts=publication_texts,
            contexts=self.publication_review_contexts(accessions=accessions),
            theme=theme,
            reviewer=reviewer,
            strategy=strategy,
            max_review_criteria=max_review_criteria,
            review_filter=review_filter,
        )
        return self.filtered_result(
            accessions=accessions,
            publication_texts=publication_texts,
            review_filter=review_filter,
            prune_accessions=prune_accessions,
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
                accession = self._capability_registry.review_identity(
                    record.get("datalink_id", "")
                )
                if accession:
                    if accession not in context["accessions"]:
                        context["accessions"].append(accession)
                metadata = build_miniml_metadata_context(
                    record.get("accession_metadata")
                )
                if accession:
                    status = str(record.get("metadata_status") or "pending")
                    if metadata:
                        status = "available"
                    elif status == "available":
                        status = "available_but_empty"
                    metadata_entry = {
                        "accession": accession,
                        "status": status,
                        "context": metadata or "",
                    }
                    if metadata_entry not in context["metadata"]:
                        context["metadata"].append(metadata_entry)
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
        max_review_criteria: int = 12,
        review_filter: str = "none",
    ) -> dict:
        self.validate_options(theme=theme, review_filter=review_filter, strategy=strategy)
        validate_max_review_criteria(max_review_criteria)
        reviewer = reviewer if reviewer is not None else self._reviewer(max_review_criteria=max_review_criteria)
        declared_cap = getattr(reviewer, "MAX_CRITERIA", getattr(reviewer, "max_criteria", 12))
        if declared_cap != max_review_criteria:
            raise ValueError("injected reviewer max_criteria conflicts with max_review_criteria")
        reviewer_identity = self._reviewer_identity(reviewer)
        reviewer_identity["max_review_criteria"] = max_review_criteria
        reviewed_publication_texts = {}
        reviewed_count = 0
        reused_count = 0
        failed_count = 0

        total = len(publication_texts)
        criteria = (
            self._review_criteria(
                theme=theme,
                strategy=strategy,
                reviewer=reviewer,
                reviewer_identity=reviewer_identity,
                checkpoint_store=checkpoint_store,
            )
            if total
            else None
        )
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
                reviewer_identity=reviewer_identity,
                criteria=criteria,
            )
            identity_hash = self._review_identity_hash(
                publication_text=publication_text,
                context=context,
                theme=theme,
                strategy=strategy,
                reviewer_identity=reviewer_identity,
                criteria=criteria,
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
                    reviewer_identity=reviewer_identity,
                    criteria=criteria,
                    review_filter=review_filter,
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
        reviewer_identity: dict,
        criteria: list[dict[str, str]] | None,
        review_filter: str = "none",
    ) -> dict:
        return PublicationReviewStage(self).run(PublicationReviewRequest(
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
            reviewer_identity=reviewer_identity,
            criteria=criteria,
            review_filter=review_filter,
        )).to_mapping()

    def _review_criteria(
        self,
        *,
        theme: str,
        strategy: str,
        reviewer,
        reviewer_identity: dict,
        checkpoint_store,
    ) -> list[dict[str, str]] | None:
        derive = getattr(reviewer, "derive_criteria", None)
        if not callable(derive):
            return None
        review_signature = inspect.signature(reviewer.review_relevancy)
        accepts_criteria = "criteria" in review_signature.parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in review_signature.parameters.values()
        )
        if not accepts_criteria:
            return None
        checkpoint_key = self._criteria_checkpoint_key(
            theme=theme,
            strategy=strategy,
            reviewer_identity=reviewer_identity,
        )
        cached = (
            checkpoint_store.get_meta(checkpoint_key)
            if checkpoint_store is not None
            else None
        )
        if (
            isinstance(cached, dict)
            and cached.get("review_contract_version") == REVIEW_CONTRACT_VERSION
        ):
            return self._validated_criteria_catalogue(cached.get("criteria"), max_criteria=reviewer_identity.get("max_review_criteria", 12))
        derived = derive(theme)
        if not isinstance(derived, dict) or set(derived) != {"criteria"}:
            raise ValueError("derive_criteria must return only a criteria list")
        criteria = self._validated_criteria_catalogue(derived["criteria"], max_criteria=reviewer_identity.get("max_review_criteria", 12))
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                checkpoint_key,
                {
                    "criteria": criteria,
                    "review_contract_version": REVIEW_CONTRACT_VERSION,
                    "reviewer_identity": reviewer_identity,
                    "strategy": strategy,
                    "theme": theme,
                },
            )
        return criteria

    @staticmethod
    def _validated_criteria_catalogue(value, *, max_criteria=12) -> list[dict[str, str]]:
        validate_max_review_criteria(max_criteria)
        if not isinstance(value, list) or not 1 <= len(value) <= max_criteria:
            raise ValueError(f"criteria must contain one to {max_criteria} definitions")
        criteria: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, dict) or set(item) != {"id", "description"}:
                raise ValueError(f"criterion {index} has an invalid shape")
            criterion_id = str(item["id"]).strip()
            description = str(item["description"]).strip()
            if not _CRITERION_ID_PATTERN.fullmatch(criterion_id):
                raise ValueError(f"criterion {index} has an invalid id")
            if not description:
                raise ValueError(f"criterion {index} has an empty description")
            if criterion_id in seen:
                raise ValueError(f"criterion id is duplicated: {criterion_id}")
            seen.add(criterion_id)
            criteria.append({"id": criterion_id, "description": description})
        return criteria

    @staticmethod
    def _criteria_checkpoint_key(
        *, theme: str, strategy: str, reviewer_identity: dict
    ) -> str:
        identity = json.dumps(
            {
                "theme": theme,
                "strategy": strategy,
                "reviewer_identity": reviewer_identity,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "thematic_review_criteria:" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _review_input_hash(
        publication_text: dict,
        context: dict,
        theme: str,
        strategy: str = "direct",
        reviewer_identity: dict | None = None,
        criteria: list[dict[str, str]] | None = None,
    ) -> str:
        value = json.dumps(
            {
                "text": publication_text.get("text", ""),
                "theme": theme,
                "context": context,
                "strategy": strategy,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
                "reviewer_identity": reviewer_identity or {},
                "criteria": criteria,
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
        reviewer_identity: dict | None = None,
        criteria: list[dict[str, str]] | None = None,
    ) -> str:
        value = json.dumps(
            {
                "text": publication_text.get("text", ""),
                "theme": theme,
                "title": context.get("title", ""),
                "accessions": context.get("accessions", []),
                "strategy": strategy,
                "review_contract_version": REVIEW_CONTRACT_VERSION,
                "reviewer_identity": reviewer_identity or {},
                "criteria": criteria,
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
        prune_accessions: bool = False,
    ) -> tuple[list[dict], dict]:
        removed_judgements = self.removed_review_judgements(review_filter=review_filter)
        filtered_accessions = []
        used_refs = set()
        pruned_associations = 0

        for record in accessions:
            publications = []
            record_accession = self.normalized_accession(
                record.get("datalink_id", "")
            )

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

                if prune_accessions and record_accession in self.removed_accessions(
                    publication_text=publication_text
                ):
                    pruned_associations += 1
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
            "Atlas thematic filter stats review_filter=%s prune_accessions=%s pruned_associations=%s input_accessions=%s output_accessions=%s input_publication_texts=%s output_publication_texts=%s",
            review_filter,
            prune_accessions,
            pruned_associations,
            len(accessions),
            len(filtered_accessions),
            len(publication_texts),
            len(filtered_publication_texts),
        )
        return filtered_accessions, filtered_publication_texts

    def removed_accessions(self, publication_text: dict) -> set[str]:
        agentic_curator = publication_text.get(AGENTIC_CURATOR, {})
        if not isinstance(agentic_curator, dict):
            return set()
        if agentic_curator.get("review_status") == "failed":
            return set()
        removals = agentic_curator.get("accessions_to_remove", [])
        if not isinstance(removals, list):
            return set()
        return {
            accession
            for item in removals
            if isinstance(item, dict)
            and (accession := self.normalized_accession(item.get("accession", "")))
        }

    @staticmethod
    def normalized_accession(value) -> str:
        return str(value or "").strip().upper()

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
        reviewer_identity: dict | None = None,
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
                "criteria": review.get("criteria", []),
                "accessions_to_remove": removals,
                "accession_assessments": review.get(
                    "accession_assessments", []
                ),
                "review_revision": review.get("review_revision"),
                "evidence_contract_version": review.get(
                    "evidence_contract_version"
                ),
                "raw_review": review,
            }
            if review_input_hash is not None:
                result.update(
                    {
                        "review_input_hash": review_input_hash,
                        "review_contract_version": REVIEW_CONTRACT_VERSION,
                        "reviewer_identity": reviewer_identity or {},
                    }
                )
            if metadata_context is not None:
                result["metadata_context"] = metadata_context
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
        if review_input_hash is not None:
            result.update(
                {
                    "review_input_hash": review_input_hash,
                    "review_contract_version": REVIEW_CONTRACT_VERSION,
                    "reviewer_identity": reviewer_identity or {},
                }
            )
        if metadata_context is not None:
            result["metadata_context"] = metadata_context
        return result

    @staticmethod
    def _reviewer_identity(reviewer) -> dict:
        filter_identity = {"filter_contract_version": REVIEW_CONTRACT_VERSION}
        declared = getattr(reviewer, "review_execution_identity", None)
        if callable(declared):
            identity = declared()
            if not isinstance(identity, dict):
                raise TypeError("review_execution_identity must return a mapping")
            required = {"provider", "model", "generation", "prompt_sha256"}
            missing = sorted(required.difference(identity))
            if missing:
                raise ValueError(
                    "review_execution_identity is missing: " + ", ".join(missing)
                )
            normalized = json.loads(json.dumps(identity, sort_keys=True, separators=(",", ":")))
            normalized.update(max_review_criteria=getattr(reviewer, "MAX_CRITERIA", getattr(reviewer, "max_criteria", 12)), **filter_identity)
            return normalized

        reviewer_type = type(reviewer)
        review_method = getattr(reviewer_type, "review_relevancy", None)
        try:
            review_source = inspect.getsource(review_method)
        except (OSError, TypeError):
            review_source = f"{reviewer_type.__module__}.{reviewer_type.__qualname__}"
        llm = getattr(reviewer, "llm", None)
        platform = getattr(llm, "platform", None)
        generation = {
            "max_output_tokens": getattr(reviewer, "MAX_OUTPUT_TOKENS", None),
            "review_revision": getattr(reviewer, "DIRECT_REVIEW_REVISION", None),
            "contract_version": REVIEW_CONTRACT_VERSION,
        }
        return {
            "max_review_criteria": getattr(reviewer, "MAX_CRITERIA", getattr(reviewer, "max_criteria", 12)),
            **filter_identity,
            "reviewer": f"{reviewer_type.__module__}.{reviewer_type.__qualname__}",
            "provider": str(
                getattr(llm, "platform_name", None)
                or (type(llm).__name__ if llm is not None else "default")
            ),
            "model": str(
                getattr(platform, "model", None)
                or getattr(llm, "model", None)
                or "default"
            ),
            "generation": generation,
            "prompt_sha256": hashlib.sha256(
                review_source.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _metadata_context(context: dict) -> dict | None:
        if "metadata_statuses" not in context:
            return None
        statuses = dict(context.get("metadata_statuses") or {})
        used = [
            item.get("accession")
            for item in context.get("metadata", [])
            if item.get("accession")
            and item.get("status", "available") == "available"
            and item.get("context")
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

    def _reviewer(self, *, max_review_criteria=12):
        validate_max_review_criteria(max_review_criteria)
        from ThematicAtlases.integrations.reviewer import configured_reviewer

        return configured_reviewer(
            max_review_criteria=max_review_criteria,
            factory=self._reviewer_factory,
            cancelled=self._cancelled,
        )

    def _resume_orchestrator(self):
        if self._resume_orchestrator_instance is not None:
            return self._resume_orchestrator_instance

        if self._resume_orchestrator_factory is not None:
            self._resume_orchestrator_instance = self._resume_orchestrator_factory(
                self
            )
            return self._resume_orchestrator_instance

        self._resume_orchestrator_instance = TracePublicationReviewResumer(self)
        return self._resume_orchestrator_instance
from ThematicAtlases.checkpoint import failure_category, is_retryable_error
from ThematicAtlases.runtime_contracts import safe_error_json, safe_error_mapping
