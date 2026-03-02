#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import numpy as np
import pandas as pd
from flask import request, render_template
import time
from app import app
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict, \
    init_session_data_state, fetch_detected_and_undetected_current_dataset_from_db, calculate_attribute_rankings, \
    _normalize_anomaly_methods, filter_error_dataframe_by_anomaly_methods, _normalize_rarity_threshold
from app import data_state_manager
from app.set_id_column import set_id_column
import json


def _parse_anomaly_methods_query_arg():
    raw = request.args.get("anomaly_methods")
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return _normalize_anomaly_methods(anomaly_methods=parsed, allow_empty=True)


def _parse_rarity_threshold_query_arg(default: float = 0.01):
    raw = request.args.get("rarity_threshold")
    if raw is None:
        return default
    return _normalize_rarity_threshold(raw, default=default)

@app.post("/api/upload")
def upload_csv():
    """
    Upload a CSV, persist it as a SQL table, run error detectors, and store error/ranking tables.

    Request form fields:
    - file: CSV file upload (required)
    - anomaly_methods: JSON list of anomaly methods (optional; e.g. ["zscore","mad","iqr"])
    - anomaly_method: single fallback method (optional; defaults to "zscore")
    """

    csv_file = request.files["file"]
    anomaly_methods_raw = request.form.get("anomaly_methods")
    anomaly_method = request.form.get("anomaly_method", "zscore")
    selected_anomaly_methods = None
    if anomaly_methods_raw:
        try:
            parsed = json.loads(anomaly_methods_raw)
            if isinstance(parsed, list):
                selected_anomaly_methods = parsed
        except json.JSONDecodeError:
            selected_anomaly_methods = None

    if selected_anomaly_methods is None:
        selected_anomaly_methods = [anomaly_method]
    selected_anomaly_methods = [
        str(method).strip().lower()
        for method in selected_anomaly_methods
        if str(method).strip().lower() in {"zscore", "mad", "iqr"}
    ] or ["zscore"]
    anomaly_method = selected_anomaly_methods[0]
    all_anomaly_methods = ["zscore", "mad", "iqr"]
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
        detected_data = run_detectors(
            cleaned_table_name,
            anomaly_method=anomaly_method,
            anomaly_methods=all_anomaly_methods
        )

        detected_data["raw_error_type"] = detected_data["error_type"]
        if "column_name" in detected_data.columns:
            if "column_id" not in detected_data.columns:
                detected_data["column_id"] = detected_data["column_name"]
            else:
                detected_data["column_id"] = detected_data["column_id"].fillna(detected_data["column_name"])

        # normalize
        anomaly_mask = detected_data["error_type"].str.contains("anomaly", na=False)
        detected_data.loc[anomaly_mask, "error_type"] = "anomaly"

        print("=== AFTER DETECTION ===")
        print("Unique error types (UI):", detected_data["error_type"].unique())
        print("Unique error types (raw):", detected_data["raw_error_type"].unique())

        if "mad" in all_anomaly_methods:
            print("Total MAD anomalies:",
                  (detected_data["raw_error_type"] == "mad_anomaly").sum())

        if "zscore" in all_anomaly_methods:
            print("Total Z-score anomalies:",
                  (detected_data["raw_error_type"] == "zscore_anomaly").sum())

        if "iqr" in all_anomaly_methods:
            print("Total IQR anomalies:",
                  (detected_data["raw_error_type"] == "iqr_anomaly").sum())

        time_to_detect = time.time() - start_time
        detected_rows_inserted = detected_data.to_sql(
            "errors" + cleaned_table_name,
            engine,
            if_exists="replace",
            index=False
        )

        rankings_source = filter_error_dataframe_by_anomaly_methods(
            detected_data,
            all_anomaly_methods,
            rarity_threshold=0.01
        )
        rankings = calculate_attribute_rankings(rankings_source)
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
                "anomaly_method": anomaly_method,
                "selected_anomaly_methods": selected_anomaly_methods,
                "detected_anomaly_methods": all_anomaly_methods
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
        selected_anomaly_methods = _parse_anomaly_methods_query_arg()
        selected_rarity_threshold = _parse_rarity_threshold_query_arg(default=0.01)
        full_error_df = filter_error_dataframe_by_anomaly_methods(
            full_error_df,
            selected_anomaly_methods,
            rarity_threshold=selected_rarity_threshold
        )
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
