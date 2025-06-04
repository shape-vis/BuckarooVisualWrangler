#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end



from datetime import timezone, datetime
from flask import request, render_template
import pandas as pd
from app import connection, engine
from app import app
from app.service_helpers import clean_table_name, get_whole_table_query

# to create a new table for a new room in the "house"
CREATE_ROOMS_TABLE = ("CREATE TABLE IF NOT EXISTS rooms (id SERIAL PRIMARY KEY, name TEXT);")
GET_ALL_INFO = "SELECT * FROM courses;"

#to insert data we'll use the below, We'll get this query to return the id column that was inserted, so that we can send it back to the client of our API.
#That way they can use the id in subsequent requests to insert temperatures related to the new room:
INSERT_ROOM_RETURN_ID = "INSERT INTO rooms (name) VALUES (%s) RETURNING id;"

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
    cleaned_table_name = clean_table_name(csv_file.filename)
    try:
        rows_inserted = dataframe.to_sql(cleaned_table_name, engine, if_exists='replace')
        return{"success": True, "rows": rows_inserted}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/get-sample")
def get_sample():
    filename = request.args.get("filename")
    cleaned_table_name = clean_table_name(filename)
    if not filename:
        return {"success": False, "error": "Filename required"}
    QUERY = get_whole_table_query(cleaned_table_name)
    try:
        sample_dataframe = pd.read_sql_query(QUERY, engine).to_dict(orient="records")
        return sample_dataframe
    except Exception as e:
        return {"success": False, "error": str(e)}


#not getting all
@app.get("/api/all")
def get_all():
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(GET_ALL_INFO)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            all = [dict(zip(columns,row)) for row in rows]
    return {"all":all, "desc[0]":columns[0],"desc[1]":columns[1],"desc[2]":columns[2],"desc[3]":columns[3],"desc[4]":columns[4]}

@app.get("/")
def home():
    return render_template('index.html')

@app.route('/data_cleaning_vis_tool')
def data_cleaning_vis_tool():
    return render_template('data_cleaning_vis_tool.html')