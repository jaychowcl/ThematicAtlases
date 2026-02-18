'''
Docstring for ThematicAtlases.wrappers.geo_wrapper

Module for GEO API wrapper for ThematicAtlases. 

For api documentation, see https://www.ncbi.nlm.nih.gov/geo/info/geo_api.html
'''

import pandas as pd

class GEOWrapper():
    def __init__(self):
        pass

    def geo_get_metadata(self, accessions: pd.DataFrame = None) -> pd.DataFrame:
        """
        Docstring for geo_get_metadata

        :param self: GEOWrapper()
        :param accessions: pd.DataFrame of GEO accessions to get metadata for

        :step 1: set up api connection
        :step 2: get xml output from api for given accession
        :step 3: extract required metadata from xml and store in dict

        :return: pd.DataFrame of metadata for given GEO accessions
        """

        # if accessions is None:
            


    



        pass