import json
import unittest
from unittest.mock import patch

from app.pgraph.delta import Delta
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph


class PGraphTests(unittest.TestCase):
    def test_json_serializes_delta_storage(self):
        graph = PGraph()
        root = GraphNode("none", "none", "n0", "n0_errors")
        node1 = GraphNode(
            "n0",
            "delete",
            "n1",
            "n1errors",
            delta=Delta("delete", {"operation": "delete", "row_ids": [1, 3]}),
        )

        graph.add_root_node(root)
        graph.add_node(node1)

        serialized = json.loads(json.dumps(
            graph,
            default=lambda o: o.__json__() if hasattr(o, "__json__") else None,
        ))

        node_data = {node["id"]: node["data"] for node in serialized["nodes"]}
        self.assertEqual(serialized["current_table"], "n1")
        self.assertEqual(node_data["n1"]["delta"]["operation"], "delete")
        self.assertEqual(node_data["n1"]["delta"]["parameters"]["row_ids"], [1, 3])
        self.assertEqual(
            node_data["n1"]["delta"]["pandas_code"],
            "df = df[~df['ID'].isin([1, 3])]",
        )

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

    def test_get_path_to_node_returns_root_to_selected_node_only(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0", "n0_errors")
        node1 = GraphNode("n0", "delete", "n1", "n1errors")
        node2 = GraphNode("n1", "impute", "n2", "n2errors")
        branch = GraphNode("n0", "delete-column", "n3", "n3errors")

        graph.add_root_node(root)
        graph.add_node(node1)
        graph.add_node(node2)
        graph.set_clicked_node_as_current("n0")
        graph.add_node(branch)

        self.assertEqual(
            [node.table_name for node in graph.get_path_to_node("n2")],
            ["n0", "n1", "n2"],
        )
        self.assertEqual(
            [node.table_name for node in graph.get_path_to_node("n3")],
            ["n0", "n3"],
        )

    def test_get_script_to_node_exports_only_selected_path_deltas_in_order(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0_sales", "errors_n0_sales")
        delete_node = GraphNode(
            "n0_sales",
            "delete",
            "n1_sales",
            "errors_n1_sales",
            delta=Delta("delete", {"operation": "delete", "row_ids": [4]}),
        )
        impute_node = GraphNode(
            "n1_sales",
            "impute",
            "n2_sales",
            "errors_n2_sales",
            delta=Delta("impute", {"operation": "impute", "row_ids": [5], "col": "age"}),
        )
        branch_node = GraphNode(
            "n0_sales",
            "delete-column",
            "n3_sales",
            "errors_n3_sales",
            delta=Delta("delete-column", {"operation": "delete-column", "column": "unused"}),
        )

        graph.add_root_node(root)
        graph.add_node(delete_node)
        graph.add_node(impute_node)
        graph.set_clicked_node_as_current("n0_sales")
        graph.add_node(branch_node)

        with patch("app.original_table_name", "sales.csv", create=True):
            script = graph.get_script_to_node("n2_sales")

        self.assertIn("import pandas as pd", script)
        self.assertIn("df = pd.read_csv('sales.csv')", script)
        self.assertIn("if 'ID' not in df.columns:", script)
        self.assertIn("# Operation: delete", script)
        self.assertIn("df = df[~df['ID'].isin([4])]", script)
        self.assertIn("# Operation: impute", script)
        self.assertIn("df.loc[df['ID'].isin([5]), 'age']", script)
        self.assertNotIn("delete-column", script)
        self.assertLess(script.index("# Operation: delete"), script.index("# Operation: impute"))

    def test_get_script_to_root_contains_load_and_no_wrangle_operations(self):
        graph = PGraph()
        root = GraphNode("root", "root", "n0_sales", "errors_n0_sales")
        graph.add_root_node(root)

        with patch("app.original_table_name", "sales.csv", create=True):
            script = graph.get_script_to_node("n0_sales")

        self.assertIn("df = pd.read_csv('sales.csv')", script)
        self.assertNotIn("# Operation:", script)


if __name__ == "__main__":
    unittest.main()
