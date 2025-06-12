import numpy as np
import pandas as pd

def anomaly(data_frame):
    """
    determines whether a cell in a column of numeric values has a zscore > 2
    :return:
    """
    error_map = {}

    # returns a tuple as -> (rows, columns)
    shape = data_frame.shape
    number_of_rows = shape[0]
    number_of_columns = shape[1]

    for column in range(number_of_columns):
        #gets the count of numbers in the column
        numeric_count = pd.to_numeric(data_frame[column], errors='coerce').notna().sum()
        if numeric_count > 10:
            mean_for_column = data_frame[column].mean()
            std_dev_for_column = data_frame[column].std()
            if std_dev_for_column is None or std_dev_for_column == 0:
                continue
            for row in range(number_of_rows):
                continue


            # for row in range(number_of_rows):
            #     data = data_frame.loc[row][column]
            #     if pd.isnull(data) or str(data) == 'null' or str(data) == 'undefined':
            #         if column in error_map:
            #             error_map[column][row] = "missing"
            #         else:
            #             error_map[column] = {}
            #             error_map[column][row] = "missing"

    return error_map
