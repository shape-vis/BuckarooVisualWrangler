"""
Supporting sub-nodes a new child inherits from its parent, and what accepting it does with them - see
app/pgraph/support_nodes.py. None of it needs a database: the records are plain JSON, and PGraph only holds them.
"""
import unittest

from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.pgraph.support_nodes import inherited_support_nodes, settle_inherited

PARENT = "n0a_t"
CHILD = "c0_t"
OTHER = "n1b_t"


def record(kind, config=None, host=PARENT, key="k"):
    return {"id": f"support:{host}:{key}", "hostId": host, "kind": kind, "side": "auto", "config": config or {}}


def compare_record(a, b, other):
    spec = {"version": 1, "anchor": b, "a": a, "b": b, "kind": "histogram", "x": "salary",
            "zoom": {"x": [0, 1]}, "kept": ["x"], "hidden": ["y"]}
    return record("compare", {"other": other, "spec": spec, "group": "g1"})


class InheritTests(unittest.TestCase):
    def test_the_wrangle_diff_is_not_inherited(self):
        inherited = inherited_support_nodes([record("wrangleDiff"), record("qualityMetrics")], PARENT, CHILD)

        kinds = []
        for child_record in inherited:
            kinds.append(child_record["kind"])
        self.assertEqual(kinds, ["qualityMetrics"])

    def test_a_copy_hangs_on_the_child_marked_inherited_and_minimised(self):
        parent_record = record("errorPlot", {"plot": "histogram", "columns": ["salary"]})
        parent_record["size"] = {"width": 300, "height": 200}

        child_record = inherited_support_nodes([parent_record], PARENT, CHILD)[0]

        self.assertEqual(child_record["hostId"], CHILD)
        self.assertTrue(child_record["id"].startswith(f"support:{CHILD}:"))
        self.assertEqual(child_record["config"], {"plot": "histogram", "columns": ["salary"]})
        self.assertEqual(child_record["size"], {"width": 300, "height": 200})
        self.assertTrue(child_record["inherited"])
        self.assertTrue(child_record["startMinimized"])

    def test_the_copies_are_deep(self):
        parent_record = record("errorPlot", {"plot": "heatmap", "columns": ["x", "y"]})

        child_record = inherited_support_nodes([parent_record], PARENT, CHILD)[0]
        child_record["config"]["columns"].append("z")

        self.assertEqual(parent_record["config"]["columns"], ["x", "y"])

    def test_a_compare_puts_the_child_in_the_parents_place_against_the_same_comparator(self):
        # The parent was selection B, compared with OTHER as A
        parent_record = compare_record(OTHER, PARENT, OTHER)

        config = inherited_support_nodes([parent_record], PARENT, CHILD)[0]["config"]

        self.assertEqual(config["other"], OTHER)
        self.assertEqual(config["spec"]["a"], OTHER)
        self.assertEqual(config["spec"]["b"], CHILD)
        self.assertEqual(config["spec"]["anchor"], CHILD)
        self.assertEqual(config["spec"]["x"], "salary")
        # Out of the parent's group, and the settings of the parent's pair start over
        self.assertIsNone(config["group"])
        self.assertIsNone(config["spec"]["zoom"])
        self.assertIsNone(config["spec"]["kept"])
        self.assertEqual(config["spec"]["hidden"], [])
        # The parent's own record is untouched
        self.assertEqual(parent_record["config"]["spec"]["b"], PARENT)
        self.assertEqual(parent_record["config"]["group"], "g1")

    def test_a_single_node_compare_becomes_one_of_the_child(self):
        parent_record = compare_record(PARENT, PARENT, PARENT)

        spec = inherited_support_nodes([parent_record], PARENT, CHILD)[0]["config"]["spec"]

        self.assertEqual(spec["a"], CHILD)
        self.assertEqual(spec["b"], CHILD)

    def test_a_sparkline_runs_on_to_the_child_and_is_measured_again(self):
        branch = {"source": "root_t", "target": PARENT, "destination": PARENT}
        parent_record = record("qualitySparkline", {"dimension": "total", "branch": branch,
                                                    "nodes": ["root_t", PARENT], "values": [0.2, 0.1],
                                                    "deltas": [-0.1]})

        config = inherited_support_nodes([parent_record], PARENT, CHILD)[0]["config"]

        self.assertEqual(config["branch"], {"source": "root_t", "target": PARENT, "destination": CHILD})
        self.assertEqual(config["dimension"], "total")
        self.assertEqual(config["values"], [])
        self.assertEqual(config["nodes"], [])
        self.assertEqual(config["deltas"], [])

    def test_a_sparkline_with_no_branch_yet_stays_blank(self):
        parent_record = record("qualitySparkline", {"dimension": "total", "branch": None})

        config = inherited_support_nodes([parent_record], PARENT, CHILD)[0]["config"]

        self.assertIsNone(config["branch"])


