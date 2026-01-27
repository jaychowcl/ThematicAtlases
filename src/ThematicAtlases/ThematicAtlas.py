'''
Docstring for ThematicAtlases.ThematicAtlas

This module contains the ThematicAtlas class, which is used to create and manage thematic atlases for organizing transcriptomic data based on specific themes or topics.

ThematicAtlas()

    
'''
import pandas as pd
import requests
from validators import validate_search_terms_df

class ThematicAtlas():
    def __init__(self):
        self.search_terms = None
        self.accessions = None

        pass

    def import_search_terms(self, filepath: str, df: pd.DataFrame) -> pd.DataFrame:
        '''
        Docstring for import_search_terms
        Imports search terms used for publication search
        
        :param self: ThematicAtlas()
        :param filepath: filepath of .tsv of search terms
        :param df: pd.DataFrame of search terms 

        :step 1: Check if only one of filepath or df is provided
        :step 2: Validate format and contents of search terms data
        :step 3: Store search terms in self.search_terms
        :return: Return self.search_terms
        '''
        #check if only one of filepath or df is provided
        if (filepath is None) == (df is None):
            raise ValueError("Exactly one of 'filepath' or 'df' must be provided.")

        #import search_terms
        ##read from filepath
        if filepath is not None:
            try:
                search_terms_df = pd.read_csv(filepath, sep="\t")
            except Exception as e:
                raise ValueError(f"Error reading search terms from {filepath}: {e}")
        ##read from df
        if df is not None:
            search_terms_df = df

        #validate format and contents using validators.validate_search_terms_df

        validate_search_terms_df(search_terms_df)

        pass

    def search_and_get_accessions(self, filepath, df):
        '''
        Docstring for search_publications
        
        :param self: ThematicAtlas()

        :step 1: Use ThematicAtlas.import_search_terms to load search terms if given. Skip if filepath or df is None
        :step 2: Build queries 
        :step 3: Use ThematicAtlases.wrappers to use queries to search EuropePMC api to get publications and publication metadata
            - Search for publication id, and metadata
                - https://www.ebi.ac.uk/europepmc/webservices/rest/search? 
                - Iterate through all pages of search using <nextPageUrl>
        :step 3a: Store publication ids and metadata into self.publications a dictionary of {publication_id: [metadata}
        :step 4: Use ThematicAtlases.wrappers to use publication ids to search EuropePMC to get any relevant ENA accessions in datalinks
            - Search publication ids for relevant datalinks
                - https://www.ebi.ac.uk/europepmc/webservices/rest/{source}}/{id}}/datalinks
        :step 5: Use ThematicAtlases.wrappers to use publications ids to search EuropePMC to get full text XMls and text mine ENA accessions.
            - Use publication ids to get full text XMls 
            - pass it text miner to get text mined ENA accessions
                - https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML
        :step 6: Store accessions from publications into self.accessions, a dictionary of {accession: publication_id}
        :return: return self.accessions

        '''

        #load search terms if given
        if filepath is not None or df is not None:
            self.import_search_terms(filepath=filepath, df=df)
        
        #use search terms to build queries




        pass

    def get_metadata_for_accessions(self):
        '''
        Docstring for get_metadata_for_accessions
        
        :param self: ThematicAtlas()

        :step 1: For each accession in self.accessions, use ThematicAtlases.wrappers to get ENA metadata object
            - https://www.ebi.ac.uk/ena/browser/api/xml/{accession}
        :step 2: Store metadata objects into self.metadata, a dictionary of {accession: metadata_object}
        :return: return self.metadata

        '''



        pass