#Buckaroo Project - June 1, 2025
#This file handles all endpoints from the front-end


import csv
import math
import os
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request, send_file
from app import app, db_operations, engine
from app.service_helpers import (
    generate_table_name,
    refresh_errors_table,
    refresh_rankings_table,
)


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


def _coerce_value_for_sql_type(value, sql_type: str):
    trimmed = _trimmed_value(value)
    if trimmed == "":
        return ""

    if sql_type in {"BIGINT", "INTEGER", "SMALLINT"}:
        parsed_int = _parse_integer_literal(trimmed)
        return "" if parsed_int is None else str(parsed_int)

    if sql_type == "DOUBLE PRECISION":
        return trimmed

    if sql_type == "BOOLEAN":
        lowered = trimmed.lower()
        truthy = {"true", "t", "yes", "y", "1"}
        falsy = {"false", "f", "no", "n", "0"}
        if lowered in truthy:
            return "true"
        if lowered in falsy:
            return "false"
        return trimmed

    return trimmed


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
                    output_row[header] = _coerce_value_for_sql_type(
                        normalized_row.get(header, ""),
                        final_column_types[header]
                    )
            elif has_original_id:
                output_row = {"ID": row_id, "Original_ID": normalized_row.get("ID", "")}
                for header in final_headers:
                    if header in {"ID", "Original_ID"}:
                        continue
                    output_row[header] = _coerce_value_for_sql_type(
                        normalized_row.get(header, ""),
                        final_column_types[header]
                    )
                row_id += 1
            else:
                output_row = {"ID": row_id}
                for header in original_headers:
                    output_row[header] = _coerce_value_for_sql_type(
                        normalized_row.get(header, ""),
                        final_column_types[header]
                    )
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


def load_file(csv_file, filename):
    """
    Load a CSV into Postgres using a staged COPY-based flow,
    build SQL-backed errors/rankings tables,
    and return the dataset metadata.

    :param csv_file: the local csv to use
    :param filename: the name of the csv_file
    :return: json object
    """
    staged_upload_path = None
    transformed_upload_path = None
    try:
        table_name = generate_table_name(filename)

        if isinstance(csv_file, str):
            staged_upload_path = csv_file
        else:
            staged_upload = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
            staged_upload_path = staged_upload.name
            staged_upload.close()
            csv_file.save(staged_upload_path)

        analysis = _analyze_csv_upload(staged_upload_path)
        transformed_upload_path, final_headers, final_column_types = _build_final_csv_for_sql(
            staged_upload_path,
            analysis
        )
        _load_csv_into_postgres(
            transformed_upload_path,
            table_name,
            final_headers,
            final_column_types
        )
        detected_rows_affected = refresh_errors_table(
            table_name,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )
        refresh_rankings_table(
            table_name,
            anomaly_methods=["zscore"],
            rarity_threshold=0.05,
        )

        """
        now we fully init the DBOperations object that was first initialized in init.py,
        get the actual row counts since .to_sql is buggy and not right
        """
        db_operations.load_table(table_name)
        rows_affected = db_operations.get_row_count(table_name)
        detected_rows_affected = db_operations.get_row_count("errors_" + table_name)

        return {"success": True, "rows for undetected data": rows_affected, "rows_for_detected": detected_rows_affected,
                "table_name": table_name}
    except Exception as e:
        print(f"Error in upload: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if transformed_upload_path:
            try:
                os.remove(transformed_upload_path)
            except OSError:
                pass
        if staged_upload_path and not isinstance(csv_file, str):
            try:
                os.remove(staged_upload_path)
            except OSError:
                pass


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
