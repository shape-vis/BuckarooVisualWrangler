#Buckaroo Project - July 2, 2025,
#This file handles all endpoints surrounding plots

from flask import request
from pprint import pprint
import os, json, uuid
from app import app, engine
from app.service_helpers import group_by_attribute
from data_management.data_attribute_summary_integration import *
from data_management.data_integration import *
from data_management.data_scatterplot_integration import generate_scatterplot_sample_data
from pathlib import Path
import hashlib
from postgres_wrangling import query
import traceback
import time

# from data_management.data_integration import generate_1d_histogram_data


@app.get("/api/plots/1-d-histogram-data")
def get_1d_histogram():
    """
    Endpoint to return data to be used to construct the 1d histogram in the view, this endpoint expects the following parameters:
        1. tablename to pull data from
        2. column name to aggregate data for
        3. desired id min and max values of the table to return to the view
    :return: the data as a csv
    """
    # tablename = request.args.get("tablename")
    column_name = request.args.get("column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    number_of_bins = request.args.get("bins", default=10)

    try:
        print("in the try")
        binned_data = generate_1d_histogram_data(column_name, int(number_of_bins), min_id, max_id)

        return {"Success": True, "binned_data": binned_data}
    except Exception as e:

        return {"Success": False, "Error": str(e)}


EXPORT_DIR = Path("histogram_exports")          # change if you prefer another location
EXPORT_DIR.mkdir(parents=True, exist_ok=True)   # create once, no-op later

REPORT_DIR = Path("report")   # ../report
REPORT_DIR.mkdir(parents=True, exist_ok=True)                 # create once

def _hash_dict(obj: dict, *, algo: str = "sha256") -> str:
    """
    Return a stable hexadecimal digest of a JSON-serialisable object.
    - Uses a *canonical* JSON encoding (sorted keys, no extra spaces)
      so logically identical dicts give identical hashes.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    h = hashlib.new(algo)
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()

# @app.get("/api/plots/2-d-histogram-data")
# def get_2d_histogram():
#     x_column_name = request.args.get("x_column")
#     y_column_name = request.args.get("y_column")
#     min_id         = int(request.args.get("min_id", 0))
#     max_id         = int(request.args.get("max_id", 200))
#     max_id = 1_000_000
#     number_of_bins = int(request.args.get("bins", 10))
#     try:
#         binned_data = generate_2d_histogram_data(
#             x_column_name, y_column_name,
#             number_of_bins, number_of_bins,
#             min_id, max_id,
#         )
#             # dataframe = pd.read_sql_query("SELECT * FROM stackoverflow_db_uncleaned;", engine)
#             # print(dataframe.head(5))

#         # ── Compute deterministic file name ──────────────────────────────────
#         digest     = _hash_dict(binned_data)          # 64-char SHA-256 hex
#         file_name  = f"{digest[:16]}.json"            # shorten if you like
#         file_path  = EXPORT_DIR / file_name

#         # ── Write only if it doesn't exist already ───────────────────────────
#         with file_path.open("w", encoding="utf-8") as fp:
#             json.dump({
#                 "x_column_name": x_column_name,
#                 "y_column_name": y_column_name,
#                 "min_id": min_id,
#                 "max_id": max_id,
#                 "number_of_bins": number_of_bins,
#                 "binned_data": binned_data
                
#                 }, fp, ensure_ascii=False, indent=2)

#         return {
#             "Success":     True,
#             "file_name":   file_name,
#             "file_path":   str(file_path),
#             "binned_data": binned_data,
#         }

#     except Exception as e:
#         return {"Success": False, "Error": str(e)}

@app.get("/api/plots/2-d-histogram-data")
def get_2d_histogram():
    """
    Endpoint to return data to be used to construct the 2-D histogram in the view.
    Saves the histogram bin counts to disk as JSON, using a content hash
    so that the same data always re-uses the same file.
    # Generates a complete 2-D histogram (heat-map) for any two columns in the
    # `stackoverflow_db_uncleaned` table, using pure SQL:
    #   • Slices rows by `index` between `min_id` and `max_id`.
    #   • Detects whether each axis is numeric or categorical.
    #   • Numeric axes are binned with `width_bucket`; categorical axes keep
    #     distinct values intact.
    #   • Builds every possible (x-bin, y-bin) pair with a CROSS JOIN, then
    #     left-joins the real counts so bins with zero observations are included.
    #   • Returns a JSON-ready dict containing:
    #       - "histograms": list of records {"xBin", "yBin", "count", "xType", "yType"}
    #       - "scaleX" / "scaleY": numeric bin ranges or categorical labels.
    #   • No Python aggregation is performed—everything is computed inside Postgres,
    #     making it efficient even for large tables.
    """
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id         = int(request.args.get("min_id", 0))
    max_id         = int(request.args.get("max_id", 200))
    number_of_bins = int(request.args.get("bins", 10))

    table_name= request.args.get("table", None)
    # table_name = request.args.get("selected_sample", None).split('/')[-1].replace('.csv', '')


    try:
        binned_data = query.generate_2d_histogram_data(
            x_column=x_column_name,
            y_column=y_column_name,
            bins=number_of_bins,
            min_id=min_id,
            max_id=max_id,
            table_name=table_name,
            whole_table=True
        )
        # ── Compute deterministic file name ──────────────────────────────────
        digest     = _hash_dict(binned_data)          # 64-char SHA-256 hex
        file_name  = f"{digest[:16]}.json"            # shorten if you like
        file_path  = EXPORT_DIR / file_name

        # ── Write only if it doesn't exist already ───────────────────────────
        with file_path.open("w", encoding="utf-8") as fp:
            json.dump({
                "table_name": table_name,
                "x_column_name": x_column_name,
                "y_column_name": y_column_name,
                "min_id": min_id,
                "max_id": max_id,
                "number_of_bins": number_of_bins,
                "binned_data": binned_data
                
                }, fp, ensure_ascii=False, indent=2)
        return {
            "Success":     True,
            "binned_data": binned_data,
        }
    except Exception as e:
        report_path = REPORT_DIR / f"{uuid.uuid4().hex}.txt"   # random hash
        report_path.write_text(traceback.format_exc(), encoding="utf-8")
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/scatterplot")
def get_scatterplot_data():
    x_column_name = request.args.get("x_column")
    y_column_name = request.args.get("y_column")
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    error_sample_count = request.args.get("error_sample_count", default=30)
    total_sample_count = request.args.get("total_sample_count", default=100)

    try:
        scatterplot_data = generate_scatterplot_sample_data(x_column_name, y_column_name, int(min_id), int(max_id), int(error_sample_count), int(total_sample_count))
        return {"Success": True, "scatterplot_data": scatterplot_data}
    except Exception as e:
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/group-by")
def get_group_by():
    """
    Endpoint to return the data according to the specified column the user wishes to group by a specific attribute - ex. group ages by continent
    :return: the data as a csv
    """
    column_a_name = request.args.get("column_a")
    group_by_name = request.args.get("group_by")
    df = data_state_manager.get_current_state()["df"]
    column_a = df[column_a_name]
    group_by = df[group_by_name]
    try:
        if is_categorical(column_a) and is_categorical(group_by):
            new_df = group_by_attribute(df, column_a_name, group_by_name).to_json()
            return {"Success": True, "group_by": new_df}
        return {"Success": False, "Error": "Both column input to the group_by are not categorical"}
    except Exception as e:
        return {"Success": False, "Error": str(e)}


@app.get("/api/plots/undo")
def undo():
    """
    Undoes the previous action performed on the data
    :return: Nothing right now - can be changed according to what the view needs
    """
    try:
        data_state_manager.undo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        print(data_state_manager.get_current_state())
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        # print(current_df)
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}


#need range for 1d,2d, and scatterplot implement
@app.get("/api/plots/redo")
def redo():
    """
    Redoes the previous action performed on the data
    :return: Nothing right now - can be changed according to what the view needs
    """
    try:
        data_state_manager.redo()
        # the current state dictionary made up of {"df":wrangled_df,"error_df":new_error_df}
        print(data_state_manager.get_current_state())
        current_df = data_state_manager.get_current_state()["df"].to_dict("records")
        # print(current_df)
        return {"success": True, "df": current_df}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/plots/summaries")
def attribute_summaries():
    """
    Populates the error attribute summaries
    :return:
    """
    min_id = request.args.get("min_id", default=0)
    max_id = request.args.get("max_id", default=200)
    try:
        #get the current error table
        print("in the get summaries")
        table_attribute_summaries = generate_complete_json(int(min_id), int(max_id))
        return {"success": True, "data": table_attribute_summaries}
    except Exception as e:
        return {"success": False, "error": str(e)}



