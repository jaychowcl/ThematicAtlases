"""Core atlas model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ThematicAtlas:
    """Minimal representation of a thematic atlas."""

    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "metadata": dict(self.metadata),
        }
