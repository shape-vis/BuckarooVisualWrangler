# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app, db_operations
from app.db_utils import query
from app import engine
import traceback
import pandas as pd
from app.server_utils.service_helpers import run_detectors, create_previews_1d, create_previews_2d, execute_wrangle_preview, _safe_pg_name
from sqlalchemy import text as sa_text



"""
Wrangling Endpoints - In-place modification of tables
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helper: Re-run error detection after modification
# ─────────────────────────────────────────────────────────────────────────────

def update_errors_table(table_name: str) -> None:
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', engine)
        detected_errors_df = run_detectors(df)
        errors_table_name = f"errors_{table_name}"
        # Drop first via raw SQL to avoid SQLAlchemy reflection (which fails on
        # table names > 63 chars due to PostgreSQL identifier truncation).
        with engine.begin() as conn:
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_table_name}"'))
        detected_errors_df.to_sql(errors_table_name, engine, if_exists='fail', index=False)
        print(f"✓ Updated errors table: {errors_table_name}")
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
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
            return create_previews_1d(table, row_ids, cols, _safe_pg_name, update_errors_table)
        else:
            return create_previews_2d(table, row_ids, cols, _safe_pg_name, update_errors_table)

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
