#Buckaroo Project - June 1, 2025
#This file helps deliver on endpoint services

import re

import numpy as np
import pandas as pd
from pandas.core.dtypes.common import is_categorical_dtype
from sqlalchemy.dialects.mssql.information_schema import columns

from app import data_state_manager
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

def init_session_data_state(df,error_df,data_state_manager):
    table_dict = {"df":df,"error_df":error_df}
    data_state_manager.set_original_df(df)
    data_state_manager.set_original_error_table(error_df)
    data_state_manager.set_current_state(table_dict)

def update_data_state(wrangled_df, new_error_df):
    new_state = {"df":wrangled_df,"error_df":new_error_df}
    data_state_manager.set_current_state(new_state)

def fetch_detected_and_undetected_current_dataset_from_db(cleaned_table_name,engine):
    try:
        full_df_query = get_whole_table_query(cleaned_table_name,False)
        error_df_query = get_whole_table_query(cleaned_table_name,True)
        undetected_df = pd.read_sql_query(full_df_query, engine)
        detected_df = pd.read_sql_query(error_df_query, engine)
        # set the first datastate for later wrangling purposes
        print("starting initial data-state:")
        init_session_data_state(undetected_df, detected_df, data_state_manager)

    except Exception as e:
        return {"success": False, "error": str(e)}

def get_whole_table_query(table_name, get_errors):
    name = clean_table_name(table_name)
    if get_errors:
        query = f"SELECT * FROM errors{name}"
        return query
    query = f"SELECT * FROM {name}"
    return query

def get_range_of_ids_query(min_id,max_id,table_name, get_errors):
    name = clean_table_name(table_name)
    if get_errors:
        query = f"SELECT * FROM errors{name} WHERE " + "'ID'" + f" BETWEEN {min_id} AND {max_id}"
        return query
    query = f"SELECT * FROM {name} WHERE " + "'ID'" + f" BETWEEN {min_id} AND {max_id}"
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

def get_error_dist(error_df):
    res = error_df.pivot_table("row_id", index="error_type", columns='column_id', aggfunc="count")
    res_mask = res.fillna(0)
    return res_mask


def add_normal_row_to_error_dist(error_distribution,normal_df):
  new_row = {}
  for col in error_distribution.columns:
    print(col)
    normal_column_size = normal_df[col].size
    error_distribution_column_size = error_distribution[col].sum()
    new_row[col] = [(normal_column_size - error_distribution_column_size)/normal_column_size]

  for col in normal_df.columns:
      if col not in new_row.keys() and col != "ID":
          new_row[col] = [1]

  row_to_add = pd.DataFrame(data=new_row,index=['no_errors'])
  full_dist_with_nans = pd.concat([error_distribution,row_to_add],axis=0)
  full_dist_without_nans = full_dist_with_nans.fillna(0)
  renamed_index_df = full_dist_without_nans.rename_axis("error_type")
  return renamed_index_df

def create_error_dict(df, error_size):
    try:
        error_size_df = df[df['row_id'].between(1, error_size)]
        result_dict = {}
        for _, row in error_size_df.iterrows():
            col = row['column_id']
            row_id = row['row_id']
            error_type = row['error_type']
            if pd.notna(error_type):
                if col not in result_dict:
                    result_dict[col] = {}
                if row_id not in result_dict[col]:
                    result_dict[col][row_id] = []
                result_dict[col][row_id].append(error_type)
        return result_dict
    except Exception as e:
        return {"success": False, "error in the error_dictionary service helper": str(e)}

def group_by_attribute(df, column_a, group_by):
    ret = df.pivot_table("ID", index=column_a, columns=group_by, aggfunc="count")
    return ret

def get_2d_bins(column_a,column_b, range,bin_count):
    column_a_categorical = is_categorical(column_a)
    column_b_categorical = is_categorical(column_b)
    column_a_bins = column_a
    column_b_bins = column_b
    if not column_a_categorical:
        column_a_bins = create_bins_for_a_numeric_column(column_a,bin_count)
    if not column_b_categorical:
        column_b_bins = create_bins_for_a_numeric_column(column_b,bin_count )
    print("before crosstab")
    return pd.crosstab(column_a_bins, column_b_bins,dropna=True)

    #make the number of bins for numeric be an option

def slice_data_by_min_max_ranges(min_val,max_val,df,error_df):
    min_val_int = int(min_val)
    max_val_int = int(max_val)
    sliced_max_df = df[df["ID"] <= max_val_int]
    sliced_min_max_df = sliced_max_df[sliced_max_df["ID"] >= min_val_int]

    sliced_error_max_df = error_df[error_df["row_id"] <= max_val_int]
    sliced_min_max_error_df = sliced_error_max_df[sliced_error_max_df["row_id"] >= min_val_int]

    return sliced_min_max_df, sliced_min_max_error_df

def is_categorical(column_a):
    value_counts = column_a.value_counts()
    type_count = {}
    type_key = {}
    largest_type = 0
    value_type = None
    # populate the count of each type in the column
    for key, value in value_counts.items():
        type_of_key = type(key).__name__
        if (isinstance(key, str)) and (bool(re.fullmatch(r'^\d+(\.\d+)?$', key.strip()))): type_of_key = "numeric"
        if type_of_key in type_count:
            type_count[type_of_key] += value
            if type_of_key in type_key:
                type_key[type_of_key].append(key)
        else:
            type_count[type_of_key] = value
            type_key[type_of_key] = [key]
    types = type_count.items()
    for key, value in types:
        if value > largest_type:
            largest_type = value
            value_type = key
    if value_type == "str":
        return True
    else:
        return False

def create_bins_for_a_numeric_column(column,bin_count):
    return pd.cut(column, bins=bin_count)