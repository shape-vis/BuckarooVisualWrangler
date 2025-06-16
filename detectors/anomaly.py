import numpy as np
import pandas as pd

def anomaly(data_frame):
    """
    determines whether a cell in a column of numeric values has a zscore > 2
    :return:
    """
    error_map = {}

    for column in data_frame.columns[1:]:
        numeric_mask = pd.to_numeric(data_frame[column], errors='coerce').notna()
        if numeric_mask.sum() < 10: continue
        #TODO: this doesn't work when trying to upload any dataset other than the stackoverflow one, it has issues with the to_numeric call as well
        data_frame[[column]] = data_frame[[column]].apply(pd.to_numeric, errors='coerce')
        column_mean = data_frame[[column]].mean().iloc[0]
        column_std = data_frame[[column]].std().iloc[0]

        if column_std == 0 or column_std is None: continue

        anomaly_mask = np.abs((data_frame[column] - column_mean) > 2 * column_std)
        row_locations = anomaly_mask[anomaly_mask].index

        for row in row_locations:
            if column not in error_map:
                error_map[column] = {}
                error_map[column][int(data_frame.loc[row, 'ID'])] = "anomaly"
            else:
                error_map[column][int(data_frame.loc[row, 'ID'])] = "anomaly"
    return error_map

