#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots
import math
import traceback

from flask import request

from app import app, engine, db_operations
from app.db_utils.db_functions_sql import DBOperations
from app.server_utils.data_attribute_summary_integration import generate_complete_json
from app.server_utils.service_helpers import session_graph


def replace_nan(value):
    """A payload with every float NaN written as the string "NaN", which JSON has no number for."""
    if isinstance(value, dict):
        replaced = {}
        for key, item in value.items():
            replaced[key] = replace_nan(item)
        return replaced

    if isinstance(value, (list, tuple)):
        replaced = []
        for item in value:
            replaced.append(replace_nan(item))
        if isinstance(value, tuple):
            return tuple(replaced)
        return replaced

    if isinstance(value, float) and math.isnan(value):
        return "NaN"

    return value


def _node_operations(table):
    """
    A DBOperations of its own pointed at one of the graph's node tables, so drawing a node's preview leaves the
    session's current table - and its filters and column types - alone.
    :raises ValueError: when the table is not a node of this session's graph
    """
    graph = session_graph()
    if graph is None or table not in graph.node_map:
        raise ValueError(f"{table} is not a node in this graph")

    node_operations = DBOperations(engine)
    node_operations.load_table(table)
    return node_operations


@app.get("/api/plots/1-d-histogram")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """

    column = request.args.get("column")
    bin_count = int(request.args.get("bins", default=10))

    try:
        histogram = db_operations.generate_one_d_histogram_with_errors(column,bin_count)
        return {"success": True, "histogram": histogram}
    except Exception as e:
        return {"success": False, "error": str(e)}

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

    try:
        histogram = db_operations.generate_two_d_histogram_with_errors(column_x,column_y,x_bins,y_bins)
        return {"success": True, "histogram": histogram}
    except Exception as e:
        return {"success": False, "error": str(e)}



@app.get("/api/plots/top-error-rows")
def get_top_error_rows():
    """
    Endpoint to return data to be used to construct the table of errors in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    num_rows = int(request.args.get("num_rows", default=10))

    try:
        data_rows, error_rows = db_operations.generate_top_error_rows(num_rows)
        return {"success": True, "table": replace_nan(data_rows.to_dict()), "errors": error_rows.to_dict()}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    error_sample_count = int(request.args.get("error_sample_count", default=30))
    total_sample_count = int(request.args.get("total_sample_count", default=100))

    try:
        scatterplot_data = db_operations.generate_scatterplot_with_errors(x_column_name,y_column_name,error_sample_count,total_sample_count)
        return {"success": True, "scatterplot_data": scatterplot_data}

    except Exception as e:
        return {"success": False, "error": str(e)}


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
      removed_keys - the plots no longer shown: {"type": "1d", "column"} or {"type": "2d", "columns": [x, y]}
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
    :return: {"success", "data"} - see generate_complete_json
    """

    tablename = db_operations.main_table_name
    try:
        table_attribute_summaries = generate_complete_json(tablename)
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        print(f"Error generating summaries for table '{tablename}': {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/plots/preview-histogram")
def get_preview_histogram():
    """
    Return histogram data for any node's table - a candidate's preview card, a support plot - without making it
    the session's current table.

    Query params:
      tablename  – the node's table
      type       – "1d" or "2d" (default "2d")
      column     – column name (1d)
      column_x, column_y – column names (2d)
      bins       – bin count for 1d (default 10)
      x_bins, y_bins – bin counts for 2d (default 10)
    """
    table = request.args.get("tablename")
    plot_type = request.args.get("type", "2d")

    try:
        preview_ops = _node_operations(table)

        if plot_type == "1d":
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
    Return scatterplot data for any node's table, as for the preview histogram.

    Query params:
      tablename  – the node's table
      x_column, y_column – column names
      error_sample_count – default 300
      total_sample_count – default 1000
    """
    table = request.args.get("tablename")
    x_column = request.args.get("x_column")
    y_column = request.args.get("y_column")
    error_sample_count = int(request.args.get("error_sample_count", 300))
    total_sample_count = int(request.args.get("total_sample_count", 1000))

    try:
        preview_ops = _node_operations(table)
        scatterplot_data = preview_ops.generate_scatterplot_with_errors(x_column, y_column, error_sample_count, total_sample_count)
        return {"success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}
