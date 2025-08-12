#Buckaroo Project - June 1, 2025
#This file allows the app to use packages for maintainability


#make it able to read the variables from the .env file
import os
import psycopg2
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine
import json

from data_management.data_state import DataState
# from data_management.data_integration import *

basepath = os.path.dirname(os.path.abspath(__file__))

#load the .env file and read the different variables in there and them in the environment variables for this proccess
load_dotenv()

app = Flask(__name__)
#sets the URL to the DB url specified for the local postgresql db on my local machine specified in .env

if os.path.exists(basepath + "/database.json"):
    with open(basepath + "/database.json", "r") as f:
        db_info = json.loads(f.read())
        host = db_info["host"]
        port = db_info["port"]
        user = db_info["user"]
        password = db_info["password"]
        db_name = db_info["db_name"]
else:
    print("database.json file not found, using default connection parameters.")
    print("Enter the host of the database (default: localhost): ")
    host = input() or "localhost"
    print("Enter the port of the database (default: 5432): ")
    port = input() or 5432
    print("Enter the user of the database (default: postgres): ")
    user = input() or "postgres"
    print("Enter the password of the database: ")
    password = input()
    print("Enter the name of the database (default: buckaroo_db): ")
    db_name = input() or "buckaroo_db"
    with open(basepath + "/database.json", "w") as f:
        db_info = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "db_name": db_name
        }
        f.write(json.dumps(db_info, indent=4))

# connection = psycopg2.connect(host=host, port=port, user=user, password=password)
connection = psycopg2.connect(host=host, port=port, user=user, password=password, database=db_name)
data_state_manager = DataState()

#engine to use pandas with the db
engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}")

from app import routes
from app import wrangler_routes
from app import plot_routes
from app import db_plot_routes
#manages the different data instances of the data during the users session
