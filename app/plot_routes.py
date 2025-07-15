#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding plots
from email.policy import default

import numpy as np
import pandas as pd
from flask import request, render_template
from numpy import number
from sqlalchemy import column

from app import app, data_state_manager
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict, get_2d_bins, \
 group_by_attribute, is_categorical, create_bins_for_a_numeric_column, add_normal_row_to_error_dist, \
    get_error_dist
from data_management.data_integration import generate_1d_histogram_data


@app.get("/api/plots/1-d-histogram-data")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view, this endpoint expects the following parameters:
        1. tablename to pull data from
        2. column name to aggregate data for
        3. desired id min and max values of the table to return to the view
    :return: the data as a csv
    """
    tablename = request.args.get("tablename")
    column_name = request.args.get("column")
    min_id = request.args.get("min_id",default=0)
    max_id = request.args.get("max_id", default=200)
    number_of_bins = request.args.get("bins",default=10)

    try:
        print("in the try")
        binned_data = generate_1d_histogram_data(column_name,number_of_bins,min_id,max_id)
        return {"Success":True,"binned_data":binned_data}
    except Exception as e:
        return {"Success": False, "Error": str(e)}

@app.get("/api/plots/2-d-histogram-data")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view - user will pass in parameters for the axis that is filled in
    :return: the data as a csv
    """
    table_name = request.args.get("tablename")
    column_a = request.args.get("column_a")
    column_b = request.args.get("column_b")
    range = request.args.get("range")

    #TODO: Make this an optional parameter
    bin_count = int(request.args.get("bin_count"))
    df = data_state_manager.get_current_state()["df"]
    column_a = df[column_a]
    column_b = df[column_b]
    try:
        binned_data = get_2d_bins(column_a,column_b, range,bin_count)
        print(binned_data)
        ret_val = binned_data.to_json()
        return {"Success": True, "binned_data": ret_val}
    except Exception as e:
        return {"Success": False, "Error": str(e)}

#add endpoints for the scatterplots and also to have min max ranges for the numerical value and lists of values for categorical


@app.get("/api/plots/group-by")
def get_group_by():
    """
    Endpoint to return the data according to the specified column the user wishes to group by a specific attribute - ex. group ages by continent
    :return: the data as a csv
    """
    column_a_name = request.args.get("column_a")
    group_by_name = request.args.get("group_by")
    df = data_state_manager.get_current_state()["df"]
    column_a = df[column_a_name]
    group_by = df[group_by_name]
    try:
        if is_categorical(column_a) and is_categorical(group_by):
            new_df = group_by_attribute(df, column_a_name, group_by_name).to_json()
            return {"Success": True, "group_by": new_df}
        return {"Success": False, "Error": "Both column input to the group_by are not categorical"}
    except Exception as e:
       return {"Success": False, "Error": str(e)}

@app.get("/api/plots/undo")
def undo():
    """
    Undoes the previous action performed on the data
    :return: Nothing right now - can be changed according to what the view needs
    """
    try:
        data_state_manager.undo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        print(data_state_manager.get_current_state())
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        # print(current_df)
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}

#need range for 1d,2d, and scatterplot implement
@app.get("/api/plots/redo")
def redo():
    """
    Redoes the previous action performed on the data
    :return: Nothing right now - can be changed according to what the view needs
    """
    try:
        data_state_manager.redo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        print(data_state_manager.get_current_state())
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        # print(current_df)
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries
    :return:
    """
    try:
        #get the current error table
        current_data_state = data_state_manager.get_current_state()
        normal_df = current_data_state['df']
        error_df = current_data_state['error_df']
        full_summary = add_normal_row_to_error_dist(get_error_dist(error_df),normal_df)
        full_summary_dict = full_summary.to_dict(orient="records")
        return {"success": True, "data": full_summary_dict}

    except Exception as e:
        return {"success": False, "error": str(e)}
    
@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    pass
