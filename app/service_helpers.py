#Buckaroo Project - started: June 1, 2025
#This file helps deliver on endpoint services

import hashlib
import random
import string
import re
from sqlalchemy import types as sql_types
from sqlalchemy import text as sa_text
import pandas as pd
from app import engine
from app.set_id_column import set_id_column
from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from postgres_wrangling import query


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
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    return _safe_pg_name("data_" + clean_name, "_" + random_string)


def clean_table_name(csv_name):
    """
    Clean a table or file name so we can safely use it as the base SQL table name.
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name)
    if clean_name and not clean_name[0].isalpha():
        clean_name = 'table' + clean_name
    return clean_name.lower()


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


def _normalize_anomaly_methods(anomaly_methods=None, anomaly_method: str = "zscore", allow_empty: bool = False):
    """
    Turn the anomaly method input into a clean list we can trust.
    """
    allowed_methods = {"zscore", "mad", "iqr"}

    if anomaly_methods is None:
        candidates = [anomaly_method]
    elif isinstance(anomaly_methods, str):
        candidates = [anomaly_methods]
    else:
        candidates = list(anomaly_methods)

    normalized = []
    for method in candidates:
        method_normalized = str(method).strip().lower()
        if method_normalized in allowed_methods and method_normalized not in normalized:
            normalized.append(method_normalized)

    if allow_empty:
        return normalized
    return normalized or ["zscore"]


def anomaly_methods_to_raw_error_types(anomaly_methods):
    method_to_raw = {
        "zscore": "zscore_anomaly",
        "mad": "mad_anomaly",
        "iqr": "iqr_anomaly",
    }
    normalized = _normalize_anomaly_methods(anomaly_methods=anomaly_methods, allow_empty=True)
    return [method_to_raw[method] for method in normalized if method in method_to_raw]


def _normalize_rarity_threshold(rarity_threshold, default: float = 0.05) -> float:
    try:
        threshold = float(rarity_threshold)
    except (TypeError, ValueError):
        threshold = default
    return max(0.0, min(1.0, threshold))


def _build_detector_rows_query(
    table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.05
):
    methods_to_run = _normalize_anomaly_methods(
        anomaly_methods=anomaly_methods,
        anomaly_method=anomaly_method
    )

    anomaly_selects = []
    params = {
        "table_name": table_name,
        "rarity_threshold_pct": _normalize_rarity_threshold(rarity_threshold),
    }
    for index, method in enumerate(methods_to_run):
        method_key = f"anomaly_method_{index}"
        params[method_key] = method
        anomaly_selects.append(
            f"SELECT row_id, column_name, error_type FROM detect_anomalies(:table_name, :{method_key})"
        )

    anomaly_union_sql = "\nUNION ALL\n".join(anomaly_selects)

    sql = sa_text(f"""
        WITH anomaly_union AS (
            {anomaly_union_sql}
        ),
        anomaly_rows AS (
            SELECT
                row_id,
                column_name,
                MIN(error_type) AS error_type,
                NULL::numeric AS rarity_score
            FROM anomaly_union
            GROUP BY row_id, column_name
        ),
        rarity_rows AS (
            SELECT
                row_id,
                column_name,
                error_type,
                rarity_score
            FROM detect_rarity(:table_name, :rarity_threshold_pct)
        ),
        missing_rows AS (
            SELECT
                row_id,
                column_name,
                error_type,
                NULL::numeric AS rarity_score
            FROM detect_missing_values(:table_name)
        ),
        mismatch_rows AS (
            SELECT
                row_id,
                column_name,
                error_type,
                NULL::numeric AS rarity_score
            FROM detect_datatype_mismatch(:table_name)
        )
        SELECT
            row_id,
            column_name AS column_id,
            error_type,
            rarity_score
        FROM anomaly_rows
        UNION ALL
        SELECT
            row_id,
            column_name AS column_id,
            error_type,
            rarity_score
        FROM rarity_rows
        UNION ALL
        SELECT
            row_id,
            column_name AS column_id,
            error_type,
            rarity_score
        FROM missing_rows
        UNION ALL
        SELECT
            row_id,
            column_name AS column_id,
            error_type,
            rarity_score
        FROM mismatch_rows
        ORDER BY row_id, column_id, error_type
    """)

    return sql, params


def _build_materialized_errors_select_query(
    table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.05
):
    detector_sql, params = _build_detector_rows_query(
        table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )

    materialized_sql = sa_text(f"""
        SELECT
            row_id,
            column_id,
            CASE
                WHEN error_type LIKE '%anomaly%' THEN 'anomaly'
                ELSE error_type
            END AS error_type,
            error_type AS raw_error_type,
            rarity_score
        FROM ({detector_sql.text}) detector_rows
    """)
    return materialized_sql, params


def _create_error_table_indexes(conn, table_name: str) -> None:
    """
    Add the indexes we care about for error tables.
    """
    table_hash = hashlib.md5(table_name.encode()).hexdigest()[:8]
    statements = [
        sa_text(f'CREATE INDEX IF NOT EXISTS "idx_err_{table_hash}_row_id" ON "{table_name}" (row_id)'),
        sa_text(f'CREATE INDEX IF NOT EXISTS "idx_err_{table_hash}_column_id" ON "{table_name}" (column_id)'),
        sa_text(f'CREATE INDEX IF NOT EXISTS "idx_err_{table_hash}_row_column" ON "{table_name}" (row_id, column_id)'),
        sa_text(f'CREATE INDEX IF NOT EXISTS "idx_err_{table_hash}_error_raw" ON "{table_name}" (error_type, raw_error_type)'),
        sa_text(f'CREATE INDEX IF NOT EXISTS "idx_err_{table_hash}_error_rarity" ON "{table_name}" (error_type, rarity_score)'),
    ]
    for statement in statements:
        conn.execute(statement)


def materialize_selected_errors_table(
    table_name: str,
    target_table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.05
) -> int:
    """
    Materialize a selected-method / selected-rarity error table directly in SQL.
    """
    sql, params = _build_materialized_errors_select_query(
        table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )
    drop_sql = sa_text(f'DROP TABLE IF EXISTS "{target_table_name}"')
    create_sql = sa_text(f'CREATE TABLE "{target_table_name}" AS {sql.text}')
    count_sql = sa_text(f'SELECT COUNT(*) FROM "{target_table_name}"')

    with engine.begin() as conn:
        conn.execute(drop_sql)
        conn.execute(create_sql, params)
        _create_error_table_indexes(conn, target_table_name)
        row_count = conn.execute(count_sql).scalar() or 0

    return int(row_count)


def refresh_rankings_table(
    table_name: str,
    anomaly_methods=None,
    rarity_threshold: float | None = 0.05
):
    """
    Rebuild rankings for a table from the current persisted errors table.
    """
    rankings_table = f"rankings_{table_name}"
    errors_table = f"errors_{table_name}"

    selected_raw_types = anomaly_methods_to_raw_error_types(anomaly_methods)
    threshold = _normalize_rarity_threshold(rarity_threshold)

    params = {
        "threshold": threshold,
        "selected_raw_types": selected_raw_types,
    }

    drop_sql = sa_text(f'DROP TABLE IF EXISTS "{rankings_table}"')
    create_sql = sa_text(f"""
        CREATE TABLE "{rankings_table}" AS
        WITH filtered_errors AS (
            SELECT e.*
            FROM "{errors_table}" e
            WHERE (
                e.error_type <> 'anomaly'
                OR e.raw_error_type = ANY(:selected_raw_types)
            )
            AND (
                e.error_type <> 'incomplete'
                OR e.rarity_score IS NULL
                OR e.rarity_score <= :threshold
            )
        ),
        counts AS (
            SELECT
                column_id AS attribute,
                COUNT(*)::int AS total_errors
            FROM filtered_errors
            WHERE column_id IS NOT NULL
              AND BTRIM(column_id) <> ''
            GROUP BY column_id
        )
        SELECT
            attribute,
            total_errors,
            ROW_NUMBER() OVER (ORDER BY total_errors DESC, attribute ASC)::int AS rank
        FROM counts;
    """)

    with engine.begin() as conn:
        conn.execute(drop_sql)
        conn.execute(create_sql, params)


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

def _clone_table_pair(conn, source_table, dest_table, errors_source):
    """Drop-and-recreate dest_table and its errors_ sibling as copies of source tables."""
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{dest_table}"'))
    conn.execute(sa_text(f'CREATE TABLE "{dest_table}" AS SELECT * FROM "{source_table}"'))
    errors_dest = f"errors_{dest_table}"
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dest}"'))
    conn.execute(sa_text(f'CREATE TABLE "{errors_dest}" AS SELECT * FROM "{errors_source}"'))

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

def create_previews_1d(table, row_ids, cols, preview_name_fn, update_errors_fn):
    """
    Create delete and impute preview tables for a 1D (single-column) selection.
    Returns a dict with preview table names and dims=1.
    """
    from app import engine

    errors_src     = f"errors_{table}"
    preview_delete = preview_name_fn(table, "_preview_delete")
    preview_impute = preview_name_fn(table, "_preview_impute")

    with engine.begin() as conn:
        _clone_table_pair(conn, table, preview_delete, errors_src)
        _clone_table_pair(conn, table, preview_impute, errors_src)
        #create_minimal_preview_table(conn, table, preview_delete, errors_src, cols)
        #create_minimal_preview_table(conn, table, preview_impute, errors_src, cols)


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
    preview_impute_x = preview_name_fn(table, "_preview_impute_x")
    preview_impute_y = preview_name_fn(table, "_preview_impute_y")

    with engine.begin() as conn:
        _clone_table_pair(conn, table, preview_delete, errors_src)
        _clone_table_pair(conn, table, preview_impute_x, errors_src)
        _clone_table_pair(conn, table, preview_impute_y, errors_src)

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
