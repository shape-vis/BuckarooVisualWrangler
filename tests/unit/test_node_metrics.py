import json
import unittest

import app
from app.pgraph.metrics import NodeMetrics, quality_trajectory
from app.pgraph.node import GraphNode, format_wrangle_label
from app.pgraph.pgraph import PGraph, node_id_for_count
from app.server_utils.service_helpers import make_new_table_name, _parse_node_id


class StubDataProfile:
    """
    Stands in for DataProfile so the metric arithmetic can be tested without a database. Mirrors the
    real contract: get_col_names returns every column including ID, and 'error_counts' comes back as
    a JSON string on both the looked-up and the freshly-computed path.
    """

    def __init__(self, error_counts_by_column):
        self.error_counts_by_column = error_counts_by_column

    def get_col_names(self):
        return list(self.error_counts_by_column)

    def calculate_column_attribute(self, attribute_name, column_name, look_up_stat=True):
        assert attribute_name == 'error_counts'
        counts = self.error_counts_by_column[column_name]
        return None if counts is None else json.dumps(counts)


class NodeMetricsTests(unittest.TestCase):
    def _profile(self):
        return StubDataProfile({
            'ID': {},
            'age': {'missing': 2, 'anomaly': 1},
            'city': {},
        })

    def test_column_rates_are_errors_over_row_count(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=10)

        self.assertAlmostEqual(metrics.columns['age']['missing'], 0.2)
        self.assertAlmostEqual(metrics.columns['age']['anomaly'], 0.1)
        self.assertAlmostEqual(metrics.columns['age']['total'], 0.3)

    def test_zero_dimensions_are_omitted_from_columns(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=10)

        self.assertNotIn('mismatch', metrics.columns['age'])
        self.assertEqual(metrics.columns['city'], {'total': 0.0})

    def test_id_columns_are_not_counted_as_attributes(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=10)

        self.assertNotIn('ID', metrics.columns)
        self.assertEqual(metrics.column_count, 2)

    def test_totals_are_errors_over_cells(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=10)

        # 2 missing out of 10 rows x 2 columns
        self.assertAlmostEqual(metrics.totals['missing'], 0.1)
        self.assertAlmostEqual(metrics.totals['anomaly'], 0.05)
        self.assertAlmostEqual(metrics.totals['mismatch'], 0.0)
        self.assertAlmostEqual(metrics.totals['total'], 0.15)

    def test_empty_table_reports_zero_instead_of_dividing_by_zero(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=0)

        self.assertEqual(metrics.totals['missing'], 0.0)
        self.assertEqual(metrics.columns['age']['total'], 0.0)

    def test_missing_profile_entry_is_treated_as_no_errors(self):
        profile = StubDataProfile({'age': None})

        metrics = NodeMetrics.from_data_profile(profile, row_count=10)

        self.assertEqual(metrics.columns['age'], {'total': 0.0})

    def test_dimension_defaults_to_zero(self):
        metrics = NodeMetrics.from_data_profile(self._profile(), row_count=10)

        self.assertAlmostEqual(metrics.dimension('missing'), 0.1)
        self.assertEqual(metrics.dimension('not_a_dimension'), 0.0)


class QualityTrajectoryTests(unittest.TestCase):
    def _metrics(self, missing_rates):
        return [
            NodeMetrics(row_count=10, column_count=1, totals={'missing': rate}, columns={})
            for rate in missing_rates
        ]

    def test_deltas_and_contributions(self):
        # 0.20 -> 0.10 -> 0.15, so deltas are -0.10 and +0.05 and the absolute change is 0.15
        trajectory = quality_trajectory(self._metrics([0.20, 0.10, 0.15]))['missing']

        self.assertAlmostEqual(trajectory['deltas'][0], -0.10)
        self.assertAlmostEqual(trajectory['deltas'][1], 0.05)
        self.assertAlmostEqual(trajectory['contributions'][0], -2 / 3)
        self.assertAlmostEqual(trajectory['contributions'][1], 1 / 3)
        self.assertFalse(trajectory['no_change'])

    def test_a_rise_in_error_rate_is_a_positive_contribution(self):
        # q is an error rate, so higher is worse: a step that adds errors degrades quality
        trajectory = quality_trajectory(self._metrics([0.1, 0.3]))['missing']

        self.assertGreater(trajectory['contributions'][0], 0)

    def test_a_fall_in_error_rate_is_a_negative_contribution(self):
        trajectory = quality_trajectory(self._metrics([0.3, 0.1]))['missing']

        self.assertLess(trajectory['contributions'][0], 0)

    def test_flat_branch_reports_no_change_instead_of_dividing_by_zero(self):
        trajectory = quality_trajectory(self._metrics([0.2, 0.2, 0.2]))['missing']

        self.assertTrue(trajectory['no_change'])
        self.assertEqual(trajectory['contributions'], [0.0, 0.0])

    def test_single_node_has_no_deltas(self):
        trajectory = quality_trajectory(self._metrics([0.2]))['missing']

        self.assertEqual(trajectory['values'], [0.2])
        self.assertEqual(trajectory['deltas'], [])
        self.assertTrue(trajectory['no_change'])

    def test_every_dimension_is_reported(self):
        trajectory = quality_trajectory(self._metrics([0.2, 0.1]))

        for dimension in ('missing', 'mismatch', 'anomaly', 'incomplete'):
            self.assertIn(dimension, trajectory)


