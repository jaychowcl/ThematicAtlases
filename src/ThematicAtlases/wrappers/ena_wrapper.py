'''
Docstring for ThematicAtlases.wrappers.ena_wrapper

Module for ENA API wrapper for ThematicAtlases.

See https://europepmc.org/RestfulWebService#!/Europe32PMC32Articles32RESTful32API/ for API documentation.


'''

import pandas as pd
import requests


### logger ###
import logging
logger = logging.getLogger(__name__)

class ENAWrapper():
    def __init__(self):
        pass

    def ena_get_metadata(self, datalinks: pd.DataFrame) -> pd.DataFrame:
        """
        Docstring for ena_get_metadata
        Wrapper for ENA API 
        https://www.ebi.ac.uk/ena/browser/api/xml/{accession}

        :param self: ENAWrapper()
        :param datalinks: pd.DataFrame of datalinks

        :step 1: iterate through each datalink and 

        :return: dict of metadata fields
        """
        logger.debug(f"Getting metadata for accession {accession} via ENA API.")
        # set up api
        api = f"https://www.ebi.ac.uk/ena/browser/api/xml/{accession}"

        # get xml from api
        response = requests.get(api)
        if response.status_code != 200:
            logger.error(f"Failed to get metadata for accession {accession} via ENA API. Status code: {response.status_code}")
            return {}
        
        # parse xml to get metadata