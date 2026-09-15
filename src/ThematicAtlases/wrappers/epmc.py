"""Compatibility imports; implementation is owned by ThematicAtlases.integrations.europe_pmc."""
from ThematicAtlases.integrations.europe_pmc import *
import ThematicAtlases.integrations.europe_pmc as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
