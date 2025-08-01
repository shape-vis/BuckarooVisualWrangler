"""
Should calculate the average of a category and apply that on the database on the specified points
"""

import pandas as pd
from typing_extensions import TypeIs


def impute_average_on_ids(column, dataframe, selected_ids):
    #need int for pandas id stuff, so convert it if selected_ids isn't an int
    for i in range(len(selected_ids)):
        selected_ids[i] = int(selected_ids[i])

    selected_ids_set = set(selected_ids)
    column_series = dataframe[column]
    is_numeric = pd.api.types.is_numeric_dtype(column_series)
    if is_numeric:
        column_values = column_series.dropna()
        column_values = column_values[column_values > 0]
        imputed_value = round(column_values.mean(), 1) if len(column_values) > 0 else 0
        print("Avg: ", imputed_value)
    else:
        frequency_counts = column_series.value_counts()
        imputed_value = frequency_counts.index[0]
        print("Computed Categorical Mode: ", imputed_value)
    df_copy = dataframe.copy()
    mask = df_copy['ID'].isin(selected_ids_set)
    df_copy.loc[mask, column] = imputed_value
    return df_copy