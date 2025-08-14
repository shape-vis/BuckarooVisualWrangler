#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding wranglers

from flask import request

from app import app
from app.service_helpers import run_detectors, update_data_state
from wranglers.impute_average import impute_average_on_ids
from wranglers.remove_data import remove_data
from app import data_state_manager

@app.get("/api/wrangle/remove")
def wrangle_remove():
    """
    Should handle when a user sends a request to remove specific data
    :return: result of the wrangle on the data
    """
    point_range_to_return = request.args.get("range")
    points_to_remove = (request.args.get("points"))
    points_to_remove_array = [points_to_remove]
    preview = request.args.get("preview")
    graph_type = request.args.get("graph_type")

    try:
        current_state = data_state_manager.get_current_state()
        current_df = current_state["df"]
        wrangled_df = remove_data(current_df, points_to_remove_array)
        new_error_df = run_detectors(wrangled_df)
        new_state = {"df": wrangled_df, "error_df": new_error_df}
        data_state_manager.push_right_table_stack(new_state)
        if preview == "yes":
            data_state_manager.pop_right_table_stack()
            return {"success": True, "new-state": None}
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


    if not filename:
        return {"success": False, "error": "Filename required"}

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
