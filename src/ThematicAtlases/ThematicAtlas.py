"""
Docstring for ThematicAtlases.ThematicAtlas

This module contains the ThematicAtlas class, which is used to create and manage thematic atlases for organizing transcriptomic data based on specific themes or topics.

ThematicAtlas()


"""

import pandas as pd

from .wrappers.wrappers import Wrappers


### logger ###
import logging
from pathlib import Path

log_path = Path(".logs/ThematicAtlases.log")
log_path.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logger_format = (
    "%(asctime)s | %(name)s | %(levelname)s | "
    "%(filename)s:%(lineno)d | %(module)s:%(funcName)s | %(message)s"
)
logging.basicConfig(
    level=logging.DEBUG,
    format=logger_format,
    filename=log_path,
    filemode="a",
)


### ThematicAtlas class ###
class ThematicAtlas:
    def __init__(self):
        self.queries = None
        self.accessions = None
        self.publications = None

        pass

    def import_queries(self, filepath: str = None, query_list: list = None) -> pd.DataFrame:
        """
        Docstring for import_queries
        Imports search terms used for publication search. Please provide one of filepath or df.

        :param self: ThematicAtlas()
        :param filepath: filepath of .txt of queries. Each row must be a separate query.
        :param list: list of queries

        :step 1: Check if only one of filepath or df is provided
        :step 2: Import queries from filepath or df
        :step 3: Queries are put into lists with each element being a query
        :step 3a: Elements in list starting wtih # will be ignored
        :step 4: Store queries in self.queries

        :return: Return self.queries
        """
        logger.info("Importing queries for publication search.")
        # check if only one of filepath or df is provided
        if (filepath is None) == (query_list is None):
            raise ValueError("Exactly one of 'filepath' or 'df' must be provided.")

        # import search_terms
        if filepath is not None: ##read from filepath
            try:
                with open(filepath, "r") as f:
                    queries = f.read().splitlines()
            except Exception as e:
                raise ValueError(f"Error reading search terms from {filepath}: {e}")
        if query_list is not None: ##read from df
            queries = query_list
        
        #process queries to ignore lines starting with 
        queries = [query for query in queries if not query.strip().startswith("#")]

        #store queries into self.queries
        self.queries = queries

        # return self.queries
        return self.queries


    def search_for_publications(self, filepath:str = None, query_list: list = None) -> pd.DataFrame:
        """
        Docstring for search_publications

        :param self: ThematicAtlas()

        :step 1: Use ThematicAtlas.import_queries to load queries if given. Skip if filepath or df is None
        :step 3: Use ThematicAtlases.wrappers to use queries to search EuropePMC api to get publications and publication metadata
            - Search for publication id, and metadata
                - https://www.ebi.ac.uk/europepmc/webservices/rest/search?
                - Iterate through all pages of search using <nextPageUrl>
        :step 3a: Store publication ids and metadata into self.publications a pd.DataFrame of publication and publication metadata
        :step 4: Use ThematicAtlases.wrappers to use publication ids to search EuropePMC to get any relevant ENA accessions in datalinks
            - Search publication ids for relevant datalinks
                - https://www.ebi.ac.uk/europepmc/webservices/rest/{source}}/{id}}/datalinks
        :step 5: Use ThematicAtlases.wrappers to use publications ids to search EuropePMC to get full text XMls and text mine ENA accessions.
            - Use publication ids to get full text XMls
            - pass it text miner to get text mined ENA accessions
                - https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML
        :step 6: Store accessions from publications into self.accessions, a dictionary of {accession: publication_id}
        :return: return self.accessions

        """
        logger.info("Searching for publications, publication metdata and datalinks using EuropePMC APIs.")
        # load search terms if given
        if filepath is not None or query_list is not None:
            self.import_queries(filepath=filepath, query_list = query_list)
        
        epmc_wrapper = Wrappers()
        # search for pubs via search api
        logger.debug("Gathering publications from queries via EuropePMC Datalinks API")
        publications = epmc_wrapper.epmc_search_api(queries=self.queries, page_limit=1, page_size=250)
        # gather datalinks and their accessions for each publication
        logger.debug("Gathering datalinks from publications via EuropePMC Datalinks API.")
        datalinks = epmc_wrapper.epmc_datalinks_api(publications=publications)
        # gather full text XMLs and text mine accessions for each publication
        logger.debug("Gathering full text XMLs and text mining accessions via EuropePMC FullTextXML API.")
        full_text_xmls = epmc_wrapper.epmc_textmine_publications(publications=publications)
        # datalinks

        # full text XML

        # store in self.datalinks

        # return self.publications
        pass

    def get_metadata_for_accessions(self):
        """
        Docstring for get_metadata_for_accessions

        :param self: ThematicAtlas()

        :step 1: For each accession in self.accessions, use ThematicAtlases.wrappers to get ENA metadata object
            - https://www.ebi.ac.uk/ena/browser/api/xml/{accession}
        :step 2: Store metadata objects into self.metadata, a dictionary of {accession: metadata_object}
        :return: return self.metadata

        """

        pass
