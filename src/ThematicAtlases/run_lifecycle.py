"""Compatibility imports; implementation is owned by ThematicAtlases.runtime.lifecycle."""
from ThematicAtlases.runtime.lifecycle import *
import ThematicAtlases.runtime.lifecycle as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
