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

Staging happens in three steps, so several candidates can be built at once:

    claim     under WRANGLE_LOCK, for a moment: check the parent, and take one table name per candidate
    build     on the node-build pool, with no lock held: copy the parent's table, run the wrangle on the copy,
              and build everything the node is read through - all of it SQL, against tables nobody else knows of
    register  under WRANGLE_LOCK again: add the built nodes to the graph, in the order their names were claimed

The one thing a candidate cannot do is be wrangled from: require_accepted is called by every path that would.
None of the SQL lives here - the tables are made by DBOperations and query.py, and built by build_node.
"""
from dataclasses import dataclass, field

import app
from app.db_utils import query
from app.pgraph.node import GraphNode
from app.server_utils.service_helpers import WRANGLE_LOCK, _parse_node_id, _safe_pg_name, build_node
from app.server_utils.workers import NODE_POOL

# The wrangle a candidate stages, as GraphNode records it: the _x / _y of a 2D impute says which column it filled
OPS = ("delete", "impute", "impute_x", "impute_y")

SOURCES = ("repair", "ai")


class CandidateError(ValueError):
    """A request about candidates that cannot be met. The message is shown to the user, so keep it plain."""


@dataclass
class CandidateSpec:
    """
    One candidate to stage.

    op:             one of OPS
    cols:           the column(s) the wrangle was chosen on, as the node records them
    row_ids:        the rows it touches
    imputed_column: the column an impute fills
    source:         "repair" (the user's selection) or "ai" (the model's suggestion)
    meta:           how to present it - {label, reason, row_count, error_type, chart_type}
    """
    op: str
    cols: list
    row_ids: list
    imputed_column: str | None = None
    source: str = "repair"
    meta: dict = field(default_factory=dict)


@dataclass
class _Build:
    """One candidate's build: its spec, its claimed table, and what building it produced or why it failed."""
    spec: CandidateSpec
    table: str
    metrics: object = None
    distortion: dict | None = None
    error: Exception | None = None


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


def candidate_json(node):
    """What the client needs to draw and act on a candidate."""
    return {"table": node.table_name, "parent": node.parent_table, "op": node.wrangle_op,
            **(node.candidate or {})}


def _check(spec):
    """Refuse a spec that could not be staged, before anything is claimed or built."""
    if spec.op not in OPS:
        raise CandidateError(f"Unknown wrangle {spec.op!r}.")
    if spec.source not in SOURCES:
        raise CandidateError(f"Unknown candidate source {spec.source!r}.")
    if spec.op.startswith("impute") and not spec.imputed_column:
        raise CandidateError("An impute needs the column it fills.")
    if not spec.row_ids:
        raise CandidateError("No rows selected.")


def _claim(parent, count):
    """
    Check the parent can be wrangled from, and take a table name for each candidate - in order, so a request's
    candidates are numbered as they were asked for.
    :return: (the graph the names were claimed in, the table names)
    """
    with WRANGLE_LOCK:
        graph = _graph()
        if parent not in graph.node_map:
            raise CandidateError(f"{parent} is not a node in this graph.")
        require_accepted(parent)

        parsed = _parse_node_id(parent)
        base = parsed[1] if parsed else parent

        tables = []
        for _ in range(count):
            prefix = graph.take_candidate_prefix()
            tables.append(_safe_pg_name(f"{prefix}_{base}", ""))

    return graph, tables


def _build(parent, build, root_table):
    """
    Build one candidate's tables: copy the parent's table, run the wrangle on the copy, and build everything the
    node is read through. Runs on the node-build pool, holding no lock - the tables are the candidate's alone until
    it is registered.
    """
    spec = build.spec
    app.db_operations.clone_table(parent, build.table)
    if spec.op == "delete":
        query.remove_rows_by_ids(table=build.table, ids=spec.row_ids)
    else:
        query.impute_by_ids(table=build.table, col=spec.imputed_column, ids=spec.row_ids)
    return build_node(build.table, root_table)


