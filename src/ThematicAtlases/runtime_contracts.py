"""Shared status-v2 and persistence-safe error helpers."""

from __future__ import annotations

import json
from typing import Any

from meta_standards_converter.runtime_contracts import (
    CompletenessStatus,
    EvidenceConfidence,
    ExecutionStatus,
    OperationStatusV2,
    PublicationDisposition,
    RetryCategory,
    SafeErrorEnvelope,
    ValidationStatus,
)


def safe_error_envelope(
    error: BaseException,
    *,
    provider: str | None,
    stage: str,
    item_id: str | None = None,
    retryable: bool | None = None,
) -> SafeErrorEnvelope:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    request = getattr(error, "request", None)
    retry_category = (
        RetryCategory.UNKNOWN
        if retryable is None
        else RetryCategory.RETRYABLE
        if retryable
        else RetryCategory.TERMINAL
    )
    return SafeErrorEnvelope.from_exception(
        error,
        provider=provider,
        location=getattr(request, "url", None),
        http_status=(
            status
            if isinstance(status, int) and not isinstance(status, bool)
            else None
        ),
        retry_category=retry_category,
        stage=stage,
        item_id=item_id,
    )


def safe_error_mapping(
    error: BaseException,
    *,
    provider: str | None,
    stage: str,
    item_id: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    return safe_error_envelope(
        error,
        provider=provider,
        stage=stage,
        item_id=item_id,
        retryable=retryable,
    ).to_dict()


def safe_error_json(
    error: BaseException,
    *,
    provider: str | None,
    stage: str,
    item_id: str | None = None,
    retryable: bool | None = None,
) -> str:
    return json.dumps(
        safe_error_mapping(
            error,
            provider=provider,
            stage=stage,
            item_id=item_id,
            retryable=retryable,
        ),
        sort_keys=True,
    )


def not_run_status(*, terminal_reason: str) -> OperationStatusV2:
    return OperationStatusV2(
        execution=ExecutionStatus.NOT_RUN,
        completeness=CompletenessStatus.EMPTY,
        evidence_confidence=EvidenceConfidence.NOT_ASSESSED,
        validation=ValidationStatus.NOT_RUN,
        publication=PublicationDisposition.NOT_REQUESTED,
        terminal_reason=terminal_reason,
    )


def failed_status(
    error: BaseException,
    *,
    provider: str | None,
    stage: str,
    item_id: str | None = None,
    retryable: bool | None = None,
    terminal_reason: str,
) -> OperationStatusV2:
    return OperationStatusV2(
        execution=ExecutionStatus.FAILED,
        completeness=CompletenessStatus.EMPTY,
        evidence_confidence=EvidenceConfidence.NOT_ASSESSED,
        validation=ValidationStatus.NOT_RUN,
        publication=PublicationDisposition.BLOCKED,
        terminal_reason=terminal_reason,
        errors=(
            safe_error_envelope(
                error,
                provider=provider,
                stage=stage,
                item_id=item_id,
                retryable=retryable,
            ),
        ),
    )


__all__ = [
    "failed_status",
    "not_run_status",
    "safe_error_envelope",
    "safe_error_json",
    "safe_error_mapping",
]
