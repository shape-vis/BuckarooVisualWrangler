#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end

import csv
import json
import math
import os
import tempfile
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd
from flask import request, render_template
from sqlalchemy import text
from app import app
from app import connection, engine
from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, \
    init_session_data_state, fetch_detected_and_undetected_current_dataset_from_db, \
    _normalize_anomaly_methods, _normalize_rarity_threshold, \
    refresh_rankings_table, refresh_errors_table
from app import data_state_manager


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


MISSING_TEXT_SENTINELS = {"", "null", "undefined"}
DATETIME_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%m/%d/%Y",
    "%Y/%m/%d",
)


def _normalize_csv_header(header: str, fallback_index: int) -> str:
    normalized = str(header or "").strip()
    return normalized or f"column_{fallback_index}"


def _normalize_cell_value(value):
    if value is None:
        return ""
    return str(value)


def _trimmed_value(value) -> str:
    return _normalize_cell_value(value).strip()


def _is_missing_like(value) -> bool:
    return _trimmed_value(value).lower() in MISSING_TEXT_SENTINELS


def _is_integer_literal(value) -> bool:
    trimmed = _trimmed_value(value)
    if trimmed == "":
        return False
    try:
        decimal_value = Decimal(trimmed)
    except InvalidOperation:
        return False
    return decimal_value == decimal_value.to_integral_value()


def _parse_integer_literal(value):
    if not _is_integer_literal(value):
        return None
    return int(Decimal(_trimmed_value(value)))


def _is_numeric_literal(value) -> bool:
    trimmed = _trimmed_value(value)
    if trimmed == "":
        return False
    try:
        decimal_value = Decimal(trimmed)
    except InvalidOperation:
        return False
    return math.isfinite(float(decimal_value))


def _is_boolean_literal(value) -> bool:
    return _trimmed_value(value).lower() in {"true", "false", "t", "f", "yes", "no", "y", "n"}


def _is_datetime_literal(value) -> bool:
    trimmed = _trimmed_value(value)
    if trimmed == "":
        return False
    for fmt in DATETIME_FORMATS:
        try:
            datetime.strptime(trimmed, fmt)
            return True
        except ValueError:
            continue
    return False


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _initialize_column_states(headers):
    return {
        header: {
            "has_non_missing": False,
            "is_integer": True,
            "is_numeric": True,
            "is_boolean": True,
            "is_datetime": True,
        }
        for header in headers
    }


def _update_column_states(column_states, row):
    for header, state in column_states.items():
        value = row.get(header, "")
        if _is_missing_like(value):
            continue
        state["has_non_missing"] = True
        state["is_integer"] = state["is_integer"] and _is_integer_literal(value)
        state["is_numeric"] = state["is_numeric"] and _is_numeric_literal(value)
        state["is_boolean"] = state["is_boolean"] and _is_boolean_literal(value)
        state["is_datetime"] = state["is_datetime"] and _is_datetime_literal(value)


def _infer_sql_type(column_state) -> str:
    if not column_state["has_non_missing"]:
        return "TEXT"
    if column_state["is_integer"]:
        return "BIGINT"
    if column_state["is_numeric"]:
        return "DOUBLE PRECISION"
    if column_state["is_boolean"]:
        return "BOOLEAN"
    if column_state["is_datetime"]:
        return "TIMESTAMP"
    return "TEXT"


def _analyze_csv_upload(csv_path: str):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise ValueError("CSV file must include a header row.")

        original_fieldnames = list(reader.fieldnames)
        headers = [_normalize_csv_header(header, idx) for idx, header in enumerate(original_fieldnames, start=1)]
        has_original_id = "ID" in headers
        column_states = _initialize_column_states(headers)
        row_count = 0
        id_is_valid = has_original_id
        seen_ids = set()

        for row in reader:
            normalized_row = {
                normalized_header: _normalize_cell_value(row.get(original_header, ""))
                for normalized_header, original_header in zip(headers, original_fieldnames)
            }
            row_count += 1
            _update_column_states(column_states, normalized_row)

            if has_original_id and id_is_valid:
                parsed_id = _parse_integer_literal(normalized_row.get("ID", ""))
                if parsed_id is None or parsed_id in seen_ids:
                    id_is_valid = False
                else:
                    seen_ids.add(parsed_id)

        return {
            "headers": headers,
            "original_fieldnames": original_fieldnames,
            "row_count": row_count,
            "column_states": column_states,
            "has_original_id": has_original_id,
            "id_is_valid": id_is_valid and has_original_id,
        }


