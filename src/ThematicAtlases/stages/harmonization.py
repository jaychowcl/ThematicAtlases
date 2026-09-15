"""HarmonizationStage: a typed operation shared by caller-specific scheduling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from .results import HarmonizationResult
if TYPE_CHECKING:
    from ThematicAtlases.harmonizer.harmonizer import AtlasHarmonizer
from concurrent.futures import as_completed, ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from agentic_curator.contracts import miniml_source_fingerprint
from agentic_curator.review_decisions import ReviewDecisionFile
from ThematicAtlases.checkpoint import failure_category, is_retryable_error
from ThematicAtlases.runtime_contracts import failed_status, not_run_status
import logging
logger = logging.getLogger("ThematicAtlases.harmonizer.harmonizer")


@dataclass(frozen=True, kw_only=True)
class HarmonizationRequest:
    datasets: dict
    details_out: str | None = None
    harmonization_options: dict | None = None
    checkpoint_store: Any = None
    review_decisions: dict | None = None


class HarmonizationStage:
    def __init__(self, owner: AtlasHarmonizer):
        self.owner = owner

    def run(self, request: HarmonizationRequest) -> HarmonizationResult:
        datasets, details = self._execute(
            datasets=request.datasets,
            details_out=request.details_out,
            harmonization_options=request.harmonization_options,
            checkpoint_store=request.checkpoint_store,
            review_decisions=request.review_decisions,
        )
        return HarmonizationResult(datasets, details)

    def _execute(
        self,
        datasets: dict,
        details_out: str | None = None,
        harmonization_options: dict | None = None,
        checkpoint_store=None,
        review_decisions: dict | None = None,
    ) -> tuple[dict, list[dict]]:
        stage_owner = self.owner
        source_accessions = [dict(record) for record in datasets.get("accessions", [])]
        accessions = list(source_accessions)
        details: list[dict | None] = [None] * len(accessions)
        harmonization_options = dict(harmonization_options or {})
        stage_owner._validate_harmonization_options(harmonization_options)
        work_by_key = {}
        ontology_harmonizer = None
        execution_identity = None
        typed_review_decisions = (
            ReviewDecisionFile.from_mapping(review_decisions)
            if review_decisions is not None
            else None
        )
        matched_review_source = False

        for index, record in enumerate(accessions):
            metadata = record.get("accession_metadata")
            datalink_id = record.get("datalink_id", "")

            eligibility_reason = stage_owner._eligibility_reason(record)
            if eligibility_reason is not None:
                status = not_run_status(
                    terminal_reason=eligibility_reason
                ).to_dict()
                record["ontology_harmonization_run_status"] = "not_run"
                record["ontology_harmonization_status"] = status
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "run_status": "not_run",
                    "status": status,
                }
                continue

            if not isinstance(metadata, (dict, list)):
                status = not_run_status(
                    terminal_reason="metadata_unavailable"
                ).to_dict()
                record["ontology_harmonization_run_status"] = "not_run"
                record["ontology_harmonization_status"] = status
                record.pop("ontology_harmonization_error", None)
                details[index] = {
                    "datalink_id": datalink_id,
                    "run_status": "not_run",
                    "status": status,
                }
                continue

            context = stage_owner.publication_context(record)
            if ontology_harmonizer is None:
                if stage_owner._requires_model_credentials(harmonization_options):
                    stage_owner._preflight_credentials()
                ontology_harmonizer = stage_owner._ontology_harmonizer()
                execution_identity = stage_owner._harmonization_execution_identity(
                    ontology_harmonizer
                )
            item_options = dict(harmonization_options)
            if typed_review_decisions is not None:
                try:
                    source_fingerprint = miniml_source_fingerprint(metadata)
                except (TypeError, ValueError):
                    source_fingerprint = None
                if source_fingerprint == typed_review_decisions.source_fingerprint:
                    item_options["review_decisions"] = typed_review_decisions.to_mapping()
                    matched_review_source = True
            key = stage_owner._work_key(
                metadata=metadata,
                publication_context=context,
                harmonization_options=item_options,
                execution_identity=execution_identity,
            )
            work_by_key.setdefault(
                key,
                {
                    "work_key": hashlib.sha256(key.encode("utf-8")).hexdigest(),
                    "metadata": metadata,
                    "publication_context": context,
                    "execution_identity": execution_identity,
                    "harmonization_options": item_options,
                    "indices": [],
                },
            )["indices"].append(index)

        if typed_review_decisions is not None and not matched_review_source:
            raise ValueError("review decision source fingerprint is stale")

        if work_by_key:
            if ontology_harmonizer is None:
                raise RuntimeError("harmonization provider was not initialized")
            work_items = list(work_by_key.values())
            for position, item in enumerate(work_items, start=1):
                item["position"] = position
                item["total"] = len(work_items)

            def run(item):
                logger.info(
                    "Atlas ontology harmonization progress work_index=%s work_total=%s accession_count=%s",
                    item["position"],
                    item["total"],
                    len(item["indices"]),
                )
                try:
                    harmonization = stage_owner._harmonize_metadata(
                        ontology_harmonizer,
                        metadata=item["metadata"],
                        publication_context=item["publication_context"],
                        options=item["harmonization_options"],
                    )
                    stage_owner._validated_operation_status(harmonization)
                    return harmonization, None
                except Exception as error:
                    return None, error

            def apply_outcome(item, harmonization, error, *, cached=False):
                for index in item["indices"]:
                    record = accessions[index]
                    datalink_id = record.get("datalink_id", "")
                    if error is not None:
                        logger.error(
                            "Atlas ontology harmonization failed datalink_id=%r error_type=%s",
                            datalink_id,
                            type(error).__name__,
                        )
                        retryable = is_retryable_error(error)
                        status = failed_status(
                            error,
                            provider="agentic_curator",
                            stage="harmonization",
                            item_id=str(datalink_id) or None,
                            retryable=retryable,
                            terminal_reason="harmonization_failed",
                        ).to_dict()
                        safe_error = status["errors"][0]
                        record["ontology_harmonization_run_status"] = "error"
                        record["ontology_harmonization_status"] = status
                        record["ontology_harmonization_error"] = safe_error
                        details[index] = {
                            "datalink_id": datalink_id,
                            "run_status": "error",
                            "status": status,
                            "error": safe_error,
                        }
                        continue

                    status = stage_owner._validated_operation_status(harmonization).to_dict()
                    record["accession_metadata"] = harmonization["miniml_json"]
                    record["ontology_harmonization_run_status"] = "completed"
                    record["ontology_harmonization_status"] = status
                    record.pop("ontology_harmonization_quality_status", None)
                    record.pop("ontology_harmonization_error", None)
                    record["ontology_harmonization_review_required"] = bool(
                        harmonization.get("review_required")
                    )
                    record["ontology_harmonization_pending_review"] = list(
                        harmonization.get("pending_review") or []
                    )
                    details[index] = {
                        "datalink_id": datalink_id,
                        "run_status": "completed",
                        "harmonization_targets": harmonization.get(
                            "harmonization_targets", []
                        ),
                        "workflow": harmonization.get("workflow"),
                        "target_paths": harmonization.get("target_paths"),
                        "harmonization_execution_identity": item[
                            "execution_identity"
                        ],
                        "status": status,
                    }
                    if "preferred_ontology_ids" in harmonization:
                        details[index]["preferred_ontology_ids"] = harmonization[
                            "preferred_ontology_ids"
                        ]
                    if "controls" in harmonization:
                        details[index]["controls"] = harmonization["controls"]
                    for field in (
                        "harmonization_patch",
                        "pending_review",
                        "extension_registry",
                        "review_required",
                        "review_decisions",
                    ):
                        if field in harmonization:
                            details[index][field] = harmonization[field]

                if checkpoint_store is None or cached:
                    return
                if error is None:
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "available",
                        payload=harmonization,
                    )
                else:
                    retryable = is_retryable_error(error)
                    persisted_error = failed_status(
                        error,
                        provider="agentic_curator",
                        stage="harmonization",
                        item_id=str(item["work_key"]),
                        retryable=retryable,
                        terminal_reason="harmonization_failed",
                    ).errors[0].to_dict()
                    checkpoint_store.put(
                        "harmonization",
                        item["work_key"],
                        item["position"],
                        "retryable_error"
                        if retryable
                        else "terminal_error",
                        error=json.dumps(persisted_error, sort_keys=True),
                        error_type=type(error).__name__,
                        failure_category=failure_category(error),
                    )

            pending = []
            for item in work_items:
                checkpoint = (
                    checkpoint_store.get("harmonization", item["work_key"])
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] == "available":
                    apply_outcome(item, checkpoint["payload"], None, cached=True)
                elif checkpoint and checkpoint["status"] == "terminal_error":
                    apply_outcome(
                        item,
                        None,
                        RuntimeError(checkpoint["error"] or "harmonization failed"),
                        cached=True,
                    )
                else:
                    pending.append(item)

            if stage_owner._max_workers == 1:
                for item in pending:
                    harmonization, error = run(item)
                    apply_outcome(item, harmonization, error)
            else:
                with ThreadPoolExecutor(max_workers=stage_owner._max_workers) as executor:
                    futures = {executor.submit(run, item): item for item in pending}
                    for future in as_completed(futures):
                        item = futures[future]
                        harmonization, error = future.result()
                        apply_outcome(item, harmonization, error)

        details = [detail for detail in details if detail is not None]

        result = {**datasets, "accessions": accessions}
        if details_out is not None:
            Path(details_out).parent.mkdir(parents=True, exist_ok=True)
            with open(details_out, "w", encoding="utf-8") as handle:
                json.dump(details, handle, indent=2)

        logger.info(
            "Atlas ontology harmonization stats accessions=%s completed=%s not_run=%s errors=%s details_path=%s",
            len(accessions),
            sum(item["run_status"] == "completed" for item in details),
            sum(item["run_status"] == "not_run" for item in details),
            sum(item["run_status"] == "error" for item in details),
            details_out,
        )
        return result, details

