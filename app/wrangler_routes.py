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
import traceback
from postgres_wrangling import dataframe_store
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
@app.post("/api/wrangle/remove/pandas")
def wrangle_remove_pandas():
    """
    Should handle when a user sends a request to remove specific data
    get table from db into df -> delete id's from it -> store as a wrangled table in df
    :return: result of the wrangle on the data
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

        current_df = dataframe_store.get_dataframe()
        print("current_df.shape: ", current_df.shape)
        wrangled_df, dropped_rows = query.remove_anomalous_rows(currentSelection, cols, current_df)
        # wrangled_df, dropped_rows = query.remove_anomalous_rows(current_df)
        print("wrangled_df.shape: ", wrangled_df.shape)
        dataframe_store.set_dataframe(wrangled_df)
        
        return {"success": True, "new_table_name": query.new_table_name(table)}
    except Exception as e:
        print("ERROR OCCURED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}
    
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


@app.post("/api/wrangle/impute/pandas")
def wrangle_impute_pandas():
    """
    Should handle when a user sends a request to impute specific data
    :return: result of the wrangle on the data
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

        current_df = dataframe_store.get_dataframe()
        points_to_remove_array = query.copy_and_impute_bin_df(
            current_selection=currentSelection,
            cols=cols,
            df=current_df
        )
        print(f"points to remove: {points_to_remove_array}")
        # remove the points from the df
        wrangled_df = query.impute_at_indices_copy(df=current_df, cols=cols, row_indices=points_to_remove_array)

        dataframe_store.set_dataframe(wrangled_df)
        # run the detectors on the new df
        new_error_df = run_detectors(wrangled_df)

        # update the table state of the app
        update_data_state(wrangled_df, new_error_df)
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        new_state = data_state_manager.get_current_state()
        new_df = new_state["df"].to_dict("records")
        new_error_df = new_state["error_df"].to_dict("records")

        return {"success": True, "new_table_name": query.new_table_name(table)}
    except Exception as e:
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}

# @app.get("/api/wrangle/impute")
# def wrangle_impute():
#     """
#     Should handle when a user sends a request to impute specific data
#     :return: result of the wrangle on the data
#     """
#     body             = request.get_json(force=True)  # or omit force=True if you prefer 415 on bad content-type
#     currentSelection = body["currentSelection"]
#     cols   = body["cols"]
#     table            = body["table"]

#     print("current selection:")
#     pprint(currentSelection)
#     print("cols:")
#     pprint(cols)
#     print("table:", table)

#     new_table_name = query.new_table_name(table)

#     # guery to get the selected range of points to return to the view

#     row_count = query.copy_and_impute_bin(current_selection=currentSelection, cols=cols, table=table, new_table_name=new_table_name)
#     json.dump({"row_count": row_count}, open("imputed_data_count/impute.json", "w"))

#     try:
#         return {"success": True, "new_table_name": new_table_name, "affected_row_count": row_count}
#     except Exception as e:
#         return {"success": False, "error": str(e)}
