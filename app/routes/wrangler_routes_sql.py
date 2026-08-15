# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app, db_operations
from app.db_utils import query
from app import engine
import traceback
import pandas as pd
from app.server_utils.service_helpers import (
    run_detectors,
    update_errors_incrementally,
    create_previews_1d,
    create_previews_2d,
    execute_wrangle_preview,
    _safe_pg_name,
    n_wrangle,
)
from sqlalchemy import text as sa_text
from app.pgraph.delta import Delta
from app.wrangle_operations.sql_utils import id_list, quote_identifier, table_columns



"""
Wrangling Endpoints - In-place modification of tables
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helper: Re-run error detection after modification
# ─────────────────────────────────────────────────────────────────────────────

def update_errors_table(
    table_name: str,
    source_table_name: str = None,
    source_error_table_name: str = None,
    operation: str = None,
    parameters: dict = None,
) -> None:
    """
    After modifying a table in-place, re-run error detection
    and update the errors table.
    """
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', engine)
        if source_error_table_name and operation:
            # Delta-aware path: use the previous errors table plus the wrangle
            # parameters to recompute only the detector scopes that went stale.
            previous_error_df = pd.read_sql_query(f'SELECT * FROM "{source_error_table_name}"', engine)
            detected_errors_df = update_errors_incrementally(
                df,
                previous_error_df,
                operation,
                parameters or {},
            )
        else:
            # Safe fallback for routes that do not tell us what changed.
            detected_errors_df = run_detectors(df)
        errors_table_name = f"errors_{table_name}"
        # Drop first via raw SQL to avoid SQLAlchemy reflection (which fails on
        # table names > 63 chars due to PostgreSQL identifier truncation).
        with engine.begin() as conn:
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{errors_table_name}"'))
        detected_errors_df.to_sql(errors_table_name, engine, if_exists='fail', index=False)
        print(f"Updated errors table: {errors_table_name}")
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
        table   = body.get("table") or db_operations.main_table_name
        row_ids = _safe_row_ids(body.get("row_ids", []))
        cols    = body.get("cols", [])

        # extra case protection.
        #cols    = [f'{col}' for col in cols]

        if not row_ids:
            return {"success": False, "error": "No rows selected"}, 400

        if not table or not db_operations.table_exists(table):
            return {"success": False, "error": f"Table '{table}' does not exist"}, 404

        current_columns = set(table_columns(engine, table))
        missing_cols = [col for col in cols if col not in current_columns]
        if missing_cols:
            return {
                "success": False,
                "error": (
                    f"Selected column(s) {missing_cols} are not in table '{table}'. "
                    "Reload the dataset or select points from the current table."
                ),
            }, 400

        if table != db_operations.main_table_name:
            db_operations.load_table(table, f"errors_{table}")

        source_row_count = int(db_operations.get_row_count(table) or 0)

        if len(cols) == 1:
            # 1D selection: delete selected rows or impute the selected column.
            result = create_previews_1d(
                table,
                row_ids,
                cols,
                _safe_pg_name,
                update_errors_table,
            )
        else:
            # 2D selection: delete selected rows, impute x column, or impute y column.
            result = create_previews_2d(
                table,
                row_ids,
                cols,
                _safe_pg_name,
                update_errors_table,
            )

        result["source_row_count"] = source_row_count
        result["selected_row_count"] = len(row_ids)
        return result

    except Exception as e:
        print("ERROR in create_previews")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400


MAX_DIFF_ROWS = 100


def _safe_row_ids(row_ids):
    safe_ids = []
    seen = set()
    for row_id in row_ids or []:
        try:
            safe_id = int(row_id)
        except (TypeError, ValueError):
            continue
        if safe_id in seen:
            continue
        seen.add(safe_id)
        safe_ids.append(safe_id)
    return safe_ids


def _display_cell(value):
    try:
        if pd.isna(value):
            return "null"
    except (TypeError, ValueError):
        pass
    return str(value)


def _cells_equal(before, after):
    try:
        if pd.isna(before) and pd.isna(after):
            return True
    except (TypeError, ValueError):
        pass
    try:
        return bool(before == after)
    except (TypeError, ValueError):
        return str(before) == str(after)


def _fetch_rows_for_diff(table_name, row_ids, cols):
    if not row_ids:
        return {}

    selected_cols = ["ID", *cols]
    sql = (
        f"SELECT {', '.join(quote_identifier(col) for col in selected_cols)} "
        f"FROM {quote_identifier(table_name)} "
        f"WHERE {quote_identifier('ID')} IN ({id_list(row_ids)})"
    )
    df = pd.read_sql_query(sql, engine)
    rows = {}
    for record in df.to_dict(orient="records"):
        rows[int(record["ID"])] = record
    return rows


def _preview_impact(source_table, preview_table, row_ids, requested_cols, source_cols):
    """Return exact row and cell impact for a generated repair preview."""
    if not row_ids:
        return {
            "rowsAffected": 0,
            "valuesChanged": 0,
            "selectedRows": 0,
        }

    source_sql = quote_identifier(source_table)
    preview_sql = quote_identifier(preview_table)
    id_sql = quote_identifier("ID")
    changed_conditions = [
        (
            f"s.{quote_identifier(col)} IS DISTINCT FROM "
            f"p.{quote_identifier(col)}"
        )
        for col in requested_cols
    ]
    changed_condition_sql = " OR ".join(changed_conditions) or "FALSE"
    changed_value_sql = " + ".join(
        (
            f"CASE WHEN s.{quote_identifier(col)} IS DISTINCT FROM "
            f"p.{quote_identifier(col)} THEN 1 ELSE 0 END"
        )
        for col in requested_cols
    ) or "0"
    data_column_count = max(0, len([col for col in source_cols if col != "ID"]))

    query = sa_text(f'''
        SELECT
            COUNT(*)::int AS selected_rows,
            COUNT(*) FILTER (
                WHERE p.{id_sql} IS NULL OR ({changed_condition_sql})
            )::int AS rows_affected,
            COALESCE(SUM(
                CASE
                    WHEN p.{id_sql} IS NULL THEN {data_column_count}
                    ELSE {changed_value_sql}
                END
            ), 0)::int AS values_changed
        FROM {source_sql} s
        LEFT JOIN {preview_sql} p ON s.{id_sql} = p.{id_sql}
        WHERE s.{id_sql} IN ({id_list(row_ids)})
    ''')

    with engine.connect() as conn:
        result = conn.execute(query).mappings().one()

    return {
        "rowsAffected": int(result["rows_affected"] or 0),
        "valuesChanged": int(result["values_changed"] or 0),
        "selectedRows": int(result["selected_rows"] or 0),
    }


@app.post("/api/wrangle/preview-row-diff")
def preview_row_diff():
    """
    Compare selected row values between the current table and a preview table.

    Body JSON:
      source_table  - current table name
      preview_table - preview table name
      row_ids       - selected row IDs
      cols          - columns to compare
    """
    try:
        body = request.get_json(force=True)
        source_table = body.get("source_table") or db_operations.main_table_name
        preview_table = body.get("preview_table")
        row_ids = _safe_row_ids(body.get("row_ids", []))
        requested_cols = body.get("cols", [])
        summary_only = bool(body.get("summary_only", False))

        if isinstance(requested_cols, str):
            requested_cols = [requested_cols]
        requested_cols = [str(col) for col in requested_cols if col and str(col) != "ID"]

        if not preview_table:
            return {"success": False, "error": "No preview table provided"}, 400
        if not row_ids:
            return {
                "success": True,
                "rows": [],
                "truncated": False,
                "totalRowCount": 0,
                "impact": {
                    "rowsAffected": 0,
                    "valuesChanged": 0,
                    "selectedRows": 0,
                },
            }

        try:
            source_cols = set(table_columns(engine, source_table))
            preview_cols = set(table_columns(engine, preview_table))
        except Exception:
            return {"success": False, "error": "Source or preview table does not exist"}, 404

        missing_cols = [
            col for col in requested_cols
            if col not in source_cols or col not in preview_cols
        ]
        if "ID" not in source_cols or "ID" not in preview_cols:
            return {"success": False, "error": "Source or preview table is missing ID column"}, 400
        if missing_cols:
            return {
                "success": False,
                "error": f"Column(s) {missing_cols} are missing from the source or preview table",
            }, 400

        impact = _preview_impact(
            source_table,
            preview_table,
            row_ids,
            requested_cols,
            source_cols,
        )
        if summary_only:
            return {
                "success": True,
                "rows": [],
                "truncated": False,
                "totalRowCount": len(row_ids),
                "returnedRowCount": 0,
                "impact": impact,
            }

        total_row_count = len(row_ids)
        limited_row_ids = row_ids[:MAX_DIFF_ROWS]
        source_rows = _fetch_rows_for_diff(source_table, limited_row_ids, requested_cols)
        preview_rows = _fetch_rows_for_diff(preview_table, limited_row_ids, requested_cols)

        diff_rows = []
        for row_id in limited_row_ids:
            source_row = source_rows.get(row_id)
            preview_row = preview_rows.get(row_id)

            for col in requested_cols:
                if source_row is None:
                    diff_rows.append({
                        "rowId": row_id,
                        "column": col,
                        "before": "missing row",
                        "after": _display_cell(preview_row.get(col)) if preview_row else "missing row",
                        "status": "missing_source",
                    })
                    continue

                before = source_row.get(col)
                if preview_row is None:
                    diff_rows.append({
                        "rowId": row_id,
                        "column": col,
                        "before": _display_cell(before),
                        "after": "deleted row",
                        "status": "deleted",
                    })
                    continue

                after = preview_row.get(col)
                diff_rows.append({
                    "rowId": row_id,
                    "column": col,
                    "before": _display_cell(before),
                    "after": _display_cell(after),
                    "status": "changed" if not _cells_equal(before, after) else "unchanged",
                })

        return {
            "success": True,
            "rows": diff_rows,
            "truncated": total_row_count > len(limited_row_ids),
            "totalRowCount": total_row_count,
            "returnedRowCount": len(limited_row_ids),
            "impact": impact,
        }

    except Exception as e:
        print("ERROR in preview_row_diff")
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

        params = {"operation": "delete-column", "column": column}
        delta = Delta("delete-column", params)
        result_meta = delta.operation_result(engine, table)
        if not result_meta.get("column_deleted"):
            if column == "ID":
                error = "Cannot delete required ID column"
            else:
                error = f"Column '{column}' does not exist"
            return {"success": False, "error": error}, 400

        new_table_name = _safe_pg_name(table, "_col_del")
        # Direct column deletion is not a preview flow, so we pass the Delta
        # parameters directly into n_wrangle().
        new_table_name = n_wrangle(table, new_table_name, "delete-column", direct_params=params)

        with engine.begin() as conn:
            view_created = delta.create_view(conn, engine, table, new_table_name)
        if not view_created:
            return {"success": False, "error": f"Could not delete column '{column}'"}, 400

        # Reload DBOperations
        db_operations.load_table(new_table_name, f"errors_{new_table_name}")
        
        # Re-run error detection
        update_errors_table(
            new_table_name,
            source_table_name=table,
            source_error_table_name=f"errors_{table}",
            operation="delete-column",
            parameters=params,
        )
        db_operations.update_rankings(new_table_name)

        return {
            "success": True,
            "remaining_columns": result_meta.get("remaining_columns", 0),
            "deleted_column": result_meta.get("deleted_column", column),
            "table_name": new_table_name
        }
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400
