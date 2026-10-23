"""
The arithmetic of the drift metric (app/pgraph/distortion.py): everything it does with the numbers DriftSQL has
already reduced the rows to, so none of it needs a database. The statistics measured from rows - W1/IQR, TVD, edit
facts, quantiles, flows - are held to their cases in tests/sql/test_drift_sql.py.
"""
import unittest

import numpy as np

from app.pgraph.distortion import (CATEGORICAL, NUMERIC, OTHER_LABEL, REMOVED_LABEL, annotation, category_flows,
                                   column_distortion, node_density, root_density_params, summarize)
from app.pgraph.pgraph import distortion_trajectory, pareto_frontier


def masses(values):
    """Values as DriftSQL.generate_value_masses gives them: each distinct number once, with how often it occurs."""
    numbers, occurrences = np.unique(np.asarray(values, dtype=float), return_counts=True)
    return {"numbers": numbers.tolist(), "occurrences": occurrences.tolist()}


def same_place(counts):
    """Flows for a node identical to root: every row stays in its category."""
    pairs = []
    for label, rows in counts.items():
        pairs.append({"source": label, "target": label, "rows": rows})
    return pairs


def tail_counts():
    """c0 holds 7 rows, c1 6, ... c6 1."""
    counts = {}
    for i in range(7):
        counts[f"c{i}"] = 7 - i
    return counts


class SummaryTests(unittest.TestCase):
    def test_numeric_columns_are_not_capped(self):
        # A shift of ten IQRs has to read worse than a shift of one, so nothing is clipped
        one = {"num": {"value": 1.0, "kind": NUMERIC, "degenerate": False},
               "cat": {"value": 0.2, "kind": CATEGORICAL, "degenerate": False}}
        ten = {**one, "num": {**one["num"], "value": 10.0}}

        self.assertAlmostEqual(summarize(one)["overall"], 0.6)
        self.assertAlmostEqual(summarize(ten)["overall"], 5.1)

    def test_weights(self):
        columns = {"num": {"value": 3.0, "kind": NUMERIC, "degenerate": False},
                   "cat": {"value": 0.2, "kind": CATEGORICAL, "degenerate": False}}

        self.assertAlmostEqual(summarize(columns, weights={"num": 3})["overall"], 2.3)

    def test_columns_without_a_value_are_left_out_not_counted_as_zero(self):
        columns = {"a": {"value": 0.4, "kind": CATEGORICAL, "degenerate": False},
                   "b": {"value": None, "kind": CATEGORICAL, "degenerate": True}}

        self.assertAlmostEqual(summarize(columns)["overall"], 0.4)

    def test_nothing_scored_has_no_overall(self):
        self.assertIsNone(summarize({})["overall"])

    def test_a_column_is_scored_from_its_measurements(self):
        measured = {"n_reference": 40, "n_node": 40, "wasserstein": 1.0, "q1": 1.0, "q3": 3.0, "std": 1.5}

        result = column_distortion(measured, NUMERIC)

        self.assertAlmostEqual(result["value"], 0.5)
        self.assertFalse(result["low_confidence"])


class DensityTests(unittest.TestCase):
    def test_root_through_its_own_fit_lies_on_its_own_curve(self):
        root = masses(np.random.default_rng(1).normal(50, 10, 500))
        params = root_density_params(root)

        np.testing.assert_allclose(node_density(root, params), params["root_curve"])

    def test_a_node_that_lost_half_its_rows_keeps_half_the_area(self):
        values = np.random.default_rng(2).normal(0, 1, 1000)
        params = root_density_params(masses(values))

        curve = np.asarray(node_density(masses(values[::2]), params))

        self.assertAlmostEqual(np.trapezoid(curve, params["grid"]), 0.5, delta=0.02)

    def test_a_node_of_one_repeated_value_still_draws(self):
        params = root_density_params(masses([1.0, 2.0, 3.0, 4.0]))

        self.assertIsNotNone(node_density(masses([2.0, 2.0, 2.0]), params))

    def test_a_constant_root_cannot_be_smoothed(self):
        self.assertIsNone(root_density_params(masses([5.0, 5.0, 5.0])))

    def test_repeated_values_smooth_as_if_every_row_were_listed(self):
        # The masses carry each value once with its count, which has to sum to the same curve as listing every row
        rows = [1.0, 1.0, 1.0, 2.0, 5.0, 5.0]
        params = root_density_params(masses(rows))
        bandwidth = params["bandwidth"]

        grid = np.asarray(params["grid"])
        by_row = np.zeros(len(grid))
        for value in rows:
            by_row += np.exp(-0.5 * ((grid - value) / bandwidth) ** 2) / (bandwidth * np.sqrt(2 * np.pi))

        np.testing.assert_allclose(params["root_curve"], by_row / len(rows))
        self.assertAlmostEqual(bandwidth, 0.30 * np.std(rows, ddof=1))


