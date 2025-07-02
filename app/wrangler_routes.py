#Buckaroo Project - July 2, 2025
#This file handles all endpoints surrounding wranglers

import numpy as np
import pandas as pd
from flask import request, render_template

from app import app
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict

"""
All these endpoints expected the following input data:
    1. points to wrangle
    2. the filename
    3. selection range of points to return to the view
"""
@app.get("/api/wrangle/remove")
def wrangle_remove():
    """
    Should handle when a user sends a request to remove specific data
    :return: result of the wrangle on the data
    """
    pass

@app.get("/api/wrangle/remove-preview")
def wrangle_remove_preview():
    """
    Should handle when a user wants a preview of a remove wrangle
    :return: new data after the wrangle
    """
    pass

@app.get("/api/wrangle/impute")
def wrangle_impute():
    """
    Should handle when a user sends a request to impute specific data
    :return: result of the wrangle on the data
    """
    pass

@app.get("/api/wrangle/impute-preview")
def wrangle_impute_preview():
    """
    Should handle when a user wants a preview of an impute wrangle
    :return: hypothetical result of the wrangle on the data
    """
    pass