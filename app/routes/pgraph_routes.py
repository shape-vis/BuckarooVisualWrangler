# This file handles all endpoints related to the pgraph - April 7, 2026

from flask import request
from app import app, db_operations
from app.pgraph.pgraph import PGraph
from app.server_utils.service_helpers import get_current_pgraph, clicked_node_access_helper


@app.get("/api/routes/update_pgraph")
def update_pgraph():
    return get_current_pgraph()

@app.post("/api/setGraphToClickedNode")
def set_selected_node():
    try:
        body = request.get_json(force=True)
        clicked_node_id = body['nodeId']
        current_table_name = clicked_node_access_helper(clicked_node_id)
        db_operations.load_table(current_table_name, f"errors_{current_table_name}", f"dp_{current_table_name}")
        return {
            "success": True,
            "current_table_name": current_table_name
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 400
    