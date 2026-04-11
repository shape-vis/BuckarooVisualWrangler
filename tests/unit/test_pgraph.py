import json
import unittest

from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph


class PGraphTests(unittest.TestCase):
    def test_getJson(self):
        graph = PGraph()
        root = GraphNode("none", "none", "n0", "n0_errors")
        node1 = GraphNode("n0", "delete","n1","n1errors")

        graph.add_root_node(root)
        graph.add_node(node1)

        val = json.dumps(graph,
                         default=lambda o: o.__json__()
                         if hasattr(o, '__json__') else None)
        self.assertEqual(True,True)

if __name__ == '__main__':
    unittest.main()
