# This file handles all endpoints related to the pgraph - April 7, 2026

from flask import request
import app as app_package
from app import app, db_operations, engine
from app.pgraph.pgraph import PGraph
from app.pgraph.metrics import quality_trajectory
from app.pgraph.compare import PLOT_KINDS, load_node_state, compare_histogram, compare_heatmap
from app.pgraph.distortion import distortion_trajectory, drift_detail
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


@app.get("/api/pgraph/branch_trajectory")
def branch_trajectory():
    """
    How data quality evolves along one branch the user picked out of the graph.

    The branch is named by an edge and an end point: source -> target fixes which way out of source
    the branch leaves, and destination fixes where it stops. The edge is what disambiguates a source
    with more than one child - without it, "everything below source" is several different branches.

    Query: ?source=<node>&target=<node>&destination=<node>
    Returns the branch's node sequence and, per quality dimension, the value series with each step's
    delta and contribution. Reads the metrics cached on each node at creation - nothing is recomputed.
    """
    try:
        # The session's graph hangs off the app package, not the Flask object
        pgraph = app_package.pgraph_for_session
        if pgraph is None:
            return {"success": False, "error": "no graph in this session"}, 400

        source = request.args.get("source")
        target = request.args.get("target")
        destination = request.args.get("destination")

        for name, value in (("source", source), ("target", target), ("destination", destination)):
            if not value:
                return {"success": False, "error": f"missing {name}"}, 400

        path = pgraph.path_between(source, destination)
        if path is None:
            return {"success": False,
                    "error": f"{destination} is not downstream of {source}"}, 400

        # The destination has to lie beyond the chosen edge, not down a sibling branch
        if len(path) < 2 or path[1] != target:
            return {"success": False,
                    "error": f"{destination} is not on the branch leaving through {target}"}, 400

        ordered_metrics = [pgraph.node_map[table_name].metrics for table_name in path]

        return {
            "success": True,
            "source": source,
            "target": target,
            "destination": destination,
            "nodes": path,
            "dimensions": quality_trajectory(ordered_metrics),
            # Beside the error dimensions rather than among them: drift is a cost, not an error
            "distortion": distortion_trajectory([pgraph.node_map[table_name].distortion for table_name in path]),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 400


def _bounded_int(name, default, low, high):
    """An integer query parameter, clamped so a request cannot ask for an absurd amount of work."""
    return max(low, min(high, int(request.args.get(name, default))))


@app.get("/api/pgraph/compare")
def compare_nodes():
    """
    Plot data for comparing the data behind two nodes, binned on axes the two states share.

    Query: ?a=<node>&b=<node>&kind=histogram|heatmap&x=<column>[&y=<column>][&bins=10]
    a is selection A and b selection B; y is required for a heatmap. Returns the plot payload
    for that kind plus each side's row count.
    Read-only: neither node becomes the session's current table. See app/pgraph/compare.py.
    """
    try:
        pgraph = app_package.pgraph_for_session
        if pgraph is None:
            return {"success": False, "error": "no graph in this session"}, 400

        table_a = request.args.get("a")
        table_b = request.args.get("b")
        # Only tables the graph owns can be read, so a request cannot name an arbitrary table
        for name, value in (("a", table_a), ("b", table_b)):
            if not value:
                return {"success": False, "error": f"missing {name}"}, 400
            if value not in pgraph.node_map:
                return {"success": False, "error": f"{value} is not a node in this graph"}, 400

        kind = request.args.get("kind", "histogram")
        if kind not in PLOT_KINDS:
            return {"success": False, "error": f"unknown plot kind {kind!r}"}, 400

        x_column = request.args.get("x")
        y_column = request.args.get("y") if kind != "histogram" else None
        if not x_column:
            return {"success": False, "error": "missing x"}, 400
        if kind != "histogram" and not y_column:
            return {"success": False, "error": f"a {kind} needs a y column"}, 400

        bin_count = _bounded_int("bins", 10, 1, 50)

        columns = [x_column] if y_column is None else [x_column, y_column]
        state_a = load_node_state(engine, table_a, columns)
        state_b = load_node_state(engine, table_b, columns)

        plot = (compare_histogram(state_a, state_b, x_column, bin_count) if kind == "histogram"
                else compare_heatmap(state_a, state_b, x_column, y_column, bin_count))

        return {
            "success": True,
            "kind": kind,
            "a": table_a,
            "b": table_b,
            "x": x_column,
            "y": y_column,
            "rows": {"a": len(state_a.data), "b": len(state_b.data)},
            **plot,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 400


def _requested_node(pgraph):
    """
    The node a request names, refusing anything that is not a node in this session's graph.
    :return: (node, None), or (None, an error response)
    """
    node = request.args.get("node")
    if not node:
        return None, ({"success": False, "error": "missing node"}, 400)
    if node not in pgraph.node_map:
        return None, ({"success": False, "error": f"{node} is not a node in this graph"}, 400)
    return node, None


@app.get("/api/pgraph/drift_detail")
def drift_detail_view():
    """
    What the compare modal's Drift views draw for one node and one column: the ridgeline curves or the
    Sankey flows, and a plain-language annotation.

    Query: ?node=<node>&column=<column>[&keep=<category>&keep=<category>...][&base=<node>]
    base measures from one of the node's ancestors instead of root - the modal sends the two selections'
    common ancestor. Read-only: the node does not become the session's current table.
    """
    try:
        pgraph = app_package.pgraph_for_session
        if pgraph is None:
            return {"success": False, "error": "no graph in this session"}, 400

        node, error = _requested_node(pgraph)
        if error:
            return error

        column = request.args.get("column")
        if not column:
            return {"success": False, "error": "missing column"}, 400

        # Only an ancestor's rows are sure to hold the node's, which every number in the detail leans on
        base = request.args.get("base") or None
        if base is not None:
            if base not in pgraph.node_map:
                return {"success": False, "error": f"{base} is not a node in this graph"}, 400
            if pgraph.path_between(base, node) is None:
                return {"success": False, "error": f"{base} is not an ancestor of {node}"}, 400

        # The categories the modal wants kept out of the catch-all, when the reader has chosen any
        keep = request.args.getlist("keep") or None
        return {"success": True, **drift_detail(pgraph, node, column, keep, base)}
    except Exception as e:
        return {"success": False, "error": str(e)}, 400
