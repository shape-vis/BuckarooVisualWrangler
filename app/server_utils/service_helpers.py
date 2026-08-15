#Buckaroo Project - started: June 1, 2025
#This file helps deliver on endpoint services

import hashlib
import inspect
import io
import json
import os
import random
import string
import re
import threading
from sqlalchemy import types as sql_types
from sqlalchemy import text as sa_text
import numpy as np
import pandas as pd

import app
from app.db_utils import query
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.server_utils.set_id_column import set_id_column
from detectors.anomaly import anomaly
from detectors.common import infer_detector_config, merged_config
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from app.pgraph.delta import Delta
from app.wrangle_operations.sql_utils import quote_identifier

# Temporary memory for preview -> Delta parameters.  When a preview is created
# we store the operation details here; when the user executes that preview,
# n_wrangle() reads these params and saves them into the permanent graph node.
PREVIEW_PARAMS = {}

# Progressive upload: large datasets return after a sample detector pass while
# the full error table is rebuilt in the background.
PROGRESSIVE_ROW_THRESHOLD = int(os.environ.get("BUCKAROO_UPLOAD_SAMPLE_ROWS", "500"))
RUN_FULL_BACKGROUND_DETECTION = os.environ.get("BUCKAROO_RUN_FULL_BACKGROUND_DETECTION") == "1"
MAX_BACKGROUND_DETECTION_ROWS = int(os.environ.get("BUCKAROO_MAX_BACKGROUND_DETECTION_ROWS", "250000"))


def should_run_full_background_detection(total_rows, max_rows=None):
    """Keep background detector work within an explicit, testable row budget."""
    limit = MAX_BACKGROUND_DETECTION_ROWS if max_rows is None else int(max_rows)
    return 0 <= int(total_rows) <= max(0, limit)
UPLOAD_BACKGROUND_STATUS = {}

def get_current_pgraph():
    """
    uses the custom json function in graph to send a json version of the graph back to the view
    :return:
    """
    return json.dumps(app.get_session_state().pgraph_for_session, default=lambda o: o.__json__() if hasattr(o, '__json__') else None)

def clicked_node_access_helper(node_table_name):
    return app.get_session_state().pgraph_for_session.set_clicked_node_as_current(node_table_name)

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
    return app.get_session_state().pgraph_for_session.redo_pgraph()

def get_pgraph_undo():
    return app.get_session_state().pgraph_for_session.undo_pgraph()

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


def _has_valid_id_column(df):
    """True when ID is numeric, unique, and already the first column."""
    if "ID" not in df.columns or df.columns[0] != "ID":
        return False
    id_values = df["ID"]
    return pd.to_numeric(id_values, errors="coerce").notnull().all() and id_values.is_unique


def error_maps_to_dataframe(error_maps, include_details=False):
    """
    Convert detector error maps directly into the app's long error format.

    Detectors return {column: {row_id: error_type}}. The old path built a wide
    DataFrame per detector and then melted it back to long form, which was a
    large extra cost on upload-sized datasets.
    """
    row_ids = []
    column_ids = []
    error_types = []
    severities = []
    confidences = []
    reasons = []
    for error_map in error_maps:
        if not error_map:
            continue
        if isinstance(error_map, dict) and "errors" in error_map:
            error_map = error_map["errors"]
        for column_id, row_errors in error_map.items():
            for row_id, error_record in row_errors.items():
                if isinstance(error_record, dict):
                    error_type = error_record.get("legacy_error_type") or error_record.get("error_type")
                    severity = error_record.get("severity")
                    confidence = error_record.get("confidence")
                    reason = error_record.get("reason")
                else:
                    error_type = error_record
                    severity = None
                    confidence = None
                    reason = None
                if pd.notna(error_type):
                    row_ids.append(int(row_id))
                    column_ids.append(column_id)
                    error_types.append(error_type)
                    severities.append(severity)
                    confidences.append(confidence)
                    reasons.append(reason)
    if not row_ids:
        return _empty_error_df(include_details=include_details)
    result = pd.DataFrame(
        {"row_id": row_ids, "column_id": column_ids, "error_type": error_types},
    )
    if include_details:
        result["severity"] = severities
        result["confidence"] = confidences
        result["reason"] = reasons
    return result


