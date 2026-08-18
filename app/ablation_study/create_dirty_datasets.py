
import sys
import pandas as pd
import itertools
import random as rand
import numpy as np
import uuid
import csv
from app.db_utils.column_types import ColumnTypes
from app.routes.routes import load_file
from app import db_operations, engine

assert len(sys.argv) == 2, "Usage: python create_dirty_datasets <path_to_csv>"

# Read in dataset name as a command line arg
csv_path = sys.argv[1]

def randomly_select_idx_and_col_pairs(pairs_with_no_errors, num_rows, percentage_to_select):
    num_pairs_to_select = int(len(num_rows) * percentage_to_select)
    selected_idx_col_pairs = rand.sample(pairs_with_no_errors, num_pairs_to_select)

    return selected_idx_col_pairs

def apply_errors_to_dataframe(row_col_tuples,  dataframe, error_type, col_types):
    rows, cols = map(list, zip(*row_col_tuples))

    if error_type == "missing":
        # any col type
        dataframe.loc[rows, cols] = None
    elif error_type == "mismatch":
        # any col type
        for (row, col) in zip(rows, cols):
            if col_types.is_numeric(col):
                dataframe.loc[row, col] = "artificial_mismatch_error"
            elif col_types.is_categorical(col):
                dataframe.loc[row, col] = 10000
    elif error_type == "incomplete":
        # only categorical
        # TODO: isn't this always gonna show up as an error if it marks an identifier col as "categorical"??

        for (row, col) in zip(rows, cols):
            if not col_types.is_categorical(col):
                continue

            # Just adding a random unique ID
            dataframe.loc[row, col] = str(uuid.uuid4())
    elif error_type == "anomaly":
        # only numeric
        # TODO:idk if this is gonna work bc one of the columns may not be numeric?
        numeric_col_count = 0

        for col in cols:
            if not col_types.is_numeric(col):
                continue
            numeric_col_count += 1

            col_mean = dataframe[col].mean()
            dataframe.loc[rows, col] = col_mean * 10000

        print("Number of numeric cols: ", numeric_col_count)

    else:
        raise ValueError("Invalid error type")

    return dataframe

if __name__ == '__main__':

    # Read in the dataset
    dataset = pd.read_csv(csv_path)

    # Have to load the file into a table so that we can use ColumnTypes
    load_file(csv_path)

    col_names = dataset.columns.tolist()
    col_types = ColumnTypes(db_operations.main_table_name, engine)

    num_cols = len(col_names)
    num_rows = len(dataset)

    # All possible idx and column tuple pairs

    all_possible_pairs = np.array(itertools.product(range(num_rows), col_names))

    categorical_only_pairs = np.array(itertools.product(range(num_rows), list(col_types.mixed_categorical_cols)))
    numeric_only_pairs = np.array(itertools.product(range(num_rows), list(col_types.mixed_numeric_cols)))

    pairs_with_no_errors = all_possible_pairs.copy()
    # Randomly pick out a set of idxs and columns for each type of error

    # Anomaly and Incomplete must go first since they're for specific column types
    positions_with_anomaly = randomly_select_idx_and_col_pairs(numeric_only_pairs, num_rows, 0.1)
    apply_errors_to_dataframe(positions_with_anomaly, dataset, "anomaly", col_types)
    pairs_with_no_errors = pairs_with_no_errors - positions_with_anomaly

    positions_with_incomplete = randomly_select_idx_and_col_pairs(categorical_only_pairs, num_rows,    0.1)
    apply_errors_to_dataframe(positions_with_incomplete, dataset, "incomplete", col_types)
    pairs_with_no_errors = pairs_with_no_errors - positions_with_incomplete

    positions_with_mismatch = randomly_select_idx_and_col_pairs(pairs_with_no_errors,num_rows, 0.1)
    apply_errors_to_dataframe(positions_with_mismatch, dataset, "mismatch", col_types)
    pairs_with_no_errors = pairs_with_no_errors - positions_with_mismatch
    positions_with_missing = randomly_select_idx_and_col_pairs(pairs_with_no_errors, num_rows, 0.1)
    apply_errors_to_dataframe(positions_with_missing, dataset, "missing", col_types)
    pairs_with_no_errors = pairs_with_no_errors - positions_with_missing


    original_file_name = csv_path.split("/")[-1]
    # write "dirtied" dataset to csv
    with open(f'artificially_dirty_datasets/{original_file_name}_dirty', 'w') as out_file:
        fieldnames = dataset.columns
        writer = csv.DictWriter(out_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dataset)

    print(f"Done dirtying {csv_path}")












