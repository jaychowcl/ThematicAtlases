"""
ThematicAtlas.py

A python package that enables:
1. Term synonym search
2. EuropePMC publication search
3. Text mine publications for ENA accessions
4. Collection of metadata from the ENA metadata objects
5. Keyword search for fibrosis filters
6. Metadata harmonization
7. Export to .tsv file


Dependency graph:


"""

import pandas as pd
import logging
logger = logging.getLogger(__name__)
from typing import List

from .providers import synonym_provider



class ThematicAtlas:
    """
    Main class for building thematic atlases
    """

    def __init__(self):
        self.search_terms = None
        self.filter_terms = None
        pass

    def import_search_terms(self, file: str) -> pd.DataFrame:
        """
        Method for importing search terms from .tsv file.

        Input:
            file path

        Returns:
            pd.DataFrame of search terms.tsv
            and
            pd.DataFrame in self.search_terms

        Defense:
            Check search terms.tsv has columns:
                "search_term_id",
                "search_scope",
                "search_term",
                "search_synonym_search",
                "search_term_source",
                "search_term_in_filter_scope",
                "search_term_regex_expression",
            Check columns not empty: # TODO
                search_term
                search_term_source


        """
        logger.debug("ThematicAtlas.import_search_terms(): Start")

        # import to pd.DataFrame
        search_terms = pd.read_csv(file, sep="\t")

        # Defense: check columns
        expected_cols = [
            "search_term_id",
            "search_scope",
            "search_term",
            "search_synonym_search",
            "search_term_source",
            "search_term_in_filter_scope",
            "search_term_regex_expression",
        ]
        for col in expected_cols:
            if col not in search_terms.columns:
                error_message = f"ThematicAtlas.import_search_terms(): ValueError: search_terms.tsv missing expected column: {col}"
                logger.critical(error_message)
                raise ValueError(error_message)

        self.search_terms = search_terms
        return search_terms

    def import_filter_groups(self, file: str) -> pd.DataFrame:
        """
        Method for importing filter terms from .tsv file.

        Input:
            file path

        Returns:
            pd.DataFrame of filter terms.tsv

        Defense:
            Check filter terms.tsv has columns:
                "filter_term_id",
                "filter_scope_group",
                "filter_scope",
                "filter_group",
                "filter_term",
                "filter_synonym_search",
                "filter_term_source",
                "filter_term_subgroup",
            Check columns not empty: # TODO
                filter_term
                filter_scope_group
                filter_term_source

        """
        logger.debug("ThematicAtlas.import_filter_groups(): Start")

        # import to pd.DataFrame
        filter_terms = pd.read_csv(file, sep="\t")
        # Defense: check columns
        expected_cols = [
            "filter_term_id",
            "filter_scope_group",
            "filter_scope",
            "filter_group",
            "filter_term",
            "filter_synonym_search",
            "filter_term_source",
            "filter_term_subgroup",
        ]
        for col in expected_cols:
            if col not in filter_terms.columns:
                error_message = f"ThematicAtlas.import_filter_groups(): ValueError: filter_terms.tsv missing expected column: {col}"
                logger.critical(error_message)
                raise ValueError(error_message)

        self.filter_terms = filter_terms

        return filter_terms
    

    def get_synonyms(
        self, df: pd.DataFrame = None, infile: str = None, outfile: str = None
    ) -> pd.DataFrame:
        """
        Method for gathering synonyms of input terms from the Ontology Lookup Service

        Input:
            pd.DataFrame of terms. Must include: search_term or filter term
            or
            .tsv of terms.

        Returns:
            pd.DataFrame of terms with appended synonyms.
            and if outfile specified:
            .tsv file of terms with appended synonyms.

        Do:
            Take .tsv and convert to pd.Dataframe.
            Determine if it is search terms or filter terms based on presence of search_term or filter_term column
            for each row, take the term and search OLS for synonyms using Wrapper_OLS
            copy original df columns to new rows for each synonym found.

            if search terms:
                change synonym search to empty
                search term source to "OLS_synonym"
            if filter terms:
                change synonym search to empty
                filter term source to "OLS_synonym"

            Append all new rows to original df
            Return pd.DataFrame

        Defense:
            Check only df or infile, not none or both
            Check if df contains search_term
            Give a warning if other expected columns not there.

        """
        logger.debug("ThematicAtlas.get_synonyms(): Start")

        # Defense: both infile and df are None or all not Null
        if (df is not None) and (infile is not None):
            error_message = "ValueError: Only 1 or less pd.DataFrame or infile can be provided to ThematicAtlas.get_synonyms()"
            logger.critical(error_message)
            raise ValueError(error_message)

        # import search terms
        if infile is not None:
            logging.debug("ThematicAtlas.get_synonyms(): Reading .tsv infile")
            df = pd.read_csv(infile, sep="\t")
        elif df is not None:
            df = df
        elif infile is None and df is None:
            df = self.search_terms
            self.filter_terms = self.get_synonyms(df = self.filter_terms)
            self.search_terms = self.get_synonyms(df = self.search_terms)
        else:
            error_message = "ValueError: No input provided to ThematicAtlas.get_synonyms()"
            logger.critical(error_message)
            raise ValueError(error_message)

        # Use SynonymProvider to get synonyms
        df_synonyms = synonym_provider.SynonymProvider().search_for_synonyms(df=df)

        return df_synonyms
    

    
    
    def get_datasets(self):
        '''
        Method for gathering datasets based on search terms and filter groups

        Input:
            None
        '''
        pass