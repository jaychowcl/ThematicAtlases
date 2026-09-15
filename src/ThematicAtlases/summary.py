"""Compatibility imports; implementation is owned by ThematicAtlases.publication.summary."""
from ThematicAtlases.publication.summary import *
import ThematicAtlases.publication.summary as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
