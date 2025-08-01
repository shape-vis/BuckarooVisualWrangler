"""
Converts the current datastate data into JSON the view can use
"""
import pandas as pd

from app.service_helpers import get_error_dist, is_categorical
from data_management.data_integration import get_filtered_dataframes


def generate_complete_json(min_id, max_id):
    main_df, error_df = get_filtered_dataframes(min_id, max_id)
    error_list = get_error_dist(error_df, main_df).to_dict('records')
    print("got the dfs")
    return {
        "columnErrors": convert_error_list_to_dict(error_list),
        "attributes": list(main_df.columns),
        "attributeDistributions": build_attribute_distributions(main_df)
    }

def get_attribute_stats(df, column):
    if is_categorical(df[column]):
        print("made it through the categorical")
        return get_categorical_stats(df, column)
    return get_numeric_stats(df, column)

def build_attribute_distributions(main_df):
    distributions = {}
    for col in main_df.columns:
        print("getting the distribution for:",col)
        distributions[col] = get_attribute_stats(main_df, col)
        print("finished getting the distribution for:", col)
    # print("got the distribution")
    return distributions

def get_categorical_stats(df, column):
    df_cat = df.copy()
    df_cat[column] = df_cat[column].fillna('N/A')
    return {
        "categorical": {
            "categories": df_cat[column].nunique(),
            "mode": df_cat[column].mode().iloc[0]
        }
    }

def get_numeric_stats(df, column):
    df = df[pd.to_numeric(df[column], errors='coerce').notna()]
    df[column] = df[column].astype('int64')
    return {
        "numeric": {
            "mean": df[column].mean().item(),
            "min": df[column].min().item(),
            "max": df[column].max().item()
        }
    }

def convert_error_list_to_dict(error_list):
   result = {}
   for row in error_list:
       print("row:", row)
       if row != "error_type":
           error_type = row["error_type"]
           print("error_type",error_type)
           for col_key, percentage in row.items():
               if col_key != "error_type" and float(percentage) > 0:
                   col_name = col_key.strip()
                   if col_name not in result:
                       result[col_name] = {}
                   result[col_name][error_type] = float(percentage)
   print("got the error list")
   return result

