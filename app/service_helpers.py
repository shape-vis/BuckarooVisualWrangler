#Buckaroo Project - June 1, 2025
#This file helps deliver on services the server provides

import re

import pandas as pd

from app.set_id_column import set_id_column
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

def get_whole_table_query(table_name, get_errors):
    name = clean_table_name(table_name)
    if get_errors:
        query = f"SELECT * FROM errors{name}"
        return query
    query = f"SELECT * FROM {name}"
    return query

def get_values_for_df_melt(df):
  values = []
  columns = df.columns
  for column in columns:
    if column not in ('ID', "Unnamed: 0", "column_id","error_type","row_id"):
      values.append(column)
  return values

def perform_melt(dfs):
  df_combined = pd.DataFrame()
  for df in dfs:
    melted_df = pd.melt(df, id_vars='ID', value_vars=get_values_for_df_melt(df))
    melted_df.rename(columns={'ID': 'row_id','variable':'column_id','value':'error_type'}, inplace=True)
    df_combined = pd.concat([df_combined,melted_df])
  nan_mask = df_combined['error_type'].isna()
  df_combined = df_combined[~nan_mask]
  df_combined.reset_index(drop=True, inplace=True)

  return df_combined

def run_detectors(data_frame):
    """
    Runs all 4 detectors on the data and returns a dataframe of the complete errors
    :param data_frame:
    :return:
    """
    df_with_id = set_id_column(data_frame)
    anomaly_df = pd.DataFrame(anomaly(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    incomplete_df = pd.DataFrame(incomplete(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    missing_value_df = pd.DataFrame(missing_value(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    datatype_mismatch_df = pd.DataFrame(datatype_mismatch(df_with_id.copy())).rename_axis("ID", axis="index").reset_index()
    frames = [anomaly_df, incomplete_df, missing_value_df,datatype_mismatch_df]

    return perform_melt(frames)



