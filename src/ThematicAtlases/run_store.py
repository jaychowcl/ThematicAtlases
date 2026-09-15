"""Compatibility imports; implementation is owned by ThematicAtlases.runtime.run_store."""
from ThematicAtlases.runtime.run_store import *
import ThematicAtlases.runtime.run_store as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
