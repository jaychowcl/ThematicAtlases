"""Transaction-like publication for related JSON artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4


class ArtifactRollbackError(RuntimeError):
    """Publication failed and at least one prior artifact needs recovery."""

    def __init__(
        self,
        publication_error: BaseException,
        rollback_errors: list[BaseException],
        recovery_paths: tuple[Path, ...],
    ) -> None:
        self.publication_error = publication_error
        self.rollback_errors = tuple(rollback_errors)
        self.recovery_paths = recovery_paths
        locations = ", ".join(map(str, recovery_paths)) or "none"
        super().__init__(
            f"JSON artifact publication failed and rollback failed; "
            f"preserved recovery backups: {locations}; "
            f"rollback failed: {rollback_errors[0]}"
        )


class JsonArtifactBundlePublisher:
    """Publish a set of JSON files as one rollback-safe bundle.

    Files are first serialized and parsed again in sibling staging files. Existing
    destinations are then moved to sibling backups before the staged files are
    published. If any publication fails, every destination is restored to its
    state before :meth:`publish` was called.
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

    def publish(self, artifacts: Mapping[str | Path, Any]) -> None:
        """Serialize and atomically replace all ``artifacts``, with rollback."""

        destinations = [Path(destination) for destination in artifacts]
        if len(set(destinations)) != len(destinations):
            raise ValueError("JSON artifact destinations must be unique")

        token = uuid4().hex
        staged = {
            destination: destination.with_name(
                f".{destination.name}.{token}.stage"
            )
            for destination in destinations
        }
        backups = {
            destination: destination.with_name(
                f".{destination.name}.{token}.backup"
            )
            for destination in destinations
        }
        backed_up: list[Path] = []
        published: list[Path] = []
        rollback_failed = False

        try:
            for destination, value in zip(destinations, artifacts.values(), strict=True):
                destination.parent.mkdir(parents=True, exist_ok=True)
                with staged[destination].open("w", encoding="utf-8") as handle:
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
                with staged[destination].open(encoding="utf-8") as handle:
                    json.load(handle)

            for destination in destinations:
                if destination.exists():
                    self._replace(destination, backups[destination])
                    backed_up.append(destination)

            for destination in destinations:
                self._replace(staged[destination], destination)
                published.append(destination)
        except BaseException as publication_error:
            rollback_errors: list[BaseException] = []
            for destination in reversed(published):
                try:
                    destination.unlink(missing_ok=True)
                except BaseException as error:
                    rollback_errors.append(error)
            for destination in reversed(backed_up):
                if backups[destination].exists():
                    try:
                        self._replace(backups[destination], destination)
                    except BaseException as error:
                        rollback_errors.append(error)
            if rollback_errors:
                rollback_failed = True
                recovery_paths = tuple(
                    path for path in backups.values() if path.exists()
                )
                raise ArtifactRollbackError(
                    publication_error,
                    rollback_errors,
                    recovery_paths,
                ) from publication_error
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)
            if not rollback_failed:
                for path in backups.values():
                    path.unlink(missing_ok=True)


__all__ = ["ArtifactRollbackError", "JsonArtifactBundlePublisher"]
