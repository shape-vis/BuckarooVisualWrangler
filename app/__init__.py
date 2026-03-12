#Buckaroo Project - June 1, 2025
#This file allows the app to use packages for maintainability


#make it able to read the variables from the .env file
import os
import psycopg2
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine
import json

from app.db_functions_sql import DBOperations
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


# Function to create the database if it does not exist
# This function checks if the database exists and creates it if it does not
def create_database_if_not_exists(conn, db_name):
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Check if the database exists
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(f"CREATE DATABASE {db_name}")

    cur.close()


# Function to load database connection information from a JSON file or prompt the user
def load_database_info():
    basepath = os.path.dirname(os.path.abspath(__file__))

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

    return host, port, user, password, db_name



#load the .env file and read the different variables in there and them in the environment variables for this proccess
load_dotenv()

app = Flask(__name__,
            static_folder="../ui/dist",
            static_url_path="/")

#sets the URL to the DB url specified for the local postgresql db on my local machine specified in .env

host, port, user, password, db_name = load_database_info()

"""
we use psycopg2 directly for the initial connection
 but only for the one-time database creation check at startup
"""
connection = psycopg2.connect(host=host, port=port, user=user, password=password)

# Create the database if it does not exist
create_database_if_not_exists(connection, db_name)



"""
 then we use SQLAlchemy (create_engine) for everything else
 this is the engine that gets passed around to fetch_sql, execute_sql, 
 pd.read_sql_query, and .to_sql() throughout routes.py, plot_routes.py, and db_operations.py
"""
print(f"Connecting to database: {db_name}")
engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}")

db_operations = DBOperations(engine)

# Initialize PostgreSQL stored procedures for histogram generation with errors
from app.db_functions import initialize_database_functions
initialize_database_functions(engine)

from app import routes
from app import wrangler_routes_sql as wrangler_routes
from app import plot_routes
#manages the different data instances of the data during the users session
