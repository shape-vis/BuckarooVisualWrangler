#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding wranglers

import numpy as np
import pandas as pd
from flask import request, render_template

from app import app
from app import connection, engine
from app.service_helpers import run_detectors, update_data_state
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
    point_range_to_return = request.args.get("range_to_return")
    points_to_remove = request.args.get("points_to_wrangle")

    #these can be used later to set the different ranges the user wants to get data from
    min_id = point_range_to_return["min"]
    max_id = point_range_to_return["max"]

    if not filename:
        return {"success": False, "error": "Filename required"}

    #guery to get the selected range of points to return to the view

    try:

        #remove the points from the df
        wrangled_df = remove_data(data_state_manager.get_current_table()["df"], points_to_remove)
        #run the detectors on the new df
        new_error_df = run_detectors(wrangled_df)

        #update the table state of the app
        update_data_state(wrangled_df, new_error_df)

        return {"success": True, "new-state":data_state_manager.get_current_state()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/wrangle/remove-preview")
def wrangle_remove_preview():
    """
    Should handle when a user wants a preview of a remove wrangle
    :return: new data after the wrangle
    """
    pass

@app.get("/api/wrangle/impute")
def wrangle_impute():
    """
    Should handle when a user sends a request to impute specific data
    :return: result of the wrangle on the data
    """
    pass

@app.get("/api/wrangle/impute-preview")
def wrangle_impute_preview():
    """
    Should handle when a user wants a preview of an impute wrangle
    :return: hypothetical result of the wrangle on the data
    """
    pass