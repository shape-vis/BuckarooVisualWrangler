# This file handles all endpoints related to the pgraph - April 7, 2026

from flask import request
import app as app_package
from app import app, db_operations
from app.pgraph.pgraph import PGraph
from app.pgraph.metrics import quality_trajectory
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


@app.get("/api/pgraph/quality_trajectory")
def quality_trajectory_for_node():
    """
    How data quality evolves along every branch downstream of a node.

    One entry per downstream branch, each carrying the branch's node sequence and, per quality
    dimension, the value series plus the step deltas and contributions. A leaf node yields a single
    one-element branch with no deltas.

    Reads the metrics cached on each node when it was created - nothing is recomputed here.
    """
    try:
        # The session's graph hangs off the app package, not the Flask object
        pgraph = app_package.pgraph_for_session
        if pgraph is None:
            return {"success": False, "error": "no graph in this session"}, 400

        node_id = request.args.get("node") or pgraph.current_node_table_name
        if node_id not in pgraph.node_map:
            return {"success": False, "error": f"unknown node {node_id}"}, 400

        branches = []
        for path in pgraph.descendant_paths(node_id):
            ordered_metrics = [pgraph.node_map[table_name].metrics for table_name in path]
            branches.append({
                "nodes": path,
                "leaf": path[-1],
                # The branch's label - the wrangle that ends it reads better than its table name,
                # which is mostly a prefix shared with every other node
                "leaf_op": pgraph.node_map[path[-1]].wrangle_label(),
                "dimensions": quality_trajectory(ordered_metrics),
            })

        return {"success": True, "node": node_id, "branches": branches}
    except Exception as e:
        return {"success": False, "error": str(e)}, 400
