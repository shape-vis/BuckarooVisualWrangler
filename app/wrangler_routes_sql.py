# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app
from postgres_wrangling import query
import traceback
from app.service_helpers import (
    refresh_errors_table,
    refresh_rankings_table,
    create_previews_1d,
    create_previews_2d,
    execute_wrangle_preview,
    _safe_pg_name,
)


"""
Wrangling Endpoints - In-place modification of tables
"""


def update_errors_table(table_name: str) -> None:
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        detected_row_count = refresh_errors_table(
            table_name,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )
        errors_table_name = f"errors_{table_name}"
        print(f"Updated errors table: {errors_table_name}")
        print(f"Error row count: {detected_row_count}")
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()
        raise


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
      table    - main table name
      row_ids  - list of integer row IDs to operate on
      cols     - list of column names involved in the selection (for imputation)
    """
    try:
        body = request.get_json(force=True)
        table = body["table"]
        row_ids = body.get("row_ids", [])
        cols = body.get("cols", [])

        cols = [f"{col}" for col in cols]

        if not row_ids:
            return {"success": False, "error": "No rows selected"}, 400

        if len(cols) == 1:
            return create_previews_1d(table, row_ids, cols, _safe_pg_name, update_errors_table)
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
        table = body["table"]
        preview_table = body["preview_table"]

        result = execute_wrangle_preview(table, preview_table, _safe_pg_name)
        if result.get("success"):
            refresh_rankings_table(
                table,
                anomaly_methods=["zscore"],
                rarity_threshold=0.05,
            )
        return result
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

        remaining_columns = query.delete_column(table=table, column=column)

        update_errors_table(table)
        refresh_rankings_table(
            table,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )

        return {
            "success": True,
            "remaining_columns": remaining_columns,
            "deleted_column": column
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400