def run_detectors(data_frame, include_details=False, detector_config=None, adaptive_config=True):
    """
    Runs all 4 detectors that are implemented
    on the server, on the data, and returns a compiled dataframe of the complete errors
    :param data_frame:the dataframe to run the detectors on
    :param detector_config: optional explicit detector threshold overrides
    :param adaptive_config: when true, profile the dataset and adapt defaults before running detectors
    :return: a single compiled dataframe of all the errors detected
    """
    df_with_id = data_frame if _has_valid_id_column(data_frame) else set_id_column(data_frame)
    effective_config = (
        infer_detector_config(df_with_id, detector_config)
        if adaptive_config
        else merged_config(detector_config)
    )

    # anomaly and incomplete both need a numeric coercion of every non-ID
    # column. Computing it once here and sharing it avoids running the
    # (expensive) pd.to_numeric pass twice over the whole dataset.
    numeric_cache = {
        col: pd.to_numeric(df_with_id[col], errors="coerce")
        for col in df_with_id.columns[1:]
    }

    error_maps = [
        anomaly(df_with_id, numeric_cache=numeric_cache, include_details=include_details, config=effective_config),
        incomplete(df_with_id, numeric_cache=numeric_cache, include_details=include_details, config=effective_config),
        missing_value(df_with_id, include_details=include_details),
        datatype_mismatch(df_with_id, include_details=include_details, config=effective_config),
    ]
    return error_maps_to_dataframe(error_maps, include_details=include_details)


DETECTOR_SCOPES = {
    # Each detector has a different invalidation scope. This map is where we
    # document those rules in code so update_errors_incrementally() can avoid
    # recomputing more error rows than necessary.
    "missing": {
        "detector": missing_value,
        # Missing-value errors can be checked only on changed cells, because
        # filling one cell cannot create/remove missing values elsewhere.
        "changed_cells_valid": True,
    },
    "mismatch": {
        "detector": datatype_mismatch,
        # Type mismatch compares values against the column's majority type, so
        # changing one value can change the interpretation of the whole column.
        "changed_cells_valid": False,
    },
    "anomaly": {
        "detector": anomaly,
        # Anomaly detection depends on the column mean/std, so one value can
        # change the cutoff for every value in that attribute.
        "changed_cells_valid": False,
    },
    "incomplete": {
        "detector": incomplete,
        # Incomplete detection is row/column-context-sensitive, so we treat the
        # affected attribute as needing recomputation.
        "changed_cells_valid": False,
    },
}


def _empty_error_df(include_details=False):
    """Return an empty errors table with the same columns used by detectors."""
    columns = ["row_id", "column_id", "error_type"]
    if include_details:
        columns.extend(["severity", "confidence", "reason"])
    return pd.DataFrame(columns=columns)


def _normalize_error_df(error_df):
    """Make sure a previous errors table has the expected shape."""
    if error_df is None or error_df.empty:
        return _empty_error_df()
    normalized = error_df.copy()
    for col in ["row_id", "column_id", "error_type"]:
        if col not in normalized.columns:
            normalized[col] = pd.Series(dtype="object")
    return normalized[["row_id", "column_id", "error_type"]].dropna(subset=["error_type"])


def _call_detector(detector_fn, data_frame, detector_config=None):
    """Call a detector and pass config only when that detector accepts it."""
    kwargs = {}
    try:
        parameters = inspect.signature(detector_fn).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if detector_config is not None and ("config" in parameters or accepts_kwargs):
        kwargs["config"] = detector_config
    return detector_fn(data_frame.copy(), **kwargs)


def _detector_to_error_df(data_frame, detector_fn, detector_config=None):
    """
    Run one detector and convert its nested error map into the app's standard
    long format: row_id, column_id, error_type.
    """
    return error_maps_to_dataframe([_call_detector(detector_fn, data_frame, detector_config=detector_config)])


