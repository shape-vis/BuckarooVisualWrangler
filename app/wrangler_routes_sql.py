# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app
from app import engine
from postgres_wrangling import query
import traceback
import hashlib
import pandas as pd
from pprint import pprint
from app.service_helpers import run_detectors, create_previews_1d, create_previews_2d, execute_wrangle_preview
from sqlalchemy import text as sa_text


def _preview_name(base: str, suffix: str) -> str:
    """
    Build a preview table name guaranteed to keep both itself and its
    derived 'errors_<name>' sibling within PostgreSQL's 63-char limit.

    errors_ prefix = 7 chars, so the preview name itself must be ≤ 56 chars.
    If base+suffix already fits, use it as-is.  Otherwise truncate the base
    and append an 8-char MD5 hash so the name stays unique.
    """
    MAX_LEN = 56  # 63 - len("errors_")
    candidate = f"{base}{suffix}"
    if len(candidate) <= MAX_LEN:
        return candidate
    h = hashlib.md5(base.encode()).hexdigest()[:8]
    max_base = MAX_LEN - len(suffix) - 9  # 9 = 1 underscore + 8 hash chars
    return f"{base[:max_base]}_{h}{suffix}"

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
        table   = body["table"]
        row_ids = body.get("row_ids", [])
        cols    = body.get("cols", [])

        if not row_ids:
            return {"success": False, "error": "No rows selected"}, 400

        if len(cols) == 1:
            return create_previews_1d(table, row_ids, cols, _preview_name, update_errors_table)
        else:
            return create_previews_2d(table, row_ids, cols, _preview_name, update_errors_table)

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
        table         = body["table"]          # main table name
        preview_table = body["preview_table"]  # the preview to promote

        return execute_wrangle_preview(table, preview_table, _preview_name)
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
        table = body["table"]
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
