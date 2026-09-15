"""Compatibility imports; implementation is owned by ThematicAtlases.publication.publisher."""
from ThematicAtlases.publication.publisher import *
import ThematicAtlases.publication.publisher as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
