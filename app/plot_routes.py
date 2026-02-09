#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots

from flask import request
import pandas as pd
import traceback

from app import app, engine, service_helpers, data_state_manager
from app.service_helpers import group_by_attribute, clean_table_name, get_whole_table_query
from data_management.data_attribute_summary_integration import *
from data_management.data_integration import *
from data_management.data_scatterplot_integration import generate_scatterplot_sample_data

@app.get("/api/plots/1-d-histogram")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    table = clean_table_name(request.args.get("tablename"))
    column = request.args.get("column")
    bin_count = request.args.get("bins", default=10)
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)

    try:
        query = f"SELECT generate_one_d_histogram_with_errors('{table}', 'errors_{table}', '{column}', {bin_count}, {min_id}, {max_id});"
        result = pd.read_sql_query(query, engine).to_dict()
        histogram = result["generate_one_d_histogram_with_errors"][0]

        return {"Success": True, "histogram": histogram}

    except Exception as e:
        return {"Success": False, "Error": str(e)}

@app.get("/api/plots/2-d-histogram")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 2d histogram in the view
    :return: the data from the database in JSON format specific to what the view needs to ingest it
    """
    table = clean_table_name(request.args.get("tablename"))
    column_x = request.args.get("column_x")
    column_y = request.args.get("column_y")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    x_bins = request.args.get("x_bins", default=10)
    y_bins = request.args.get("y_bins", default=10)

    try:
        query_str = f"SELECT generate_two_d_histogram_with_errors('{table}', 'errors_{table}', '{column_x}','{column_y}', {x_bins},{y_bins}, {min_id}, {max_id});"
        binned_data = pd.read_sql_query(query_str, engine).to_dict()
        histogram = binned_data["generate_two_d_histogram_with_errors"][0]

        return {"Success": True, "histogram": histogram}

    except Exception as e:
        return {"Success": False, "Error": str(e)}

@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    table = clean_table_name(request.args.get("tablename"))
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    error_sample_count = request.args.get("error_sample_count", default=30)
    total_sample_count = request.args.get("total_sample_count", default=100)

    try:
        query = f"SELECT generate_scatterplot_with_errors('{table}', 'errors_{table}', '{x_column_name}', '{y_column_name}', {error_sample_count}, {total_sample_count}, {min_id}, {max_id});"
        result = pd.read_sql_query(query, engine).to_dict()
        scatterplot_data = result["generate_scatterplot_with_errors"][0]

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
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    tablename = request.args.get("tablename")

    if not tablename:
        return {"success": False, "error": "No tablename provided"}

    try:
        #get the current error table
        table_attribute_summaries = generate_complete_json(int(min_id), int(max_id), tablename)
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        print(f"Error generating summaries for table '{tablename}': {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
