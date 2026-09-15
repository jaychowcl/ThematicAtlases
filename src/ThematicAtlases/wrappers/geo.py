"""Compatibility imports; implementation is owned by ThematicAtlases.integrations.geo."""
from ThematicAtlases.integrations.geo import *
import ThematicAtlases.integrations.geo as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
