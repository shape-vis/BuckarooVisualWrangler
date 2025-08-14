#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots

from flask import request

from app import app
from app.service_helpers import group_by_attribute
from data_management.data_attribute_summary_integration import *
from data_management.data_integration import *
from data_management.data_scatterplot_integration import generate_scatterplot_sample_data

@app.get("/api/plots/1-d-histogram-data")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view
    :return: the data as JSON in the format the view needs
    """
    column_name = request.args.get("column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    number_of_bins = request.args.get("bins", default=10)

    try:
        binned_data = generate_1d_histogram_data(column_name, int(number_of_bins), min_id, max_id)
        return {"Success": True, "binned_data": binned_data}
    except Exception as e:
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/2-d-histogram-data")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 2d histogram in the view
    :return: the data as JSON in the format the view needs
    """
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    number_of_bins = request.args.get("bins", default=10)

    try:
        binned_data = generate_2d_histogram_data(x_column_name, y_column_name, number_of_bins, number_of_bins, min_id,
                                                 max_id)
        return {"Success": True, "binned_data": binned_data}
    except Exception as e:
        return {"Success": False, "Error": str(e)}

@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    """
    Endpoint to return data to be used to construct the scatter plot in the view
    :return: the data as JSON in the format the view needs
    """
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    error_sample_count = request.args.get("error_sample_count", default=30)
    total_sample_count = request.args.get("total_sample_count", default=100)

    try:
        scatterplot_data = generate_scatterplot_sample_data(x_column_name, y_column_name, int(min_id), int(max_id), int(error_sample_count), int(total_sample_count))
        return {"Success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        return {"Success": False, "Error": str(e)}


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
    :return: the current df - can be changed according to what the view needs
    """
    try:
        data_state_manager.undo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}



@app.get("/api/plots/redo")
def redo():
    """
    Redoes the previous action performed on the data
    :return: the current undetected df - can be changed according to what the view needs
    """
    try:
        data_state_manager.redo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries and returns them for the view to ingest
    :return: json of the attribute summaries
    """
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    try:
        #get the current error table
        table_attribute_summaries = generate_complete_json(int(min_id), int(max_id))
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        return {"success": False, "error": str(e)}