def _run_detector_scope(data_frame, detector_name, columns=None, row_ids=None, detector_config=None):
    """
    Run one detector on a narrowed slice of data.

    columns limits the attributes considered. row_ids optionally limits the
    rows too. This is how missing-value detection can recompute only the cells
    actually changed by an impute operation.
    """
    columns = [col for col in (columns or []) if col in data_frame.columns and col != "ID"]
    if not columns:
        return _empty_error_df()

    scoped_df = set_id_column(data_frame)
    if row_ids is not None:
        scoped_df = scoped_df[scoped_df["ID"].isin([int(row_id) for row_id in row_ids])]

    scoped_df = scoped_df[["ID"] + columns]
    return _detector_to_error_df(
        scoped_df,
        DETECTOR_SCOPES[detector_name]["detector"],
        detector_config=detector_config,
    )


def update_errors_incrementally(
    data_frame,
    previous_error_df,
    operation,
    parameters,
    detector_config=None,
    adaptive_config=True,
):
    """
    Update an errors table by invalidating and recomputing only the detector
    scopes that can be affected by a wrangle.

    Detector scope rules:
      - missing: changed cells for impute, deleted rows for delete
      - mismatch/anomaly/incomplete: changed attribute for impute
      - delete rows: full recompute for column/dataset-sensitive detectors
      - delete-column: drop errors for the removed attribute
    """
    df_with_id = set_id_column(data_frame)
    existing = _normalize_error_df(previous_error_df)
    parameters = parameters or {}
    effective_config = (
        infer_detector_config(df_with_id, detector_config)
        if adaptive_config
        else merged_config(detector_config)
    )
    # Some callers pass the operation separately, and some store it inside the
    # Delta parameters. Prefer the parameter value so replayed deltas behave the
    # same way they did during preview.
    operation = parameters.get("operation", operation)

    if operation == "delete-column":
        column = parameters.get("column")
        if not column:
            return existing
        # If the column is gone, every error attached to that column is gone.
        # Errors on all other columns are still valid.
        return existing[existing["column_id"] != column].reset_index(drop=True)

    if operation == "delete":
        row_ids = [int(row_id) for row_id in parameters.get("row_ids", [])]
        # Delete removes selected rows entirely. For row-local missing errors,
        # we can simply drop errors for deleted row IDs. For mismatch/anomaly/
        # incomplete, removing rows can change the column/dataset context, so
        # those detector types are recomputed on the surviving data.
        surviving_errors = existing[
            ~(
                existing["row_id"].isin(row_ids)
                | existing["error_type"].isin(["mismatch", "anomaly", "incomplete"])
            )
        ]
        recomputed = [
            _detector_to_error_df(
                df_with_id,
                DETECTOR_SCOPES[name]["detector"],
                detector_config=effective_config,
            )
            for name in ["mismatch", "anomaly", "incomplete"]
        ]
        return pd.concat([surviving_errors, *recomputed], ignore_index=True).drop_duplicates().reset_index(drop=True)

    if operation in {"impute", "impute_x", "impute_y"}:
        column = parameters.get("col")
        row_ids = [int(row_id) for row_id in parameters.get("row_ids", [])]
        if not column:
            return run_detectors(
                df_with_id,
                detector_config=detector_config,
                adaptive_config=adaptive_config,
            )

        # Missing errors are stale only for the exact cells that were filled.
        stale_missing = (
            (existing["column_id"] == column)
            & (existing["error_type"] == "missing")
            & (existing["row_id"].isin(row_ids))
        )
        # These detector types depend on column-level context, so the whole
        # affected attribute is stale even if only a few rows were imputed.
        stale_column_scoped = (
            (existing["column_id"] == column)
            & (existing["error_type"].isin(["mismatch", "anomaly", "incomplete"]))
        )
        # Keep all still-valid existing errors, then append fresh detector
        # results only for the scopes invalidated above.
        kept = existing[~(stale_missing | stale_column_scoped)]
        recomputed = [
            _run_detector_scope(df_with_id, "missing", [column], row_ids),
            _run_detector_scope(df_with_id, "mismatch", [column], detector_config=effective_config),
            _run_detector_scope(df_with_id, "anomaly", [column], detector_config=effective_config),
            _run_detector_scope(df_with_id, "incomplete", [column], detector_config=effective_config),
        ]
        return pd.concat([kept, *recomputed], ignore_index=True).drop_duplicates().reset_index(drop=True)

    # For operations without a specific rule, fall back to the safe behavior:
    # recompute every detector on the whole dataset.
    return run_detectors(
        df_with_id,
        detector_config=detector_config,
        adaptive_config=adaptive_config,
    )

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
    if len(value_counts) == 0:
        # An all-null column has no dominant concrete type; treat as categorical
        # to match the original behavior (value_type stays None -> True).
        return True

    unique_values = value_counts.index
    counts = value_counts.values

    # Category for each unique value is its Python type name, except string
    # values that look numeric (e.g. "123", "4.5") which are reclassified as
    # "numeric" -- identical to the original per-value rule, but the regex test
    # is vectorized over just the string values instead of one re.fullmatch
    # call per unique value.
    type_names = np.array([type(key).__name__ for key in unique_values], dtype=object)
    is_str = np.array([isinstance(key, str) for key in unique_values])
    if is_str.any():
        string_values = pd.Index([key for key in unique_values if isinstance(key, str)])
        numeric_like = np.asarray(
            string_values.str.strip().str.fullmatch(r'\d+(\.\d+)?', na=False),
            dtype=bool,
        )
        type_names[is_str] = np.where(numeric_like, "numeric", type_names[is_str])

    # Sum the value counts per category. sort=False preserves first-appearance
    # order, so ties are broken exactly like the original dict-insertion loop.
    category_totals = pd.Series(counts).groupby(type_names, sort=False).sum()

    value_type = None
    largest_type = 0
    for category, total in category_totals.items():
        if total > largest_type:
            largest_type = total
            value_type = category

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
        if col == "ID":
            dtype_map[col] = sql_types.BigInteger()
            continue

        series = df[col]
        pandas_dtype = series.dtype

        # Fast path: pandas already inferred a concrete numeric dtype during
        # read_csv, so we can skip the expensive per-column type scan.
        if pd.api.types.is_integer_dtype(pandas_dtype):
            dtype_map[col] = sql_types.BigInteger()
            continue
        if pd.api.types.is_float_dtype(pandas_dtype):
            dtype_map[col] = sql_types.Float()
            continue
        if pd.api.types.is_bool_dtype(pandas_dtype):
            dtype_map[col] = sql_types.Text()
            continue

        if is_categorical(series):
            dtype_map[col] = sql_types.Text()
        else:
            non_null = series.dropna()
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


