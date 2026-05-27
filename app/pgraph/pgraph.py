"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node
"""
import json
from typing import TypedDict, List, Dict, Any

import app
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
            ser_map[key] = {
                "id": key,
                "parent_table": node.parent_table,
                "wrangle_op": node.wrangle_op,
                "table_name": node.table_name,
                "delta": node.delta.__json__() if node.delta else None,
                "children": node.children
            }
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
        for key, node in self.node_map.items():
            list_of_nodes.append(
                {
                    "id": key,
                    "data": {
                        "label": key,
                        "wrangle_op": node.wrangle_op,
                        "delta": node.delta.__json__() if node.delta else None
                    }
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
        if self.prev_node_table_name == "root" or self.prev_node_table_name is None:
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
        else:
            #set next to the last child added if there are children for this node
            self.next_node_table_name = current_node_child_list[len(current_node_child_list)-1]

        return self.current_node_table_name

    def set_clicked_node_as_current(self, node_table_name):
        #get the node from the graph the user clicked in the front-end
        current_node = self.node_map[node_table_name]
        child_list = current_node.children
        #check to see if it has any children for the next node pointer
        if len(child_list) == 0:
            #no child for next pointer
            self.next_node_table_name = None
        else:
            # set next to the last child added if there are children for this node
            self.next_node_table_name = child_list[len(child_list) - 1]

        #set parent as prev pointer
        self.prev_node_table_name = current_node.parent_table

        #set current table name
        self.current_node_table_name = node_table_name
        return self.current_node_table_name

    def get_path_to_node(self, node_table_name: str) -> List[GraphNode]:
        """Returns the list of nodes from root to the specified node."""
        path = []
        curr = node_table_name
        while curr and curr != "root":
            node = self.node_map.get(curr)
            if not node:
                break
            path.append(node)
            curr = node.parent_table
        return path[::-1] # Reverse to get root-to-leaf

    def get_script_to_node(self, node_table_name: str) -> str:
        """Generates a complete Pandas script to reach the specified data state."""
        path = self.get_path_to_node(node_table_name)
        
        # Start with initial load
        filename = getattr(app, 'original_table_name', 'data.csv')
        script = [
            "import pandas as pd",
            "",
            f"df = pd.read_csv('{filename}')",
            "# Ensure ID column exists as in the app",
            "if 'ID' not in df.columns:",
            "    df.insert(0, 'ID', range(1, len(df) + 1))",
            ""
        ]
        
        for node in path:
            if node.delta:
                script.append(f"# Operation: {node.wrangle_op}")
                script.append(node.delta.pandas_code)
                script.append("")
        
        return "\n".join(script)