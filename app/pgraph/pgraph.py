"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret


"""
from app.pgraph.node import GraphNode


class PGraph:
    def __init__(self, root_node: GraphNode):
        self.root_node = root_node

