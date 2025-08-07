'''
Constructs the JSON formats needed to render data in the view for the scatterplots
'''

import random
import numpy as np
import pandas as pd

from app.service_helpers import is_categorical
from data_management.data_integration import get_filtered_dataframes

def generate_scatterplot_sample_data(x_column, y_column, min_id, max_id, error_sample_size, total_sample_size):
    """Generate scatterplot data in the required JSON format"""
    # Get filtered data
    main_df, error_df = get_filtered_dataframes(min_id, max_id)
    print("got the dfs")
    # Determine column types
    x_type = get_column_type_for_scatterplot(main_df, x_column)
    y_type = get_column_type_for_scatterplot(main_df, y_column)
    print("got the types")
    # Sample data directly using the more efficient approach
    sampled_ids = sample_scatterplot_data(
        main_df, error_df, x_column, y_column, error_sample_size, total_sample_size
    )
    print("got the sampled ids")
    # Build data entries
    data_entries = []
    for row_id in sampled_ids:
        entry = build_scatterplot_data_entry(
            main_df, error_df, row_id, x_column, y_column, x_type, y_type
        )
        data_entries.append(entry)
    print("data_entries done")
    # Build scale information
    scale_x = get_scale_info_for_scatterplot(main_df, x_column, x_type)
    scale_y = get_scale_info_for_scatterplot(main_df, y_column, y_type)

    return {
        "data": data_entries,
        "scaleX": scale_x,
        "scaleY": scale_y
    }

def get_column_type_for_scatterplot(dataframe, column_name):
    """Determine if column is categorical or numeric for scatterplot"""
    column_data = dataframe[column_name].dropna()

    if len(column_data) == 0:
        return "categorical"  # Handle all-null case

    return "categorical" if is_categorical(column_data) else "numeric"


def get_errors_for_id(error_df, row_id, x_column, y_column):
    """Get list of error types for a specific ID and columns"""
    relevant_errors = error_df[
        (error_df['row_id'] == row_id) &
        (error_df['column_id'].isin([x_column, y_column]))
        ]
    return relevant_errors['error_type'].tolist()


def get_column_value_for_scatterplot(dataframe, row_id, column_name, column_type):
    """Get the actual value for a column, handling nulls appropriately"""
    row_data = dataframe[dataframe['ID'] == row_id]

    if len(row_data) == 0:
        return "null"

    value = row_data[column_name].iloc[0]

    if pd.isna(value):
        return "null"

    # Convert numpy/pandas types to native Python types - this
    # needs to happen so that it can convert it to JSON later on when the endpoint returns the data
    if hasattr(value, 'item'):
        return value.item()

    return value


def build_scatterplot_data_entry(main_df, error_df, row_id, x_column, y_column, x_type, y_type):
    """Build a single data entry for the scatterplot"""
    # Get x and y values
    x_value = get_column_value_for_scatterplot(main_df, row_id, x_column, x_type)
    y_value = get_column_value_for_scatterplot(main_df, row_id, y_column, y_type)

    # Get errors for this ID
    errors = get_errors_for_id(error_df, row_id, x_column, y_column)

    return {
        "ID": row_id,
        "xType": x_type,
        "yType": y_type,
        "x": x_value,
        "y": y_value,
        "errors": errors
    }


def get_scale_info_for_scatterplot(dataframe, column_name, column_type):
    """Get scale information for scatterplot axes"""
    if column_type == "categorical":
        unique_values = dataframe[column_name].dropna().unique().tolist()
        # Add "null" if there are any null values
        if dataframe[column_name].isna().any():
            unique_values.append("null")
        return {"numeric": [], "categorical": sorted(unique_values)}
    else:
        # For numeric, return the range
        non_null_values = dataframe[column_name].dropna()
        if len(non_null_values) == 0:
            return {"numeric": [0, 1], "categorical": []}

        min_val = non_null_values.min()
        max_val = non_null_values.max()
        # Add small buffer to max to include the maximum value
        return {"numeric": [int(min_val), int(max_val) + 1], "categorical": []}


def sample_scatterplot_data(main_df, error_df, x_column, y_column, error_sample_size, total_sample_size):
    """Directly sample data for scatterplot following the JavaScript pattern"""
    # Get IDs that have errors in the specified columns
    relevant_errors = error_df[error_df['column_id'].isin([x_column, y_column])]
    error_ids = set(relevant_errors['row_id'].unique())

    # Split main dataframe into error and non-error rows
    error_rows = main_df[main_df['ID'].isin(error_ids)].copy()
    non_error_rows = main_df[~main_df['ID'].isin(error_ids)].copy()

    # Randomly remove error rows until we have <= error_sample_size
    while len(error_rows) > error_sample_size:
        random_idx = random.randint(0, len(error_rows) - 1)
        error_rows = error_rows.drop(error_rows.index[random_idx]).reset_index(drop=True)

    # Randomly remove non-error rows until total <= total_sample_size
    while (len(error_rows) + len(non_error_rows)) > total_sample_size:
        random_idx = random.randint(0, len(non_error_rows) - 1)
        non_error_rows = non_error_rows.drop(non_error_rows.index[random_idx]).reset_index(drop=True)

    # Combine the sampled data
    sampled_data = pd.concat([error_rows, non_error_rows], ignore_index=True)

    return sampled_data['ID'].tolist()

