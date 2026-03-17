#Buckaroo Project - started: June 1, 2025
#This file helps deliver on endpoint services

import random
import string
import re
from sqlalchemy import types as sql_types
from sqlalchemy import text as sa_text
import pandas as pd
from app.set_id_column import set_id_column
from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from postgres_wrangling import query


def generate_table_name(csv_name):
    """
    Cleans the file name so that it is ready to be used to make a table in the database, it needs to:
    - Remove file extension (.csv), replace spaces/special chars with underscores, ensure it starts with a letter (SQL requirement)
    :param csv_name: csv name from user upload
    :return: cleaned name without
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name)
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=10)
)
    return "data_" + clean_name.lower() + "_" + random_string


def init_session_data_state(df,error_df,data_state_manager):
    """
    Initializes the session data state with the undetected and detected dataframes
    so that as the user performs actions on the data, we can keep track of the different states
    :param df: the undetected dataframe
    :param error_df: the detected dataframe
    :param data_state_manager: the data state manager object the current app session is using
    :return: None
    """

    table_dict = {"df":df,"error_df":error_df}

    data_state_manager.set_original_df(df)
    data_state_manager.set_original_error_table(error_df)
    data_state_manager.set_current_state(table_dict)

def update_data_state(wrangled_df, new_error_df):
    """
    Updates the current data state with the new wrangled dataframe and error dataframe, the idea is that 
    the user has performed an action on the data, and we need to update the session state with the new data
    :param wrangled_df: the wrangled dataframe after the user has performed an action
    :param new_error_df: the new error dataframe after the user has performed an action
    :return: None
    """

    new_state = {"df":wrangled_df,"error_df":new_error_df}
    data_state_manager.set_current_state(new_state)

def fetch_detected_and_undetected_current_dataset_from_db(cleaned_table_name,engine):
    """
    Fetches the undetected and detected dataframes from the database by first constructing the queries using the helper which takes in 
    the name of the table to fetch from the db, and initializes the session data state
    :param cleaned_table_name: the name of the table in the database
    :param engine: the database connection
    :return: None
    """

    try:
        full_df_query = get_whole_table_query(cleaned_table_name,False)
        error_df_query = get_whole_table_query(cleaned_table_name,True)
        undetected_df = pd.read_sql_query(full_df_query, engine)
        detected_df = pd.read_sql_query(error_df_query, engine)
        # set the first datastate for later wrangling purposes
        print("starting initial data-state:")
        init_session_data_state(undetected_df, detected_df, data_state_manager)

    except Exception as e:
        return {"success": False, "error": str(e)}

def get_whole_table_query(table_name, get_errors):
    """
    Constructs the sql query to get the whole table from the database, either the undetected or detected
    :param table_name: the name of the table to fetch from the database
    :param get_errors: boolean to determine if the query is for the error table or the undetected table
    :return: the query string to fetch the whole table
    """
    if get_errors:
        query = f"SELECT * FROM errors_{table_name}"
        return query
    query = f"SELECT * FROM {table_name}"
    return query

def get_range_of_ids_query(min_id,max_id,table_name, get_errors):
    """
    Constructs the sql query to get a range of IDs from the table in the database, either the undetected or detected
    :param min_id: the minimum ID to bound the window of IDs to fetch
    :param max_id: the maximum ID to bound the window of IDs to fetch
    :param table_name: the name of the table to fetch from the database
    :param get_errors: boolean to determine if the query is for the error table or the undetected table
    :return: the query string to fetch the range of IDs
    """
    if get_errors:
        query = f"SELECT * FROM errors_{table_name} WHERE " + "'ID'" + f" BETWEEN {min_id} AND {max_id}"
        return query
    query = f"SELECT * FROM {table_name} WHERE " + "'ID'" + f" BETWEEN {min_id} AND {max_id}"
    return query

def get_values_for_df_melt(df):
    """
    Gets the column names of the columns which have errors in them, the excluded 
    columns are the one's which make up the structure for the error dataframe, these should be
    ignored
    :param df: the dataframe to get the values from
    :return: a list of column names to be used in the melt operation
    """
    values = []
    columns = df.columns
    for column in columns:
        if column not in ('ID', "Unnamed: 0", "column_id","error_type","row_id"):
            values.append(column)
    return values

def perform_melt(dfs):
    """
    Performs a melt operation, basically combines them, on the list of error detected dataframes provided, this is used to combine the
    error dataframes from the detectors into a single dataframe for easier processing
    :param dfs: a list of dataframes to be melted
    :return: a single melted dataframe 
    """
    df_combined = pd.DataFrame()
    for df in dfs:
        melted_df = pd.melt(df, id_vars='ID', value_vars=get_values_for_df_melt(df))
        melted_df.rename(columns={'ID': 'row_id','variable':'column_id','value':'error_type'}, inplace=True)
        df_combined = pd.concat([df_combined,melted_df])
    nan_mask = df_combined['error_type'].isna()
    df_combined = df_combined[~nan_mask]
    df_combined.reset_index(drop=True, inplace=True)

    return df_combined

def run_detectors(data_frame):
    """
    Runs all 4 detectors that are implemented
    on the server, on the data, and returns a compiled dataframe of the complete errors
    :param data_frame:the dataframe to run the detectors on
    :return: a single compiled dataframe of all the errors detected
    """
    df_with_id = set_id_column(data_frame)
    anomaly_df = pd.DataFrame(anomaly(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    incomplete_df = pd.DataFrame(incomplete(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    missing_value_df = pd.DataFrame(missing_value(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    datatype_mismatch_df = pd.DataFrame(datatype_mismatch(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    frames = [anomaly_df, incomplete_df, missing_value_df,datatype_mismatch_df]
    return perform_melt(frames)

def calculate_attribute_rankings(error_df):
    """
    Calculate attribute rankings by total error count
    :param error_df: Melted error DataFrame with columns {row_id, column_id, error_type}
    :return: DataFrame with columns [attribute, total_errors, rank] sorted by total_errors descending
    """
    if error_df.empty:
        return pd.DataFrame(columns=['attribute', 'total_errors', 'rank'])

    ranking = error_df.groupby('column_id').size().reset_index(name='total_errors')
    ranking = ranking.sort_values('total_errors', ascending=False)
    ranking['rank'] = range(1, len(ranking) + 1)
    ranking = ranking.rename(columns={'column_id': 'attribute'})

    return ranking[['attribute', 'total_errors', 'rank']]

def get_error_dist(error_df,normal_df):
    """
    Gets the distribution of errors in the error dataframe, this is used to create a pivot table, and also in the attribute summaries
    :param error_df: the error dataframe to get the distribution from
    :param normal_df: the normal dataframe to get the total number of IDs from
    :return: a pivot table of the error distribution
    """
    res = error_df.pivot_table("row_id", index="error_type", columns='column_id', aggfunc="count")
    res_mask = res.fillna(0)
    total_ids = normal_df['ID'].count()
    res_mask.iloc[:, 0:] = res_mask.iloc[:, 0:].div(total_ids)

    # Flatten the multi-level columns
    res_mask = res_mask.reset_index()
    return res_mask

def create_error_dict(df, error_size):
    """
    Creates a dictionary of errors from the error dataframe
    :param df: the error dataframe to create the dictionary from
    :param error_size: the size of the error to limit the dictionary to
    :return: a dictionary of errors in the format {column_name: {row_id: [error_type, ...]}} for
    the view to use
    """
    try:
        error_size_df = df[df['row_id'].between(1, error_size)]
        result_dict = {}
        for _, row in error_size_df.iterrows():
            col = row['column_id']
            row_id = row['row_id']
            error_type = row['error_type']
            if pd.notna(error_type):
                if col not in result_dict:
                    result_dict[col] = {}
                if row_id not in result_dict[col]:
                    result_dict[col][row_id] = []
                result_dict[col][row_id].append(error_type)
        return result_dict
    except Exception as e:
        return {"success": False, "error in the error_dictionary service helper": str(e)}

def group_by_attribute(df, column_a, group_by):
    """
    Groups the dataframe by the specified column and aggregates the count of IDs in each group for the group_by endpoint
    :param df: the dataframe to group
    :param column_a: the column to group by
    :param group_by: the column to aggregate by
    :return: a pivot table with the count of IDs in each group
    """
    ret = df.pivot_table("ID", index=column_a, columns=group_by, aggfunc="count")
    return ret

def get_2d_bins(column_a,column_b, range,bin_count):
    column_a_categorical = is_categorical(column_a)
    column_b_categorical = is_categorical(column_b)
    column_a_bins = column_a
    column_b_bins = column_b
    if not column_a_categorical:
        column_a_bins = create_bins_for_a_numeric_column(column_a,bin_count)
    if not column_b_categorical:
        column_b_bins = create_bins_for_a_numeric_column(column_b,bin_count )
    print("before crosstab")
    return pd.crosstab(column_a_bins, column_b_bins,dropna=True)

    #make the number of bins for numeric be an option

def slice_data_by_min_max_ranges(min_val,max_val,df,error_df):
    """
    Slices the dataframe and error dataframe by the min and max values provided, this is used
    to get a range of IDs from the dataframe and error dataframe, used in various endpoints
    :param min_val: the minimum value to slice the dataframe by
    :param max_val: the maximum value to slice the dataframe by
    :param df: the dataframe to slice
    :param error_df: the error dataframe to slice
    :return: the sliced dataframe and error dataframe
    """
    min_val_int = int(min_val)
    max_val_int = int(max_val)

    if "ID" not in df.columns:
        df = set_id_column(df)

    sliced_max_df = df[df["ID" or "index"] <= max_val_int]
    sliced_min_max_df = sliced_max_df[sliced_max_df["ID" or "index"] >= min_val_int]

    sliced_error_max_df = error_df[error_df["row_id"] <= max_val_int]
    sliced_min_max_error_df = sliced_error_max_df[sliced_error_max_df["row_id"] >= min_val_int]

    return sliced_min_max_df, sliced_min_max_error_df

def is_categorical(column_a):
    """
    Checks if the column is categorical, used in endpoints which need to determine if the column is categorical or not
    such as the attribute summaries endpoint
    :param column_a: the column to check
    :return: True if the column is categorical, False otherwise
    """
    value_counts = column_a.value_counts()
    type_count = {}
    type_key = {}
    largest_type = 0
    value_type = None
    # populate the count of each type in the column
    for key, value in value_counts.items():
        type_of_key = type(key).__name__
        if (isinstance(key, str)) and (bool(re.fullmatch(r'^\d+(\.\d+)?$', key.strip()))): type_of_key = "numeric"
        if type_of_key in type_count:
            type_count[type_of_key] += value
            if type_of_key in type_key:
                type_key[type_of_key].append(key)
        else:
            type_count[type_of_key] = value
            type_key[type_of_key] = [key]
    types = type_count.items()
    for key, value in types:
        if value > largest_type:
            largest_type = value
            value_type = key
    if value_type == "str":
        return True
    if value_type is None:
        return True
    else:
        return False

def get_sqlalchemy_dtype_map(df):
    """
    Builds a dtype map for .to_sql() by inspecting the actual values in each column
    to find the majority type, so messy/mixed columns get cast correctly in PostgreSQL.
    :param df: the dataframe to inspect
    :return: dict mapping column name to SQLAlchemy type
    """
    dtype_map = {}
    for col in df.columns:
        if is_categorical(df[col]):
            dtype_map[col] = sql_types.Text()
        else:
            non_null = df[col].dropna()
            numeric_series = pd.to_numeric(non_null, errors='coerce')
            # If any non-null values failed numeric coercion, the column has true mixed
            # values (e.g. "N/A" strings alongside numbers). Store as Text to preserve
            # all values; gather_mixed_cols() will classify it as categorical_mixed.
            if numeric_series.isna().any() or numeric_series.empty:
                dtype_map[col] = sql_types.Text()
            else:
                try:
                    if (numeric_series == numeric_series.astype(int)).all():
                        dtype_map[col] = sql_types.BigInteger()
                    else:
                        dtype_map[col] = sql_types.Float()
                except (OverflowError, ValueError):
                    dtype_map[col] = sql_types.Float()
    return dtype_map

def create_bins_for_a_numeric_column(column,bin_count):
    """
    Creates bins for a numeric column, used in endpoints which need to create bins for numeric columns
    such as attribute summaries and 2D histogram endpoints
    :param column: the column to create bins for
    :param bin_count: the number of bins to create
    :return: bins for the column as a pandas object
    """
    column_numeric = pd.to_numeric(column, errors='coerce')
    return pd.cut(column_numeric, bins=bin_count)

    # return pd.cut(column, bins=bin_count)


def execute_wrangle_preview(table, preview_table, preview_name_fn):
    """
    Promote a preview table to become the main table:
    1. Drop all other preview tables (and their errors_ siblings)
    2. Rename the main table to <table>_old
    3. Rename the selected preview table to <table>
    4. Drop <table>_old
    5. Reload db_operations for the promoted table
    Returns a dict with success and table name.
    """
    from app import engine, db_operations

    all_possible_previews = [
        preview_name_fn(table, "_preview_delete"),
        preview_name_fn(table, "_preview_impute"),
        preview_name_fn(table, "_preview_impute_x"),
        preview_name_fn(table, "_preview_impute_y"),
    ]

    with engine.begin() as conn:
        for pt in all_possible_previews:
            if pt != preview_table:
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{pt}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "errors_{pt}"'))

        old_table = f"{table}_old"
        conn.execute(sa_text(f'ALTER TABLE "{table}" RENAME TO "{old_table}"'))
        conn.execute(sa_text(f'ALTER TABLE IF EXISTS "errors_{table}" RENAME TO "errors_{old_table}"'))

        conn.execute(sa_text(f'ALTER TABLE "{preview_table}" RENAME TO "{table}"'))
        conn.execute(sa_text(f'ALTER TABLE IF EXISTS "errors_{preview_table}" RENAME TO "errors_{table}"'))

        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{old_table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "errors_{old_table}"'))

    db_operations.load_table(table, f"errors_{table}")

    return {"success": True, "table": table}


def create_previews_1d(table, row_ids, cols, preview_name_fn, update_errors_fn):
    """
    Create delete and impute preview tables for a 1D (single-column) selection.
    Returns a dict with preview table names and dims=1.
    """
    from app import engine

    errors_src     = f"errors_{table}"
    preview_delete = preview_name_fn(table, "_preview_delete")
    errors_dst_del = f"errors_{preview_delete}"
    preview_impute = preview_name_fn(table, "_preview_impute")
    errors_dst_imp = f"errors_{preview_impute}"

    with engine.begin() as conn:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_delete}"'))
        conn.execute(sa_text(f'CREATE TABLE "{preview_delete}" AS SELECT * FROM "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_del}"'))
        conn.execute(sa_text(f'CREATE TABLE "{errors_dst_del}" AS SELECT * FROM "{errors_src}"'))

        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute}"'))
        conn.execute(sa_text(f'CREATE TABLE "{preview_impute}" AS SELECT * FROM "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp}"'))
        conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp}" AS SELECT * FROM "{errors_src}"'))

    query.remove_rows_by_ids(table=preview_delete, ids=row_ids)
    query.impute_by_ids(table=preview_impute, col=cols[0], ids=row_ids)

    update_errors_fn(preview_delete)
    update_errors_fn(preview_impute)

    return {
        "success": True,
        "preview_delete": preview_delete,
        "preview_impute": preview_impute,
        "dims": 1,
    }


def create_previews_2d(table, row_ids, cols, preview_name_fn, update_errors_fn):
    """
    Create delete, impute_x, and impute_y preview tables for a 2D (two-column) selection.
    Returns a dict with preview table names and dims=2.
    """
    from app import engine

    errors_src       = f"errors_{table}"
    preview_delete   = preview_name_fn(table, "_preview_delete")
    errors_dst_del   = f"errors_{preview_delete}"
    preview_impute_x = preview_name_fn(table, "_preview_impute_x")
    errors_dst_imp_x = f"errors_{preview_impute_x}"
    preview_impute_y = preview_name_fn(table, "_preview_impute_y")
    errors_dst_imp_y = f"errors_{preview_impute_y}"

    with engine.begin() as conn:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_delete}"'))
        conn.execute(sa_text(f'CREATE TABLE "{preview_delete}" AS SELECT * FROM "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_del}"'))
        conn.execute(sa_text(f'CREATE TABLE "{errors_dst_del}" AS SELECT * FROM "{errors_src}"'))

        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute_x}"'))
        conn.execute(sa_text(f'CREATE TABLE "{preview_impute_x}" AS SELECT * FROM "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp_x}"'))
        conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp_x}" AS SELECT * FROM "{errors_src}"'))

        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute_y}"'))
        conn.execute(sa_text(f'CREATE TABLE "{preview_impute_y}" AS SELECT * FROM "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp_y}"'))
        conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp_y}" AS SELECT * FROM "{errors_src}"'))

    query.remove_rows_by_ids(table=preview_delete, ids=row_ids)
    query.impute_by_ids(table=preview_impute_x, col=cols[0], ids=row_ids)
    query.impute_by_ids(table=preview_impute_y, col=cols[1], ids=row_ids)

    update_errors_fn(preview_delete)
    update_errors_fn(preview_impute_x)
    update_errors_fn(preview_impute_y)

    return {
        "success": True,
        "preview_delete": preview_delete,
        "preview_impute_x": preview_impute_x,
        "preview_impute_y": preview_impute_y,
        "dims": 2,
    }