"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node
"""
import json
from typing import TypedDict

from sqlalchemy import String

from app.pgraph.node import GraphNode

class PGraph:
    def __init__(self):
        self.root_node = None
        # this will be [node_table_name, GraphNode) for easy node access
        self.node_map = {}
        self.node_count = 0
        # keep track of the wrangle number and what it was for meta post-processing
        self.wrangle_map = {}
        """
        these are referenced by table names, and then and services should load the node from the graph
        using the table names    
        """
        self.prev_node_table_name = None
        self.next_node_table_name = None
        self.current_node_table_name = None

    def serialize_node_map(self):
        ser_map = {}
        for key in self.node_map.keys():
            node = self.node_map[key]
            ser_map[key] = json.dumps(node, default=lambda o: o.__json__()
                         if hasattr(o, '__json__') else None)
        return ser_map

    def __json__(self):
        return {
            "nodes": self.serialize_nodes(),
            "edges": self.serialize_edges(),
            "current_table": self.current_node_table_name,
            "prev_table": self.prev_node_table_name,
            "next_table": self.next_node_table_name
        }

    def serialize_nodes(self):
        list_of_nodes = []
        for key in self.node_map.keys():
            list_of_nodes.append(
                {
                    "id": key,
                    "data": {"label": key}
                }
            )
        return list_of_nodes

    def serialize_edges(self):
        list_of_edges = []
        for node in self.node_map.values():
            node_name = node.table_name
            if len(node.children) == 0:
                continue
            for child in node.children:
                child_node_obj = self.node_map[child]
                list_of_edges.append(
                    {
                        "id": f"e{node_name+child}",
                        "source": node_name,
                        "target": child,
                        "type": "edgeType",
                        "animated": "true",
                        "label": child_node_obj.wrangle_op
                    }
                )
        return list_of_edges

    def add_node(self, node: GraphNode):
        new_node_table_name = node.table_name
        self.node_map[new_node_table_name] = node
        self.node_count += 1
        self.wrangle_map[self.node_count] = node.wrangle_op

        #update the children of the parent node
        if node.parent_table in self.node_map:
            self.node_map[node.parent_table].add_child(new_node_table_name)

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = new_node_table_name

    def add_root_node(self, node: GraphNode):
        root_node_table_name = node.table_name
        self.node_map[root_node_table_name] = node
        self.node_count += 1

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = root_node_table_name

        self.root_node = root_node_table_name

    def get_new_node_id(self):
        return f"n{self.node_count}"

    def undo_pgraph(self):
        if self.prev_node_table_name == "root":
            return None
        self.next_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.prev_node_table_name
        self.prev_node_table_name = self.node_map[self.prev_node_table_name].parent_table
        return self.current_node_table_name

    def redo_pgraph(self):
        if self.next_node_table_name is None:
            return None
        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.next_node_table_name
        current_node = self.node_map[self.current_node_table_name]
        current_node_child_list = current_node.children
        if len(current_node_child_list) == 0:
            self.next_node_table_name = None
            return self.current_node_table_name
        #set next to the last child added if there are children for this node
        self.next_node_table_name = current_node_child_list[len(current_node_child_list)-1]

        return self.current_node_table_name
