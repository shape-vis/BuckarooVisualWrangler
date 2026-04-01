"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node
"""
from typing import TypedDict

from app.pgraph.node import GraphNode

class PGraph:
    def __init__(self):
        self.root_node = None
        # this will be [node_name, GraphNode) for easy node access
        self.node_map = {}
        self.wrangle_counter = 0
        # keep track of the wrangle number and what it was for meta post-processing
        self.wrangle_map = {}

    def add_node(self, node: GraphNode):
        name = node.db_op.main_table_name
        self.node_map[name] = node
        self.wrangle_counter += 1
        self.wrangle_map[self.wrangle_counter] = node.wrangle_op

        if node.parent_id in self.node_map:
            parent = self.node_map[node.parent_id]
            parent.add_child(node)




