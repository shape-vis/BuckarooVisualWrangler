
import sys
import pandas as pd
import itertools
import random as rand
import os
import json
import uuid
import csv
from app.db_utils.column_types import ColumnTypes
from app.routes.routes import load_file
from app import db_operations, engine
from math import ceil

assert len(sys.argv) == 2, f"Usage: python create_dirty_datasets <path_to_csv>. len(sys.argv) = {len(sys.argv)}"

# Read in dataset name as a command line arg
rand.seed(42)
csv_path = sys.argv[1]

def randomly_select_idx_and_col_pairs(pairs_with_no_errors, num_rows, percentage_to_select):
    num_pairs_to_select = int(num_rows * percentage_to_select)
    assert num_pairs_to_select > 0, "Number of pairs to select must be greater than 0"
    if num_pairs_to_select > len(pairs_with_no_errors):
        num_pairs_to_select = min(num_pairs_to_select, len(pairs_with_no_errors))
    selected_idx_col_pairs = rand.sample(list(pairs_with_no_errors), num_pairs_to_select)

    #selected_idx_col_pairs = None
    return selected_idx_col_pairs

def apply_errors_to_dataframe(row_col_tuples,  dataframe, error_type, col_types):
    print("error type", error_type)
    print("ROW COL TUPLES:", row_col_tuples)
    rows, cols = map(list, zip(*row_col_tuples))

    if error_type == "missing":
        # any col type
        for (row, col) in zip(rows, cols):
            dataframe.loc[row, col] = None
    elif error_type == "mismatch":
        # any col type
        for (row, col) in zip(rows, cols):

            # Switching type to object so it will allow multiple types in same col
            dataframe[col] = dataframe[col].astype(object)

            if col_types.is_numeric_col(col):
                dataframe.loc[row, col] = "artificial_mismatch_error"
            elif col_types.is_categorical_col(col):
                dataframe.loc[row, col] = 10000
    elif error_type == "incomplete":
        # only categorical
        for (row, col) in zip(rows, cols):
            if not col_types.is_categorical_col(col):
                continue

            # Just adding a random unique ID
            dataframe.loc[row, col] = str(uuid.uuid4())
    elif error_type == "anomaly":
        # only numeric


        for (row, col) in zip(rows, cols):
            mean = dataframe[col].mean()
            std = dataframe[col].std()
            anomalous_value = mean + 5 * std

            dataframe.loc[row, col] = ceil(anomalous_value)

    else:
        raise ValueError("Invalid error type")

    return dataframe

if __name__ == '__main__':
    original_file_name = csv_path.split("/")[-1]
    # Read in the dataset
    dataset = pd.read_csv(csv_path, index_col=False, low_memory=False)

    # Have to load the file into a table so that we can use ColumnTypes
    load_file(csv_path, original_file_name)

    col_names = dataset.columns.tolist()
    col_types = ColumnTypes(db_operations.main_table_name, engine)

    num_cols = len(col_names)
    num_rows = len(dataset)

    # All possible idx and column tuple pairs
    # TODO: something is going wrong here where ID and index are ending up in the final dirty dataset
    valid_categorical_cols = list(col_types.categorical_cols.copy())
    valid_numeric_cols = list(col_types.numeric_cols.copy())
    if "ID" in valid_numeric_cols:
        valid_numeric_cols.remove("ID")

    if "index" in valid_numeric_cols:
        valid_numeric_cols.remove("index")

    all_possible_pairs = list(itertools.product(range(num_rows), col_names))

    categorical_only_pairs = list(itertools.product(range(num_rows), valid_categorical_cols))
    numeric_only_pairs = list(itertools.product(range(num_rows), valid_numeric_cols))

    pairs_with_no_errors = all_possible_pairs.copy()
    # Randomly pick out a set of idxs and columns for each type of error

    # Anomaly and Incomplete must go first since they're for specific column types
    if not numeric_only_pairs == []:
        positions_with_anomaly = randomly_select_idx_and_col_pairs(numeric_only_pairs, num_rows, 0.1)
        apply_errors_to_dataframe(positions_with_anomaly, dataset, "anomaly", col_types)
        pairs_with_no_errors = set(pairs_with_no_errors) - set(positions_with_anomaly)

        print("NO NUMERIC COLS FOUND. SKIPPING ANOMALY ERRORS")

    if not categorical_only_pairs == []:
        positions_with_incomplete = randomly_select_idx_and_col_pairs(categorical_only_pairs, num_rows,    0.1)
        apply_errors_to_dataframe(positions_with_incomplete, dataset, "incomplete", col_types)
        pairs_with_no_errors = set(pairs_with_no_errors) - set(positions_with_incomplete)
    else:
        print("NO CATEGORICAL COLS FOUND. SKIPPING INCOMPLETE ERRORS")

    positions_with_mismatch = randomly_select_idx_and_col_pairs(pairs_with_no_errors,num_rows, 0.1)
    apply_errors_to_dataframe(positions_with_mismatch, dataset, "mismatch", col_types)
    pairs_with_no_errors = set(pairs_with_no_errors) - set(positions_with_mismatch)
    positions_with_missing = randomly_select_idx_and_col_pairs(pairs_with_no_errors, num_rows, 0.1)
    apply_errors_to_dataframe(positions_with_missing, dataset, "missing", col_types)
    pairs_with_no_errors = set(pairs_with_no_errors) - set(positions_with_missing)

    finished_dataset_location = os.getcwd() + os.sep + 'app' + os.sep + 'ablation_study' + os.sep + 'artificially_dirty_datasets' + os.sep
    # write "dirtied" dataset to csv
    dirty_csv_name = f'dirty_{original_file_name}'

    dataset.to_csv(finished_dataset_location + dirty_csv_name)
    print("------------ Summary ------------")
    if positions_with_incomplete is not None:
        print("Num incomplete:", len(positions_with_incomplete))
    if positions_with_anomaly is not None:
        print("Num anomaly:", len(positions_with_anomaly))
    print("Num missing:", len(positions_with_missing))
    print("Num mismatch:", len(positions_with_mismatch))

    errors = {
        "incomplete": positions_with_incomplete,
        "mismatch": positions_with_mismatch,
        "anomaly": positions_with_anomaly,
        "missing": positions_with_missing
    }

    errors_json_path = finished_dataset_location + original_file_name +'_errors' ".json"

    print("ERRORS JSON PATH", errors_json_path)
    with open(errors_json_path, 'w') as outfile:
        json.dump(errors, outfile)

    print("Saved errors json to " + errors_json_path)

    print(f"Done dirtying {csv_path}")












