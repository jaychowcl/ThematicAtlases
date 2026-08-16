from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
import gzip
import hashlib
from uuid import uuid4

from meta_standards_converter.miniml import MINiMLCompatibilityError

from ThematicAtlases.miniml_boundary import canonicalize_miniml_package


GEO_SOURCE_STAGE = "geo_miniml_source"
ARRAYEXPRESS_SOURCE_STAGE = "arrayexpress_magetab_source"
GEO_PRECANONICAL_STAGE = "geo_precanonical_metadata"
ARRAYEXPRESS_PRECANONICAL_STAGE = "arrayexpress_precanonical_metadata"
VALIDATION_DIAGNOSTICS_STAGE = "metadata_validation_diagnostics"
EVIDENCE_CONTRACT_VERSION = 1


def compressed_text(value: str) -> dict:
    raw = str(value).encode("utf-8")
    return {
        "encoding": "gzip+base64",
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "data": base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii"),
    }


def restored_text(value: Mapping) -> str:
    if value.get("encoding") != "gzip+base64":
        raise ValueError("metadata evidence encoding is unsupported")
    try:
        raw = gzip.decompress(base64.b64decode(str(value.get("data") or "")))
    except Exception as error:
        raise ValueError("metadata evidence payload is corrupt") from error
    if len(raw) != value.get("byte_count"):
        raise ValueError("metadata evidence byte count does not match")
    if hashlib.sha256(raw).hexdigest() != value.get("sha256"):
        raise ValueError("metadata evidence checksum does not match")
    return raw.decode("utf-8")


def package_mapping(value) -> dict:
    if hasattr(value, "to_mapping"):
        value = value.to_mapping()
    if not isinstance(value, Mapping):
        raise TypeError("pre-canonical metadata package must be a mapping")
    return dict(value)


def checkpoint_precanonical(store, stage: str, key: str, ordinal: int, packages) -> list[dict]:
    mappings = [package_mapping(package) for package in packages]
    store.put(
        stage,
        key,
        ordinal,
        "available" if mappings else "no_data",
        payload={
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "packages": mappings,
        },
    )
    return mappings


def canonicalize_with_diagnostics(
    packages: Sequence[Mapping],
    *,
    store,
    provider: str,
    key: str,
    ordinal: int,
) -> list[dict]:
    canonical = []
    diagnostics = []
    issues = []
    diagnostic_key = f"{provider}:{key}"
    previous_diagnostic = store.get(VALIDATION_DIAGNOSTICS_STAGE, diagnostic_key)
    attempt_count = int((previous_diagnostic or {}).get("attempt_count", 0)) + 1
    for package_index, package in enumerate(packages):
        try:
            canonical.append(canonicalize_miniml_package(package))
        except MINiMLCompatibilityError as error:
            issues.extend(error.diagnostics)
            diagnostics.extend(
                {
                    "package_index": package_index,
                    "code": issue.code,
                    "path": issue.path,
                    "severity": issue.severity,
                }
                for issue in error.diagnostics
            )
        except Exception as error:
            correlation_id = uuid4().hex
            store.put(
                VALIDATION_DIAGNOSTICS_STAGE,
                diagnostic_key,
                ordinal,
                "terminal_error",
                payload={
                    "contract_version": EVIDENCE_CONTRACT_VERSION,
                    "provider": provider,
                    "accession": key,
                    "failure_stage": "canonicalization",
                    "attempt_count": attempt_count,
                    "correlation_id": correlation_id,
                    "diagnostics": [
                        {
                            "package_index": package_index,
                            "code": "canonicalization_exception",
                            "path": "$",
                            "severity": "error",
                        }
                    ],
                },
                error_type=type(error).__name__,
                failure_category="metadata_construction",
            )
            raise
    if diagnostics:
        correlation_id = uuid4().hex
        store.put(
            VALIDATION_DIAGNOSTICS_STAGE,
            diagnostic_key,
            ordinal,
            "terminal_error",
            payload={
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "provider": provider,
                "accession": key,
                "failure_stage": "canonicalization",
                "attempt_count": attempt_count,
                "correlation_id": correlation_id,
                "diagnostics": diagnostics,
            },
            error_type="MINiMLCompatibilityError",
            failure_category="metadata_compatibility",
        )
        raise MINiMLCompatibilityError(tuple(issues))
    store.put(
        VALIDATION_DIAGNOSTICS_STAGE,
        diagnostic_key,
        ordinal,
        "available",
        payload={
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "provider": provider,
            "accession": key,
            "failure_stage": None,
            "attempt_count": attempt_count,
            "correlation_id": None,
            "diagnostics": [],
        },
    )
    return canonical
