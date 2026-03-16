#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots
import hashlib
import json
from pathlib import Path

from flask import request
import pandas as pd
import traceback

from app import app, engine, service_helpers, db_operations
from app.service_helpers import group_by_attribute, get_whole_table_query
from app.data_attribute_summary_integration import *
# from data_management.data_integration import *

import math


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

    try:
        histogram = db_operations.generate_one_d_histogram_with_errors(column,bin_count)
        return {"Success": True, "histogram": histogram}
    except Exception as e:
        return {"Success": False, "Error": str(e)}

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
        return {"Success": True, "histogram": histogram}
    except Exception as e:
        return {"Success": False, "Error": str(e)}



@app.get("/api/plots/top-error-rows")
def get_top_error_rows():
    """
    Endpoint to return data to be used to construct the table of errors in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    table = request.args.get("tablename")
    num_rows = request.args.get("num_rows", default=10)

    try:
        top_errors_query = f"SELECT * FROM \"errors_{table}\" WHERE row_id IN (  SELECT row_id   FROM \"errors_{table}\"   GROUP BY row_id   ORDER BY COUNT(*) DESC   LIMIT {num_rows} ) ORDER BY row_id;"
        top_errors_result = pd.read_sql_query(top_errors_query, engine)

        print(f"### Top errors query: {top_errors_query}")
        print(f"### Top errors result: {top_errors_result}")

        # top_data_query = f"WITH top_row_ids AS ( SELECT row_id FROM \"{table}_errors\" GROUP BY row_id ORDER BY COUNT(*) DESC LIMIT {num_rows} )  SELECT d.*  FROM \"{table}\" d JOIN top_row_ids t ON d.\"index\" = t.row_id;"
        top_data_query = f"WITH top_row_ids AS ( SELECT row_id FROM \"errors_{table}\" GROUP BY row_id ORDER BY COUNT(*) DESC LIMIT {num_rows} )  SELECT d.*  FROM \"{table}\" d JOIN top_row_ids t ON d.\"ID\" = t.row_id;"
        top_data_result = pd.read_sql_query(top_data_query, engine)

        print(f"### Top data query: {top_data_query}")
        print(f"### Top data result: ")
        print(top_data_result)

        # # TODO: Implement logic to get top error rows based on error counts
        # query = f"SELECT * FROM \"{table}\" LIMIT {num_rows};"
        # print(f"Executing query: {query}")
        # result = pd.read_sql_query(query, engine).to_dict()

        return {"Success": True, "table": replace_nan(top_data_result.to_dict()), "errors": top_errors_result.to_dict()}

    except Exception as e:
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    table = request.args.get("tablename")
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    error_sample_count = int(request.args.get("error_sample_count", default=30))
    total_sample_count = int(request.args.get("total_sample_count", default=100))

    try:
        scatterplot_data = db_operations.generate_scatterplot_with_errors(x_column_name,y_column_name,error_sample_count,total_sample_count)
        return {"Success": True, "scatterplot_data": scatterplot_data}

    except Exception as e:
        return {"Success": False, "Error": str(e)}


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
    from app.db_functions_sql import DBOperations

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
            return {"Success": True, "histogram": histogram}
        else:
            column_x = request.args.get("column_x")
            column_y = request.args.get("column_y")
            x_bins   = int(request.args.get("x_bins", 10))
            y_bins   = int(request.args.get("y_bins", 10))
            histogram = preview_ops.generate_two_d_histogram_with_errors(column_x, column_y, x_bins, y_bins)
            return {"Success": True, "histogram": histogram}

    except Exception as e:
        traceback.print_exc()
        return {"Success": False, "Error": str(e)}


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
    from app.db_functions_sql import DBOperations

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
        return {"Success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        traceback.print_exc()
        return {"Success": False, "Error": str(e)}


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
            bin_count = int(body.get("bin_count", 10))
            row_ids = db_operations.get_row_ids_in_1d_bin(column, bin_value, bin_count)
        else:
            col_x = body["column_x"]
            col_y = body["column_y"]
            x_bin = body["x_bin"]
            y_bin = body["y_bin"]
            x_bins = int(body.get("x_bins", 10))
            y_bins = int(body.get("y_bins", 10))
            row_ids = db_operations.get_row_ids_in_2d_bin(col_x, col_y, x_bin, y_bin, x_bins, y_bins)

        return {"Success": True, "row_ids": row_ids}
    except Exception as e:
        traceback.print_exc()
        return {"Success": False, "Error": str(e)}


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
            bin_count = int(body.get("bin_count", 10))
            bins = db_operations.get_1d_bins_containing_rows(column, row_ids, bin_count)
            return {"Success": True, "bins": bins}
        else:
            col_x = body["column_x"]
            col_y = body["column_y"]
            x_bins = int(body.get("x_bins", 10))
            y_bins = int(body.get("y_bins", 10))
            bins = db_operations.get_2d_bins_containing_rows(col_x, col_y, row_ids, x_bins, y_bins)
            return {"Success": True, "bins": bins}
    except Exception as e:
        traceback.print_exc()
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries
    :return:
    """

    try:
        tablename = db_operations.main_table_name
        print(f"Generating attribute summaries for table {tablename}")
        table_attribute_summaries = generate_complete_json(tablename)
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        print(f"Error generating summaries for table '{tablename}': {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
