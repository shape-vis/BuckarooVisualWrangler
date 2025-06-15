#Buckaroo Project - June 1, 2025
#This file helps deliver on services the server provides

import re

import pandas as pd

from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value


def clean_table_name(csv_name):
    """
    Cleans the file name so that it is ready to be used to make a table in the database, it needs to:
    - Remove file extension (.csv), replace spaces/special chars with underscores, ensure it starts with a letter (SQL requirement)
    :param csv_name: csv name from user upload
    :return: cleaned name without
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name)
    if not clean_name[0].isalpha():
        clean_name = 'table' + clean_name
    return clean_name.lower()

def get_whole_table_query(table_name):
    name = clean_table_name(table_name)
    query = f"SELECT * FROM {name}"
    return query

def run_detectors(data_frame):
    """
    Runs all 4 detectors on the data and returns a dataframe of the complete errors
    :param data_frame:
    :return:
    """
    anomaly_df = pd.DataFrame(anomaly(data_frame)).rename_axis("ID", axis="index").reset_index()
    incomplete_df = pd.DataFrame(incomplete(data_frame)).rename_axis("ID", axis="index").reset_index()
    missing_value_df = pd.DataFrame(missing_value(data_frame)).rename_axis("ID", axis="index").reset_index()
    datatype_mismatch_df = pd.DataFrame(datatype_mismatch(data_frame)).rename_axis("ID", axis="index").reset_index()
    frames = [incomplete_df, missing_value_df,datatype_mismatch_df]

    result = anomaly_df.copy()
    for df in frames:
        result = result.merge(df, on='ID', how='outer', suffixes=('', '_temp'))
    for col in result.columns:
        col_temp = col+'_temp'
        if col != 'ID' and col_temp in result.columns:
            both_exist = ~result[col].isna() & ~result[col + '_temp'].isna()
            result.loc[both_exist, col] = result.loc[both_exist, col] + ',' + result.loc[both_exist, col + '_temp']
            result = result.drop(columns=[col + '_temp'])

    return result



