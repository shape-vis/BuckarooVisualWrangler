"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node
"""
import json
from typing import TypedDict

from sqlalchemy import String

from app.pgraph.node import GraphNode

# Node ids are n{digit}{letter} - n0a, n0b ... n0z, n1a ... n9z. Always exactly three characters, so
# the prefix on a table name has a fixed width and 260 nodes fit before ids run out.
NODE_ID_CAPACITY = 260


def node_id_for_count(count):
    """
    :param count: how many nodes the graph already holds
    :return: the id for the next node, e.g. 0 -> "n0a", 26 -> "n1a"
    """
    if count >= NODE_ID_CAPACITY:
        raise ValueError(f"pgraph supports {NODE_ID_CAPACITY} nodes, got {count}")
    return f"n{count // 26}{chr(ord('a') + count % 26)}"


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
            node = self.node_map[key]
            list_of_nodes.append(
                {
                    "id": key,
                    "data": {
                        "label": key,
                        # The front end derives the default delta baseline, collapse validation and
                        # node highlighting from this, so none of them need a round trip
                        "parent": node.parent_table,
                        "metrics": node.metrics.__json__() if node.metrics is not None else None
                    }
                }
            )
        return list_of_nodes

    def descendant_paths(self, node_table_name):
        """
        Every path from this node down to a leaf, one list per downstream branch. A leaf returns a
        single one-element path.
        :param node_table_name: the node to walk down from
        :return: list of lists of node table names, each ordered from this node to a leaf
        """
        if node_table_name not in self.node_map:
            return []

        children = self.node_map[node_table_name].children
        if not children:
            return [[node_table_name]]

        paths = []
        for child in children:
            for path in self.descendant_paths(child):
                paths.append([node_table_name] + path)
        return paths

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
                        "label": child_node_obj.wrangle_label()
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
        return node_id_for_count(self.node_count)

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

    def set_clicked_node_as_current(self, node_table_name):
        #get the node from the graph the user clicked in the front-end
        current_node = self.node_map[node_table_name]
        child_list = current_node.children
        #check to see if it has any children for the next node pointer
        if len(child_list) == 0:
            #no child for next pointer
            self.next_node_table_name = None

        # set next to the last child added if there are children for this node
        if len(child_list) > 0:
            self.next_node_table_name = child_list[len(child_list) - 1]

        #set parent as prev pointer
        self.prev_node_table_name = current_node.parent_table

        #set current table name
        self.current_node_table_name = node_table_name
        return self.current_node_table_name