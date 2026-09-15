"""Compatibility imports; implementation is owned by ThematicAtlases.publication.documents."""
from ThematicAtlases.publication.documents import *
import ThematicAtlases.publication.documents as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
