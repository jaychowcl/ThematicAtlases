"""Compatibility imports; implementation is owned by ThematicAtlases.publication.adapter."""
from ThematicAtlases.publication.adapter import *
import ThematicAtlases.publication.adapter as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
