# This file handles all endpoints related to the pgraph - April 7, 2026

from flask import request
from app import app, db_operations, engine
from app.pgraph.metrics import quality_trajectory
from app.db_utils.compare_sql import PLOT_KINDS, CompareSQL
from app.pgraph.distortion import distortion_trajectory, drift_detail
from app.server_utils.service_helpers import (
    WRANGLE_LOCK,
    clicked_node_access_helper,
    get_current_pgraph,
    session_graph,
)


def _graph_or_error():
    """:return: (the session's graph, None), or (None, an error response) before anything has been uploaded"""
    pgraph = session_graph()
    if pgraph is None:
        return None, ({"success": False, "error": "no graph in this session"}, 400)
    return pgraph, None


@app.get("/api/routes/update_pgraph")
def update_pgraph():
    return get_current_pgraph()

@app.post("/api/setGraphToClickedNode")
def set_selected_node():
    try:
        body = request.get_json(force=True)
        clicked_node_id = body['nodeId']
        # Under the lock, so a candidate can't be declined - and its tables dropped - between moving onto it and
        # loading it
        with WRANGLE_LOCK:
            current_table_name = clicked_node_access_helper(clicked_node_id)
            db_operations.load_table(current_table_name)
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
        pgraph, error = _graph_or_error()
        if error:
            return error

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

        ordered_metrics = []
        ordered_distortions = []
        for table_name in path:
            node = pgraph.node_map[table_name]
            ordered_metrics.append(node.metrics)
            ordered_distortions.append(node.distortion)

        return {
            "success": True,
            "source": source,
            "target": target,
            "destination": destination,
            "nodes": path,
            "dimensions": quality_trajectory(ordered_metrics),
            # Beside the error dimensions rather than among them: drift is a cost, not an error
            "distortion": distortion_trajectory(ordered_distortions),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 400


def _bounded_int(name, default, low, high):
    """An integer query parameter, clamped so a request cannot ask for an absurd amount of work."""
    value = int(request.args.get(name, default))
    return max(low, min(high, value))


@app.get("/api/pgraph/compare")
def compare_nodes():
    """
    Plot data for comparing the data behind two nodes, binned on axes the two states share.

    Query: ?a=<node>&b=<node>&kind=histogram|heatmap&x=<column>[&y=<column>][&bins=10]
    a is selection A and b selection B; y is required for a heatmap. Returns the plot payload
    for that kind plus each side's row count, both built in Postgres - see app/db_utils/compare_sql.py.
    Read-only: neither node becomes the session's current table.
    """
    try:
        pgraph, error = _graph_or_error()
        if error:
            return error

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
        y_column = None
        if kind != "histogram":
            y_column = request.args.get("y")
        if not x_column:
            return {"success": False, "error": "missing x"}, 400
        if kind != "histogram" and not y_column:
            return {"success": False, "error": f"a {kind} needs a y column"}, 400

        bin_count = _bounded_int("bins", 10, 1, 50)

        compare = CompareSQL(engine, table_a, table_b)
        if kind == "histogram":
            plot = compare.generate_compare_histogram(x_column, bin_count)
        else:
            plot = compare.generate_compare_heatmap(x_column, y_column, bin_count)

        return {
            "success": True,
            "kind": kind,
            "a": table_a,
            "b": table_b,
            "x": x_column,
            "y": y_column,
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
    What the compare panel's Drift views draw for one node and one column: the ridgeline curves or the
    Sankey flows, and a plain-language annotation.

    Query: ?node=<node>&column=<column>[&keep=<category>&keep=<category>...][&base=<node>]
    base measures from one of the node's ancestors instead of root - the panel sends the two selections'
    common ancestor. Read-only: the node does not become the session's current table.
    """
    try:
        pgraph, error = _graph_or_error()
        if error:
            return error

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

        # The categories the panel wants kept out of the catch-all, when the reader has chosen any
        keep = request.args.getlist("keep") or None
        return {"success": True, **drift_detail(pgraph, node, column, keep, base)}
    except Exception as e:
        return {"success": False, "error": str(e)}, 400
