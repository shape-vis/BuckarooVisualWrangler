#Buckaroo Project - June 1, 2025
#This file allows the app to use packages for maintainability

import builtins
import json
import logging
import os
import pkgutil

import psycopg2
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import URL, create_engine

from app.db_utils.bootstrap import create_database_if_not_exists


#This is so that that whatever we print in the server comes out blue in the terminal
_original_print = builtins.print
def _blue_print(*args, **kwargs):
    words = []
    for arg in args:
        words.append(str(arg))
    _original_print('\033[94m' + ' '.join(words) + '\033[0m', **kwargs)
builtins.print = _blue_print


#This is so that endpoint calls in the server are always white, only errors are red now
class _WhiteFormatter(logging.Formatter):
    def format(self, record):
        return '\033[97m' + super().format(record) + '\033[0m'

_werkzeug_handler = logging.StreamHandler()
_werkzeug_handler.setFormatter(_WhiteFormatter('%(message)s'))
logging.getLogger('werkzeug').handlers = [_werkzeug_handler]

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



# Read the variables in the .env file into this process's environment
load_dotenv()

app = Flask(__name__,
            static_folder="../ui/dist",
            static_url_path="/")

host, port, user, password, db_name = load_database_info()

# psycopg2 directly, only for the one-time check at startup that the database exists
connection = psycopg2.connect(host=host, port=port, user=user, password=password)
create_database_if_not_exists(connection, db_name)

# SQLAlchemy for everything else: this engine is what fetch_sql, execute_sql, pd.read_sql_query and .to_sql()
# are handed throughout the app
print(f"Connecting to database: {db_name}")

# The connection pool is sized for the server's worker threads at full tilt - 8 query workers and 4 node builds,
# see app/server_utils/workers.py - plus the requests the threaded dev server is serving at the same moment.
# SQLAlchemy's default of 5 would leave the workers queueing for connections.
#
# Every connection also gets more working memory than Postgres' default of 4MB. Error detection, drift and the
# compare plots sort and hash whole columns, and at 4MB a quarter-million-row column spills to disk part way.
WORK_MEM = "64MB"

# URL.create rather than a formatted string, so a password holding "@" or "/" still reads as a password
database_url = URL.create("postgresql+psycopg2", username=user, password=password, host=host, port=int(port),
                          database=db_name)
engine = create_engine(database_url,
                       pool_size=16, max_overflow=8,
                       connect_args={"options": f"-c work_mem={WORK_MEM}"})

from app.db_utils.db_functions_sql import DBOperations
db_operations = DBOperations(engine)

# The session's provenance graph - a PGraph once a file has been uploaded, None until then. It lives on the app
# package, which is what every module reads it from: read it through service_helpers.session_graph.
pgraph_for_session = None

#this automatically imports any new route files added to the app/routes dir
import app.routes as _routes_pkg
for _, module_name, _ in pkgutil.iter_modules(_routes_pkg.__path__):
    __import__(f"app.routes.{module_name}")


