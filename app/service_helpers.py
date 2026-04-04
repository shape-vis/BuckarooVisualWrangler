#Buckaroo Project - June 1, 2025
#This file helps deliver on endpoint services

import re

import pandas as pd

from app import data_state_manager
from app.set_id_column import set_id_column
from app import engine
from sqlalchemy import text


def clean_table_name(csv_name):
    """
    Cleans the file name so that it is ready to be used to make a table in the database, it needs to:
    - Remove file extension (.csv), replace spaces/special chars with underscores, ensure it starts with a letter (SQL requirement)
    :param csv_name: csv name from user upload
    :return: cleaned name without
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name)
    if not clean_name[0].isalpha():
        clean_name = 'table' + clean_name
    return clean_name.lower()

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
    name = clean_table_name(table_name)
    if get_errors:
        query = f"SELECT * FROM errors{name}"
        return query
    query = f"SELECT * FROM {name}"
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
    name = clean_table_name(table_name)

    if get_errors:
        query = f'SELECT * FROM errors{name} WHERE "ID" BETWEEN {min_id} AND {max_id}'
        return query

    query = f'SELECT * FROM {name} WHERE "ID" BETWEEN {min_id} AND {max_id}'
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
        melted_df = pd.melt(
            df,
            id_vars='ID',
            value_vars=get_values_for_df_melt(df),
            var_name='column_id',
            value_name='error_type'
        )
        melted_df.rename(columns={'ID': 'row_id'}, inplace=True)
        df_combined = pd.concat([df_combined,melted_df])
    nan_mask = df_combined['error_type'].isna()
    df_combined = df_combined[~nan_mask]
    df_combined.reset_index(drop=True, inplace=True)

    return df_combined

def _normalize_anomaly_methods(anomaly_methods=None, anomaly_method: str = "zscore", allow_empty: bool = False):
    """
    Normalize anomaly method input into a deduplicated, validated list.

    Accepts either a list/string in ``anomaly_methods`` or a single fallback
    value in ``anomaly_method``.
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


def _normalize_rarity_threshold(rarity_threshold, default: float = 0.01) -> float:
    try:
        threshold = float(rarity_threshold)
    except (TypeError, ValueError):
        threshold = default
    return max(0.0, min(1.0, threshold))


def filter_error_dataframe_by_anomaly_methods(
    error_df: pd.DataFrame,
    anomaly_methods,
    rarity_threshold: float | None = 0.01
):
    """
    Filter anomaly rows based on selected methods while keeping all non-anomaly errors.
    Optionally filter rarity rows (error_type='incomplete') by rarity_score threshold.
    """
    if error_df.empty:
        return error_df

    filtered_df = error_df

    if anomaly_methods is not None and "error_type" in filtered_df.columns and "raw_error_type" in filtered_df.columns:
        selected_raw_types = set(anomaly_methods_to_raw_error_types(anomaly_methods))
        anomaly_mask = filtered_df["error_type"].eq("anomaly")
        if anomaly_mask.any():
            keep_mask = (~anomaly_mask) | (filtered_df["raw_error_type"].isin(selected_raw_types))
            filtered_df = filtered_df[keep_mask].reset_index(drop=True)

    if rarity_threshold is not None and "error_type" in filtered_df.columns and "rarity_score" in filtered_df.columns:
        rarity_mask = filtered_df["error_type"].eq("incomplete")
        if rarity_mask.any():
            threshold = _normalize_rarity_threshold(rarity_threshold)
            rarity_scores = pd.to_numeric(filtered_df["rarity_score"], errors="coerce")
            keep_mask = (~rarity_mask) | (rarity_scores <= threshold)
            filtered_df = filtered_df[keep_mask].reset_index(drop=True)

    return filtered_df


