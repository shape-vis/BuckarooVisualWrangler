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


#main drivers
def generate_1d_histogram_data(column_name, number_of_bins, min_id, max_id):
    """Generate 1D histogram data"""
    return generate_histogram_data([column_name], [number_of_bins], min_id, max_id)

def generate_2d_histogram_data(x_column, y_column, x_bins, y_bins, min_id, max_id):
    """Generate 2D histogram data"""
    return generate_histogram_data([x_column, y_column], [int(x_bins),int(y_bins)], min_id, max_id)

def generate_2d_histogram_data_modified(df, error_df, x_column, y_column, x_bins, y_bins, min_id, max_id):
    """Generate 2D histogram data"""
    return generate_histogram_data_modified(df, error_df, [x_column, y_column], [int(x_bins),int(y_bins)], min_id, max_id)

#Data access functions
def get_filtered_dataframes(min_id, max_id):
    """Get current dataframes filtered by ID range"""
    current_state = data_state_manager.get_current_state()
    main_df = current_state["df"]
    error_df = current_state["error_df"]
    return slice_data_by_min_max_ranges(min_id, max_id, main_df, error_df)


def get_relevant_errors(error_df, column_names):
    """Get errors that relate to the specified columns"""
    return error_df[error_df['column_id'].isin(column_names)]

#Column processing
def get_column_bin_assignments(dataframe, column_name, number_of_bins):
    """Create bin assignments for any column type"""
    column_data = dataframe[column_name].dropna()

    if len(column_data) == 0:
        # Treat as categorical with single "null" category
        scale_data = ["null"]
        # All rows get assigned to bin 0 (the null bin)
        bin_assignments = np.zeros(len(dataframe), dtype=int)
        return bin_assignments, scale_data, "categorical"

    if is_categorical(column_data):
        unique_categories = column_data.unique()
        category_to_bin = {category: index for index, category in enumerate(unique_categories)}
        bin_assignments = dataframe[column_name].map(category_to_bin).values
        return bin_assignments, unique_categories, "categorical"
    else:
        df_clean = dataframe.dropna(subset=[column_name])
        numeric_bins = create_bins_for_a_numeric_column(df_clean[column_name], number_of_bins)
        bin_assignments = numeric_bins.cat.codes.values
        return bin_assignments, numeric_bins.cat.categories, "numeric"

#row to bin mapping
def create_row_to_bin_mapping(dataframe, column_names, all_bin_assignments):
    """Map each row ID to its bin coordinates across all dimensions"""
    row_to_bin_mapping = {}

    for row_index, data_row in dataframe.iterrows():
        # Get bin coordinates for this row
        bin_coordinates = []
        valid_row = True

        for bin_assignments in all_bin_assignments:
            if row_index < len(bin_assignments) and bin_assignments[row_index] >= 0:
                bin_coordinates.append(bin_assignments[row_index])
            else:
                valid_row = False
                break

        if valid_row:
            row_to_bin_mapping[data_row['ID']] = tuple(bin_coordinates)

    return row_to_bin_mapping

#counting functions
def count_items_per_bin(row_to_bin_mapping):
    """Count total items in each bin"""
    items_per_bin = {}
    for bin_coordinates in row_to_bin_mapping.values():
        items_per_bin[bin_coordinates] = items_per_bin.get(bin_coordinates, 0) + 1
    return items_per_bin


def count_errors_per_bin(relevant_errors, row_to_bin_mapping):
    """Count errors by type in each bin"""
    errors_per_bin = {}

    for _, error_row in relevant_errors.iterrows():
        row_id = error_row['row_id']
        error_type = error_row['error_type']

        if row_id in row_to_bin_mapping:
            bin_coordinates = row_to_bin_mapping[row_id]

            if bin_coordinates not in errors_per_bin:
                errors_per_bin[bin_coordinates] = {}

            current_count = errors_per_bin[bin_coordinates].get(error_type, 0)
            errors_per_bin[bin_coordinates][error_type] = current_count + 1

    return errors_per_bin

#scale info functions
def create_scale_info(scale_data, column_type):
    """Create scale information for histogram axes"""
    if column_type == "categorical":
        categories = scale_data.tolist() if hasattr(scale_data, 'tolist') else list(scale_data)
        return {"numeric": [], "categorical": categories}
    else:
        ranges = [{"x0": int(interval.left), "x1": int(interval.right)} for interval in scale_data]
        return {"numeric": ranges, "categorical": []}
    
