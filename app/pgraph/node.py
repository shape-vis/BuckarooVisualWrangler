""" the base node class for the pgraph - March 31, 2026 - Nicolas Baret

When the user performs a new wrangling operation, a new instance of this class is made
and put into the provenance graph

"""
from app import DBOperations


class GraphNode:
    def __init__(self, engine, parent_id: str, wrangle_op: str, table_name: str, error_table_name: str):

        self.parent_id = parent_id
        self.wrangle_op = wrangle_op
        self.table_name = table_name
        self.error_table_name = error_table_name
        self.db_op = DBOperations(engine)
        self.db_op.load_table(table_name, error_table_name)

        """ quality metric parts """
        self.anomaly_metric = 0
        self.missing_metric = 0
        self.incomplete_metric = 0
        self.mismatch_metric = 0

    def update_metrics(self, anomaly, missing, incomplete, mismatch):
        self.anomaly_metric = anomaly
        self.anomaly_metric = missing
        self.anomaly_metric = incomplete
        self.anomaly_metric = mismatch


