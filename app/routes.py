#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import numpy as np
import pandas as pd
from flask import request, send_file
import time
from app import app, db_operations, engine
from app.service_helpers import (
    generate_table_name,
    get_sqlalchemy_dtype_map,
    refresh_errors_table,
    refresh_rankings_table,
)
from app.set_id_column import set_id_column
import json


def load_file(csv_file, filename):
    """
    This loads the csv from the local path of the repo that the user clicked;
    set's IDs to each row,
    puts the whole csv into a Pandas Dataframe,
    runs the python detectors the dataframe,
    generates a unique name for the table,
    and returns a JSON object of all the info.

    :param csv_file: the local csv to use
    :param filename: the name of the csv_file
    :return: json object
    """
    try:
        # Load in the initial dataframe.
        table_name = generate_table_name(filename)
        dataframe = pd.read_csv(csv_file)

        table_with_id_added = set_id_column(dataframe)
        dtype_map = get_sqlalchemy_dtype_map(table_with_id_added)
        table_with_id_added.to_sql(table_name, engine, if_exists='replace', dtype=dtype_map)
        detected_rows_affected = refresh_errors_table(
            table_name,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )
        refresh_rankings_table(
            table_name,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )

        """
        now we fully init the DBOperations object that was first initialized in init.py,
        get the actual row counts since .to_sql is buggy and not right
        """
        db_operations.load_table(table_name)
        rows_affected = db_operations.get_row_count(table_name)
        detected_rows_affected = db_operations.get_row_count("errors_" + table_name)

        return {"success": True, "rows for undetected data": rows_affected, "rows_for_detected": detected_rows_affected,
                "table_name": table_name}
    except Exception as e:
        print(f"Error in upload: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/upload")
def upload_csv():
    """
    Handles when a user uploads a csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    #get the file path from the DataFrame object sent by the user's upload in the view
    csv_file = request.files['file']
    return load_file(csv_file, csv_file.filename)


@app.get("/api/preloaded")
def preloaded_csv():
    """
    Handles when a user wants to use a preloaded csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    #get the file name from request args
    csv_file = request.args.get("file")
    csv_file = csv_file[csv_file.rfind("/") + 1:]

    return load_file("provided_datasets/" + csv_file, csv_file)


@app.post("/api/reset")
def reset_app():
    """
    Resets the server-side DBOperations state when the user navigates back to the home page.
    """
    db_operations.reset()
    return {"success": True}


@app.get("/")
def home():
    return send_file("../ui/dist/index.html")
