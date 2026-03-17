#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import numpy as np
import pandas as pd
from flask import request, render_template, send_file
import time
from app import app, db_operations
from app import connection, engine
from app.service_helpers import *
from app.set_id_column import set_id_column
import json
import random
import string

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
    dataframe = pd.read_csv(csv_file)

    # run the detectors on the uploaded file for the starting data state
    table_with_id_added = set_id_column(dataframe)
    start_time = time.time()
    detected_data = run_detectors(dataframe)
    time_to_detect = time.time() - start_time

    table_name = generate_table_name(filename)

    # Build dtype map from actual column values before pushing to DB
    dtype_map = get_sqlalchemy_dtype_map(table_with_id_added)

    # json.dump({'table': table_name, "clean_time": time_to_detect, "dataframe_shape": list(detected_data.shape)}, open(f"report/{table_name}.json", "w"))

    try:
        """
        pulled from the Pandas Docs for reference because these values returned by .to_sql is not the actual numbers:

        https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_sql.html

        The number of returned rows affected is the sum of the rowcount attribute of sqlite3.Cursor or SQLAlchemy
        connectable which may not reflect the exact number of written rows as stipulated in the sqlite3 or SQLAlchemy.
        """
        rows_affected = table_with_id_added.to_sql(table_name, engine, if_exists='replace',dtype=dtype_map)
        detected_rows_affected = detected_data.to_sql("errors_"+table_name, engine, if_exists='replace')

        """
        now we fully init the DBOperations object that was first initialized in init.py,
        get the actual row counts since .to_sql is buggy and not right
        """
        db_operations.load_table(table_name)
        rows_affected = db_operations.get_row_count(table_name)
        detected_rows_affected = db_operations.get_row_count("errors_" + table_name)

        #calculate the attribute rankings for the top 10 error rows table on the Buckaroo.tsx page
        rankings = calculate_attribute_rankings(detected_data)
        rankings.to_sql("rankings_"+table_name, engine, if_exists='replace', index=False)

        return{"success": True, "rows for undetected data": rows_affected, "rows_for_detected": detected_rows_affected, "table_name": table_name}
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



@app.get("/api/get-sample")
def get_sample():
    """
    Constructs a postgresql query to get the undetected table data from the database
    :return: a dictionary of the table dataa
    """
    data_size = request.args.get("datasize")
    table_name = request.args.get("table_name")

    if not table_name:
        return {"success": False, "error": "Table name required"}

    QUERY = get_whole_table_query(table_name,False) + " LIMIT "+ data_size
    try:
        fetch_detected_and_undetected_current_dataset_from_db(table_name,engine)
        # sample_dataframe = pd.read_sql_query(QUERY, engine).to_dict(orient="records")
        sample_dataframe_as_dictionary = pd.read_sql_query(QUERY, engine).replace(np.nan, None).to_dict(orient="records")
        # print("First row:", sample_dataframe_as_dictionary[0])  # See what keys exist
        return sample_dataframe_as_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/get-errors")
def get_errors():
    """
    Constructs a postgresql query to get the error table corresponding to the current table from the database
    :return: a dictionary of the error table
    """
    data_size = request.args.get("datasize")
    data_size_int = int(data_size)
    table_name = request.args.get("table_name")

    if not table_name:
        return {"success": False, "error": "Table name required"}
    query = get_whole_table_query(table_name,True)
    try:
        full_error_df = pd.read_sql_query(query, engine)
        data_sized_error_dictionary = create_error_dict(full_error_df,data_size_int)
        return data_sized_error_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/reset")
def reset_app():
    """
    Resets the server-side DBOperations state when the user navigates back to the home page.
    """
    db_operations.reset()
    return {"success": True}


@app.get("/")
def home():
    # return render_template('ui/dist/index.html')
    return send_file("../ui/dist/index.html")

