from zipfile import error

import pandas as pd
from numpy.ma.core import indices


def missing_value(data_frame):
    """
    goes through each cell in the datatable and checks to see if the cell is
    null, undefined, an empty string, or a null/undefined string
    :param data_frame: the datatable to run the detector on
    :return: a dictionary of structure: { column: { id: errorType } }
    """
    error_map = {}

    mask = data_frame.isna() | (data_frame.astype(str) == 'null') | (data_frame.astype(str) == 'undefined')
    na_locations = mask.stack()
    missing_coords = na_locations[na_locations].index.tolist()

    for cord in missing_coords:
        if cord[1] not in error_map:
            error_map[cord[1]] = {}
            error_map[cord[1]][cord[0]] = "missing"
        else: error_map[cord[1]][cord[0]] = "missing"

    return error_map