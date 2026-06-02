#Buckaroo Project - June 1, 2025
#This file allows the app to use packages for maintainability


#make it able to read the variables from the .env file
import builtins
import logging
import os
import pkgutil

import psycopg2
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine
import json


#This is so that that whatever we print in the server comes out blue in the terminal
_original_print = builtins.print
def _blue_print(*args, **kwargs):
    _original_print('\033[94m' + ' '.join(str(a) for a in args) + '\033[0m', **kwargs)
builtins.print = _blue_print


#This is so that endpoint calls in the server are always white, only errors are red now
class _WhiteFormatter(logging.Formatter):
    def format(self, record):
        return '\033[97m' + super().format(record) + '\033[0m'

_werkzeug_handler = logging.StreamHandler()
_werkzeug_handler.setFormatter(_WhiteFormatter('%(message)s'))
logging.getLogger('werkzeug').handlers = [_werkzeug_handler]

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

# Tests set BUCKAROO_SKIP_DB_INIT=1 so importing Flask routes does not require
# a live local Postgres database. Normal app runs leave this unset.
skip_db_init = os.environ.get("BUCKAROO_SKIP_DB_INIT") == "1"

if skip_db_init:
    engine = None
    db_operations = None
else:
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

    from app.db_utils.db_functions_sql import DBOperations
    db_operations = DBOperations(engine)

# Global vars to use throughout one browser session.
wrangle_occurred = False
# pgraph_for_session is filled after upload/preloaded dataset load. It stores
# the table-version graph used for undo/redo and Pandas export.
pgraph_for_session = None
# original_table_name is used by export so the generated script starts from the
# same CSV the user loaded in the UI.
original_table_name = "data.csv"

if not skip_db_init:
    #this automatically imports any new route files added to the app/routes dir
    import app.routes as _routes_pkg
    for _, module_name, _ in pkgutil.iter_modules(_routes_pkg.__path__):
        __import__(f"app.routes.{module_name}")


