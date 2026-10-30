"""
the class for the pgraph which creates the DAG structure - March 31, 2026 - Nicolas Baret

uses a dictionary to have parent <--> child interaction
to traverse up and down, it access' the child's parent node

It also holds what is read across nodes rather than off one: a branch's trajectory and the Pareto frontier. Each node's
own measurements - its error metrics (metrics.py) and its drift from root (distortion.py) - are made when it is built
and cached on it, and everything here is plain arithmetic over those, so it is testable without a database.
"""
from app.pgraph.metrics import DIMENSIONS
from app.pgraph.node import GraphNode
from app.pgraph.support_nodes import inherited_support_nodes

# Node ids are n{digit}{letter} - n0a, n0b ... n0z, n1a ... n9z. Always exactly three characters, so
# the prefix on a table name has a fixed width and 260 nodes fit before ids run out.
NODE_ID_CAPACITY = 260

# Both Pareto axes are rounded to this many places, so float noise cannot make equal nodes dominate
PARETO_PRECISION = 6


def node_id_for_count(count):
    """
    :param count: how many nodes the graph already holds
    :return: the id for the next node, e.g. 0 -> "n0a", 26 -> "n1a"
    """
    if count >= NODE_ID_CAPACITY:
        raise ValueError(f"pgraph supports {NODE_ID_CAPACITY} nodes, got {count}")
    return f"n{count // 26}{chr(ord('a') + count % 26)}"


# ── Across nodes ─────────────────────────────────────────────────────────────

def branch_deltas(values):
    """
    Each step's change along a branch: the difference of two values both measured on their own node, not a fresh
    measurement between parent and child. A step with a value missing on either side has no change.

    :param values: one value per node, root-most first; None where a node has none
    :return: the deltas, one fewer than the values
    """
    deltas = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None:
            deltas.append(None)
        else:
            deltas.append(current - previous)
    return deltas


def quality_trajectory(ordered_metrics):
    """
    Compute the downstream quality trajectory along one branch.

        delta_i        = q(n_i+1) - q(n_i)
        contribution_i = delta_i / sum_j |delta_j|

    q is an *error* rate, so higher is worse: a positive delta means errors increased. That is why a
    positive contribution indicates degradation and a negative one indicates improvement.

    When every delta along the branch is zero there is nothing to attribute, so the branch is reported
    as unchanged rather than dividing by zero.

    :param ordered_metrics: NodeMetrics in path order, root-most first
    :return: {dimension: {"values", "deltas", "contributions", "no_change"}}
    """
    trajectory = {}

    for dimension in DIMENSIONS:
        values = []
        for metrics in ordered_metrics:
            values.append(metrics.dimension(dimension))
        deltas = branch_deltas(values)

        total_absolute_change = 0
        for delta in deltas:
            total_absolute_change += abs(delta)
        no_change = total_absolute_change == 0

        contributions = []
        for delta in deltas:
            if no_change:
                contributions.append(0.0)
            else:
                contributions.append(delta / total_absolute_change)

        trajectory[dimension] = {
            "values": values,
            "deltas": deltas,
            "contributions": contributions,
            "no_change": no_change,
        }

    return trajectory


def distortion_trajectory(ordered):
    """
    The drift number along a branch. Every value is measured against root, and each step's delta is the
    difference of two of them - not a fresh parent-to-child measurement, which is a different number and
    would hide drift that builds up over many small steps (doc 01 §1.4).

    :param ordered: each node's distortion (or None), root-most first
    :return: {"values", "deltas"}
    """
    values = []
    for distortion in ordered:
        if distortion:
            values.append(distortion.get("overall"))
        else:
            values.append(None)

    return {"values": values, "deltas": branch_deltas(values)}


