#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import numpy as np
import pandas as pd
from flask import request, render_template
import time
from app import app
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict, \
    init_session_data_state, fetch_detected_and_undetected_current_dataset_from_db, calculate_attribute_rankings
from app import data_state_manager
from app.set_id_column import set_id_column
import json

@app.post("/api/upload")
def upload_csv():

    csv_file = request.files["file"]
    anomaly_method = request.form.get("anomaly_method", "zscore")
    dataframe = pd.read_csv(csv_file)

    dataframe_with_id = set_id_column(dataframe)

    cleaned_table_name = clean_table_name(csv_file.filename)

    try:
        rows_inserted = dataframe_with_id.to_sql(
            cleaned_table_name,
            engine,
            if_exists="replace",
            index=False
        )

        start_time = time.time()
        detected_data = run_detectors(cleaned_table_name, anomaly_method=anomaly_method)

        detected_data["raw_error_type"] = detected_data["error_type"]

        # normalize
        anomaly_mask = detected_data["error_type"].str.contains("anomaly", na=False)
        detected_data.loc[anomaly_mask, "error_type"] = "anomaly"
        detected_data.loc[anomaly_mask, "column_id"] = detected_data.loc[anomaly_mask, "column_name"]

        print("=== AFTER DETECTION ===")
        print("Unique error types (UI):", detected_data["error_type"].unique())
        print("Unique error types (raw):", detected_data["raw_error_type"].unique())

        if anomaly_method == "mad":
            print("Total MAD anomalies:",
                (detected_data["raw_error_type"] == "mad_anomaly").sum())

        if anomaly_method == "zscore":
            print("Total Z-score anomalies:",
                (detected_data["raw_error_type"] == "zscore_anomaly").sum())

        time_to_detect = time.time() - start_time
        detected_rows_inserted = detected_data.to_sql(
            "errors" + cleaned_table_name,
            engine,
            if_exists="replace",
            index=False
        )

        rankings = calculate_attribute_rankings(detected_data)
        rankings.to_sql(
            "rankings" + cleaned_table_name,
            engine,
            if_exists="replace",
            index=False
        )

        json.dump(
            {
                "db": cleaned_table_name,
                "clean_time": time_to_detect,
                "dataframe_shape": list(detected_data.shape),
                "anomaly_method": anomaly_method
            },
            open(f"report/{cleaned_table_name}.json", "w")
        )

        return {
            "success": True,
            "rows_for_undetected": rows_inserted,
            "rows_for_detected": detected_rows_inserted,
            "clean_table_name": cleaned_table_name,
            "new_table_name": cleaned_table_name
        }

    except Exception as e:
        print(f"Error in upload: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500

@app.get("/api/get-sample")
def get_sample():
    """
    Constructs a postgresql query to get the undetected table data from the database
    :return: a dictionary of the table dataa
    """
    filename = request.args.get("filename")
    data_size = request.args.get("datasize")
    cleaned_table_name = clean_table_name(filename)

    if not filename:
        return {"success": False, "error": "Filename required"}
    QUERY = get_whole_table_query(cleaned_table_name,False) + " LIMIT "+ data_size
    try:
        fetch_detected_and_undetected_current_dataset_from_db(cleaned_table_name,engine)
        # sample_dataframe = pd.read_sql_query(QUERY, engine).to_dict(orient="records")
        sample_dataframe_as_dictionary = pd.read_sql_query(QUERY, engine).replace(np.nan, None).to_dict(orient="records")
        # print("First row:", sample_dataframe_as_dictionary[0])  # See what keys exist
        return sample_dataframe_as_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/get-errors")
def get_errors():
    """
    Constructs a postgresql query to get the error table corresponding to the current file from the database
    :return: a dictionary of the error table
    """
    filename = request.args.get("filename")
    data_size = request.args.get("datasize")
    data_size_int = int(data_size)
    cleaned_table_name = clean_table_name(filename)
    if not filename:
        return {"success": False, "error": "Filename required"}
    query = get_whole_table_query(cleaned_table_name,True)
    try:
        full_error_df = pd.read_sql_query(query, engine)
        print("=== GET-ERRORS ROUTE ===")
        print("Errors returned to frontend:", len(full_error_df))
        print("Unique error types sent:", full_error_df["error_type"].unique())

        data_sized_error_dictionary = create_error_dict(full_error_df,data_size_int)
        return data_sized_error_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/")
def home():
    return render_template('index.html')

@app.get('/data_cleaning_vis_tool')
def data_cleaning_vis_tool():
    return render_template('data_cleaning_vis_tool.html')