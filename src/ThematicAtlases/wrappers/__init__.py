"""Compatibility provider exports, loaded only when requested.

Provider implementations may import shared wrapper helpers. Eager imports here
would form a cycle when an owning integration module is imported directly.
"""
from importlib import import_module

_EXPORTS = {
    'ArrayExpressWrapper': 'ThematicAtlases.integrations.arrayexpress',
    'EuropePMCWrapper': 'ThematicAtlases.integrations.europe_pmc',
    'GEOWrapper': 'ThematicAtlases.integrations.geo',
    'PubMedGDSLinkGraphWrapper': 'ThematicAtlases.wrappers.pubmed_gds',
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name]), name)
    globals()[name] = value
    return value
