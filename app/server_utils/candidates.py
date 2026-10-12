"""
Staging candidate wrangles as provisional pgraph nodes - October 12, 2026

A candidate is a wrangle that has been worked out but not yet accepted: a way of repairing the rows the user
selected, or a repair the AI suggested. Both are staged the same way, and differ only in where they came from.

This is the write-audit-publish pattern data pipelines use. Write: the wrangle is run on a copy of its parent
and the copy is registered in the graph as a provisional node, with everything an accepted node has - its
errors, profile, rankings, metrics and drift - so it can be navigated to, compared, and given supporting
sub-nodes. Audit: the user does whatever analysis they like on it. Publish: accepting it clears the flag.

A candidate's table name - c{n}_<base> - is its identity, set once here and never changed. Accepting it does not
rename anything; the node just gets its label (n2c...), so nothing that refers to it has to be told. That is why
the name is not the label: a key that changed with the node's status would break every reference to it.

The one thing a candidate cannot do is be wrangled from: require_accepted is called by every path that would.
"""
from sqlalchemy import text as sa_text

import app
from app import engine
from app.db_utils import query
from app.pgraph.metrics import refresh_node_metrics
from app.pgraph.node import GraphNode
from app.server_utils.service_helpers import (
    WRANGLE_LOCK,
    _clone_table_pair,
    _parse_node_id,
    _safe_pg_name,
    build_data_profile_table,
)

# The wrangle a candidate stages, as GraphNode records it: the _x / _y of a 2D impute says which column it filled
OPS = ("delete", "impute", "impute_x", "impute_y")

SOURCES = ("repair", "ai")


class CandidateError(ValueError):
    """A request about candidates that cannot be met. The message is shown to the user, so keep it plain."""


def _session_graph():
    # The session's graph hangs off the app package, and does not exist at all until the first upload
    return getattr(app, "pgraph_for_session", None)


def _graph():
    graph = _session_graph()
    if graph is None:
        raise CandidateError("There is no graph in this session yet.")
    return graph


def require_accepted(table_name):
    """
    Refuse to wrangle from a candidate. Every path that would make a new node from a table - repairing a
    selection, asking the AI, deleting a column - calls this first, so none can get around it.
    """
    graph = _session_graph()
    if graph is not None and graph.is_provisional(table_name):
        raise CandidateError("Accept this candidate before wrangling from it.")


def _companions(table_name):
    """A node's table and every table derived from it."""
    return [table_name, f"errors_{table_name}", f"dp_{table_name}", f"rankings_{table_name}",
            f"{table_name}_filtering"]


def _drop_tables(table_name):
    with engine.begin() as conn:
        for name in _companions(table_name):
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))


def candidate_json(node):
    """What the client needs to draw and act on a candidate."""
    return {"table": node.table_name, "parent": node.parent_table, "op": node.wrangle_op,
            **(node.candidate or {})}


def materialize(parent, op, cols, row_ids, imputed_column=None, source="repair", meta=None):
    """
    Stage one candidate: run the wrangle on a copy of parent and register the copy as a provisional node.

    :param parent: the node table the wrangle runs on - an accepted node
    :param op: one of OPS
    :param cols: the column(s) the wrangle was chosen on, as the node records them
    :param row_ids: the rows it touches
    :param imputed_column: the column an impute fills
    :param source: "repair" (the user's selection) or "ai" (the model's suggestion)
    :param meta: how to present it - {label, reason, row_count, error_type, chart_type}
    :return: the candidate, as candidate_json gives it
    """
    if op not in OPS:
        raise CandidateError(f"Unknown wrangle {op!r}.")
    if source not in SOURCES:
        raise CandidateError(f"Unknown candidate source {source!r}.")
    if op.startswith("impute") and not imputed_column:
        raise CandidateError("An impute needs the column it fills.")
    if not row_ids:
        raise CandidateError("No rows selected.")

    # Imported here: routes are auto-imported alphabetically, and this module is used by them
    from app.routes.wrangler_routes_sql import update_errors_table

    with WRANGLE_LOCK:
        graph = _graph()
        if parent not in graph.node_map:
            raise CandidateError(f"{parent} is not a node in this graph.")
        require_accepted(parent)

        parsed = _parse_node_id(parent)
        base = parsed[1] if parsed else parent
        table = _safe_pg_name(f"{graph.take_candidate_prefix()}_{base}", "")

        try:
            with engine.begin() as conn:
                _clone_table_pair(conn, parent, table, query._get_errors_table(parent))
            if op == "delete":
                query.remove_rows_by_ids(table=table, ids=row_ids)
            else:
                query.impute_by_ids(table=table, col=imputed_column, ids=row_ids)
            update_errors_table(table)

            node = GraphNode(parent, op, table, f"errors_{table}", list(cols))
            node.candidate = {"source": source, "cols": list(cols), **(meta or {})}
            graph.add_candidate(node)

            # Everything an accepted node has, so the candidate can be made current and explored like one
            build_data_profile_table(table)
            app.db_operations.update_rankings(table)
            refresh_node_metrics(table)
        except Exception:
            if table in graph.node_map:
                graph.remove_candidate(table)
            _drop_tables(table)
            raise

        return candidate_json(node)


def accept(table):
    """
    Publish a candidate into the graph for good, and move the session onto it. Nothing is renamed: it keeps its
    table, its sub-nodes keep pointing at it, and its siblings stay staged under the same, unchanged parent.
    :return: {"success", "table", "label", "parent"}
    """
    with WRANGLE_LOCK:
        graph = _graph()
        if not graph.is_provisional(table):
            raise CandidateError(f"{table} is not a candidate.")
        node = graph.publish(table)
        # It may branch off a node other than the current one, so the cursor is set from the tree
        graph.set_clicked_node_as_current(table)
        app.db_operations.load_table(table, f"errors_{table}", f"dp_{table}")
    return {"success": True, "table": table, "label": node.label, "parent": node.parent_table}


def discard(tables):
    """
    Drop candidates and their tables. When the session was on one of them it moves to the parent.
    :return: {"success", "current": the table the session is on now when it moved, else None}
    """
    moved_to = None
    with WRANGLE_LOCK:
        graph = _graph()
        for table in tables:
            if not graph.is_provisional(table):
                raise CandidateError(f"{table} is not a candidate.")
        for table in tables:
            moved = graph.remove_candidate(table)
            if moved:
                moved_to = moved
            _drop_tables(table)
        if moved_to:
            app.db_operations.load_table(moved_to, f"errors_{moved_to}", f"dp_{moved_to}")
    return {"success": True, "current": moved_to}


def discard_all():
    """Drop every candidate still staged - when the session is reset, so none is left behind in the database."""
    graph = _session_graph()
    if graph is None:
        return
    tables = [name for name, node in graph.node_map.items() if node.provisional]
    if tables:
        discard(tables)
