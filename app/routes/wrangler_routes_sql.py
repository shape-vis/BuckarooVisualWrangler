# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app.db_utils import query
from app import app, engine, db_operations
import traceback
import pandas as pd
from app.server_utils.service_helpers import create_error_df, create_previews_1d, create_previews_2d, \
    execute_wrangle_preview, _safe_pg_name, create_data_profile_df, get_sqlalchemy_dtype_map, extract_preview_action
from sqlalchemy import inspect, text

from app.db_utils.data_profile import DataProfile
from datetime import datetime, timezone
from app.server_utils.logger_utils import update_action_log, update_preview_log, get_action_details_from_preview_log
import json

"""
Wrangling Endpoints - In-place modification of tables
"""


# Where updated_df is just the data that needed to actually be updated
# Assumes that updated_df has the same columns as the target table
def update_table(updated_df, target_table_name, key_col, cols_to_remove):
    with engine.begin() as conn:
        result = conn.execute(
            text(f'DELETE FROM "{target_table_name}" WHERE "{key_col}" = ANY(:categories)'),
            {"categories": cols_to_remove}
        )

    staging_table_name = _safe_pg_name(target_table_name, "_staging")

    dtype_dict = query.get_table_dtypes(target_table_name, engine)

    # 1. Push data to a temp staging table
    updated_df.to_sql(staging_table_name, engine, if_exists='replace', dtype=dtype_dict)

    # Make sure that there's a main errors table we can update
    inspector = inspect(engine)
    assert inspector.has_table(target_table_name), f"Table {target_table_name} does not exist!"

    # 2. Set-based update, Postgres native syntax
    with engine.begin() as conn:
        conn.execute(text(f'''
            INSERT INTO "{target_table_name}"
            SELECT *
            FROM "{staging_table_name}"
        '''))

        conn.execute(text(f'DROP TABLE "{staging_table_name}"'))

# ─────────────────────────────────────────────────────────────────────────────
# Helper: Re-run error detection after modification
# ─────────────────────────────────────────────────────────────────────────────



def update_errors_table(table_name: str, columns_selected_for_wrangling: list) -> pd.DataFrame:
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', engine)

        df = df[columns_selected_for_wrangling]

        # TODO: optimize this so it doesn't load the whole table into a df first
        detected_errors_df = create_error_df(df)
        errors_table_name = f"errors_{table_name}"

        key_column = "column_id"
        update_table(detected_errors_df, errors_table_name, key_column, columns_selected_for_wrangling)

        # Drop first via raw SQL to avoid SQLAlchemy reflection (which fails on
        # table names > 63 chars due to PostgreSQL identifier truncation).
        #with engine.begin() as conn:
        #    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_table_name}"'))


        # detected_errors_df.to_sql(errors_table_name, engine, if_exists='fail', index=False)

        print(f"✓ Updated errors table: {errors_table_name}")
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()
        raise

# TODO:optimize this so it doesn't load the whole table into a df first
def update_data_profile_table(table_name: str, columns_selected_for_wrangling: list) -> None:
    try:

        dp_table_name = f"dp_{table_name}"

        # Can't use db_operations.data_profile because this function is also used for updating preview tables,
        # meaning that the "main_table" that this function uses may be a preview table. Using the db_operations data_profile
        # has the table name set as the main table and it'll be calculating statistics on the wrong table. So we create a new data
        # profile object
        data_profile = DataProfile(table_name, engine)

        updated_df = create_data_profile_df(data_profile, col_names=columns_selected_for_wrangling)

        key_column = "column_name"

        update_table(updated_df, dp_table_name, key_column, columns_selected_for_wrangling)

        print(f"✓ Updated data profile table: {dp_table_name}")
    except Exception as e:
        print(f"ERROR: Could not update data profile table for {table_name}: {e}")
        traceback.print_exc()
        raise


def update_preview_error_table(table_name: str, err_table_name: str) -> None:
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        x = None

        # df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', engine)
        # detected_errors_df = run_detectors(df)
        # errors_table_name = f"errors_{table_name}"
        # # Drop first via raw SQL to avoid SQLAlchemy reflection (which fails on
        # # table names > 63 chars due to PostgreSQL identifier truncation).
        # with engine.begin() as conn:
        #     conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_table_name}"'))
        # detected_errors_df.to_sql(errors_table_name, engine, if_exists='fail', index=False)
        # print(f"✓ Updated errors table: {errors_table_name}")
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()
        raise

def execute_wrangle_logic(preview_table, table):
    action_details_dict = get_action_details_from_preview_log(preview_table, engine)

    wrangle_executed = extract_preview_action(preview_table)

    new_table_name = execute_wrangle_preview(table, preview_table, _safe_pg_name, db_operations)

    return (new_table_name, action_details_dict, wrangle_executed)



