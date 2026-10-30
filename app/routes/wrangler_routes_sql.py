# Buckaroo Project - July 2, 2025
# The repair endpoint: create-previews works out every way of repairing the rows the user selected and stages each
# as a candidate - a provisional node of the graph, with its own table, that the user can analyse before accepting
# one. See app/server_utils/candidates.py, which stages the AI's suggestions the same way and accepts both.

import traceback

from flask import request

from app import app, db_operations
from app.server_utils import candidates
from app.server_utils.wrangle_ops import repair_options

# The range of a bigint, which the table's "ID" column is: an id outside it names no row
SMALLEST_ROW_ID = -(2 ** 63)
LARGEST_ROW_ID = 2 ** 63 - 1


def _is_row_id(value):
    """
    Whether a request's value can name a row: a whole number, within a bigint's range. Anything else - a string, a
    fraction, a list - is refused, rather than handed to Postgres to cast, which would read 1.5 as row 2.
    """
    # A bool is an int to Python, but true is not a row
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return SMALLEST_ROW_ID <= value <= LARGEST_ROW_ID


def _is_list_of_columns(value):
    """Whether a request's value is a list of column names."""
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, str):
            return False
    return True


@app.post("/api/wrangle/create-previews")
def create_previews():
    """
    Stage every way of repairing the current node's selected rows as a candidate: a provisional node under the
    current node, its wrangle already run on a copy of its table. One candidate per operation in
    app/server_utils/wrangle_ops.py - delete and impute for a one-column selection; delete, impute x and impute y for
    two.

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
        if not isinstance(row_ids, list):
            return {"success": False, "error": "row_ids must be a list of row IDs"}, 400
        for row_id in row_ids:
            if not _is_row_id(row_id):
                return {"success": False, "error": f"{row_id!r} is not a row ID"}, 400
        if not _is_list_of_columns(cols) or len(cols) not in (1, 2):
            return {"success": False, "error": "A selection is on one column or two"}, 400

        # A one-column candidate's preview is a histogram; a two-column one draws as the plot it was selected on
        if len(cols) == 1:
            chart_type = "histogram"
        else:
            chart_type = body.get("source") or "heatmap"

        specs = []
        for op, imputed, label, reason in repair_options(cols, len(row_ids)):
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