def get_upload_background_status(table_name):
    """Return background detector status for a table uploaded progressively."""
    return UPLOAD_BACKGROUND_STATUS.get(
        table_name,
        {"status": "complete"},
    )


def _complete_error_detection(table_name, total_rows):
    """
    Recompute the full errors/rankings tables after a progressive upload.

    The upload endpoint writes all rows immediately but only blocks on detector
    output for the first PROGRESSIVE_ROW_THRESHOLD rows.
    """
    try:
        full_df = pd.read_sql_query(
            f'SELECT * FROM "{table_name}"',
            app.engine,
        )
        detected_data = run_detectors(full_df)
        write_dataframe_to_sql(
            detected_data,
            f"errors_{table_name}",
            app.engine,
            if_exists="replace",
            index=False,
        )
        rankings = calculate_attribute_rankings(detected_data)
        write_dataframe_to_sql(
            rankings,
            f"rankings_{table_name}",
            app.engine,
            if_exists="replace",
            index=False,
        )
        if app.db_operations.main_table_name == table_name:
            app.db_operations.load_table(table_name, f"errors_{table_name}")
        from app.server_utils.dataset_processing_metadata import mark_detector_complete

        mark_detector_complete(app.engine, table_name, total_rows)
        UPLOAD_BACKGROUND_STATUS[table_name] = {"status": "complete"}
        print(f"[BACKGROUND DETECTION COMPLETE] {table_name}")
    except Exception as exc:
        UPLOAD_BACKGROUND_STATUS[table_name] = {
            "status": "failed",
            "error": str(exc),
        }
        print(f"[BACKGROUND DETECTION FAILED] {table_name}: {exc}")


