"""Crash-durable publication for related Atlas JSON artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
import tempfile
from typing import Any

from meta_standards_converter.artifact_bundle import (
    ArtifactRecoveryError,
    DurableArtifactBundlePublisher,
    PublishedArtifactBundle,
    resolve_current_bundle,
)


class ArtifactRollbackError(RuntimeError):
    """JSON publication failed and prior compatibility views need recovery."""

    def __init__(
        self,
        publication_error: BaseException,
        rollback_errors: list[BaseException] | tuple[BaseException, ...],
        recovery_paths: tuple[Path, ...],
    ) -> None:
        self.publication_error = publication_error
        self.rollback_errors = tuple(rollback_errors)
        self.recovery_paths = recovery_paths
        locations = ", ".join(map(str, recovery_paths)) or "none"
        super().__init__(
            "JSON artifact publication failed and rollback failed; "
            f"preserved recovery backups: {locations}; "
            f"rollback failed: {self.rollback_errors[0]}"
        )


class JsonArtifactBundlePublisher:
    """Serialize JSON into an immutable generation and atomically select it.

    Direct destination files remain compatibility views. The returned
    :class:`PublishedArtifactBundle` and its ``current.json`` pointer are the
    authoritative crash-atomic publication boundary.
    """

    def __init__(
        self,
        *,
        replace: Callable[
            [
                str | bytes | os.PathLike[str] | os.PathLike[bytes],
                str | bytes | os.PathLike[str] | os.PathLike[bytes],
            ],
            None,
        ] = os.replace,
    ) -> None:
        self._replace = replace

    def publish(
        self, artifacts: Mapping[str | Path, Any]
    ) -> PublishedArtifactBundle:
        """Publish one validated JSON generation and return its current pointer."""

        destinations = [Path(destination) for destination in artifacts]
        if not destinations:
            raise ValueError("JSON artifact bundle must not be empty")
        if len(set(destinations)) != len(destinations):
            raise ValueError("JSON artifact destinations must be unique")
        parents = {destination.parent.resolve() for destination in destinations}
        if len(parents) != 1:
            raise ValueError("JSON artifact destinations must share one parent")
        parent = next(iter(parents))
        parent.mkdir(parents=True, exist_ok=True)
        roles = self._roles(destinations)

        with tempfile.TemporaryDirectory(
            prefix=".atlas-json-stage-", dir=parent
        ) as temporary:
            stage_root = Path(temporary)
            staged: dict[str, Path] = {}
            destination_map: dict[str, Path] = {}
            for role, destination, value in zip(
                roles, destinations, artifacts.values(), strict=True
            ):
                path = stage_root / destination.name
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(
                        value,
                        handle,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                with path.open(encoding="utf-8") as handle:
                    json.load(handle)
                staged[role] = path
                destination_map[role] = destination
            try:
                return DurableArtifactBundlePublisher(
                    replace=self._replace
                ).publish(staged, destination_map, overwrite=True)
            except ArtifactRecoveryError as error:
                raise ArtifactRollbackError(
                    error.publication_error,
                    error.recovery_errors,
                    error.recovery_paths,
                ) from error

    @staticmethod
    def _roles(destinations: list[Path]) -> tuple[str, ...]:
        roles = tuple(
            destination.name.removesuffix(".json") for destination in destinations
        )
        if len(set(roles)) != len(roles):
            raise ValueError("JSON artifact roles derived from filenames must be unique")
        return roles


__all__ = [
    "ArtifactRollbackError",
    "JsonArtifactBundlePublisher",
    "PublishedArtifactBundle",
    "resolve_current_bundle",
]