def generate_histogram_data_modified(main_df, error_df, column_names, numbers_of_bins, min_id, max_id):
    """Generate histogram data for 1D or 2D histograms"""
    if len(column_names) > 2:
        raise ValueError("Maximum 2 dimensions supported for now")
    print("generating histogram data")
    # Get filtered data ( get the window of min/max data from the datatable)
    print("got filtered df")
    # Process each column to get bin assignments and scale data
    all_bin_assignments = []
    all_scale_data = []
    all_column_types = []

    for column_name, number_of_bins in zip(column_names, numbers_of_bins):
        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            main_df, column_name, number_of_bins
        )
        all_bin_assignments.append(bin_assignments)
        all_scale_data.append(scale_data)
        all_column_types.append(column_type)
        print("Added column to bin assignments and scale data:", column_name)

    print("bin assignments, and scale data compiled")
    # Create mappings and count items/errors
    row_to_bin_mapping = create_row_to_bin_mapping(main_df, column_names, all_bin_assignments)
    relevant_errors = get_relevant_errors(error_df, column_names)

    items_per_bin = count_items_per_bin(row_to_bin_mapping)
    errors_per_bin = count_errors_per_bin(relevant_errors, row_to_bin_mapping)

    # Build histogram entries
    histogram_entries = build_histogram_entries(
        items_per_bin, errors_per_bin, all_scale_data, all_column_types
    )

    # Build response
    response = {"histograms": histogram_entries}

    if len(column_names) == 1:
        response["scaleX"] = create_scale_info(all_scale_data[0], all_column_types[0])
    elif len(column_names) == 2:
        response["scaleX"] = create_scale_info(all_scale_data[0], all_column_types[0])
        response["scaleY"] = create_scale_info(all_scale_data[1], all_column_types[1])

    return response

def generate_histogram_data(column_names, numbers_of_bins, min_id, max_id):
    """Generate histogram data for 1D or 2D histograms"""
    if len(column_names) > 2:
        raise ValueError("Maximum 2 dimensions supported for now")
    print("generating histogram data")
    # Get filtered data ( get the window of min/max data from the datatable)
    main_df, error_df = get_filtered_dataframes(min_id, max_id)
    print("got filtered df")
    # Process each column to get bin assignments and scale data
    all_bin_assignments = []
    all_scale_data = []
    all_column_types = []

    for column_name, number_of_bins in zip(column_names, numbers_of_bins):
        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            main_df, column_name, number_of_bins
        )
        all_bin_assignments.append(bin_assignments)
        all_scale_data.append(scale_data)
        all_column_types.append(column_type)
        print("Added column to bin assignments and scale data:", column_name)

    print("bin assignments, and scale data compiled")
    # Create mappings and count items/errors
    row_to_bin_mapping = create_row_to_bin_mapping(main_df, column_names, all_bin_assignments)
    relevant_errors = get_relevant_errors(error_df, column_names)

    items_per_bin = count_items_per_bin(row_to_bin_mapping)
    errors_per_bin = count_errors_per_bin(relevant_errors, row_to_bin_mapping)

    # Build histogram entries
    histogram_entries = build_histogram_entries(
        items_per_bin, errors_per_bin, all_scale_data, all_column_types
    )

    # Build response
    response = {"histograms": histogram_entries}

    if len(column_names) == 1:
        response["scaleX"] = create_scale_info(all_scale_data[0], all_column_types[0])
    elif len(column_names) == 2:
        response["scaleX"] = create_scale_info(all_scale_data[0], all_column_types[0])
        response["scaleY"] = create_scale_info(all_scale_data[1], all_column_types[1])

    return response

def format_error_counts(error_type_counts, total_items):
    """Format error counts into the required structure"""
    count_dict = {"items": total_items}
    for error_type, count in error_type_counts.items():
        count_dict[error_type] = count
    return count_dict


def get_bin_value_for_dimension(bin_index, scale_data, column_type):
    """Get the appropriate bin value for a single dimension"""
    if column_type == "categorical":
        return scale_data[bin_index]
    else:
        return bin_index


def create_count_information(bin_coordinates, items_per_bin, errors_per_bin):
    """Create the count information for a single bin"""
    item_count = items_per_bin.get(bin_coordinates, 0)
    error_types_in_bin = errors_per_bin.get(bin_coordinates, {})
    return format_error_counts(error_types_in_bin, item_count)


def add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types):
    """Add dimension-specific bin and type information to histogram entry"""
    num_dimensions = len(all_column_types)

    if num_dimensions == 1:
        entry["xBin"] = get_bin_value_for_dimension(
            bin_coordinates[0], all_scale_data[0], all_column_types[0]
        )
        entry["xType"] = all_column_types[0]
    elif num_dimensions == 2:
        entry["xBin"] = get_bin_value_for_dimension(
            bin_coordinates[0], all_scale_data[0], all_column_types[0]
        )
        entry["yBin"] = get_bin_value_for_dimension(
            bin_coordinates[1], all_scale_data[1], all_column_types[1]
        )
        entry["xType"] = all_column_types[0]
        entry["yType"] = all_column_types[1]

    return entry


def create_single_histogram_entry(bin_coordinates, items_per_bin, errors_per_bin, all_scale_data, all_column_types):
    """Create a single histogram entry for given bin coordinates"""
    entry = {"count": create_count_information(bin_coordinates, items_per_bin, errors_per_bin)}
    return add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types)


def generate_all_bin_coordinate_combinations(all_scale_data):
    """Generate all possible bin coordinate combinations"""
    import itertools
    bins_per_dimension = [len(scale_data) for scale_data in all_scale_data]
    return itertools.product(*[range(num_bins) for num_bins in bins_per_dimension])


def build_histogram_entries(items_per_bin, errors_per_bin, all_scale_data, all_column_types):
    """Build all histogram entries for the response"""
    histogram_entries = []

    all_bin_coordinates = generate_all_bin_coordinate_combinations(all_scale_data)

    for bin_coordinates in all_bin_coordinates:
        entry = create_single_histogram_entry(
            bin_coordinates, items_per_bin, errors_per_bin, all_scale_data, all_column_types
        )
        histogram_entries.append(entry)

    return histogram_entries