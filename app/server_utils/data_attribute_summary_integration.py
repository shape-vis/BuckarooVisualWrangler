"""
Converts the current datastate data into JSON the view can use
"""

"""
Refactored to use jacobs new backend sql files March 11,2026 - db_functions_sql.py, execute_sql.py, filtering_sql.py 
"""

from app.db_utils.execute_sql import fetch_sql
from app.server_utils.service_helpers import get_error_dist, is_categorical, _validate_identifier
from app.db_utils.data_profile import DataProfile


def get_default_attributes_from_rankings(tablename, engine):
    """
    Fetch top 3 attributes from pre-computed rankings table.
    :param tablename: Name of the data table
    :param engine: SQLAlchemy engine
    :return: List of top 3 attribute names
    """
    try:
        _validate_identifier(tablename)
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

    _validate_identifier(tablename)
    print(f"Generating JSON for table: {tablename}")

    data_profile = DataProfile(tablename, engine)

    error_df = data_profile.get_error_df()
    main_df = data_profile.get_main_df()
    error_list = get_error_dist(error_df, main_df).to_dict('records')

    default_attributes = get_default_attributes_from_rankings(tablename, engine)


    return {
        "columnErrors": convert_error_list_to_dict(error_list),
        "attributes": list(data_profile._main_df.columns),
        "attributeDistributions": build_attribute_distributions(data_profile),
        "defaultAttributes": default_attributes
    }

def get_attribute_stats(data_profile, column):
    """
    Get statistics for a specific attribute in the DataFrame
    :param data_profile: Data profile class instance (used for calculating summary stats)
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the column
    """
    if is_categorical(data_profile._main_df[column]):
        return get_categorical_stats(data_profile, column)
    return get_numeric_stats(data_profile, column)

def build_attribute_distributions(data_profile):
    """
    Build distributions for each attribute in the main DataFrame
    :param data_profile: Data profile class instance (used for calculating summary stats)
    :return: dictionary containing distributions for each attribute
    """
    distributions = {}

    for col in data_profile.get_col_names():
        distributions[col] = get_attribute_stats(data_profile, col)
    return distributions

def get_categorical_stats(data_profile, column):
    """
    Get statistics for a categorical attribute in the DataFrame
    :param data_profile: DataProfile class instance with optimized summary stat calculation functions
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the categorical column
    """
    return {
        "categorical": {
            "categories": data_profile.calculate_column_attribute('n_categories', column),
            "mode": data_profile.calculate_column_attribute('mode', column)
        }
    }

def get_numeric_stats(data_profile, column):
    """
    Get statistics for a numeric attribute in the DataFrame
    :param data_profile: DataProfile class instance with optimized summary stat calculation functions
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the numeric column
    """
    return {
        "numeric": {
            "mean": data_profile.calculate_column_attribute('mean', column),
            "min": data_profile.calculate_column_attribute('min', column),
            "max": data_profile.calculate_column_attribute('max', column)
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




