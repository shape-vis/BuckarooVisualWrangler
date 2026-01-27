#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import numpy as np
import pandas as pd
from flask import request, render_template, send_file
import time
from app import app
from app import connection, engine
from app.service_helpers import generate_table_name, get_whole_table_query, run_detectors, create_error_dict, \
    init_session_data_state, fetch_detected_and_undetected_current_dataset_from_db, calculate_attribute_rankings
from app import data_state_manager
from app.set_id_column import set_id_column
import json
import random
import string

def load_file(csv_file, filename):
    dataframe = pd.read_csv(csv_file)

    # run the detectors on the uploaded file for the starting data state
    table_with_id_added = set_id_column(dataframe)
    start_time = time.time()
    detected_data = run_detectors(dataframe)
    time_to_detect = time.time() - start_time

    table_name = generate_table_name(filename)

    json.dump({'table': table_name, "clean_time": time_to_detect, "dataframe_shape": list(detected_data.shape)}, open(f"report/{table_name}.json", "w"))

    try:
        #insert the undetected dataframe
        rows_inserted = table_with_id_added.to_sql(table_name, engine, if_exists='replace')
        detected_rows_inserted = detected_data.to_sql(table_name+"_errors", engine, if_exists='replace')

        # Calculate and store attribute rankings
        rankings = calculate_attribute_rankings(detected_data)
        rankings.to_sql(table_name+"_rankings", engine, if_exists='replace', index=False)

        return{"success": True, "rows for undetected data": rows_inserted, "rows_for_detected": detected_rows_inserted, "table_name": table_name}
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


@app.get("/")
def home():
    # return render_template('ui/dist/index.html')
    return send_file("../ui/dist/index.html")