class DescendantPathsTests(unittest.TestCase):
    def _branched_graph(self):
        """
        n0a
         |
        n1b --- n2c
         |
        n3d
        """
        graph = PGraph()
        graph.add_root_node(GraphNode("root", "root", "n0a", "errors_n0a"))
        graph.add_node(GraphNode("n0a", "delete", "n1b", "errors_n1b"))
        graph.add_node(GraphNode("n1b", "impute", "n2c", "errors_n2c"))
        graph.add_node(GraphNode("n1b", "delete", "n3d", "errors_n3d"))
        return graph

    def test_one_path_per_leaf(self):
        paths = self._branched_graph().descendant_paths("n0a")

        self.assertEqual(
            sorted(paths),
            [["n0a", "n1b", "n2c"], ["n0a", "n1b", "n3d"]],
        )

    def test_leaf_returns_a_single_one_element_path(self):
        self.assertEqual(self._branched_graph().descendant_paths("n2c"), [["n2c"]])

    def test_unknown_node_returns_nothing(self):
        self.assertEqual(self._branched_graph().descendant_paths("nope"), [])


class NodeIdTests(unittest.TestCase):
    def test_ids_advance_through_letters_then_digits(self):
        self.assertEqual(node_id_for_count(0), "n0a")
        self.assertEqual(node_id_for_count(25), "n0z")
        self.assertEqual(node_id_for_count(26), "n1a")
        self.assertEqual(node_id_for_count(259), "n9z")

    def test_ids_are_always_three_characters(self):
        self.assertTrue(all(len(node_id_for_count(n)) == 3 for n in range(260)))

    def test_ids_are_unique(self):
        self.assertEqual(len({node_id_for_count(n) for n in range(260)}), 260)

    def test_running_out_of_ids_raises(self):
        with self.assertRaises(ValueError):
            node_id_for_count(260)


class TableNamingTests(unittest.TestCase):
    def setUp(self):
        self.previous_pgraph = getattr(app, "pgraph_for_session", None)
        app.pgraph_for_session = PGraph()
        app.pgraph_for_session.add_root_node(
            GraphNode("root", "root", "n0a_adult_x7f2q", "errors_n0a_adult_x7f2q")
        )

    def tearDown(self):
        app.pgraph_for_session = self.previous_pgraph

    def test_parse_node_id(self):
        self.assertEqual(_parse_node_id("n0c_adult_x7f2q"), ("0c", "adult_x7f2q"))
        self.assertIsNone(_parse_node_id("adult_x7f2q"))

    def test_base_name_survives_past_the_tenth_node(self):
        """The old positional slice assumed a two-character prefix and corrupted names from n10 on."""
        table_name = "n0a_adult_x7f2q"

        for _ in range(15):
            table_name = make_new_table_name(table_name)
            app.pgraph_for_session.add_node(
                GraphNode("parent", "delete", table_name, f"errors_{table_name}")
            )

            self.assertTrue(table_name.endswith("_adult_x7f2q"), table_name)

        # 1 root + 15 children, so the last id minted is the sixteenth
        self.assertEqual(table_name, "n0p_adult_x7f2q")


if __name__ == '__main__':
    unittest.main()


class WrangleLabelTests(unittest.TestCase):
    """
    Edge labels name the operation and the column(s) it acted on. Before columns were carried through
    to node creation, every edge read just "impute" or "delete".
    """

    def test_one_d_wrangle_names_its_column(self):
        self.assertEqual(format_wrangle_label("impute", ["salary"]), "impute · salary")
        self.assertEqual(format_wrangle_label("delete", ["salary"]), "delete · salary")

    def test_two_d_delete_names_both_columns(self):
        self.assertEqual(
            format_wrangle_label("delete", ["salary", "region"]),
            "delete · salary × region",
        )

    def test_two_d_impute_names_only_the_column_it_filled(self):
        # The _x / _y suffix says which of the pair was imputed, so the label resolves it to a name
        self.assertEqual(format_wrangle_label("impute_x", ["salary", "region"]), "impute · salary")
        self.assertEqual(format_wrangle_label("impute_y", ["salary", "region"]), "impute · region")

    def test_falls_back_to_the_bare_operation_without_columns(self):
        self.assertEqual(format_wrangle_label("root", []), "root")
        self.assertEqual(format_wrangle_label("delete", None), "delete")

    def test_node_labels_itself(self):
        node = GraphNode("n0a_x", "impute_y", "n0b_x", "errors_n0b_x", ["salary", "region"])
        self.assertEqual(node.wrangle_label(), "impute · region")

    def test_root_node_has_no_columns(self):
        root = GraphNode("root", "root", "n0a_x", "errors_n0a_x")
        self.assertEqual(root.wrangle_cols, [])
        self.assertEqual(root.wrangle_label(), "root")
