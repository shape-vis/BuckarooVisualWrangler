import pandas as pd
from app.service_helpers import get_whole_table_query, run_detectors
from app import engine
from sqlalchemy import text
import numpy as np
from data_management.data_integration import generate_2d_histogram_data_modified
from postgres_wrangling import query

number_of_bins = 10

def insert_dataframe_to_postgres(dataframe, table_name):
    dataframe.to_sql(table_name, engine, if_exists='replace')

def get_table_dataframe_from_postgres(table_name):
    return pd.read_sql_query(get_whole_table_query(table_name,False), engine).replace(np.nan, None)

def calculate_2D_histogram_pandas(dataframe, x_column_name, y_column_name, max_row_count):
    error_df = run_detectors(dataframe)

    binned_data = generate_2d_histogram_data_modified(
        dataframe, error_df,
        x_column_name, y_column_name,
        number_of_bins, number_of_bins,
        0, max_row_count,
    )
    return binned_data

def calculate_2D_histogram_postgres(x_column_name, y_column_name, table_name, max_row_count):
    binned_data = query.generate_2d_histogram_data(
        x_column=x_column_name,
        y_column=y_column_name,
        bins=number_of_bins,
        min_id=0,
        max_id=max_row_count,
        table_name=table_name,
        whole_table=True
    )
    return binned_data

def remove_bad_data_pandas(currentSelection, cols, current_df):
    return query.remove_problematic_rows(currentSelection, cols, current_df)

def remove_bad_data_postgres(currentSelection, cols, table):
    new_table_name = query.new_table_name(table)
    deletedRowCount = query.copy_without_flagged_rows(current_selection=currentSelection, cols=cols, table=table, new_table_name=new_table_name)
    return deletedRowCount, new_table_name

def impute_missing_data_pandas(currentSelection, cols, current_df):
    points_to_remove_array = query.copy_and_impute_bin_df(
            current_selection=currentSelection,
            cols=cols,
            df=current_df
        )
    # remove the points from the df
    wrangled_df = query.impute_at_indices_copy(df=current_df, cols=cols, row_indices=points_to_remove_array)
    return wrangled_df

def impute_missing_data_postgres(currentSelection, cols, table):
    new_table_name = query.new_table_name(table)
    deletedRowCount = query.copy_without_flagged_rows(current_selection=currentSelection, cols=cols, table=table, new_table_name=new_table_name)
    return deletedRowCount

def get_row_count(table_name: str) -> int:
    """
    Return the number of rows in *table_name*.

    Parameters
    ----------
    engine      : sqlalchemy.Engine  – created with create_engine(...)
    table_name  : str               – exact table name (optionally schema-qualified)

    Returns
    -------
    int
        Row count.
    """
    stmt = text(f'SELECT COUNT(*) FROM "{table_name}"')   # double quotes preserve case/mixed-case identifiers
    with engine.connect() as conn:
        return conn.execute(stmt).scalar_one()

def get_all_clickable_bins(histograms):
    error_bins = []
    for bin in histograms['histograms']:
        if len(bin['count']) > 1:
            error_bins.append({
                'scaleX': histograms['scaleX'],
                'scaleY': histograms['scaleY'],
                'data': [bin]
            })

    return error_bins