class FlowFoldingTests(unittest.TestCase):
    def test_the_long_tail_folds_into_other(self):
        flows = category_flows(same_place(tail_counts()), limit=6)

        self.assertEqual(flows["sources"], ["c0", "c1", "c2", "c3", "c4", OTHER_LABEL])
        self.assertEqual(flows["categories"], 7)

    def test_a_column_within_the_limit_keeps_every_category(self):
        flows = category_flows(same_place(tail_counts()), limit=7)

        self.assertEqual(flows["sources"], [f"c{i}" for i in range(7)])

    def test_null_is_kept_when_the_tail_folds(self):
        counts = {}
        for i in range(7):
            counts[f"c{i}"] = 8 - i
        counts["null"] = 1

        flows = category_flows(same_place(counts), limit=6)

        self.assertEqual(flows["sources"], ["c0", "c1", "c2", "c3", "null", OTHER_LABEL])

    def test_the_catch_all_names_what_it_holds(self):
        other = category_flows(same_place(tail_counts()), limit=4)["other"]

        # c3 down, biggest first, with the rows each one took into the catch-all
        self.assertEqual(other["categories"], [{"category": "c3", "rows": 4}, {"category": "c4", "rows": 3},
                                               {"category": "c5", "rows": 2}, {"category": "c6", "rows": 1}])
        self.assertEqual(other["rows"], 10)
        self.assertEqual(other["more"], 0)

    def test_named_categories_are_kept_whatever_their_size(self):
        flows = category_flows(same_place(tail_counts()), keep=["c0", "c6"])

        self.assertEqual(flows["sources"], ["c0", "c6", OTHER_LABEL])
        self.assertEqual([row["category"] for row in flows["other"]["categories"]], ["c1", "c2", "c3", "c4", "c5"])

    def test_nothing_folded_means_no_catch_all_to_look_into(self):
        self.assertIsNone(category_flows(same_place({"a": 2, "b": 1}))["other"])

    def test_removed_rows_set_each_categorys_removal_rate(self):
        pairs = [{"source": "a", "target": "a", "rows": 2}, {"source": "b", "target": REMOVED_LABEL, "rows": 1}]

        flows = category_flows(pairs)

        self.assertEqual(flows["targets"][-1], REMOVED_LABEL)
        self.assertEqual(flows["removal_rates"], {"a": 0.0, "b": 1.0})
        self.assertAlmostEqual(flows["churn"], 1 / 3)


class AcrossNodesTests(unittest.TestCase):
    def test_doc_02_pareto_table(self):
        scores = [{"id": node_id, "error": error, "distortion": distortion} for node_id, error, distortion in [
            ("n0", 1.0714, 0.0000), ("n1", 0.1146, 0.1224), ("n2", 0.8571, 0.0035), ("n3", 0.8571, 0.0028),
            ("n4", 0.8571, 0.0024), ("n5", 0.7500, 0.0028), ("n6", 0.7857, 0.0031), ("n7", 0.0386, 0.1227),
        ]]

        frontier, dominated = pareto_frontier(scores)

        self.assertEqual(set(frontier), {"n0", "n1", "n4", "n5", "n7"})
        # 02 lists n3 -> n5; n4 dominates n3 too, and the tie-break names the lowest id
        self.assertEqual(dominated, {"n2": "n3", "n3": "n4", "n6": "n5"})

    def test_float_noise_does_not_make_equal_nodes_dominate(self):
        frontier, dominated = pareto_frontier([{"id": "a", "error": 0.1, "distortion": 0.2},
                                               {"id": "b", "error": 0.1 + 1e-12, "distortion": 0.2}])

        self.assertEqual(dominated, {})
        self.assertEqual(frontier, ["a", "b"])

    def test_trajectory_deltas_are_differences_of_root_referenced_values(self):
        trajectory = distortion_trajectory([{"overall": 0.0}, {"overall": 0.1}, {"overall": 0.05}])

        self.assertEqual(trajectory["values"], [0.0, 0.1, 0.05])
        np.testing.assert_allclose(trajectory["deltas"], [0.1, -0.05])


class AnnotationTests(unittest.TestCase):
    def test_a_collateral_column_is_described_by_facts_alone(self):
        result = {"kind": CATEGORICAL, "stat": "TVD", "value": 0.0105}
        facts = {"rows_root": 400, "rows_removed": 26, "cells_changed": {"Gender": 0}}
        flows = {"churn": 0.065, "removal_rates": {"Male": 0.055, "Female": 0.133}}

        sentences = annotation("Gender", result, facts, acted_on=False, flows=flows)["sentences"]
        text = " ".join(sentences)

        self.assertIn("26 of 400 rows were removed.", sentences)
        self.assertIn("No operation acted on Gender", text)
        self.assertIn("Female rows were removed at 13.3%, against 5.5% of Male.", sentences)
        self.assertNotIn("because", text)


if __name__ == "__main__":
    unittest.main()
