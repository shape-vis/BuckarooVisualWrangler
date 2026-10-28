#Buckaroo Project - June 1, 2025 - Nicolas Baret


import os
import traceback

import pandas as pd
from flask import request, send_file

import app as app_package
from app import app
from app import db_operations, engine
from app.db_utils.execute_sql import copy_insert, errors_table_name
from app.server_utils.service_helpers import (
    WRANGLE_LOCK,
    build_node,
    generate_table_name,
    get_sqlalchemy_dtype_map,
    get_pgraph_redo,
    get_pgraph_undo,
    init_pgraph_for_session,
)
from app.server_utils.set_id_column import set_id_column
from app.pgraph.pgraph import node_id_for_count


def load_file(csv_file, filename):
    """
    Load an uploaded or provided csv as the session's root: read it into a pandas DataFrame, give each row an
    "ID", write it to the database under a unique table name, build the root's errors, data profile, metrics and
    drift there - the same build every node gets - and start the session's graph from it.

    :param csv_file: the local csv to use
    :param filename: the name of the csv_file
    :return: json object
    """
    dataframe = pd.read_csv(csv_file)

    table_with_id_added = set_id_column(dataframe)
    table_name = generate_table_name(filename)
    table_name_with_node_id = f"{node_id_for_count(0)}_{table_name}"
    # Build dtype map from actual column values before pushing to DB
    dtype_map = get_sqlalchemy_dtype_map(table_with_id_added)
    error_table_name = errors_table_name(table_name_with_node_id)

    try:
        # The rows go in through COPY, one stream, rather than one INSERT per row. "ID" names each row, so pandas'
        # own index is left out rather than stored as a column of its own
        table_with_id_added.to_sql(table_name_with_node_id, engine, if_exists='replace', dtype=dtype_map,
                                   method=copy_insert, index=False)

        # The root is detected, profiled, ranked and measured from the stored table, exactly as every node is
        root_metrics, root_distortion = build_node(table_name_with_node_id, table_name_with_node_id)

        init_pgraph_for_session(table_name_with_node_id, root_metrics, root_distortion)

        # Point DBOperations, made empty at startup in app/__init__.py, at the new root. The row counts are read back
        # from the tables, since the number .to_sql returns isn't guaranteed to be the rows it wrote
        db_operations.load_table(table_name_with_node_id)
        rows_affected = db_operations.get_row_count(table_name_with_node_id)
        detected_rows_affected = db_operations.get_row_count(error_table_name)

        return {"success": True, "rows for undetected data": rows_affected, "rows_for_detected": detected_rows_affected,
                "table_name": table_name_with_node_id}
    except Exception as e:
        print(f"Error in upload: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/upload")
def upload_csv():
    """
    Handles when a user uploads a csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    csv_file = request.files['file']
    return load_file(csv_file, csv_file.filename)


@app.get("/api/preloaded")
def preloaded_csv():
    """
    Handles when a user wants to use a preloaded csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    # Only the file's own name, so a request can't reach outside provided_datasets/
    csv_file = os.path.basename(request.args.get("file"))

    return load_file("provided_datasets/" + csv_file, csv_file)


@app.get("/api/tablename")
def get_tablename():
    """
    Returns the current active table name from the server-side DBOperations state.
    This is the single source of truth for which table the backend is operating on.
    """
    name = db_operations.main_table_name
    if name is None:
        return {"success": False, "error": "No table loaded"}, 400
    return {"success": True, "table_name": name}

def _move_to(table, missing_error):
    """
    Make a node the session's current table, once it is sure the table is still there.
    :param table: the node to move to
    :param missing_error: what to say when its table is gone
    :return: the response
    """
    if not db_operations.table_exists(table):
        return {"success": False, "error": missing_error}, 404

    db_operations.load_table(table)
    return {"success": True, "table_name": table}


@app.post("/api/undo")
def undo_wrangle():
    """
    Navigate to the previous version of the table
    """
    # Under the lock, so a candidate can't be declined - and its tables dropped - while the graph moves
    with WRANGLE_LOCK:
        prev = get_pgraph_undo()

        if prev is None:
            return {"success": False, "error": "Already at the root table, cannot undo further"}, 400

        return _move_to(prev, f"Table '{prev}' does not exist")


@app.post("/api/redo")
def redo_wrangle():
    """
    Navigate to the next version of the table: the node undo last stepped up from, or the current node's most recent
    child.
    """
    # Under the lock, as for undo
    with WRANGLE_LOCK:
        next_node = get_pgraph_redo()

        if next_node is None:
            return {"success": False, "error": "There is no further redo to execute"}, 404

        if next_node == db_operations.main_table_name:
            return {"success": False, "error": "You have reached the most up to date table"}

        return _move_to(next_node, "Table does not exist")


@app.post("/api/reset")
def reset_app():
    """
    Resets the server-side session when the user navigates back to the home page.
    """
    # Candidates are only ever staged; leaving the session drops them rather than their tables lingering
    from app.server_utils import candidates
    try:
        candidates.discard_all()
    except Exception as exc:  # never let cleanup stand in the way of leaving
        print(f"[reset] could not drop staged candidates: {exc}")

    # The graph goes too. A candidate build still running sees it has gone when it comes to register, and drops
    # its own tables instead of adding them to a graph nobody holds anymore
    with WRANGLE_LOCK:
        app_package.pgraph_for_session = None

    db_operations.reset()
    return {"success": True}


@app.get("/")
def home():
    return send_file("../ui/dist/index.html")
