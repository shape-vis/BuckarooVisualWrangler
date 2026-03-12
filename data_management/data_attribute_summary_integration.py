"""
Converts the current datastate data into JSON the view can use
"""
import pandas as pd

from app.execute_sql import fetch_sql
from app.service_helpers import get_error_dist, is_categorical
from data_management.data_integration import get_filtered_dataframes
from app import engine


# def get_default_attributes_from_rankings(tablename, engine):
#     """
#     Fetch top 3 attributes from pre-computed rankings table
#     :param tablename: Name of the data table (will be cleaned if needed)
#     :param engine: SQLAlchemy engine
#     :return: List of top 3 attribute names
#     """
#     # from app.service_helpers import clean_table_name
#
#     try:
#         # cleaned_tablename = clean_table_name(tablename)
#         rankings_table = f"rankings_{tablename}"
#
#         # Try exact match first
#         try:
#             query = f"SELECT attribute FROM {rankings_table} ORDER BY rank ASC LIMIT 3"
#             result = pd.read_sql_query(query, engine)
#             return result['attribute'].tolist()
#         except Exception:
#             # Fallback: search for similar table names (handles version suffixes)
#             # Create pattern: if looking for "rankings_stackoverflow_db_uncleaned_version_5"
#             # also match "rankings_stackoverflow_db_uncleaned"
#             base_pattern = cleaned_tablename.split('_version')[0] if '_version' in cleaned_tablename else cleaned_tablename
#             pattern = f"rankings_{base_pattern}%"
#
#             matching_tables = pd.read_sql_query(
#                 "SELECT tablename FROM pg_tables WHERE tablename LIKE %s ORDER BY tablename DESC LIMIT 1",
#                 engine,
#                 params=(pattern,)
#             )
#
#             if not matching_tables.empty:
#                 found_table = matching_tables.iloc[0]['tablename']
#                 query = f"SELECT attribute FROM {found_table} ORDER BY rank ASC LIMIT 3"
#                 result = pd.read_sql_query(query, engine)
#                 return result['attribute'].tolist()
#             else:
#                 return []
#
#     except Exception as e:
#         print(f"Error fetching rankings for table '{tablename}': {e}")
#         return []
#

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

# def generate_complete_json(min_id, max_id, tablename=None):
#     """
#     Generate a complete JSON representation of the current data state
#     1. Get the current data state from the data state manager, filtered by min and max ID
#     2. Get the error distribution for the current data state
#     3. Convert the error distribution to a dictionary format
#     4. Get the attributes from the main DataFrame
#     5. Build the attribute distributions for each attribute in the main DataFrame
#     6. Return a JSON object containing the column errors, attributes, and attribute distributions
#
#     :param min_id: minimum ID for filtering data
#     :param max_id: maximum ID for filtering data
#     :param tablename: name of the table (optional, for fetching default attributes)
#     :return: JSON representation of the data state
#     """
#     from app import engine
#
#     # main_df, error_df = get_filtered_dataframes(min_id, max_id)
#     # error_list = get_error_dist(error_df, main_df).to_dict('records')
#     print(f"Generating JSON for IDs between {min_id} and {max_id} (Table: {tablename})")
#
#     # use sql to get the data from the table into a data frame
#     if tablename:
#         query = f"SELECT * FROM \"{tablename}\" WHERE index >= {min_id} AND index <= {max_id}"
#         main_df = pd.read_sql_query(query, engine)
#         query = f"SELECT * FROM \"errors_{tablename}\" WHERE index >= {min_id} AND index <= {max_id}"
#         error_df = pd.read_sql_query(query, engine)
#         error_list = get_error_dist(error_df, main_df).to_dict('records')
#
#
#     default_attributes = []
#     if tablename:
#         default_attributes = get_default_attributes_from_rankings(tablename, engine)
#
#     return {
#         "columnErrors": convert_error_list_to_dict(error_list),
#         "attributes": list(main_df.columns),
#         "attributeDistributions": build_attribute_distributions(main_df),
#         "defaultAttributes": default_attributes
#     }

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


"""
Refactored to use jacobs new backend sql files - db_functions_sql.py, execute_sql.py, filtering_sql.py 
"""

