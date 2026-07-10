# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app, db_operations
from app.db_utils import query
from app import engine
import traceback
import pandas as pd
from app.server_utils.service_helpers import run_detectors, create_previews_1d, create_previews_2d, \
    execute_wrangle_preview, _safe_pg_name, create_data_profile_df
from sqlalchemy import text as sa_text
from sqlalchemy import inspect, text



"""
Wrangling Endpoints - In-place modification of tables
"""

# Where updated_df is just the data that needed to actually be updated
# Assumes that updated_df has the same columns as the target table
# TODO: reimplement with "dirty flags"
def update_table(updated_df, target_table_name, key_col, cols_to_remove):
    with engine.begin() as conn:
        result = conn.execute(
            text(f'DELETE FROM "{target_table_name}" WHERE "{key_col}" = ANY(:categories)'),
            {"categories": cols_to_remove}
        )

    staging_table = _safe_pg_name(target_table_name, "_staging")

    cols_to_update = updated_df.columns

    # 1. Push data to a temp staging table
    updated_df.to_sql(staging_table, engine, if_exists='replace', index=False)

    # Make sure that there's a main errors table we can update
    inspector = inspect(engine)
    assert inspector.has_table(target_table_name), f"Table {target_table_name} does not exist!"

    # 2. Set-based update, Postgres native syntax
    with engine.begin() as conn:
        set_clause = ", ".join(f'"{c}" = staged."{c}"' for c in cols_to_update)
        conn.execute(text(f'''
            UPDATE "{target_table_name}" target
            SET {set_clause}
            FROM "{staging_table}" staged
            WHERE target."{key_col}" = staged."{key_col}"
        '''))

        conn.execute(text(f'DROP TABLE "{staging_table}"'))


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Re-run error detection after modification
# ─────────────────────────────────────────────────────────────────────────────

# Returns error_df for update_data_profile_table to use (so it doesn't have to get it from the database)
def update_errors_table(table_name: str, columns_selected_for_wrangling: list) -> pd.DataFrame:
    # TODO: fix this so it doesn't update the whole table after small changes to the table
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', engine)

        # TODO: optimize this so it doesn't load the whole table into a df first
        df = df[columns_selected_for_wrangling]

        detected_errors_df = run_detectors(df)
        errors_table_name = f"errors_{table_name}"

        key_column = "column_id"
        update_table(detected_errors_df, errors_table_name, key_column, columns_selected_for_wrangling)

        # Drop first via raw SQL to avoid SQLAlchemy reflection (which fails on
        # table names > 63 chars due to PostgreSQL identifier truncation).
        #with engine.begin() as conn:
        #    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_table_name}"'))


        # detected_errors_df.to_sql(errors_table_name, engine, if_exists='fail', index=False)

        print(f"✓ Updated errors table: {errors_table_name}")
        return detected_errors_df
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()
        raise

# TODO: Make update_data_profile_table and update_errors_table more similar
# TODO: Re-implement with "dirty flags"
def update_data_profile_table(table_name: str, error_df: pd.DataFrame, columns_selected_for_wrangling: list) -> None:
    try:

        # TODO: optimize this so it doesn't load the whole table into a df first
        dp_table_name = f"dp_{table_name}"
        print("COL NAMES", columns_selected_for_wrangling)

        updated_df = create_data_profile_df(table_name, engine, col_names=columns_selected_for_wrangling, error_df=error_df)
        # Can't use db_operations.data_profile because this function is also used for updating preview tables,
        # meaning that the "main_table" that this function uses may be a preview table. Using the db_operations data_profile
        # has the table name set as the main table and it'll be calculating statistics on the wrong table. So we create a new data
        # profile object
        data_profile = DataProfile(table_name, engine)

        key_column = "column_name"

        update_table(updated_df, dp_table_name, key_column, columns_selected_for_wrangling)



        print(f"✓ Updated data profile table: {dp_table_name}")
    except Exception as e:
        print(f"ERROR: Could not update data profile table for {table_name}: {e}")
        traceback.print_exc()
        raise


# TODO: Finish this later
#def update_stat_to_data_profile_table(table_name: str, error_df: pd.DataFrame) -> None:






# TODO: does this even do anything? Can I remove it?
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
    try:
        body = request.get_json(force=True)
        table   = db_operations.main_table_name
        row_ids = body.get("row_ids", [])
        cols    = body.get("cols", [])

        # extra case protection.
        #cols    = [f'{col}' for col in cols]

        if not row_ids:
            return {"success": False, "error": "No rows selected"}, 400

        if len(cols) == 1:
            return create_previews_1d(table, row_ids, cols, _safe_pg_name, update_errors_table, update_data_profile_table)
        else:
            return create_previews_2d(table, row_ids, cols, _safe_pg_name, update_errors_table, update_data_profile_table)

    except Exception as e:
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
    try:
        body = request.get_json(force=True)
        table         = db_operations.main_table_name
        preview_table = body["preview_table"]  # the preview to promote

        return execute_wrangle_preview(table, preview_table, _safe_pg_name, db_operations)
    except Exception as e:
        print("ERROR in execute_wrangle")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400


@app.post("/api/wrangle/delete-column")
def wrangle_delete_column():
    """
    Delete a column from the table in-place.

    Modifies the table directly - no versioning.
    """
    try:
        body = request.get_json(force=True)
        table = db_operations.main_table_name
        column = body["column"]

        print(f"Deleting column '{column}' from table '{table}'")

        # Delete the column
        remaining_columns = query.delete_column(table=table, column=column)

        # Re-run error detection
        update_errors_table(table)

        return {
            "success": True,
            "remaining_columns": remaining_columns,
            "deleted_column": column
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400
