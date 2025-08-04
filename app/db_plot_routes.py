#Buckaroo Project - July 25, 2025,
#This file handles all endpoints surrounding plots, but calls them directly from the db

from flask import request

from app import app, engine
from app.service_helpers import group_by_attribute, clean_table_name
from data_management.data_attribute_summary_integration import *
from data_management.data_integration import *
from data_management.data_scatterplot_integration import generate_scatterplot_sample_data


# from data_management.data_integration import generate_1d_histogram_data


@app.get("/api/plots/1-d-histogram-data-db")
def get_1d_histogram_db():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view, this endpoint expects the following parameters:
        1. tablename to pull data from
        2. column name to aggregate data for
        3. desired id min and max values of the table to return to the view
    :return: the data as a csv
    """
    tablename = request.args.get("tablename")
    cleaned_name = clean_table_name(tablename)
    column_name = request.args.get("column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    number_of_bins = request.args.get("bins", default=10)
    query = f"SELECT generate_one_d_histogram_with_errors('{cleaned_name}', 'errors{cleaned_name}', '{column_name}', {number_of_bins}, {min_id}, {max_id});"

    try:
        print("in the try")
        binned_data = pd.read_sql_query(query, engine).to_dict()
        histogram = binned_data["generate_one_d_histogram_with_errors"][0]
        return {"Success": True, "binned_data": histogram}
    except Exception as e:
        return {"Success": False, "Error": str(e)}

@app.get("/api/plots/2-d-histogram-data-db")
def get_2d_histogram_db():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view, this endpoint expects the following parameters:
        1. tablename to pull data from
        2. column name to aggregate data for
        3. desired id min and max values of the table to return to the view
    :return: the data as a csv
    """
    tablename = request.args.get("tablename")
    cleaned_name = clean_table_name(tablename)
    column_x = request.args.get("column_x")
    column_y = request.args.get("column_y")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    x_bins = request.args.get("x_bins", default=10)
    y_bins = request.args.get("y_bins", default=10)
    query = f"SELECT generate_two_d_histogram_with_errors('{cleaned_name}', 'errors{cleaned_name}', '{column_x}','{column_y}', {x_bins},{y_bins}, {min_id}, {max_id});"

    try:
        print("in the try")
        binned_data = pd.read_sql_query(query, engine).to_dict()
        histogram = binned_data["generate_two_d_histogram_with_errors"][0]
        return {"Success": True, "binned_data": histogram}
    except Exception as e:
        return {"Success": False, "Error": str(e)}
