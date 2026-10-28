""" the base node class for the pgraph - March 31, 2026 - Nicolas Baret

When the user performs a new wrangling operation, a new instance of this class is made
and put into the provenance graph
"""


def wrangle_operation_name(wrangle_op):
    """
    The bare operation, with the _x / _y suffix dropped.

    That suffix only says which of a 2D pair was imputed, which is detail rather than identity - the
    graph's edges are labelled with this, and name the columns in their hover detail instead.

    :param wrangle_op: "delete", "impute", "impute_x", "impute_y" or "root"
    :return: "delete", "impute" or "root"
    """
    return "impute" if wrangle_op.startswith("impute") else wrangle_op


def acted_on_columns(wrangle_op, wrangle_cols):
    """
    The column(s) a wrangle actually acted on.

    A 1D wrangle acted on its single column. A 2D delete acted on both, because it removes rows picked
    out by the pair. A 2D impute acted only on the column it filled - which is the whole point of the
    _x / _y suffix, since "impute_x" on its own never said *which* column that was.

    :param wrangle_op: "delete", "impute", "impute_x", "impute_y" or "root"
    :param wrangle_cols: the columns the wrangle was performed on, in selection order
    :return: a list of column names, empty when none were recorded
    """
    if not wrangle_cols:
        return []
    if wrangle_op == "impute_x":
        return list(wrangle_cols[:1])
    if wrangle_op == "impute_y":
        return list(wrangle_cols[1:2])
    return list(wrangle_cols)


def format_wrangle_label(wrangle_op, wrangle_cols):
    """
    Build the label an edge carries: the operation plus the column(s) it acted on, as
    acted_on_columns picks them.

    Falls back to the bare operation when no columns were recorded, so the root node and any wrangle
    that did not carry its columns through still label sensibly.

    :param wrangle_op: "delete", "impute", "impute_x", "impute_y" or "root"
    :param wrangle_cols: the columns the wrangle was performed on, in selection order
    :return: a label such as "impute · salary" or "delete · salary × region"
    """
    columns = acted_on_columns(wrangle_op, wrangle_cols)
    if not columns:
        return wrangle_op

    # The _x / _y suffix has done its job once the column it refers to is named outright
    return f"{wrangle_operation_name(wrangle_op)} · {' × '.join(columns)}"


class GraphNode:
    def __init__(self, parent_table, wrangle_op: str, table_name: str, error_table_name: str,
                 wrangle_cols=None):

        self.parent_table = parent_table
        self.wrangle_op = wrangle_op
        # The column(s) the wrangle acted on, in selection order: one for a 1D wrangle, x then y for
        # a 2D one. Kept alongside wrangle_op rather than folded into it, so the bare operation name
        # stays available to anything matching on it.
        self.wrangle_cols = wrangle_cols or []
        self.table_name = table_name
        self.error_table_name = error_table_name
        self.children = []

        # Per-column and node-level error rates, a NodeMetrics. Computed once when the node is
        # created and never recomputed on read - see app/pgraph/metrics.py
        self.metrics = None

        # Drift from root, per column and for the node, with the facts about what its wrangles did.
        # Computed once alongside metrics and kept apart from them: drift is a cost, not an error, and is
        # never folded into the error totals - see app/pgraph/distortion.py
        self.distortion = None

        # Staging - see app/server_utils/candidates.py
        # A candidate wrangle - a repair of a selection, or an AI suggestion - staged as a node so it can be
        # analysed before it is accepted. It is a full node of the graph in every way but one: nothing may be
        # wrangled from it until it is accepted. Accepting only clears this.
        self.provisional = False
        # What the user sees the node called - "n0a", "n2c" - assigned when it joins the graph for good. The
        # table name is the node's identity and never changes, so this is kept apart from it; a candidate
        # shows its own table's prefix ("c7") until it is accepted.
        self.label = None
        # Where a candidate came from and how to present it: {source: "repair" | "ai", label, reason,
        # row_count, error_type, cols, chart_type}. None for a node that was never a candidate.
        self.candidate = None

        # The supporting sub-nodes hung beside this node, as plain JSON records - the recipe for each plot, never the
        # plot itself, which the front end fetches when it draws one. A new child starts with copies of its parent's -
        # see app/pgraph/support_nodes.py
        self.support_nodes = []

    def __json__(self):
        return {
            "parent_table": self.parent_table,
            "wrangle_op": self.wrangle_op,
            "wrangle_cols": self.wrangle_cols,
            "table_name": self.table_name,
            "error_table_name": self.error_table_name,
            "children": self.children,
            "metrics": self.metrics.__json__() if self.metrics is not None else None,
            "distortion": self.distortion,
            "provisional": self.provisional,
            "label": self.label,
            "candidate": self.candidate,
            "support_nodes": self.support_nodes,
        }

    def set_metrics(self, metrics):
        """
        Cache this node's quality metrics.
        :param metrics: a NodeMetrics for this node's table
        """
        self.metrics = metrics

    def set_distortion(self, distortion):
        """
        Cache this node's drift from root.
        :param distortion: what distortion.node_distortion returns, plus the node's edit facts
        """
        self.distortion = distortion

    def wrangle_label(self):
        """The operation and columns that produced this node - its incoming edge's hover detail."""
        return format_wrangle_label(self.wrangle_op, self.wrangle_cols)

    def wrangle_name(self):
        """Just the operation - what its incoming edge is labelled with in the graph."""
        return wrangle_operation_name(self.wrangle_op)

    def wrangle_summary(self):
        """The operation and the columns it acted on, for the front end to describe this node with."""
        return {"op": self.wrangle_name(), "columns": acted_on_columns(self.wrangle_op, self.wrangle_cols)}

    def add_child(self, child_node: str):
        self.children.append(child_node)

    def remove_child(self, child_node: str):
        if child_node in self.children:
            self.children.remove(child_node)
