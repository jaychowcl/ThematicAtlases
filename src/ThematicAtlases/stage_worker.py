"""Compatibility imports; implementation is owned by ThematicAtlases.workflows.worker."""
from ThematicAtlases.workflows.worker import *
import ThematicAtlases.workflows.worker as _implementation


def __getattr__(name):
    return getattr(_implementation, name)
