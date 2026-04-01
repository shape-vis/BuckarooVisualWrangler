""" the base node class for the pgraph - March 31, 2026 - Nicolas Baret

When the user performs a new wrangling operation, a new instance of this class is made
and put into the provenance graph

"""
from app import DBOperations


class GraphNode:
    def __init__(self, engine, parent_id, wrangle_op: str, table_name: str, error_table_name: str):
        """
        Creates a node so that all members of it don't need to be loaded in at init time
        :param engine: db engine for DBOperations
        """
        self.parent_id = parent_id
        self.wrangle_op = wrangle_op
        self.db_op = DBOperations(engine)
        self.db_op.load_table(table_name, error_table_name)
        self.children = []

        """ quality metric parts """
        self.anomaly_metric = 0
        self.missing_metric = 0
        self.incomplete_metric = 0
        self.mismatch_metric = 0

    def update_metrics(self, anomaly, missing, incomplete, mismatch):
        """
        the helper that will store all the metrics for this table state
        :param anomaly: percentage of anomalies found in the table
        :param missing: percentage of missing found in the table
        :param incomplete: percentage of incomplete found in the table
        :param mismatch: percentage of mismatch found in the table
        :return:
        """
        self.anomaly_metric = anomaly
        self.missing_metric = missing
        self.incomplete_metric = incomplete
        self.mismatch_metric = mismatch

    def add_child(self, child_node: GraphNode):
        self.children.append(child_node)




