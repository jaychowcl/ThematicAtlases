"""Strict JSON transport boundary for canonical MSC MINiML 3.0 packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from meta_standards_converter.miniml import (
    MINIML_SCHEMA_VERSION,
    MINiMLCodec,
    MINiMLPackage,
)


MINIML_CHECKPOINT_PAYLOAD_VERSION = 1


def canonicalize_miniml_package(value: Mapping[str, Any] | MINiMLPackage) -> dict[str, Any]:
    """Decode supported input and emit canonical JSON-native MSC MINiML 3.0."""

    if not isinstance(value, Mapping):
        raise TypeError("MSC MINiML package must be a mapping or MINiMLPackage")
    codec = MINiMLCodec()
    return codec.encode(codec.decode(value, strict=True).package)


def canonicalize_miniml_packages(values: Sequence[Mapping[str, Any] | MINiMLPackage]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("MSC MINiML packages must be an array")
    return [canonicalize_miniml_package(value) for value in values]


def canonicalize_atlas_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate MINiML-shaped Atlas metadata while retaining other metadata mappings."""

    if isinstance(value, MINiMLPackage):
        return canonicalize_miniml_package(value)
    if not isinstance(value, Mapping):
        raise TypeError("Atlas dataset metadata must be a mapping")
    if set(value) == {"packages"}:
        packages = value.get("packages")
        if not isinstance(packages, (list, tuple)):
            raise ValueError("Atlas MINiML package collection must be an array")
        return {"packages": canonicalize_miniml_packages(packages)}
    if "miniml_schema_version" in value or "mage_tab" in value:
        return canonicalize_miniml_package(value)
    return deepcopy(dict(value))


def checkpoint_payload(
    packages: Sequence[Mapping[str, Any] | MINiMLPackage],
    *,
    checkpoint_version: int,
    **values: Any,
) -> dict[str, Any]:
    """Build a versioned, JSON-native metadata checkpoint payload."""

    return {
        "checkpoint_version": checkpoint_version,
        "miniml_checkpoint_payload_version": MINIML_CHECKPOINT_PAYLOAD_VERSION,
        "miniml_schema_version": MINIML_SCHEMA_VERSION,
        **values,
        "packages": canonicalize_miniml_packages(packages),
    }


def checkpoint_packages(payload: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """Return canonical packages only for the current checkpoint contract."""

    if not isinstance(payload, Mapping):
        return None
    if payload.get("miniml_checkpoint_payload_version") != MINIML_CHECKPOINT_PAYLOAD_VERSION:
        return None
    if payload.get("miniml_schema_version") != MINIML_SCHEMA_VERSION:
        return None
    packages = payload.get("packages")
    if not isinstance(packages, list):
        return None
    try:
        return canonicalize_miniml_packages(packages)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MINIML_CHECKPOINT_PAYLOAD_VERSION",
    "canonicalize_atlas_metadata",
    "canonicalize_miniml_package",
    "canonicalize_miniml_packages",
    "checkpoint_packages",
    "checkpoint_payload",
]