def start_background_error_detection(table_name, total_rows=None):
    """Kick off bounded full-table detector work without risking an unbounded read."""
    if total_rows is None:
        total_rows = int(pd.read_sql_query(
            f'SELECT COUNT(*) AS count FROM "{table_name}"',
            app.engine,
        ).iloc[0]["count"])
    if not should_run_full_background_detection(total_rows):
        UPLOAD_BACKGROUND_STATUS[table_name] = {
            "status": "sample_only",
            "reason": "dataset_exceeds_background_row_limit",
            "total_rows": int(total_rows),
            "max_background_rows": MAX_BACKGROUND_DETECTION_ROWS,
        }
        return False

    UPLOAD_BACKGROUND_STATUS[table_name] = {"status": "processing"}
    thread = threading.Thread(
        target=_complete_error_detection,
        args=(table_name, int(total_rows)),
        daemon=True,
    )
    thread.start()
    return True


def write_dataframe_to_sql(df, table_name, engine, if_exists="replace", dtype=None, index=False):
    """
    Write a DataFrame to SQL using PostgreSQL COPY for fast bulk loads.

    The app already carries row identity in the ID column, so upload paths should
    pass index=False to avoid storing the pandas RangeIndex as an extra column.
    """
    copy_df = df.reset_index() if index else df
    copy_df = copy_df.copy(deep=False)

    # Let pandas/SQLAlchemy create the table with the desired schema, then use
    # psycopg2 COPY for the actual rows. COPY is much faster than multi-row
    # INSERTs for upload-sized datasets.
    copy_df.head(0).to_sql(
        table_name,
        engine,
        if_exists=if_exists,
        index=False,
        dtype=dtype,
    )

    if copy_df.empty:
        return 0

    for col, sql_type in (dtype or {}).items():
        if col in copy_df.columns and isinstance(sql_type, sql_types.BigInteger):
            numeric_col = pd.to_numeric(copy_df[col], errors="coerce")
            copy_df[col] = numeric_col.astype("Int64")

    csv_buffer = io.StringIO()
    copy_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    columns_sql = ", ".join(quote_identifier(str(col)) for col in copy_df.columns)
    copy_sql = (
        f"COPY {quote_identifier(table_name)} ({columns_sql}) "
        "FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')"
    )

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            cursor.copy_expert(copy_sql, csv_buffer)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    return len(copy_df)

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


def execute_wrangle_preview(table, preview_table, preview_name_fn, db_operations):
    """
    Promote a preview table to the new current table and make it as a new node in the pgraph
    1. Drop all other preview tables (and their errors_ siblings)
    2. Rename preview to the new node table
    3. Reload db_operations with the new node
    Returns a dict with success and table name.
    """
    # from app import engine, db_operations

    all_possible_previews = [
        preview_name_fn(table, "_preview_delete"),
        preview_name_fn(table, "_preview_impute"),
        preview_name_fn(table, "_preview_impute_x"),
        preview_name_fn(table, "_preview_impute_y"),
    ]

    app.db_operations.drop_preview_tables(all_possible_previews, preview_table)

    wrangle_executed = extract_preview_action(preview_table)
    preview_table_trimmed = trim_preview_suffix(preview_table)

    # Enter into pgraph before current/new tables are modified. This gives us
    # the new node name that will become the promoted table version.
    new_table_name = n_wrangle(table, preview_table_trimmed, wrangle_executed, preview_table)
    
    node = app.get_session_state().pgraph_for_session.node_map[new_table_name]

    from sqlalchemy import text as sa_text
    from app import engine
    
    view_created = False
    with engine.begin() as conn:
        if node.delta:
            view_created = node.delta.promote_from_preview(
                conn, engine, table, preview_table, new_table_name
            )

    if not view_created:
        # Older operations used physical preview tables. This fallback keeps
        # those paths working if a Delta cannot create a SQL view.
        print(f"Fallback to physical renaming for operation {wrangle_executed}")
        app.db_operations.rename_preview_to_new(preview_table, new_table_name)
    
    db_operations.load_table(new_table_name, f"errors_{new_table_name}")

    app.db_operations.update_rankings(new_table_name)

    return {"success": True, "table": new_table_name}

