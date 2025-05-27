#make it able to read the variables from the .env file
import datetime
import os
from time import timezone
import psycopg2
from dotenv import load_dotenv
from flask import Flask, request

#basic REST POST AND GET queries

# to create a new table for a new room in the "house"
CREATE_ROOMS_TABLE = (
    "CREATE TABLE IF NOT EXISTS rooms (id SERIAL PRIMARY KEY, name TEXT);"
)

# to create a new table for a new temperature recorded in the "house", 
# This uses a FOREIGN KEY constraint to link the table to the rooms table. All this does 
# is ensure referential integrity (i.e. can't enter a room_id for a room that doesn't exist). 
# Also using ON DELETE CASCADE means that if we delete a room, all its referenced temperatures will be deleted too.
CREATE_TEMPS_TABLE = """CREATE TABLE IF NOT EXISTS temperatures (room_id INTEGER, temperature REAL, 
                        date TIMESTAMP, FOREIGN KEY(room_id) REFERENCES rooms(id) ON DELETE CASCADE);"""

INSERT_TEMP = (
    "INSERT INTO temperatures (room_id, temperature, date) VALUES (%s, %s, %s);"
)

#to insert data we'll use the below, We'll get this query to return the id column that was inserted, so that we can send it back to the client of our API.
#That way they can use the id in subsequent requests to insert temperatures related to the new room:"
INSERT_ROOM_RETURN_ID = "INSERT INTO rooms (name) VALUES (%s) RETURNING id;"

#load the .env file and read the different variables in there and but them in the environment variables for this proccess
load_dotenv()

app = Flask(__name__)
#sets the URL to the DB url specified for the local postgresql db on my local machine specified in .env
url = os.getenv("DATABASE_URL")
#a connection to the db, can use to insert or read data from the db
connection = psycopg2.connect(url)

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

@app.post("/api/temperature")
def add_temp():
    # For this, we'd expect the client to send a request that contains the temperature reading and the room id.
    data = request.get_json()
    temperature = data["temperature"]
    room_id = data["room"]
    # If the date is provided, use it. Otherwise use the current date.
    try:
        date = datetime.strptime(data["date"], "%m-%d-%Y %H:%M:%S")
    except KeyError:
        date = datetime.now(timezone.utc)
    with connection:
        with connection.cursor() as cursor:
            #Create a table for the temperatures if not already existing
            cursor.execute(CREATE_TEMPS_TABLE)
            #Insert the temperature reading into the table.
            cursor.execute(INSERT_TEMP, (room_id, temperature, date))
    return {"message": "Temperature added."}, 201


@app.get("/")
def home():
    return "Testing the get request"