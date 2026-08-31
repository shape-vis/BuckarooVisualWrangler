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


def format_wrangle_label(wrangle_op, wrangle_cols):
    """
    Build the label an edge carries: the operation plus the column(s) it acted on.

    A 1D wrangle names its single column. A 2D delete names both, because it removes rows picked out
    by the pair. A 2D impute names only the column it actually filled - which is the whole point of
    the _x / _y suffix, since "impute_x" on its own never said *which* column that was.

    Falls back to the bare operation when no columns were recorded, so the root node and any wrangle
    that did not carry its columns through still label sensibly.

    :param wrangle_op: "delete", "impute", "impute_x", "impute_y" or "root"
    :param wrangle_cols: the columns the wrangle was performed on, in selection order
    :return: a label such as "impute · salary" or "delete · salary × region"
    """
    if not wrangle_cols:
        return wrangle_op

    if wrangle_op == "impute_x":
        columns = wrangle_cols[:1]
    elif wrangle_op == "impute_y":
        columns = wrangle_cols[1:2]
    else:
        columns = wrangle_cols

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

        """ quality metric parts """
        self.anomaly_metric = 0
        self.missing_metric = 0
        self.incomplete_metric = 0
        self.mismatch_metric = 0

        # Per-column and node-level error rates, a NodeMetrics. Computed once when the node is
        # created and never recomputed on read - see app/pgraph/metrics.py
        self.metrics = None

    def __json__(self):
        return {
            "parent_table": self.parent_table,
            "wrangle_op": self.wrangle_op,
            "wrangle_cols": self.wrangle_cols,
            "table_name": self.table_name,
            "error_table_name": self.error_table_name,
            "children": self.children,
            "metrics": self.metrics.__json__() if self.metrics is not None else None
        }

    def set_metrics(self, metrics):
        """
        Cache this node's quality metrics and mirror the four node-level dimensions onto the scalar
        fields above.
        :param metrics: a NodeMetrics for this node's table
        """
        self.metrics = metrics
        self.update_metrics(
            anomaly=metrics.dimension("anomaly"),
            missing=metrics.dimension("missing"),
            incomplete=metrics.dimension("incomplete"),
            mismatch=metrics.dimension("mismatch"),
        )

    def update_metrics(self, anomaly, missing, incomplete, mismatch):

        self.anomaly_metric = anomaly
        self.missing_metric = missing
        self.incomplete_metric = incomplete
        self.mismatch_metric = mismatch

    def wrangle_label(self):
        """The operation and columns that produced this node - its incoming edge's hover detail."""
        return format_wrangle_label(self.wrangle_op, self.wrangle_cols)

    def wrangle_name(self):
        """Just the operation - what its incoming edge is labelled with in the graph."""
        return wrangle_operation_name(self.wrangle_op)

    def add_child(self, child_node: str):
        self.children.append(child_node)




