'''
Docstring for ThematicAtlases.validators.validate_search_terms

A module for validating search terms dataframes

'''
import pandas as pd

class SearchTermsValidator():

    def __init__(self):



        pass

    def validate_search_terms_df(self, df: pd.DataFrame) -> bool:
        '''
        Docstring for validate_search_terms_df
        Validates the format and contents of a search terms dataframe
        
        :param self: SearchTermsValidator()
        :param df: pd.DataFrame of search terms

        :step 1: Check required columns exist
        :step 2: Check data types of columns
        :step 3: Check for missing values
        :return: True if valid, raises ValueError if invalid
        '''

        required_columns = ["search_terms"]

        # Step 1: Check required columns exist
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Step 2: Check data types of columns
        if not pd.api.types.is_string_dtype(df["term"]):
            raise ValueError("Column 'term' must be of string type."))

        # Step 3: Check for missing values
        if df[required_columns].isnull().any().any():
            raise ValueError("Search terms dataframe contains missing values.")

        return True