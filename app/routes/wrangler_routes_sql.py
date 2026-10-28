# Buckaroo Project - July 2, 2025
# The repair endpoint: create-previews works out every way of repairing the rows the user selected and stages each
# as a candidate - a provisional node of the graph, with its own table, that the user can analyse before accepting
# one. See app/server_utils/candidates.py, which stages the AI's suggestions the same way and accepts both.

import traceback

from flask import request

from app import app, db_operations
from app.server_utils import candidates


def _repair_options(cols, row_count):
    """
    The ways a selection can be repaired. Deleting removes the selected rows; imputing fills a column in them
    with its mean, or its most common value if it is categorical. A two-column selection can be imputed on
    either column.
    :return: [(op, imputed column, label, reason)]
    """
    if row_count == 1:
        rows = "the selected row"
    else:
        rows = f"the {row_count:,} selected rows"

    def fill(column):
        return f"Fill {column} in {rows} with its mean, or its most common value if it is categorical"

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

        # A one-column candidate's preview is a histogram; a two-column one draws as the plot it was selected on
        if len(cols) == 1:
            chart_type = "histogram"
        else:
            chart_type = body.get("source") or "heatmap"

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
