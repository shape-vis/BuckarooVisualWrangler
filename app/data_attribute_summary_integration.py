"""
Converts the current datastate data into JSON the view can use
"""

"""
Refactored to use jacobs new backend sql files March 11,2026 - db_functions_sql.py, execute_sql.py, filtering_sql.py 
"""
import pandas as pd

from app.execute_sql import fetch_sql
from app.service_helpers import get_error_dist, is_categorical


def get_default_attributes_from_rankings(tablename, engine):
    """
    Fetch top 3 attributes from pre-computed rankings table.
    :param tablename: Name of the data table
    :param engine: SQLAlchemy engine
    :return: List of top 3 attribute names
    """
    try:
        query = f'SELECT attribute FROM "rankings_{tablename}" ORDER BY rank ASC LIMIT 3'
        rows = fetch_sql(query, False, engine)
        return [row[0] for row in rows] if rows else []
    except Exception as e:
        print(f"Error fetching rankings for table '{tablename}': {e}")
        return []



def generate_complete_json(tablename):
    """
    Generate a complete JSON representation of the current data state using the whole table.
    :param tablename: name of the table
    :return: JSON representation of the data state
    """
    from app import engine

    if not tablename:
        return {"columnErrors": {}, "attributes": [], "attributeDistributions": {}, "defaultAttributes": []}

    print(f"Generating JSON for table: {tablename}")

    main_rows = fetch_sql(f'SELECT * FROM "{tablename}"', False, engine)
    error_rows = fetch_sql(f'SELECT * FROM "errors_{tablename}"', False, engine)

    main_cols = fetch_sql(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{tablename}' ORDER BY ordinal_position", False, engine)
    error_cols = fetch_sql(f"SELECT column_name FROM information_schema.columns WHERE table_name = 'errors_{tablename}' ORDER BY ordinal_position", False, engine)

    main_df = pd.DataFrame(main_rows, columns=[row[0] for row in main_cols] if main_cols else None)
    error_df = pd.DataFrame(error_rows, columns=[row[0] for row in error_cols] if error_cols else None)

    error_list = get_error_dist(error_df, main_df).to_dict('records')
    default_attributes = get_default_attributes_from_rankings(tablename, engine)

    return {
        "columnErrors": convert_error_list_to_dict(error_list),
        "attributes": list(main_df.columns),
        "attributeDistributions": build_attribute_distributions(main_df),
        "defaultAttributes": default_attributes
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
    # Convert to numeric (handles both int and float)
    df[column] = pd.to_numeric(df[column], errors='coerce')
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




