import unittest

import numpy as np
import pandas as pd

from app.pgraph.distortion import (CATEGORICAL, NUMERIC, OTHER_LABEL, REMOVED_LABEL, RowIdentityError,
                                   annotation, category_flows, column_detail, column_distortion,
                                   detail_route, distortion_trajectory, edit_facts, node_density,
                                   node_distortion, null_applicability, null_distribution, null_result,
                                   pareto_frontier, root_density_params, root_distortion, summarize)


def numeric(values):
    return pd.Series(values, dtype=object)


def labels(values):
    return pd.Series(values, dtype=object)


class NumericDistortionTests(unittest.TestCase):
    def test_identical_column_scores_zero(self):
        values = numeric([1.0, 2.0, 3.0, 4.0, 5.0])

        self.assertEqual(column_distortion(values, values.copy(), NUMERIC)["value"], 0.0)

    def test_shift_is_measured_in_root_iqrs(self):
        # Root's IQR is 3 - 1 = 2, and every value moved up by 1
        result = column_distortion(numeric([0, 1, 2, 3, 4]), numeric([1, 2, 3, 4, 5]), NUMERIC)

        self.assertAlmostEqual(result["value"], 0.5)
        self.assertEqual(result["stat"], "W1/IQR")

    def test_unequal_sizes(self):
        # Worked by hand over the two quantile functions, which step at fifths and at thirds: W1 = 1
        result = column_distortion(numeric([0, 1, 2, 3, 4]), numeric([0, 1, 2]), NUMERIC)

        self.assertAlmostEqual(result["value"], 0.5)

    def test_nulls_are_left_out_and_imputation_registers(self):
        root = numeric([1, 2, 3, 4, None])

        self.assertEqual(column_distortion(root, root.copy(), NUMERIC)["value"], 0.0)
        self.assertGreater(column_distortion(root, numeric([1, 2, 3, 4, 2.5]), NUMERIC)["value"], 0.0)

    def test_text_in_a_numeric_column_is_ignored(self):
        root = numeric([1, 2, 3, 4, "oops"])

        self.assertEqual(column_distortion(root, root.copy(), NUMERIC)["value"], 0.0)

    def test_no_iqr_falls_back_to_the_standard_deviation(self):
        # The middle half is all 5s; the standard deviation is sqrt(12.5)
        result = column_distortion(numeric([0, 5, 5, 5, 10]), numeric([1, 6, 6, 6, 11]), NUMERIC)

        self.assertAlmostEqual(result["value"], 1 / np.sqrt(12.5))

    def test_constant_column_has_no_value_rather_than_zero(self):
        result = column_distortion(numeric([5, 5, 5]), numeric([5, 5]), NUMERIC)

        self.assertTrue(result["degenerate"])
        self.assertIsNone(result["value"])
        self.assertEqual(result["reason"], "constant column")

    def test_an_emptied_column_has_no_value_rather_than_zero(self):
        result = column_distortion(numeric([1, 2, 3]), numeric([None, None]), NUMERIC)

        self.assertIsNone(result["value"])
        self.assertEqual(result["reason"], "no values")

    def test_small_columns_are_low_confidence(self):
        self.assertTrue(column_distortion(numeric([1, 2, 3]), numeric([1, 2]), NUMERIC)["low_confidence"])
        big = numeric(list(range(40)))
        self.assertFalse(column_distortion(big, big.copy(), NUMERIC)["low_confidence"])


