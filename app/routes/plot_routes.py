#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots
from flask import request
import pandas as pd
import traceback

from app import app, engine, db_operations
from app.db_utils.db_functions_sql import DBOperations
from app.server_utils.data_attribute_summary_integration import generate_complete_json

import math


def _resolve_db_for_request():
    """
    Return (db, is_temp) for the requested tablename. If the request's tablename
    query arg is missing or matches the active main table, returns the shared
    db_operations (is_temp=False). Otherwise spins up a temporary DBOperations
    loaded with the requested table; the caller is responsible for releasing it
    by passing it to _release_temp_db().
    """
    requested = request.args.get("tablename")
    if not requested or requested == db_operations.main_table_name:
        return db_operations, False

    temp_db = DBOperations(engine)
    temp_db.load_table(requested)
    return temp_db, True


def _release_temp_db(db, is_temp):
    if is_temp:
        db.reset()
        del db


def replace_nan(obj):
    if isinstance(obj, dict):
        return {k: replace_nan(v) for k, v in obj.items()}

    elif isinstance(obj, list):
        return [replace_nan(v) for v in obj]

    elif isinstance(obj, tuple):
        return tuple(replace_nan(v) for v in obj)

    elif isinstance(obj, float) and math.isnan(obj):
        return "NaN"

    else:
        return obj


