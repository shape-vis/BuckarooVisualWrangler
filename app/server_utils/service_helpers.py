#Buckaroo Project - started: June 1, 2025
#This file helps deliver on endpoint services

import hashlib
import json
import random
import string
import re
from sqlalchemy import types as sql_types
from sqlalchemy import text as sa_text
import pandas as pd

import app
from app.db_utils import query
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.server_utils.set_id_column import set_id_column
from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from app.db_utils.data_profile import DataProfile

def get_current_pgraph():
    """
    uses the custom json function in graph to send a json version of the graph back to the view
    :return:
    """
    return json.dumps(app.pgraph_for_session, default=lambda o: o.__json__() if hasattr(o, '__json__') else None)

def clicked_node_access_helper(node_table_name):
    return app.pgraph_for_session.set_clicked_node_as_current(node_table_name)

def _validate_identifier(name: str) -> str:
    """
    Ensures a table or column name contains only safe characters before it
    is interpolated into a SQL string.  Raises ValueError if the name does
    not match the expected pattern so callers get an explicit, early error
    rather than a silent SQL injection.
    """
    if not re.fullmatch(r'[a-zA-Z0-9_]+', name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    return name

def get_pgraph_redo():
    return app.pgraph_for_session.redo_pgraph()

def get_pgraph_undo():
    return app.pgraph_for_session.undo_pgraph()

def _safe_pg_name(base: str, suffix: str) -> str:
    """
    Build a table name guaranteed to keep both itself and all derived
    sibling tables within PostgreSQL's 63-char identifier limit.

    Derived siblings and their affixes:
      errors_<name>     prefix  7 chars  -> name <= 56
      rankings_<name>   prefix  9 chars  -> name <= 54
      <name>_filtering  suffix 10 chars  -> name <= 53  (most restrictive)

    If base+suffix already fits, use it as-is. Otherwise truncate the base
    and append an 8-char MD5 hash so the name stays unique.
    """
    MAX_LEN = 53  # 63 - len("_filtering")
    candidate = f"{base}{suffix}"
    if len(candidate) <= MAX_LEN:
        return candidate
    h = hashlib.md5(base.encode()).hexdigest()[:8]
    max_base = MAX_LEN - len(suffix) - 9  # 9 = 1 underscore + 8 hash chars
    return f"{base[:max_base]}_{h}{suffix}"


def generate_table_name(csv_name):
    """
    Cleans the file name so that it is ready to be used to make a table in the database, it needs to:
    - Remove file extension (.csv), replace spaces/special chars with underscores, ensure it starts with a letter (SQL requirement)
    :param csv_name: csv name from user upload
    :return: cleaned name without
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name).lower()
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=5))
    return _safe_pg_name(clean_name, "_" + random_string)


def fetch_detected_and_undetected_current_dataset_from_db(cleaned_table_name, engine):
    """
    Fetches the undetected and detected dataframes from the database.
    :param cleaned_table_name: the name of the table in the database
    :param engine: the database connection
    :return: None
    """
    try:
        full_df_query = get_whole_table_query(cleaned_table_name, False)
        error_df_query = get_whole_table_query(cleaned_table_name, True)
        pd.read_sql_query(full_df_query, engine)
        pd.read_sql_query(error_df_query, engine)
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_whole_table_query(table_name, get_errors):
    """
    Constructs the sql query to get the whole table from the database, either the undetected or detected
    :param table_name: the name of the table to fetch from the database
    :param get_errors: boolean to determine if the query is for the error table or the undetected table
    :return: the query string to fetch the whole table
    """
    _validate_identifier(table_name)
    if get_errors:
        return f'SELECT * FROM "errors_{table_name}"'
    return f'SELECT * FROM "{table_name}"'

def get_range_of_ids_query(min_id,max_id,table_name, get_errors):
    """
    Constructs the sql query to get a range of IDs from the table in the database, either the undetected or detected
    :param min_id: the minimum ID to bound the window of IDs to fetch
    :param max_id: the maximum ID to bound the window of IDs to fetch
    :param table_name: the name of the table to fetch from the database
    :param get_errors: boolean to determine if the query is for the error table or the undetected table
    :return: the query string to fetch the range of IDs
    """
    _validate_identifier(table_name)
    min_id_int = int(min_id)
    max_id_int = int(max_id)
    if get_errors:
        return f'SELECT * FROM "errors_{table_name}" WHERE "ID" BETWEEN {min_id_int} AND {max_id_int}'
    return f'SELECT * FROM "{table_name}" WHERE "ID" BETWEEN {min_id_int} AND {max_id_int}'

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

# Previously called run_detectors
def create_error_df(data_frame):
    """
    Runs all 4 detectors that are implemented
    on the server, on the data, and returns a compiled dataframe of the complete errors
    :param data_frame:the dataframe to run the detectors on
    :return: a single compiled dataframe of all the errors detected
    """
    df_with_id = set_id_column(data_frame)

    # TODO: optimize these functions
    anomaly_df = pd.DataFrame(anomaly(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    incomplete_df = pd.DataFrame(incomplete(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    missing_value_df = pd.DataFrame(missing_value(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    datatype_mismatch_df = pd.DataFrame(datatype_mismatch(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    frames = [anomaly_df, incomplete_df, missing_value_df,datatype_mismatch_df]

    df = perform_melt(frames)
    print("CREATE ERROR TABLE TYPE MAP", df.dtypes)
    return df

def create_data_profile_df(data_profile, col_names=None):
    """
    :param data_profile: the data profile object
    :param col_names: the column names of interest in the table
    :return: a dataframe of the data profile for the table
    """
    print("CREATED DATA_PROFILE DF FOR TABLE", data_profile.table_name)

    # Dict of attributes that will be in the data profile and the type that they should be
    default_attributes = ['mean', 'median', 'min', 'max', 'n_categories',
                  'mode', 'error_counts',
                  'category_counts']


    col_list = []

    # If col_names is not provided (no specific columns to create a dp for), use all column names from the data profile
    if col_names is None:
        col_names = data_profile.get_col_names()

    for col in col_names:

        row_dict = {'column_name': col}
        for attribute in default_attributes:

            # Make sure that attribute and the column type match

            numeric = ((data_profile.col_types.is_numeric_mixed_col(col) or data_profile.col_types.is_numeric_col  )and attribute in data_profile.attribute_type_assignment['numeric'])
            categorical = ((data_profile.is_categorical_mixed_col(col) or data_profile.col_types.is_categorical_col)and attribute in data_profile.attribute_type_assignment['categorical'])

            if not (numeric or categorical):

                row_dict[attribute] = None

                continue

            print("CALCULATING ATTRIBUTE: ", attribute)
            print("COLUMN: ", col)

            row_dict[attribute] = data_profile.calculate_column_attribute(attribute, col, False)
        col_list.append(row_dict)

    df = pd.DataFrame(col_list)

    return df


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
    res_mask = res_mask.div(total_ids)

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

    id_col = "ID" if "ID" in df.columns else "index"
    sliced_max_df = df[df[id_col] <= max_val_int]
    sliced_min_max_df = sliced_max_df[sliced_max_df[id_col] >= min_val_int]

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


def execute_wrangle_preview(table, preview_table, safe_pg_name_fn, db_operations):
    """
    Promote a preview table to the new current table and make it as a new node in the pgraph
    1. Drop all other preview tables (and their errors_ siblings)
    2. Rename preview to the new node table
    3. Reload db_operations with the new node
    Returns a dict with success and table name.
    """
    # from app import engine, db_operations

    all_possible_previews = [
        safe_pg_name_fn(table, "_preview_delete"),
        safe_pg_name_fn(table, "_preview_impute"),
        safe_pg_name_fn(table, "_preview_impute_x"),
        safe_pg_name_fn(table, "_preview_impute_y"),
    ]

    app.db_operations.drop_preview_tables(all_possible_previews, preview_table)

    wrangle_executed = extract_preview_action(preview_table)
    preview_table_trimmed = trim_preview_suffix(preview_table)

    #enter into pgraph before current or new tables are modified, return the new tables name with nodeID added
    # new_table_name = pgraph_entry_point(table, preview_table_trimmed, wrangle_executed)
    new_table_name = n_wrangle(table, preview_table_trimmed, wrangle_executed)
    app.db_operations.rename_preview_to_new(preview_table, new_table_name)
    db_operations.load_table(new_table_name, f"errors_{new_table_name}", f"dp_{new_table_name}")

    app.db_operations.update_rankings(new_table_name)


    return {"success": True, "table": new_table_name}

def _clone_table_pair(conn, source_table, dest_table, errors_source, dp_source):
    """Drop-and-recreate dest_table and its errors_ and dp_ sibling as copies of source tables."""
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{dest_table}"'))
    conn.execute(sa_text(f'CREATE TABLE "{dest_table}" AS SELECT * FROM "{source_table}"'))
    errors_dest = f"errors_{dest_table}"
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dest}"'))
    conn.execute(sa_text(f'CREATE TABLE "{errors_dest}" AS SELECT * FROM "{errors_source}"'))

    dp_dest = f"dp_{dest_table}"
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{dp_dest}"'))
    conn.execute(sa_text(f'CREATE TABLE "{dp_dest}" AS SELECT * FROM "{dp_source}"'))

def trim_preview_suffix(name: str) -> str:
    """Remove the '_preview...' tail from a table name, if present."""
    idx = name.find("_preview")
    if idx != -1:
        return name[:idx]
    return name

def init_pgraph_for_session(root_table):
    app.pgraph_for_session = PGraph()

    # create the root node, add it to the pgraph as the root
    root_node = GraphNode("root", "root", root_table, f"errors_{root_table}")
    app.pgraph_for_session.add_root_node(root_node)

def n_wrangle(parent_table, child_table, wrangle_executed):
    new_table_name = make_new_table_name(child_table)
    current_node = GraphNode(parent_table,wrangle_executed, new_table_name,f"errors_{new_table_name}" )
    app.pgraph_for_session.add_node(current_node)
    return new_table_name

def make_new_table_name(child_table):
    node_id = app.pgraph_for_session.get_new_node_id()
    new_table_name = f"{node_id}{child_table[2:]}"
    return new_table_name

def create_minimal_preview_table(conn, source_table, preview_table_name, errors_source, cols):
    """
    Drop and recreate a minimal dest table and empty error table to populate only with regard to the cols.
    This is because we don't know which wrangle the user will select, so only generate enough information
    to populate the preview.

    :arg: conn               - connection to the Postgres database.
    :arg: source_table       - name of the current main table.
    :arg: preview_table_name - temporary preview table to create.
    :arg: errors_source      - the current main table error table.
    :arg: cols               - the column(s) of interest for the preview.
    """

    col_sel_query = ", ".join(cols)

    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_table_name}"'))
    conn.execute(sa_text(f'CREATE TABLE "{preview_table_name}" AS SELECT {col_sel_query} FROM "{source_table}"'))
    errors_dest = f"errors_{preview_table_name}"
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dest}"'))

    # Copy schema but leave empty.
    conn.execute(sa_text(f'CREATE TABLE "{errors_dest}" (LIKE "{errors_source}" INCLUDING ALL)"'))

def create_previews_1d(table, row_ids, cols, safe_pg_name_fn, update_errors_fn, update_data_profile_table_fn):
    """
    Create delete and impute preview tables for a 1D (single-column) selection.
    Returns a dict with preview table names and dims=1.
    """
    from app import engine

    errors_src = f"errors_{table}"
    dp_src = f"dp_{table}"
    # Creates name for the preview tables
    preview_delete_table_name = safe_pg_name_fn(table, "_preview_delete")
    preview_impute_table_name = safe_pg_name_fn(table, "_preview_impute")

    # Preview tables are created (error_..._preview, dp_..._preview)
    with engine.begin() as conn:
        _clone_table_pair(conn, table, preview_delete_table_name, errors_src, dp_src)
        _clone_table_pair(conn, table, preview_impute_table_name, errors_src, dp_src)

        #create_minimal_preview_table(conn, table, preview_delete, errors_src, cols)
        #create_minimal_preview_table(conn, table, preview_impute, errors_src, cols)


    # Modify the preview table based on the preview type
    query.remove_rows_by_ids(table=preview_delete_table_name, ids=row_ids)
    query.impute_by_ids(table=preview_impute_table_name, col=cols[0], ids=row_ids)

    update_errors_fn(preview_delete_table_name, cols)
    update_errors_fn(preview_impute_table_name, cols)
    update_data_profile_table_fn(preview_delete_table_name, cols)
    update_data_profile_table_fn(preview_impute_table_name, cols)

    return {
        "success": True,
        "preview_delete": preview_delete_table_name,
        "preview_impute": preview_impute_table_name,
        "dims": 1,
    }

def extract_preview_action(name: str) -> str:
    """Extract the action after '_preview_' (e.g. 'impute_y'), or '' if not found."""
    marker = "_preview_"
    idx = name.find(marker)
    if idx != -1:
        return name[idx + len(marker):]
    return ""

def create_previews_2d(table, row_ids, cols, safe_pg_name_fn, update_errors_fn, update_data_profile_table_fn):
    """
    Create delete, impute_x, and impute_y preview tables for a 2D (two-column) selection.
    Returns a dict with preview table names and dims=2.
    """
    from app import engine

    errors_src  = f"errors_{table}"
    dp_src = f"dp_{table}"
    preview_delete_table_name   = safe_pg_name_fn(table, "_preview_delete")
    preview_impute_x_table_name = safe_pg_name_fn(table, "_preview_impute_x")
    preview_impute_y_table_name = safe_pg_name_fn(table, "_preview_impute_y")

    with engine.begin() as conn:
        _clone_table_pair(conn, table, preview_delete_table_name, errors_src, dp_src)
        _clone_table_pair(conn, table, preview_impute_x_table_name, errors_src, dp_src)
        _clone_table_pair(conn, table, preview_impute_y_table_name, errors_src, dp_src)

    query.remove_rows_by_ids(table=preview_delete_table_name, ids=row_ids)
    query.impute_by_ids(table=preview_impute_x_table_name, col=cols[0], ids=row_ids)
    query.impute_by_ids(table=preview_impute_y_table_name, col=cols[1], ids=row_ids)

    update_errors_fn(preview_delete_table_name, cols)
    update_errors_fn(preview_impute_x_table_name, cols)
    update_errors_fn(preview_impute_y_table_name, cols)

    update_data_profile_table_fn(preview_delete_table_name, cols)
    update_data_profile_table_fn(preview_impute_x_table_name, cols)
    update_data_profile_table_fn(preview_impute_y_table_name, cols)


    return {
        "success": True,
        "preview_delete": preview_delete_table_name,
        "preview_impute_x": preview_impute_x_table_name,
        "preview_impute_y": preview_impute_y_table_name,
        "dims": 2,
    }

def _parse_node_id(table_name):
    """Parse 'n3_rest_of_name' into (3, 'rest_of_name'). Returns None on failure."""
    m = re.match(r'^n(\d+)_(.+)$', table_name)
    if not m:
        return None
    return int(m.group(1)), m.group(2)
