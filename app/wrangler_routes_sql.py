# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app
from app import engine
from postgres_wrangling import query
import traceback
import pandas as pd
from pprint import pprint
from app.service_helpers import run_detectors

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
        detected_errors_df = run_detectors(
            table_name,
            anomaly_methods=["zscore", "mad", "iqr"]
        )
        if "error_type" in detected_errors_df.columns:
            detected_errors_df["raw_error_type"] = detected_errors_df["error_type"]
            anomaly_mask = detected_errors_df["error_type"].astype(str).str.contains("anomaly", na=False)
            detected_errors_df.loc[anomaly_mask, "error_type"] = "anomaly"
        errors_table_name = f"errors{table_name}"
        detected_errors_df.to_sql(errors_table_name, engine, if_exists='replace', index=False)
        print(f"✓ Updated errors table: {errors_table_name}")
    except Exception as e:
        print(f"Warning: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()

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