def _build_all(parent, specs):
    """
    Claim a table for each spec and build them all at once, each on its own node-build thread. A candidate whose
    build fails has its tables dropped here, and carries its error.
    :return: (the graph the names were claimed in, a _Build per spec, in order)
    """
    for spec in specs:
        _check(spec)

    graph, tables = _claim(parent, len(specs))

    builds = []
    futures = []
    for spec, table in zip(specs, tables):
        build = _Build(spec=spec, table=table)
        builds.append(build)
        futures.append(NODE_POOL.submit(_build, parent, build, graph.root_node))

    for build, future in zip(builds, futures):
        try:
            build.metrics, build.distortion = future.result()
        except Exception as error:
            build.error = error
            app.db_operations.drop_node_tables(build.table)

    return graph, builds


def _register(graph, parent, builds):
    """
    Add the built candidates to the graph, in the order their names were claimed. If the session moved on while
    they were being built - a reset, or a new upload - they belong to no graph any more, so their tables are
    dropped instead.
    :return: the staged candidates, as candidate_json gives them
    """
    with WRANGLE_LOCK:
        if _session_graph() is not graph or parent not in graph.node_map:
            for build in builds:
                app.db_operations.drop_node_tables(build.table)
            raise CandidateError("The session changed while these candidates were being built.")

        staged = []
        for build in builds:
            spec = build.spec
            node = GraphNode(parent, spec.op, build.table, f"errors_{build.table}", list(spec.cols))
            node.candidate = {"source": spec.source, "cols": list(spec.cols), **spec.meta}
            node.set_metrics(build.metrics)
            node.set_distortion(build.distortion)
            graph.add_candidate(node)
            staged.append(candidate_json(node))

    return staged


def stage_all(parent, specs):
    """
    Stage a set of candidates that stand together - the ways of repairing one selection. They are built at once,
    and staged only if every one of them builds: if one fails, none are staged, and its error is raised.

    :param parent: the node table the wrangles run on - an accepted node
    :param specs: a CandidateSpec per candidate
    :return: the candidates, as candidate_json gives them, in the specs' order
    """
    graph, builds = _build_all(parent, specs)

    failed = []
    for build in builds:
        if build.error is not None:
            failed.append(build)

    if failed:
        for build in builds:
            if build.error is None:
                app.db_operations.drop_node_tables(build.table)
        raise failed[0].error

    return _register(graph, parent, builds)


def stage_each(parent, specs):
    """
    Stage candidates that stand alone - the AI's suggestions, each its own proposal. They are built at once, and
    each that builds is staged whether or not the others do.

    :param parent: the node table the wrangles run on - an accepted node
    :param specs: a CandidateSpec per candidate
    :return: (the staged candidates as candidate_json gives them, in the specs' order, and [(spec, error)] for
             each that could not be built)
    """
    graph, builds = _build_all(parent, specs)

    built = []
    failures = []
    for build in builds:
        if build.error is None:
            built.append(build)
        else:
            failures.append((build.spec, build.error))

    staged = []
    if built:
        staged = _register(graph, parent, built)
    return staged, failures


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
    spec = CandidateSpec(op=op, cols=list(cols), row_ids=row_ids, imputed_column=imputed_column, source=source,
                         meta=meta or {})
    return stage_all(parent, [spec])[0]


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
            app.db_operations.drop_node_tables(table)
        if moved_to:
            app.db_operations.load_table(moved_to, f"errors_{moved_to}", f"dp_{moved_to}")
    return {"success": True, "current": moved_to}


def discard_all():
    """Drop every candidate still staged - when the session is reset, so none is left behind in the database."""
    graph = _session_graph()
    if graph is None:
        return
    tables = []
    for name, node in graph.node_map.items():
        if node.provisional:
            tables.append(name)
    if tables:
        discard(tables)
