#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import pandas as pd
from flask import request, send_file
import io
from pathlib import Path
import time
import zipfile
import app as app_module
from app import app
from app import db_operations, engine
from app.server_utils.service_helpers import (
    generate_table_name,
    run_detectors,
    get_sqlalchemy_dtype_map,
    calculate_attribute_rankings, get_pgraph_redo, get_pgraph_undo, init_pgraph_for_session,
    write_dataframe_to_sql,
    PROGRESSIVE_ROW_THRESHOLD,
    RUN_FULL_BACKGROUND_DETECTION,
    start_background_error_detection,
    get_upload_background_status,

)
from app.server_utils.pandas_export import (
    EXPORT_LIBRARY_FILENAME,
    read_export_library_source,
)
from app.server_utils.set_id_column import set_id_column
from app.server_utils.dataset_processing_metadata import save_dataset_processing_metadata


DETECTOR_SAMPLE_SEED = 20260714


def load_file(csv_file, filename):
    """
    This loads the csv from the local path of the repo that the user clicked;
    set's IDs to each row,
    puts the whole csv into a Pandas Dataframe,
    runs the python detectors the dataframe,
    generates a unique name for the table,
    and returns a JSON object of all the info.

    :param csv_file: the local csv to use
    :param filename: the name of the csv_file
    :return: json object
    """
    timings = {}

    def time_phase(label, fn):
        phase_start = time.perf_counter()
        result = fn()
        timings[label] = round(time.perf_counter() - phase_start, 3)
        return result

    total_start = time.perf_counter()

    dataframe = time_phase("read_csv", lambda: pd.read_csv(csv_file))

    # run the detectors on the uploaded file for the starting data state
    table_with_id_added = time_phase("set_id_column", lambda: set_id_column(dataframe))
    total_rows = len(table_with_id_added)
    use_progressive_loading = total_rows > PROGRESSIVE_ROW_THRESHOLD
    detector_input = (
        table_with_id_added.sample(
            n=PROGRESSIVE_ROW_THRESHOLD,
            replace=False,
            random_state=DETECTOR_SAMPLE_SEED,
        ).reset_index(drop=True)
        if use_progressive_loading
        else table_with_id_added
    )
    detected_data = time_phase("run_detectors", lambda: run_detectors(detector_input))
    if use_progressive_loading:
        timings["run_detectors_scope"] = f"sample_{PROGRESSIVE_ROW_THRESHOLD}"
    app_module.get_session_state().original_table_name = filename
    table_name = generate_table_name(filename)
    table_name_with_node_id = f"n0_{table_name}"
    # Build dtype map from actual column values before pushing to DB
    dtype_map = time_phase("build_dtype_map", lambda: get_sqlalchemy_dtype_map(table_with_id_added))

    try:
        """
        pulled from the Pandas Docs for reference because these values returned by .to_sql is not the actual numbers:

        https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_sql.html

        The number of returned rows affected is the sum of the rowcount attribute of sqlite3.Cursor or SQLAlchemy
        connectable which may not reflect the exact number of written rows as stipulated in the sqlite3 or SQLAlchemy.
        """
        rows_affected = time_phase(
            "write_main_table",
            lambda: write_dataframe_to_sql(
                table_with_id_added,
                table_name_with_node_id,
                engine,
                if_exists='replace',
                dtype=dtype_map,
                index=False,
            ),
        )
        detected_rows_affected = time_phase(
            "write_errors_table",
            lambda: write_dataframe_to_sql(
                detected_data,
                "errors_" + table_name_with_node_id,
                engine,
                if_exists='replace',
                index=False,
            ),
        )

        """
        now we fully init the DBOperations object that was first initialized in init.py,
        get the actual row counts since .to_sql is buggy and not right
        """
        time_phase("load_db_operations", lambda: db_operations.load_table(table_name_with_node_id))
        rows_affected = time_phase("count_main_rows", lambda: db_operations.get_row_count(table_name_with_node_id))
        detected_rows_affected = time_phase(
            "count_error_rows",
            lambda: db_operations.get_row_count("errors_" + table_name_with_node_id),
        )

        #calculate the attribute rankings for the top 10 error rows table on the Buckaroo.tsx page
        rankings = time_phase("calculate_rankings", lambda: calculate_attribute_rankings(detected_data))
        time_phase(
            "write_rankings_table",
            lambda: write_dataframe_to_sql(
                rankings,
                "rankings_" + table_name_with_node_id,
                engine,
                if_exists='replace',
                index=False,
            ),
        )
        time_phase(
            "write_processing_metadata",
            lambda: save_dataset_processing_metadata(
                engine,
                table_name=table_name_with_node_id,
                total_rows=total_rows,
                detector_rows=len(detector_input),
                detector_is_complete=not use_progressive_loading,
                detector_sampling_method=(
                    "deterministic_random_without_replacement"
                    if use_progressive_loading
                    else "full_dataset"
                ),
                detector_sample_seed=DETECTOR_SAMPLE_SEED if use_progressive_loading else None,
            ),
        )

        #init the pgraph
        app_module.get_session_state().original_table_name = filename
        time_phase("init_pgraph", lambda: init_pgraph_for_session(table_name_with_node_id))
        background_detection_started = False
        if use_progressive_loading and RUN_FULL_BACKGROUND_DETECTION:
            background_detection_started = start_background_error_detection(
                table_name_with_node_id,
                total_rows=total_rows,
            )
            timings["background_detection"] = (
                "started" if background_detection_started else "skipped_row_limit"
            )
        elif use_progressive_loading:
            timings["background_detection"] = "skipped_sample_first_mode"
        timings["total"] = round(time.perf_counter() - total_start, 3)
        print(f"[UPLOAD TIMINGS] {filename}: {timings}")

        return {
            "success": True,
            "rows for undetected data": rows_affected,
            "rows_for_detected": detected_rows_affected,
            "table_name": table_name_with_node_id,
            "timings": timings,
            "loading_complete": not background_detection_started,
            "sample_rows": min(PROGRESSIVE_ROW_THRESHOLD, total_rows),
            "sample_mode": use_progressive_loading,
            "sampling_method": (
                "deterministic_random_without_replacement"
                if use_progressive_loading
                else "full_dataset"
            ),
            "sample_seed": DETECTOR_SAMPLE_SEED if use_progressive_loading else None,
            "total_rows": total_rows,
        }
    except Exception as e:
        timings["total"] = round(time.perf_counter() - total_start, 3)
        print(f"[UPLOAD TIMINGS][FAILED] {filename}: {timings}")
        print(f"Error in upload: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/upload")
