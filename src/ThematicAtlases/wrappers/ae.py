"""Compatibility imports; implementation is owned by ThematicAtlases.integrations.arrayexpress."""
from ThematicAtlases.integrations.arrayexpress import *
import ThematicAtlases.integrations.arrayexpress as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
