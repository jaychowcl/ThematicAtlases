"""
Docstring for ThematicAtlases.providers.synonym_provider

Module for providing synonym searching. Interface into different synonym wrappers.
"""

from . import wrapper_OLS
import logging
logger = logging.getLogger(__name__)
from typing import List

class SynonymProvider:
    """
    Docstring for SynonymProvider
    Interface class for different synonym search wrappers.
    """

    def __init__(self):
        pass

    def search_for_synonyms(self, search_term: str) -> List:
        '''
        Method for searching for synonyms for a search term

        Input:
            string of single search_term
        Return:
            List of (synonyms, source) tuples
        Do:
            Use search_term to search different synonym wrappers.
            Append seach term with synonym wrapper source tuple
        Defense:

        '''
        logger.debug(f"SynonymProvider.search_for_synonyms(): Searching for synonyms for term: {search_term}")
        synonyms = []
        #OLS wrapper
        ols_synonyms = wrapper_OLS.Wrapper_OLS().search_for_synonyms(search_term=search_term)
        ols_synonyms = [(syn, "OLS") for syn in ols_synonyms]
        synonyms.extend(ols_synonyms)
        # other wrappers here

        return synonyms
