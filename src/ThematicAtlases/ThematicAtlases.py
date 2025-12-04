"""
ThematicAtlases.py

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
from .wrappers.wrapper_OLS import Wrapper_OLS

logger = logging.getLogger(__name__)



class ThematicAtlases:
    """
    Main class for building thematic atlases
    """

    def __init__(self):
        pass

    def get_synonyms(
        self, df: pd.DataFrame = None, infile: str = None, outfile: str = None
    ) -> pd.DataFrame:
        """
        Method for gathering synonyms of input terms from the Ontology Lookup Service

        Input:
            pd.DataFrame of terms. Must include: search_term
            or
            .tsv of terms.

        Returns:
            pd.DataFrame of terms with appended synonyms.
            and if outfile specified:
            .tsv file of terms with appended synonyms.

        Do:
            Take .tsv and convert to pd.Dataframe.
            Use search term with synonym search col to search  OLS to gather all related synonyms
            Create new rows from input df and keep original synonym search term column values the same
            Change synonym_search to empty
            Change search_term_source to appropriate synonym search

        Defense:
            Check only df or infile, not none or both
            Check in df contains search_term
            Give a warning if other expected columns not there.

        """
        logger.debug("ThematicAtlases.get_synonyms(): Start")

        # Defense: both infile and df are None or all not Null
        if (df is None) == (infile is None):
            error_message = "ValueError: Only 1 pd.DataFrame or infile can be provided to ThematicAtlases.get_synonyms()"
            logger.critical(error_message)
            raise ValueError(error_message)

        # If infile .tsv provided, read and change to pd.DataFrame 
        if infile is not None:
            logging.debug("ThematicAtlases.get_synonyms(): Reading .tsv infile")
            df = pd.read_csv(infile, sep="\t")

        # Defense: Check df has column: search_term.
        if "search_term" not in df.columns:
            error_message = "ValueError: ThematicAtlases.get_synonyms(): Input search terms does not have search_term column!"
            logger.critical(error_message)
            raise ValueError(error_message)
        # Defense: Give warning if columns missing: search_scope, synonym_search, search_term_source
        check_cols = ["search_scope", "synonym_search", "search_term_source"]
        for col in check_cols:
            if col not in df.columns:
                logger.warning(
                    f"ThematicAtlases.get_synonyms(): Column not in search_terms.tsv: {col}"
                )

        # Iterate through each search_term in df, search through OLS and collect synonyms. Append relevant columns to synonyms
        logger.debug("ThematicAtlases.get_synonyms(): Searching OLS for synonyms")
        all_synonyms = []
        for index, row in df.iterrows():
            synonyms = Wrapper_OLS().search_for_synonyms(search_term=row["search_term"])
            

        # Append to df 

        # Return pd.DataFrame 

        # and export to .tsv if outfile provided
        pass
