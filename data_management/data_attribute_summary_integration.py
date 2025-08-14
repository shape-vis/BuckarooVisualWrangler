"""
Converts the current datastate data into JSON the view can use
"""
import pandas as pd

from app.service_helpers import get_error_dist, is_categorical
from data_management.data_integration import get_filtered_dataframes


def generate_complete_json(min_id, max_id):
    """
    Generate a complete JSON representation of the current data state
    1. Get the current data state from the data state manager, filtered by min and max ID
    2. Get the error distribution for the current data state
    3. Convert the error distribution to a dictionary format
    4. Get the attributes from the main DataFrame
    5. Build the attribute distributions for each attribute in the main DataFrame
    6. Return a JSON object containing the column errors, attributes, and attribute distributions

    :param min_id: minimum ID for filtering data
    :param max_id: maximum ID for filtering data
    :return: JSON representation of the data state
    """
    main_df, error_df = get_filtered_dataframes(min_id, max_id)
    error_list = get_error_dist(error_df, main_df).to_dict('records')
    return {
        "columnErrors": convert_error_list_to_dict(error_list),
        "attributes": list(main_df.columns),
        "attributeDistributions": build_attribute_distributions(main_df)
    }

def get_attribute_stats(df, column):
    """
    Get statistics for a specific attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the column
    """
    if is_categorical(df[column]):
        return get_categorical_stats(df, column)
    return get_numeric_stats(df, column)

def build_attribute_distributions(main_df):
    """
    Build distributions for each attribute in the main DataFrame
    :param main_df: DataFrame containing the main data
    :return: dictionary containing distributions for each attribute
    """
    distributions = {}
    for col in main_df.columns:
        distributions[col] = get_attribute_stats(main_df, col)
    return distributions

def get_categorical_stats(df, column):
    """
    Get statistics for a categorical attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the categorical column
    """
    df_cat = df.copy()
    df_cat[column] = df_cat[column].fillna('N/A')
    return {
        "categorical": {
            "categories": df_cat[column].nunique(),
            "mode": df_cat[column].mode().iloc[0]
        }
    }

def get_numeric_stats(df, column):
    """
    Get statistics for a numeric attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the numeric column
    """
    df = df[pd.to_numeric(df[column], errors='coerce').notna()]
    df[column] = df[column].astype('int64')
    return {
        "numeric": {
            "mean": df[column].mean().item(),
            "min": df[column].min().item(),
            "max": df[column].max().item()
        }
    }

def convert_error_list_to_dict(error_list):
   """ 
   Convert the error list to a dictionary format
   :param error_list: list of error dictionaries
   :return: dictionary with a format like this (an example):
            "Age": {"incomplete": 0.75},
            "Country": {"missing": 2.25},
            "ConvertedSalary": {"incomplete": 2.5}
   """
   result = {}
   for row in error_list:
       if row != "error_type":
           error_type = row["error_type"]
           for col_key, percentage in row.items():
               if col_key != "error_type" and float(percentage) > 0:
                   col_name = col_key.strip()
                   if col_name not in result:
                       result[col_name] = {}
                   result[col_name][error_type] = float(percentage)
   return result

