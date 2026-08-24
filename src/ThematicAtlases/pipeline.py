from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STOP_AFTER_STAGES = (
    "query-results",
    "datalinks",
    "publication-text",
    "fulltext-accessions",
    "accession-graph",
    "metadata",
    "review",
    "harmonization",
)

DISCOVERY_STOP_STAGES = STOP_AFTER_STAGES[:5]


def validate_stop_after(value: str | None) -> str | None:
    if value is not None and value not in STOP_AFTER_STAGES:
        raise ValueError(
            "stop_after must be one of: " + ", ".join(STOP_AFTER_STAGES)
        )
    return value


@dataclass(eq=False)
class AtlasStagePause(RuntimeError):
    """Internal control result for a requested, durable stage boundary."""

    stage: str
    result: dict[str, Any]

    def __post_init__(self) -> None:
        validate_stop_after(self.stage)
        RuntimeError.__init__(self, f"Atlas paused after {self.stage}")

