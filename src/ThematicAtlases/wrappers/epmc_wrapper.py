"""
Docstring for ThematicAtlases.wrappers.epmc_wrapper

Module for EuropePMC API wrapper for ThematicAtlases.

See https://europepmc.org/RestfulWebService#!/Europe32PMC32Articles32RESTful32API/ for API documentation.

"""

import pandas as pd
import requests


class EPMCWrapper:
    def __init__(self):
        pass

    def epmc_search_api(self, queries: list, page_limit: int = 5) -> pd.DataFrame:
        """
        Docstring for epmc_search_gather_publications

        :param self: EPMCWrapper()
        :param queries: list of queries to search EuropePMC API


        :step 1: set up api connection
        :step 2: initialize empty dataframe to store publication ids and metadata
        :step 2: get json output from api for each query
        :step 3: append to dataframe

        :return: DataFrame of publication ids and metadata
        """

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
                "pageSize": 1000,
                "cursorMark": "*",
                "synonym": "TRUE",
            }

            # iterate through each page
            nextCursorMark = "*"
            page = 0
            while nextCursorMark is not None and page <= page_limit:
                params["cursorMark"] = nextCursorMark
                response = requests.get(api, params=params)
                hits = response.json().get("resultList", {}).get("result", [])

                # extract nextCursorMark for paging & page limits
                nextCursorMark = response.json().get("nextCursorMark", None)
                page += 1

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
                    if "fullTextUrlList" in hit: # TODO:
                        for url in hit["fullTextUrlList"]["fullTextUrl"]:
                            full_text_urls.append(url["url"])
                    publication_data["fullTextUrls"] = full_text_urls
                    publication_data["firstPublicationDate"] = hit.get("firstPublicationDate", "")
                    # append to publications DataFrame
                    publications.loc[len(publications)] = publication_data

        return publications

    # def epmc_datalinks_api(self, publications: list) -> dict: