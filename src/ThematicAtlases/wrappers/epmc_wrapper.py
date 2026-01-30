"""
Docstring for ThematicAtlases.wrappers.epmc_wrapper

Module for EuropePMC API wrapper for ThematicAtlases.

See https://europepmc.org/RestfulWebService#!/Europe32PMC32Articles32RESTful32API/ for API documentation.

"""

import pandas as pd
import requests

### logger ###
import logging
logger = logging.getLogger(__name__)

class EPMCWrapper:
    def __init__(self):
        pass

    def epmc_search_api(self, queries: list, page_limit: int = 5, page_size: int = 1000) -> pd.DataFrame:
        """
        Docstring for epmc_search_gather_publications
        Wrapper for EuropePMC Search API 
        https://www.ebi.ac.uk/europepmc/webservices/rest/search?

        :param self: EPMCWrapper()
        :param queries: list of queries to search EuropePMC API

        :step 1: set up api connection
        :step 2: initialize empty dataframe to store publication ids and metadata
        :step 2: get json output from api for each query
        :step 3: append required publication metadata to dataframe

        :return: DataFrame of publication ids and metadata
        """
        logger.debug("Searching for publications via EuropePMC Search API.")
        # set up api
        api = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"

        # Initialize DataFrame to store metdata
        required_metadata_fields = [
            "epmc_id",
            "source",
            "pmid",
            "pmcid",
            "doi",
            "title",
            "authorString",
            "abstractText",
            "affiliation",
            "fullTextUrls",  # involves extracting fullTextUrlList{fullTestUrl[{url}{url}]} from fullTextUrlList
            "firstPublicationDate",
        ]
        publications = pd.DataFrame(columns=required_metadata_fields)

        # iterate through each query
        for query in queries:

            # call api
            params = {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": page_size,
                "cursorMark": "*",
                "synonym": "TRUE",
            }

            # iterate through each page and extract hits
            nextCursorMark = "*"
            page = 0
            while nextCursorMark is not None and page <= page_limit:
                params["cursorMark"] = nextCursorMark
                response = requests.get(api, params=params)
                hits = response.json().get("resultList", {}).get("result", [])

                # extract nextCursorMark for paging & page limits
                nextCursorMark = response.json().get("nextCursorMark", None)
                page += 1
                # check if page is empty / final page
                if len(hits) == 0:
                    nextCursorMark = None
                    break

                # iterate through each hit to extract metadata
                for hit in hits:
                    publication_data = {}  # dictionary to store publication metadata

                    publication_data["epmc_id"] = hit.get("id", "")
                    publication_data["source"] = hit.get("source", "")
                    publication_data["pmid"] = hit.get("pmid", "")
                    publication_data["pmcid"] = hit.get("pmcid", "")
                    publication_data["doi"] = hit.get("doi", "")
                    publication_data["title"] = hit.get("title", "")
                    publication_data["authorString"] = hit.get("authorString", "")
                    publication_data["abstractText"] = hit.get("abstractText", "")
                    publication_data["affiliation"] = hit.get("affiliation", "")
                    full_text_urls = []
                    if "fullTextUrlList" in hit:  # TODO:
                        for url in hit["fullTextUrlList"]["fullTextUrl"]:
                            full_text_urls.append(url["url"])
                    publication_data["fullTextUrls"] = full_text_urls
                    publication_data["firstPublicationDate"] = hit.get(
                        "firstPublicationDate", ""
                    )
                    # append to publications DataFrame
                    publications.loc[len(publications)] = publication_data
        #enforce dtypes in publications pd.DataFrame TODO:

        #detect and remove duplicates TODO:


        return publications

    def epmc_datalinks_api(self, publications: pd.DataFrame) -> pd.DataFrame:
        """
        Docstring for epmc_datalinks_api
        Wrapper for EuropePMC Datalinks API
        https://www.ebi.ac.uk/europepmc/webservices/rest/{source}}/{id}}/datalinks

        :param self: EPMCWrapper()
        :param publications: pd.DataFrame of publications. Exects columns: ['epmc_id', 'source', 'pmid', 'pmcid', 'doi', 'title', 'authorString', 'abstractText', 'affiliation', 'fullTextUrls', 'firstPublicationDate']
        :type publications: pd.DataFrame

        :return: A pd.DataFrame of accessions, their publications, id scheme and idurl
        :rtype: pd.DataFrame

        :step 1: set up api connection
        :step 2: get json output from api for each publication
        :step 3: Extract accession id, accession id scheme , idurl
        """
        logger.debug("Gathering datalinks for publications via EuropePMC Datalinks API.")

        #TODO: validate pd.DataFrame has required columns and types
        
        # initialize dataframe to store datalinks
        required_metadata_fields = [
            "epmc_id",
            "source",
            "datalink_ID",
            "datalink_IDScheme",
            "datalink_IDURL",
            "datalink_Category"
        ]
        datalinks = pd.DataFrame(columns=required_metadata_fields)

        # iterate through each publication
        datalink_data = {} # dict to store datalink data 
        for epmc_id, source in publications[['epmc_id', 'source']].itertuples(index=False):  
            
            # set up and call api
            api = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks"
            params = {
                "format": "json",
            }
            response = requests.get(api, params=params)
            categories = response.json().get("dataLinkList", {}).get("Category", {})

            #store epmc and source
            datalink_data["epmc_id"] = epmc_id
            datalink_data["source"] = source

            #iterate through each category
            for category in categories:
                
                #store category name, check if category wanted
                datalink_data["datalink_Category"] = category.get("Name", "")
                desired_categories = ["ENA", "ArrayExpress", "BioSample", "SRA"]  #TODO: make so only goes into desired caategories. perhaps restrict in params when doing requests and loop over each datalink category?

                # extract datalink accessions
                for section in category.get("Section", []):
                    for link in section.get("Linklist", []).get("Link", []):
                        identifier = link.get("Target", "").get("Identifier", "")
                        ID = identifier.get("ID", "")
                        IDScheme = identifier.get("IDScheme", "")
                        IDURL = identifier.get("IDURL", "")
                        #store accession data
                        datalink_data["datalink_ID"] = ID
                        datalink_data["datalink_IDScheme"] = IDScheme
                        datalink_data["datalink_IDURL"] = IDURL
                        #append to datalinks pd.DataFrame
                        datalinks.loc[len(datalinks)] = datalink_data

        #enforce dtypes in publications pd.DataFrame TODO:

        #detect and remove duplicates TODO:

        return datalinks
    
    def epmc_textmine_publications(self, publications: pd.DataFrame) -> pd.DataFrame:
        pass


