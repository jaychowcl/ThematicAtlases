"""Compatibility imports; implementation is owned by ThematicAtlases.runtime.trace."""
from ThematicAtlases.runtime.trace import *
import ThematicAtlases.runtime.trace as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
