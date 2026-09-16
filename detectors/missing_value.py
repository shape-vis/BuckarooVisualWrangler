from zipfile import error

import pandas as pd
from numpy.ma.core import indices


def missing_mask(values):
    """
    Which cells count as missing: null, or the literal text "null" or "undefined".

    Kept apart from the detector so other code can ask the same question of any values. The distortion
    metric (app/pgraph/distortion.py) leaves out exactly these cells, so it and the Missing metric can never
    disagree about which cells of a column are missing.
    :param values: a DataFrame or a Series
    :return: a boolean mask of the same shape
    """
    as_text = values.astype(str)
    return values.isna() | (as_text == 'null') | (as_text == 'undefined')


def missing_value(data_frame):
    """
    goes through each cell in the datatable and checks to see if the cell is
    null, undefined, an empty string, or a null/undefined string
    :param data_frame: the datatable to run the detector on
    :return: a dictionary of structure: { column: { id: errorType } }
    """
    error_map = {}

    mask = missing_mask(data_frame)
    na_locations = mask.stack()
    missing_coords = na_locations[na_locations].index.tolist()

    for cord in missing_coords:
        if cord[1] not in error_map:
            error_map[cord[1]] = {}
            error_map[cord[1]][int(data_frame.loc[cord[0], 'ID'])] = "missing"
        else: error_map[cord[1]][int(data_frame.loc[cord[0], 'ID'])] = "missing"

    return error_map