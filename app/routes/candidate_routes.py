"""
Accepting and declining candidates - October 12, 2026

A candidate is a wrangle staged as a provisional node, whether it came from repairing the user's selection
(/api/wrangle/create-previews) or from the AI (/api/ai/suggest). Both are accepted and declined here, the same
way - see app/server_utils/candidates.py.

Registered automatically by the pkgutil sweep in app/__init__.py.
"""
import traceback

from flask import request

from app import app
from app.server_utils import candidates


@app.post("/api/candidates/accept")
def accept_candidate():
    """
    Accept a candidate into the graph for good, and move the session onto it. Its siblings stay staged.

    Body: {"table": "c7_adult_x7f2q"}
    :return: {"success", "table", "label", "parent"}
    """
    body = request.get_json(force=True, silent=True) or {}
    table = body.get("table")
    if not isinstance(table, str) or not table:
        return {"success": False, "error": "table is required"}, 400
    try:
        return candidates.accept(table)
    except candidates.CandidateError as exc:
        return {"success": False, "error": str(exc)}, 409
    except Exception as exc:
        print("ERROR in accept_candidate")
        print(traceback.format_exc())
        return {"success": False, "error": str(exc)}, 500


@app.post("/api/candidates/discard")
def discard_candidates():
    """
    Decline candidates: drop their nodes and tables. When the session was on one, it moves to the parent.

    Body: {"tables": ["c7_adult_x7f2q", ...]}
    :return: {"success", "current": the table the session moved to, or null}
    """
    body = request.get_json(force=True, silent=True) or {}
    tables = body.get("tables")
    if not isinstance(tables, list) or not tables or not all(isinstance(t, str) for t in tables):
        return {"success": False, "error": "tables is required"}, 400
    try:
        return candidates.discard(tables)
    except candidates.CandidateError as exc:
        return {"success": False, "error": str(exc)}, 409
    except Exception as exc:
        print("ERROR in discard_candidates")
        print(traceback.format_exc())
        return {"success": False, "error": str(exc)}, 500