class CategoricalDistortionTests(unittest.TestCase):
    def test_identical_column_scores_zero(self):
        values = labels(["a", "b", "b"])

        self.assertEqual(column_distortion(values, values.copy(), CATEGORICAL)["value"], 0.0)

    def test_disjoint_columns_score_one(self):
        result = column_distortion(labels(["a", "a", "b"]), labels(["c", "d"]), CATEGORICAL)

        self.assertAlmostEqual(result["value"], 1.0)
        self.assertEqual(result["stat"], "TVD")

    def test_moved_mass_is_counted_once(self):
        # a goes from half to three quarters and b the other way: 0.25 of the mass moved, not 0.5
        result = column_distortion(labels(["a", "a", "b", "b"]), labels(["a", "a", "a", "b"]), CATEGORICAL)

        self.assertAlmostEqual(result["value"], 0.25)

    def test_missing_cells_are_left_out_on_both_sides(self):
        # A node identical to root scores zero even though root has missing cells
        values = labels(["a", "b", None, "null", "undefined"])

        self.assertEqual(column_distortion(values, values.copy(), CATEGORICAL)["value"], 0.0)

    def test_imputation_registers(self):
        # Root's clean values are half a, half b; filling both gaps with a makes a three quarters
        result = column_distortion(labels(["a", "b", None, None]), labels(["a", "b", "a", "a"]), CATEGORICAL)

        self.assertAlmostEqual(result["value"], 0.25)


def frame(rows):
    return pd.DataFrame(rows)


ROOT = frame({"ID": [1, 2, 3, 4, 5, 6], "num": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "cat": list("aabbcc")})
KINDS = {"num": NUMERIC, "cat": CATEGORICAL}


class NodeDistortionTests(unittest.TestCase):
    def test_node_identical_to_root_scores_zero_everywhere(self):
        result = node_distortion(ROOT, ROOT.copy(), KINDS)

        self.assertEqual(result["overall"], 0.0)
        self.assertEqual({column: r["value"] for column, r in result["columns"].items()}, {"num": 0.0, "cat": 0.0})

    def test_root_short_circuits_to_zero(self):
        result = root_distortion(ROOT, KINDS)

        self.assertEqual(result["overall"], 0.0)
        self.assertFalse(any(r["degenerate"] for r in result["columns"].values()))

    def test_a_row_root_does_not_have_raises(self):
        grown = pd.concat([ROOT, frame({"ID": [7], "num": [7.0], "cat": ["c"]})])

        with self.assertRaises(RowIdentityError):
            node_distortion(ROOT, grown, KINDS)

    def test_dropped_and_added_columns_are_structural_not_scored(self):
        node = ROOT.drop(columns="cat").assign(extra=1)
        result = node_distortion(ROOT, node, KINDS)

        self.assertEqual(result["columns"]["cat"]["reason"], "column removed")
        self.assertEqual(result["columns"]["extra"]["reason"], "column added")
        self.assertEqual(result["structural"], {"removed": ["cat"], "added": ["extra"]})
        self.assertEqual(result["overall"], result["columns"]["num"]["value"])

    def test_row_identifiers_are_not_scored(self):
        result = node_distortion(ROOT.assign(index=range(6)), ROOT.assign(index=range(6)), KINDS)

        self.assertNotIn("index", result["columns"])
        self.assertNotIn("ID", result["columns"])

    def test_numeric_columns_are_capped(self):
        columns = {"num": {"value": 3.0, "kind": NUMERIC, "degenerate": False},
                   "cat": {"value": 0.2, "kind": CATEGORICAL, "degenerate": False}}

        result = summarize(columns)

        self.assertAlmostEqual(result["overall"], 0.6)
        self.assertEqual(result["capped"], ["num"])

    def test_weights(self):
        columns = {"num": {"value": 3.0, "kind": NUMERIC, "degenerate": False},
                   "cat": {"value": 0.2, "kind": CATEGORICAL, "degenerate": False}}

        self.assertAlmostEqual(summarize(columns, weights={"num": 3})["overall"], 0.8)

    def test_columns_without_a_value_are_left_out_not_counted_as_zero(self):
        columns = {"a": {"value": 0.4, "kind": CATEGORICAL, "degenerate": False},
                   "b": {"value": None, "kind": CATEGORICAL, "degenerate": True}}

        self.assertAlmostEqual(summarize(columns)["overall"], 0.4)

    def test_nothing_scored_has_no_overall(self):
        self.assertIsNone(summarize({})["overall"])

    def test_edit_facts_count_removed_rows_and_changed_cells(self):
        node = ROOT[ROOT["ID"] != 6].copy()
        node.loc[node["ID"] == 1, "cat"] = "b"

        facts = edit_facts(ROOT, node, KINDS)

        self.assertEqual(facts["rows_root"], 6)
        self.assertEqual(facts["rows_removed"], 1)
        self.assertEqual(facts["cells_changed"], {"num": 0, "cat": 1})


