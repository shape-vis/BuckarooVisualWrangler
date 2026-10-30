"""
The error types, read once from shared/error_types.json - October 29, 2026

The one list of error types the app has: the backend and the frontend both read it from that file, so a new detector's
type, its label and its colour are written down once. Its keys, in order, are ERROR_TYPES in
app/db_utils/detector_sql.py, which every query, metric and tool loops over.
"""
import json
from pathlib import Path

ERROR_TYPES_FILE = Path(__file__).resolve().parents[1] / "shared" / "error_types.json"


def _read_error_types():
    with open(ERROR_TYPES_FILE, encoding="utf-8") as file:
        return json.load(file)["error_types"]


# Each error type as the file describes it, in its order
ERROR_TYPE_ENTRIES = _read_error_types()


def error_type_keys():
    """The error types' keys, in order - "missing", "mismatch", ..."""
    keys = []
    for entry in ERROR_TYPE_ENTRIES:
        keys.append(entry["key"])
    return tuple(keys)
