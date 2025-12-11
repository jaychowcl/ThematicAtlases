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
from .providers import synonym_provider

logger = logging.getLogger(__name__)


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
        if (df is None) == (infile is None):
            error_message = "ValueError: Only 1 pd.DataFrame or infile can be provided to ThematicAtlas.get_synonyms()"
            logger.critical(error_message)
            raise ValueError(error_message)

        # If infile .tsv provided, read and change to pd.DataFrame
        if infile is not None:
            logging.debug("ThematicAtlas.get_synonyms(): Reading .tsv infile")
            df = pd.read_csv(infile, sep="\t")


        # Determine if search terms or filter terms
        if "search_term" in df.columns:
            term_type = "search_term"
        elif "filter_term" in df.columns:
            term_type = "filter_term"
        else:# Defense: neither search_term or filter_term in columns
            error_message = "ValueError: ThematicAtlas.get_synonyms(): Input terms must have either search_term or filter_term column!"
            logger.critical(error_message)
            raise ValueError(error_message)
    
        # Iterate through rows and get synonyms from OLS using Wrapper_OLS
        logger.debug("ThematicAtlas.get_synonyms(): Searching OLS for synonyms")
        all_synonyms = []
        for index, row in df.iterrows():
            synonyms = synonym_provider.SynonymProvider().search_for_synonyms(search_term=row[term_type]) #TODO: make it possible to use other wrappers and expand term source

            # Append to df
            #for synonym, source in synonyms:
                # new_row = row.copy()
                # new_row[term_type] = synonym

                # # Adjust synonym search and source columns
                # if term_type == "search_term":
                #     new_row["synonym_search"] = ""
                #     new_row["search_term_source"] = "OLS_synonym"
                # else:
                #     new_row["filter_synonym_search"] = ""
                #     new_row["filter_term_source"] = "OLS_synonym"
                # all_synonyms.append(new_row)


        # # Defense: Check df has column: search_term.
        # if "search_term" not in df.columns:
        #     error_message = "ValueError: ThematicAtlas.get_synonyms(): Input search terms does not have search_term column!"
        #     logger.critical(error_message)
        #     raise ValueError(error_message)
        # # Defense: Give warning if columns missing: search_scope, synonym_search, search_term_source
        # check_cols = ["search_scope", "synonym_search", "search_term_source"]
        # for col in check_cols:
        #     if col not in df.columns:
        #         logger.warning(
        #             f"ThematicAtlas.get_synonyms(): Column not in search_terms.tsv: {col}"
        #         )

        # Iterate through each search_term in df, search through OLS and collect synonyms. Append relevant columns to synonyms
        logger.debug("ThematicAtlas.get_synonyms(): Searching OLS for synonyms")
        all_synonyms = []
        for index, row in df.iterrows():
            synonyms = Wrapper_OLS().search_for_synonyms(search_term=row["search_term"])

        # Append to df

        # Return pd.DataFrame

        # and export to .tsv if outfile provided
        pass
