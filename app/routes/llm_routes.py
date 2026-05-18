"""LLM orchestration routes.

Auto-registered by app/__init__.py's iter_modules sweep.
"""
from flask import request

from app import app
from app.llm import orchestrator


@app.post("/api/llm/analyze")
def llm_analyze():
    body = request.get_json(force=True, silent=True) or {}
    node_table = body.get("node_table")
    if not node_table:
        return {"success": False, "error": "node_table is required"}, 400
    try:
        proposals = orchestrator.analyze(node_table)
        return {"success": True, "proposals": proposals}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500


@app.post("/api/llm/materialize")
def llm_materialize():
    body = request.get_json(force=True, silent=True) or {}
    node_table = body.get("node_table")
    proposal = body.get("proposal")
    if not node_table or not proposal:
        return {"success": False, "error": "node_table and proposal are required"}, 400
    try:
        result = orchestrator.materialize(node_table, proposal)
        return {"success": True, **result}
    except NotImplementedError as e:
        return {"success": False, "error": str(e)}, 501
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500
