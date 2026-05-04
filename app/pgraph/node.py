""" the base node class for the pgraph - March 31, 2026 - Nicolas Baret

When the user performs a new wrangling operation, a new instance of this class is made
and put into the provenance graph

"""



class GraphNode:
    def __init__(self, parent_table, wrangle_op: str, table_name: str, error_table_name: str):

        self.parent_table = parent_table
        self.wrangle_op = wrangle_op
        self.table_name = table_name
        self.error_table_name = error_table_name
        self.children = []

        """ quality metric parts """
        self.anomaly_metric = 0
        self.missing_metric = 0
        self.incomplete_metric = 0
        self.mismatch_metric = 0

        # Cached output of generate_complete_json for this node's table.
        # Populated lazily on first /api/plots/summaries hit; valid for the
        # node's lifetime since wrangle ops produce new immutable tables.
        self.attribute_summary = None

    # def __json__(self):
    #     return {
    #         "parent_table": self.parent_table,
    #         "wrangle_op": self.wrangle_op,
    #         "table_name": self.table_name,
    #         "error_table_name": self.error_table_name,
    #         "children": self.children
    #     }
    def update_metrics(self, anomaly, missing, incomplete, mismatch):

        self.anomaly_metric = anomaly
        self.missing_metric = missing
        self.incomplete_metric = incomplete
        self.mismatch_metric = mismatch

    def add_child(self, child_node: str):
        self.children.append(child_node)

    def get_attribute_summary(self):
        return self.attribute_summary

    def set_attribute_summary(self, summary):
        self.attribute_summary = summary