@app.get("/api/plots/1-d-histogram")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """

    column = request.args.get("column")
    bin_count = int(request.args.get("bins", default=10))

    db, is_temp = _resolve_db_for_request()
    try:
        histogram = db.generate_one_d_histogram_with_errors(column, bin_count)
        return {"success": True, "histogram": histogram}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        _release_temp_db(db, is_temp)

@app.get("/api/plots/2-d-histogram")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 2d histogram in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    column_x = request.args.get("column_x")
    column_y = request.args.get("column_y")
    x_bins = int(request.args.get("x_bins", default=10))
    y_bins = int(request.args.get("y_bins", default=10))

    db, is_temp = _resolve_db_for_request()
    try:
        histogram = db.generate_two_d_histogram_with_errors(column_x, column_y, x_bins, y_bins)
        return {"success": True, "histogram": histogram}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        _release_temp_db(db, is_temp)



@app.get("/api/plots/top-error-rows")
def get_top_error_rows():
    """
    Endpoint to return data to be used to construct the table of errors in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    table = db_operations.main_table_name
    num_rows = int(request.args.get("num_rows", default=10))

    try:
        top_errors_query = f'SELECT * FROM "errors_{table}" WHERE row_id IN ( SELECT row_id FROM "errors_{table}" GROUP BY row_id ORDER BY COUNT(*) DESC LIMIT {num_rows} ) ORDER BY row_id;'
        top_errors_result = pd.read_sql_query(top_errors_query, engine)

        top_data_query = f'WITH top_row_ids AS ( SELECT row_id FROM "errors_{table}" GROUP BY row_id ORDER BY COUNT(*) DESC LIMIT {num_rows} )  SELECT d.*  FROM "{table}" d JOIN top_row_ids t ON d."ID" = t.row_id;'
        top_data_result = pd.read_sql_query(top_data_query, engine)

        return {"success": True, "table": replace_nan(top_data_result.to_dict()), "errors": top_errors_result.to_dict()}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    error_sample_count = int(request.args.get("error_sample_count", default=30))
    total_sample_count = int(request.args.get("total_sample_count", default=100))

    db, is_temp = _resolve_db_for_request()
    try:
        scatterplot_data = db.generate_scatterplot_with_errors(x_column_name, y_column_name, error_sample_count, total_sample_count)
        return {"success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        _release_temp_db(db, is_temp)


@app.post("/api/plots/rows-in-bin")
def get_rows_in_bin():
    """
    Return the row IDs that fall inside a clicked histogram bin or heatmap tile.

    Body JSON keys:
      type        – "1d" or "2d"
      column      – column name (1d only)
      column_x, column_y – column names (2d only)
      bin         – bin index (numeric) or category label (categorical), for 1d
      x_bin, y_bin – same for 2d
      bin_count   – number of bins (default 10)
      x_bins, y_bins – bin counts for 2d (default 10)
    """
    try:
        body = request.get_json(force=True)
        dim = body.get("type", "1d")

        if dim == "1d":
            column = body["column"]
            bin_value = body["bin"]
            row_ids = db_operations.get_row_ids_in_bin(column, bin_value)
        else:
            col_x = body["column_x"]
            col_y = body["column_y"]
            x_bin = body["x_bin"]
            y_bin = body["y_bin"]

            joint_col = (col_x, col_y)
            joint_bin_val = (x_bin, y_bin)
            row_ids = db_operations.get_row_ids_in_bin(joint_col, joint_bin_val)

        return {"success": True, "row_ids": row_ids}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/plots/update-backend-attributes")
def update_backend_attributes():
    """
    Given a list of now non-active attributes, remove their storage bins from the backend.

    Body JSON keys:
      removed_atributes - list of non-active attributes
    """
    try:
        body = request.get_json(force=True)
        removed_attributes = body.get("removed_keys", [])
        parsed_removed_keys = []

        for removed_attribute in removed_attributes:
            if removed_attribute.get("type") == "1d":
                parsed_removed_keys.append(removed_attribute["column"])
            else:
                x_col, y_col = removed_attribute["columns"]
                parsed_removed_keys.append((x_col, y_col))

        db_operations.del_nonactive_hists(parsed_removed_keys)
        return {"success": True}
    except Exception as e:
        print(f"Error with updating backend attributes: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/plots/bins-for-rows")
def get_bins_for_rows():
    """
    Given a list of row IDs, return which histogram bins / heatmap tiles contain
    at least one of those rows.

    Body JSON keys:
      type        – "1d" or "2d"
      column      – column name (1d only)
      column_x, column_y – column names (2d only)
      row_ids     – array of integer row IDs
      bin_count   – number of bins (default 10)
      x_bins, y_bins – bin counts for 2d (default 10)
    """
    try:
        body = request.get_json(force=True)
        dim = body.get("type", "1d")
        row_ids = body.get("row_ids", [])

        if dim == "1d":
            column = body["column"]
            bins = db_operations.get_1d_bins_containing_rows(column, row_ids)
            return {"success": True, "bins": bins}
        else:
            col_x = body["column_x"]
            col_y = body["column_y"]
            joint_col = (col_x, col_y)

            bins = db_operations.get_2d_bins_containing_rows(joint_col, row_ids)
            return {"success": True, "bins": bins}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries
    :return:
    """

    try:
        tablename = request.args.get("tablename") or db_operations.main_table_name

        pgraph = getattr(app, "pgraph_for_session", None)
        node = pgraph.node_map.get(tablename) if pgraph else None
        if node is not None and node.get_attribute_summary() is not None:
            return {"success": True, "data": node.get_attribute_summary()}

        print(f"Generating attribute summaries for table {tablename}")
        table_attribute_summaries = generate_complete_json(tablename)
        if node is not None:
            node.set_attribute_summary(table_attribute_summaries)
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        print(f"Error generating summaries for table '{tablename}': {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/plots/preview-histogram")
def get_preview_histogram():
    """
    Return histogram data for a preview table (preview_delete / preview_impute).
    Creates a temporary DBOperations instance pointed at the requested table
    so the main db_operations object (and its filters / column-type cache) is
    left untouched.

    Query params:
      tablename  – the preview table name
      type       – "1d" or "2d" (default "2d")
      column     – column name (1d)
      column_x, column_y – column names (2d)
      bins       – bin count for 1d (default 10)
      x_bins, y_bins – bin counts for 2d (default 10)
    """
    from app.db_utils.db_functions_sql import DBOperations

    table  = request.args.get("tablename")
    type_  = request.args.get("type", "2d")

    try:
        errors_table = f"errors_{table}"
        preview_ops = DBOperations(engine)
        preview_ops.load_table(table, error_table_name=errors_table)

        if type_ == "1d":
            column    = request.args.get("column")
            bin_count = int(request.args.get("bins", 10))
            histogram = preview_ops.generate_one_d_histogram_with_errors(column, bin_count)
            return {"success": True, "histogram": histogram}
        else:
            column_x = request.args.get("column_x")
            column_y = request.args.get("column_y")
            x_bins   = int(request.args.get("x_bins", 10))
            y_bins   = int(request.args.get("y_bins", 10))
            histogram = preview_ops.generate_two_d_histogram_with_errors(column_x, column_y, x_bins, y_bins)
            return {"success": True, "histogram": histogram}

    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.get("/api/plots/preview-scatterplot")
def get_preview_scatterplot():
    """
    Return scatterplot data for a preview table.
    Creates a temporary DBOperations instance for the requested preview table.

    Query params:
      tablename  – the preview table name
      x_column, y_column – column names
      error_sample_count – default 300
      total_sample_count – default 1000
    """
    from app.db_utils.db_functions_sql import DBOperations

    table = request.args.get("tablename")
    x_column = request.args.get("x_column")
    y_column = request.args.get("y_column")
    error_sample_count = int(request.args.get("error_sample_count", 300))
    total_sample_count = int(request.args.get("total_sample_count", 1000))

    try:
        errors_table = f"errors_{table}"
        preview_ops = DBOperations(engine)
        preview_ops.load_table(table, error_table_name=errors_table)
        scatterplot_data = preview_ops.generate_scatterplot_with_errors(x_column, y_column, error_sample_count, total_sample_count)
        return {"success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}
