'''
Docstring for ThematicAtlases.providers.wrapper_OLS
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
        Currently only takes exact matches
        # TODO: expand to include layer below? ie. child nodes?

        Input:
            string of single search_term

        Return:
            List of synonyms

        Do:
            Use search_term to search OLS API for synonyms. 
            Synonyms are 
        
        Defense:
        '''

        logger.debug(f"Wrapper_OLS.search_for_synonyms(): Contacting OLS API for synonym search for term: {search_term}")
        
        #OLS api to search and return json
        api = "https://www.ebi.ac.uk/ols4/api/search"
        payload = {
            "q": search_term,
            "fieldList" : "iri,label,obo_id",#fields being returned
            "queryFields" : "label, synonym, description, short_form, obo_id, annotations, logical_description, iri", #fields to query for search
            "exact" : "true",
            "rows" : "5000"
        }
        r = requests.get(api, params=payload)
        ols_json = r.json()
    

        #Extract synonyms from ols json:
        ## {response: {docs: [{label}]}}
        ## {response: {docs: [{obo_id}]}}
        synonyms = []
        for entry in ols_json["response"]["docs"]:
            synonyms.append(entry["label"])
            synonyms.append(entry["obo_id"])
        
        synonyms = list(set(synonyms))

        #TODO: expand synonym search to include child nodes?


        #end

        return synonyms