class DetailTests(unittest.TestCase):
    def test_shift_is_read_on_the_grid_in_root_iqrs(self):
        root = numeric(list(range(101)))
        detail = column_detail(root, numeric([value + 10 for value in range(101)]), NUMERIC)

        # Root's IQR is 50, and every quantile moved up by 10
        np.testing.assert_allclose(detail["shift"], [0.2] * len(detail["grid"]))

    def test_mean_shift_on_a_fine_grid_matches_the_number(self):
        rng = np.random.default_rng(0)
        root = pd.Series(rng.normal(0, 1, 2000))
        node = root * 1.1 + 0.2
        fine = tuple(np.linspace(0.001, 0.999, 999))

        detail = column_detail(root, node, NUMERIC, grid=fine)
        value = column_distortion(root, node, NUMERIC)["value"]

        self.assertAlmostEqual(np.mean(np.abs(detail["shift"])), value, delta=0.1 * value)

    def test_categories_that_moved_most_are_named_and_the_rest_summed(self):
        root = labels([f"c{i}" for i in range(10) for _ in range(10)])
        node = labels([f"c{i}" for i in range(10) for _ in range(10 + i)])

        detail = column_detail(root, node, CATEGORICAL)
        rows = detail["categories"]

        self.assertEqual(len(rows), 9)
        self.assertEqual(detail["truncated_n"], 2)
        self.assertEqual(rows[-1]["category"], OTHER_LABEL)
        self.assertEqual(rows[0]["category"], "c0")
        # Shares always sum to 100, so the changes sum to zero across every row, the summed one included
        self.assertAlmostEqual(sum(row["change_pct"] for row in rows), 0.0)

    def test_root_through_its_own_fit_lies_on_its_own_curve(self):
        root = pd.Series(np.random.default_rng(1).normal(50, 10, 500))
        params = root_density_params(root)

        np.testing.assert_allclose(node_density(root, params), params["root_curve"])

    def test_a_node_that_lost_half_its_rows_keeps_half_the_area(self):
        root = pd.Series(np.random.default_rng(2).normal(0, 1, 1000))
        params = root_density_params(root)

        curve = np.asarray(node_density(root.iloc[::2], params))

        self.assertAlmostEqual(np.trapezoid(curve, params["grid"]), 0.5, delta=0.02)

    def test_a_node_of_one_repeated_value_still_draws(self):
        params = root_density_params(pd.Series([1.0, 2.0, 3.0, 4.0]))

        self.assertIsNotNone(node_density(pd.Series([2.0, 2.0, 2.0]), params))


