#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding plots

import numpy as np
import pandas as pd
from flask import request, render_template

from app import app
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict



@app.get("/api/plots/1-d-histogram-data")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view, this endpoint expects the following parameters:
        1. tablename to pull data from
        2. column name to aggregate data for
        3. desired id min and max values of the table to return to the view
    :return: the data as a csv
    """
    pass

@app.get("/api/plots/2-d-histogram-data")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view - user will pass in parameters for the axis that is filled in
    :return: the data as a csv
    """
    pass

#add endpoints for the scatterplots and also to have min max ranges for the numerical value and lists of values for categorical


@app.get("/api/plots/group-by")
def get_group_by():
    """
    Endpoint to return the data according to the specified categorical data the user wishes to group an attribute by - ex. group ages by continent
    :return: the data as a csv
    """
    pass

@app.get("/api/plots/undo")
def undo():
    """
    Undoes the previous action performed on the data
    :return:
    """
    pass

@app.get("/api/plots/redo")
def redo():
    """
    Redoes the previous action performed on the data
    :return:
    """
    pass

@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries
    :return:
    """