def pareto_frontier(scores):
    """
    Which nodes are beaten outright. Lower is better on both axes, and node Y is dominated by X when X is
    no worse on both and strictly better on one. A dominated node is never the right choice, whatever the
    analyst values, so it can be ruled out without asking. The rest form the frontier, which this declines
    to rank - analysts who value keeping every row and analysts who value clean flags sit at opposite ends.

    Both axes are rounded first, or float noise makes equal nodes dominate each other. When several nodes
    dominate Y, the one named is the lowest id, so the explanation does not change between renders.

    :param scores: [{"id", "error", "distortion"}]
    :return: (frontier ids, {dominated id: dominating id}), in id order
    """
    ranked_scores = []
    for score in scores:
        rounded_error = round(score["error"], PARETO_PRECISION)
        rounded_drift = round(score["distortion"], PARETO_PRECISION)
        ranked_scores.append((score["id"], rounded_error, rounded_drift))
    ranked_scores.sort()

    dominated = {}
    for y_id, y_error, y_drift in ranked_scores:
        for x_id, x_error, x_drift in ranked_scores:
            no_worse = x_error <= y_error and x_drift <= y_drift
            strictly_better = x_error < y_error or x_drift < y_drift
            if no_worse and strictly_better:
                dominated[y_id] = x_id
                break

    frontier = []
    for node_id, _, _ in ranked_scores:
        if node_id not in dominated:
            frontier.append(node_id)
    return frontier, dominated


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
        # The nodes undo stepped up from, the nearest last, so redo retraces them in turn. Any other move clears it.
        self._redo_path = []

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
        Which leaf nodes are beaten outright on error and drift together - see pareto_frontier.

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

        scored = []
        for score in scores:
            scored.append(score["id"])

        frontier, dominated = pareto_frontier(scores)
        return {"scored": scored, "frontier": frontier, "dominated": dominated}

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
                        "wrangle": node.wrangle_summary(),
                        # The supporting sub-nodes hung beside it - see app/pgraph/support_nodes.py
                        "support_nodes": node.support_nodes,
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

    def _redo_target(self):
        """:return: where redo goes from the current node - back down the path undo came up, else its last child"""
        if self._redo_path:
            return self._redo_path[-1]
        current = self.node_map.get(self.current_node_table_name)
        return self._last_child(current)

    def add_node(self, node: GraphNode):
        new_node_table_name = node.table_name
        self._assign_next_label(node)
        self.node_map[new_node_table_name] = node

        # Update the children of the parent node
        if node.parent_table in self.node_map:
            self.node_map[node.parent_table].add_child(new_node_table_name)

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = new_node_table_name
        self._redo_path = []
        self.next_node_table_name = None

    def add_root_node(self, node: GraphNode):
        root_table_name = node.table_name
        self._assign_next_label(node)
        self.node_map[root_table_name] = node

        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = root_table_name
        self._redo_path = []
        self.next_node_table_name = None

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
            parent = self.node_map[node.parent_table]
            parent.add_child(node.table_name)
            # It starts with its parent's sub-nodes, minimised until accepting it says otherwise
            node.support_nodes = inherited_support_nodes(parent.support_nodes, parent.table_name, node.table_name)

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
        # A candidate has no children, so it can only be the deepest step of the redo path
        if table_name in self._redo_path:
            self._redo_path.remove(table_name)
        self.next_node_table_name = self._redo_target()
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
        self._redo_path.append(current_node.table_name)
        self.next_node_table_name = current_node.table_name
        self.current_node_table_name = parent_node.table_name
        self.prev_node_table_name = parent_node.parent_table
        return self.current_node_table_name

    def redo_pgraph(self):
        """
        Step back down the path undo came up, one node at a time; with no undo to retrace, to the current node's
        most recent child.
        :return: that node's table name, or None when there is nothing below
        """
        if self.next_node_table_name is None:
            return None
        if self._redo_path and self._redo_path[-1] == self.next_node_table_name:
            self._redo_path.pop()
        self.prev_node_table_name = self.current_node_table_name
        self.current_node_table_name = self.next_node_table_name
        self.next_node_table_name = self._redo_target()
        return self.current_node_table_name

    def set_clicked_node_as_current(self, node_table_name):
        """
        Move to the node the user clicked in the front end: its parent becomes prev, its most recent child next.
        :return: the node's table name
        """
        current_node = self.node_map[node_table_name]
        self._redo_path = []
        self.next_node_table_name = self._last_child(current_node)
        self.prev_node_table_name = current_node.parent_table
        self.current_node_table_name = node_table_name
        return self.current_node_table_name

    # ── Supporting sub-nodes ─────────────────────────────────────────────────
    # Kept on their host node - see app/pgraph/support_nodes.py. A record goes with its host when a candidate is
    # declined, since the node it lives on is gone.

    def _support_record_index(self, host, support_id):
        """:return: where the record sits in its host's list, or None when the host has no such record"""
        records = self.node_map[host].support_nodes
        for index, record in enumerate(records):
            if record.get("id") == support_id:
                return index
        return None

    def add_support_node(self, host, record):
        """Hang a sub-node beside a node. A record already there under the same id is replaced."""
        index = self._support_record_index(host, record["id"])
        records = self.node_map[host].support_nodes
        if index is None:
            records.append(record)
        else:
            records[index] = record

    def update_support_node(self, host, support_id, changes):
        """
        Merge changes into one of a node's sub-nodes. A record the user changed is their own from then on, so it is
        no longer counted as inherited - unless the changes say otherwise, as a change the front end makes by itself
        does (measuring an inherited sparkline's branch, say).
        :return: whether the record was there to change
        """
        index = self._support_record_index(host, support_id)
        if index is None:
            return False
        records = self.node_map[host].support_nodes
        updated = dict(records[index])
        updated.update(changes)
        if "inherited" not in changes:
            updated["inherited"] = False
        records[index] = updated
        return True

    def remove_support_node(self, host, support_id):
        """:return: whether the record was there to remove"""
        index = self._support_record_index(host, support_id)
        if index is None:
            return False
        del self.node_map[host].support_nodes[index]
        return True