def upload_csv():
    """
    Handles when a user uploads a csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    #get the file path from the DataFrame object sent by the user's upload in the view
    csv_file = request.files['file']
    return load_file(csv_file, csv_file.filename)


@app.get("/api/preloaded")
def preloaded_csv():
    """
    Handles when a user wants to use a preloaded csv to the app, creates a new table with it in the database
    :return: whether it was completed successfully
    """
    #get the file name from request args
    csv_file = request.args.get("file")
    csv_file = csv_file[csv_file.rfind("/") + 1:]

    return load_file("provided_datasets/" + csv_file, csv_file)


@app.get("/api/upload-status")
def upload_status():
    """
    Poll progressive-upload background work for a table.
    """
    table_name = request.args.get("table_name")
    if not table_name:
        return {"success": False, "error": "table_name is required"}, 400
    status = get_upload_background_status(table_name)
    return {"success": True, "table_name": table_name, **status}


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

@app.post("/api/undo")
def undo_wrangle():
    """
    Navigate to the previous version of the table
    """
    prev = get_pgraph_undo()

    if prev is None:
        return {"success": False, "error": "Already at the root table, cannot undo further"}, 400

    if not db_operations.table_exists(prev):
        return {"success": False, "error": f"Table '{prev}' does not exist"}, 404

    db_operations.load_table(prev, f"errors_{prev}")

    return {"success": True, "table_name": prev}


@app.post("/api/redo")
def redo_wrangle():
    """
    Navigate to the next version of the table (increment node ID).
    e.g. n1_data_xyz -> n2_data_xyz
    """
    next_node = get_pgraph_redo()

    if next_node is None:
        return {"success": False, "error": "There is no further redo to execute"}, 404

    if not db_operations.table_exists(next_node):
        return {"success": False, "error": "Table does not exist"}, 404

    if next_node == db_operations.main_table_name:
        return {"success": False, "error": "You have reached the most up to date table"}

    db_operations.load_table(next_node, f"errors_{next_node}")
    return {"success": True, "table_name": next_node}


@app.post("/api/reset")
def reset_app():
    """
    Resets the server-side DBOperations state when the user navigates back to the home page.
    """
    db_operations.reset()
    session_state = app_module.get_session_state()
    session_state.pgraph_for_session = None
    session_state.original_table_name = "data.csv"
    return {"success": True}


@app.get("/api/export/pandas")
def export_pandas():
    """
    Returns a zip with a Pandas script that replicates the current data state
    plus the helper library the script imports.
    """
    # The export is only meaningful after a dataset has been loaded. The
    # DBOperations object tracks the current table name that the UI is viewing.
    current_table = db_operations.main_table_name
    if not current_table:
        return {"success": False, "error": "No table loaded"}, 400
    
    # The provenance graph stores the sequence of Deltas needed to recreate
    # that current table from the original CSV.
    session_state = app_module.get_session_state()
    if session_state.pgraph_for_session is None:
        return {"success": False, "error": "No provenance graph loaded"}, 400

    # get_script_to_node walks root -> current node and concatenates the Pandas
    # code stored in each Delta.
    script = session_state.pgraph_for_session.get_script_to_node(current_table)

    # The generated script imports its helpers from EXPORT_LIBRARY_FILENAME, so
    # both files are bundled together. The library is the single source of truth
    # for the export boilerplate, kept out of the generated script itself.
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("buckaroo_export.py", script)
        bundle.writestr(EXPORT_LIBRARY_FILENAME, read_export_library_source())
    archive.seek(0)

    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name="buckaroo_export.zip",
    )


@app.get("/")
def home():
    project_root = Path(__file__).resolve().parents[2]
    return send_file(project_root / "ui" / "dist" / "index.html")