class AcceptTests(unittest.TestCase):
    def records(self):
        inherited = inherited_support_nodes([record("drift", {"column": "age"}, key="a"),
                                             record("errorPlot", {"columns": ["age"]}, key="b")], PARENT, CHILD)
        own = record("qualityMetrics", host=CHILD, key="mine")
        return inherited, own

    def test_accepting_opens_what_was_inherited_and_keeps_everything(self):
        inherited, own = self.records()

        kept = settle_inherited(inherited + [own])

        self.assertEqual(len(kept), 3)
        for kept_record in kept:
            self.assertFalse(kept_record.get("startMinimized", False))
            self.assertFalse(kept_record["inherited"])

    def test_a_copy_the_user_changed_is_left_as_it_is(self):
        inherited, own = self.records()
        # The user changed the second copy while looking the candidate over, so it is theirs now
        inherited[1]["inherited"] = False

        kept = settle_inherited(inherited + [own])

        self.assertFalse(kept[0]["startMinimized"])
        self.assertTrue(kept[1]["startMinimized"])


class GraphTests(unittest.TestCase):
    def graph(self):
        graph = PGraph()
        graph.add_root_node(GraphNode("root", "root", PARENT, f"errors_{PARENT}"))
        graph.add_support_node(PARENT, record("drift", {"column": "age"}))
        graph.add_support_node(PARENT, record("wrangleDiff", key="diff"))
        return graph

    def test_a_staged_candidate_starts_with_its_parents_sub_nodes(self):
        graph = self.graph()
        graph.add_candidate(GraphNode(PARENT, "delete", CHILD, f"errors_{CHILD}", ["age"]))

        child_records = graph.node_map[CHILD].support_nodes
        self.assertEqual(len(child_records), 1)
        self.assertEqual(child_records[0]["kind"], "drift")
        self.assertEqual(child_records[0]["hostId"], CHILD)

    def test_publishing_keeps_them(self):
        graph = self.graph()
        graph.add_candidate(GraphNode(PARENT, "delete", CHILD, f"errors_{CHILD}", ["age"]))
        graph.publish(CHILD)

        self.assertEqual(len(graph.node_map[CHILD].support_nodes), 1)

    def test_updating_a_record_makes_it_the_users_unless_told_otherwise(self):
        graph = self.graph()
        graph.add_candidate(GraphNode(PARENT, "delete", CHILD, f"errors_{CHILD}", ["age"]))
        support_id = graph.node_map[CHILD].support_nodes[0]["id"]

        graph.update_support_node(CHILD, support_id, {"config": {"column": "age"}, "inherited": True})
        self.assertTrue(graph.node_map[CHILD].support_nodes[0]["inherited"])

        graph.update_support_node(CHILD, support_id, {"config": {"column": "salary"}})
        self.assertFalse(graph.node_map[CHILD].support_nodes[0]["inherited"])
        self.assertEqual(graph.node_map[CHILD].support_nodes[0]["config"], {"column": "salary"})

    def test_removing_a_record(self):
        graph = self.graph()

        self.assertTrue(graph.remove_support_node(PARENT, f"support:{PARENT}:k"))
        self.assertFalse(graph.remove_support_node(PARENT, f"support:{PARENT}:k"))
        self.assertEqual(len(graph.node_map[PARENT].support_nodes), 1)


if __name__ == "__main__":
    unittest.main()
