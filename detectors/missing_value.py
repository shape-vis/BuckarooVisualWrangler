import pandas as pd


def missing_value(data_frame):
    """
    goes through each cell in the datatable and checks to see if the cell is
    null, undefined, an empty string, or a null/undefined string
    :param data_frame: the datatable to run the detector on
    :return: a dictionary of structure: { column: { id: errorType } }
    """
    error_map = {}

    normalized = data_frame.astype(str).apply(lambda column: column.str.strip().str.lower())
    mask = (
        data_frame.isna()
        | normalized.eq("")
        | normalized.eq("null")
        | normalized.eq("undefined")
    )
    na_locations = mask.stack()
    missing_coords = na_locations[na_locations].index.tolist()

    for cord in missing_coords:
        if cord[1] not in error_map:
            error_map[cord[1]] = {}
            error_map[cord[1]][int(data_frame.loc[cord[0], 'ID'])] = "missing"
        else: error_map[cord[1]][int(data_frame.loc[cord[0], 'ID'])] = "missing"

    return error_map
