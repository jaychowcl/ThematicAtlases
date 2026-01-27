'''
Docstring for ThematicAtlases.providers.search_provider

Module for providing search functionality. Interface into different search wrappers.
'''
class SearchProvider():
    """
    Class for providing search functionality. Interface into different search wrappers & query creation
    """

    def __init__(self, ):
        """

        """
        
        pass
    def create_search_queries(self, df: pd.DataFrame) -> List:
            '''
            Method for creating search queries from search terms

            Input:
                pd.DataFrame of search terms and filter groups
            Returns:
                List of search queries
            Do:
                Iterate through search terms and filter groups
                Create search queries based on search_term_regex_expression and filter_term_subgroup
                Return list of search queries
            Defense:
                Check if df has search_term_regex_expression and filter_term_subgroup columns
                Raise ValueError if not
            '''
            pass