def _clone_table_pair(conn, source_table, dest_table, errors_source):
    """Drop-and-recreate dest_table and its errors_ sibling as copies of source tables."""
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{dest_table}"'))
    conn.execute(sa_text(f'CREATE TABLE "{dest_table}" AS SELECT * FROM "{source_table}"'))
    errors_dest = f"errors_{dest_table}"
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dest}"'))
    conn.execute(sa_text(f'CREATE TABLE "{errors_dest}" AS SELECT * FROM "{errors_source}"'))

def trim_preview_suffix(name: str) -> str:
    """Remove the '_preview...' tail from a table name, if present."""
    idx = name.find("_preview")
    if idx != -1:
        return name[:idx]
    return name

def impute_target_row_ids(table, row_ids, column, engine):
    """Return selected row IDs that are currently flagged for the imputed column."""
    if not row_ids or not column:
        return []

    normalized_ids = []
    for row_id in row_ids:
        try:
            normalized_ids.append(int(row_id))
        except (TypeError, ValueError):
            continue

    if not normalized_ids:
        return []

    ids_sql = ", ".join(str(row_id) for row_id in normalized_ids)
    errors_table = quote_identifier(f"errors_{table}")
    with engine.connect() as conn:
        flagged_rows = conn.execute(
            sa_text(
                f'''
                SELECT DISTINCT row_id
                FROM {errors_table}
                WHERE row_id IN ({ids_sql})
                  AND column_id = :column
                '''
            ),
            {"column": column},
        ).scalars().all()

    flagged_set = {int(row_id) for row_id in flagged_rows}
    return [row_id for row_id in normalized_ids if row_id in flagged_set]

def init_pgraph_for_session(root_table):
    """Start a new provenance graph when a dataset is first loaded."""
    state = app.get_session_state()
    state.pgraph_for_session = PGraph(source_filename=state.original_table_name)

    # create the root node, add it to the pgraph as the root
    root_node = GraphNode("root", "root", root_table, f"errors_{root_table}")
    state.pgraph_for_session.add_root_node(root_node)

def n_wrangle(parent_table, child_table, wrangle_executed, preview_table_name=None, direct_params=None):
    """
    Create the next graph node for an executed wrangle.

    This is where delta storage becomes permanent: preview parameters are read,
    converted into a Delta, and attached to the new GraphNode.
    """
    state = app.get_session_state()
    if state.pgraph_for_session is None or parent_table not in state.pgraph_for_session.node_map:
        init_pgraph_for_session(parent_table)
        state = app.get_session_state()

    new_table_name = make_new_table_name(child_table)
    
    # Delta Storage: capture parameters and map them to replay/export behavior.
    params = direct_params
    if preview_table_name in PREVIEW_PARAMS:
        params = PREVIEW_PARAMS[preview_table_name]
    
    delta = None
    if params:
        op = params.get("operation", wrangle_executed)
        delta = Delta(op, params)
    
    current_node = GraphNode(parent_table, wrangle_executed, new_table_name, f"errors_{new_table_name}", delta=delta)
    state.pgraph_for_session.add_node(current_node)
    
    # Cleanup PREVIEW_PARAMS for this table if it was used
    if preview_table_name in PREVIEW_PARAMS:
        del PREVIEW_PARAMS[preview_table_name]
        
    return new_table_name

def make_new_table_name(child_table):
    """Prefix the table with the next graph node ID, such as n1_ or n2_."""
    node_id = app.get_session_state().pgraph_for_session.get_new_node_id()
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
    conn.execute(sa_text(f'CREATE TABLE "{errors_dest}" (LIKE "{errors_source}" INCLUDING ALL)'))

