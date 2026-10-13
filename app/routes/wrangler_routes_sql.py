# Buckaroo Project - July 2, 2025
# This file handles all endpoints surrounding wranglers

from flask import request
from app import app, db_operations
from app.db_utils import query
from app import engine
import traceback
import pandas as pd
from app.server_utils.service_helpers import _safe_pg_name, create_data_profile_df
from sqlalchemy import inspect, text

from app.db_utils.column_types import ColumnTypes
from app.db_utils.data_profile import DataProfile
from app.db_utils.detector_sql import DetectorSQL
from app.server_utils import candidates

"""
Wrangling Endpoints - In-place modification of tables
"""

def get_table_dtypes(target_table_name, engine):
    """Build a dtype dict for to_sql() by reflecting the target table's real column types."""
    inspector = inspect(engine)
    columns = inspector.get_columns(target_table_name)
    # col["type"] is already a SQLAlchemy type instance we can hand straight to to_sql
    return {col["name"]: col["type"] for col in columns}

# Where updated_df is just the data that needed to actually be updated
# Assumes that updated_df has the same columns as the target table
# TODO: reimplement with "dirty flags"
def update_table(updated_df, target_table_name, key_col, cols_to_remove):
    with engine.begin() as conn:
        result = conn.execute(
            text(f'DELETE FROM "{target_table_name}" WHERE "{key_col}" = ANY(:categories)'),
            {"categories": cols_to_remove}
        )

    staging_table_name = _safe_pg_name(target_table_name, "_staging")

    dtype_dict = query.get_table_dtypes(target_table_name, engine)

    # 1. Push data to a temp staging table
    # index=False to match how the target table was written: step 2 inserts positionally, so the
    # staging table has to have exactly the target's columns
    updated_df.to_sql(staging_table_name, engine, if_exists='replace', dtype=dtype_dict, index=False)

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

def update_errors_table(table_name: str) -> None:
    """
    After modifying a table in-place, re-run error detection and rebuild the errors table.

    The detectors run inside Postgres over the whole table, "ID" included, and the whole errors table is rebuilt -
    see app/db_utils/detector_sql.py.

    Both of those matter. Slicing the table down to just the wrangled columns - which this did
    between 33f0e34 and the pandas rewrite - drops "ID", so the detectors minted fresh positional ids and every
    row_id in errors_<table> ended up naming a row *position* rather than a row. And updating only
    the wrangled columns' rows leaves error rows for every other column pointing at ids that a
    delete has since removed. A full rebuild has neither problem. See tests/sql/test_errors_row_id.py.
    """
    try:
        DetectorSQL(engine, table_name).generate_errors_table()
        print(f"✓ Updated errors table: errors_{table_name}")
    except Exception as e:
        print(f"ERROR: Could not update errors table for {table_name}: {e}")
        traceback.print_exc()
        raise

# TODO: Make update_data_profile_table and update_errors_table more similar
# TODO: Re-implement with "dirty flags"
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


# TODO: Finish this later
#def update_stat_to_data_profile_table(table_name: str, error_df: pd.DataFrame) -> None:






# ─────────────────────────────────────────────────────────────────────────────
# Wrangling Endpoints
# create-previews works out every way of repairing the rows the user selected and stages each as a candidate:
# a provisional node of the graph, with its own table, that the user can analyse before accepting one. See
# app/server_utils/candidates.py, which stages the AI's suggestions the same way and accepts both.
# ─────────────────────────────────────────────────────────────────────────────


def _repair_options(cols, row_count):
    """
    The ways a selection can be repaired. Deleting removes the selected rows; imputing fills a column in them
    with its mean, or its most common value if it is categorical. A two-column selection can be imputed on
    either column.
    :return: [(op, imputed column, label, reason)]
    """
    rows = "the selected row" if row_count == 1 else f"the {row_count:,} selected rows"
    fill = lambda column: f"Fill {column} in {rows} with its mean, or its most common value if it is categorical"
    if len(cols) == 1:
        return [
            ("delete", None, "Delete rows", f"Remove {rows}"),
            ("impute", cols[0], f"Impute {cols[0]}", fill(cols[0])),
        ]
    return [
        ("delete", None, "Delete rows", f"Remove {rows}"),
        ("impute_x", cols[0], f"Impute {cols[0]}", fill(cols[0])),
        ("impute_y", cols[1], f"Impute {cols[1]}", fill(cols[1])),
    ]


@app.post("/api/wrangle/create-previews")
def create_previews():
    """
    Stage every way of repairing the current node's selected rows as a candidate: a provisional node under the
    current node, its wrangle already run on a copy of its table. Delete and impute for a one-column selection;
    delete, impute x and impute y for two.

    Body JSON:
      row_ids  – list of integer row IDs to operate on
      cols     – list of column names involved in the selection (for imputation)
      source   – the plot the selection was made on, "heatmap" or "scatterplot", which a two-column candidate's
                 preview chart draws as
    :return: {"success", "candidates": [...]} - see candidates.candidate_json
    """
    try:
        body = request.get_json(force=True)
        table   = db_operations.main_table_name
        row_ids = body.get("row_ids", [])
        cols    = body.get("cols", [])

        if not row_ids:
            return {"success": False, "error": "No rows selected"}, 400
        if len(cols) not in (1, 2):
            return {"success": False, "error": "A selection is on one column or two"}, 400

        chart_type = "histogram" if len(cols) == 1 else (body.get("source") or "heatmap")

        specs = []
        for op, imputed, label, reason in _repair_options(cols, len(row_ids)):
            meta = {"label": label, "reason": reason, "row_count": len(row_ids), "error_type": None,
                    "chart_type": chart_type}
            specs.append(candidates.CandidateSpec(op=op, cols=list(cols), row_ids=row_ids, imputed_column=imputed,
                                                  source="repair", meta=meta))

        # The repairs of one selection stand together, so they are built at once and staged all or none
        staged = candidates.stage_all(table, specs)
        return {"success": True, "candidates": staged}

    except candidates.CandidateError as e:
        return {"success": False, "error": str(e)}, 409
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
        table_name = db_operations.main_table_name
        column = body["column"]
        # Deleting a column changes the table in place - a candidate must be accepted before it is wrangled
        candidates.require_accepted(table_name)

        print(f"Deleting column '{column}' from table '{table_name}'")

        # Delete the column. The table keeps its name, so its cached column types have to be let go by hand
        remaining_columns = query.delete_column(table=table_name, column=column)
        ColumnTypes.forget(table_name)

        # Re-run error detection
        update_errors_table(table_name)
        update_data_profile_table(table_name, [column])

        return {
            "success": True,
            "remaining_columns": remaining_columns,
            "deleted_column": column
        }
    except candidates.CandidateError as e:
        return {"success": False, "error": str(e)}, 409
    except Exception as e:
        print("ERROR OCCURRED")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}, 400
