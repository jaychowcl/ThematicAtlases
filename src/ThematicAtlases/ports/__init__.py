"""Intentional dependency-injection contracts for Atlas application code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CollectorPort(Protocol):
    """Discover and optionally enrich legacy stage records."""

    def collect_jsons(self, **kwargs: Any) -> list[dict]: ...


@runtime_checkable
class FiltererPort(Protocol):
    """Attach publication evidence and apply optional review filtering."""

    def filter_jsons(self, **kwargs: Any) -> dict: ...


@runtime_checkable
class HarmonizerPort(Protocol):
    """Harmonize a legacy stage mapping and return result plus details."""

    def harmonize_datasets(self, **kwargs: Any) -> tuple[dict, list[dict]]: ...


@runtime_checkable
class ArtifactPublisherPort(Protocol):
    """Publish one related set of serialized artifacts or raise."""

    def publish(self, artifacts: Mapping[Any, Any]) -> Any: ...


__all__ = [
    "ArtifactPublisherPort",
    "CollectorPort",
    "FiltererPort",
    "HarmonizerPort",
]