def _build_final_csv_for_sql(csv_path: str, analysis: dict):
    has_original_id = analysis["has_original_id"]
    keep_original_id = analysis["id_is_valid"]
    original_headers = analysis["headers"]
    original_fieldnames = analysis["original_fieldnames"]

    if keep_original_id:
        final_headers = ["ID"] + [header for header in original_headers if header != "ID"]
    elif has_original_id:
        final_headers = ["ID", "Original_ID"] + [header for header in original_headers if header != "ID"]
    else:
        final_headers = ["ID"] + original_headers

    final_column_types = {"ID": "BIGINT"}
    if keep_original_id:
        for header in original_headers:
            if header == "ID":
                continue
            final_column_types[header] = _infer_sql_type(analysis["column_states"][header])
    elif has_original_id:
        final_column_types["Original_ID"] = "TEXT"
        for header in original_headers:
            if header == "ID":
                continue
            final_column_types[header] = _infer_sql_type(analysis["column_states"][header])
    else:
        for header in original_headers:
            final_column_types[header] = _infer_sql_type(analysis["column_states"][header])

    temp_output = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", delete=False, suffix=".csv")
    temp_output_path = temp_output.name
    row_id = 1

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as infile, temp_output:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(temp_output, fieldnames=final_headers)
        writer.writeheader()

        for row in reader:
            normalized_row = {
                normalized_header: _normalize_cell_value(row.get(original_header, ""))
                for normalized_header, original_header in zip(original_headers, original_fieldnames)
            }

            if keep_original_id:
                output_row = {"ID": _parse_integer_literal(normalized_row.get("ID", ""))}
                for header in final_headers:
                    if header == "ID":
                        continue
                    output_row[header] = normalized_row.get(header, "")
            elif has_original_id:
                output_row = {"ID": row_id, "Original_ID": normalized_row.get("ID", "")}
                for header in final_headers:
                    if header in {"ID", "Original_ID"}:
                        continue
                    output_row[header] = normalized_row.get(header, "")
                row_id += 1
            else:
                output_row = {"ID": row_id}
                for header in original_headers:
                    output_row[header] = normalized_row.get(header, "")
                row_id += 1

            writer.writerow(output_row)

    return temp_output_path, final_headers, final_column_types


def _load_csv_into_postgres(csv_path: str, table_name: str, headers, column_types) -> None:
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS {_quote_identifier(table_name)} CASCADE')
            column_definitions = ", ".join(
                f'{_quote_identifier(header)} {column_types[header]}'
                for header in headers
            )
            cursor.execute(
                f'CREATE TABLE {_quote_identifier(table_name)} ({column_definitions}, PRIMARY KEY ("ID"))'
            )

            with open(csv_path, "r", encoding="utf-8", newline="") as infile:
                copy_sql = (
                    f'COPY {_quote_identifier(table_name)} '
                    f'({", ".join(_quote_identifier(header) for header in headers)}) '
                    "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
                )
                cursor.copy_expert(copy_sql, infile)

        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()

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
    initial_anomaly_methods = ["zscore"]
    initial_rarity_threshold = 0.01

    cleaned_table_name = clean_table_name(csv_file.filename)
    staged_upload = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    staged_upload_path = staged_upload.name
    staged_upload.close()
    csv_file.save(staged_upload_path)
    transformed_upload_path = None

    try:
        analysis = _analyze_csv_upload(staged_upload_path)
        transformed_upload_path, final_headers, final_column_types = _build_final_csv_for_sql(
            staged_upload_path,
            analysis
        )
        _load_csv_into_postgres(
            transformed_upload_path,
            cleaned_table_name,
            final_headers,
            final_column_types
        )
        rows_inserted = analysis["row_count"]

        start_time = time.time()
        detected_data = run_detectors(
            cleaned_table_name,
            anomaly_method=anomaly_method,
            anomaly_methods=initial_anomaly_methods,
            rarity_threshold=initial_rarity_threshold
        )
        time_to_detect = time.time() - start_time
        detected_rows_inserted = refresh_errors_table(
            cleaned_table_name,
            anomaly_method=anomaly_method,
            anomaly_methods=initial_anomaly_methods,
            rarity_threshold=initial_rarity_threshold
        )

        refresh_rankings_table(
            cleaned_table_name,
            anomaly_methods=initial_anomaly_methods,
            rarity_threshold=initial_rarity_threshold
        )

        json.dump(
            {
                "db": cleaned_table_name,
                "clean_time": time_to_detect,
                "dataframe_shape": list(detected_data.shape),
                "anomaly_method": anomaly_method,
                "selected_anomaly_methods": selected_anomaly_methods,
                "detected_anomaly_methods": initial_anomaly_methods
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
    finally:
        try:
            os.remove(staged_upload_path)
        except OSError:
            pass
        if transformed_upload_path:
            try:
                os.remove(transformed_upload_path)
            except OSError:
                pass

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
    try:
        selected_anomaly_methods = _parse_anomaly_methods_query_arg()
        selected_rarity_threshold = _parse_rarity_threshold_query_arg(default=0.01)
        selected_methods = selected_anomaly_methods or ["zscore"]
        detector_rows = run_detectors(
            cleaned_table_name,
            anomaly_methods=selected_methods,
            rarity_threshold=selected_rarity_threshold
        )
        limited_rows = detector_rows[detector_rows["row_id"].between(1, data_size_int)]

        data_sized_error_dictionary = {}
        for _, row in limited_rows.iterrows():
            col = row["column_id"]
            row_id = row["row_id"]
            error_type = row["error_type"]
            if col is None or str(col).strip() == "":
                col = "Unknown"
            data_sized_error_dictionary.setdefault(col, {}).setdefault(row_id, []).append(error_type)

        print("=== GET-ERRORS ROUTE ===")
        print("Errors returned to frontend:", len(limited_rows))
        print("Unique error types sent:", sorted(set(limited_rows["error_type"].tolist())))
        return data_sized_error_dictionary
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/")
def home():
    return render_template('index.html')

@app.get('/data_cleaning_vis_tool')
def data_cleaning_vis_tool():
    return render_template('data_cleaning_vis_tool.html')
