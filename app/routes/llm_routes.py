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
        plans = orchestrator.propose_plans(node_table)
        return {"success": True, "proposals": proposals, "plans": plans}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500


@app.post("/api/llm/materialize-plan")
def llm_materialize_plan():
    body = request.get_json(force=True, silent=True) or {}
    node_table = body.get("node_table")
    plan = body.get("plan")
    if not node_table or not plan:
        return {"success": False, "error": "node_table and plan are required"}, 400
    try:
        return {"success": True, **orchestrator.materialize_plan(node_table, plan)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500


@app.post("/api/llm/preview")
def llm_preview():
    body = request.get_json(force=True, silent=True) or {}
    node_table = body.get("node_table")
    proposal = body.get("proposal")
    if not node_table or not proposal:
        return {"success": False, "error": "node_table and proposal are required"}, 400
    try:
        return {"success": True, **orchestrator.preview(node_table, proposal)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500


@app.post("/api/llm/preview-plan")
def llm_preview_plan():
    body = request.get_json(force=True, silent=True) or {}
    node_table = body.get("node_table")
    plan = body.get("plan")
    if not node_table or not plan:
        return {"success": False, "error": "node_table and plan are required"}, 400
    try:
        return {"success": True, **orchestrator.preview_plan(node_table, plan)}
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
