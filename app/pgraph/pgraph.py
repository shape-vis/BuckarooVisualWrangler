"""
Provenance graph for table versions.

The graph records how the user moved from the uploaded root table to later
wrangled tables. Each node is one data state, and each edge is one operation
that produced the child table from its parent. The graph is a DAG because a
user can undo to an earlier node and then create a different child branch.
"""
import json
from typing import TypedDict, List, Dict, Any

import app
from app.pgraph.node import GraphNode
from app.server_utils.pandas_export import build_pandas_export_script

class PGraph:
    def __init__(self, source_filename: str | None = None):
        # Keep export provenance self-contained. A graph may outlive the request
        # that loaded the CSV, so the replay script must not depend on mutable
        # module globals to discover its source file.
        self.source_filename = source_filename
        self.root_node = None
        # Fast lookup by table name. Example: "n1_sales" -> GraphNode(...).
        self.node_map = {}
        self.node_count = 0
        # Keeps a simple chronological record of wrangle operations.
        self.wrangle_map = {}
        # The UI has Undo/Redo controls, so we store table-name pointers rather
        # than copying entire nodes around.
        self.prev_node_table_name = None
        self.next_node_table_name = None
        self.current_node_table_name = None

    def serialize_node_map(self):
        """Return a JSON-friendly dictionary of every graph node."""
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
        """Build React Flow node data for the provenance graph UI."""
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
        """Build React Flow edge data by reading each node's children."""
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
        """Add a non-root node and connect it to its parent."""
        new_node_table_name = node.table_name
        self.node_map[new_node_table_name] = node
        self.node_count += 1
        self.wrangle_map[self.node_count] = node.wrangle_op

        # Connect parent -> child so graph traversal and UI edges both work.
        if node.parent_table in self.node_map:
            self.node_map[node.parent_table].add_child(new_node_table_name)

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = new_node_table_name

    def add_root_node(self, node: GraphNode):
        """Add the uploaded dataset as the root/original data state."""
        root_node_table_name = node.table_name
        self.node_map[root_node_table_name] = node
        self.node_count += 1

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = root_node_table_name

        self.root_node = root_node_table_name

    def get_new_node_id(self):
        return f"n{self.node_count}"

    def undo_pgraph(self):
        """Move the current pointer one step back, without deleting any node."""
        if self.prev_node_table_name == "root" or self.prev_node_table_name is None:
            return None
        self.next_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.prev_node_table_name
        self.prev_node_table_name = self.node_map[self.prev_node_table_name].parent_table
        return self.current_node_table_name

    def redo_pgraph(self):
        """Move the current pointer forward along the most recent child path."""
        if self.next_node_table_name is None:
            return None
        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.next_node_table_name
        current_node = self.node_map[self.current_node_table_name]
        current_node_child_list = current_node.children
        if len(current_node_child_list) == 0:
            self.next_node_table_name = None
        else:
            # If there are multiple branches, redo follows the most recent one.
            self.next_node_table_name = current_node_child_list[len(current_node_child_list)-1]

        return self.current_node_table_name

    def set_clicked_node_as_current(self, node_table_name):
        # When the user clicks a node in the UI graph, the backend changes the
        # active table to that exact version.
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
        """Return the list of nodes from root to the requested node."""
        path = []
        curr = node_table_name
        while curr and curr != "root":
            # Walk upward through parent links, then reverse at the end so the
            # final order is root -> child -> grandchild.
            node = self.node_map.get(curr)
            if not node:
                break
            path.append(node)
            curr = node.parent_table
        return path[::-1] # Reverse to get root-to-leaf

    def get_script_to_node(self, node_table_name: str) -> str:
        """Generate a complete Pandas script for the requested data state."""
        path = self.get_path_to_node(node_table_name)

        # Every exported script starts by loading the original CSV, then the
        # shared builder adds readable helper functions and applies each Delta
        # along the path to the current node.
        filename = self.source_filename
        if not filename:
            # Compatibility for graphs created before source_filename became a
            # graph property. New production graphs always take the first path.
            filename = getattr(app.get_session_state(), "original_table_name", None)
        if not filename:
            filename = getattr(app, "original_table_name", "data.csv")
        return build_pandas_export_script(filename, path)
