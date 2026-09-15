"""Compatibility imports; implementation is owned by ThematicAtlases.domain.atlas."""
from ThematicAtlases.domain.atlas import *
import ThematicAtlases.domain.atlas as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
