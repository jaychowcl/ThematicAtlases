"""Compatibility imports; implementation is owned by ThematicAtlases.runtime.archive."""
from ThematicAtlases.runtime.archive import *
import ThematicAtlases.runtime.archive as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
