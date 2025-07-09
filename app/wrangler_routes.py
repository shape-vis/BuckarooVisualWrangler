#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding wranglers

from flask import request

from app import app
from app.service_helpers import run_detectors, update_data_state
from wranglers.impute_average import impute_average_on_ids
from wranglers.remove_data import remove_data
from app import data_state_manager

"""
All these endpoints expected the following input data:
    1. points to wrangle
    2. the filename
    3. selection range of points to return to the view
"""

@app.get("/api/wrangle/remove")
def wrangle_remove():
    """
    Should handle when a user sends a request to remove specific data
    get table from db into df -> delete id's from it -> store as a wrangled table in df
    :return: result of the wrangle on the data
    """
    filename = request.args.get("filename")
    point_range_to_return = request.args.get("range")
    points_to_remove = (request.args.get("points"))
    points_to_remove_array = [points_to_remove]
    preview = request.args.get("preview")
    #these can be used later to set the different ranges the user wants to get data from
    # min_id = request.args.get()point_range_to_return["min"]
    # max_id = point_range_to_return["max"]

    if not filename:
        return {"success": False, "error": "Filename required"}

    #guery to get the selected range of points to return to the view

    try:
        current_state = data_state_manager.get_current_state()
        current_df = current_state["df"]
        #remove the points from the df
        wrangled_df = remove_data(current_df, points_to_remove_array)
        #run the detectors on the new df
        new_error_df = run_detectors(wrangled_df)

        if preview == "no":
            #update the table state of the app
            update_data_state(wrangled_df, new_error_df)
            #the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
            new_state = data_state_manager.get_current_state()
            new_df = new_state["df"].to_dict("records")
            new_error_df = new_state["error_df"].to_dict("records")
            return {"success": True, "new-state": new_df}
        else:
            return {"success": True, "new-state": wrangled_df}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
