"""
Helper functions which allow the data being represented in the server as dataframes along with the
data state manager, and data state objects to be translated in to the desired JSON formats needed by the view
to render the data
"""
from app import data_state_manager
from app.service_helpers import is_categorical, create_bins_for_a_numeric_column, get_error_dist, \
    slice_data_by_min_max_ranges
import pandas as pd
import numpy as np


def generate_1d_histogram_data(column, num_bins,min_id,max_id):
    current_state = data_state_manager.get_current_state()
    df, error_df = current_state["df"], current_state["error_df"]
    print("before slicing")
    df, error_df = slice_data_by_min_max_ranges(min_id,max_id,df,error_df)
    print("after slicing")
    column_type, _ = determine_column_type_and_bins(df, column, num_bins)

    if column_type == "categorical":
        return build_categorical_histogram(df, error_df, column)
    else:
        return build_numeric_histogram(df, error_df, column, num_bins)

#helper for determining what the type is and how the bins should be created
def determine_column_type_and_bins(df, column, num_bins):
    #data without NA
    column_data = df[column].dropna()
    if is_categorical(column_data):
        return "categorical", column_data.unique().tolist()
    else:
        return "numeric", create_bins_for_a_numeric_column(column_data, num_bins)


def get_optimized_error_counts_by_bins(df, error_df, column, bin_assignments):
    # Get full error distribution once
    full_error_dist = get_error_dist(error_df)

    # Filter for our column
    if column not in full_error_dist.columns:
        return {}

    column_errors = error_df[error_df['column_id'] == column]
    # Create mapping of row_id to bin
    row_to_bin = {}
    for idx, row in df.iterrows():
        if pd.notna(row[column]) and idx < len(bin_assignments):
            row_to_bin[row['ID']] = bin_assignments[idx]

    # Group errors by bin
    bin_error_counts = {}
    for _, error_row in column_errors.iterrows():
        row_id = error_row['row_id']
        error_type = error_row['error_type']

        if row_id in row_to_bin:
            bin_num = row_to_bin[row_id]
            if bin_num not in bin_error_counts:
                bin_error_counts[bin_num] = {}

            bin_error_counts[bin_num][error_type] = bin_error_counts[bin_num].get(error_type, 0) + 1

    return bin_error_counts


def count_categorical_bins_with_error_types(df, error_df, column):
    categories = df[column].dropna().unique()

    # Create category-to-bin mapping
    category_to_bin = {cat: i for i, cat in enumerate(categories)}
    bin_assignments = df[column].map(category_to_bin).values

    # Get error counts by bin efficiently
    bin_error_counts = get_optimized_error_counts_by_bins(df, error_df, column, bin_assignments)

    results = []
    for i, category in enumerate(categories):
        category_rows = df[df[column] == category]
        items = len(category_rows)
        error_types = bin_error_counts.get(i, {})

        results.append({
            "items": items,
            "error_types": error_types,
            "bin": i,
            "category": category
        })

    return results, categories


def count_numeric_bins_with_error_types(df, error_df, column, num_bins):
    df_clean = df.dropna(subset=[column]).copy()
    bins = create_bins_for_a_numeric_column(df_clean[column], num_bins)

    # Get bin assignments as integers
    bin_assignments = bins.cat.codes.values

    # Get error counts by bin efficiently
    bin_error_counts = get_optimized_error_counts_by_bins(df_clean, error_df, column, bin_assignments)

    results = []
    for i, bin_interval in enumerate(bins.cat.categories):
        bin_rows = df_clean[bins.cat.codes == i]
        items = len(bin_rows)
        error_types = bin_error_counts.get(i, {})

        results.append({
            "items": items,
            "error_types": error_types,
            "bin": i,
            "interval": bin_interval
        })

    return results, bins.cat.categories


def format_error_counts(error_type_counts, total_items):
    count_dict = {"items": total_items}

    # Add each error type found dynamically
    for error_type, count in error_type_counts.items():
        count_dict[error_type] = count

    return count_dict


def build_categorical_histogram(df, error_df, column):
    results, categories = count_categorical_bins_with_error_types(df, error_df, column)

    histograms = []
    for r in results:
        count_dict = format_error_counts(r["error_types"], r["items"])
        histograms.append({
            "count": count_dict,
            "xBin": r["bin"],
            "xType": "categorical"
        })

    return {
        "histograms": histograms,
        "scaleX": {"numeric": [], "categorical": categories.tolist()}
    }


def build_numeric_histogram(df, error_df, column, num_bins):
    results, bin_intervals = count_numeric_bins_with_error_types(df, error_df, column, num_bins)

    ranges = [{"x0": int(interval.left), "x1": int(interval.right)}
              for interval in bin_intervals]

    histograms = []
    for r in results:
        count_dict = format_error_counts(r["error_types"], r["items"])
        histograms.append({
            "count": count_dict,
            "xBin": r["bin"],
            "xType": "numeric"
        })

    return {
        "histograms": histograms,
        "scaleX": {"numeric": ranges, "categorical": []}
    }

