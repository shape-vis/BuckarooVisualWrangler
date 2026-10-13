"""
Converts the current table's attribute summaries into JSON the view can use: each column's error rates and summary
statistics, read from the data profile, and the columns to show first.
"""

import app
from app.server_utils.service_helpers import _validate_identifier
from app.server_utils.workers import run_queries
from app.db_utils.data_profile import DataProfile


def get_default_attributes_from_rankings(tablename):
    """
    The three columns carrying the most error flags, from the pre-computed rankings table.
    :param tablename: Name of the data table
    :return: List of top 3 attribute names, or [] when they cannot be read
    """
    try:
        return app.db_operations.get_top_ranked_attributes(tablename, 3)
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

    data_profile = DataProfile(tablename, engine)
    attributes = list(data_profile.get_col_names())

    return {
        # Each column's error rates, counted in the database rather than by reading the table out of it
        "columnErrors": data_profile.calculate_error_distribution(),
        "attributes": attributes,
        "attributeDistributions": build_attribute_distributions(data_profile, attributes),
        "defaultAttributes": get_default_attributes_from_rankings(tablename)
    }

def get_attribute_stats(data_profile, column):
    """
    Get statistics for a specific attribute in the table
    :param data_profile: Data profile class instance (used for calculating summary stats)
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the column
    """

    if data_profile.col_types.is_categorical_mixed_col(column) or data_profile.col_types.is_categorical_col(column):
        return get_categorical_stats(data_profile, column)
    return get_numeric_stats(data_profile, column)

def build_attribute_distributions(data_profile, columns):
    """
    Build distributions for each attribute in the table. Each column's stats are their own lookups in the data
    profile, so the columns are read at the same time.
    :param data_profile: Data profile class instance (used for calculating summary stats)
    :param columns: the table's column names
    :return: dictionary containing distributions for each attribute
    """
    def stats_of(column):
        return get_attribute_stats(data_profile, column)

    column_stats = run_queries(stats_of, columns)

    distributions = {}
    for column, stats in zip(columns, column_stats):
        distributions[column] = stats
    return distributions

def get_categorical_stats(data_profile, column):
    """
    Get statistics for a categorical attribute
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
    Get statistics for a numeric attribute
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
