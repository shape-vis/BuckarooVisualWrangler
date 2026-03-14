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
from app.service_helpers import run_detectors
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
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/wrangle/remove")
def wrangle_remove():
    """
    Remove rows in-place. Handles both bin-based (histogram) and ID-based (scatterplot) selections.

    Modifies the table directly - no versioning.
    """
    try:
        body = request.get_json(force=True)
        currentSelection = body["currentSelection"]
        cols = body["cols"]
        table = body["table"]

        print("current selection:")
        pprint(currentSelection)
        print("cols:")
        pprint(cols)
        print("table:", table)

        # Detect selection type: 1D bin / 2D bin / ID-based
        first_item = currentSelection["data"][0]

        if "bin" in first_item and "xBin" not in first_item:
            # 1D histogram (barchart) - uses "bin" not "xBin"
            remaining_rows = query.remove_flagged_rows_in_1d_bin(
                current_selection=currentSelection,
                col=cols[0],  # Only one column for 1D
                table=table
            )
        elif "xBin" in first_item and "yBin" in first_item:
            # 2D histogram (heatmap)
            remaining_rows = query.remove_flagged_rows_in_bin(
                current_selection=currentSelection,
                cols=cols,
                table=table
            )
        else:
            # ID-based (scatterplot)
            ids = [point["ID"] for point in currentSelection["data"]]
            remaining_rows = query.remove_rows_by_ids(table=table, ids=ids)

        # Re-run error detection
        update_errors_table(table)

        return {
            "success": True,
            "remaining_rows": remaining_rows
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400


@app.post("/api/wrangle/impute")
def wrangle_impute():
    """
    Impute missing values in-place. Handles both bin-based (histogram) and ID-based (scatterplot) selections.

    Modifies the table directly - no versioning.
    """
    try:
        body = request.get_json(force=True)
        currentSelection = body["currentSelection"]
        cols = body["cols"]
        table = body["table"]
        col = body.get("col")  # For scatterplot: which specific column to impute

        print("current selection:")
        pprint(currentSelection)
        print("cols:")
        pprint(cols)
        print("col:", col)
        print("table:", table)

        # Detect selection type: 1D bin / 2D bin / ID-based
        first_item = currentSelection["data"][0]

        if "bin" in first_item and "xBin" not in first_item:
            # 1D histogram (barchart) - uses "bin" not "xBin"
            rows_examined, cells_imputed = query.impute_1d_bin_in_place(
                current_selection=currentSelection,
                col=cols[0],  # Only one column for 1D
                table=table
            )
        elif "xBin" in first_item and "yBin" in first_item:
            # 2D histogram (heatmap)
            rows_examined, cells_imputed = query.impute_bin_in_place(
                current_selection=currentSelection,
                cols=cols,
                table=table
            )
        else:
            # ID-based (scatterplot)
            if not col:
                return {"success": False, "error": "Column 'col' required for scatterplot imputation"}, 400
            ids = [point["ID"] for point in currentSelection["data"]]
            rows_examined, cells_imputed = query.impute_by_ids(table=table, col=col, ids=ids)

        # Re-run error detection
        update_errors_table(table)

        return {
            "success": True,
            "rows_examined": rows_examined,
            "cells_imputed": cells_imputed
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400


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

        errors_src     = f"errors_{table}"
        preview_delete = _preview_name(table, "_preview_delete")
        errors_dst_del = f"errors_{preview_delete}"

        if len(cols) == 1:
            # ── 1D: delete + single impute ───────────────────────────────────
            preview_impute = _preview_name(table, "_preview_impute")
            errors_dst_imp = f"errors_{preview_impute}"

            with engine.begin() as conn:
                # Delete preview
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_delete}"'))
                conn.execute(sa_text(f'CREATE TABLE "{preview_delete}" AS SELECT * FROM "{table}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_del}"'))
                conn.execute(sa_text(f'CREATE TABLE "{errors_dst_del}" AS SELECT * FROM "{errors_src}"'))

                # Impute preview
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute}"'))
                conn.execute(sa_text(f'CREATE TABLE "{preview_impute}" AS SELECT * FROM "{table}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp}"'))
                conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp}" AS SELECT * FROM "{errors_src}"'))

            query.remove_rows_by_ids(table=preview_delete, ids=row_ids)
            query.impute_by_ids(table=preview_impute, col=cols[0], ids=row_ids)

            update_errors_table(preview_delete)
            update_errors_table(preview_impute)

            return {
                "success": True,
                "preview_delete": preview_delete,
                "preview_impute": preview_impute,
                "dims": 1,
            }

        else:
            # ── 2D: delete + impute_x + impute_y ────────────────────────────
            preview_impute_x = _preview_name(table, "_preview_impute_x")
            preview_impute_y = _preview_name(table, "_preview_impute_y")
            errors_dst_imp_x = f"errors_{preview_impute_x}"
            errors_dst_imp_y = f"errors_{preview_impute_y}"

            with engine.begin() as conn:
                # Delete preview
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_delete}"'))
                conn.execute(sa_text(f'CREATE TABLE "{preview_delete}" AS SELECT * FROM "{table}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_del}"'))
                conn.execute(sa_text(f'CREATE TABLE "{errors_dst_del}" AS SELECT * FROM "{errors_src}"'))

                # Impute X preview
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute_x}"'))
                conn.execute(sa_text(f'CREATE TABLE "{preview_impute_x}" AS SELECT * FROM "{table}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp_x}"'))
                conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp_x}" AS SELECT * FROM "{errors_src}"'))

                # Impute Y preview
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{preview_impute_y}"'))
                conn.execute(sa_text(f'CREATE TABLE "{preview_impute_y}" AS SELECT * FROM "{table}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_dst_imp_y}"'))
                conn.execute(sa_text(f'CREATE TABLE "{errors_dst_imp_y}" AS SELECT * FROM "{errors_src}"'))

            query.remove_rows_by_ids(table=preview_delete, ids=row_ids)
            query.impute_by_ids(table=preview_impute_x, col=cols[0], ids=row_ids)
            query.impute_by_ids(table=preview_impute_y, col=cols[1], ids=row_ids)

            update_errors_table(preview_delete)
            update_errors_table(preview_impute_x)
            update_errors_table(preview_impute_y)

            return {
                "success": True,
                "preview_delete": preview_delete,
                "preview_impute_x": preview_impute_x,
                "preview_impute_y": preview_impute_y,
                "dims": 2,
            }

    except Exception as e:
        print("ERROR in create_previews")
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
