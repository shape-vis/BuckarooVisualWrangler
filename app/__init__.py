#Buckaroo Project - June 1, 2025
#This file allows the app to use packages for maintainability


#make it able to read the variables from the .env file
import os
import psycopg2
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine

from data_management.data_state import DataState
# from data_management.data_integration import *


#load the .env file and read the different variables in there and them in the environment variables for this proccess
load_dotenv()

app = Flask(__name__)
#sets the URL to the DB url specified for the local postgresql db on my local machine specified in .env
url = os.getenv("DATABASE_URL")
#a connection to the db, can use to insert or read data from the db
connection = psycopg2.connect(url)
data_state_manager = DataState()

#engine to use pandas with the db
engine = create_engine(url)

from app import routes
from app import wrangler_routes
from app import plot_routes
#manages the different data instances of the data during the users session
