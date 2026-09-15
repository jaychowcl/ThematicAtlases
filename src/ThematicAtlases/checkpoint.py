"""Compatibility imports; implementation is owned by ThematicAtlases.runtime.checkpoint."""
from ThematicAtlases.runtime.checkpoint import *
import ThematicAtlases.runtime.checkpoint as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