def create_previews_1d(table, row_ids, cols, preview_name_fn, update_errors_fn):
    """
    Create delete and impute preview views for a 1D (single-column) selection.
    Returns a dict with preview table names and dims=1.
    """
    from app import engine

    preview_delete = preview_name_fn(table, "_preview_delete")
    preview_impute = preview_name_fn(table, "_preview_impute")
    impute_row_ids = impute_target_row_ids(table, row_ids, cols[0], engine)
    delete_delta = Delta("delete", {"operation": "delete", "row_ids": row_ids})
    impute_delta = Delta("impute", {"operation": "impute", "row_ids": impute_row_ids, "col": cols[0]})
    impute_created = False
    
    with engine.begin() as conn:
        # Previews are SQL views generated from the same Delta objects that will
        # later be saved in the graph if the user executes one.
        delete_delta.create_view(conn, engine, table, preview_delete)
        impute_created = impute_delta.create_view(conn, engine, table, preview_impute)

    update_errors_fn(
        preview_delete,
        source_table_name=table,
        source_error_table_name=f"errors_{table}",
        operation="delete",
        parameters=delete_delta.parameters,
    )
    if impute_created:
        update_errors_fn(
            preview_impute,
            source_table_name=table,
            source_error_table_name=f"errors_{table}",
            operation="impute",
            parameters=impute_delta.parameters,
        )

    # Store preview parameters so execute can attach the chosen Delta to the
    # permanent provenance graph node.
    PREVIEW_PARAMS[preview_delete] = delete_delta.parameters
    if impute_created:
        PREVIEW_PARAMS[preview_impute] = impute_delta.parameters

    return {
        "success": True,
        "preview_delete": preview_delete,
        "preview_impute": preview_impute,
        "dims": 1,
    }

def extract_preview_action(name: str) -> str:
    """Extract the action after '_preview_' (e.g. 'impute_y'), or '' if not found."""
    marker = "_preview_"
    idx = name.find(marker)
    if idx != -1:
        return name[idx + len(marker):]
    return ""

def create_previews_2d(table, row_ids, cols, preview_name_fn, update_errors_fn):
    """
    Create delete, impute_x, and impute_y preview views for a 2D (two-column) selection.
    Returns a dict with preview table names and dims=2.
    """
    from app import engine

    preview_delete   = preview_name_fn(table, "_preview_delete")
    preview_impute_x = preview_name_fn(table, "_preview_impute_x")
    preview_impute_y = preview_name_fn(table, "_preview_impute_y")
    impute_x_row_ids = impute_target_row_ids(table, row_ids, cols[0], engine)
    impute_y_row_ids = impute_target_row_ids(table, row_ids, cols[1], engine)
    deltas_by_preview = {
        preview_delete: Delta("delete", {"operation": "delete", "row_ids": row_ids}),
        preview_impute_x: Delta("impute_x", {"operation": "impute_x", "row_ids": impute_x_row_ids, "col": cols[0]}),
        preview_impute_y: Delta("impute_y", {"operation": "impute_y", "row_ids": impute_y_row_ids, "col": cols[1]}),
    }
    created_previews = {}

    with engine.begin() as conn:
        for preview_name, delta in deltas_by_preview.items():
            # Create all available repair options so the panel can show the user
            # delete, impute-x, and impute-y previews side by side.
            created_previews[preview_name] = delta.create_view(conn, engine, table, preview_name)

    update_errors_fn(
        preview_delete,
        source_table_name=table,
        source_error_table_name=f"errors_{table}",
        operation="delete",
        parameters=deltas_by_preview[preview_delete].parameters,
    )
    
    PREVIEW_PARAMS[preview_delete] = deltas_by_preview[preview_delete].parameters
    
    if created_previews.get(preview_impute_x):
        update_errors_fn(
            preview_impute_x,
            source_table_name=table,
            source_error_table_name=f"errors_{table}",
            operation="impute_x",
            parameters=deltas_by_preview[preview_impute_x].parameters,
        )
        PREVIEW_PARAMS[preview_impute_x] = deltas_by_preview[preview_impute_x].parameters
        
    if created_previews.get(preview_impute_y):
        update_errors_fn(
            preview_impute_y,
            source_table_name=table,
            source_error_table_name=f"errors_{table}",
            operation="impute_y",
            parameters=deltas_by_preview[preview_impute_y].parameters,
        )
        PREVIEW_PARAMS[preview_impute_y] = deltas_by_preview[preview_impute_y].parameters

    return {
        "success": True,
        "preview_delete": preview_delete,
        "preview_impute_x": preview_impute_x,
        "preview_impute_y": preview_impute_y,
        "dims": 2,
    }

def _parse_node_id(table_name):
    """Parse 'n3_rest_of_name' into (3, 'rest_of_name'). Returns None on failure."""
    m = re.match(r'^n(\d+)_(.+)$', table_name)
    if not m:
        return None
    return int(m.group(1)), m.group(2)
