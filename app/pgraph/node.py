"""
Base node class for the provenance graph.

Think of a GraphNode as "one version of the dataset." When the user performs a
wrangling operation, the app creates a new GraphNode and places it in the graph.
The node stores both the data table and the matching errors table for that
version.
"""



from app.pgraph.delta import Delta

class GraphNode:
    def __init__(self, parent_table, wrangle_op: str, table_name: str, error_table_name: str, delta: Delta = None):

        # parent_table points backward, children points forward. Together they
        # let us traverse the graph for undo, redo, clicking nodes, and export.
        self.parent_table = parent_table
        self.wrangle_op = wrangle_op
        self.table_name = table_name
        self.error_table_name = error_table_name
        # delta is optional because the root upload has no wrangle operation.
        # Non-root nodes use it to replay/export the wrangle that created them.
        self.delta = delta
        self.children = []

        # Quality metric placeholders for future graph summaries.
        self.anomaly_metric = 0
        self.missing_metric = 0
        self.incomplete_metric = 0
        self.mismatch_metric = 0

    # def __json__(self):
    #     return {
    #         "parent_table": self.parent_table,
    #         "wrangle_op": self.wrangle_op,
    #         "table_name": self.table_name,
    #         "error_table_name": self.error_table_name,
    #         "children": self.children
    #     }
    def update_metrics(self, anomaly, missing, incomplete, mismatch):
        """Store per-node data quality summary values."""

        self.anomaly_metric = anomaly
        self.missing_metric = missing
        self.incomplete_metric = incomplete
        self.mismatch_metric = mismatch

    def add_child(self, child_node: str):
        """Record that another table version was created from this one."""
        self.children.append(child_node)




