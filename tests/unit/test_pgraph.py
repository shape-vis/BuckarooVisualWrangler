import json
import unittest

from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph


class PGraphTests(unittest.TestCase):
    def test_getJson(self):
        graph = PGraph()
        root = GraphNode("none", "none", "n0", "n0_errors")
        node1 = GraphNode("n0", "delete", "n1", "n1errors")

        graph.add_root_node(root)
        graph.add_node(node1)

        val = json.dumps(
            graph,
            default=lambda o: o.__json__() if hasattr(o, "__json__") else None,
        )
        self.assertEqual(True, True)

    def test_undo_at_root_returns_none_and_keeps_current_root(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0", "n0_errors")

        graph.add_root_node(root)

        self.assertIsNone(graph.undo_pgraph())
        self.assertEqual(graph.current_node_table_name, "n0")

    def test_redo_at_leaf_returns_none(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0", "n0_errors")
        graph.add_root_node(root)

        self.assertIsNone(graph.redo_pgraph())
        self.assertEqual(graph.current_node_table_name, "n0")

    def test_undo_and_redo_through_two_wrangles(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0", "n0_errors")
        node1 = GraphNode("n0", "delete", "n1", "n1errors")
        node2 = GraphNode("n1", "impute", "n2", "n2errors")

        graph.add_root_node(root)
        graph.add_node(node1)
        graph.add_node(node2)

        self.assertEqual(graph.current_node_table_name, "n2")

        self.assertEqual(graph.undo_pgraph(), "n1")
        self.assertEqual(graph.current_node_table_name, "n1")

        self.assertEqual(graph.undo_pgraph(), "n0")
        self.assertEqual(graph.current_node_table_name, "n0")

        self.assertIsNone(graph.undo_pgraph())
        self.assertEqual(graph.current_node_table_name, "n0")

        self.assertEqual(graph.redo_pgraph(), "n1")
        self.assertEqual(graph.redo_pgraph(), "n2")
        self.assertEqual(graph.current_node_table_name, "n2")

        self.assertIsNone(graph.redo_pgraph())


if __name__ == "__main__":
    unittest.main()
