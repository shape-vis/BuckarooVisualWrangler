#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding wranglers

from flask import request
import json
from app import app
from app.service_helpers import run_detectors, update_data_state
from wranglers.impute_average import impute_average_on_ids
from wranglers.remove_data import remove_data
from app import data_state_manager
from pprint import pprint
from postgres_wrangling import query
"""
All these endpoints expected the following input data:
    1. points to wrangle
    2. the filename
    3. selection range of points to return to the view
"""

# @app.get("/api/wrangle/remove")
# def wrangle_remove():
#     """
#     Should handle when a user sends a request to remove specific data
#     get table from db into df -> delete id's from it -> store as a wrangled table in df
#     :return: result of the wrangle on the data
#     """
#     # filename = request.args.get("filename")
#     point_range_to_return = request.args.get("range")
#     points_to_remove = (request.args.get("points"))
#     points_to_remove_array = [points_to_remove]
#     preview = request.args.get("preview")
#     graph_type = request.args.get("graph_type")

#     try:
#         current_state = data_state_manager.get_current_state()
#         current_df = current_state["df"]
#         wrangled_df = remove_data(current_df, points_to_remove_array)
#         new_error_df = run_detectors(wrangled_df)
#         new_state = {"df": wrangled_df, "error_df": new_error_df}
#         data_state_manager.push_right_table_stack(new_state)
#         if preview == "yes":
#             data_state_manager.pop_right_table_stack()
#             return {"success": True, "new-state": None}
#         else:
#             return {"success": True, "new-state": wrangled_df}
#     except Exception as e:
#         return {"success": False, "error": str(e)}
    
@app.post("/api/wrangle/remove")
def wrangle_remove():
    """
    Remove selected rows from *table* and save the wrangled version.

    Expects JSON body:
        {
            "currentSelection": {...},
            "viewParameters":  {...},
            "table": "tablename"
        }
    """
    try:
        body             = request.get_json(force=True)  # or omit force=True if you prefer 415 on bad content-type
        currentSelection = body["currentSelection"]
        cols   = body["cols"]
        table            = body["table"]

        print("current selection:")
        pprint(currentSelection)
        print("cols:")
        pprint(cols)
        print("table:", table)

        new_table_name = query.new_table_name(table)

        deletedRowCount = query.copy_without_flagged_rows(current_selection=currentSelection, cols=cols, table=table, new_table_name=new_table_name)

        return {"success": True, "deletedRows": deletedRowCount, "new_table_name": new_table_name}
    except Exception as e:
        # Log e for debugging
        
        return {"success": False, "error": str(e)}, 400


@app.get("/api/wrangle/impute")
def wrangle_impute():
    """
    Should handle when a user sends a request to impute specific data
    :return: result of the wrangle on the data
    """
    filename = request.args.get("filename")
    point_range_to_return = request.args.get("range")
    points_to_remove = (request.args.get("points"))
    points_to_remove_array = [points_to_remove]
    preview = request.args.get("preview")
    axis = request.args.get("axis")
    # these can be used later to set the different ranges the user wants to get data from
    # min_id = request.args.get()point_range_to_return["min"]
    # max_id = point_range_to_return["max"]

    if not filename:
        return {"success": False, "error": "Filename required"}

    # guery to get the selected range of points to return to the view

    try:
        current_state = data_state_manager.get_current_state()
        current_df = current_state["df"]
        # remove the points from the df
        wrangled_df = impute_average_on_ids(axis,current_df, points_to_remove_array)
        # run the detectors on the new df
        new_error_df = run_detectors(wrangled_df)

        if preview == "no":
            # update the table state of the app
            update_data_state(wrangled_df, new_error_df)
            # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
            new_state = data_state_manager.get_current_state()
            new_df = new_state["df"].to_dict("records")
            new_error_df = new_state["error_df"].to_dict("records")
            return {"success": True, "new-state": new_df}
        else:
            return {"success": True, "new-state": wrangled_df.to_dict("records")}
    except Exception as e:
        return {"success": False, "error": str(e)}