def _build_detector_rows_query(
    table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.01
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

    sql = text(f"""
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
    rarity_threshold: float = 0.01
):
    detector_sql, params = _build_detector_rows_query(
        table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )

    materialized_sql = text(f"""
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
    Add the most useful indexes for persisted or materialized error tables.

    Main query patterns use:
    - row_id range filters
    - joins on row_id
    - grouping/filtering by column_id
    - anomaly-method filtering through (error_type, raw_error_type)
    - rarity filtering through (error_type, rarity_score)
    """
    statements = [
        text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_row_id" ON "{table_name}" (row_id)'),
        text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_column_id" ON "{table_name}" (column_id)'),
        text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_row_column" ON "{table_name}" (row_id, column_id)'),
        text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_error_raw" ON "{table_name}" (error_type, raw_error_type)'),
        text(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_error_rarity" ON "{table_name}" (error_type, rarity_score)'),
    ]
    for statement in statements:
        conn.execute(statement)


def run_detectors(
    table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.01
):
    """
    Run all detector categories for a table and return a unified long error dataframe.
    """
    sql, params = _build_materialized_errors_select_query(
        table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )

    combined = pd.read_sql_query(sql, engine, params=params)
    if combined.empty:
        return pd.DataFrame(columns=["row_id", "column_id", "error_type", "raw_error_type", "rarity_score"])
    return combined


def refresh_errors_table(
    table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.01
) -> int:
    """
    Rebuild errors{table_name} directly in SQL from the detector functions.
    """
    cleaned_table_name = clean_table_name(table_name)
    errors_table = f"errors{cleaned_table_name}"
    sql, params = _build_materialized_errors_select_query(
        cleaned_table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )

    create_sql = text(f"""
        CREATE TABLE "{errors_table}" AS
        {sql.text}
    """)
    count_sql = text(f'SELECT COUNT(*) FROM "{errors_table}"')
    drop_sql = text(f'DROP TABLE IF EXISTS "{errors_table}"')

    with engine.begin() as conn:
        conn.execute(drop_sql)
        conn.execute(create_sql, params)
        _create_error_table_indexes(conn, errors_table)
        row_count = conn.execute(count_sql).scalar() or 0

    return int(row_count)


def materialize_selected_errors_table(
    table_name: str,
    target_table_name: str,
    anomaly_method: str = "zscore",
    anomaly_methods=None,
    rarity_threshold: float = 0.01
) -> int:
    """
    Materialize a selected-method / selected-rarity error table directly in SQL.
    """
    cleaned_table_name = clean_table_name(table_name)
    sql, params = _build_materialized_errors_select_query(
        cleaned_table_name,
        anomaly_method=anomaly_method,
        anomaly_methods=anomaly_methods,
        rarity_threshold=rarity_threshold
    )
    drop_sql = text(f'DROP TABLE IF EXISTS "{target_table_name}"')
    create_sql = text(f'CREATE TABLE "{target_table_name}" AS {sql.text}')
    count_sql = text(f'SELECT COUNT(*) FROM "{target_table_name}"')

    with engine.begin() as conn:
        conn.execute(drop_sql)
        conn.execute(create_sql, params)
        _create_error_table_indexes(conn, target_table_name)
        row_count = conn.execute(count_sql).scalar() or 0

    return int(row_count)

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


def refresh_rankings_table(
    table_name: str,
    anomaly_methods=None,
    rarity_threshold: float | None = 0.01
):
    """
    Rebuild rankings{table_name} directly in SQL from the persisted errors table.

    This keeps rankings computation DB-side instead of materializing the full error
    dataframe in pandas for grouping/sorting.
    """
    cleaned_table_name = clean_table_name(table_name)
    rankings_table = f"rankings{cleaned_table_name}"
    errors_table = f"errors{cleaned_table_name}"

    selected_raw_types = anomaly_methods_to_raw_error_types(anomaly_methods)
    threshold = _normalize_rarity_threshold(rarity_threshold)

    params = {
        "threshold": threshold,
        "selected_raw_types": selected_raw_types,
    }

    drop_sql = text(f'DROP TABLE IF EXISTS "{rankings_table}"')
    create_sql = text(f"""
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
            if pd.isna(col) or col is None or str(col).strip() == "":
                col = "Unknown" 
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
