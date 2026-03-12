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


# @app.get("/api/plots/group-by")
# def get_group_by():
#     """
#     Endpoint to return the data according to the specified column the user wishes to group by a specific attribute - ex. group ages by continent
#     :return: the data as a csv
#     """
#     column_a_name = request.args.get("column_a")
#     group_by_name = request.args.get("group_by")
#     df = data_state_manager.get_current_state()["df"]
#     column_a = df[column_a_name]
#     group_by = df[group_by_name]
#     try:
#         if is_categorical(column_a) and is_categorical(group_by):
#             new_df = group_by_attribute(df, column_a_name, group_by_name).to_json()
#             return {"Success": True, "group_by": new_df}
#         return {"Success": False, "Error": "Both column input to the group_by are not categorical"}
#     except Exception as e:
#         return {"Success": False, "Error": str(e)}


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
