#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end



from datetime import timezone, datetime
from venv import create

import numpy as np
from flask import request, render_template
import pandas as pd
from sqlalchemy import false

from app import connection, engine
from app import app
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict


#this endpoint is just for reference of how to use a cursor object if not using pandas
#We tell Flask what endpoint to accept data in using a decorator (@)
@app.post("/api/room")
def create_room():
    #We expect the client to send us JSON data, 
    # which we retrieve from the incoming request using request.get_json().
    data = request.get_json()
    name = data["name"]
    with connection:
        # We connect to the database and use a cursor to interact with it. 
        # Here we use context managers so we don't have to remember to close the connection manually.
        with connection.cursor() as cursor:
            # We create the table (since it only runs IF NOT EXISTS), and insert the record.
            cursor.execute(CREATE_ROOMS_TABLE)
            cursor.execute(INSERT_ROOM_RETURN_ID, (name,))
            #We get the result of running our query, which should be the inserted row id.
            room_id = cursor.fetchone()[0]
    # We return a Python dictionary, which Flask conveniently converts to JSON.
    # The return status code is 201, which means "Created". 
    # It's a way for our API to tell the client succinctly the status of the request.        
    return {"id": room_id, "message": f"Room {name} created."}, 201

@app.post("/api/upload")
def upload_csv():
    """
    Handles when a user uploads a csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    #get the file path from the DataFrame object sent by the user's upload in the view
    csv_file = request.files['file']
    #parse the file into a csv using pandas
    dataframe = pd.read_csv(csv_file)
    # file_errors = run_detectors(dataframe)
    detected_data = run_detectors(dataframe)

    cleaned_table_name = clean_table_name(csv_file.filename)

    try:
        #insert the undetected dataframe
        rows_inserted = dataframe.to_sql(cleaned_table_name, engine, if_exists='replace')
        detected_rows_inserted = detected_data.to_sql("errors"+cleaned_table_name, engine, if_exists='replace')
        return{"success": True, "rows for undetected data": rows_inserted, "rows_for_detected": detected_rows_inserted}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/get-sample")
def get_sample():
    """
    Constructs a postgresql query to get the undetected table data from the database
    :return: a dictionary of the table dataa
    """
    filename = request.args.get("filename")
    data_size = request.args.get("datasize")
    cleaned_table_name = clean_table_name(filename)
    if not filename:
        return {"success": False, "error": "Filename required"}
    QUERY = get_whole_table_query(cleaned_table_name,False) + " LIMIT "+ data_size
    try:
        # sample_dataframe = pd.read_sql_query(QUERY, engine).to_dict(orient="records")
        sample_dataframe_as_dictionary = pd.read_sql_query(QUERY, engine).replace(np.nan, None).to_dict(orient="records")
        # print("First row:", sample_dataframe_as_dictionary[0])  # See what keys exist
        return sample_dataframe_as_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/get-errors")
def get_errors():
    """
    Constructs a postgresql query to get the error table corresponding to the current file from the database
    :return: a dictionary of the error table
    """
    filename = request.args.get("filename")
    data_size = request.args.get("datasize")
    data_size_int = int(data_size)
    cleaned_table_name = clean_table_name(filename)
    if not filename:
        return {"success": False, "error": "Filename required"}
    query = get_whole_table_query(cleaned_table_name,True)
    try:
        full_error_df = pd.read_sql_query(query, engine)
        print("error_df from db: ",full_error_df)
        data_sized_error_dictionary = create_error_dict(full_error_df,data_size_int)
        print(data_sized_error_dictionary)
        return data_sized_error_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/")
def home():
    return render_template('index.html')

@app.get('/data_cleaning_vis_tool')
def data_cleaning_vis_tool():
    return render_template('data_cleaning_vis_tool.html')