import numpy as np
import pandas as pd

def anomaly(data_frame, include_skipped=False):
    """
    determines whether a cell in a column of numeric values has a zscore > 2
    :return:
    """
    error_map = {}
    skipped_columns = {}

    for column in data_frame.columns[1:]:
        # Skip the ID column by starting at columns[1:]. For every other
        # column, try to convert values to numbers. Non-numeric values become
        # NaN and are ignored by mean/std calculations.
        numeric_mask = pd.to_numeric(data_frame[column], errors='coerce').notna()
        numeric_count = int(numeric_mask.sum())
        if numeric_count < 10:
            # With very few numeric values, mean/std based anomaly detection is
            # too unstable, so the detector records why it skipped the column.
            skipped_columns[column] = {
                "reason": "fewer_than_10_numeric_values",
                "numeric_count": numeric_count,
            }
            continue
        numeric_col = pd.to_numeric(data_frame[column], errors='coerce')
        column_mean = numeric_col.mean()
        column_std = numeric_col.std()

        if column_std == 0 or column_std is None:
            # If all values are the same, std is zero and no z-score cutoff can
            # be computed safely.
            skipped_columns[column] = {
                "reason": "zero_or_missing_standard_deviation",
                "numeric_count": numeric_count,
            }
            continue

        # A value is anomalous when it is more than two standard deviations
        # away from the column mean.
        anomaly_mask = np.abs(numeric_col - column_mean) > 2 * column_std
        row_locations = anomaly_mask[anomaly_mask].index

        for row in row_locations:
            # The tests assert row IDs, not DataFrame positions. That is why we
            # look up data_frame.loc[row, 'ID'] before writing the error map.
            if column not in error_map:
                error_map[column] = {}
                error_map[column][int(data_frame.loc[row, 'ID'])] = "anomaly"
            else:
                error_map[column][int(data_frame.loc[row, 'ID'])] = "anomaly"
    if include_skipped:
        return {
            "errors": error_map,
            "skipped": skipped_columns,
        }
    return error_map

def anomaly_sql(table_name: str, err_table_name: str) -> str:
    """
    determines whether a cell in a column of numeric values has a zscore > 2
    :return: the CTEs for the anomaly table.
    """

    query = f''''''

