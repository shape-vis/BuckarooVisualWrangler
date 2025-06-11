import pandas as pd

def missing_value(data_frame):
    """
    goes through each cell in the datatable and checks to see if the cell is
    null, undefined, an empty string, or a null/undefined string
    :param data_frame: the datatable to run the detector on
    :return: a dictionary of structure: { column: { id: errorType } }
    """
    error_map = {}

    #returns a tuple as -> (rows, columns)
    shape = data_frame.shape
    number_of_rows = shape[0]
    number_of_columns = shape[1]

    for column in range(number_of_columns):
        for row in range(number_of_rows):
            data = data_frame.loc[row][column]
            if pd.isnull(data) or str(data) == 'null' or str(data) == 'undefined':
                if column in error_map:
                    error_map[column][row] = "missing"
                else:
                    error_map[column] = {}
                    error_map[column][row] = "missing"

    return error_map