# ─────────────────────────────────────────────────────────────────────────────
# Wrangling Endpoints (Supports both bin-based and ID-based selections)
# the way it works is, create-previews does all wrangles (delete, impute x/y), 
# puts the wrangled tables into the DB, then execute promotes the desired wrangle
# and deletes the previews
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/wrangle/create-previews")
def create_previews():
    """
    Create preview copies of the main table for the current row selection.

    For 1D (len(cols)==1):
      - <table>_preview_delete  : selected rows removed
      - <table>_preview_impute  : selected column imputed for those rows

    For 2D (len(cols)==2):
      - <table>_preview_delete    : selected rows removed
      - <table>_preview_impute_x  : cols[0] imputed for those rows
      - <table>_preview_impute_y  : cols[1] imputed for those rows

    Body JSON:
      table    – main table name
      row_ids  – list of integer row IDs to operate on
      cols     – list of column names involved in the selection (for imputation)
    """

    timestamp = datetime.now(timezone.utc)
    try:
        body = request.get_json(force=True)
        table   = db_operations.main_table_name
        row_ids = body.get("row_ids", [])
        cols    = body.get("cols", [])


        # extra case protection.
        #cols    = [f'{col}' for col in cols]

        if not row_ids:
            update_action_log(main_table_name=table, action_name="create_previews",
                              action_details=json.dumps({"row_ids": row_ids, "cols": cols}), engine=engine,
                              timestamp=timestamp, action_successful=False, action_error_message="Row IDs list is empty")

            return {"success": False, "error": "No rows selected"}, 400


        action_details_dict = {"row_ids": row_ids, "cols": cols}

        if len(cols) == 1:

            (preview_delete_table_name, preview_impute_table_name) = create_previews_1d(table, row_ids, cols, _safe_pg_name, update_errors_table, update_data_profile_table)

            update_preview_log(preview_delete_table_name, "delete_wrangle", action_details_dict, engine)
            update_preview_log(preview_impute_table_name, "impute_wrangle", action_details_dict, engine)

            result_dict = {
                "success": True,
                "preview_delete": preview_delete_table_name,
                "preview_impute": preview_impute_table_name,
                "dims": 1,
            }
        else:
            (preview_delete_table_name, preview_impute_x_table_name, preview_impute_y_table_name) = create_previews_2d(table, row_ids, cols, _safe_pg_name, update_errors_table, update_data_profile_table)

            update_preview_log(preview_delete_table_name, "delete_wrangle", action_details_dict, engine)
            update_preview_log(preview_impute_x_table_name, "impute_x_wrangle", action_details_dict, engine)
            update_preview_log(preview_impute_y_table_name, "impute_y_wrangle", action_details_dict, engine)

            result_dict = {
                "success": True,
                "preview_delete": preview_delete_table_name,
                "preview_impute_x": preview_impute_x_table_name,
                "preview_impute_y": preview_impute_y_table_name,
                "dims": 2,
            }

        action_duration = (datetime.now(timezone.utc) - timestamp).total_seconds()


        update_action_log(main_table_name=table, action_name="create_previews",
                          action_details=json.dumps(action_details_dict), engine=engine,
                          timestamp=timestamp, action_duration= action_duration, action_successful=True)

        assert result_dict is not None

        return result_dict

    except Exception as e:

        update_action_log(main_table_name=table, action_name="create_previews",
                          action_details=json.dumps({"row_ids": row_ids, "cols": cols}), engine=engine,
                          timestamp=timestamp, action_successful=False, action_error_message=e)

        print("ERROR in create_previews")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400


@app.post("/api/wrangle/execute")
def execute_wrangle():
    """
    Promote a preview table to become the main table:
    1. Delete all other preview tables (and their errors_ siblings) for this base table
    2. Rename the main table to <table>_old
    3. Rename the selected preview table to <table>
    4. Delete <table>_old
    """
    timestamp = datetime.now(timezone.utc)
    try:
        body = request.get_json(force=True)
        table         = db_operations.main_table_name
        preview_table = body["preview_table"]  # the preview to promote

        # TODO: incorporate action details from preview log table into this
        (new_table_name, action_details_dict, wrangle_executed) = execute_wrangle_logic(preview_table, table)

        action_duration =  (datetime.now(timezone.utc) - timestamp).total_seconds()
        update_action_log(main_table_name=db_operations.base_table_name, action_name=f"{wrangle_executed}_wrangle",
                          action_details=action_details_dict, engine=db_operations.engine, timestamp=timestamp, action_duration= action_duration, action_successful=True)

        return {"success": True, "table": new_table_name}
    except Exception as e:
        print("ERROR in execute_wrangle")
        print(traceback.format_exc())

        update_action_log(main_table_name=db_operations.base_table_name, action_name=f"{wrangle_executed}_wrangle",
                          action_details=action_details_dict, engine=db_operations.engine, timestamp=timestamp, action_duration= None, action_successful=False, action_error_message=e)
        return {"success": False, "error": str(e)}, 400


# TODO: check if the column delete functionality actually even works
@app.post("/api/wrangle/delete-column")
def wrangle_delete_column():
    # TODO: why doesn't this have versioning? What if the user wants to undo this action?
    """
    Delete a column from the table in-place.

    Modifies the table directly - no versioning.
    """

    timestamp = datetime.now(timezone.utc)
    try:
        body = request.get_json(force=True)
        table_name = db_operations.main_table_name
        column = body["column"]

        print(f"Deleting column '{column}' from table '{table_name}'")

        # Delete the column
        remaining_columns = query.delete_column(table=table_name, column=column)

        # Re-run error detection
        update_errors_table(table_name, [column])
        update_data_profile_table(table_name, [column])
        action_duration = (datetime.now(timezone.utc) - timestamp).total_seconds()
        update_action_log(main_table_name=db_operations.base_table_name, action_name="delete_column",
                          action_details={"column": column}, engine=engine, timestamp=timestamp, action_duration= action_duration,
                          action_successful=True)


        return {
            "success": True,
            "remaining_columns": remaining_columns,
            "deleted_column": column
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())

        update_action_log(main_table_name=db_operations.base_table_name, action_name=f"delete_column",
                          action_details={"column": column}, engine=db_operations.engine, timestamp=timestamp, action_duration= None, action_successful=False, action_error_message=e)

        return {"success": False, "error": str(e)}, 400
