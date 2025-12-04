'''
wrappers/wrapper_OLS.py

Wrapper module for Ontology Lookup Service API


'''
from typing import List
import requests
import logging

logger = logging.getLogger(__name__)

class Wrapper_OLS:
    '''
    Wrapper for Ontology Lookup Service API
    '''
    def __init__(self):
        pass

    def search_for_synonyms(self, search_term:str) -> List:
        '''
        Method for searching for synonyms for a search term

        Input:
            string of single search_term

        Return:
            List of synonyms

        Do:
            Use search_term to search OLS API for synonyms
        
        Defense:
        '''

        logger.debug(f"Wrapper_OLS.search_for_synonyms(): Contacting OLS API for synonym search for term: {search_term}")
        
        #OLS api
        api = "https://www.ebi.ac.uk/ols4/api/search"
        payload = {
            "q": search_term,
            "fieldList" : "iri,label,short_form,obo_id,ontology_name,ontology_prefix,description,type",#fields being returned
            "queryFields" : "label, synonym, description, short_form, obo_id, annotations, logical_description, iri", #fields to query for search
            "exact" : "true",
            "rows" : "10"
        }
        r = requests.get(api, params=payload)
        print(r.url)


        #end