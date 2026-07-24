#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import pandas as pd
from flask import request, send_file
import time
from app import app
from app import db_operations, engine
from app.db_utils.data_profile import DataProfile 
from app.server_utils.service_helpers import (
    generate_base_table_name,
    create_error_df,
    get_sqlalchemy_dtype_map,
    calculate_attribute_rankings, get_pgraph_redo, get_pgraph_undo, init_pgraph_for_session, create_data_profile_df,
)
from app.server_utils.set_id_column import set_id_column


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
    dataframe = pd.read_csv(csv_file)

    # run the detectors on the uploaded file for the starting data state
    table_with_id_added = set_id_column(dataframe)
    start_time = time.time()
    detected_data = create_error_df(dataframe)
    time_to_detect = time.time() - start_time
    app.original_table_name = filename
    base_table_name = generate_base_table_name(filename)

    #initialize_action_log(engine)
    #update_action_log(dataset_id=base_table_name, action_name="load_dataset", action_details=None, engine=engine)

    table_name_with_node_id = f"n0_{base_table_name}"
    # Build dtype map from actual column values before pushing to DB
    dtype_map = get_sqlalchemy_dtype_map(table_with_id_added)
    error_table_name = f"errors_{table_name_with_node_id}"
    dp_table_name = f"dp_{table_name_with_node_id}"

    try:
        """
        pulled from the Pandas Docs for reference because these values returned by .to_sql is not the actual numbers:

        https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_sql.html

        The number of returned rows affected is the sum of the rowcount attribute of sqlite3.Cursor or SQLAlchemy
        connectable which may not reflect the exact number of written rows as stipulated in the sqlite3 or SQLAlchemy.
        """
        table_with_id_added.to_sql(table_name_with_node_id, engine, if_exists='replace', dtype=dtype_map)
        detected_data.to_sql(error_table_name, engine, if_exists='replace')
        data_profile = DataProfile(table_name_with_node_id, engine)

        data_profile_df = create_data_profile_df(data_profile)
        dtype_map = data_profile.dtype_dict

        data_profile_df.to_sql(dp_table_name, engine, if_exists='replace', dtype=dtype_map)

        """
        now we fully init the DBOperations object that was first initialized in init.py,
        get the actual row counts since .to_sql is buggy and not right
        """
        db_operations.load_table(table_name_with_node_id, error_table_name, dp_table_name, base_table_name=base_table_name)
        print("DB OPERATIONS LOAD_TABLE DONE")
        rows_affected = db_operations.get_row_count(table_name_with_node_id)
        detected_rows_affected = db_operations.get_row_count(error_table_name)

        #calculate the attribute rankings for the top 10 error rows table on the Buckaroo.tsx page
        rankings = calculate_attribute_rankings(detected_data)
        rankings.to_sql("rankings_" + table_name_with_node_id, engine, if_exists='replace', index=False)

        #init the pgraph
        init_pgraph_for_session(table_name_with_node_id)

        return {"success": True, "rows for undetected data": rows_affected, "rows_for_detected": detected_rows_affected,
                "table_name": table_name_with_node_id}
    except Exception as e:
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

    db_operations.load_table(prev, f"errors_{prev}", f"dp_{prev}")

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

    db_operations.load_table(next_node, f"errors_{next_node}", f"dp_{next_node}")
    return {"success": True, "table_name": next_node}


@app.post("/api/reset")
def reset_app():
    """
    Resets the server-side DBOperations state when the user navigates back to the home page.
    """
    db_operations.reset()
    return {"success": True}


@app.get("/")
def home():
    return send_file("../ui/dist/index.html")
