"""
Docstring for ThematicAtlases.providers.synonym_provider

Module for providing synonym searching. Interface into different synonym wrappers.
"""

from .wrappers import wrapper_OLS
import logging
logger = logging.getLogger(__name__)
from typing import List
import pandas as pd

class SynonymProvider():
    """
    Docstring for SynonymProvider
    Interface class for different synonym search wrappers.
    """

    def __init__(self):
        pass
    

    def get_synonym_list(self, search_term:str ) -> List:
        '''
        Method for searching for synonyms for a single search term
        Input:
            string of single search_term
        Return:
            List of (synonyms, source) tuples
        Do:
            Use search_term to search different synonym wrappers.
            Append seach term with synonym wrapper source tuple
        Defense:
        '''

        logger.debug(f"SynonymProvider.get_synonym_list(): Searching for synonyms for term: {search_term}")
        synonyms = []
        #OLS wrapper
        ols_synonyms = wrapper_OLS.Wrapper_OLS().search_for_synonyms(search_term=search_term)
        ols_synonyms = [(syn, "OLS") for syn in ols_synonyms]
        synonyms.extend(ols_synonyms)
        # other wrappers here


        return synonyms


    def search_for_synonyms(self, df: pd.DataFrame) -> pd.DataFrame:
        '''
        Method for searching for synonyms for a search term

        Input:
            dataframe of search terms or filter terms
        Return:
            List of (synonyms, source) tuples
        Do:
            Use search_term to search different synonym wrappers.
            Append seach term with synonym wrapper source tuple
        Defense:

        '''

        # Determine if search terms or filter terms
        if "search_term" in df.columns:
            term_type = "search_term"
        elif "filter_term" in df.columns:
            term_type = "filter_term"
        else:# Defense: neither search_term or filter_term in columns
            error_message = "ValueError: ThematicAtlas.get_synonyms(): Input terms must have either search_term or filter_term column!"
            logger.critical(error_message)
            raise ValueError(error_message)
    
        # Iterate through rows and get synonyms from OLS using SynonymProvider
        logger.debug("ThematicAtlas.get_synonyms(): Searching OLS for synonyms")
        df_synonyms = df.copy()
        for index, row in df.iterrows():
            synonyms = self.get_synonym_list(search_term=row[term_type])

            for synonym, syn_source in synonyms:
                # Copy original row
                new_row = row.copy()
                new_row[term_type] = synonym

                # adjust columns
                if term_type == "search_term":
                    new_row["search_synonym_search"] = ""
                    new_row["search_term_source"] = syn_source
                else: # TODO: handle group and subgrouping of synonyms of a searched term. 
                    new_row["filter_synonym_search"] = ""
                    new_row["filter_term_source"] = syn_source
                df_synonyms = pd.concat([df_synonyms, pd.DataFrame([new_row])], ignore_index=True)

        return df_synonyms
