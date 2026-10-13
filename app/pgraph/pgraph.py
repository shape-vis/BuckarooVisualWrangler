"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node
"""
from app.pgraph.node import GraphNode
from app.pgraph.distortion import pareto_frontier

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


def is_scored_leaf(node: GraphNode):
    """
    Whether a node is ranked on the Pareto plot: it is a leaf - where a branch ended up - and carries both an
    error total and an overall drift.
    """
    if node.children:
        return False
    if node.metrics is None or node.distortion is None:
        return False
    return node.distortion.get("overall") is not None


class PGraph:
    def __init__(self):
        self.root_table_name = None
        # {node table name: GraphNode}
        self.node_map = {}
        # How many nodes have joined the graph for good; it hands out their labels - see node_id_for_count
        self.node_count = 0

        # The undo / redo / current pointers are table names; services look the node up in node_map
        self.prev_node_table_name = None
        self.next_node_table_name = None
        self.current_node_table_name = None


        # How many candidates have ever been staged. Their tables are named c{count}_<base> from it, and it only
        # counts up, so a name is never reused - not even a discarded candidate's. Candidates do not count in
        # node_count, which hands out the labels of nodes that joined the graph for good.
        self.candidate_count = 0

    def __json__(self):
        return {
            "nodes": self.serialize_nodes(),
            "edges": self.serialize_edges(),
            "current_table": self.current_node_table_name,
            "prev_table": self.prev_node_table_name,
            "next_table": self.next_node_table_name,
            "pareto": self.pareto(),
        }

    def pareto(self):
        """
        Which leaf nodes are beaten outright on error and drift together - see distortion.pareto_frontier.

        Only leaves are candidates: an interior node is a step on the way somewhere, not where a branch
        ended up, so it is never ranked. A leaf is scored once it carries both numbers.

        :return: {"scored", "frontier", "dominated": {dominated id: dominating id}}
        """
        scores = []
        for node in self.node_map.values():
            if not is_scored_leaf(node):
                continue
            scores.append({
                "id": node.table_name,
                "error": node.metrics.dimension("total"),
                "distortion": node.distortion["overall"],
            })

        frontier, dominated = pareto_frontier(scores)
        return {"scored": [score["id"] for score in scores], "frontier": frontier, "dominated": dominated}

    def serialize_nodes(self):
        list_of_nodes = []
        for key in self.node_map.keys():
            node = self.node_map[key]
            list_of_nodes.append(
                {
                    "id": key,
                    "data": {
                        # Its name as the user knows it - "n2c" - or a candidate's own "c7" until it is accepted
                        "label": node.label or key.split("_")[0],
                        # A staged candidate: a node like any other, which nothing may be wrangled from until it
                        # is accepted, and what it came from - see app/server_utils/candidates.py
                        "provisional": node.provisional,
                        "candidate": node.candidate,
                        # The front end derives collapse validation, the analysis plot's links and
                        # node highlighting from this, so none of them need a round trip
                        "parent": node.parent_table,
                        "metrics": node.metrics.__json__() if node.metrics is not None else None,
                        # Drift from root, sent beside the error metrics rather than among them
                        "distortion": node.distortion,
                        # What produced the node, so it can be described without its incoming edge -
                        # which a collapsed run hides, and which the root never had
                        "wrangle": node.wrangle_summary()
                    }
                }
            )
        return list_of_nodes

    def path_between(self, start_table_name, end_table_name):
        """
        The path running from start down to end.

        The graph is a tree - every node has exactly one parent - so the path between an ancestor and
        one of its descendants is unique, and walking up from end until start is reached finds it.

        :param start_table_name: the node the branch runs from
        :param end_table_name: the node the branch runs to
        :return: node table names ordered start to end, or None when end is not below start
        """
        if start_table_name not in self.node_map or end_table_name not in self.node_map:
            return None

        path = [end_table_name]
        cursor = end_table_name

        while cursor != start_table_name:
            parent = self.node_map[cursor].parent_table
            if parent not in self.node_map:
                # Walked off the top without meeting start, so end does not descend from it
                return None
            cursor = parent
            path.append(cursor)

        return list(reversed(path))

    def serialize_edges(self):
        list_of_edges = []
        for node in self.node_map.values():
            node_name = node.table_name
            for child in node.children:
                child_node_obj = self.node_map[child]
                list_of_edges.append(
                    {
                        "id": f"e{node_name+child}",
                        "source": node_name,
                        "target": child,
                        "type": "edgeType",
                        "animated": "true",
                        # The edge shows the bare operation and keeps the columns for its hover detail
                        "label": child_node_obj.wrangle_name(),
                        # An edge into a candidate is drawn dashed: the wrangle has not been accepted yet
                        "data": {"detail": child_node_obj.wrangle_label(), "provisional": child_node_obj.provisional}
                    }
                )
        return list_of_edges

    def _assign_next_label(self, node: GraphNode):
        """Give a node joining the graph for good the next label - n0a, n0b, ..."""
        node.label = node_id_for_count(self.node_count)
        self.node_count += 1

    def _last_child(self, node: GraphNode):
        """:return: the node's most recently added child - where redo goes from it - or None when it has none"""
        if node is None or not node.children:
            return None
        return node.children[-1]

    def add_node(self, node: GraphNode):
        new_node_table_name = node.table_name
        self._assign_next_label(node)
        self.node_map[new_node_table_name] = node

        # Update the children of the parent node
        if node.parent_table in self.node_map:
            self.node_map[node.parent_table].add_child(new_node_table_name)

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = new_node_table_name

    def add_root_node(self, node: GraphNode):
        root_table_name = node.table_name
        self._assign_next_label(node)
        self.node_map[root_table_name] = node

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = root_table_name

        self.root_table_name = root_table_name

    # ── Candidates ───────────────────────────────────────────────────────────
    # A candidate wrangle is staged as a provisional node: a full node of the graph - a child of its parent,
    # with its edge, in the Pareto scoring, reachable by undo and redo - that nothing may be wrangled from until
    # it is accepted. Its table name is its identity and never changes; accepting it only clears the flag and
    # gives it a label. See app/server_utils/candidates.py.

    def take_candidate_prefix(self):
        """:return: the next candidate's table prefix - "c0", "c1", ... - never handed out twice"""
        prefix = f"c{self.candidate_count}"
        self.candidate_count += 1
        return prefix

    def add_candidate(self, node: GraphNode):
        """
        Stage a candidate under its parent. Unlike add_node it takes no label and no place in node_count, and
        leaves the current node where it is: asking for candidates does not move anyone.
        """
        node.provisional = True
        self.node_map[node.table_name] = node
        if node.parent_table in self.node_map:
            self.node_map[node.parent_table].add_child(node.table_name)

    def is_provisional(self, table_name):
        node = self.node_map.get(table_name)
        return bool(node and node.provisional)

    def publish(self, table_name):
        """
        Accept a candidate into the graph for good: it is already a child of its parent, so all that changes is
        that it stops being provisional and gets the next label.
        :return: the node
        """
        node = self.node_map[table_name]
        if not node.provisional:
            raise ValueError(f"{table_name} is not a candidate")
        node.provisional = False
        self._assign_next_label(node)
        return node

    def remove_candidate(self, table_name):
        """
        Take a candidate out of the graph. A candidate never has children - nothing may be wrangled from it -
        so nothing is orphaned. A pointer left on it is moved: off the current node to its parent, and the
        parent's next to its last remaining child.
        :return: the table the session should be on afterwards, when it had to move, else None
        """
        node = self.node_map.get(table_name)
        if node is None or not node.provisional:
            raise ValueError(f"{table_name} is not a candidate")
        parent = self.node_map.get(node.parent_table)
        if parent is not None:
            parent.remove_child(table_name)
        del self.node_map[table_name]

        if self.current_node_table_name == table_name and parent is not None:
            self.set_clicked_node_as_current(parent.table_name)
            return parent.table_name
        if self.next_node_table_name == table_name:
            current = self.node_map.get(self.current_node_table_name)
            self.next_node_table_name = self._last_child(current)
        return None

    def undo_pgraph(self):
        """
        Step up to the current node's parent.
        :return: the parent's table name, or None at the root, which has no parent to step up to
        """
        current_node = self.node_map.get(self.current_node_table_name)
        if current_node is None or current_node.parent_table not in self.node_map:
            return None

        parent_node = self.node_map[current_node.parent_table]
        self.next_node_table_name = current_node.table_name
        self.current_node_table_name = parent_node.table_name
        self.prev_node_table_name = parent_node.parent_table
        return self.current_node_table_name

    def redo_pgraph(self):
        """
        Step down to the node undo last stepped up from, or the current node's most recent child.
        :return: that node's table name, or None when there is nothing below
        """
        if self.next_node_table_name is None:
            return None
        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.next_node_table_name

        current_node = self.node_map[self.current_node_table_name]
        self.next_node_table_name = self._last_child(current_node)
        return self.current_node_table_name

    def set_clicked_node_as_current(self, node_table_name):
        """
        Move to the node the user clicked in the front end: its parent becomes prev, its most recent child next.
        :return: the node's table name
        """
        current_node = self.node_map[node_table_name]
        self.next_node_table_name = self._last_child(current_node)
        self.prev_node_table_name = current_node.parent_table
        self.current_node_table_name = node_table_name
        return self.current_node_table_name
