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

        # defense
        # both None or all not Null
        logging.debug("ThematicAtlases.get_synonyms(): Defense")
        if (df is None) == (infile is None):  
            raise ValueError(
                "Only 1 pd.DataFrame or infile can be provided to ThematicAtlases.get_synonyms()"
            )
        
        logging.debug("ThematicAtlases.get_synonyms(): Defense done.")
        
        
        #Handle infile to pd.DataFrame



        pass