class NullTests(unittest.TestCase):
    def test_draws_are_seeded_and_shared(self):
        values = labels(["a"] * 50 + ["b"] * 50)

        first = null_distribution(("t", "seeded"), values, CATEGORICAL, 80, draws=50, seed=1)
        again = null_distribution(("t", "seeded"), values, CATEGORICAL, 80, draws=50, seed=1)

        self.assertIs(first, again)
        self.assertEqual(len(first), 50)

    def test_deleting_one_category_selectively_is_flagged(self):
        root = labels(["a"] * 50 + ["b"] * 50)
        node = root.iloc[:80]
        observed = column_distortion(root, node, CATEGORICAL)["value"]

        result = null_result(("t", "selective"), root, CATEGORICAL, len(node), observed)

        self.assertTrue(result["flagged"])
        self.assertGreater(result["percentile"], 95)

    def test_deleting_evenly_is_not_flagged(self):
        root = labels(["a", "b"] * 50)
        node = root.iloc[20:]
        observed = column_distortion(root, node, CATEGORICAL)["value"]

        result = null_result(("t", "even"), root, CATEGORICAL, len(node), observed)

        self.assertFalse(result["flagged"])

    def test_deleting_a_numeric_tail_is_flagged(self):
        root = numeric([float(value) for value in range(100)])
        node = root.iloc[:80]
        observed = column_distortion(root, node, NUMERIC)["value"]

        self.assertTrue(null_result(("t", "tail"), root, NUMERIC, len(node), observed)["flagged"])

    def test_applies_only_to_rows_leaving_a_column_no_one_edited(self):
        scored = {"degenerate": False, "reason": None}
        removed = {"rows_removed": 3, "cells_changed": {"a": 0, "b": 2}}

        self.assertEqual(null_applicability(removed, "a", scored), (True, None))
        self.assertEqual(null_applicability(removed, "b", scored), (False, "values edited in place"))
        self.assertEqual(null_applicability({"rows_removed": 0, "cells_changed": {}}, "a", scored),
                         (False, "no rows removed"))
        self.assertEqual(null_applicability(removed, "a", {"degenerate": True, "reason": "no values"}),
                         (False, "no values"))

    def test_an_untested_column_carries_no_percentile(self):
        result = null_result(("t", "untested"), labels(["a"]), CATEGORICAL, 1, 0.0,
                             applicable=False, reason="no rows removed")

        self.assertIsNone(result["percentile"])
        self.assertFalse(result["flagged"])


class FlowTests(unittest.TestCase):
    def test_a_swap_leaves_tvd_at_zero_but_churn_counts_it(self):
        root = frame({"ID": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]})
        node = frame({"ID": [1, 2, 3, 4], "g": ["b", "a", "a", "b"]})

        self.assertEqual(column_distortion(root["g"], node["g"], CATEGORICAL)["value"], 0.0)
        self.assertAlmostEqual(category_flows(root, node, "g")["churn"], 0.5)

    def test_deleted_rows_go_to_the_removed_sink(self):
        root = frame({"ID": [1, 2, 3], "g": ["a", "a", "b"]})
        node = frame({"ID": [1, 2], "g": ["a", "a"]})

        flows = category_flows(root, node, "g")

        self.assertIn({"source": "b", "target": REMOVED_LABEL, "rows": 1}, flows["flows"])
        self.assertEqual(flows["targets"][-1], REMOVED_LABEL)
        self.assertEqual(flows["removal_rates"], {"a": 0.0, "b": 1.0})
        self.assertAlmostEqual(flows["churn"], 1 / 3)

    def test_the_long_tail_folds_into_other(self):
        values = [f"c{i}" for i in range(7) for _ in range(7 - i)]
        root = frame({"ID": list(range(len(values))), "g": values})

        flows = category_flows(root, root.copy(), "g", top=5)

        self.assertEqual(flows["sources"], ["c0", "c1", "c2", "c3", "c4", OTHER_LABEL])
        self.assertEqual(flows["categories"], 7)

    def test_the_view_opened_first_follows_what_happened_to_the_column(self):
        self.assertEqual(detail_route(0, 0, 3), "change")    # drifted only through other columns' deletes
        self.assertEqual(detail_route(2, 0, 3), "flows")     # recoded cells
        self.assertEqual(detail_route(0, 5, 3), "flows")     # rows deleted by a step on this column
        self.assertEqual(detail_route(2, 0, 20), "change")   # too many categories for ribbons


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
        null = {"applicable": True, "flagged": True, "percentile": 98.6}
        flows = {"churn": 0.065, "removal_rates": {"Male": 0.055, "Female": 0.133}}

        sentences = annotation("Gender", result, facts, null=null, acted_on=False, flows=flows)["sentences"]
        text = " ".join(sentences)

        self.assertIn("26 of 400 rows were removed.", sentences)
        self.assertIn("No operation acted on Gender", text)
        self.assertIn("Female rows were removed at 13.3%, against 5.5% of Male.", sentences)
        self.assertIn("Drift exceeds 99% of random deletions of the same size.", sentences)
        self.assertNotIn("because", text)


if __name__ == "__main__":
    unittest.main()
